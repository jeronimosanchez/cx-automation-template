#!/usr/bin/env python3
"""
act/validate_server_cloudrun.py — Smoke test de act/server_cloudrun.py.

El servidor es una capa nueva entre el panel y el pipeline, y puede fallar por
razones que `validate_pipeline_cloudrun.py` (Fase 4) no cubre: un puerto mal
configurado, CORS roto, un body que no se puede parsear, o un endpoint que
responde con datos de ejemplo sin estar conectado a nada. Esto lo comprueba
golpeando el servidor con peticiones HTTP reales, sin ningún paso manual.

Siete niveles de riesgo creciente. Se hereda el patrón de la Fase 4 —mismos
niveles, mismo criterio de cero residuo, mismo `CheckRunner`— en vez de
inventar uno nuevo:

    Nivel 0  Estructura y arranque. Sin destino: analiza el código del
             servidor, del cliente de la GitHub App y del Dockerfile, y
             comprueba que el proceso arranca y se cierra siempre.
    Nivel 1  Contrato HTTP contra el destino desechable. Solo lecturas.
    Nivel 2  Conexión real: cada endpoint contra la función del pipeline a la
             que dice delegar, comparando el resultado. Y `dry_run`
             comprobado por el estado antes y después, no por lo que diga.
    Nivel 3  Escritura real por HTTP: el ciclo entero, del pull a publicar.
    Nivel 4  Caos: SIGKILL a mitad de una escritura, timeout del cliente con
             la operación viva, y concurrencia entre dos peticiones.
    Nivel 5  El contenedor: `docker build` y el servidor sirviendo dentro.
    Nivel 6  Cloud Run real, en staging, con el Service Account de runtime.

**Nunca contra Petal.** Ni siquiera para leer. Hay dos barreras y las dos
tienen que pasar: la lista de destinos protegidos de este archivo, que se
comprueba antes de emitir nada, y `exigir_agente_desechable` de la Fase 4, que
obliga a que el agente destino declare en su propio nombre que lo es. Se
importa a propósito en vez de reescribirse: un validador nuevo no hereda la
guarda de otro por parecerse a él.

**Cero residuo.** Todo lo que se crea lleva `actsrv_<corrida>`, se barre al
empezar además de al terminar —un `finally` no sobrevive a un SIGKILL— y cada
borrado se confirma leyendo el resultado, nunca por el código de respuesta.

---

## Provisión del destino desechable (una sola vez, fuera del test)

El smoke test asume que ya existen y usa sus identificadores. Crearlos dentro
del propio test mezclaría la infraestructura con lo que se prueba, igual que el
comando IAM del onboarding (S6b) vive fuera del panel. La receta completa:

    # 1. Un agente CX que declare en su nombre que es desechable.
    #    La marca no es decorativa: es lo que mira la guarda antes de escribir.
    POST https://<region>-dialogflow.googleapis.com/v3beta1/
         projects/<PROYECTO>/locations/<REGION>/agents
         {"displayName": "...-desechable", "defaultLanguageCode": "es",
          "timeZone": "Europe/Madrid"}

    # 2. Su entorno de producción. CX rechaza crearlo vacío
    #    ("Version must be provided for start flow resource"), así que antes
    #    hay que crear una versión del flow de arranque:
    POST .../agents/<AGENTE>/flows/<FLOW>/versions   {"displayName": "base"}
    POST .../agents/<AGENTE>/environments
         {"displayName": "production", "versionConfigs": [{"version": "<esa>"}]}

    # 3. Dos ramas desechables en el repositorio: la principal del proyecto y
    #    la de trabajo del agente. La principal NO puede ser main/master/
    #    production — publicar fusiona una en otra y el guardarraíl se niega.
    #    Las crea la GitHub App; la de trabajo la crea el propio alta del
    #    agente si se le pasa el nombre.

    # 4. El vínculo, con las dos funciones del pipeline (o sus endpoints):
    link_project_repo(<PROYECTO>, "https://github.com/<owner>/<repo>",
                      "<rama-principal-desechable>")
    register_agent(<PROYECTO>, <AGENTE>, region=<REGION>,
                   rama="<rama-de-trabajo-desechable>",
                   carpeta_raiz="act/scaffolding")

Variables de entorno que el test necesita, y que también inyecta al servidor:

    FIRESTORE_PROJECT           proyecto donde vive Firestore
    GITHUB_APP_ID               App ID de la GitHub App
    GITHUB_APP_SECRET_PROJECT   proyecto del secreto con su clave privada

Uso:
    python act/validate_server_cloudrun.py --levels 0
    python act/validate_server_cloudrun.py --project P --agent A --levels 0-4
    python act/validate_server_cloudrun.py --project P --agent A --levels 6 \\
        --staging-service act-server-staging
"""

import argparse
import ast
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline
from act import server_cloudrun
from act.utils import cx_client_cloudrun as cx
from act.utils import firestore_client_cloudrun as store
from act.utils import github_app_client_cloudrun as github

# El patrón de la Fase 4, importado y no reescrito. `exigir_agente_desechable`
# y `exigir_rama_principal_desechable` son la única barrera que no depende de
# acordarse, y un validador nuevo no las hereda por parecerse al anterior: hay
# que traerlas explícitamente.
from act.validate_pipeline_cloudrun import (   # noqa: E402
    PASS, FAIL, SKIP, CheckRunner,
    exigir_agente_desechable, exigir_rama_principal_desechable,
)

SERVIDOR = "act/server_cloudrun.py"
DOCKERFILE = "Dockerfile"
CLIENTE_GITHUB = "act/utils/github_app_client_cloudrun.py"

# Rutas del servidor que no pertenecen al pipeline: no reciben destino, no
# delegan en ninguna de sus funciones y no tocan CX, Firestore ni GitHub.
# `/health` dice si el proceso está en pie; `/` y `/panel` sirven el archivo del
# panel desde este mismo origen (S25). Se enumeran una a una a propósito: la
# alternativa —saltarse la comprobación para cualquier ruta que no delegue— la
# haría pasar también para un endpoint del pipeline que dejara de delegar, que
# es justo lo que la comprobación existe para cazar.
RUTAS_QUE_NO_SON_DEL_PIPELINE = frozenset({"/health", "/", "/panel"})

# Prefijo de todo lo que crea una corrida. Distinto del de la Fase 4 (`actval`)
# a propósito: cada suite barre lo suyo, y con el mismo prefijo una corrida
# podría borrar lo que la otra está usando en ese momento.
PREFIJO = "actsrv"

# Segunda barrera, en código, delante de la del agente desechable. La primera
# lista lo que nunca se toca; la segunda exige que el destino se declare
# desechable. Hacen falta las dos: la lista se queda corta con un agente real
# que no esté en ella, y la marca no protege de un proyecto entero.
PROYECTOS_PROHIBIDOS = frozenset({"floristeria-petal-digital"})
AGENTES_PROHIBIDOS = frozenset({
    "745375ba-ac7e-4eb8-b8a0-d742891f2aa4",   # Petal 1.0
    "cea66b60-192d-4b5a-af10-28f8661032e0",   # Petal 1.1
})

# Los nueve puntos de entrada del pipeline que el servidor tiene que exponer.
FUNCIONES_DEL_PIPELINE = {
    "step_1_inventory", "step_2_pull_to_repo", "step_3_apply_to_cx",
    "step_4_validate_tests", "step_5_publish", "discover", "register_agent",
    "link_project_repo", "manage_versions",
}

# Cuánto se espera a que el servidor conteste al arrancar. Pasado esto se le
# mata igual: un arranque colgado sin limpiar deja un proceso huérfano
# ocupando el puerto, que es el mismo problema que un cierre mal hecho.
ARRANQUE_MAX_SEGUNDOS = 45

# Lo que imprime una precarga cuando ha llegado hasta el final. Es la única
# forma de distinguir "el caso se forzó" de "el `sitecustomize` reventó y el
# servidor arrancó normal", que se ve exactamente igual desde fuera.
MARCA_PRECARGA = "[precarga] aplicada"


def _comprobar_destino(project, agent_id=None):
    """Se niega a seguir si el destino está protegido. Antes de tocar la red."""
    if project in PROYECTOS_PROHIBIDOS or agent_id in AGENTES_PROHIBIDOS:
        raise SystemExit(
            f"ALTO: {project}/{agent_id or '—'} es un destino protegido. Este "
            f"script escribe de verdad. No se ha tocado nada."
        )


def _lleva_la_marca(tipo, item):
    """Si un resource lo creó una corrida de este validador.

    Las versiones que cuelgan de un playbook o un tool llevan la marca en
    `description`, porque esos endpoints no aceptan `displayName`. El resto de
    tipos, solo en `displayName`: buscar también en la descripción de cualquier
    resource cazaría los que una prueba se limitó a *modificar*, y el barrido
    intentaría borrar el flow de arranque del agente, que CX no deja borrar.
    """
    if tipo == "version":
        return PREFIJO in f"{item.get('displayName', '')} {item.get('description', '')}"
    return str(item.get("displayName", "")).startswith(PREFIJO)


