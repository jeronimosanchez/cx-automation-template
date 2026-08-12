#!/usr/bin/env python3
"""
act/server_cloudrun.py — Servidor Flask que expone el pipeline por HTTP.

Es un **adaptador**, no un segundo pipeline: cada endpoint traduce una petición
HTTP en una llamada a una función de `act_cx_resources_deploy_cloudrun.py` y
devuelve su resultado tal cual. Toda la lógica vive allí, y por eso el pipeline
sigue funcionando por CLI sin este servidor. Si un endpoint decidiera algo por
su cuenta habría dos fuentes de verdad que pueden divergir sin que nada avise.

Nueve puntos de entrada, y solo esos:

    POST /step/1            Inventario
    POST /step/2            Traer al repositorio
    POST /step/3            Aplicar en CX
    POST /step/4            Validar tests
    POST /step/5            Publicar
    GET  /discover          Proyectos y agentes para los desplegables
    POST /register-agent    Alta de un agente (el botón del Paso 1, S24)
    POST /link-project-repo Vincular proyecto y repositorio (la Tool, S22)
    POST /manage-versions   Listar y borrar versiones

Más dos rutas que no son del pipeline y no reciben destino: `GET /` y
`GET /panel`, que sirven el propio panel desde este mismo origen (S25,
`docs/cloudrun_diseno_servidor.md §16`). No es una pieza nueva: es lo que hace
que el panel llame a `/step/1` sin URL que configurar y que CORS deje de
existir en vez de gestionarse.

El playbook los cuenta como «ocho» porque la segunda ronda de decisiones (S24,
2026-08-08) partió el onboarding en dos —vincular el proyecto una vez, y dar de
alta cada agente— después de escribirse esa cifra. El pipeline ya nació partido:
`link_project_repo` y `register_agent` son dos funciones con firmas distintas,
así que fundirlas en un endpoint exigiría lógica de reparto dentro del propio
endpoint, que es justo lo que la fase prohíbe.

Hay además un `GET /health`, que no es un noveno endpoint del pipeline: no
recibe destino, no toca CX, Firestore ni GitHub, y no dice nada de ningún
agente. Existe porque «arrancó pero no responde» tiene que poder distinguirse
de «no arrancó», y sin nada que consultar esa diferencia no se puede observar.

Los cuatro pasos largos —`/step/1`, `/step/2`, `/step/3` y `/step/5`— pueden
además emitir su registro **según ocurre**, si quien llama lo pide con
`Accept: text/event-stream`. No es un endpoint más ni cambia el contrato: el
sobre `{status, log, data}` sigue llegando entero, dentro del evento que marca
el final. Ver `_respuesta_en_flujo`.

Tres cosas separan esto del servidor local que sustituye (`act/server.py`,
retirado):

1. **Autenticación hacia CX por ADC**, no por la sesión de `gcloud` de nadie.
   En Cloud Run no hay sesión humana interactiva. Es la excepción documentada a
   la regla de `CLAUDE.md §3.1`, y aplica solo a este servidor.

2. **El repositorio se lee y se escribe por la GitHub App**, no desde un árbol
   de git en disco: en el contenedor no hay repositorio ni binario de git.

3. **El candado de concurrencia vive en Firestore**, no en un `threading.Lock`.
   Una instancia de Cloud Run con concurrencia 1 **encola** las peticiones en
   vez de rechazarlas, y un candado por proceso no protege nada en cuanto hay
   más de una instancia.

Arranque:
    PORT=8080 FIRESTORE_PROJECT=... GITHUB_APP_ID=... \\
      GITHUB_APP_SECRET_PROJECT=... python act/server_cloudrun.py
"""

import functools
import json
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import google.api_core.exceptions
import google.auth.exceptions
from flask import Flask, Response, jsonify, redirect, request, send_file
from flask_cors import CORS

from act import act_cx_resources_deploy_cloudrun as pipeline
from act.utils import cx_client_cloudrun as cx
from act.utils import firestore_client_cloudrun as store
from act.utils import github_app_client_cloudrun as github


# ── Configuración por entorno ────────────────────────────────────────────────
#
# Nada de esto se escribe en el código. `PORT` lo inyecta Cloud Run y el
# servidor tiene que escuchar exactamente ahí: en otro puerto el health check
# de la plataforma falla y el despliegue no llega a arrancar.

PUERTO_POR_DEFECTO = 8080

# El origen permitido para CORS. En el despliegue real el panel y los endpoints
# salen de la misma URL detrás de IAP, así que no hay petición entre orígenes
# que autorizar; esta variable existe para los casos en que sí la hay —el panel
# abierto desde `file://` manda `Origin: null`, y durante la construcción se
# golpea el servidor desde fuera—. El valor por defecto es abierto porque CORS
# no es aquí la barrera de seguridad: quien la pone es IAP más
# `--no-allow-unauthenticated`, que rechazan la petición antes de que el
# navegador llegue a mirar ninguna cabecera.
ORIGEN_PERMITIDO = os.environ.get("ALLOWED_ORIGIN", "*")

# ── El panel, servido desde este mismo origen (S25) ──────────────────────────
#
# El panel no es un archivo suelto en otro sitio: sale de este servicio, por la
# misma URL que los endpoints. Con eso desaparecen dos problemas en vez de
# gestionarse — el panel llama a rutas relativas (`/step/1`, sin URL que
# configurar) y no hay petición entre orígenes que autorizar.
#
# Dos sitios posibles, en este orden, porque son dos vidas distintas del mismo
# archivo: dentro de la imagen lo copia el `Dockerfile` a `/app/panel/`, y en el
# Mac se sirve directamente el del repositorio para poder iterar sin reconstruir
# la imagen en cada cambio. `PANEL_PATH` gana a los dos, para el caso de servir
# una copia concreta sin moverla de sitio.
PANEL_ARCHIVO = "act_cx_resources_deploy_v2_output_cloudrun.html"
PANEL_EN_LA_IMAGEN = REPO_ROOT / "panel" / PANEL_ARCHIVO
PANEL_EN_EL_REPOSITORIO = REPO_ROOT / "docs" / "panels" / PANEL_ARCHIVO


def ruta_del_panel():
    """El archivo del panel que toca servir, o `None` si no hay ninguno.

    Devolver `None` en vez de reventar es lo que permite que la falta del panel
    se conteste con un 404 explicado: una imagen construida sin él sigue
    sirviendo la API, y el error dice exactamente qué falta y dónde se buscó.
    """
    explicita = os.environ.get("PANEL_PATH")
    candidatas = ([Path(explicita)] if explicita else []) + [
        PANEL_EN_LA_IMAGEN, PANEL_EN_EL_REPOSITORIO,
    ]
    return next((c for c in candidatas if c.is_file()), None)


# ── Destinos que este servidor no acepta ─────────────────────────────────────
#
# Guarda de la fase de construcción, no una regla del producto. Mientras se
# construyen y validan las Fases 5 a 8, el servidor se golpea con peticiones
# generadas por scripts y por un panel a medio conectar, y basta un id copiado
# de un ejemplo para escribir en el agente real de una floristería que está en
# producción. Ya ocurrió dos veces en este repositorio: hay dos agentes de
# prueba creados dentro del proyecto real, con sus documentos de Firestore sin
# limpiar.
#
# Una lista en código para sola; una instrucción depende de que alguien se
# acuerde a las cuatro horas. **Retirarla es una decisión consciente de Jero**,
# el día que este servidor pase a ser el camino real a producción de Petal —
# hasta entonces, que un destino real no se pueda alcanzar por accidente vale
# más que la generalidad.
PROYECTOS_PROHIBIDOS = frozenset({"floristeria-petal-digital"})
AGENTES_PROHIBIDOS = frozenset({
    "745375ba-ac7e-4eb8-b8a0-d742891f2aa4",   # Petal 1.0
    "cea66b60-192d-4b5a-af10-28f8661032e0",   # Petal 1.1
})


class SolicitudInvalida(ValueError):
    """El cuerpo de la petición no sirve: falta algo o tiene la forma que no es."""


class DestinoProhibido(RuntimeError):
    """La petición apunta a un proyecto o agente que este servidor no atiende."""


app = Flask(__name__)