def _puerto_libre():
    """Un puerto que nadie esté usando, para no chocar con otra corrida."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _escucha(puerto, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, puerto)) == 0


# ── El servidor como subproceso ──────────────────────────────────────────────

class Servidor:
    """Arranca `server_cloudrun.py` y garantiza que se cierra siempre.

    El cierre no depende de que el proceso muera por su cuenta ni de que el
    test termine bien: `__exit__` mata igual, y si el arranque se cuelga sin
    contestar, también. Un arranque colgado que no se limpia deja el puerto
    ocupado y bloquea la corrida siguiente.
    """

    def __init__(self, puerto=None, entorno_extra=None, sin_credenciales=False,
                 esperar=True, precarga=None):
        self.puerto = puerto if puerto is not None else _puerto_libre()
        self.entorno_extra = dict(entorno_extra or {})
        self.sin_credenciales = sin_credenciales
        self.esperar = esperar
        self.precarga = precarga
        self.proceso = None
        self.salida = None
        self._temporales = []

    def _entorno(self):
        entorno = dict(os.environ)
        entorno["PORT"] = str(self.puerto)
        entorno.setdefault("ALLOWED_ORIGIN", "*")
        entorno.update(self.entorno_extra)
        if self.sin_credenciales:
            # ADC busca, en este orden: la variable explícita, el archivo del
            # SDK bajo CLOUDSDK_CONFIG, y el metadata server. Se cortan las
            # tres. Sin cortar la tercera, en un Mac el intento contra
            # 169.254.169.254 tarda en rendirse y el arranque parece colgado.
            entorno.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            vacio = tempfile.mkdtemp(prefix="sin-adc-")
            self._temporales.append(vacio)
            entorno["CLOUDSDK_CONFIG"] = vacio
            entorno["GCE_METADATA_HOST"] = "127.0.0.1:1"
            entorno["GCE_METADATA_IP"] = "127.0.0.1:1"
        if self.precarga:
            # Un `sitecustomize.py` en el PYTHONPATH del subproceso: es la
            # forma de forzar un caso dentro del servidor real —el mismo
            # proceso, los mismos endpoints— sin tener que modificar su código
            # ni pedir un permiso que no se puede pedir.
            #
            # Se deja una marca al final: un `sitecustomize` que revienta a
            # medias no impide arrancar, y sin la marca el check pasaría
            # creyendo que forzó un caso que nunca llegó a forzarse.
            carpeta = tempfile.mkdtemp(prefix="precarga-")
            self._temporales.append(carpeta)
            (Path(carpeta) / "sitecustomize.py").write_text(
                self.precarga + f'\nprint("{MARCA_PRECARGA}", flush=True)\n')
            entorno["PYTHONPATH"] = os.pathsep.join(
                [carpeta, entorno.get("PYTHONPATH", "")]
            ).strip(os.pathsep)
        return entorno

    def __enter__(self):
        self.salida = tempfile.NamedTemporaryFile(
            prefix="server-", suffix=".log", delete=False, mode="w+")
        self.proceso = subprocess.Popen(
            [sys.executable, SERVIDOR], cwd=str(REPO_ROOT), env=self._entorno(),
            stdout=self.salida, stderr=subprocess.STDOUT,
        )
        if self.esperar and not self.esperar_a_que_conteste():
            registro = self.log()[-1200:]
            self.cerrar()
            raise RuntimeError(
                f"El servidor no contestó en {ARRANQUE_MAX_SEGUNDOS}s y se ha "
                f"matado igual. Últimas líneas:\n{registro}"
            )
        return self

    def __exit__(self, *_):
        self.cerrar()
        return False

    def esperar_a_que_conteste(self, segundos=ARRANQUE_MAX_SEGUNDOS):
        limite = time.time() + segundos
        while time.time() < limite:
            if self.proceso.poll() is not None:
                return False           # murió por su cuenta: no hay nada que esperar
            try:
                if requests.get(self.url("/health"), timeout=2).status_code == 200:
                    return True
            except requests.RequestException:
                time.sleep(0.3)
        return False

    def url(self, ruta):
        return f"http://127.0.0.1:{self.puerto}{ruta}"

    def log(self):
        try:
            return Path(self.salida.name).read_text(errors="replace")
        except OSError:
            return ""

    def vivo(self):
        return self.proceso is not None and self.proceso.poll() is None

    def matar_de_golpe(self):
        """SIGKILL: ni `finally`, ni cierre ordenado, ni nada. Como un
        contenedor que la plataforma termina a mitad de una operación."""
        if self.vivo():
            self.proceso.send_signal(signal.SIGKILL)
            self.proceso.wait(timeout=10)

    def cerrar(self):
        if self.proceso is not None and self.proceso.poll() is None:
            self.proceso.terminate()
            try:
                self.proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proceso.kill()
                self.proceso.wait(timeout=10)
        if self.salida is not None:
            self.salida.close()
        for carpeta in self._temporales:
            shutil.rmtree(carpeta, ignore_errors=True)
        self._temporales = []


def pedir(servidor, metodo, ruta, cuerpo=None, timeout=900, **extra):
    return requests.request(metodo, servidor.url(ruta), json=cuerpo,
                            timeout=timeout, **extra)


def sobre(respuesta):
    """El cuerpo de la respuesta, exigiendo que tenga la forma del sobre.

    Un endpoint que devolviera texto plano o le faltara un campo rompería el
    panel de una forma que no se ve hasta abrir la consola del navegador.
    """
    datos = respuesta.json()
    faltan = [c for c in ("status", "log", "data") if c not in datos]
    if faltan:
        raise AssertionError(f"al sobre le faltan {faltan}: {str(datos)[:200]}")
    if not isinstance(datos["log"], list) or not isinstance(datos["data"], dict):
        raise AssertionError(
            f"log tiene que ser lista y data diccionario: "
            f"{type(datos['log']).__name__}/{type(datos['data']).__name__}"
        )
    return datos


# ── Nivel 0 · Estructura y arranque ──────────────────────────────────────────

def _vistas_del_servidor():
    """Las funciones de `server_cloudrun.py` que están enrutadas, con su árbol."""
    arbol = ast.parse((REPO_ROOT / SERVIDOR).read_text())
    vistas = {}
    for nodo in arbol.body:
        if not isinstance(nodo, ast.FunctionDef):
            continue
        rutas = [
            d.args[0].value for d in nodo.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and d.func.attr in ("get", "post", "route") and d.args
            and isinstance(d.args[0], ast.Constant)
        ]
        if rutas:
            vistas[nodo.name] = (rutas[0], nodo)
    return vistas


def _llamadas_a_modulo(nodo, modulo):
    return [n.func.attr for n in ast.walk(nodo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name) and n.func.value.id == modulo]


def nivel_0(runner):
    print("\nNIVEL 0 — Estructura y arranque · sin destino")

    def los_nueve_puntos_de_entrada_estan_enrutados():
        rutas = {ruta for ruta, _ in _vistas_del_servidor().values()}
        esperadas = {"/step/1", "/step/2", "/step/3", "/step/4", "/step/5",
                     "/discover", "/register-agent", "/link-project-repo",
                     "/manage-versions"}
        faltan = esperadas - rutas
        return not faltan, f"sin enrutar: {sorted(faltan)}"

    runner.check(0, "Los cinco pasos y los cuatro endpoints sin numerar están "
                    "enrutados", los_nueve_puntos_de_entrada_estan_enrutados)

    def cada_endpoint_delega_y_no_reimplementa():
        """El servidor es un adaptador HTTP, no un segundo pipeline.

        Se mira lo que llama cada vista: tiene que llamar a una de las nueve
        funciones del pipeline, y no puede llamar por su cuenta ni a la API de
        CX ni a la de GitHub. Si reimplementara lógica habría dos fuentes de
        verdad, y divergirían sin que nada avisara.
        """
        problemas = []
        for nombre, (ruta, nodo) in _vistas_del_servidor().items():
            delegadas = set(_llamadas_a_modulo(nodo, "pipeline"))
            if ruta in RUTAS_QUE_NO_SON_DEL_PIPELINE:
                continue
            if not delegadas & FUNCIONES_DEL_PIPELINE:
                problemas.append(f"{ruta} no delega en ninguna función del pipeline")
            for modulo in ("cx", "github"):
                if _llamadas_a_modulo(nodo, modulo):
                    problemas.append(f"{ruta} llama directamente a {modulo}")
            invasoras = set(_llamadas_a_modulo(nodo, "store")) - {
                "get_client", "agent_lock"}
            if invasoras:
                problemas.append(f"{ruta} toca Firestore por su cuenta: {sorted(invasoras)}")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Cada endpoint delega en una función del pipeline y ninguno "
                    "reimplementa lógica dentro", cada_endpoint_delega_y_no_reimplementa)

    def todo_endpoint_que_escribe_pasa_por_el_candado():
        """Cada escritura pasa por el candado exactamente una vez.

        No se puede pedir que lo coja el servidor siempre: el candado de
        Firestore no es reentrante, así que envolver un paso que ya lo coge
        dentro haría que chocara consigo mismo y ningún deploy avanzaría. La
        regla verificable es la otra: para cada endpoint que escribe, el
        candado se coge una vez — en el servidor o en el pipeline, nunca en los
        dos ni en ninguno.
        """
        fuente_pipeline = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(fuente_pipeline)
        con_candado_dentro = {
            nodo.name for nodo in arbol.body
            if isinstance(nodo, ast.FunctionDef)
            and "agent_lock" in _llamadas_a_modulo(nodo, "store")
        }
        escriben = {
            "/step/2": "step_2_pull_to_repo", "/step/3": "step_3_apply_to_cx",
            "/step/4": "step_4_validate_tests", "/step/5": "step_5_publish",
            "/register-agent": "register_agent",
            "/link-project-repo": "link_project_repo",
            "/manage-versions": "manage_versions",
        }
        problemas = []
        for ruta, nodo in ((r, n) for r, n in _vistas_del_servidor().values()):
            if ruta not in escriben:
                continue
            en_el_servidor = "agent_lock" in _llamadas_a_modulo(nodo, "store")
            en_el_pipeline = escriben[ruta] in con_candado_dentro
            if en_el_servidor and en_el_pipeline:
                problemas.append(f"{ruta}: candado dos veces, chocaría consigo mismo")
            if not en_el_servidor and not en_el_pipeline:
                problemas.append(f"{ruta}: escribe sin candado")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Todo endpoint que escribe pasa por el candado de Firestore "
                    "exactamente una vez", todo_endpoint_que_escribe_pasa_por_el_candado)

    def el_servidor_no_guarda_estado_entre_peticiones():
        """Ninguna variable de módulo mutable donde quepa el estado de una
        petición. Cloud Run puede matar y rearrancar la instancia en cualquier
        momento, y reutiliza el contenedor entre peticiones de agentes
        distintos: un valor guardado arriba se filtraría de uno a otro."""
        arbol = ast.parse((REPO_ROOT / SERVIDOR).read_text())
        mutables = []
        for nodo in arbol.body:
            if not isinstance(nodo, ast.Assign):
                continue
            if isinstance(nodo.value, (ast.List, ast.Dict, ast.Set)):
                mutables += [d.id for d in nodo.targets if isinstance(d, ast.Name)]
        return not mutables, f"variables de módulo mutables: {mutables}"

    runner.check(0, "El servidor no guarda estado entre peticiones",
                 el_servidor_no_guarda_estado_entre_peticiones)

    def el_puerto_sale_de_la_variable_y_nunca_es_el_5000():
        fuente = (REPO_ROOT / SERVIDOR).read_text()
        lee_la_variable = 'os.environ.get("PORT"' in fuente
        menciona_el_5000 = "5000" in fuente
        por_defecto = server_cloudrun.PUERTO_POR_DEFECTO
        return (lee_la_variable and por_defecto == 8080
                and not menciona_el_5000), (
            f"por defecto={por_defecto} · ¿lee PORT?={lee_la_variable} · "
            f"¿menciona el 5000?={menciona_el_5000}"
        )

    runner.check(0, "El puerto sale de la variable PORT, con 8080 por defecto y "
                    "nunca el 5000 del servidor local",
                 el_puerto_sale_de_la_variable_y_nunca_es_el_5000)

    def el_origen_de_cors_sale_de_una_variable():
        fuente = (REPO_ROOT / SERVIDOR).read_text()
        return 'os.environ.get("ALLOWED_ORIGIN"' in fuente, (
            "el origen permitido no se lee de una variable de entorno"
        )

    runner.check(0, "El origen permitido de CORS se lee de una variable de "
                    "entorno, no está escrito en el código",
                 el_origen_de_cors_sale_de_una_variable)

    def el_token_de_github_no_vive_en_una_variable_de_modulo():
        """Un token guardado arriba lo comparten dos peticiones de repositorios
        distintos, y caduca en silencio para las dos.

        Se busca la única forma en que una variable de módulo puede recibir un
        valor calculado dentro de una función —una sentencia `global`— y se
        exige que el token se guarde en la instancia. Mirar los nombres que
        contienen «token» no vale: `TOKEN_MARGIN_SECONDS` es un número.
        """
        fuente = (REPO_ROOT / CLIENTE_GITHUB).read_text()
        arbol = ast.parse(fuente)
        globales = sorted({nombre for nodo in ast.walk(arbol)
                           if isinstance(nodo, ast.Global) for nombre in nodo.names})
        # Toda asignación de módulo tiene que ser una constante literal: si lo
        # es, no puede contener nada que se calcule por petición.
        calculadas = [d.id for nodo in arbol.body if isinstance(nodo, ast.Assign)
                      for d in nodo.targets if isinstance(d, ast.Name)
                      and not isinstance(nodo.value, ast.Constant)]
        en_la_instancia = "self._token = " in fuente
        return (not globales and not calculadas and en_la_instancia), (
            f"global {globales} · asignaciones de módulo calculadas "
            f"{calculadas} · ¿el token va en la instancia?={en_la_instancia}")

    runner.check(0, "El token de la GitHub App no vive en una variable de módulo",
                 el_token_de_github_no_vive_en_una_variable_de_modulo)

    def el_dockerfile_dice_lo_que_tiene_que_decir():
        texto = (REPO_ROOT / DOCKERFILE).read_text()
        faltan = [t for t in ("FROM python:3.11-slim", "requirements.txt",
                              "COPY act/", "EXPOSE 8080", "server_cloudrun.py")
                  if t not in texto]
        # Ninguna credencial dentro de la imagen: las pone Cloud Run al arrancar.
        colados = [t for t in ("application_default_credentials", "PRIVATE KEY",
                               "GOOGLE_APPLICATION_CREDENTIALS")
                   if t in texto]
        return not faltan and not colados, (
            f"faltan {faltan} · credenciales dentro: {colados}")

    runner.check(0, "El Dockerfile parte de python:3.11-slim, instala las "
                    "dependencias, copia act/, expone el 8080 y no lleva "
                    "credenciales dentro", el_dockerfile_dice_lo_que_tiene_que_decir)

    # ── Arranque y cierre, ya como comportamiento ────────────────────────────

    def arranca_en_el_puerto_de_la_variable():
        puerto = _puerto_libre()
        with Servidor(puerto=puerto) as servidor:
            respuesta = requests.get(servidor.url("/health"), timeout=10)
            return (respuesta.status_code == 200
                    and sobre(respuesta)["status"] == "ok"), \
                f"{respuesta.status_code} en el puerto {puerto}"

    runner.check(0, "Arranca en el puerto que dice PORT y contesta",
                 arranca_en_el_puerto_de_la_variable)

    def sin_port_escucha_en_el_8080():
        """El valor por defecto tiene que ser 8080 de verdad, no solo en el
        código: si Cloud Run no inyectara PORT y el servidor escuchara en otro
        sitio, el health check de la plataforma fallaría y el despliegue no
        llegaría a arrancar."""
        if _escucha(8080):
            return True, "(el 8080 ya está ocupado en esta máquina: no se prueba)"
        servidor = Servidor(puerto=8080, esperar=False)
        servidor.entorno_extra["PORT"] = ""       # como si no viniera
        try:
            with servidor:
                servidor.proceso.terminate()
                servidor.proceso.wait(timeout=5)
        except Exception:
            pass
        finally:
            servidor.cerrar()
        # Se repite sin trucos: se arranca sin PORT en el entorno y se mira si
        # el 8080 contesta.
        entorno = {k: v for k, v in os.environ.items() if k != "PORT"}
        proceso = subprocess.Popen(
            [sys.executable, SERVIDOR], cwd=str(REPO_ROOT), env=entorno,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        try:
            limite = time.time() + ARRANQUE_MAX_SEGUNDOS
            while time.time() < limite:
                try:
                    if requests.get("http://127.0.0.1:8080/health",
                                    timeout=2).status_code == 200:
                        return True, ""
                except requests.RequestException:
                    time.sleep(0.3)
            return False, "sin PORT no contestó en el 8080"
        finally:
            proceso.terminate()
            try:
                proceso.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proceso.kill()

    runner.check(0, "Sin PORT en el entorno, escucha en el 8080",
                 sin_port_escucha_en_el_8080)

    def un_arranque_colgado_se_mata_igual():
        """No basta con matar el proceso cuando muere solo: si arranca y no
        contesta, hay que matarlo también, o se queda ocupando el puerto para
        la corrida siguiente."""
        # Se fuerza el cuelgue con una precarga que duerme antes de que el
        # servidor llegue a servir nada: el proceso existe y no contesta.
        servidor = Servidor(precarga="import time\ntime.sleep(600)\n",
                            esperar=False)
        with servidor:
            arranco = servidor.esperar_a_que_conteste(segundos=6)
            pid = servidor.proceso.pid
            servidor.cerrar()
        vivo = False
        try:
            os.kill(pid, 0)
            vivo = True
        except OSError:
            vivo = False
        return (not arranco and not vivo), (
            f"contestó={arranco} · sigue vivo tras cerrar={vivo}")

    runner.check(0, "Un arranque que se cuelga sin contestar se mata igual, no "
                    "solo cuando el proceso muere por su cuenta",
                 un_arranque_colgado_se_mata_igual)

    def sin_credenciales_error_claro_y_no_una_traza():
        """El fallo más frecuente del primer despliegue. Un stacktrace crudo
        obliga a depurarlo a ciegas."""
        with Servidor(sin_credenciales=True) as servidor:
            respuesta = pedir(servidor, "GET", "/discover", timeout=60)
            datos = sobre(respuesta)
            texto = " ".join(datos["log"])
            return ("Traceback" not in texto
                    and datos["status"] == "error"
                    and ("credencial" in texto.lower() or "ADC" in texto)), \
                f"{respuesta.status_code}: {texto[:160]}"

    runner.check(0, "Sin credenciales ADC responde con un error claro, no con "
                    "una traza cruda", sin_credenciales_error_claro_y_no_una_traza)

    # ── La GitHub App, con la API real ───────────────────────────────────────

    def el_token_dura_una_hora_o_menos():
        cliente = github.GitHubAppClient(_repo_de_referencia())
        cliente.token()
        restante = (cliente._token_expires_at
                    - github.datetime.now(github.timezone.utc)).total_seconds()
        return 0 < restante <= 3600, f"caduca en {int(restante)}s"

    def el_token_se_reutiliza_y_se_renueva_cuando_toca():
        cliente = github.GitHubAppClient(_repo_de_referencia())
        primero = cliente.token()
        segundo = cliente.token()
        if primero != segundo:
            return False, "regeneró un token que seguía siendo válido"
        # Se le hace creer que ya caducó: tiene que pedir uno nuevo.
        cliente._token_expires_at = github.datetime.now(github.timezone.utc)
        tercero = cliente.token()
        if tercero == primero:
            return False, "reutilizó un token caducado"
        otro = github.GitHubAppClient(_repo_de_referencia())
        return otro._token is None, (
            "un cliente recién creado ya trae token: se está compartiendo")

    if os.environ.get("GITHUB_APP_ID") and os.environ.get("GITHUB_APP_SECRET_PROJECT"):
        runner.check(0, "El token de la GitHub App dura una hora o menos",
                     el_token_dura_una_hora_o_menos)
        runner.check(0, "Dos llamadas seguidas reutilizan el token si sigue "
                        "vivo, y piden uno nuevo si caducó",
                     el_token_se_reutiliza_y_se_renueva_cuando_toca)
    else:
        runner.skip(0, "El token de la GitHub App dura una hora o menos",
                    "faltan GITHUB_APP_ID y/o GITHUB_APP_SECRET_PROJECT")
        runner.skip(0, "Dos llamadas seguidas reutilizan el token si sigue vivo",
                    "faltan GITHUB_APP_ID y/o GITHUB_APP_SECRET_PROJECT")


def _repo_de_referencia():
    """Un repositorio donde la GitHub App esté instalada, para probarla.

    Sale del entorno o del mapeo del proyecto que se esté validando: escribirlo
    aquí ataría el validador a un repositorio concreto.
    """
    if os.environ.get("GITHUB_TEST_REPO"):
        return os.environ["GITHUB_TEST_REPO"]
    if os.environ.get("VALIDATE_PROJECT"):
        return store.get_project_mapping(
            store.get_client(), os.environ["VALIDATE_PROJECT"])["repo"]
    raise RuntimeError(
        "No hay repositorio de referencia: pasa GITHUB_TEST_REPO o ejecuta con "
        "--project, que lo saca del mapeo del proyecto."
    )


# ── Nivel 1 · Contrato HTTP ──────────────────────────────────────────────────

def nivel_1(runner, servidor, project, agent_id):
    print("\nNIVEL 1 — Contrato HTTP · lecturas contra el destino desechable")

    destino = {"project": project, "agent": agent_id}
    mapeo = store.get_agent_mapping(store.get_client(), project, agent_id)

    def los_nueve_endpoints_devuelven_200_y_el_sobre():
        """Los cinco numerados y los cuatro que no lo son, uno por uno.

        Cada uno se llama con la petición que no cambia nada: `traer` vacío no
        trae, el Paso 3 en dry-run no escribe, y vincular y dar de alta se
        piden con exactamente lo que el destino ya tiene, así que son no-ops.
        El Paso 5 se para en su propio candado y contesta `aborted`, que es una
        respuesta correcta con el mismo sobre — por eso el estado esperado se
        declara por endpoint en vez de exigir «ok» a todos.
        """
        llamadas = [
            ("POST", "/step/1", destino, "ok"),
            ("POST", "/step/2", {**destino, "traer": []}, "ok"),
            ("POST", "/step/3", {**destino, "dry_run": True}, "ok"),
            ("POST", "/step/4", {**destino, "resultado": "fallidos"}, "ok"),
            ("POST", "/step/5", {**destino,
                                 "version_label": f"{PREFIJO}_forma"}, "aborted"),
            ("GET", f"/discover?project={project}", None, "ok"),
            ("POST", "/register-agent",
             {**destino, "region": mapeo["region"], "rama": mapeo["rama"],
              "carpeta_raiz": mapeo.get("carpeta_raiz", "definitions")}, "ok"),
            ("POST", "/link-project-repo",
             {"project": project,
              "repo_url": f"https://github.com/{mapeo['repo']}",
              "rama_principal": mapeo["rama_principal"]}, "ok"),
            ("POST", "/manage-versions", {**destino, "action": "list"}, "ok"),
        ]
        problemas = []
        for metodo, ruta, cuerpo, esperado in llamadas:
            respuesta = pedir(servidor, metodo, ruta, cuerpo)
            if respuesta.status_code != 200:
                problemas.append(f"{ruta}: HTTP {respuesta.status_code}")
                continue
            try:
                datos = sobre(respuesta)
            except Exception as error:
                problemas.append(f"{ruta}: {error}")
                continue
            if datos["status"] != esperado:
                problemas.append(f"{ruta}: status={datos['status']} "
                                 f"(se esperaba {esperado})")
        return not problemas, " · ".join(problemas)

    runner.check(1, "Los nueve endpoints devuelven 200 y JSON válido con "
                    "status, log y data", los_nueve_endpoints_devuelven_200_y_el_sobre)

    def sin_destino_400_nunca_200():
        casos = [
            ("/step/1", {"agent": agent_id}),
            ("/step/1", {"project": project}),
            ("/step/2", {}),
            ("/step/3", {"agent": agent_id}),
            ("/step/4", {"project": project, "resultado": "superados"}),
            ("/step/5", {"agent": agent_id, "version_label": "x"}),
            ("/register-agent", {"project": project}),
            ("/manage-versions", {"agent": agent_id}),
            ("/link-project-repo", {"project": project}),
        ]
        problemas = []
        for ruta, cuerpo in casos:
            respuesta = pedir(servidor, "POST", ruta, cuerpo)
            datos = sobre(respuesta)
            if respuesta.status_code != 400:
                problemas.append(f"{ruta} {cuerpo} → {respuesta.status_code}")
            elif not any("Falta" in linea for linea in datos["log"]):
                problemas.append(f"{ruta}: el mensaje no dice qué falta")
        return not problemas, " · ".join(problemas)

    runner.check(1, "Una petición de escritura sin project o sin agent devuelve "
                    "400 diciendo qué falta, nunca 200", sin_destino_400_nunca_200)

    def json_mal_formado_400_y_no_500():
        """El 400 no basta: el mensaje tiene que señalar al cuerpo.

        Un servidor que se tragara el JSON roto y lo tratara como cuerpo vacío
        acabaría contestando 400 igualmente —por el destino que falta— y este
        check pasaría sin haber probado nada. Lo que distingue un caso del otro
        es lo que dice el mensaje, así que es lo que se mira. El body se manda
        con destino completo a propósito: si se parseara, la petición sería
        válida y contestaría 200.
        """
        rotos = ('{"project": "' + project + '", "agent": ',
                 "no soy json", "[1,2,3]", '"hola"')
        problemas = []
        for cuerpo in rotos:
            respuesta = requests.post(
                servidor.url("/step/1"), data=cuerpo.encode(),
                headers={"Content-Type": "application/json"}, timeout=30)
            datos = sobre(respuesta)
            texto = " ".join(datos["log"])
            if respuesta.status_code != 400:
                problemas.append(f"{cuerpo[:16]!r} → {respuesta.status_code}")
            elif not ("JSON" in texto or "objeto" in texto):
                problemas.append(f"{cuerpo[:16]!r}: el mensaje no menciona el "
                                 f"cuerpo: {texto[:60]!r}")
            if "Traceback" in texto:
                problemas.append(f"{cuerpo[:16]!r} devolvió una traza")
        return not problemas, " · ".join(problemas)

    runner.check(1, "Un body con JSON mal formado responde 400 con mensaje "
                    "claro, nunca un 500 crudo", json_mal_formado_400_y_no_500)

    def cors_en_la_respuesta_real_y_en_el_preflight():
        origen = "http://localhost:4321"
        real = pedir(servidor, "POST", "/step/1", destino,
                     headers={"Origin": origen})
        previa = requests.options(
            servidor.url("/step/1"), timeout=30,
            headers={"Origin": origen,
                     "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type"})
        problemas = []
        for nombre, respuesta in (("respuesta real", real), ("preflight", previa)):
            permitido = respuesta.headers.get("Access-Control-Allow-Origin")
            if permitido not in (origen, "*"):
                problemas.append(f"{nombre}: Allow-Origin={permitido!r}")
        if previa.status_code not in (200, 204):
            problemas.append(f"preflight → HTTP {previa.status_code}")
        if "POST" not in (previa.headers.get("Access-Control-Allow-Methods") or ""):
            problemas.append("el preflight no autoriza POST")
        return not problemas, " · ".join(problemas)

    runner.check(1, "La cabecera CORS está en la respuesta real y en el "
                    "preflight OPTIONS", cors_en_la_respuesta_real_y_en_el_preflight)

    def un_agente_sin_registrar_da_404_y_no_500():
        respuesta = pedir(servidor, "POST", "/step/1",
                          {"project": project, "agent": str(uuid.uuid4())})
        datos = sobre(respuesta)
        return respuesta.status_code == 404 and datos["status"] == "error", \
            f"HTTP {respuesta.status_code}: {' '.join(datos['log'])[:120]}"

    runner.check(1, "Un agente que no está dado de alta responde 404 con su "
                    "motivo, no un 500", un_agente_sin_registrar_da_404_y_no_500)

    def los_destinos_protegidos_se_rechazan_antes_de_llamar_a_nada():
        """La guarda del servidor, probada por comportamiento: si respondiera
        403 *después* de leer, ya habría leído."""
        problemas = []
        casos = [("POST", "/step/1", {"project": "floristeria-petal-digital",
                                      "agent": "745375ba-ac7e-4eb8-b8a0-d742891f2aa4"}),
                 ("POST", "/step/1", {"project": "floristeria-petal-digital",
                                      "agent": agent_id}),
                 ("POST", "/step/1", {"project": project,
                                      "agent": "cea66b60-192d-4b5a-af10-28f8661032e0"}),
                 ("GET", "/discover?project=floristeria-petal-digital", None)]
        for metodo, ruta, cuerpo in casos:
            respuesta = pedir(servidor, metodo, ruta, cuerpo)
            datos = sobre(respuesta)
            if respuesta.status_code != 403:
                problemas.append(f"{ruta} {str(cuerpo)[:40]} → {respuesta.status_code}")
            if datos["data"].get("reason") != "destino_protegido":
                problemas.append(f"{ruta}: sin motivo declarado")
        return not problemas, " · ".join(problemas)

    runner.check(1, "Un destino protegido se rechaza con 403 antes de emitir "
                    "ninguna llamada",
                 los_destinos_protegidos_se_rechazan_antes_de_llamar_a_nada)

    def el_paso_1_trae_los_tres_grupos_que_el_panel_pinta():
        datos = sobre(pedir(servidor, "POST", "/step/1", destino))["data"]
        faltan = [g for g in ("emparejados", "solo_cx", "solo_repo")
                  if g not in datos]
        listas = [g for g in ("emparejados", "solo_cx", "solo_repo")
                  if g in datos and not isinstance(datos[g], list)]
        return not faltan and not listas, f"faltan {faltan} · no son listas {listas}"

    runner.check(1, "La respuesta del Paso 1 trae los tres grupos que el panel "
                    "espera pintar: emparejados, solo en CX, solo en el repositorio",
                 el_paso_1_trae_los_tres_grupos_que_el_panel_pinta)

    def el_descubrimiento_marca_el_repositorio_de_cada_agente():
        datos = sobre(pedir(servidor, "GET",
                            f"/discover?project={project}"))["data"]
        agentes = datos.get("agentes") or []
        mio = [a for a in agentes if a["agentId"] == agent_id]
        if not mio:
            return False, "el agente desechable no sale en el descubrimiento"
        campos = [c for c in ("repo", "rama", "vinculado", "registrado")
                  if c not in mio[0]]
        return not campos, f"al agente le faltan {campos}"

    runner.check(1, "El descubrimiento devuelve, por agente, el repositorio que "
                    "le toca y si está dado de alta",
                 el_descubrimiento_marca_el_repositorio_de_cada_agente)


# ── Nivel 2 · Conexión real ──────────────────────────────────────────────────

def _sin_volatiles(data):
    """Quita de una respuesta lo que cambia entre dos llamadas idénticas."""
    limpio = dict(data)
    for campo in ("registrado_en", "vinculado_en", "guardado_en"):
        limpio.pop(campo, None)
    return limpio


def nivel_2(runner, servidor, project, agent_id):
    print("\nNIVEL 2 — Conexión real · el endpoint contra su función")

    destino = {"project": project, "agent": agent_id}
    mapeo = store.get_agent_mapping(store.get_client(), project, agent_id)

    def _comparar(nombre, ruta, cuerpo, llamada, metodo="POST"):
        """Golpea el endpoint y llama a la función, y exige el mismo resultado.

        Un endpoint que devolviera datos de ejemplo pasaría todos los checks de
        estructura del Nivel 1 sin estar conectado a nada.
        """
        def check():
            por_http = sobre(pedir(servidor, metodo, ruta, cuerpo))
            directo = llamada()
            del_http = _sin_volatiles(por_http["data"])
            de_la_funcion = _sin_volatiles(directo["data"])
            if del_http != de_la_funcion:
                difieren = sorted(
                    campo for campo in set(del_http) | set(de_la_funcion)
                    if del_http.get(campo) != de_la_funcion.get(campo))
                return False, f"difieren en {difieren}"
            if por_http["status"] != directo["status"]:
                return False, (f"status {por_http['status']} vs "
                               f"{directo['status']}")
            return True, ""
        runner.check(2, f"{nombre}: el endpoint devuelve lo mismo que su función",
                     check)

    _comparar("Paso 1 · Inventario", "/step/1", destino,
              lambda: pipeline.step_1_inventory(project, agent_id))

    _comparar("Paso 2 · Traer al repositorio (sin nada que traer)", "/step/2",
              {**destino, "traer": []},
              lambda: pipeline.step_2_pull_to_repo(project, agent_id, []))

    _comparar("Paso 3 · Aplicar (dry-run)", "/step/3",
              {**destino, "dry_run": True},
              lambda: pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True))

    _comparar("Paso 4 · Validar tests", "/step/4",
              {**destino, "resultado": "fallidos"},
              lambda: pipeline.step_4_validate_tests(project, agent_id, "fallidos"))

    _comparar("Paso 5 · Publicar (parado en su candado)", "/step/5",
              {**destino, "version_label": f"{PREFIJO}_comparacion"},
              lambda: pipeline.step_5_publish(project, agent_id,
                                              f"{PREFIJO}_comparacion"))

    _comparar("Descubrimiento", f"/discover?project={project}", None,
              lambda: pipeline.discover(project), metodo="GET")

    _comparar("Alta de agente (ya dado de alta)", "/register-agent",
              {**destino, "region": mapeo["region"], "rama": mapeo["rama"],
               "carpeta_raiz": mapeo.get("carpeta_raiz", "definitions")},
              lambda: pipeline.register_agent(
                  project, agent_id, region=mapeo["region"], rama=mapeo["rama"],
                  carpeta_raiz=mapeo.get("carpeta_raiz", "definitions")))

    _comparar("Vincular proyecto y repositorio (ya vinculado)",
              "/link-project-repo",
              {"project": project, "repo_url": f"https://github.com/{mapeo['repo']}",
               "rama_principal": mapeo["rama_principal"]},
              lambda: pipeline.link_project_repo(
                  project, f"https://github.com/{mapeo['repo']}",
                  mapeo["rama_principal"]))

    _comparar("Versiones existentes", "/manage-versions",
              {**destino, "action": "list"},
              lambda: pipeline.manage_versions(project, agent_id, action="list"))

    def el_argumento_llega_de_verdad_a_la_funcion():
        """Comparar respuestas iguales no distingue un endpoint conectado de uno
        que devuelva siempre lo mismo. Se le manda algo que solo la función real
        puede rechazar, y se compara el motivo palabra por palabra."""
        respuesta = pedir(servidor, "POST", "/step/2",
                          {**destino, "traer": [{"tipo": "intent",
                                                 "cx_id": "no-existo"}]})
        por_http = " ".join(sobre(respuesta)["log"] or [])
        try:
            pipeline.step_2_pull_to_repo(project, agent_id,
                                         [{"tipo": "intent", "cx_id": "no-existo"}])
            return False, "la función no rechazó lo que el endpoint sí rechazó"
        except pipeline.PipelineError as error:
            return str(error) in por_http, (
                f"HTTP dijo {por_http[:90]!r} y la función {str(error)[:90]!r}")

    runner.check(2, "Un argumento inválido llega hasta la función y vuelve con "
                    "su mismo mensaje", el_argumento_llega_de_verdad_a_la_funcion)

    def dry_run_no_cambia_el_estado_del_agente():
        """No se comprueba lo que el servidor dice que hizo, sino el estado del
        agente antes y después."""
        antes = pipeline._huella_borrador(
            pipeline.inventariar_cx(pipeline.Contexto(project, agent_id))[0])
        respuesta = sobre(pedir(servidor, "POST", "/step/3",
                                {**destino, "dry_run": True}))
        despues = pipeline._huella_borrador(
            pipeline.inventariar_cx(pipeline.Contexto(project, agent_id))[0])
        return antes == despues and respuesta["data"].get("dry_run") is True, (
            f"la huella del borrador cambió: {antes} → {despues}")

    runner.check(2, "dry_run no escribe: la huella del borrador es idéntica "
                    "antes y después", dry_run_no_cambia_el_estado_del_agente)


# ── Nivel 3 · Escritura real por HTTP ────────────────────────────────────────

def _desanclar_lo_de_las_pruebas(contexto, inventario):
    """Quita de los entornos las versiones de resources de prueba.

    Es el primer eslabón de la cadena de residuo: publicar fija en producción
    la versión de un resource de prueba, y mientras siga fijada CX se niega a
    borrar el resource — *"still referenced in the following environments"*.
    """
    desancladas = 0
    for entorno in list(inventario.get("environment", {}).values()):
        fijadas = [c["version"] for c in entorno.get("versionConfigs", [])]
        sobreviven = []
        for version in fijadas:
            padre = version.rsplit("/versions/", 1)[0]
            respuesta = cx.api_get(contexto.project, contexto.region, padre)
            nombre = (respuesta.json().get("displayName", "")
                      if respuesta.status_code == 200 else "")
            if str(nombre).startswith(PREFIJO):
                desancladas += 1
            else:
                sobreviven.append(version)
        if len(sobreviven) != len(fijadas):
            pipeline._apuntar_entorno(contexto, entorno, sobreviven)
    return desancladas


def _barrer(contexto):
    """Borra de CX todo lo que lleve el prefijo de este validador.

    Al empezar y al terminar. Al empezar porque un `finally` no sobrevive a un
    SIGKILL: el residuo de una corrida que murió a medias se limpia en la
    siguiente, no se acumula para siempre.

    **Lo que un entorno sigue fijando tras desanclar no es residuo.** Por
    construcción solo puede ser una versión de un contenedor legítimo del
    agente —el flow de arranque, un playbook suyo— que lleva el prefijo porque
    el validador publicó con ese nombre, no porque el contenedor sea de prueba.
    Producción tiene que apuntar a alguna versión de esos contenedores, y el
    flow de arranque ni siquiera se puede desanclar: CX exige versión para todo
    flow alcanzable desde él. Contarlas como suciedad convertía una corrida
    correcta en dos FAIL — pasó, y el mismo criterio ya estaba corregido en
    `validate_pipeline_cloudrun.py`. Se devuelven aparte, para que se vean sin
    contarse como residuo.
    """
    inventario, _, _ = pipeline.inventariar_cx(contexto)
    desancladas = _desanclar_lo_de_las_pruebas(contexto, inventario)
    inventario, _, _ = pipeline.inventariar_cx(contexto)
    en_uso = {c["version"]
              for e in inventario.get("environment", {}).values()
              for c in e.get("versionConfigs", [])}
    # Las versiones primero: mientras exista una versión de un resource de
    # prueba, CX se niega a borrar el resource.
    objetivos = [i for i in inventario.get("version", {}).values()
                 if _lleva_la_marca("version", i)]
    objetivos += [i for tipo, items in inventario.items() if tipo != "version"
                  for i in items.values() if _lleva_la_marca(tipo, i)]

    borrados, resistentes, servidas = [], [], []
    for item in objetivos:
        if item["name"] in en_uso:
            servidas.append(item["name"])
            continue
        cx.api_delete(contexto.project, contexto.region, item["name"])
        # El borrado se confirma leyendo, nunca por el código de la respuesta.
        if cx.api_get(contexto.project, contexto.region,
                      item["name"]).status_code == 404:
            borrados.append(item["name"])
        else:
            resistentes.append(item["name"])
    return desancladas, borrados, resistentes, servidas


def _limpiar_registros_de_prueba(cliente, project, agent_id):
    """Borra de Firestore los registros de los resources que creó el test.

    Sin esto, el resource desaparece de CX pero su registro se queda diciendo
    que sigue pendiente de publicar, y la publicación siguiente lo cuenta entre
    los suyos. No lo detecta ningún otro check porque no se ve desde CX ni
    desde el repositorio.
    """
    borrados = []
    for clave, registro in store.list_resource_records(cliente, project,
                                                       agent_id).items():
        marca = f"{registro.get('display_name') or ''} {registro.get('archivo') or ''}"
        if PREFIJO in marca:
            (cliente.collection(store.COL_AGENTES)
             .document(f"{project}__{agent_id}")
             .collection(store.SUB_RESOURCES)
             .document(f"{clave[0]}__{clave[1]}").delete())
            borrados.append(clave)
    return borrados


def _forzar_rama(contexto, rama, destino):
    """Devuelve una rama a un commit concreto. Solo contra el desechable."""
    respuesta = requests.patch(
        f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/{rama}",
        headers=contexto.gh._headers(), json={"sha": destino, "force": True},
        timeout=30)
    if respuesta.status_code != 200:
        return False, f"{rama}: HTTP {respuesta.status_code}"
    # GitHub no devuelve el nuevo valor de la referencia al instante tras
    # forzarla: leerlo de inmediato da el anterior.
    for intento in range(5):
        if contexto.gh.branch_head(rama) == destino:
            return True, ""
        time.sleep(1 + intento)
    return False, f"{rama}: no volvió a {destino[:7]}"


def nivel_3(runner, servidor, project, agent_id, run_id):
    print("\nNIVEL 3 — Escritura real por HTTP · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)
    destino = {"project": project, "agent": agent_id}
    etiqueta = f"{PREFIJO}_{run_id}"
    rama_al_empezar = contexto.gh.branch_head(contexto.rama)
    principal_al_empezar = contexto.gh.branch_head(contexto.rama_principal)
    creado = {}

    # El bloque que escribe, dentro de un try/finally: si algo revienta
    # fuera de un check —y `CheckRunner` solo atrapa lo que pasa dentro de
    # uno— la limpieza tiene que correr igual. Un nivel que se cae a mitad
    # sin limpiar deja el agente y la rama como los dejó el último check.
    try:
        runner.check(3, "Barrido de restos de corridas anteriores antes de crear nada",
                     lambda: (lambda r: (not r[2], f"{r[0]} desancladas · "
                                                   f"{len(r[1])} borradas · "
                                                   f"resisten {r[2]} · "
                                                   f"{len(r[3])} las sirve un entorno "
                                                   f"y no se tocan"))(_barrer(contexto)))

        def el_paso_5_se_niega_sin_un_paso_4_superado():
            """El candado del Paso 5, por HTTP. Es el mismo que la Fase 4 probó
            llamando a la función: lo que se comprueba aquí es que sigue puesto
            después de pasar por la capa HTTP, que es donde se pierde sin que nadie
            lo note."""
            respuesta = pedir(servidor, "POST", "/step/5",
                              {**destino, "version_label": etiqueta})
            datos = sobre(respuesta)
            directo = pipeline.step_5_publish(project, agent_id, etiqueta)
            return (datos["status"] == "aborted"
                    and datos["data"]["publicado"] is False
                    and directo["status"] == "aborted"), (
                f"HTTP status={datos['status']} publicado="
                f"{datos['data'].get('publicado')} · función={directo['status']}")

        runner.check(3, "Publicar sin un Paso 4 declarado 'superados' se aborta "
                        "igual por HTTP que llamando a la función",
                     el_paso_5_se_niega_sin_un_paso_4_superado)

        def crear_un_playbook_de_prueba():
            """Un playbook y no un intent: es de los tres tipos que CX versiona, y
            sin eso el Paso 5 no llegaría a crear ninguna versión — justo la parte
            que hay que ver funcionar."""
            respuesta = cx.api_post(
                project, contexto.region, f"{contexto.parent}/playbooks",
                {"displayName": f"{etiqueta}_playbook", "goal": "objetivo de prueba",
                 "playbookType": "ROUTINE",
                 "instruction": {"steps": [{"text": "haz algo"}]}})
            if respuesta.status_code not in (200, 201):
                return False, f"{respuesta.status_code} {respuesta.text[:150]}"
            creado["playbook"] = respuesta.json()["name"]
            creado["cx_id"] = creado["playbook"].rsplit("/", 1)[-1]
            return True, creado["cx_id"]

        runner.check(3, "Crear un resource real en el agente desechable",
                     crear_un_playbook_de_prueba)

        def el_paso_2_lo_trae_al_repositorio_en_un_commit():
            cuerpo = {**destino, "traer": [{"tipo": "playbook",
                                            "cx_id": creado["cx_id"]}]}
            primera = sobre(pedir(servidor, "POST", "/step/2", cuerpo))
            segunda = sobre(pedir(servidor, "POST", "/step/2", cuerpo))
            creado["ruta"] = (primera["data"]["traidos"] or [{}])[0].get("ruta")
            return (bool(primera["data"]["commit"])
                    and segunda["data"]["commit"] is None), (
                f"primera={primera['data']['commit']} "
                f"segunda={segunda['data']['commit']}")

        runner.check(3, "El Paso 2 escribe el resource en el repositorio con un "
                        "commit, y repetirlo no crea un segundo",
                     el_paso_2_lo_trae_al_repositorio_en_un_commit)

        def el_paso_3_aplica_en_cx_lo_que_cambio_en_el_repositorio():
            """Se cambia el YAML en el repositorio y se comprueba en CX que el
            cambio llegó — no que el servidor diga que llegó."""
            contenido = contexto.gh.read_repo_files(contexto.rama)[creado["ruta"]]
            import yaml as _yaml
            documento = _yaml.safe_load(contenido)
            documento["goal"] = f"objetivo cambiado por {etiqueta}"
            contexto.gh.commit_files(
                contexto.rama, {creado["ruta"]: _yaml.safe_dump(
                    documento, allow_unicode=True, sort_keys=False)},
                f"test({PREFIJO}): cambiar el objetivo del playbook de prueba")

            datos = sobre(pedir(servidor, "POST", "/step/3", destino))["data"]
            en_cx = cx.api_get(project, contexto.region, creado["playbook"]).json()
            return (datos["aplicadas"] >= 1
                    and en_cx.get("goal") == f"objetivo cambiado por {etiqueta}"), (
                f"aplicadas={datos.get('aplicadas')} · goal en CX="
                f"{en_cx.get('goal')!r}")

        runner.check(3, "El Paso 3 aplica en CX el cambio hecho en el repositorio, "
                        "verificado leyendo el agente",
                     el_paso_3_aplica_en_cx_lo_que_cambio_en_el_repositorio)

        def el_paso_4_registra_y_abre_el_candado():
            datos = sobre(pedir(servidor, "POST", "/step/4",
                                {**destino, "resultado": "superados"}))["data"]
            creado["huella"] = datos.get("huella_borrador")
            return datos.get("avanza") is True and bool(creado["huella"]), str(datos)

        runner.check(3, "El Paso 4 registra 'superados' y devuelve la huella del "
                        "borrador", el_paso_4_registra_y_abre_el_candado)

        def el_paso_4_no_admite_cualquier_cosa():
            respuesta = pedir(servidor, "POST", "/step/4",
                              {**destino, "resultado": "mas o menos"})
            return respuesta.status_code == 400, f"HTTP {respuesta.status_code}"

        runner.check(3, "Un resultado de tests que no es 'superados' ni 'fallidos' "
                        "se rechaza con 400", el_paso_4_no_admite_cualquier_cosa)

        def publicar_fusiona_versiona_y_apunta_produccion():
            antes = len(sobre(pedir(servidor, "POST", "/manage-versions",
                                    {**destino, "action": "list"}))["data"]["versiones"])
            datos = sobre(pedir(servidor, "POST", "/step/5",
                                {**destino, "version_label": etiqueta}))
            creado["publicacion"] = datos
            if datos["status"] != "ok":
                return False, f"status={datos['status']} · {' '.join(datos['log'])[:180]}"
            d = datos["data"]
            # Se comprueba contra CX y contra GitHub, no contra lo que dice el paso.
            principal = contexto.gh.branch_head(contexto.rama_principal)
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            entorno = pipeline._buscar_entorno(contexto, inventario, "production")
            fijadas = {c["version"] for c in entorno.get("versionConfigs", [])}
            despues = len(inventario.get("version", {}))
            creado["versiones"] = d.get("versiones_creadas") or []
            return (d["fusionado"] and d["publicado"]
                    and principal != principal_al_empezar
                    and creado["versiones"]
                    and set(creado["versiones"]) <= fijadas
                    and despues > antes), (
                f"fusionado={d['fusionado']} publicado={d['publicado']} "
                f"principal movida={principal != principal_al_empezar} "
                f"versiones={creado['versiones']} fijadas={len(fijadas)} "
                f"{antes}→{despues}")

        runner.check(3, "Publicar fusiona la rama, crea la versión y deja producción "
                        "apuntando a ella — verificado en GitHub y en CX",
                     publicar_fusiona_versiona_y_apunta_produccion)

        def publicar_no_borra_ninguna_version_por_su_cuenta():
            """Publicar dejó de podar el 2026-08-10. Se comprueba por HTTP, no solo
            en la función: es el tipo de cambio que se pierde al portarlo."""
            antes = {v["name"] for v in sobre(pedir(
                servidor, "POST", "/manage-versions",
                {**destino, "action": "list"}))["data"]["versiones"]}
            sobre(pedir(servidor, "POST", "/step/4",
                        {**destino, "resultado": "superados"}))
            segunda = sobre(pedir(servidor, "POST", "/step/5",
                                  {**destino, "version_label": f"{etiqueta}_bis"}))
            despues = {v["name"] for v in sobre(pedir(
                servidor, "POST", "/manage-versions",
                {**destino, "action": "list"}))["data"]["versiones"]}
            creado["versiones"] = list(
                set(creado.get("versiones") or [])
                | set(segunda["data"].get("versiones_creadas") or []))
            perdidas = antes - despues
            return not perdidas, f"publicar borró {sorted(perdidas)}"

        runner.check(3, "Publicar no borra ninguna versión por su cuenta — solo "
                        "avisa de las que sobran",
                     publicar_no_borra_ninguna_version_por_su_cuenta)

        def borrar_una_version_en_uso_se_rechaza():
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            entorno = pipeline._buscar_entorno(contexto, inventario, "production")
            en_uso = [c["version"] for c in entorno.get("versionConfigs", [])]
            if not en_uso:
                return False, "producción no está sirviendo ninguna versión"
            datos = sobre(pedir(servidor, "POST", "/manage-versions",
                                {**destino, "action": "delete",
                                 "version_names": [en_uso[0]]}))["data"]
            sigue = cx.api_get(project, contexto.region, en_uso[0]).status_code == 200
            return (datos["protegidas"] == [en_uso[0]] and not datos["borradas"]
                    and sigue), str(datos)

        runner.check(3, "Borrar una versión que sirve un entorno se rechaza, y la "
                        "versión sigue ahí", borrar_una_version_en_uso_se_rechaza)

        def borrar_una_version_de_otro_agente_se_rechaza():
            """La ruta llega del cliente: el servidor la comprueba contra el destino
            elegido antes de tocarla (C3)."""
            ajena = (f"projects/{project}/locations/{contexto.region}/agents/"
                     f"{uuid.uuid4()}/flows/x/versions/1")
            respuesta = pedir(servidor, "POST", "/manage-versions",
                              {**destino, "action": "delete", "version_names": [ajena]})
            return respuesta.status_code == 400, f"HTTP {respuesta.status_code}"

        runner.check(3, "Borrar una versión que no es del agente elegido se rechaza",
                     borrar_una_version_de_otro_agente_se_rechaza)

        def borrar_una_version_libre_funciona_y_se_confirma_leyendo():
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            en_uso = {c["version"]
                      for e in inventario.get("environment", {}).values()
                      for c in e.get("versionConfigs", [])}
            libres = [v["name"] for v in inventario.get("version", {}).values()
                      if _lleva_la_marca("version", v) and v["name"] not in en_uso]
            if not libres:
                return True, "(no quedó ninguna versión de prueba libre que borrar)"
            datos = sobre(pedir(servidor, "POST", "/manage-versions",
                                {**destino, "action": "delete",
                                 "version_names": [libres[0]]}))["data"]
            ido = cx.api_get(project, contexto.region, libres[0]).status_code == 404
            return datos["borradas"] == [libres[0]] and ido, (
                f"{datos} · ¿desapareció de CX?={ido}")

        runner.check(3, "Borrar una versión libre la borra de verdad, confirmado "
                        "leyendo el resultado",
                     borrar_una_version_libre_funciona_y_se_confirma_leyendo)

    finally:
        # ── Limpieza ────────────────────────────────────────────────────────────

        def cero_residuo_en_cx():
            desancladas, borrados, resisten, servidas = _barrer(contexto)
            return not resisten, (f"{desancladas} desancladas · {len(borrados)} "
                                  f"borrados · resisten {resisten} · "
                                  f"{len(servidas)} las sirve un entorno y no se tocan")

        runner.check(3, "Cero residuo en CX: lo creado se borra y el borrado se "
                        "confirma leyendo", cero_residuo_en_cx)

        def cero_residuo_en_el_repositorio():
            fallos = []
            for rama, sha in ((contexto.rama, rama_al_empezar),
                              (contexto.rama_principal, principal_al_empezar)):
                if contexto.gh.branch_head(rama) == sha:
                    continue
                ok, detalle = _forzar_rama(contexto, rama, sha)
                if not ok:
                    fallos.append(detalle)
            return not fallos, " · ".join(fallos)

        runner.check(3, "Cero residuo en el repositorio: las dos ramas vuelven al "
                        "commit en el que estaban", cero_residuo_en_el_repositorio)

        def el_candado_queda_libre_y_firestore_sin_registros_de_prueba():
            cliente = store.get_client()
            borrados = _limpiar_registros_de_prueba(cliente, project, agent_id)
            cliente.collection(store.COL_VERSIONES_EN_VUELO).document(
                f"{project}__{agent_id}").delete()
            candado = cliente.collection(store.COL_CANDADOS).document(project).get()
            if not candado.exists:
                return True, f"{len(borrados)} registros de prueba retirados"
            cliente.collection(store.COL_CANDADOS).document(project).delete()
            return False, ("el nivel dejó el candado tomado; se ha liberado "
                           "explícitamente, sin esperar al TTL")

        runner.check(3, "El candado de Firestore queda libre y no quedan registros "
                        "de prueba en Firestore",
                     el_candado_queda_libre_y_firestore_sin_registros_de_prueba)


    # ── Nivel 4 · Caos ───────────────────────────────────────────────────────────

def nivel_4(runner, servidor, project, agent_id, run_id):
    print("\nNIVEL 4 — Caos · fallo inyectado, timeout y concurrencia")

    contexto = pipeline.Contexto(project, agent_id)
    cliente = store.get_client()
    destino = {"project": project, "agent": agent_id}
    etiqueta = f"{PREFIJO}_{run_id}c"
    rama_al_empezar = contexto.gh.branch_head(contexto.rama)
    principal_al_empezar = contexto.gh.branch_head(contexto.rama_principal)

    def _liberar_candado():
        cliente.collection(store.COL_CANDADOS).document(project).delete()

    def un_candado_tomado_devuelve_409_y_no_escribe():
        """La respuesta que el panel traduce en 'espera a que termine'. Se
        provoca de forma determinista tomando el candado desde fuera: una
        carrera real depende del reloj y podría no solaparse."""
        token = store.acquire_lock(cliente, project, agent_id, "prueba 409")
        try:
            respuesta = pedir(servidor, "POST", "/step/2",
                              {**destino, "traer": []})
            datos = sobre(respuesta)
            return (respuesta.status_code == 409
                    and datos["data"].get("reason") == "ocupado"), \
                f"HTTP {respuesta.status_code}: {' '.join(datos['log'])[:120]}"
        finally:
            store.release_lock(cliente, project, agent_id, token)

    runner.check(4, "Con el candado tomado, un endpoint que escribe responde "
                    "409 y no escribe", un_candado_tomado_devuelve_409_y_no_escribe)

    def dos_peticiones_concurrentes_solo_una_procede():
        """Dos peticiones de escritura a la vez sobre el mismo proyecto. Se usa
        el Paso 2 sin nada que traer porque coge el candado igual y tarda lo
        suficiente —lee el agente entero y el repositorio entero— para que el
        solapamiento sea real, no de milisegundos."""
        respuestas = []

        def lanzar():
            try:
                respuestas.append(pedir(servidor, "POST", "/step/2",
                                        {**destino, "traer": []}).status_code)
            except requests.RequestException as error:
                respuestas.append(repr(error))

        hilos = [threading.Thread(target=lanzar) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        candado = cliente.collection(store.COL_CANDADOS).document(project).get()
        if candado.exists:
            _liberar_candado()
            return False, f"quedó el candado tomado · respuestas {respuestas}"
        return (sorted(respuestas) == [200, 409]), f"respuestas {respuestas}"

    runner.check(4, "Dos peticiones de escritura concurrentes: exactamente una "
                    "procede, y ninguna deja el candado tomado",
                 dos_peticiones_concurrentes_solo_una_procede)

    def el_timeout_del_cliente_no_deja_la_operacion_sin_dueno():
        """El cliente deja de esperar; el servidor sigue. Antes de dar la prueba
        por cerrada hay que mirar si la operación siguió viva, porque puede
        terminar de escribir después de que el test ya reportó lo suyo."""
        antes = contexto.gh.branch_head(contexto.rama)
        respuesta_a_tiempo = None
        try:
            respuesta_a_tiempo = pedir(servidor, "POST", "/step/2",
                                       {**destino, "traer": []}, timeout=0.4)
        except requests.Timeout:
            pass
        except requests.RequestException as error:
            return False, f"falló por otra razón: {error!r}"
        if respuesta_a_tiempo is not None:
            return True, "(el servidor contestó antes del timeout: no se pudo probar)"

        # El cliente ya no espera. Hay que observar el efecto real, y para eso
        # hacen falta las dos mitades: primero que la operación *empiece* y
        # luego que *acabe*.
        #
        # Mirar solo si el candado está libre no vale, y es un error que este
        # check cometió: cuando el cliente se rinde a los 0,4 s el servidor
        # todavía está construyendo el contexto y aún no ha cogido el candado,
        # así que "libre" significaba "no ha empezado" y el check daba la
        # operación por terminada. La siguiente petición se comía un 409 de una
        # operación que este check había declarado cerrada.
        def _esperar_candado(tomado, segundos):
            limite = time.time() + segundos
            while time.time() < limite:
                existe = cliente.collection(
                    store.COL_CANDADOS).document(project).get().exists
                if existe == tomado:
                    return True
                time.sleep(1)
            return False

        if not _esperar_candado(True, 90):
            return False, ("la operación no llegó a coger el candado: no se "
                           "puede saber si siguió viva")
        if not _esperar_candado(False, 300):
            _liberar_candado()
            return False, "la operación no terminó y dejó el candado tomado"
        despues = contexto.gh.branch_head(contexto.rama)
        return True, (f"la operación siguió viva tras el timeout y terminó sola "
                      f"· rama {'sin mover' if antes == despues else 'movida: ' + despues[:7]}")

    runner.check(4, "Si el cliente hace timeout, el test comprueba si la "
                    "operación siguió viva antes de darse por cerrado",
                 el_timeout_del_cliente_no_deja_la_operacion_sin_dueno)

    # ── SIGKILL a mitad de una escritura ────────────────────────────────────

    estado_del_sigkill = {}

    # Igual que el Nivel 3: lo que escribe va dentro de un try/finally,
    # porque este nivel mata el servidor a propósito y es donde más fácil
    # es que algo salga por un camino que ningún check envuelve.
    try:
        def preparar_una_publicacion_de_verdad():
            """Deja el destino con un cambio pendiente y el Paso 4 superado.

            Sin esto, matar el servidor durante el Paso 5 lo mataría mientras lee:
            no habría ninguna escritura a medias que observar, y el check pasaría
            sin haber probado lo que dice probar.
            """
            respuesta = cx.api_post(
                project, contexto.region, f"{contexto.parent}/playbooks",
                {"displayName": f"{etiqueta}_playbook", "goal": "objetivo de caos",
                 "playbookType": "ROUTINE",
                 "instruction": {"steps": [{"text": "haz algo"}]}})
            if respuesta.status_code not in (200, 201):
                return False, f"{respuesta.status_code} {respuesta.text[:150]}"
            cx_id = respuesta.json()["name"].rsplit("/", 1)[-1]
            pull = pedir(servidor, "POST", "/step/2",
                         {**destino, "traer": [{"tipo": "playbook", "cx_id": cx_id}]})
            traido = sobre(pull)
            if traido["status"] != "ok":
                return False, (f"el Paso 2 falló con HTTP {pull.status_code}: "
                               f"{' '.join(traido['log'])[:220]}")
            ruta = (traido["data"]["traidos"] or [{}])[0].get("ruta")
            if not ruta:
                return False, f"el Paso 2 no trajo el playbook: {traido['data']}"
            import yaml as _yaml
            documento = _yaml.safe_load(contexto.gh.read_repo_files(contexto.rama)[ruta])
            documento["goal"] = f"objetivo cambiado por {etiqueta}"
            contexto.gh.commit_files(
                contexto.rama, {ruta: _yaml.safe_dump(documento, allow_unicode=True,
                                                      sort_keys=False)},
                f"test({PREFIJO}): preparar el caso de caos")
            aplicadas = sobre(pedir(servidor, "POST", "/step/3", destino))["data"]
            sobre(pedir(servidor, "POST", "/step/4",
                        {**destino, "resultado": "superados"}))
            return aplicadas["aplicadas"] >= 1, f"aplicadas={aplicadas['aplicadas']}"

        runner.check(4, "Preparar una publicación real que dejar a medias",
                     preparar_una_publicacion_de_verdad)

        def matar_el_servidor_a_mitad_de_publicar():
            """SIGKILL mientras publica: ni `finally`, ni cierre ordenado.

            Publicar es la escritura larga y en varios tramos —fusionar, versionar,
            apuntar producción—, así que es donde matar de golpe puede dejar algo a
            medias de verdad. El momento no se elige por reloj sino leyendo el
            registro del propio servidor: se espera a que anuncie el tramo que
            versiona, y se le mata ahí. Con un `sleep` fijo la muerte caía a veces
            mientras solo leía, y entonces el check pasaba sin haber probado nada.

            Lo que se comprueba después: que el candado se queda tomado y con
            caducidad —la garantía es el TTL, no un `finally` que un proceso muerto
            de golpe nunca ejecuta— y que lo que llegara a crearse es identificable
            por su prefijo. Que la corrida siguiente arranque limpia lo comprueba el
            check de después.
            """
            propio = Servidor()
            tramo = ""
            with propio:
                fallo = {}

                def publicar():
                    try:
                        pedir(propio, "POST", "/step/5",
                              {**destino, "version_label": etiqueta}, timeout=600)
                    except requests.RequestException as error:
                        fallo["error"] = type(error).__name__

                hilo = threading.Thread(target=publicar, daemon=True)
                hilo.start()
                limite = time.time() + 240
                while time.time() < limite:
                    registro = propio.log()
                    if "2/3 Versionando" in registro:
                        tramo = "versionando"
                        break
                    if "1/3 Fusionando" in registro:
                        tramo = "fusionando"
                    if not hilo.is_alive():
                        break
                    time.sleep(0.25)
                tomado = cliente.collection(
                    store.COL_CANDADOS).document(project).get().exists
                propio.matar_de_golpe()
                hilo.join(timeout=30)
                estado_del_sigkill["registro"] = propio.log()[-600:]

            candado = cliente.collection(store.COL_CANDADOS).document(project).get()
            estado_del_sigkill["tramo"] = tramo
            if not tramo:
                return False, "el Paso 5 no llegó a escribir: la prueba sería nula"
            if not tomado:
                return False, "el servidor no tenía el candado al matarlo"
            if not candado.exists:
                return False, ("el candado desapareció sin que nadie lo soltara: un "
                               "proceso muerto de golpe no ejecuta ningún finally")
            caduca = candado.to_dict().get("expires_at")
            return bool(caduca), (
                f"muerto en el tramo «{tramo}» · el candado quedó tomado y caduca "
                f"el {caduca} · cliente: {fallo.get('error', 'sin error')}")

        runner.check(4, "Matar el servidor con SIGKILL a mitad de publicar deja el "
                        "candado tomado con caducidad — se libera por TTL, no por "
                        "un finally que no llega a correr",
                     matar_el_servidor_a_mitad_de_publicar)

    finally:
        def la_corrida_siguiente_arranca_limpia():
            """El candado se libera explícitamente, sin esperar al TTL, y se barre
            lo que la muerte súbita dejara a medias. Luego se comprueba que un
            servidor nuevo puede volver a escribir."""
            _liberar_candado()
            desancladas, borrados, resisten, servidas = _barrer(contexto)
            fallos = []
            for rama, sha in ((contexto.rama, rama_al_empezar),
                              (contexto.rama_principal, principal_al_empezar)):
                if contexto.gh.branch_head(rama) != sha:
                    ok, detalle = _forzar_rama(contexto, rama, sha)
                    if not ok:
                        fallos.append(detalle)
            cliente.collection(store.COL_VERSIONES_EN_VUELO).document(
                f"{project}__{agent_id}").delete()
            registros = _limpiar_registros_de_prueba(cliente, project, agent_id)
            with Servidor() as nuevo:
                respuesta = pedir(nuevo, "POST", "/step/2", {**destino, "traer": []})
                if respuesta.status_code != 200:
                    fallos.append(f"un servidor nuevo no puede escribir: "
                                  f"HTTP {respuesta.status_code}")
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            # Lo que un entorno sirve no cuenta como resto, por la misma razón
            # que en `_barrer`: es una versión de un contenedor legítimo del
            # agente que lleva el prefijo porque el validador publicó con ese
            # nombre. Producción tiene que apuntar a alguna, y el flow de
            # arranque no se puede desanclar.
            servidas = {c["version"]
                        for e in inventario.get("environment", {}).values()
                        for c in e.get("versionConfigs", [])}
            restos = [i["name"] for t, items in inventario.items()
                      for i in items.values()
                      if _lleva_la_marca(t, i) and i["name"] not in servidas]
            if restos:
                fallos.append(f"quedan resources con el prefijo: {restos}")
            return not fallos, (" · ".join(fallos) or
                                f"muerto en «{estado_del_sigkill.get('tramo')}» · "
                                f"{desancladas} desancladas · {len(borrados)} "
                                f"borradas · {len(registros)} registros retirados")

        runner.check(4, "Tras el SIGKILL, se libera el candado explícitamente, no "
                        "queda ninguna versión a medio crear y la corrida siguiente "
                        "arranca limpia", la_corrida_siguiente_arranca_limpia)

    def sin_fugas_entre_agentes_en_el_mismo_proceso():
        """Cloud Run reutiliza el contenedor entre peticiones de agentes
        distintos. Una cabecera de cuota cacheada se filtraría de uno a otro."""
        return (cx.get_headers("proyecto-a")["x-goog-user-project"] == "proyecto-a"
                and cx.get_headers("proyecto-b")["x-goog-user-project"] == "proyecto-b"), \
            "la cabecera x-goog-user-project se está cacheando"

    runner.check(4, "La cabecera de cuota no se cachea entre peticiones de "
                    "agentes distintos", sin_fugas_entre_agentes_en_el_mismo_proceso)

    def el_descubrimiento_sin_permiso_de_resource_manager():
        """El caso se fuerza dentro del servidor real —mismo proceso, mismo
        endpoint— con una precarga que hace fallar la llamada a Resource
        Manager igual que fallaría sin el permiso. Lo que se observa es la
        respuesta real, no una cadena de texto en el código fuente.

        **No es el criterio completo.** Retirar el permiso de verdad exige
        tocar IAM, que es un gate del proyecto: queda pendiente de Jero.
        """
        # `sitecustomize` se importa antes de que el servidor añada la raíz del
        # repositorio a `sys.path`, así que hay que añadirla aquí o el import
        # falla en silencio y la precarga no llega a aplicarse — el check
        # pasaría creyendo que forzó un caso que nunca se forzó.
        precarga = (
            f"import sys\nsys.path.insert(0, {str(REPO_ROOT)!r})\n"
            "from act.utils import cx_client_cloudrun as cx\n"
            "def _sin_permiso(*a, **k):\n"
            "    raise cx.ProjectListPermissionError(\n"
            "        'Sin permiso para listar proyectos GCP: falta "
            "resourcemanager.projects.list en Cloud Resource Manager. "
            "Escribe el ID del proyecto a mano.', status_code=403)\n"
            "cx.list_gcp_projects = _sin_permiso\n"
        )
        with Servidor(precarga=precarga) as sin_permiso:
            if MARCA_PRECARGA not in sin_permiso.log():
                return False, ("la precarga no llegó a aplicarse: el caso no se "
                               "forzó y el check no probaría nada")
            respuesta = pedir(sin_permiso, "GET", "/discover")
            datos = sobre(respuesta)
            texto = " ".join(datos["log"])
            return (respuesta.status_code == 403
                    and datos["data"].get("reason") == "missing_permission"
                    and datos["data"].get("manual_entry") is True
                    and "Traceback" not in texto), \
                f"HTTP {respuesta.status_code} · {texto[:140]} · {datos['data']}"

    runner.check(4, "Sin permiso de Resource Manager, el Descubrimiento "
                    "responde 403 con salida ofrecida, no un 500 crudo",
                 el_descubrimiento_sin_permiso_de_resource_manager)

    runner.skip(4, "Retirar de verdad el permiso de Resource Manager con "
                   "add/remove-iam-policy-binding y repetir",
                "IAM es un gate del proyecto (CLAUDE.md §7.1 y §8.2): el "
                "criterio se cubre aquí forzando el fallo dentro del servidor, "
                "pero quitar el binding de verdad lo tiene que autorizar Jero.")

    # ── Vincular un proyecto que nunca tuvo documento ────────────────────────

    def vincular_no_deja_un_documento_a_medias_si_falla():
        """Si el repositorio no se puede leer, no se registra nada.

        Es la mitad comprobable del criterio de onboarding: la otra mitad
        —provocarlo con un fallo de IAM— exige tocar IAM. El fallo se provoca
        con un repositorio al que la App no llega, que produce el mismo camino:
        revienta antes de escribir en Firestore.
        """
        inventado = f"proyecto-que-no-existe-{run_id}"
        antes = cliente.collection(store.COL_PROYECTOS).document(inventado).get().exists
        respuesta = pedir(servidor, "POST", "/link-project-repo", {
            "project": inventado,
            "repo_url": f"https://github.com/jeronimosanchez/no-existe-{run_id}",
        })
        despues = cliente.collection(store.COL_PROYECTOS).document(inventado).get().exists
        if despues:
            cliente.collection(store.COL_PROYECTOS).document(inventado).delete()
        return (respuesta.status_code >= 400 and not antes and not despues), (
            f"HTTP {respuesta.status_code} · documento creado={despues}")

    runner.check(4, "Vincular un proyecto cuyo repositorio no se puede leer "
                    "falla sin dejar un documento a medias en Firestore",
                 vincular_no_deja_un_documento_a_medias_si_falla)

    def vincular_un_proyecto_sin_documento_previo_lo_crea_bien():
        """El vínculo se rehace desde cero: se borra el documento del proyecto
        —es el del destino desechable, creado por esta misma tarea— y se llama
        al endpoint real, como haría un proyecto que nunca se vinculó.

        No sustituye al criterio completo, que pide un tercer proyecto GCP
        desechable: aquí el proyecto ya existía en GCP, lo que no existía era su
        documento. La parte que se prueba de verdad es la que solo ocurre la
        primera vez: crear el registro con su esquema.
        """
        mapeo = store.get_project_mapping(cliente, project)
        cliente.collection(store.COL_PROYECTOS).document(project).delete()
        try:
            respuesta = pedir(servidor, "POST", "/link-project-repo", {
                "project": project,
                "repo_url": f"https://github.com/{mapeo['repo']}",
                "rama_principal": mapeo["rama_principal"]})
            datos = sobre(respuesta)
            documento = cliente.collection(
                store.COL_PROYECTOS).document(project).get().to_dict() or {}
            faltan = [c for c in store.CAMPOS_OBLIGATORIOS_PROYECTO
                      if not documento.get(c)]
            return (respuesta.status_code == 200
                    and datos["data"]["ya_estaba"] is False
                    and not faltan
                    and documento["repo"] == mapeo["repo"]), (
                f"HTTP {respuesta.status_code} · ya_estaba="
                f"{datos['data'].get('ya_estaba')} · faltan {faltan}")
        finally:
            # Pase lo que pase, el vínculo vuelve a estar como se encontró.
            store.save_project_mapping(cliente, project, mapeo["repo"],
                                       mapeo["rama_principal"])

    runner.check(4, "Vincular un proyecto sin documento previo lo crea con el "
                    "esquema correcto", vincular_un_proyecto_sin_documento_previo_lo_crea_bien)

    def la_region_se_detecta_la_primera_vez():
        """El alta con la región desconocida: se borra el registro del agente y
        se deja que el endpoint la resuelva contra CX, sin pista."""
        mapeo = dict(store.get_agent_mapping(cliente, project, agent_id))
        cliente.collection(store.COL_AGENTES).document(
            f"{project}__{agent_id}").delete()
        try:
            datos = sobre(pedir(servidor, "POST", "/register-agent", {
                **destino, "rama": mapeo["rama"],
                "carpeta_raiz": mapeo.get("carpeta_raiz", "definitions")}))
            return datos["data"]["region"] == mapeo["region"], (
                f"detectó {datos['data'].get('region')} y era {mapeo['region']}")
        finally:
            store.save_agent_mapping(cliente, project, agent_id, mapeo["region"],
                                     mapeo["rama"],
                                     carpeta_raiz=mapeo.get("carpeta_raiz",
                                                            "definitions"))

    runner.check(4, "La región se detecta sola en el alta cuando no se le pasa "
                    "ninguna pista", la_region_se_detecta_la_primera_vez)

    runner.skip(4, "Onboarding contra un tercer proyecto GCP desechable, sin "
                   "ningún documento previo en Firestore",
                "no hay ningún proyecto desechable en la cuenta y crear uno "
                "nuevo no entra en esta tarea: los que existen son el de Petal "
                "y dos que no son desechables. Se cubre parcialmente rehaciendo "
                "el vínculo del destino desde cero.")


# ── Nivel 5 · El contenedor ──────────────────────────────────────────────────

IMAGEN = "act-server-cloudrun:validacion"


def _docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          **kwargs)


def nivel_5(runner, project, agent_id):
    print("\nNIVEL 5 — El contenedor · docker build y el servidor dentro")

    # Tener el binario no basta: en un Mac el demonio vive dentro de una
    # máquina virtual que puede estar parada, y entonces `docker build` no
    # falla por el Dockerfile sino por no encontrar con quién hablar. Se
    # distinguen porque la salida es distinta — uno se instala, el otro se
    # arranca— y porque un FAIL por el demonio parado se lee como un defecto
    # del contenedor que no existe.
    motivo = None
    if shutil.which("docker") is None:
        motivo = "no hay `docker` en el PATH de esta máquina"
    elif _docker("info", "--format", "{{.ServerVersion}}").returncode != 0:
        motivo = ("el demonio de Docker no responde: arráncalo (en un Mac con "
                  "colima, `colima start`) y repite este nivel")
    if motivo:
        for nombre in ("docker build completa sin errores",
                       "El contenedor arranca y responde en el 8080 con datos "
                       "reales",
                       "Dentro del contenedor, sin project o agent responde 400",
                       "Dentro del contenedor, sin credenciales ADC responde con "
                       "un error claro"):
            runner.skip(5, nombre, motivo)
        return

    construida = {}

    def docker_build_completa_sin_errores():
        resultado = _docker("build", "-t", IMAGEN, ".", cwd=str(REPO_ROOT))
        construida["ok"] = resultado.returncode == 0
        return construida["ok"], (resultado.stdout + resultado.stderr)[-500:]

    runner.check(5, "docker build completa sin errores",
                 docker_build_completa_sin_errores)

    if not construida.get("ok"):
        for nombre in ("El contenedor arranca y responde en el 8080 con datos "
                       "reales",
                       "Dentro del contenedor, sin project o agent responde 400",
                       "Dentro del contenedor, sin credenciales ADC responde con "
                       "un error claro"):
            runner.skip(5, nombre, "la imagen no se pudo construir")
        return

    adc = Path.home() / ".config/gcloud"
    puerto = _puerto_libre()

    def _arrancar(nombre, con_credenciales=True, extra=()):
        args = ["run", "--rm", "-d", "--name", nombre, "-p", f"{puerto}:8080",
                "-e", "PORT=8080",
                "-e", f"FIRESTORE_PROJECT={os.environ.get('FIRESTORE_PROJECT','')}",
                "-e", f"GITHUB_APP_ID={os.environ.get('GITHUB_APP_ID','')}",
                "-e", ("GITHUB_APP_SECRET_PROJECT="
                       f"{os.environ.get('GITHUB_APP_SECRET_PROJECT','')}"),
                "-e", "ALLOWED_ORIGIN=*", *extra]
        if con_credenciales:
            # Las credenciales se montan, no se copian en la imagen: dentro de
            # Cloud Run las pone la plataforma y aquí hay que suplirlas de
            # alguna forma para poder hablar con CX.
            args += ["-v", f"{adc}:/adc:ro",
                     "-e", "GOOGLE_APPLICATION_CREDENTIALS=/adc/"
                           "application_default_credentials.json",
                     "-e", "CLOUDSDK_CONFIG=/adc"]
        else:
            args += ["-e", "GCE_METADATA_HOST=127.0.0.1:1",
                     "-e", "GCE_METADATA_IP=127.0.0.1:1"]
        return _docker(*args, IMAGEN)

    def _esperar(url, segundos=60):
        limite = time.time() + segundos
        while time.time() < limite:
            try:
                if requests.get(url, timeout=2).status_code == 200:
                    return True
            except requests.RequestException:
                time.sleep(0.5)
        return False

    base = f"http://127.0.0.1:{puerto}"
    nombre = f"actsrv-validacion-{uuid.uuid4().hex[:6]}"

    def el_contenedor_sirve_datos_reales():
        arranque = _arrancar(nombre)
        if arranque.returncode != 0:
            return False, arranque.stderr[-300:]
        try:
            if not _esperar(f"{base}/health"):
                return False, _docker("logs", nombre).stdout[-400:]
            respuesta = requests.post(f"{base}/step/1", timeout=600,
                                      json={"project": project, "agent": agent_id})
            datos = sobre(respuesta)
            return (respuesta.status_code == 200 and datos["status"] == "ok"
                    and datos["data"]["agent_id"] == agent_id
                    and datos["data"]["total_archivos"] > 0), \
                f"HTTP {respuesta.status_code} · {str(datos['data'])[:160]}"
        finally:
            pass

    runner.check(5, "El contenedor arranca y responde en el 8080 con datos "
                    "reales del agente desechable", el_contenedor_sirve_datos_reales)

    def dentro_del_contenedor_sin_destino_400():
        respuesta = requests.post(f"{base}/step/1", json={"agent": agent_id},
                                  timeout=60)
        return respuesta.status_code == 400, f"HTTP {respuesta.status_code}"

    runner.check(5, "Dentro del contenedor, una petición sin project responde "
                    "400, no 200", dentro_del_contenedor_sin_destino_400)

    _docker("rm", "-f", nombre)

    def dentro_del_contenedor_sin_credenciales_error_claro():
        otro = f"{nombre}-sin-adc"
        arranque = _arrancar(otro, con_credenciales=False)
        if arranque.returncode != 0:
            return False, arranque.stderr[-300:]
        try:
            if not _esperar(f"{base}/health"):
                return False, _docker("logs", otro).stdout[-400:]
            respuesta = requests.get(f"{base}/discover", timeout=120)
            datos = sobre(respuesta)
            texto = " ".join(datos["log"])
            return ("Traceback" not in texto and datos["status"] == "error"
                    and ("credencial" in texto.lower() or "ADC" in texto)), \
                f"HTTP {respuesta.status_code}: {texto[:160]}"
        finally:
            _docker("rm", "-f", otro)

    runner.check(5, "Dentro del contenedor, sin credenciales ADC responde con "
                    "un error claro y no una traza",
                 dentro_del_contenedor_sin_credenciales_error_claro)


# ── Nivel 6 · Cloud Run real, en staging ─────────────────────────────────────

def nivel_6(runner, project, agent_id, servicio, imagen_remota, cuenta_runtime,
            region_servicio, proyecto_servidor):
    print("\nNIVEL 6 — Cloud Run real · staging, con el Service Account de runtime")

    if not (servicio and imagen_remota and cuenta_runtime):
        runner.skip(6, "Desplegar el contenedor a un Cloud Run de staging real",
                    "faltan --staging-service, --staging-image o "
                    "--runtime-service-account")
        return

    def _gcloud(*args):
        return subprocess.run(
            ["gcloud", *args, "--project", proyecto_servidor],
            capture_output=True, text=True)

    desplegado = {}

    def desplegar_el_contenedor_en_staging():
        resultado = _gcloud(
            "run", "deploy", servicio, "--image", imagen_remota,
            "--region", region_servicio, "--service-account", cuenta_runtime,
            "--no-allow-unauthenticated", "--timeout", "3600",
            "--set-env-vars",
            f"FIRESTORE_PROJECT={proyecto_servidor},"
            f"GITHUB_APP_ID={os.environ.get('GITHUB_APP_ID','')},"
            f"GITHUB_APP_SECRET_PROJECT={proyecto_servidor},"
            f"ALLOWED_ORIGIN=*",
            "--format", "value(status.url)")
        if resultado.returncode != 0:
            return False, (resultado.stderr or resultado.stdout)[-400:]
        desplegado["url"] = resultado.stdout.strip().splitlines()[-1]
        return bool(desplegado["url"]), desplegado.get("url", "")

    runner.check(6, "El contenedor se despliega en un Cloud Run de staging con "
                    "el Service Account de runtime real",
                 desplegar_el_contenedor_en_staging)

    if not desplegado.get("url"):
        for nombre in ("Las variables de entorno llegan inyectadas por la "
                       "plataforma, no por un .env local",
                       "El Paso 3 contra el agente desechable, desde el Cloud "
                       "Run de staging"):
            runner.skip(6, nombre, "el servicio no llegó a desplegarse")
        return

    token = subprocess.run(["gcloud", "auth", "print-identity-token"],
                           capture_output=True, text=True).stdout.strip()
    cabeceras = {"Authorization": f"Bearer {token}"}

    def las_variables_llegan_de_la_plataforma():
        """Ninguna sale de un `.env` local, que dentro de Cloud Run no existe.

        `PORT` lo pone la plataforma, y que el servicio conteste ya lo prueba:
        si el servidor escuchara en otro puerto, el health check habría tumbado
        el despliegue antes de darle una URL. `ALLOWED_ORIGIN` se comprueba
        mirando la cabecera que devuelve, que es su único efecto observable.
        """
        salud = requests.get(f"{desplegado['url']}/health", headers=cabeceras,
                             timeout=120)
        if salud.status_code != 200 or sobre(salud)["status"] != "ok":
            return False, f"/health devolvió HTTP {salud.status_code}"
        origen = "http://localhost:4321"
        con_origen = requests.get(f"{desplegado['url']}/health", timeout=120,
                                  headers={**cabeceras, "Origin": origen})
        permitido = con_origen.headers.get("Access-Control-Allow-Origin")
        return permitido in (origen, "*"), (
            f"PORT llegó (el servicio contesta) · Allow-Origin={permitido!r}")

    runner.check(6, "Las variables de entorno que el servidor espera llegan "
                    "inyectadas por la plataforma, no por un .env local",
                 las_variables_llegan_de_la_plataforma)

    def adc_funciona_dentro_de_un_contenedor_de_cloud_run():
        """La asunción que la Fase 5 dejó abierta, cerrada aquí.

        Estaba verificado que ADC funciona desde el Mac con la cabecera de
        cuota; lo que faltaba era comprobarlo dentro de un contenedor real, sin
        sesión humana y con la identidad que inyecta la plataforma. Se
        comprueba con una llamada autenticada de verdad a una API de Google —el
        Descubrimiento sin proyecto va contra Cloud Resource Manager—: si el
        token no valiera, volvería 401 o 403, no 200.
        """
        respuesta = requests.get(f"{desplegado['url']}/discover",
                                 headers=cabeceras, timeout=300)
        datos = sobre(respuesta)
        if respuesta.status_code != 200 or datos["status"] != "ok":
            return False, (f"HTTP {respuesta.status_code}: "
                           f"{' '.join(datos['log'])[:200]}")
        return True, (
            f"llamada autenticada aceptada · {len(datos['data']['proyectos'])} "
            f"proyectos visibles para la cuenta de servicio")

    runner.check(6, "ADC funciona dentro de un contenedor de Cloud Run real, "
                    "con la identidad que inyecta la plataforma y sin sesión "
                    "humana", adc_funciona_dentro_de_un_contenedor_de_cloud_run)

    def el_paso_3_desde_staging():
        """Devuelve (ok, detalle) o None si la respuesta es el hueco de IAM.

        Un 403 aquí no es un fallo del código: es un permiso que a la cuenta de
        servicio de runtime le falta, y concederlo es un gate del proyecto que
        solo puede levantar Jero. Se distingue del resto para no contar como
        FAIL algo que ningún cambio de código arregla — y para no contarlo como
        PASS, que sería peor.
        """
        respuesta = requests.post(
            f"{desplegado['url']}/step/3", headers=cabeceras, timeout=900,
            json={"project": project, "agent": agent_id, "dry_run": True})
        datos = sobre(respuesta)
        texto = " ".join(datos["log"])
        if respuesta.status_code == 200 and datos["status"] == "ok":
            return True, "el Service Account de runtime tiene lo que necesita"
        if respuesta.status_code == 403:
            return None, (
                f"la cuenta {cuenta_runtime} no tiene permisos: «{texto[:120]}». "
                f"El propio 403 llega limpio, con su mensaje y sin traza.")
        return False, f"HTTP {respuesta.status_code} · {texto[:300]}"

    resultado = el_paso_3_desde_staging()
    if resultado[0] is None:
        runner.skip(6, "El Paso 3 contra el agente desechable, desde el Cloud "
                       "Run de staging y con el Service Account de runtime",
                    f"{resultado[1]} Conceder ese permiso es un gate de IAM "
                    f"(CLAUDE.md §7.1 y §8.2): queda pendiente de Jero.")
    else:
        runner.check(6, "El Paso 3 contra el agente desechable, desde el Cloud "
                        "Run de staging y con el Service Account de runtime",
                     lambda: resultado)

    runner.skip(6, "Dos peticiones de escritura concurrentes desde dos "
                   "instancias físicamente distintas del servicio de staging",
                "depende del check anterior: mientras el Service Account de "
                "runtime no pueda escribir, las dos peticiones fallarían antes "
                "de llegar al candado y la prueba no diría nada.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_levels(texto):
    niveles = set()
    for parte in texto.split(","):
        parte = parte.strip()
        if "-" in parte:
            desde, hasta = parte.split("-")
            niveles.update(range(int(desde), int(hasta) + 1))
        elif parte:
            niveles.add(int(parte))
    fuera = [n for n in niveles if not 0 <= n <= 6]
    if fuera:
        raise SystemExit(f"Niveles válidos: 0 a 6. Recibido {fuera}.")
    return sorted(niveles)


def _huella_del_repositorio(project, agent_id):
    """Dónde está cada rama del destino, para comparar antes y después.

    Las dos: publicar fusiona una en otra, así que una corrida puede dejar la
    principal movida sin tocar la de trabajo.
    """
    contexto = pipeline.Contexto(project, agent_id)
    return {contexto.rama: contexto.gh.branch_head(contexto.rama),
            contexto.rama_principal:
                contexto.gh.branch_head(contexto.rama_principal)}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke test del servidor Cloud Run del pipeline ACT.")
    parser.add_argument("--project", help="Proyecto GCP del agente desechable")
    parser.add_argument("--agent", help="ID del agente CX desechable")
    parser.add_argument("--levels", default="0", help="'0', '0-4', '3,5'")
    parser.add_argument("--staging-service", help="Nombre del servicio de staging")
    parser.add_argument("--staging-image", help="Imagen ya subida al registro")
    parser.add_argument("--runtime-service-account",
                        help="Cuenta de servicio de runtime del staging")
    parser.add_argument("--staging-region", default="europe-west1")
    parser.add_argument("--server-project",
                        default=os.environ.get("FIRESTORE_PROJECT"),
                        help="Proyecto donde vive el servicio y Firestore")
    args = parser.parse_args(argv)

    niveles = parse_levels(args.levels)
    runner = CheckRunner()
    run_id = uuid.uuid4().hex[:8]

    necesita_destino = any(n in niveles for n in (1, 2, 3, 4, 5, 6))
    if necesita_destino and not (args.project and args.agent):
        parser.error(
            "Los niveles 1 a 6 exigen --project y --agent. No hay valor por "
            "defecto: un default silencioso convierte una prueba en una "
            "escritura sobre un agente real.")

    if args.project:
        # Las dos barreras, en este orden: la lista de destinos protegidos no
        # necesita salir a la red, así que va primero.
        _comprobar_destino(args.project, args.agent)
        os.environ["VALIDATE_PROJECT"] = args.project

    region = None
    if necesita_destino:
        region, nombre = exigir_agente_desechable(args.project, args.agent)
        if any(n in niveles for n in (3, 4)):
            exigir_rama_principal_desechable(args.project)
        print(f"Destino: {nombre} · {args.project} · {region} · corrida {run_id}")

    huella_inicial = _huella_del_repositorio(args.project, args.agent) \
        if necesita_destino else None

    if 0 in niveles:
        nivel_0(runner)

    if any(n in niveles for n in (1, 2, 3, 4)):
        # Un solo servidor para los cuatro niveles: arrancarlo por nivel
        # multiplicaría el arranque sin probar nada nuevo. Los niveles que
        # necesitan uno propio —el que muere de golpe, el que arranca sin
        # permisos— se lo montan aparte.
        with Servidor() as servidor:
            print(f"Servidor de pruebas en {servidor.url('')}")
            if 1 in niveles:
                nivel_1(runner, servidor, args.project, args.agent)
            if 2 in niveles:
                nivel_2(runner, servidor, args.project, args.agent)
            if 3 in niveles:
                nivel_3(runner, servidor, args.project, args.agent, run_id)
            if 4 in niveles:
                nivel_4(runner, servidor, args.project, args.agent, run_id)

    if 5 in niveles:
        nivel_5(runner, args.project, args.agent)
    if 6 in niveles:
        nivel_6(runner, args.project, args.agent, args.staging_service,
                args.staging_image, args.runtime_service_account,
                args.staging_region, args.server_project)

    if huella_inicial is not None:
        def la_corrida_entera_no_deja_rastro():
            final = _huella_del_repositorio(args.project, args.agent)
            if final == huella_inicial:
                return True, ""
            movidas = [f"{rama}: {huella_inicial[rama][:7]} → {sha[:7]}"
                       for rama, sha in final.items()
                       if huella_inicial.get(rama) != sha]
            return False, " · ".join(movidas)

        runner.check(max(niveles), "La corrida entera devuelve el repositorio "
                                   "como lo encontró, no solo cada nivel el suyo",
                     la_corrida_entera_no_deja_rastro)

    c = runner.counts()
    print(f"\nRESUMEN: {c[PASS]} PASS · {c[FAIL]} FAIL · {c[SKIP]} SKIP")
    if c[SKIP]:
        print("Los SKIP no son cobertura: cada uno dice arriba qué falta para "
              "poder ejecutarlo.")
    return 1 if runner.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