# `flask_cors` añade además el manejo del preflight `OPTIONS`. Sin él, un panel
# servido desde otro origen ve bloqueada la petición real antes de emitirla,
# aunque la respuesta del POST llevara la cabecera correcta — y el fallo solo
# se ve abriendo la consola del navegador, nunca en el log del servidor.
CORS(app, origins=[o.strip() for o in ORIGEN_PERMITIDO.split(",") if o.strip()])


# ── Lectura de la petición ───────────────────────────────────────────────────

def _cuerpo():
    """El body como diccionario, o un error claro si no lo es.

    `force=True` para no rechazar por la cabecera `Content-Type`: un cliente que
    manda JSON válido sin declararlo se entiende igual. Lo que sí se distingue
    es el body vacío —que es un diccionario vacío legítimo— del body con
    contenido que no se puede parsear, que es un 400 con su motivo y nunca un
    500 con la traza dentro.
    """
    crudo = request.get_data()
    if not crudo:
        return {}
    cuerpo = request.get_json(silent=True, force=True)
    if cuerpo is None:
        raise SolicitudInvalida(
            "El cuerpo de la petición no es JSON válido. Manda un objeto JSON "
            "con los datos del paso."
        )
    if not isinstance(cuerpo, dict):
        raise SolicitudInvalida(
            f"El cuerpo tiene que ser un objeto JSON, no {type(cuerpo).__name__}."
        )
    return cuerpo


def _exigir(cuerpo, *campos):
    """Los campos obligatorios de una petición, o 400 diciendo cuáles faltan.

    Nunca hay valor por defecto. El servidor no guarda estado entre peticiones,
    así que rellenar un destino ausente significaría adivinarlo — y operar sobre
    el agente equivocado sin que nadie lo note.
    """
    faltan = [campo for campo in campos if not cuerpo.get(campo)]
    if faltan:
        raise SolicitudInvalida(
            f"Falta {' y '.join(faltan)} en el cuerpo de la petición. El "
            f"servidor no aplica ningún valor por defecto: cada llamada trae "
            f"su propio destino o se rechaza."
        )
    return [cuerpo[campo] for campo in campos]


def _comprobar_destino(project, agent_id=None):
    """Rechaza los destinos prohibidos antes de emitir ninguna llamada.

    Antes de cualquier cosa: antes de construir el contexto, antes de leer
    Firestore y antes de tocar la API. Una guarda que se comprueba después de
    la primera llamada ya llega tarde para las lecturas.
    """
    if project in PROYECTOS_PROHIBIDOS or agent_id in AGENTES_PROHIBIDOS:
        raise DestinoProhibido(
            f"Este servidor no atiende el destino {project}/{agent_id or '—'}: "
            f"está en la lista de destinos protegidos mientras se construye y "
            f"valida el pipeline. No se ha emitido ninguna llamada."
        )


def _lista(cuerpo, campo, por_defecto=None):
    """Un campo del body que tiene que ser una lista, si viene.

    Sin esta comprobación, mandar una cadena donde se espera una lista no falla:
    el pipeline la recorre carácter a carácter y el error que sale después no
    menciona el campo que estaba mal.
    """
    valor = cuerpo.get(campo, por_defecto)
    if valor is None:
        return por_defecto
    if not isinstance(valor, list):
        raise SolicitudInvalida(
            f"'{campo}' tiene que ser una lista, no {type(valor).__name__}."
        )
    return valor


def _registrar(linea):
    """Cada línea del paso, al log del contenedor según ocurre.

    En Cloud Run no hay terminal donde mirar el progreso: si el registro se
    construyera entero y se devolviera al final, una operación de cuarenta
    minutos no daría señal de vida hasta terminar o morir.
    """
    print(linea, flush=True)


# ── Traducción de errores ────────────────────────────────────────────────────
#
# Un solo sitio decide qué código HTTP corresponde a cada fallo, para que dos
# endpoints no contesten distinto al mismo problema. La respuesta lleva siempre
# el mismo sobre `{status, log, data}`: el panel no tiene que aprender una
# forma para el éxito y otra para el fallo.

def _traducir(error):
    """De una excepción a (mensaje, código HTTP, data)."""

    # El cuerpo de la petición no sirve. Incluye `ValueError` del propio
    # pipeline —una etiqueta de versión inválida, un resultado de tests que no
    # es 'superados' ni 'fallidos'— porque el origen es el mismo: lo que llegó.
    if isinstance(error, (SolicitudInvalida, ValueError)):
        return str(error), 400, {}

    if isinstance(error, DestinoProhibido):
        return str(error), 403, {"reason": "destino_protegido"}

    # Sin permiso de Resource Manager se puede seguir trabajando escribiendo el
    # id del proyecto a mano, así que el panel necesita distinguir este caso de
    # un fallo cualquiera en vez de quedarse con un desplegable vacío.
    if isinstance(error, cx.ProjectListPermissionError):
        return str(error), 403, {"reason": "missing_permission",
                                 "manual_entry": True}

    # El agente o el proyecto no están dados de alta. Se distingue del 403
    # porque la salida es otra: aquí falta un alta, no un permiso.
    if isinstance(error, (store.MappingNotFound, store.MappingIncomplete,
                          cx.RegionNotFound)):
        return str(error), 404, {"reason": "sin_registrar"}

    # Otra operación tiene el candado del proyecto. Es la respuesta que el panel
    # traduce en "espera a que termine", no un error que haya que investigar.
    if isinstance(error, store.LockBusy):
        return str(error), 409, {"reason": "ocupado",
                                 "expires_at": str(error.expires_at or "")}

    # Sin credenciales por defecto el servidor no puede hablar con nadie. Es una
    # configuración incompleta del propio servicio, no un fallo de quien llama,
    # y se dice con esas palabras: es el error más frecuente del primer
    # despliegue y un stacktrace crudo obliga a depurarlo a ciegas.
    #
    # Las dos familias, no solo la del cliente de CX: el cliente de Firestore
    # pide las credenciales por su cuenta, con la librería de Google, y su
    # excepción no pasa por `cx.AuthError`. Es además el primer sitio donde
    # falla el Descubrimiento —construye el cliente de Firestore antes de nada—,
    # así que sin esta rama el error más frecuente del primer despliegue llegaba
    # como un 500 sin explicación.
    if isinstance(error, (cx.AuthError,
                          google.auth.exceptions.DefaultCredentialsError)):
        return (f"Sin credenciales por defecto (ADC): {error}. En Cloud Run las "
                f"inyecta la plataforma a través de la cuenta de servicio; en "
                f"local, ejecuta `gcloud auth application-default login`."
                ), 500, {"reason": "sin_credenciales"}

    if isinstance(error, google.auth.exceptions.RefreshError):
        return (f"Las credenciales existen pero no se pueden refrescar: {error}. "
                f"Vuelve a autenticarte o revisa la cuenta de servicio del "
                f"servicio."), 500, {"reason": "sin_credenciales"}

    # Firestore y el resto de librerías de Google traen su propio código de
    # estado. Se respeta el que ya viene en vez de traducirlo a un 500 genérico:
    # un 403 de Firestore significa que a la cuenta de servicio le falta un rol,
    # y decirlo así es la diferencia entre pedir el permiso y depurar a ciegas.
    if isinstance(error, google.api_core.exceptions.GoogleAPICallError):
        codigo = getattr(error, "code", None)
        return str(error), codigo if codigo in (403, 404, 409) else 502, {}

    if isinstance(error, (cx.ApiError, github.GitHubError)):
        codigo = getattr(error, "status_code", None)
        return str(error), codigo if codigo in (403, 404) else 502, {}

    if isinstance(error, cx.OperationTimeout):
        return str(error), 504, {"reason": "operacion_sin_terminar"}

    if isinstance(error, github.TreeTruncated):
        return str(error), 502, {}

    # El pipeline paró y sabe por qué. Es un 400 y no un 500 porque siempre
    # describe algo de la petición o del estado del destino que quien llama
    # puede corregir — nunca un fallo interno sin explicación.
    if isinstance(error, pipeline.PipelineError):
        return str(error), 400, {}

    # Lo que no se esperaba. La traza va al log del contenedor, nunca a la
    # respuesta: quien llama recibe algo legible y quien opera tiene el detalle.
    traceback.print_exc()
    return (f"Fallo interno del servidor: {type(error).__name__}. El detalle "
            f"está en el log del servicio."), 500, {}


def endpoint(vista):
    """Envuelve una vista para que siempre conteste con el mismo sobre.

    La vista devuelve el resultado del pipeline tal cual —`{status, log, data}`—
    y de traducir excepciones a códigos HTTP se encarga esto. Así ningún
    endpoint tiene su propio criterio sobre qué es un 400 y qué un 500.
    """
    @functools.wraps(vista)
    def envoltura(*args, **kwargs):
        try:
            resultado = vista(*args, **kwargs)
            # Un paso que emite el registro según ocurre ya trae su propia
            # respuesta hecha —ver `_responder`—: envolverla otra vez la
            # convertiría en un JSON con un objeto de Flask dentro.
            if isinstance(resultado, Response):
                return resultado
            return jsonify(resultado), 200
        except Exception as error:           # noqa: BLE001 — se traduce, no se traga
            mensaje, codigo, datos = _traducir(error)
            _registrar(f"✗ {request.method} {request.path} → {codigo}: {mensaje}")
            return jsonify(pipeline.step_result("error", [mensaje], datos)), codigo
    return envoltura


# ── El registro según ocurre ─────────────────────────────────────────────────
#
# Los pasos largos tardan minutos y el pipeline ya emite cada línea en el
# momento en que ocurre, por el `on_log` que reciben todas sus funciones. Lo
# que faltaba era el transporte: el servidor las acumulaba y las mandaba de
# golpe al terminar, así que el panel solo podía contar segundos. Este canal
# las lleva según salen.
#
# **Es un canal añadido, no un cambio de contrato.** El sobre sigue siendo
# `{status, log, data}` con el registro entero dentro; quien no pida el flujo
# —`curl`, un cliente viejo, el propio panel para el plan en dry-run— recibe
# exactamente lo de siempre.
#
# **Negociado por la cabecera `Accept`**, no por un parámetro de la URL ni por
# una ruta paralela. Tres razones, en orden de peso:
#
#   1. Los nueve puntos de entrada siguen siendo nueve. Una ruta gemela por
#      paso duplicaría la superficie que el panel, `/health` y los validadores
#      enumeran, y con ella la posibilidad de que las dos versiones de un mismo
#      paso dejen de hacer lo mismo.
#   2. Es exactamente para lo que existe `Accept`: la operación es la misma y
#      lo que cambia es la representación de la respuesta.
#   3. Un parámetro en la URL viaja en la dirección, y la dirección se copia,
#      se cachea y se comparte. La forma de la respuesta no debería depender de
#      algo que se pega en un chat.
#
# **Y Server-Sent Events, no NDJSON.** SSE tiene eventos con nombre, que es lo
# que permite distinguir «una línea más» de «terminado» sin inspeccionar el
# contenido de cada trozo. Además su `Content-Type` es el que los proxys de
# por medio reconocen como flujo: `cloud-run-proxy`, que es como se alcanza
# este servicio desde un Mac, reenvía sin acumular en cuanto ve
# `text/event-stream`, y con cualquier otro tipo agrupa por intervalos.

TIPO_FLUJO = "text/event-stream"


def _quiere_flujo():
    """Si quien llama pidió recibir el registro según ocurre."""
    return TIPO_FLUJO in request.headers.get("Accept", "")


def _evento(nombre, datos):
    """Un evento con nombre en el formato de Server-Sent Events.

    El JSON va en una sola línea a propósito: en SSE el salto de línea separa
    campos, así que un `data:` con saltos dentro llega partido en trozos que el
    cliente no puede volver a juntar.
    """
    return f"event: {nombre}\ndata: {json.dumps(datos, ensure_ascii=False)}\n\n"


def _responder(trabajo):
    """Ejecuta el trabajo del paso y contesta — en flujo si se pidió.

    `trabajo` recibe la función a la que el pipeline le pasa cada línea, y
    devuelve el sobre. Sin flujo, esto es literalmente lo que había antes.
    """
    if not _quiere_flujo():
        return trabajo(_registrar)
    return _respuesta_en_flujo(trabajo)


def _respuesta_en_flujo(trabajo):
    """El paso corriendo en un hilo y sus líneas saliendo por la conexión.

    El pipeline **empuja** cada línea (llama a `on_log`) y una respuesta HTTP
    se **tira** (el servidor pide el trozo siguiente). Una cola entre los dos
    traduce lo uno en lo otro: el hilo del paso mete líneas, el generador de la
    respuesta las saca. Sin cola no hay forma de ceder el control entre línea y
    línea, que es justamente lo que hace falta para que salgan según ocurren.

    **El evento `fin` es la única marca de que el paso terminó**, y trae el
    sobre completo más el código HTTP que le habría correspondido. Su ausencia
    significa «no sé si terminó» y nunca «terminó bien»: una conexión puede
    morir después de la mitad de las líneas, y sin una marca explícita eso es
    indistinguible de un paso corto que acabó pronto. Por eso el código HTTP
    viaja **dentro** del evento: las cabeceras salen antes de que el paso
    empiece, así que a esas alturas siempre son 200 y ya no pueden decir nada.

    La cola no tiene tope a propósito. Si quien escucha se va, el hilo del paso
    tiene que poder terminar lo que estaba escribiendo en CX y en el
    repositorio; con un tope se quedaría bloqueado poniendo una línea que ya no
    lee nadie, a mitad de una escritura.
    """
    lineas = queue.Queue()
    FIN = object()
    # Todo lo que hace falta de la petición se lee **aquí**, antes de que
    # arranque nada: ni el hilo ni el generador viven dentro del contexto de
    # petición de Flask, y tocarlo desde ahí falla de una forma que solo se ve
    # en producción.
    ruta = f"{request.method} {request.path}"

    def emitir(linea):
        # También al log del contenedor: los dos destinos importan y no son el
        # mismo: quien opera mira los logs de Cloud Run mucho después de que la
        # conexión del panel se haya cerrado.
        _registrar(linea)
        lineas.put(linea)

    def trabajar():
        try:
            sobre, codigo = trabajo(emitir), 200
        except Exception as error:       # noqa: BLE001 — se traduce, no se traga
            mensaje, codigo, datos = _traducir(error)
            _registrar(f"✗ {ruta} → {codigo}: {mensaje}")
            sobre = pipeline.step_result("error", [mensaje], datos)
        lineas.put((FIN, codigo, sobre))

    # `daemon`: un contenedor al que Cloud Run manda SIGTERM tiene diez
    # segundos, y un hilo no-daemon podría alargar el cierre esperando una
    # publicación de minutos. El corte se cuenta igual que cualquier otro: sin
    # evento `fin`, quien llama no da el paso por terminado.
    threading.Thread(target=trabajar, name="paso-en-flujo", daemon=True).start()

    def eventos():
        # Un comentario SSE antes de nada: obliga a que las cabeceras salgan ya
        # y da una señal observable de «la conexión está abierta y no se ha
        # perdido» mientras el paso todavía no ha emitido su primera línea.
        yield ": flujo abierto\n\n"
        while True:
            elemento = lineas.get()
            if isinstance(elemento, tuple) and elemento[0] is FIN:
                yield _evento("fin", {"http": elemento[1], "sobre": elemento[2]})
                return
            yield _evento("log", {"linea": elemento})

    return Response(eventos(), mimetype=TIPO_FLUJO, headers={
        # `no-transform` además de `no-cache`: hay proxys que recomprimen —y
        # por tanto acumulan— lo que pasa por ellos si no se les dice que no.
        "Cache-Control": "no-cache, no-transform",
        # Para los proxys de la familia nginx, que acumulan por defecto. Cloud
        # Run no lo necesita; cuesta una cabecera y evita depender de por dónde
        # se sirva esto mañana.
        "X-Accel-Buffering": "no",
    })


# ── Los cinco pasos ──────────────────────────────────────────────────────────
#
# Cada uno delega en una función del pipeline y no decide nada más. Lo que el
# endpoint sí hace, porque es trabajo de adaptador y no de pipeline: leer el
# body, comprobar que trae destino, comprobar que ese destino está permitido, y
# traducir el resultado a HTTP.
#
# Cuatro de los cinco pasan por `_responder`, que es lo que les permite emitir
# el registro según ocurre si quien llama lo pide. Son los que tardan: leer el
# agente entero, escribir en el repositorio, aplicar en CX y publicar. El Paso
# 4 no está: declara el resultado de unos tests y termina en una escritura, sin
# nada que contar por el camino.

@app.post("/step/1")
@endpoint
def paso_1_inventario():
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    return _responder(lambda emitir: pipeline.step_1_inventory(
        project, agent, on_log=emitir,
    ))


@app.post("/step/2")
@endpoint
def paso_2_traer_al_repositorio():
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    traer = _lista(cuerpo, "traer", [])
    return _responder(lambda emitir: pipeline.step_2_pull_to_repo(
        project, agent, traer, on_log=emitir,
    ))


@app.post("/step/3")
@endpoint
def paso_3_aplicar_en_cx():
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    aplicar = _lista(cuerpo, "aplicar")
    eliminar = _lista(cuerpo, "eliminar", [])
    dry_run = bool(cuerpo.get("dry_run", False))
    only_pending = _lista(cuerpo, "only_pending")
    return _responder(lambda emitir: pipeline.step_3_apply_to_cx(
        project, agent,
        aplicar=aplicar, eliminar=eliminar, dry_run=dry_run,
        only_pending=only_pending, on_log=emitir,
    ))


@app.post("/step/4")
@endpoint
def paso_4_validar_tests():
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    # El único paso que escribe (en Firestore, el registro que abre el candado
    # del Paso 5) sin coger el candado dentro del pipeline. Lo coge aquí: la
    # regla es que todo endpoint que escribe pasa por él, sin excepción.
    cliente = store.get_client()
    with store.agent_lock(cliente, project, agent, "validar tests"):
        return pipeline.step_4_validate_tests(
            project, agent, cuerpo.get("resultado"), client=cliente,
            on_log=_registrar,
        )


@app.post("/step/5")
@endpoint
def paso_5_publicar():
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    etiqueta = cuerpo.get("version_label")
    return _responder(lambda emitir: pipeline.step_5_publish(
        project, agent, etiqueta, on_log=emitir,
    ))


# ── Los que no pertenecen a ningún paso ──────────────────────────────────────

@app.get("/discover")
@endpoint
def descubrimiento():
    """Proyectos y, si se da uno, sus agentes con el repositorio que les toca.

    Sin `project` lista los proyectos GCP visibles; con él, los agentes de ese
    proyecto. No escribe nada, así que es el único que no exige un destino
    completo — pero el proyecto que llegue sí pasa por la misma guarda.
    """
    project = request.args.get("project")
    _comprobar_destino(project)
    return pipeline.discover(project or None, on_log=_registrar)


@app.post("/register-agent")
@endpoint
def alta_de_agente():
    """El botón del Paso 1: le crea al agente su rama de trabajo (S24).

    Es una escritura —crea una rama en el repositorio compartido y un documento
    en Firestore— y el pipeline no coge el candado dentro, así que se coge aquí.
    """
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    cliente = store.get_client()
    with store.agent_lock(cliente, project, agent, "dar de alta un agente"):
        return pipeline.register_agent(
            project, agent,
            region=cuerpo.get("region"),
            rama=cuerpo.get("rama"),
            carpeta_raiz=cuerpo.get("carpeta_raiz", "definitions"),
            client=cliente, on_log=_registrar,
        )


@app.post("/link-project-repo")
@endpoint
def vincular_proyecto_y_repositorio():
    """La Tool de onboarding: proyecto GCP + URL de repositorio (S22).

    **No pide agente, y no es un olvido.** El repositorio es del proyecto desde
    S24: todos sus agentes viven dentro, cada uno con su rama, y se dan de alta
    uno a uno desde el Paso 1. Exigir aquí un `agent` obligaría a inventar un
    valor que la función a la que delega ni siquiera acepta.

    Es también el único sitio donde el servidor acepta un repositorio de quien
    llama, porque es el acto de decidirlo. En cualquier otra llamada el
    repositorio se deriva del mapeo y nunca del cliente (C3).
    """
    cuerpo = _cuerpo()
    project, repo_url = _exigir(cuerpo, "project", "repo_url")
    _comprobar_destino(project)
    cliente = store.get_client()
    with store.agent_lock(cliente, project, "(proyecto)",
                          "vincular proyecto y repositorio"):
        return pipeline.link_project_repo(
            project, repo_url, cuerpo.get("rama_principal", "main"),
            client=cliente, on_log=_registrar,
        )


@app.post("/manage-versions")
@endpoint
def versiones_existentes():
    """Lista las versiones del agente, o borra exactamente las que se nombren.

    Borrar coge el candado dentro del pipeline, y ahí relee qué versiones sirve
    un entorno justo antes de decidir: por eso no se coge aquí, que además
    provocaría un choque del candado consigo mismo.
    """
    cuerpo = _cuerpo()
    project, agent = _exigir(cuerpo, "project", "agent")
    _comprobar_destino(project, agent)
    return pipeline.manage_versions(
        project, agent,
        action=cuerpo.get("action", "list"),
        version_names=_lista(cuerpo, "version_names"),
        on_log=_registrar,
    )


# ── El panel ─────────────────────────────────────────────────────────────────
#
# No son endpoints del pipeline: no reciben destino, no delegan en ninguna
# función y no tocan CX, Firestore ni GitHub. Sirven un archivo.

@app.get("/")
def raiz():
    """Quien abra la URL a secas quiere el panel, no una página en blanco."""
    return redirect("/panel", code=302)


@app.get("/panel")
def panel():
    """El panel de producción, servido desde el mismo origen que la API.

    `no-store` y no una caché larga: el panel cambia con cada despliegue, y un
    panel viejo cacheado contra un servidor nuevo produce fallos que nadie
    relaciona con la caché — se ven como funciones que dejaron de existir.
    """
    ruta = ruta_del_panel()
    if ruta is None:
        buscado = " · ".join(str(c) for c in
                             (PANEL_EN_LA_IMAGEN, PANEL_EN_EL_REPOSITORIO))
        mensaje = (f"No se encontró el archivo del panel ({PANEL_ARCHIVO}). "
                   f"Se buscó en: {buscado}. La API sigue funcionando; lo que "
                   f"falta es el archivo dentro de la imagen.")
        _registrar(f"✗ GET /panel → 404: {mensaje}")
        return jsonify(pipeline.step_result(
            "error", [mensaje], {"reason": "panel_no_encontrado"})), 404
    respuesta = send_file(ruta, mimetype="text/html")
    respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


# ── Salud ────────────────────────────────────────────────────────────────────

@app.get("/health")
@endpoint
def salud():
    """Que el proceso está en pie y sirviendo. No toca nada externo.

    Sin esto, un arranque colgado y un arranque fallido se ven igual desde
    fuera: los dos son "no contesta". Distinguirlos es lo que permite matar el
    proceso en el primer caso en vez de dejarlo ocupando el puerto.
    """
    # La cuenta con la que corre este proceso, para que el panel pueda componer
    # el comando IAM de un proyecto que el servidor todavía no alcanza. Se
    # pregunta y no se escribe en el panel: si el servicio se redespliega con
    # otra cuenta, el comando que se copie tiene que seguir siendo el correcto.
    #
    # Best-effort a propósito. La salud responde si el proceso está en pie, y
    # eso no puede depender de que se pueda averiguar la identidad: si fallara,
    # un arranque sano se vería igual que uno roto, que es justo lo que este
    # endpoint existe para distinguir.
    try:
        cuenta = cx.runtime_service_account()
    except Exception:
        cuenta = None

    return pipeline.step_result("ok", ["servidor en marcha"], {
        "endpoints": sorted(
            regla.rule for regla in app.url_map.iter_rules()
            if regla.rule != "/static/<path:filename>"
        ),
        "service_account": cuenta,
        "roles_del_alta": list(pipeline.ROLES_DEL_ALTA),
    })


def main():
    puerto = int(os.environ.get("PORT", PUERTO_POR_DEFECTO))
    # `0.0.0.0` y no `127.0.0.1`: dentro de un contenedor, un servidor atado al
    # loopback no es alcanzable desde fuera y Cloud Run lo da por muerto.
    app.run(host="0.0.0.0", port=puerto, debug=False, threaded=True)


if __name__ == "__main__":
    main()
