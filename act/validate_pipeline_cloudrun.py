#!/usr/bin/env python3
"""
act/validate_pipeline_cloudrun.py — Smoke test de act_cx_resources_deploy_cloudrun.py.

Cinco niveles de riesgo creciente. Cada uno se puede lanzar por separado, y
ninguno depende del panel: eso no existe hasta la Fase 7, así que todo se
ejecuta por CLI o llamando a las funciones del pipeline.

    Nivel 0  Estático. Sin red ni credenciales. Atrapa violaciones de
             arquitectura antes de gastar una llamada.
    Nivel 1  Solo lectura contra CX y el repositorio reales. Cero riesgo.
    Nivel 2  Dry-run. No escribe nada real.
    Nivel 3  Escritura real automatizada, contra el agente desechable.
    Nivel 4  Fallo inyectado y concurrencia. El nivel que encuentra lo que no
             se nota: residuos, candados colgados, fugas entre agentes.

**La validación contra un Cloud Run real vive en la Fase 6**, no aquí. El
Build Playbook la describía como un sexto nivel de esta fase, pero exige un
servicio desplegado con su Service Account de runtime — y el servidor y el
Dockerfile son outputs de la Fase 5. Un nivel que solo puede saltarse no es
cobertura: es un hueco con nombre. Va donde se valida el servidor.

**Nunca contra Petal.** Ni siquiera para leer: comparar contra un agente real
que puede cambiar entre dos llamadas produce falsos fallos. El agente destino
tiene que declararse desechable en su propio nombre, y el script se niega a
arrancar si no lo hace — es la única barrera que no depende de acordarse.

**Cero residuo.** Todo lo que crea lleva un prefijo con el identificador de la
corrida, se barre al empezar además de al terminar (un `finally` no sobrevive a
un SIGKILL), y el borrado se confirma leyendo el resultado, nunca el código de
respuesta.

Uso:
    python act/validate_pipeline_cloudrun.py --project P --agent A --levels 0-2
    python act/validate_pipeline_cloudrun.py --project P --agent A --levels 3,4
"""

import argparse
import ast
import inspect
import re
import sys
import time
import uuid
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
# El panel es la especificación: varios checks lo contrastan contra el código.
PANEL = "docs/panels/act_cx_resources_deploy_v2.html"
# Y el que sirve Cloud Run de verdad. Son dos archivos y los dos tienen que
# enseñar lo mismo: un aviso que solo existe en la especificación no lo ve nadie.
PANEL_CLOUDRUN = "docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html"

# El campo con que el Paso 1 cuenta lo que la comparación contra producción
# averiguó, y el `id` con que ese dato aparece en pantalla. Viven aquí porque
# los usan varios checks y el panel: si cambian, cambian en un solo sitio.
CAMPO_COMPARACION = "comparacion_produccion"
ID_AVISO_BORRADOS = "aviso-borrados-produccion"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act import act_cx_resources_deploy_cloudrun as pipeline
from act.utils import cx_client_cloudrun as cx
from act.utils import cx_payloads_cloudrun as payloads
from act.utils import firestore_client_cloudrun as store

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _lleva_la_marca(tipo, item):
    """Si un resource lo creó una corrida de este validador.

    Las **versiones** llevan la marca en `description` cuando cuelgan de un
    playbook, porque ese endpoint no acepta `displayName`. El resto de tipos
    solo en `displayName`: buscar en la descripción de cualquier resource caza
    también los que una prueba se limitó a *modificar* — y así el barrido
    intentaba borrar el flow de arranque del agente, que CX no deja borrar.
    """
    if tipo == "version":
        return PREFIJO in f"{item.get('displayName','')} {item.get('description','')}"
    return str(item.get("displayName", "")).startswith(PREFIJO)


def pathlib_stem(ruta):
    """El nombre del archivo sin carpeta ni extensión."""
    return ruta.rsplit("/", 1)[-1].rsplit(".", 1)[0]

# Marca que un agente tiene que llevar en su nombre para que este script acepte
# escribir en él. No es una lista de agentes prohibidos —una lista se queda
# desactualizada— sino lo contrario: solo se admite lo que se declara
# desechable, así que un agente real nunca pasa por olvido.
MARCA_DESECHABLE = "desechable"

# Prefijo de todo lo que crea una corrida. Permite saber qué borrar y de qué
# ejecución es, incluso si dos corridas se solapan.
PREFIJO = "actval"

# Cuerpo mínimo válido de cada tipo desplegable, para fabricar resources de
# prueba. No es un fixture guardado: se construye en el momento, y solo lleva
# los campos que la API exige para que el POST no se caiga por otra razón.
CUERPO_MINIMO = {
    "intent": {"trainingPhrases": [{"parts": [{"text": "hola"}], "repeatCount": 1}]},
    "entity_type": {"kind": "KIND_MAP",
                    "entities": [{"value": "a", "synonyms": ["a"]}]},
    "webhook": {"genericWebService": {"uri": "https://example.invalid/x"},
                "timeout": "5s"},
    "generator": {"promptText": {"text": "resume"}},
    "playbook": {"goal": "objetivo de prueba", "playbookType": "ROUTINE",
                 "instruction": {"steps": [{"text": "haz algo"}]}},
    "example": {"actions": [{"userUtterance": {"text": "hola"}},
                            {"agentUtterance": {"text": "hola"}}],
                "conversationState": "OUTPUT_STATE_OK"},
    "flow": {},
    "page": {},
    "transition_route_group": {"transitionRoutes": []},
    "tool": {"description": "herramienta de prueba", "openApiSpec": {
        "textSchema": "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n"}},
}

# Archivos del pipeline cloud que el Nivel 0 analiza.
ARCHIVOS_PIPELINE = [
    "act/act_cx_resources_deploy_cloudrun.py",
    "act/utils/cx_client_cloudrun.py",
    "act/utils/cx_payloads_cloudrun.py",
    "act/utils/firestore_client_cloudrun.py",
    "act/utils/github_app_client_cloudrun.py",
]

# Literales que no pueden aparecer en el código del pipeline. Viven aquí, en un
# archivo de test, que es donde el propio criterio del Nivel 0 los admite.
LITERALES_PROHIBIDOS = re.compile(
    r"(floristeria-petal-digital|745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
    r"|cea66b60-192d-4b5a-af10-28f8661032e0|cloud-run-multiproyecto)"
)


class CheckRunner:
    """Recolector de resultados. Una excepción cuenta como FAIL de ese check,
    no como caída del script: un nivel tiene que poder terminar y contarlo."""

    def __init__(self, solo=None):
        self.results = []
        # Filtro por texto del nombre. Sin él, depurar un check exige tragarse
        # el nivel entero —veinticinco minutos por vuelta—, y comprobar que un
        # check caza el defecto que dice cazar cuesta una corrida completa por
        # cada defecto que se inyecta. Con el filtro, esa comprobación pasa de
        # horas a minutos, que es la diferencia entre hacerla y no hacerla.
        #
        # Lo omitido se registra como omitido, nunca se calla: una corrida
        # filtrada no puede leerse después como una corrida completa.
        self.solo = (solo or "").strip().lower() or None
        self.omitidos = 0

    def _pasa_el_filtro(self, name):
        if not self.solo:
            return True
        # El barrido y la limpieza corren SIEMPRE, filtre lo que filtre. No son
        # cobertura, son las que dejan el agente como estaba: filtrarlas
        # convertía cada corrida acotada en un depósito de residuo. Pasó —
        # doce corridas filtradas dejaron siete playbooks vivos y siete
        # punteros de prueba en el entorno de producción, y los validadores
        # siguientes lo declararon todo limpio porque su propio barrido inicial
        # los borraba... después de que otra corrida los hubiera vuelto a
        # publicar. Una herramienta para depurar no puede ensuciar lo que
        # depura.
        if any(m in name.lower() for m in ("barrido", "residuo")):
            return True
        return self.solo in name.lower()

    def check(self, level, name, funcion):
        if not self._pasa_el_filtro(name):
            self.omitidos += 1
            return None
        try:
            resultado = funcion()
            if isinstance(resultado, tuple):
                ok, detalle = resultado
            else:
                ok, detalle = bool(resultado), ""
            self._record(level, name, PASS if ok else FAIL, detalle)
            return ok
        except Exception as error:
            self._record(level, name, FAIL, f"{type(error).__name__}: {error}")
            return False

    def skip(self, level, name, motivo):
        """Un check que no se ejecuta se cuenta y se explica — nunca se calla.

        Un SKIP silencioso se lee después como cobertura que nunca existió.
        """
        self._record(level, name, SKIP, motivo)

    def _record(self, level, name, status, detalle):
        self.results.append((level, name, status, detalle))
        marca = {PASS: "✓", FAIL: "✗", SKIP: "–"}[status]
        print(f"  {marca} [N{level}] {name}")
        if detalle and status != PASS:
            print(f"      {detalle}")

    def failed(self):
        return [r for r in self.results if r[2] == FAIL]

    def counts(self):
        c = {PASS: 0, FAIL: 0, SKIP: 0}
        for _, _, status, _ in self.results:
            c[status] += 1
        return c


# ── Instrumentación ──────────────────────────────────────────────────────────

class ContadorHttp:
    """Cuenta las llamadas del cliente CX por verbo.

    Instrumentar es la única forma de demostrar "solo lectura": inspeccionar el
    código es fiarse de que nadie añadió una escritura sin darse cuenta.
    """

    def __init__(self):
        self.llamadas = []
        self._original = None

    def __enter__(self):
        self._original = cx.api_request

        def espia(method, project, region, path, *args, **kwargs):
            self.llamadas.append((method, path))
            return self._original(method, project, region, path, *args, **kwargs)

        cx.api_request = espia
        return self

    def __exit__(self, *_):
        cx.api_request = self._original
        return False

    def escrituras(self):
        """Las llamadas que mutan el agente.

        `compareVersions` viaja como POST porque lleva cuerpo, pero no muta
        nada: compara dos versiones y devuelve las dos fotos. Contarla como
        escritura haría fallar todo lo que mide «esto no escribe» en cuanto la
        comparación de producción entra en juego, y taparlo caso por caso
        acabaría con cada check llevando su propia excepción. Se nombra aquí una
        sola vez, y `escrituras_crudas` permite demostrar que es la única que
        ocurre — que es lo que impide que esta puerta se ensanche sola.
        """
        return [c for c in self.escrituras_crudas()
                if not any(c[1].endswith(sufijo)
                           for sufijo in LECTURAS_CON_VERBO_DE_ESCRITURA)]

    def escrituras_crudas(self):
        """Todo verbo de escritura, sin excepciones ni criterio."""
        return [c for c in self.llamadas
                if c[0] in ("POST", "PATCH", "DELETE", "PUT")]


# Lo único que puede llegar con verbo de escritura sin serlo. Verificado contra
# la documentación y contra la API: `compareVersions` solo lee.
LECTURAS_CON_VERBO_DE_ESCRITURA = (":compareVersions",)


# ── Agente ficticio · para comparar sin red ──────────────────────────────────
#
# El grueso de la cobertura de la comparación borrador ↔ producción no toca la
# red: se construye un inventario con la forma exacta que devuelve
# `inventariar_cx` —{tipo: {cx_id: item}}— y se le pasa a la función. Así los
# seis casos se prueban sin credenciales, sin agente y sin gastar una llamada.

AGENTE_FICTICIO = "projects/proyecto-ficticio/locations/region-ficticia/agents/agente-ficticio"


class ContextoFicticio:
    """Lo mínimo que la comparación pide de un contexto: dónde llamar."""

    def __init__(self, project="proyecto-ficticio", region="region-ficticia"):
        self.project = project
        self.region = region
        self.parent = AGENTE_FICTICIO


class CompareVersionsFalso:
    """Doble del endpoint de comparación de flows, para el Nivel 0.

    Sustituye `cx.api_request` igual que hace `ContadorHttp`, y contesta según
    lo que se le diga por versión: iguales, distintos, o el estado HTTP que se
    quiera simular. Cualquier llamada que no sea `compareVersions` revienta a
    propósito — si el código toca la red por otro camino, el check tiene que
    enterarse en vez de pasar por casualidad.
    """

    def __init__(self, iguales=True, status=200):
        self.iguales = iguales
        self.status = status
        self.llamadas = []
        self._original = None

    def __enter__(self):
        self._original = cx.api_request

        def doble(method, project, region, path, body=None, **kwargs):
            if not path.endswith(":compareVersions"):
                raise AssertionError(
                    f"El Nivel 0 no habla con la red: {method} {path}"
                )
            self.llamadas.append((method, path, (body or {}).get("targetVersion")))
            iguales = (self.iguales(path) if callable(self.iguales)
                       else self.iguales)
            return _RespuestaFalsa(self.status, {
                "baseVersionContentJson": '{"flow":"publicado"}',
                "targetVersionContentJson": ('{"flow":"publicado"}' if iguales
                                             else '{"flow":"borrador"}'),
                "compareTime": "2026-08-11T00:00:00Z",
            })

        cx.api_request = doble
        return self

    def __exit__(self, *_):
        cx.api_request = self._original
        return False


class _RespuestaFalsa:
    def __init__(self, status_code, cuerpo):
        self.status_code = status_code
        self._cuerpo = cuerpo
        self.text = str(cuerpo)

    def json(self):
        return self._cuerpo


def _ficticio_playbook(cx_id, goal="objetivo", display=None):
    """Un playbook del borrador, con los campos que la API devuelve de más."""
    return {"name": f"{AGENTE_FICTICIO}/playbooks/{cx_id}",
            "displayName": display or cx_id, "goal": goal,
            "playbookType": "ROUTINE",
            "instruction": {"steps": [{"text": "haz algo"}]},
            # Campos que gestiona la API: no pueden contar como contenido.
            "tokenCount": 120, "createTime": "2026-01-01T00:00:00Z"}


def _ficticio_example(cx_id, playbook_id, texto="hola"):
    return {"name": f"{AGENTE_FICTICIO}/playbooks/{playbook_id}/examples/{cx_id}",
            "displayName": cx_id,
            "actions": [{"userUtterance": {"text": texto}},
                        {"agentUtterance": {"text": texto}}],
            "conversationState": "OUTPUT_STATE_OK", "tokenCount": 9}


def _ficticio_tool(cx_id, descripcion="herramienta"):
    return {"name": f"{AGENTE_FICTICIO}/tools/{cx_id}", "displayName": cx_id,
            "description": descripcion, "toolType": "CUSTOMIZED_TOOL",
            "openApiSpec": {"textSchema": "openapi: 3.0.0"}}


def _ficticio_flow(cx_id, display=None):
    return {"name": f"{AGENTE_FICTICIO}/flows/{cx_id}",
            "displayName": display or cx_id, "nluSettings": {}}


def _ficticia_version(contenedor, numero, contenido=None, hijos=None,
                      clave_contenido=None, clave_hijos=None):
    """Una versión con la forma exacta que devuelve el LIST de CX.

    Verificado el 2026-08-11: el LIST de un playbook devuelve `playbook` y
    `examples` en línea, el de un tool devuelve `tool`, y el de un flow no
    devuelve contenido ninguno.
    """
    version = {"name": f"{contenedor}/versions/{numero}",
               "description": "etiqueta", "updateTime": "2026-08-01T00:00:00Z"}
    if clave_contenido:
        version[clave_contenido] = contenido
    if hijos:
        version[clave_hijos] = hijos
    return version


def _ficticio_inventario(playbooks=(), examples=(), tools=(), flows=(),
                         versiones=(), fijadas=(), con_entorno=True):
    """Monta el inventario con las mismas claves que usa `inventariar_cx`.

    Las versiones se indexan por `_clave_de_version` y el resto por su cx_id,
    exactamente como el inventario real: si esa regla cambiara, estos checks
    dejarían de estar probando lo que el Paso 5 recibe.
    """
    inventario = {tipo: {} for tipo in pipeline.RESOURCE_TYPES}
    for tipo, items in (("playbook", playbooks), ("example", examples),
                        ("tool", tools), ("flow", flows)):
        for item in items:
            inventario[tipo][pipeline._cx_id_de(item)] = item
    for version in versiones:
        inventario["version"][pipeline._clave_de_version(version)] = version
    if con_entorno:
        inventario["environment"]["env-ficticio"] = {
            "name": f"{AGENTE_FICTICIO}/environments/env-ficticio",
            "displayName": pipeline.ENTORNO_PRODUCCION,
            "versionConfigs": [{"version": v} for v in fijadas],
        }
    return inventario


def agente_ficticio_completo():
    """Los seis casos de la tabla del encargo, en un solo agente.

        playbook A  contenido idéntico a su versión publicada  → igual
        playbook B  contenido distinto                         → cambiado
        playbook C  en el borrador, sin ninguna versión        → cambiado
        flow F      contenido distinto                         → cambiado
        tool T      contenido idéntico                         → igual
        playbook D  fijado en el entorno, ausente del borrador  → borrado
    """
    a = _ficticio_playbook("A", "objetivo de A")
    b = _ficticio_playbook("B", "objetivo NUEVO de B")
    c = _ficticio_playbook("C", "objetivo de C")
    d_congelado = _ficticio_playbook("D", "objetivo de D")
    t = _ficticio_tool("T")
    f = _ficticio_flow("F")

    versiones = [
        # A: la foto congelada es idéntica al borrador salvo en los campos que
        # gestiona la API — que no pueden contar como contenido.
        _ficticia_version(a["name"], 1,
                          {**a, "tokenCount": 999, "createTime": "2020-01-01T00:00:00Z"},
                          clave_contenido="playbook"),
        # B: la foto congelada tiene el objetivo viejo.
        _ficticia_version(b["name"], 1, {**b, "goal": "objetivo VIEJO de B"},
                          clave_contenido="playbook"),
        _ficticia_version(t["name"], 1, dict(t), clave_contenido="tool"),
        _ficticia_version(f["name"], 1),
        _ficticia_version(d_congelado["name"], 1, d_congelado,
                          clave_contenido="playbook"),
    ]
    fijadas = [v["name"] for v in versiones]
    return _ficticio_inventario(
        playbooks=[a, b, c], tools=[t], flows=[f],
        versiones=versiones, fijadas=fijadas,
    )


def comparar_ficticio(inventario, iguales=True, status=200):
    """Corre la comparación real contra un inventario de mentira."""
    with CompareVersionsFalso(iguales=iguales, status=status):
        return pipeline._contenedores_cambiados(ContextoFicticio(), inventario)


def _nombres(filas):
    return sorted(f["cx_id"] for f in filas)


def contenedor_de_pruebas(contexto, tipo, nombre, marca):
    """Crea —o modifica— un contenedor propio del validador y lo devuelve.

    Cada llamada deja una marca distinta dentro del contenedor, así que llamarla
    dos veces con marcas distintas garantiza que difiere de cualquier versión
    creada antes. Es la forma de provocar «hay algo que publicar» ahora que el
    Paso 5 lo decide mirando el borrador y no leyendo una lista: sembrar una
    anotación en Firestore ya no provoca nada.

    Lleva el prefijo en su nombre para que el barrido de restos lo reconozca.
    Modificar un contenedor que ya estuviera en el agente dejaría su contenido
    cambiado sin que nada lo devolviera a su sitio, porque la limpieza borra por
    nombre y ese no lo lleva.
    """
    spec = pipeline.RESOURCE_TYPES[tipo]
    ruta = f"{contexto.parent}/{spec['api']}"
    existentes = cx.list_all_pages(contexto.project, contexto.region, ruta,
                                   spec["key"])
    actual = next((x for x in existentes if x.get("displayName") == nombre), None)
    cuerpo = {**CUERPO_MINIMO[tipo], "displayName": nombre}
    if tipo == "playbook":
        cuerpo["goal"] = f"objetivo {marca}"
    else:
        cuerpo["description"] = marca

    if actual is None:
        respuesta = cx.api_post(contexto.project, contexto.region, ruta, cuerpo)
    else:
        # Full Update: el remoto entero como base y lo nuevo por encima. Sin la
        # base, un PATCH sin updateMask borra lo que no se menciona.
        fusionado = {**{k: v for k, v in actual.items()
                        if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS},
                     **cuerpo}
        respuesta = cx.api_patch(contexto.project, contexto.region,
                                 actual["name"], fusionado)
    if respuesta.status_code not in (200, 201):
        raise AssertionError(
            f"no se pudo preparar el {tipo} de pruebas {nombre}: "
            f"{respuesta.status_code} {respuesta.text[:150]}"
        )
    return cx.resolve_operation(contexto.project, contexto.region, respuesta)


def versiones_fijadas_ahora(contexto, entorno=None):
    """Qué versión fija cada contenedor en el entorno, releído de CX.

    Releído, no de una foto: comprobar «producción sirve exactamente esto» con
    un inventario de antes de publicar demostraría lo contrario de lo que se
    quiere demostrar.
    """
    inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
    return pipeline._versiones_fijadas(
        inventario, entorno or pipeline.ENTORNO_PRODUCCION)


# ── Barrido de CX · compartido, a propósito ──────────────────────────────────
#
# Vive aquí y no dentro de un nivel porque el Nivel 3 sabía desanclar antes de
# borrar y el Nivel 4 no sabía nada: creaba resources, los publicaba, y su única
# limpieza era la de las ramas. El resultado fue residuo real —cuatro resources
# vivos y cuatro punteros de prueba en el entorno de producción— con la corrida
# declarando «cero residuo». Compartiendo el código, el conocimiento no puede
# estar en un nivel y faltar en el otro.

def desanclar_lo_de_las_pruebas(contexto, project):
    """Quita del entorno las versiones de contenedores que creó una prueba.

    Es el primer eslabón y sin él los otros no se pueden romper: mientras un
    entorno fije una versión suya, CX se niega a borrar el contenedor —
    *"cannot be deleted because it is still referenced in the following
    environments"*. Devuelve cuántas desancló.
    """
    inventario, _, _ = pipeline.inventariar_cx(contexto)
    desancladas = 0
    for entorno in list(inventario.get("environment", {}).values()):
        fijadas = [c["version"] for c in entorno.get("versionConfigs", [])]
        sobreviven = []
        for version in fijadas:
            padre = version.rsplit("/versions/", 1)[0]
            respuesta = cx.api_get(project, contexto.region, padre)
            nombre = (respuesta.json().get("displayName", "")
                      if respuesta.status_code == 200 else "")
            if str(nombre).startswith(PREFIJO):
                desancladas += 1
            else:
                sobreviven.append(version)
        if len(sobreviven) != len(fijadas):
            pipeline._apuntar_entorno(contexto, entorno, sobreviven)
    return desancladas


def barrer_cx_de_las_pruebas(contexto, project, creados=()):
    """Desancla, borra lo que lleva el prefijo, y lo confirma leyendo.

    Las versiones de playbook llevan la marca en `description` y no en
    `displayName`, porque ese endpoint no acepta displayName: buscar solo por
    displayName las dejaba fuera del barrido para siempre y se acumulaban
    contra el límite por playbook.

    Lo que siga fijado **tras** desanclar no es residuo y no hace fallar nada.
    Por construcción solo puede ser una versión de un contenedor legítimo del
    agente —el flow de arranque, un playbook suyo— que lleva la etiqueta de una
    corrida solo porque el validador publicó con ese nombre. Producción tiene
    que apuntar a alguna versión de esos contenedores; borrarla rompería el
    entorno, y el flow de arranque ni siquiera se puede desanclar. Se informa
    para que se vea, pero no se cuenta como suciedad.

    Lo que sí falla es `pendientes`: algo que **no** estaba fijado, que por
    tanto se podía borrar, y que tras el DELETE sigue ahí al releerlo.
    """
    desancladas = desanclar_lo_de_las_pruebas(contexto, project)
    inventario, _, _ = pipeline.inventariar_cx(contexto)
    en_uso = {
        config["version"]
        for entorno in inventario.get("environment", {}).values()
        for config in entorno.get("versionConfigs", [])
    }
    objetivos = set(creados) | {
        item["name"]
        for tipo, items in inventario.items() for item in items.values()
        if _lleva_la_marca(tipo, item)
    }

    pendientes, servidos = [], []
    for nombre in sorted(objetivos):
        if nombre in en_uso:
            servidos.append(nombre.rsplit("/", 1)[-1])
            continue
        cx.api_delete(project, contexto.region, nombre)
        # El borrado se confirma leyendo, no por el código de respuesta.
        if cx.api_get(project, contexto.region, nombre).status_code != 404:
            pendientes.append(nombre)

    partes = []
    if pendientes:
        partes.append(
            f"no se borraron: {[p.rsplit('/', 1)[-1] for p in pendientes]}")
    if desancladas:
        partes.append(f"{desancladas} desancladas")
    if servidos:
        partes.append(
            f"{len(servidos)} versiones de contenedores del agente siguen "
            f"fijadas y no se tocan: {servidos}")
    return not pendientes, " · ".join(partes)


# ── Guardas ──────────────────────────────────────────────────────────────────

# Ramas que este script no puede tocar bajo ningún concepto. El Paso 5 fusiona
# la rama de trabajo en la principal, así que si la principal de un proyecto es
# `main`, probar la publicación escribe en ella. Ocurrió: una tanda de checks
# dejó cinco commits de merge en `main` con nombres como "Publicar
# corte_inyectado en producción".
RAMAS_INTOCABLES = ("main", "master", "produccion", "production")


def exigir_rama_principal_desechable(project, client=None):
    """Se niega a arrancar si publicar acabaría escribiendo en la rama real.

    Nada impedía que un check de publicar fusionara en `main`: el agente estaba
    marcado como desechable, pero la rama principal no la miraba nadie.
    """
    from act.utils import firestore_client_cloudrun as _store
    try:
        proyecto = _store.get_project_mapping(client or _store.get_client(), project)
    except Exception:
        return None
    principal = proyecto.get("rama_principal", "")
    if principal in RAMAS_INTOCABLES:
        raise SystemExit(
            f"La rama principal del proyecto {project} es '{principal}'. Este "
            f"script prueba la publicación, y publicar fusiona la rama de "
            f"trabajo en la principal: correría un merge real sobre '{principal}'. "
            f"Apunta el proyecto a una rama principal desechable antes de "
            f"lanzarlo. No se ha tocado nada."
        )
    return principal


def exigir_agente_desechable(project, agent_id):
    """Se niega a seguir si el agente no se declara desechable en su nombre."""
    region = cx.detect_agent_region(project, agent_id)
    respuesta = cx.api_get(project, region, cx.build_parent(project, region, agent_id))
    if respuesta.status_code != 200:
        raise SystemExit(
            f"No se pudo leer el agente {agent_id}: {respuesta.status_code}"
        )
    nombre = respuesta.json().get("displayName", "")
    if MARCA_DESECHABLE not in nombre.lower():
        raise SystemExit(
            f"El agente '{nombre}' no se declara desechable. Este script "
            f"escribe de verdad, así que solo acepta agentes cuyo nombre "
            f"contenga '{MARCA_DESECHABLE}'. No se ha tocado nada."
        )
    return region, nombre


# ── Nivel 0 · Estático ───────────────────────────────────────────────────────

def nivel_0(runner):
    print("\nNIVEL 0 — Estático · sin red ni credenciales")

    def sin_literales_reales():
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if LITERALES_PROHIBIDOS.search(linea):
                    sucios.append(f"{ruta}:{i}")
        return not sucios, f"aparecen en {', '.join(sucios)}" if sucios else ""

    runner.check(0, "Ningún literal de proyecto, agente o región real en el código",
                 sin_literales_reales)

    def sin_constantes_de_destino():
        sospechosas = []
        for ruta in ARCHIVOS_PIPELINE:
            arbol = ast.parse((REPO_ROOT / ruta).read_text())
            for nodo in arbol.body:
                if not isinstance(nodo, ast.Assign):
                    continue
                for objetivo in nodo.targets:
                    if not isinstance(objetivo, ast.Name):
                        continue
                    if not isinstance(nodo.value, ast.Constant):
                        continue
                    if not isinstance(nodo.value.value, str):
                        continue
                    if re.search(r"^(PROJECT|AGENT|AGENT_ID|REGION|LOCATION)$",
                                 objetivo.id):
                        sospechosas.append(f"{ruta}:{objetivo.id}")
        return not sospechosas, ", ".join(sospechosas)

    runner.check(0, "Ninguna constante de módulo fija proyecto, agente o región",
                 sin_constantes_de_destino)

    def entrada_exige_destino():
        fallos = []
        for nombre in ("step_1_inventory", "step_3_apply_to_cx", "step_5_publish",
                       "manage_versions"):
            funcion = getattr(pipeline, nombre)
            try:
                funcion()
                fallos.append(f"{nombre} aceptó llamada sin destino")
            except TypeError:
                pass
        return not fallos, "; ".join(fallos)

    runner.check(0, "Las funciones de entrada exigen project y agent explícitos",
                 entrada_exige_destino)

    def contexto_rechaza_vacios():
        for project, agent in (("", "a"), ("p", ""), (None, None)):
            try:
                pipeline.Contexto(project, agent)
                return False, f"aceptó project={project!r} agent={agent!r}"
            except ValueError:
                continue
            except Exception:
                # Cualquier otro fallo llegaría después de la validación, y eso
                # significa que la validación no se hizo primero.
                return False, f"no validó antes de actuar con {project!r}/{agent!r}"
        return True, ""

    runner.check(0, "Un destino vacío falla al construir el contexto, no más tarde",
                 contexto_rechaza_vacios)

    def esquema_firestore_obligatorio():
        """El repositorio es del proyecto y la región del agente: son dos
        documentos con dos esquemas, y ninguno puede quedarse sin sus campos."""
        agente = set(store.CAMPOS_OBLIGATORIOS_AGENTE)
        proyecto = set(store.CAMPOS_OBLIGATORIOS_PROYECTO)
        problemas = []
        if agente != {"project", "agent_id", "region", "rama"}:
            problemas.append(f"agente: {sorted(agente)}")
        if proyecto != {"project", "repo", "rama_principal"}:
            problemas.append(f"proyecto: {sorted(proyecto)}")
        if "repo" in agente:
            problemas.append("el agente exige repositorio, y el repositorio es del proyecto")
        if "rama" in proyecto:
            problemas.append("el proyecto fija la rama de trabajo, y esa es de cada agente: "
                             "compartirla haría que publicar uno arrastrara a sus hermanos")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Los documentos de proyecto y de agente declaran sus campos "
                    "obligatorios, y el repositorio vive en el del proyecto",
                 esquema_firestore_obligatorio)

    def mapeo_incompleto_falla():
        class DocFalso:
            exists = True
            def to_dict(self): return {"project": "p", "agent_id": "a"}
        class RefFalsa:
            def get(self): return DocFalso()
        class ColFalsa:
            def document(self, _): return RefFalsa()
        class ClienteFalso:
            def collection(self, _): return ColFalsa()
        try:
            store.get_agent_mapping(ClienteFalso(), "p", "a")
            return False, "aceptó un documento sin region ni repo"
        except store.MappingIncomplete as error:
            return "region" in str(error), str(error)[:80]

    runner.check(0, "Un documento incompleto falla con error propio, no con None implícito",
                 mapeo_incompleto_falla)

    def temporales_sin_ruta_fija():
        # El pipeline no escribe archivos temporales: todo lo que necesita
        # persistir va a Firestore o a GitHub. Se comprueba que sigue siendo
        # verdad, porque una ruta fija por agente colisionaría entre dos
        # peticiones concurrentes en el mismo contenedor reutilizado.
        # `open(` a secas cazaba `tarfile.open(fileobj=...)`, que lee de
        # memoria y no toca el disco. Lo que importa es escribir en una ruta.
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if linea.strip().startswith("#"):
                    continue
                for patron in ("/tmp/", "tempfile.", "NamedTemporary",
                               ".write_text(", ".write_bytes(", "open(\"w"):
                    if patron in linea:
                        sucios.append(f"{ruta}:{i} {patron}")
        return not sucios, "; ".join(sucios)

    runner.check(0, "El pipeline no escribe archivos temporales en disco",
                 temporales_sin_ruta_fija)

    def ningun_log_interpola_tokens():
        sucios = []
        for ruta in ARCHIVOS_PIPELINE:
            for i, linea in enumerate((REPO_ROOT / ruta).read_text().splitlines(), 1):
                if not re.search(r"(print|_emit|log\.append)", linea):
                    continue
                if re.search(r"\{[^}]*token[^}]*\}|\+\s*token\b", linea, re.I):
                    sucios.append(f"{ruta}:{i}")
        return not sucios, ", ".join(sucios)

    runner.check(0, "Ningún registro interpola el token de acceso ni el de GitHub",
                 ningun_log_interpola_tokens)

    def adc_en_lugar_de_gcloud():
        """Se mira el código, no el texto.

        Buscar la cadena "gcloud" da un falso positivo con el propio docstring
        del cliente, que explica en prosa por qué aquí no se usa. Lo que
        importa es si el módulo lo importa o lo invoca.
        """
        arbol = ast.parse((REPO_ROOT / "act/utils/cx_client_cloudrun.py").read_text())
        importa_subprocess = any(
            (isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "subprocess")
            for n in ast.walk(arbol)
        )
        # Los docstrings también son nodos constantes, y el del propio cliente
        # nombra a gcloud para explicar por qué NO se usa. Se excluyen.
        docstrings = set()
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                cuerpo = getattr(nodo, "body", [])
                if (cuerpo and isinstance(cuerpo[0], ast.Expr)
                        and isinstance(cuerpo[0].value, ast.Constant)
                        and isinstance(cuerpo[0].value.value, str)):
                    docstrings.add(id(cuerpo[0].value))
        invoca_gcloud = any(
            isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings and "print-access-token" in n.value
            for n in ast.walk(arbol)
        )
        usa_adc = any(
            isinstance(n, ast.Attribute) and n.attr == "default"
            for n in ast.walk(arbol)
        )
        problemas = []
        if importa_subprocess:
            problemas.append("importa subprocess")
        if invoca_gcloud:
            problemas.append("invoca gcloud print-access-token")
        if not usa_adc:
            problemas.append("no llama a google.auth.default")
        return not problemas, "; ".join(problemas)

    runner.check(0, "La autenticación es ADC, no gcloud — dentro del contenedor "
                    "no hay sesión interactiva ni binario de gcloud",
                 adc_en_lugar_de_gcloud)

    def url_absoluta_rechazada():
        try:
            cx.api_request("GET", "p", "europe-west1", "https://evil.example.com/x")
            return False, "aceptó una URL absoluta del cliente"
        except ValueError:
            return True, ""

    runner.check(0, "El cliente rechaza URLs absolutas — el token no puede "
                    "dirigirse a un host de fuera (C3)",
                 url_absoluta_rechazada)

    def x_goog_user_project_esta_en_toda_cabecera():
        """Que el cliente la mande siempre, verificado en el árbol.

        No es una regla arbitraria del pipeline: medido contra la API real el
        2026-08-09, sin esta cabecera Dialogflow responde 403 PERMISSION_DENIED
        — "requires a quota project". El barrido de mutaciones la rompió y las
        99 comprobaciones de entonces siguieron en verde: nadie la vigilaba.
        Aquí se comprueba en el árbol, no repitiendo la llamada a la API en
        cada corrida — la medición real ya está hecha y documentada arriba.
        """
        arbol = ast.parse((REPO_ROOT / "act/utils/cx_client_cloudrun.py")
                          .read_text())
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "get_headers")
        claves = {k.value for n in ast.walk(funcion) if isinstance(n, ast.Dict)
                 for k in n.keys if isinstance(k, ast.Constant)}
        return "x-goog-user-project" in claves, \
            "get_headers ya no incluye x-goog-user-project"

    runner.check(0, "La cabecera x-goog-user-project va en toda llamada — "
                    "medido: sin ella la API responde 403 (falta quota project)",
                 x_goog_user_project_esta_en_toda_cabecera)

    def ninguna_escritura_alcanza_entornos():
        return "environment" not in pipeline.TIPOS_DESPLEGABLES, (
            "TIPOS_DESPLEGABLES contiene environment"
        )

    runner.check(0, "Ninguna escritura de resource puede resolver a un endpoint "
                    "de entorno: la tabla no tiene la entrada",
                 ninguna_escritura_alcanza_entornos)

    def el_panel_y_el_pipeline_declaran_los_mismos_grupos():
        """El Paso 1 devuelve exactamente los grupos que el panel pinta.

        El panel es la especificación, y el pipeline la implementa. Si el panel
        enseña una tarjeta que el pipeline no alimenta, esa tarjeta no puede
        mostrar nada real — y nadie se entera hasta conectarlos, en la Fase 7.
        Se comprueba aquí, sin red, comparando las etiquetas del panel contra
        los campos que devuelve el paso.
        """
        panel = (REPO_ROOT / PANEL).read_text()
        bloque = panel[panel.find('id="inv-done"'):panel.find('id="view-2"')]
        etiquetas = re.findall(r'class="grupo-label">([^<]+)<', bloque)
        esperado = {
            "Emparejados": "emparejados",
            "Solo en CX": "solo_cx",
            "Solo en el repositorio": "solo_repo",
            "Sin agente asignado": "sin_agente",
        }

        faltan_en_panel = [e for e in esperado if e not in etiquetas]
        sobran_en_panel = [e for e in etiquetas if e not in esperado]

        # Y que el paso devuelva de verdad un campo por cada tarjeta.
        fuente = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(fuente)
        paso1 = next(n for n in ast.walk(arbol)
                     if isinstance(n, ast.FunctionDef) and n.name == "step_1_inventory")
        devueltos = {
            k.value for nodo in ast.walk(paso1) if isinstance(nodo, ast.Dict)
            for k in nodo.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        sin_fuente = [campo for tarjeta, campo in esperado.items()
                      if tarjeta in etiquetas and campo not in devueltos]

        problemas = []
        if faltan_en_panel:
            problemas.append(f"el panel no pinta: {faltan_en_panel}")
        if sobran_en_panel:
            problemas.append(f"el panel pinta tarjetas que nadie alimenta: {sobran_en_panel}")
        if sin_fuente:
            problemas.append(f"el Paso 1 no devuelve: {sin_fuente}")
        return not problemas, " · ".join(problemas)

    runner.check(0, "El panel y el Paso 1 declaran los mismos grupos: ninguna "
                    "tarjeta se queda sin datos que mostrar",
                 el_panel_y_el_pipeline_declaran_los_mismos_grupos)

    def trece_tipos():
        return len(pipeline.RESOURCE_TYPES) == 13 and \
            "transition_route_group" in pipeline.RESOURCE_TYPES, \
            f"{len(pipeline.RESOURCE_TYPES)} tipos"

    runner.check(0, "13 tipos de recurso, con Transition Route Groups", trece_tipos)

    # ── El alta de agente es una escritura, y por eso es un botón ────────────

    def toda_version_que_crea_el_validador_lleva_su_marca():
        """Lo que esta suite crea en CX tiene que poder reconocerlo después.

        La limpieza borra por la marca del prefijo. Una versión publicada con
        una etiqueta sin marca —`corte_inyectado`— no la reconoce nadie y se
        queda en el agente **para siempre**: una por corrida, acumulándose
        contra el límite de versiones que CX impone por flow. Llegaron a 12 en
        dos días, y los tres checks de publicar empezaron a fallar por eso, sin
        que el motivo tuviera nada que ver con publicar.

        Se comprueba en el árbol, sobre las llamadas reales: cada etiqueta que
        se pasa a `step_5_publish` tiene que interpolar el prefijo o la
        etiqueta de la corrida, nunca ser un texto suelto.
        """
        arbol = ast.parse((REPO_ROOT / "act/validate_pipeline_cloudrun.py")
                          .read_text())
        sueltas = []
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr == "step_5_publish"):
                continue
            if len(nodo.args) < 3:
                continue
            etiqueta = nodo.args[2]
            # Una constante de texto no puede llevar la marca: se conoce al
            # escribir el archivo, no en la corrida.
            if isinstance(etiqueta, ast.Constant):
                sueltas.append(f"línea {etiqueta.lineno}: {etiqueta.value!r}")
        return not sueltas, " · ".join(sueltas)

    runner.check(0, "Ninguna versión que publica el validador nace sin su "
                    "marca: si no, la limpieza no la reconoce y se queda",
                 toda_version_que_crea_el_validador_lleva_su_marca)

    def las_versiones_se_leen_de_los_tres_contenedores():
        """Los tres contenedores, cada uno con la clave que CX usa de verdad.

        Verificado contra la API el 2026-08-09: `flow` responde con `versions`,
        `playbook` con `playbookVersions` y `tool` con `toolVersions`. Pedir la
        clave equivocada no da error — devuelve una lista vacía, y el pipeline
        concluye que ese contenedor no tiene versiones.

        Eso es lo que dejó 100 versiones invisibles en un playbook hasta que CX
        se negó a crear la 101 y publicar dejó de funcionar.
        """
        spec = pipeline.RESOURCE_TYPES["version"]
        esperado = {"flow": "versions", "playbook": "playbookVersions",
                    "tool": "toolVersions"}
        declarado = dict(spec.get("padres") or ())
        if declarado != esperado:
            return False, f"declara {declarado}, y CX usa {esperado}"
        # Y que ningún contenedor se quede fuera de la tabla de tipos.
        faltan = [c for c in esperado if c not in pipeline.RESOURCE_TYPES]
        return not faltan, f"contenedores sin declarar: {faltan}"

    runner.check(0, "Las versiones se leen de los tres contenedores, cada uno "
                    "con la clave que CX usa de verdad",
                 las_versiones_se_leen_de_los_tres_contenedores)

    def dos_versiones_del_mismo_numero_no_se_pisan():
        """CX numera dentro de cada contenedor: hay una v1 por contenedor.

        Guardarlas por el número a secas hacía que la del playbook pisara a la
        del flow en el inventario, en silencio. Se provoca el caso con dos
        objetos falsos que comparten número y distinto padre.
        """
        uno = {"name": "projects/p/locations/r/agents/a/flows/F/versions/1"}
        otro = {"name": "projects/p/locations/r/agents/a/playbooks/P/versions/1"}
        claves = {pipeline._clave_de_version(uno), pipeline._clave_de_version(otro)}
        return len(claves) == 2, f"las dos comparten clave: {claves}"

    runner.check(0, "Dos versiones con el mismo número y distinto contenedor no "
                    "se pisan en el inventario",
                 dos_versiones_del_mismo_numero_no_se_pisan)

    def los_tres_contenedores_tienen_limite_de_poda():
        """Sin límite, el contenedor nunca se avisa de que se pasó — se queda mudo.

        Añadir un contenedor nuevo a `RESOURCE_TYPES["version"]["padres"]` sin
        añadirlo también a `LIMITE_VERSIONES` dejaría ese contenedor sin aviso,
        en silencio: `_contenedores_sobre_limite` simplemente lo salta.
        """
        contenedores = {c for c, _ in pipeline.RESOURCE_TYPES["version"]["padres"]}
        faltan = contenedores - set(pipeline.LIMITE_VERSIONES)
        return not faltan, f"sin límite de poda: {faltan}"

    runner.check(0, "Los tres contenedores tienen un límite de poda declarado",
                 los_tres_contenedores_tienen_limite_de_poda)

    def el_panel_no_promete_escrituras_que_ya_no_ocurren():
        """Lo que el panel dice que pasa tiene que seguir pasando.

        Vincular dejaba un `cx-deploy.yaml` en la raíz del repositorio y se
        retiró: nadie lo leía, y el Paso 1 lo contaba como un YAML más. El
        panel siguió anunciándolo en cuatro sitios —specs y registro en vivo—,
        y una promesa que el código ya no cumple no se distingue de un fallo
        cuando el archivo no aparece.

        Es un check por escritura retirada, no una lista de textos prohibidos:
        se comprueba contra el código que la escritura ya no existe, y solo
        entonces se exige que el panel tampoco la nombre.
        """
        panel = (REPO_ROOT / PANEL).read_text()
        # Contra el árbol, no contra el texto del archivo: el código explica en
        # un comentario por qué se retiró el marcador, y buscar la cadena a
        # secas encontraba ese comentario y daba la escritura por viva. El
        # árbol no lleva comentarios, así que aquí solo quedan los literales
        # que el código usa de verdad.
        funcion = next(n for n in ast.walk(ast.parse(
            inspect.getsource(pipeline.link_project_repo)))
            if isinstance(n, ast.FunctionDef))
        escribe_marcador = any(
            isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "cx-deploy" in n.value for n in ast.walk(funcion))
        problemas = []
        if not escribe_marcador and "cx-deploy" in panel.lower():
            problemas.append(
                f"vincular ya no escribe cx-deploy.yaml y el panel lo anuncia "
                f"{panel.lower().count('cx-deploy')} veces")
        return not problemas, " · ".join(problemas)

    runner.check(0, "El panel no anuncia escrituras que el pipeline ya no hace",
                 el_panel_no_promete_escrituras_que_ya_no_ocurren)

    def el_panel_ensena_lo_que_el_paso_1_averigua():
        """Cada dato nuevo del Paso 1 tiene que llegar a la pantalla.

        El Paso 1 empezó a devolver si al agente le falta el entorno de
        producción — sin él, el Paso 5 no tiene dónde publicar, y antes eso se
        descubría al final, con el agente ya escrito. Un dato que el paso
        calcula y el panel no enseña no sirve de nada: el aviso solo existe si
        se ve.

        Se comprueba en las dos direcciones, contra el árbol del pipeline: si
        el paso deja de devolverlo, este check también salta.
        """
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "step_1_inventory")
        devueltos = {
            clave.value for nodo in ast.walk(funcion)
            if isinstance(nodo, ast.Dict)
            for clave in nodo.keys
            if isinstance(clave, ast.Constant) and isinstance(clave.value, str)
        }
        panel = (REPO_ROOT / PANEL).read_text()
        problemas = []
        if "tiene_entorno_produccion" not in devueltos:
            problemas.append("el Paso 1 ya no averigua si falta el entorno")
        # Un `id` concreto, no un texto suelto: buscar "entorno de producción"
        # en el panel lo encontraba en el Paso 5 y en la lista de puesta en
        # marcha, así que el check pasaba sin que el aviso del Paso 1
        # existiera. El aviso tiene que ser un elemento identificable, como
        # `aviso-sin-repos`, que es su hermano.
        elif "aviso-sin-entorno" not in panel:
            problemas.append(
                "el Paso 1 avisa de que falta el entorno de producción y el "
                "panel no tiene el aviso (falta el id `aviso-sin-entorno`)")
        return not problemas, " · ".join(problemas)

    runner.check(0, "El panel enseña lo que el Paso 1 averigua: el aviso de "
                    "entorno de producción llega a la pantalla",
                 el_panel_ensena_lo_que_el_paso_1_averigua)

    def el_panel_tiene_el_boton_del_alta():
        """El tercer estado de la caja del destino existe en la pantalla.

        `discover` manda `rama_propuesta` justo para que el Paso 1 pueda
        enseñar el nombre de la rama antes de crearla, y `register_agent` es lo
        que dispara el botón. Sin botón, ese campo viaja para nada y un agente
        sin rama deja el paso muerto sin decir por qué.
        """
        panel = (REPO_ROOT / PANEL).read_text()
        problemas = []
        if not hasattr(pipeline, "register_agent"):
            problemas.append("el pipeline no expone el alta")
        if "Dar de alta" not in panel:
            problemas.append("el panel no tiene el botón de dar de alta")
        # La rama propuesta se enseña, no se calcula en el navegador: si el
        # panel la construyera por su cuenta podría crear una distinta de la
        # que se leyó, y el botón dejaría de confirmar nada.
        if "rama_propuesta" not in panel and "agente/" not in panel:
            problemas.append("el panel no enseña la rama antes de crearla")
        return not problemas, " · ".join(problemas)

    runner.check(0, "El panel tiene el botón de alta y enseña la rama antes de "
                    "crearla",
                 el_panel_tiene_el_boton_del_alta)

    def el_paso_1_no_da_de_alta_a_nadie():
        """Que el alta no cuelgue de mirar, sino de pulsar.

        Se comprueba en el árbol y no leyendo: la garantía es que ninguna de
        las funciones que el Paso 1 recorre —ni él, ni la resolución del
        destino, ni la lectura del repositorio— llama a lo que crea la rama.
        Si algún día alguien la engancha ahí «para que sea más cómodo», elegir
        un agente en el desplegable volvería a dejar rastro.
        """
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        prohibidas = {"register_agent", "create_branch", "save_agent_mapping",
                      "save_project_mapping", "commit_files"}
        culpables = []
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.FunctionDef):
                continue
            if nodo.name not in ("step_1_inventory", "cargar_repositorio",
                                 "inventariar_cx", "emparejar", "discover"):
                continue
            for hijo in ast.walk(nodo):
                if not isinstance(hijo, ast.Call):
                    continue
                nombre = (hijo.func.attr if isinstance(hijo.func, ast.Attribute)
                          else getattr(hijo.func, "id", None))
                if nombre in prohibidas:
                    culpables.append(f"{nodo.name} llama a {nombre}")
        return not culpables, " · ".join(culpables)

    runner.check(0, "Mirar no da de alta: ninguna función del Paso 1 crea la "
                    "rama ni registra el agente",
                 el_paso_1_no_da_de_alta_a_nadie)

    def el_panel_ensena_la_rama_antes_de_crearla():
        """El nombre que se ve en pantalla y el que se crea son el mismo.

        `discover` manda `rama_propuesta` para que el Paso 1 pueda enseñar qué
        va a pasar antes de que pase. Si el panel lo calculara por su cuenta, o
        el alta usara otra regla, se crearía una rama distinta de la que se
        leyó — y el botón dejaría de ser una confirmación de nada.
        """
        propuesta = pipeline.rama_propuesta("abc-123", "Petal Voz")
        por_id = pipeline.rama_propuesta("abc-123")
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        emisores = [n.name for n in ast.walk(arbol)
                    if isinstance(n, ast.FunctionDef)
                    and any(isinstance(c, ast.Call)
                            and getattr(c.func, "id", None) == "rama_propuesta"
                            for c in ast.walk(n))]
        problemas = []
        if propuesta != "agente/petal_voz":
            problemas.append(f"propone {propuesta!r} para 'Petal Voz'")
        if por_id != "agente/abc-123":
            problemas.append(f"sin displayName propone {por_id!r}")
        for quien in ("discover", "register_agent"):
            if quien not in emisores:
                problemas.append(f"{quien} no usa rama_propuesta")
        return not problemas, " · ".join(problemas)

    runner.check(0, "La rama que el Paso 1 enseña es la misma que el alta crea",
                 el_panel_ensena_la_rama_antes_de_crearla)

    def vincular_no_pregunta_por_ningun_agente():
        """El repositorio es del proyecto: la herramienta no toca agentes.

        Si volviera a aceptar un `agent_id`, volvería a haber dos caminos para
        dar de alta un agente —la herramienta y el botón— y el de la
        herramienta solo serviría para el primero de cada proyecto.
        """
        firma = inspect.signature(pipeline.link_project_repo)
        sobra = [p for p in firma.parameters if "agent" in p]
        falta = [p for p in ("project", "repo_url") if p not in firma.parameters]
        # Y no trae nada: traer es el Paso 2, no un segundo camino.
        fuente = inspect.getsource(pipeline.link_project_repo)
        if "step_2_pull_to_repo" in fuente:
            sobra.append("hace el pull inicial")
        return not (sobra or falta), \
            f"sobra: {sobra} · falta: {falta}" if (sobra or falta) else ""

    runner.check(0, "Vincular es del proyecto: ni pide agente ni trae nada",
                 vincular_no_pregunta_por_ningun_agente)

    def vincular_no_escribe_en_el_repositorio():
        """Vincular es apuntar una correspondencia, no tocar el repositorio.

        Dejaba un marcador `cx-deploy.yaml` en la raíz que nadie leía nunca —se
        escribía y no se consultaba— y que el Paso 1 contaba como un YAML más
        del repositorio. Se comprueba en el árbol: si vuelve a aparecer una
        llamada de escritura ahí dentro, este check lo dice.
        """
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "link_project_repo")
        escrituras = [
            hijo.func.attr for hijo in ast.walk(funcion)
            if isinstance(hijo, ast.Call)
            and isinstance(hijo.func, ast.Attribute)
            and hijo.func.attr in ("commit_files", "create_branch",
                                   "delete_branch", "merge_branches")
        ]
        return not escrituras, f"escribe en el repositorio: {escrituras}"

    runner.check(0, "Vincular un proyecto no escribe nada en el repositorio: "
                    "solo apunta a qué repositorio pertenece",
                 vincular_no_escribe_en_el_repositorio)

    def el_comando_iam_se_puede_copiar():
        """Sin variables de shell sin resolver.

        Es el único paso del onboarding que ocurre fuera del panel. Pegado en
        una terminal donde `$ACT_SERVICE_ACCOUNT` no existe, `--member=` queda
        vacío y gcloud falla con un error de sintaxis que no menciona el alta.
        """
        fuente = inspect.getsource(pipeline.link_project_repo)
        trozo = fuente[fuente.find("comando_iam"):]
        trozo = trozo[:trozo.find("_emit")]
        return "$" not in trozo.replace('f"', "").replace("f'", ""), \
            "el comando lleva una variable de shell sin resolver"

    runner.check(0, "El comando IAM que muestra el panel se puede pegar tal cual",
                 el_comando_iam_se_puede_copiar)

    # ── La comparación borrador ↔ producción, contra el agente ficticio ──────
    #
    # Aquí está el grueso de la cobertura del cambio, y no toca la red: el
    # inventario se fabrica en memoria con la forma exacta de `inventariar_cx`,
    # y la única llamada que la comparación haría —`compareVersions` de un
    # flow— la contesta un doble.

    def el_agente_ficticio_se_reparte_como_toca():
        """0.1 — los seis casos de una vez, en un solo agente."""
        resultado = comparar_ficticio(agente_ficticio_completo(), iguales=False)
        esperado = {"cambiados": ["B", "C", "F"], "iguales": ["A", "T"],
                    "borrados": ["D"]}
        real = {clave: _nombres(filas) for clave, filas in resultado.items()}
        return real == esperado, f"esperado {esperado} · real {real}"

    runner.check(0, "El agente ficticio completo produce el reparto esperado: "
                    "cambiados, iguales y borrados",
                 el_agente_ficticio_se_reparte_como_toca)

    def contenido_identico_no_es_un_cambio():
        """0.2 — y 0.8: un cambio solo en los campos que gestiona la API
        tampoco. La versión de A trae otro `tokenCount` y otro `createTime`."""
        resultado = comparar_ficticio(agente_ficticio_completo(), iguales=False)
        return "A" not in _nombres(resultado["cambiados"]), \
            "un playbook idéntico a su versión publicada salió como cambiado"

    runner.check(0, "Contenido idéntico no aparece como cambiado",
                 contenido_identico_no_es_un_cambio)

    def contenido_distinto_es_un_cambio():
        """0.3"""
        resultado = comparar_ficticio(agente_ficticio_completo(), iguales=False)
        return "B" in _nombres(resultado["cambiados"]), \
            "un playbook con otro contenido no salió como cambiado"

    runner.check(0, "Contenido distinto aparece como cambiado",
                 contenido_distinto_es_un_cambio)

    def sin_ninguna_version_es_un_cambio():
        """0.4 — necesita su primera versión."""
        resultado = comparar_ficticio(agente_ficticio_completo(), iguales=False)
        fila = next((f for f in resultado["cambiados"] if f["cx_id"] == "C"), None)
        return fila is not None and fila["version_fijada"] is None, \
            "un contenedor sin ninguna versión no salió como cambiado"

    runner.check(0, "Un contenedor sin ninguna versión aparece como cambiado",
                 sin_ninguna_version_es_un_cambio)

    def fijado_y_ausente_es_un_borrado():
        """0.5 — producción lo sirve y el borrador ya no lo tiene."""
        resultado = comparar_ficticio(agente_ficticio_completo(), iguales=False)
        fila = next((f for f in resultado["borrados"] if f["cx_id"] == "D"), None)
        problemas = []
        if fila is None:
            problemas.append("D no salió como borrado")
        else:
            if fila["tipo"] != "playbook":
                problemas.append(f"tipo {fila['tipo']!r} en vez de playbook")
            if not fila["version_fijada"]:
                problemas.append("sin decir qué versión lo fija")
        if "D" in _nombres(resultado["cambiados"]):
            problemas.append("además salió como cambiado")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Fijado en el entorno y ausente del borrador aparece como "
                    "borrado",
                 fijado_y_ausente_es_un_borrado)

    def entorno_vacio_saca_todo_como_cambiado():
        """0.6 — el agente nunca publicado: todo pendiente, nada borrado."""
        inventario = agente_ficticio_completo()
        inventario["environment"]["env-ficticio"]["versionConfigs"] = []
        resultado = comparar_ficticio(inventario, iguales=False)
        problemas = []
        if _nombres(resultado["cambiados"]) != ["A", "B", "C", "F", "T"]:
            problemas.append(f"cambiados {_nombres(resultado['cambiados'])}")
        if resultado["borrados"]:
            problemas.append(f"borrados {_nombres(resultado['borrados'])}")
        if resultado["iguales"]:
            problemas.append(f"iguales {_nombres(resultado['iguales'])}")
        return not problemas, " · ".join(problemas)

    runner.check(0, "Entorno vacío: todos los contenedores salen como cambiados "
                    "y ninguno como borrado",
                 entorno_vacio_saca_todo_como_cambiado)

    def sin_entorno_de_produccion_no_revienta():
        """0.7 — el Paso 1 lee esto solo para informar: ahí no toca romper."""
        inventario = agente_ficticio_completo()
        inventario["environment"] = {}
        resultado = comparar_ficticio(inventario, iguales=False)
        return (_nombres(resultado["cambiados"]) == ["A", "B", "C", "F", "T"]
                and not resultado["borrados"]), \
            f"con el agente sin entorno devolvió {resultado}"

    runner.check(0, "Un agente sin entorno de producción no revienta: devuelve "
                    "algo coherente",
                 sin_entorno_de_produccion_no_revienta)

    def los_campos_que_gestiona_la_api_no_son_contenido():
        """0.8 — explícito, cambiando solo `createTime` en la foto congelada."""
        a = _ficticio_playbook("A")
        version = _ficticia_version(
            a["name"], 1,
            {**a, "createTime": "1999-01-01T00:00:00Z", "tokenCount": 7,
             "name": "otra/ruta/entera"},
            clave_contenido="playbook")
        inventario = _ficticio_inventario(playbooks=[a], versiones=[version],
                                          fijadas=[version["name"]])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["iguales"]) == ["A"], \
            f"un cambio solo en CAMPOS_LEIDOS_NO_ENVIADOS contó como cambio: {resultado}"

    runner.check(0, "Un cambio solo en los campos que gestiona la API no cuenta "
                    "como cambio",
                 los_campos_que_gestiona_la_api_no_son_contenido)

    def cambiar_un_example_cambia_su_playbook():
        """0.9 — un playbook y sus examples son un solo contenedor."""
        a = _ficticio_playbook("A")
        congelado = _ficticio_example("E1", "A", texto="hola")
        vivo = _ficticio_example("E1", "A", texto="hola CAMBIADO")
        version = _ficticia_version(a["name"], 1, dict(a), hijos=[congelado],
                                    clave_contenido="playbook",
                                    clave_hijos="examples")
        inventario = _ficticio_inventario(playbooks=[a], examples=[vivo],
                                          versiones=[version],
                                          fijadas=[version["name"]])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["cambiados"]) == ["A"], \
            f"cambiar un example no sacó su playbook como cambiado: {resultado}"

    runner.check(0, "Cambiar un example hace que su playbook salga como cambiado",
                 cambiar_un_example_cambia_su_playbook)

    def borrar_un_example_cambia_su_playbook():
        """0.14 — el borrado de un hijo es un cambio del contenedor.

        Es el caso que se escapa si la comparación solo mira el contenedor:
        el playbook está igual, y aun así lo que producción sirve ya no es lo
        que hay en el borrador.
        """
        a = _ficticio_playbook("A")
        congelado = _ficticio_example("E1", "A")
        version = _ficticia_version(a["name"], 1, dict(a), hijos=[congelado],
                                    clave_contenido="playbook",
                                    clave_hijos="examples")
        # El borrador ya no tiene ese example.
        inventario = _ficticio_inventario(playbooks=[a], examples=[],
                                          versiones=[version],
                                          fijadas=[version["name"]])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["cambiados"]) == ["A"], \
            f"borrar un example no sacó su playbook como cambiado: {resultado}"

    runner.check(0, "Borrar un example hace que su playbook salga como cambiado",
                 borrar_un_example_cambia_su_playbook)

    def anadir_el_primer_example_cambia_su_playbook():
        """0.14 bis — CX omite `examples` cuando no había ninguno, en vez de
        devolver una lista vacía. Tratar la ausencia como «no sé» dejaría pasar
        el primer example de cada playbook."""
        a = _ficticio_playbook("A")
        version = _ficticia_version(a["name"], 1, dict(a),
                                    clave_contenido="playbook")
        inventario = _ficticio_inventario(
            playbooks=[a], examples=[_ficticio_example("E1", "A")],
            versiones=[version], fijadas=[version["name"]])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["cambiados"]) == ["A"], \
            f"añadir el primer example no sacó su playbook como cambiado: {resultado}"

    runner.check(0, "Añadir el primer example de un playbook lo saca como cambiado",
                 anadir_el_primer_example_cambia_su_playbook)

    def los_tipos_sin_version_no_aparecen_nunca():
        """0.10 — generator y agent_config no se versionan, así que no pueden
        salir como cambiados: proponerlos sería proponer una llamada que CX
        rechaza."""
        inventario = agente_ficticio_completo()
        inventario["generator"]["G"] = {
            "name": f"{AGENTE_FICTICIO}/generators/G", "displayName": "G",
            "promptText": {"text": "resume"}}
        inventario["agent_config"]["agente-ficticio"] = {
            "name": AGENTE_FICTICIO, "displayName": "agente"}
        resultado = comparar_ficticio(inventario, iguales=False)
        tipos = {f["tipo"] for lista in resultado.values() for f in lista}
        sobran = tipos & set(pipeline.TIPOS_SIN_VERSION)
        return not sobran, f"aparecen tipos sin versión: {sorted(sobran)}"

    runner.check(0, "generator y agent_config no aparecen nunca en la comparación",
                 los_tipos_sin_version_no_aparecen_nunca)

    def un_tool_nativo_no_se_propone():
        """Los tools que trae la plataforma no admiten versión — CX contesta
        404 al pedirla. Proponerlos gastaría una llamada segura de fallar y
        ensuciaría el recuento de lo que se versiona."""
        nativo = {**_ficticio_tool("df-code-interpreter-tool"),
                  "toolType": "BUILTIN_TOOL"}
        inventario = _ficticio_inventario(tools=[nativo])
        resultado = comparar_ficticio(inventario)
        vacio = not any(resultado.values())
        return vacio, f"un tool nativo se coló en la comparación: {resultado}"

    runner.check(0, "Un tool nativo de la plataforma no se propone para versionar",
                 un_tool_nativo_no_se_propone)

    def la_comparacion_es_determinista():
        """0.11 — mismo inventario, mismo resultado y mismo orden."""
        inventario = agente_ficticio_completo()
        primera = comparar_ficticio(inventario, iguales=False)
        segunda = comparar_ficticio(inventario, iguales=False)
        return primera == segunda, "dos llamadas dieron resultados distintos"

    runner.check(0, "Determinismo: dos llamadas con el mismo inventario dan el "
                    "mismo resultado y el mismo orden",
                 la_comparacion_es_determinista)

    def se_compara_contra_la_version_fijada_no_contra_la_ultima():
        """0.12 — el check que caza el error que reproduciría el fallo original.

        El entorno fija la `v3`. Existe además una `v4`, creada y nunca
        publicada: el Paso 5 murió a mitad, o alguien la creó a mano. El
        borrador coincide con la `v4` y no con la `v3`.

        Comparando contra la fijada, el contenedor sale como **cambiado** y el
        cambio llega a producción. Comparando contra «la última», saldría como
        igual, no se crearía versión ninguna, el paso diría que fue bien y el
        cambio se quedaría en el borrador para siempre.
        """
        borrador = _ficticio_playbook("A", "objetivo NUEVO")
        v3 = _ficticia_version(borrador["name"], 3,
                               {**borrador, "goal": "objetivo VIEJO"},
                               clave_contenido="playbook")
        v4 = _ficticia_version(borrador["name"], 4, dict(borrador),
                               clave_contenido="playbook")
        inventario = _ficticio_inventario(playbooks=[borrador],
                                          versiones=[v3, v4],
                                          fijadas=[v3["name"]])
        resultado = comparar_ficticio(inventario)
        fila = next((f for f in resultado["cambiados"] if f["cx_id"] == "A"), None)
        if fila is None:
            return False, ("se comparó contra la última versión creada (v4) y "
                           "no contra la que el entorno fija (v3): el cambio no "
                           "habría llegado nunca a producción")
        return fila["version_fijada"] == v3["name"], \
            f"dice comparar contra {fila['version_fijada']}"

    runner.check(0, "Se compara contra la versión que el entorno FIJA, no contra "
                    "la última creada",
                 se_compara_contra_la_version_fijada_no_contra_la_ultima)

    def con_versiones_pero_sin_puntero_es_un_cambio():
        """0.13 — tener versiones no es estar publicado."""
        a = _ficticio_playbook("A")
        version = _ficticia_version(a["name"], 1, dict(a),
                                    clave_contenido="playbook")
        inventario = _ficticio_inventario(playbooks=[a], versiones=[version],
                                          fijadas=[])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["cambiados"]) == ["A"], \
            f"un contenedor con versiones y sin puntero no salió como cambiado: {resultado}"

    runner.check(0, "Un contenedor con versiones pero sin puntero en el entorno "
                    "sale como cambiado",
                 con_versiones_pero_sin_puntero_es_un_cambio)

    def una_version_fijada_que_ya_no_existe_es_un_cambio():
        """Alguien borró en la consola la versión que producción fijaba. Sin
        con qué comparar, lo seguro es republicar — nunca dar por bueno."""
        a = _ficticio_playbook("A")
        inventario = _ficticio_inventario(
            playbooks=[a], versiones=[],
            fijadas=[f"{a['name']}/versions/9"])
        resultado = comparar_ficticio(inventario)
        return _nombres(resultado["cambiados"]) == ["A"], \
            f"una versión fijada inexistente no sacó su contenedor como cambiado: {resultado}"

    runner.check(0, "Si la versión que el entorno fija ya no existe, el "
                    "contenedor sale como cambiado",
                 una_version_fijada_que_ya_no_existe_es_un_cambio)

    def un_borrador_vacio_no_revienta():
        """0.15 — agente degenerado, sin ningún contenedor."""
        resultado = comparar_ficticio(_ficticio_inventario())
        return resultado == {"cambiados": [], "borrados": [], "iguales": []}, \
            f"un borrador sin contenedores devolvió {resultado}"

    runner.check(0, "Un borrador sin ningún contenedor no revienta",
                 un_borrador_vacio_no_revienta)

    def el_paso_5_ya_no_recuerda():
        """0.16 — el mecanismo de la lista de Firestore ya no existe."""
        rastros = []
        for ruta in ARCHIVOS_PIPELINE:
            texto = (REPO_ROOT / ruta).read_text()
            for termino in ("list_pending_publication", "mark_published",
                            "pendiente_publicar"):
                if termino in texto:
                    rastros.append(f"{ruta}: {termino}")
        return not rastros, " · ".join(rastros)

    runner.check(0, "El Paso 5 ya no recuerda: list_pending_publication, "
                    "mark_published y pendiente_publicar no aparecen",
                 el_paso_5_ya_no_recuerda)

    def padres_versionables_ya_no_existe():
        """0.17 — la traducción de «pendientes» a contenedores ya no hace falta:
        la comparación devuelve contenedores directamente."""
        texto = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        return "_padres_versionables" not in texto, \
            "_padres_versionables sigue en el pipeline"

    runner.check(0, "_padres_versionables ya no existe ni se llama",
                 padres_versionables_ya_no_existe)

    def la_deteccion_de_conflicto_sigue_en_pie():
        """0.18 — anti-regresión. `huella_cx` y `record_resource_write` viven en
        el mismo documento de Firestore que la marca que se retiró, pero sirven
        para otra cosa: son el tercer punto de referencia que permite avisar de
        que un resource cambió en el repositorio y en CX a la vez. Esa
        protección importa **más** después de este cambio, porque ahora se edita
        en la consola a propósito.
        """
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        definidas = {n.name for n in ast.walk(arbol)
                     if isinstance(n, ast.FunctionDef)}
        llamadas = {(n.func.attr if isinstance(n.func, ast.Attribute)
                     else getattr(n.func, "id", None))
                    for n in ast.walk(arbol) if isinstance(n, ast.Call)}
        firestore = (REPO_ROOT / "act/utils/firestore_client_cloudrun.py").read_text()
        faltan = []
        if "_marcar_conflicto" not in definidas:
            faltan.append("_marcar_conflicto ya no se define")
        if "_marcar_conflicto" not in llamadas:
            faltan.append("_marcar_conflicto ya no se llama")
        if "record_resource_write" not in llamadas:
            faltan.append("record_resource_write ya no se llama")
        if "def record_resource_write" not in firestore:
            faltan.append("record_resource_write ya no existe en Firestore")
        if "huella_cx" not in firestore:
            faltan.append("huella_cx ya no se guarda")
        if not any("huella_cx" in ast.dump(n) for n in ast.walk(arbol)):
            faltan.append("el pipeline ya no lee huella_cx")
        return not faltan, " · ".join(faltan)

    runner.check(0, "Anti-regresión: la detección de conflicto sigue entera — "
                    "huella_cx, record_resource_write y _marcar_conflicto",
                 la_deteccion_de_conflicto_sigue_en_pie)

    def only_pending_del_paso_3_sigue_intacto():
        """0.19 — anti-regresión. Se llama parecido y no tiene nada que ver: es
        el filtro de «reintentar solo lo que falló», lo manda el panel en la
        petición y no lee Firestore."""
        firma = inspect.signature(pipeline.step_3_apply_to_cx)
        if "only_pending" not in firma.parameters:
            return False, "step_3_apply_to_cx ya no acepta only_pending"
        fuente = inspect.getsource(pipeline.step_3_apply_to_cx)
        if "if only_pending:" not in fuente:
            return False, "only_pending ya no filtra nada"
        # Y sigue sin leer Firestore para decidirlo.
        if "list_pending" in fuente:
            return False, "only_pending pasó a leer Firestore"
        return True, ""

    runner.check(0, "Anti-regresión: el parámetro only_pending del Paso 3 sigue "
                    "intacto y sigue sin leer Firestore",
                 only_pending_del_paso_3_sigue_intacto)

    def el_panel_ensena_los_borrados_que_el_paso_1_detecta():
        """0.20 — el dato nuevo del Paso 1 llega a la pantalla con un `id`.

        Mismo criterio que `aviso-sin-entorno`: un `id` concreto, no un texto
        suelto que pueda estar hablando de otra cosa. Y en los dos paneles — el
        de especificación y el que sirve Cloud Run—, porque un aviso que solo
        existe en la especificación no lo ve nadie.
        """
        arbol = ast.parse((REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py")
                          .read_text())
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "step_1_inventory")
        devueltos = {
            clave.value for nodo in ast.walk(funcion)
            if isinstance(nodo, ast.Dict)
            for clave in nodo.keys
            if isinstance(clave, ast.Constant) and isinstance(clave.value, str)
        }
        problemas = []
        if CAMPO_COMPARACION not in devueltos:
            problemas.append(
                f"el Paso 1 no devuelve `{CAMPO_COMPARACION}`")
        for ruta in (PANEL, PANEL_CLOUDRUN):
            texto = (REPO_ROOT / ruta).read_text()
            if ID_AVISO_BORRADOS not in texto:
                problemas.append(f"{ruta} no tiene el id `{ID_AVISO_BORRADOS}`")
            elif CAMPO_COMPARACION not in texto:
                problemas.append(
                    f"{ruta} tiene el aviso pero no lee `{CAMPO_COMPARACION}`")
        return not problemas, " · ".join(problemas)

    runner.check(0, "El panel enseña lo que el Paso 1 averigua: el aviso de "
                    "contenedores borrados llega a la pantalla, en los dos paneles",
                 el_panel_ensena_los_borrados_que_el_paso_1_detecta)

    def el_log_del_paso_5_no_habla_de_resources_tocados():
        """0.22 — el texto decía «N resources tocados desde la última
        publicación», que describía el mecanismo retirado. Dejarlo sería que el
        paso informara de algo que ya no es cierto."""
        fuente = inspect.getsource(pipeline.step_5_publish)
        return "resources tocados" not in fuente, \
            "el log del Paso 5 sigue hablando de «resources tocados»"

    runner.check(0, "El log del Paso 5 ya no habla de «resources tocados»",
                 el_log_del_paso_5_no_habla_de_resources_tocados)


# ── Nivel 1 · Solo lectura ───────────────────────────────────────────────────

def nivel_1(runner, project, agent_id, region, run_id, hermano=None):
    print("\nNIVEL 1 — Solo lectura · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)

    def listar_los_trece():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        faltan = set(pipeline.RESOURCE_TYPES) - set(inventario)
        return not faltan, f"no se listaron: {sorted(faltan)}"

    runner.check(1, "LIST de los 13 tipos sin errores", listar_los_trece)

    def region_desde_firestore():
        mapeo = store.get_agent_mapping(contexto.store, project, agent_id)
        return mapeo["region"] == region, f"{mapeo['region']} != {region}"

    runner.check(1, "La región se lee de Firestore, no de una constante",
                 region_desde_firestore)

    def region_no_se_resondea():
        with ContadorHttp() as contador:
            pipeline.Contexto(project, agent_id)
        sondeos = [c for c in contador.llamadas if c[1].endswith(f"/agents/{agent_id}")]
        return len(sondeos) == 0, (
            f"{len(sondeos)} sondeos de región en una segunda construcción"
        )

    runner.check(1, "La región guardada no se vuelve a sondear en cada ejecución",
                 region_no_se_resondea)

    def region_invalida_da_error_claro():
        """Una región inventada produce un host inexistente, y Google responde
        con su página de error en HTML. Sin traducirlo, quien depure recibe un
        404 con una página web dentro y ninguna pista de la causa."""
        try:
            cx.api_get(project, "region-que-no-existe",
                       cx.build_parent(project, "region-que-no-existe", agent_id))
            return False, "una región inventada no produjo ningún error"
        except cx.ApiError as error:
            return "región" in str(error), (
                f"el error no nombra la región: {str(error)[:90]}"
            )

    runner.check(1, "Una región inconsistente falla de forma reconocible",
                 region_invalida_da_error_claro)

    def rename_sigue_emparejando():
        """Se renombra de verdad un resource en CX y se comprueba que sigue
        emparejando con su archivo.

        Mirar el estado tal cual está no prueba nada: justo después de un pull
        no hay ningún nombre distinto entre los dos lados, así que el escenario
        no llega a existir y el check pasaría siempre.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        emparejados = pipeline.emparejar(inventario, repositorio)["emparejados"]
        objetivo = next((e for e in emparejados if e["tipo"] == "intent"),
                        None) or (emparejados[0] if emparejados else None)
        if objetivo is None:
            return False, "no hay ningún resource emparejado que renombrar"

        remoto = inventario[objetivo["tipo"]][objetivo["cx_id"]]
        original = remoto.get("displayName")
        cuerpo = {k: v for k, v in remoto.items()
                  if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
        cuerpo["displayName"] = f"{PREFIJO}_{run_id}_renombrado"
        respuesta = cx.api_patch(project, contexto.region, remoto["name"], cuerpo)
        if respuesta.status_code not in (200, 201):
            return False, f"no se pudo renombrar: {respuesta.status_code}"
        try:
            inv2, _, _ = pipeline.inventariar_cx(contexto)
            grupos = pipeline.emparejar(inv2, repositorio)
            sigue = any(e["cx_id"] == objetivo["cx_id"]
                        for e in grupos["emparejados"])
            fantasma = any(s.get("cx_id") == objetivo["cx_id"]
                           for s in grupos["solo_repo"])
            return sigue and not fantasma, (
                f"tras renombrar: emparejado={sigue} · fantasma={fantasma}. "
                f"Si el emparejamiento cayera al nombre, el renombrado "
                f"produciría un duplicado en el repositorio"
            )
        finally:
            cuerpo["displayName"] = original
            cx.api_patch(project, contexto.region, remoto["name"], cuerpo)

    runner.check(1, "Un displayName cambiado con el mismo cx_id sigue emparejando, "
                    "sin duplicado fantasma",
                 rename_sigue_emparejando)

    def cx_id_repetido_entre_tipos_no_se_confunde():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        por_id = {}
        for tipo, items in inventario.items():
            for cx_id in items:
                por_id.setdefault(cx_id, []).append(tipo)
        compartidos = {k: v for k, v in por_id.items() if len(v) > 1}
        if not compartidos:
            return True, "(este agente no tiene ids compartidos entre tipos)"
        # Si los hay, ninguno puede colisionar: el emparejamiento agrupa por
        # tipo antes de buscar por cx_id.
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        grupos = pipeline.emparejar(inventario, repositorio)
        total = len(grupos["emparejados"]) + len(grupos["solo_cx"])
        esperado = sum(len(v) for t, v in inventario.items()
                       if t not in pipeline.TIPOS_FUERA_DEL_REPARTO)
        return total == esperado, f"{total} != {esperado} con ids compartidos"

    runner.check(1, "Dos resources de distinto tipo con el mismo cx_id no se confunden",
                 cx_id_repetido_entre_tipos_no_se_confunde)

    def la_cabecera_nace_completa_tipo_por_tipo():
        """La cabecera que escribe el pull, comprobada en los 13 tipos.

        Es la función real del pull la que se ejercita, sobre los resources
        reales del agente: se comprueba que `tipo` es el correcto, que el
        `cx_id` es el que CX asigna, y que `padre` está relleno **solo** si el
        tipo cuelga de otro — y que ese padre existe de verdad en el agente.

        Un tipo con la cabecera a medias produce un archivo que el pipeline no
        sabrá emparejar después, y eso no se ve hasta el deploy siguiente.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos, revisados = [], []
        for tipo, items in inventario.items():
            if tipo in pipeline.TIPOS_FUERA_DEL_REPARTO:
                continue
            item = next((i for i in items.values()
                         if not pipeline.es_nativo(tipo, i)), None)
            if item is None:
                continue
            spec = pipeline.RESOURCE_TYPES[tipo]
            padre_id = pipeline._padre_id_de(tipo, item) if spec.get("padre") else None
            documento = __import__("yaml").safe_load(
                pipeline._yaml_para_repo(tipo, item, padre_id))
            meta = documento.get("metadata") or {}
            revisados.append(tipo)

            if meta.get("tipo") != tipo:
                fallos.append(f"{tipo}: metadata.tipo = {meta.get('tipo')!r}")
            if meta.get("cx_id") != pipeline._cx_id_de(item):
                fallos.append(f"{tipo}: cx_id {meta.get('cx_id')!r} != "
                              f"{pipeline._cx_id_de(item)!r}")
            if "metadata" in {k for k in documento if k != "metadata"}:
                fallos.append(f"{tipo}: metadata duplicada en el cuerpo")
            if spec.get("padre"):
                if not meta.get("padre"):
                    fallos.append(f"{tipo}: cuelga de {spec['padre']} y padre "
                                  f"viene vacío")
                elif meta["padre"] == pipeline.PADRE_AGENTE:
                    # Los tipos que existen en los dos niveles lo declaran así
                    # cuando cuelgan del agente. Es lo correcto, no un hueco.
                    if not spec.get("tambien_en_agente"):
                        fallos.append(f"{tipo}: dice colgar del agente y no puede")
                elif meta["padre"] not in inventario.get(spec["padre"], {}):
                    fallos.append(f"{tipo}: declara padre {meta['padre']}, que "
                                  f"no existe como {spec['padre']}")
            elif meta.get("padre") is not None:
                fallos.append(f"{tipo}: no cuelga de nada y trae padre "
                              f"{meta['padre']!r}")

        return not fallos, f"revisados {len(revisados)} tipos · " + " | ".join(fallos)

    runner.check(1, "El pull construye la cabecera completa y correcta en cada "
                    "tipo: tipo, cx_id y padre solo cuando corresponde",
                 la_cabecera_nace_completa_tipo_por_tipo)

    def un_archivo_sin_cabecera_no_es_un_resource():
        """Lo que convierte un archivo en resource es tener cabecera.

        Un YAML sin ella no es un resource del pipeline y no puede aparecer en
        ningún grupo del reparto ni en el diff — el repositorio tiene YAML que
        nunca fueron resources: taxonomías, configuraciones, specs OpenAPI.
        """
        original = contexto.gh.read_repo_files
        archivos = dict(original(contexto.gh.branch_head(contexto.rama)))
        intruso = {"path": "definitions/intents/sin_cabecera.yaml"}
        archivos[intruso["path"]] = (
            b"displayName: sin_cabecera\ndescription: no soy un resource\n")
        contexto.gh.read_repo_files = lambda *_a, **_k: archivos
        try:
            repositorio, _ = pipeline.cargar_repositorio(contexto)
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            grupos = pipeline.emparejar(inventario, repositorio)
            operaciones = pipeline.calcular_diff(contexto, inventario, repositorio)
            aparece = (
                any(x.get("ruta") == intruso["path"] for x in grupos["solo_repo"])
                or any(o.get("ruta") == intruso["path"] for o in operaciones)
            )
            return not aparece, "el archivo sin cabecera entró en el reparto o en el diff"
        finally:
            contexto.gh.read_repo_files = original

    runner.check(1, "Un YAML sin cabecera no es un resource: ni entra en el "
                    "reparto ni genera operación",
                 un_archivo_sin_cabecera_no_es_un_resource)

    def un_padre_inexistente_se_rechaza_con_su_nombre():
        """Resolver dónde cuelga un resource es el único punto donde el padre
        declarado se usa. Un padre que no existe tiene que decirlo, no fallar
        con un error que apunte a otro sitio."""
        operacion = pipeline._operacion(
            "POST", "example", None,
            {"ruta": "definitions/examples/huerfano.yaml",
             "display_name": "huerfano", "padre": "padre-que-no-existe"},
            {"displayName": "huerfano"},
        )
        try:
            pipeline._ruta_padre(contexto, operacion, {"playbook": {}})
            return False, "aceptó un padre que no existe"
        except pipeline.PipelineError as error:
            texto = str(error)
            return ("padre-que-no-existe" in texto and "playbook" in texto), \
                f"el error no nombra el padre ni su tipo: {texto[:90]}"

    runner.check(1, "Un padre declarado que no existe se rechaza nombrándolo, "
                    "junto al tipo que se esperaba",
                 un_padre_inexistente_se_rechaza_con_su_nombre)

    def cifras_cuadran():
        resultado = pipeline.step_1_inventory(project, agent_id)["data"]
        suma = len(resultado["emparejados"]) + len(resultado["solo_cx"])
        return resultado["total_cx"] == suma, \
            f"total {resultado['total_cx']} != {suma}"

    runner.check(1, "Las cifras cuadran: total = emparejados + solo en CX",
                 cifras_cuadran)

    def el_paso_1_dice_si_falta_el_entorno_de_produccion():
        """Que el Paso 1 lo diga, en vez de descubrirlo el Paso 5.

        Sin entorno de producción el Paso 5 falla — pero fallaba al final, con
        el agente ya escrito y el pipeline entero recorrido. El dato lo tiene
        el Paso 1 desde siempre; solo faltaba mirarlo.

        Se contrasta contra CX directamente, no contra sí mismo: se piden los
        entornos por la API y se compara con lo que el paso declara.

        Y se recorren **los dos agentes**, porque con uno solo no se prueba
        nada: el desechable tiene entorno de producción, así que un paso que
        respondiera «sí» siempre acertaría con él y el check pasaría en verde
        sin haber comprobado nunca el caso que importa. El hermano no tiene
        ninguno — comprobado leyendo CX— y es el que ejercita el «no».
        """
        casos = [a for a in (agent_id, hermano) if a]
        if len(casos) < 2:
            return True, "(sin agente hermano: solo se ejercita el caso «sí»)"
        vistos = set()
        for agente in casos:
            resultado = pipeline.step_1_inventory(project, agente)
            datos = resultado["data"]
            ctx = pipeline.Contexto(project, agente)
            entornos = cx.list_all_pages(project, ctx.region,
                                         f"{ctx.parent}/environments",
                                         "environments")
            real = any(e.get("displayName") == pipeline.ENTORNO_PRODUCCION
                       for e in entornos)
            vistos.add(real)
            if datos["tiene_entorno_produccion"] != real:
                return False, (f"{agente[:8]}: el paso dice "
                               f"{datos['tiene_entorno_produccion']} y en CX "
                               f"es {real}")
            # Cuando falta, tiene que decirlo en el registro, no solo en un
            # campo que el panel podría no llegar a mirar.
            if not real and not any(pipeline.ENTORNO_PRODUCCION in linea
                                    for linea in resultado["log"]):
                return False, f"{agente[:8]}: falta y el registro no lo menciona"
        return len(vistos) == 2, (
            "los dos agentes dan el mismo caso: el «no» no se llega a probar")

    runner.check(1, "El Paso 1 dice si al agente le falta el entorno de "
                    "producción, en vez de dejarlo para el Paso 5",
                 el_paso_1_dice_si_falta_el_entorno_de_produccion)

    def cero_escrituras():
        """1.1 — el Paso 1 no muta nada, y lo único que llega con verbo de
        escritura es `compareVersions`, que solo compara.

        Se comprueban las dos cosas: que no hay mutaciones, y que la excepción
        es exactamente la que se declaró. Sin lo segundo, la excepción sería
        una puerta abierta a cualquier POST que alguien añadiera después.
        """
        with ContadorHttp() as contador:
            pipeline.step_1_inventory(project, agent_id)
        escrituras = contador.escrituras()
        con_verbo = contador.escrituras_crudas()
        coladas = [c for c in con_verbo if c not in escrituras
                   and not c[1].endswith(":compareVersions")]
        return not escrituras and not coladas, (
            f"{len(escrituras)} escrituras: {escrituras[:3]} · "
            f"{len(con_verbo)} con verbo de escritura, de las que "
            f"{len(con_verbo) - len(escrituras)} son compareVersions"
        )

    runner.check(1, "Cero llamadas de escritura, verificado instrumentando el "
                    "cliente HTTP y no leyendo el código — lo único con verbo "
                    "de escritura es compareVersions",
                 cero_escrituras)

    def el_coste_lo_marca_lo_publicado_no_el_tamano_del_agente():
        """1.2 — el coste de comparar tiene que estar acotado por los
        contenedores **publicados**, no por el tamaño del agente.

        Playbooks y tools se comparan con el contenido que el LIST de versiones
        ya trajo; solo los flows fijados cuestan una llamada cada uno. Si algún
        día alguien pide cada versión con un GET aparte, esto lo caza.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fijadas = pipeline._versiones_fijadas(inventario)
        flows_fijados = sum(1 for c in fijadas if "/flows/" in c)
        with ContadorHttp() as contador:
            pipeline._contenedores_cambiados(contexto, inventario)
        total = len(contador.llamadas)
        comparaciones = [c for c in contador.llamadas
                         if c[1].endswith(":compareVersions")]
        contenedores = sum(len(inventario.get(t, {}))
                           for t in pipeline.CONTENIDO_EN_LA_VERSION)
        return (len(comparaciones) <= flows_fijados
                and total == len(comparaciones)), (
            f"{total} llamadas para comparar, {len(comparaciones)} de ellas "
            f"compareVersions, con {flows_fijados} flows fijados y "
            f"{contenedores} contenedores en el borrador"
        )

    runner.check(1, "El coste de comparar lo marcan los contenedores publicados, "
                    "no el tamaño del agente",
                 el_coste_lo_marca_lo_publicado_no_el_tamano_del_agente)

    def compare_versions_contesta_lo_esperado():
        """1.3 y 1.4 — el endpoint sobre el que descansa la comparación de
        flows, contra el agente real y sin tocar nada.

        `versions/0` es como CX nombra el borrador. Con el borrador sin mover
        desde la versión, los dos JSON tienen que ser idénticos byte a byte: es
        lo que permite comparar sin normalizar nada.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(el agente no tiene flows)"
        flow = flows[0]
        versiones = [v for v in inventario.get("version", {}).values()
                     if v.get("name", "").startswith(f"{flow['name']}/versions/")]
        if not versiones:
            # Comparar contra la propia foto del borrador: el endpoint tiene que
            # aceptar `versions/0` en los dos lados y devolver dos JSON iguales.
            base = f"{flow['name']}/versions/0"
        else:
            base = versiones[0]["name"]
        respuesta = cx.api_request(
            "POST", project, contexto.region, f"{base}:compareVersions",
            body={"targetVersion": f"{flow['name']}/versions/0"},
        )
        if respuesta.status_code != 200:
            return False, f"{respuesta.status_code} {respuesta.text[:150]}"
        claves = set(respuesta.json())
        esperadas = {"baseVersionContentJson", "targetVersionContentJson",
                     "compareTime"}
        if not esperadas <= claves:
            return False, f"faltan claves: {sorted(esperadas - claves)}"
        # Y contra sí mismo, que es la única comparación cuya respuesta se
        # conoce de antemano pase lo que pase en el agente.
        espejo = cx.api_request(
            "POST", project, contexto.region,
            f"{flow['name']}/versions/0:compareVersions",
            body={"targetVersion": f"{flow['name']}/versions/0"},
        )
        cuerpo = espejo.json()
        identicos = (cuerpo.get("baseVersionContentJson")
                     == cuerpo.get("targetVersionContentJson"))
        return identicos, (
            "el borrador comparado consigo mismo no dio dos JSON idénticos: "
            "la comparación de flows no se puede sostener sobre esto"
        )

    runner.check(1, "compareVersions contra versions/0 devuelve 200 y las tres "
                    "claves, y sin cambios los dos JSON son idénticos",
                 compare_versions_contesta_lo_esperado)

    def el_paso_1_devuelve_el_resumen_de_produccion():
        """1.5 — con las tres listas, y con la forma que el panel espera."""
        datos = pipeline.step_1_inventory(project, agent_id)["data"]
        comparacion = datos.get("comparacion_produccion")
        if not isinstance(comparacion, dict):
            return False, f"el Paso 1 no devuelve {CAMPO_COMPARACION}"
        faltan = {"cambiados", "borrados", "iguales"} - set(comparacion)
        if faltan:
            return False, f"faltan claves: {sorted(faltan)}"
        filas = [f for lista in comparacion.values() for f in lista]
        sin_forma = [f for f in filas
                     if not {"tipo", "cx_id", "name"} <= set(f)]
        return not sin_forma, (
            f"{len(sin_forma)} filas sin la forma esperada: {sin_forma[:1]}")

    runner.check(1, "El Paso 1 devuelve el resumen de la comparación contra "
                    "producción con las claves esperadas",
                 el_paso_1_devuelve_el_resumen_de_produccion)

    def el_paso_1_y_el_paso_5_usan_el_mismo_criterio():
        """1.6 — un solo criterio, no dos que puedan discrepar.

        Si el Paso 1 enseñara una cosa y el Paso 5 versionara otra, el panel
        estaría informando de algo que no va a pasar — que es peor que no
        informar de nada.
        """
        contexto = pipeline.Contexto(project, agent_id)
        del_paso_1 = pipeline.step_1_inventory(
            project, agent_id)["data"]["comparacion_produccion"]
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        del_paso_5 = pipeline._contenedores_cambiados(contexto, inventario)
        iguales = all(
            _nombres(del_paso_1[clave]) == _nombres(del_paso_5[clave])
            for clave in ("cambiados", "borrados", "iguales")
        )
        return iguales, (
            f"paso 1: { {k: _nombres(v) for k, v in del_paso_1.items()} } · "
            f"paso 5: { {k: _nombres(v) for k, v in del_paso_5.items()} }")

    runner.check(1, "El resumen del Paso 1 y lo que el Paso 5 usaría coinciden: "
                    "no hay dos criterios distintos",
                 el_paso_1_y_el_paso_5_usan_el_mismo_criterio)

    def el_servidor_no_se_come_el_campo_nuevo():
        """1.7 — el campo viaja hasta la respuesta HTTP.

        Se llama a la vista del servidor, no a la función del pipeline: entre
        una y otra está el sobre, el `jsonify` y el traductor de errores, y
        cualquiera de los tres podría filtrar campos. Comprobarlo leyendo el
        código sería fiarse de que nadie añade un filtro después.
        """
        from act import server_cloudrun

        with server_cloudrun.app.test_client() as cliente:
            respuesta = cliente.post("/step/1",
                                     json={"project": project, "agent": agent_id})
        if respuesta.status_code != 200:
            return False, f"HTTP {respuesta.status_code}: {respuesta.get_data(as_text=True)[:150]}"
        datos = respuesta.get_json().get("data", {})
        comparacion = datos.get(CAMPO_COMPARACION)
        return isinstance(comparacion, dict) and "borrados" in comparacion, (
            f"la respuesta HTTP no trae `{CAMPO_COMPARACION}`: "
            f"claves={sorted(datos)[:12]}")

    runner.check(1, "El servidor transporta el campo nuevo del Paso 1 hasta la "
                    "respuesta HTTP",
                 el_servidor_no_se_come_el_campo_nuevo)

    def sin_destino_error_claro():
        try:
            pipeline.step_1_inventory("", "")
            return False, "aceptó destino vacío"
        except ValueError as error:
            return "project" in str(error), str(error)[:80]

    runner.check(1, "Ejecutar sin project o sin agent termina con mensaje claro",
                 sin_destino_error_claro)

    def descubrimiento_lista_proyectos():
        datos = pipeline.discover()["data"]
        proyectos = datos["proyectos"]
        return bool(proyectos) and all("projectId" in p for p in proyectos), \
            f"{len(proyectos)} proyectos, sin projectId en alguno"

    runner.check(1, "Descubrimiento sin proyecto devuelve la lista de proyectos GCP",
                 descubrimiento_lista_proyectos)

    def descubrimiento_lista_agentes_con_su_repositorio():
        datos = pipeline.discover(project)["data"]
        agentes = datos["agentes"]
        nuestro = next((a for a in agentes if a["agentId"] == agent_id), None)
        if nuestro is None:
            return False, "el agente desechable no aparece en el descubrimiento"
        campos = {"agentId", "displayName", "region", "repo", "rama", "vinculado"}
        return campos <= set(nuestro) and nuestro["vinculado"] and nuestro["repo"], \
            f"faltan campos o no viene vinculado: {nuestro}"

    runner.check(1, "Descubrimiento devuelve cada agente con el repositorio que "
                    "le corresponde — es lo que rellena los desplegables del panel",
                 descubrimiento_lista_agentes_con_su_repositorio)

    def agentes_sin_repositorio_no_se_omiten():
        datos = pipeline.discover(project)["data"]
        sin_vincular = [a for a in datos["agentes"] if not a["vinculado"]]
        # Lo que importa no es que existan, sino que si existen vengan marcados
        # en vez de desaparecer: omitirlos los haría invisibles justo cuando
        # hace falta vincularlos.
        return all(a["repo"] is None for a in sin_vincular), \
            "un agente sin vincular trae repositorio"

    runner.check(1, "Un agente sin repositorio se incluye marcado, nunca se omite "
                    "en silencio",
                 agentes_sin_repositorio_no_se_omiten)

    def los_trece_tipos_traen_contenido():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        vacios = [t for t, items in inventario.items() if not items]
        return not vacios, f"sin contenido: {sorted(vacios)}"

    runner.check(1, "Los 13 tipos devuelven contenido real, no solo responden",
                 los_trece_tipos_traen_contenido)

    if hermano:
        def cada_agente_ve_solo_lo_suyo():
            """Un repositorio compartido no puede filtrar los archivos de un
            agente en la vista de otro.

            Sin el filtro por agente, los archivos del hermano aparecerían
            como "solo en el repositorio" del nuestro — pendientes de crear en
            CX, cuando ya existen en su propio agente.
            """
            resultados = {}
            for quien in (agent_id, hermano):
                ctx = pipeline.Contexto(project, quien)
                inv, _, _ = pipeline.inventariar_cx(ctx)
                repo, _ = pipeline.cargar_repositorio(ctx)
                grupos = pipeline.emparejar(inv, repo)
                resultados[quien] = {
                    "mios": {e["cx_id"] for e in grupos["emparejados"]},
                    "rutas": {e["ruta"] for e in grupos["emparejados"]},
                    "solo_repo": len(grupos["solo_repo"]),
                    "otros": len(repo["otros_agentes"]),
                }
            a, b = resultados[agent_id], resultados[hermano]
            comunes = a["rutas"] & b["rutas"]
            if comunes:
                return False, f"{len(comunes)} archivos aparecen en los dos agentes"
            if not a["otros"] or not b["otros"]:
                return False, ("ninguno de los dos ve archivos del otro: no "
                               "están compartiendo repositorio de verdad")
            return True, (f"{a['otros']} y {b['otros']} archivos ajenos, "
                          f"contados aparte y fuera del reparto")

        runner.check(1, "Dos agentes comparten repositorio sin mezclarse: "
                        "ningún archivo aparece en los dos, y los ajenos se "
                        "cuentan aparte en vez de salir como pendientes",
                     cada_agente_ve_solo_lo_suyo)

        def el_mismo_cx_id_en_dos_agentes_no_colisiona():
            """CX reutiliza identificadores entre agentes.

            Verificado con agentes reales: sus "Default Start Flow" y "Default
            Welcome Intent" comparten cx_id. Con la clave sin el agente, la
            defensa de duplicados saltaría el primer día y nada arrancaría.
            """
            ids = {}
            for quien in (agent_id, hermano):
                ctx = pipeline.Contexto(project, quien)
                inv, _, _ = pipeline.inventariar_cx(ctx)
                for tipo, items in inv.items():
                    for cx_id in items:
                        ids.setdefault((tipo, cx_id), set()).add(quien)
            compartidos = {k: v for k, v in ids.items() if len(v) > 1}
            if not compartidos:
                return False, ("los dos agentes no comparten ningún cx_id, así "
                               "que el caso no se llega a probar")
            # Y aun compartiéndolos, cargar el repositorio no protesta.
            pipeline.cargar_repositorio(pipeline.Contexto(project, agent_id))
            return True, (f"{len(compartidos)} identificadores compartidos entre "
                          f"los dos agentes, sin colisión")

        runner.check(1, "Dos agentes con el mismo cx_id no disparan la defensa "
                        "de duplicados: la clave lleva el agente",
                     el_mismo_cx_id_en_dos_agentes_no_colisiona)

        def un_resource_ajeno_no_entra_en_el_diff():
            datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
            ctx = pipeline.Contexto(project, hermano)
            repo_hermano, _ = pipeline.cargar_repositorio(ctx)
            suyas = {e["ruta"] for por_tipo in repo_hermano["por_tipo"].values()
                     for e in por_tipo.values()}
            intrusas = [o["ruta"] for o in datos["operaciones"] if o.get("ruta") in suyas]
            return not intrusas, f"el diff propone tocar archivos del hermano: {intrusas[:3]}"

        runner.check(1, "El diff de un agente no propone nada sobre los archivos "
                        "de su hermano",
                     un_resource_ajeno_no_entra_en_el_diff)
    else:
        runner.skip(1, "Dos agentes comparten repositorio sin mezclarse",
                    "hace falta --agente-hermano: un segundo agente desechable "
                    "del mismo proyecto")

    def un_archivo_sin_agente_se_cuenta_aparte():
        """Un archivo con cabecera pero sin `agente` no es de nadie.

        Filtrando por agente desaparecería de todas las vistas sin dejar
        rastro: no se puede aplicar en ninguno y nadie sabría por qué. El
        Paso 1 es el único momento que lee el repositorio entero antes de
        repartirlo, así que es el único sitio donde se puede contar.
        """
        original = contexto.gh.read_repo_files
        archivos = dict(original(contexto.gh.branch_head(contexto.rama)))
        huerfano = {"path": "definitions/intents/sin_dueno.yaml"}
        archivos[huerfano["path"]] = (
            b"metadata:\n  tipo: intent\n  padre: null\n"
            b"  cx_id: null\ndisplayName: sin_dueno\n")
        contexto.gh.read_repo_files = lambda *_a, **_k: archivos
        try:
            repositorio, _ = pipeline.cargar_repositorio(contexto)
            sin_agente = [e["ruta"] for e in repositorio["sin_agente"]]
            en_el_reparto = any(
                e["ruta"] == huerfano["path"]
                for por_tipo in repositorio["por_tipo"].values()
                for e in por_tipo.values()
            ) or any(e["ruta"] == huerfano["path"] for e in repositorio["sin_cx_id"])
            return (huerfano["path"] in sin_agente and not en_el_reparto), (
                f"sin_agente={sin_agente[:2]} · entró en el reparto={en_el_reparto}"
            )
        finally:
            contexto.gh.read_repo_files = original

    runner.check(1, "Un archivo con cabecera pero sin agente se cuenta aparte y "
                    "no entra en el reparto de ningún agente",
                 un_archivo_sin_agente_se_cuenta_aparte)

    runner.skip(1, "Dos pares proyecto+agente en el mismo proceso no se contaminan",
                "exige un segundo agente desechable; la propiedad que probaría "
                "—que la cabecera de cuota no se cachea— sí está cubierta en el "
                "Nivel 4 sin necesitarlo")


# ── Nivel 2 · Dry-run ────────────────────────────────────────────────────────

def nivel_2(runner, project, agent_id):
    print("\nNIVEL 2 — Dry-run · no escribe nada")

    def dry_run_no_escribe():
        with ContadorHttp() as contador:
            pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)
        escrituras = contador.escrituras()
        return not escrituras, f"{len(escrituras)} escrituras en dry-run"

    runner.check(2, "El dry-run no hace ninguna llamada de escritura",
                 dry_run_no_escribe)

    def se_puede_saber_que_versionaria_sin_versionar_nada():
        """2.2 — el equivalente de un dry-run para el Paso 5.

        No hace falta un `dry_run` en `step_5_publish`: la comparación es una
        función aparte y de solo lectura, así que preguntarle qué versionaría no
        crea nada. Es lo mismo que el Paso 1 devuelve al panel y lo mismo que el
        Paso 5 usará, así que un dry-run propio sería un tercer camino que
        podría discrepar de los otros dos.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        antes = pipeline._versiones_fijadas(inventario)
        with ContadorHttp() as contador:
            comparacion = pipeline._contenedores_cambiados(contexto, inventario)
        despues = versiones_fijadas_ahora(contexto)
        versiones_antes = len(inventario.get("version", {}))
        inv2, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow", "playbook",
                                                              "tool", "version"])
        return (not contador.escrituras() and antes == despues
                and len(inv2.get("version", {})) == versiones_antes), (
            f"listó {len(comparacion['cambiados'])} contenedores a versionar · "
            f"{len(contador.escrituras())} escrituras · entorno intacto="
            f"{antes == despues} · versiones {versiones_antes} → "
            f"{len(inv2.get('version', {}))}")

    runner.check(2, "Se puede saber qué versionaría el Paso 5 sin crear ninguna "
                    "versión ni mover el entorno",
                 se_puede_saber_que_versionaria_sin_versionar_nada)

    def plan_estable():
        a = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        b = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        clave = lambda d: sorted((o["operacion"], o["tipo"], str(o["cx_id"]))
                                 for o in d["operaciones"])
        return clave(a) == clave(b), "dos dry-run seguidos dan planes distintos"

    runner.check(2, "Dos dry-run sobre el mismo estado dan el mismo plan",
                 plan_estable)

    def nunca_delete_por_ausencia():
        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        borrados = [o for o in datos["operaciones"] if o["operacion"] == "DELETE"]
        return not borrados, f"{len(borrados)} DELETE propuestos sin pedirlos"

    runner.check(2, "El diff nunca propone DELETE por ausencia en el repositorio",
                 nunca_delete_por_ausencia)

    def borrado_exige_que_no_tenga_archivo():
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        emparejado = None
        for tipo, items in repositorio["por_tipo"].items():
            for cx_id in items:
                if cx_id in inventario.get(tipo, {}):
                    emparejado = {"tipo": tipo, "cx_id": cx_id}
                    break
            if emparejado:
                break
        if not emparejado:
            return True, "(sin resources emparejados que probar)"
        try:
            pipeline.calcular_diff(contexto, inventario, repositorio, [emparejado])
            return False, "aceptó borrar un resource que sí tiene archivo"
        except pipeline.PipelineError as error:
            return "repositorio" in str(error), str(error)[:80]

    runner.check(2, "Pedir borrar algo que sí tiene archivo en el repositorio "
                    "se rechaza — el servidor comprueba, no obedece",
                 borrado_exige_que_no_tenga_archivo)

    def borrado_de_algo_inexistente_se_rechaza():
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        try:
            pipeline.calcular_diff(contexto, inventario, repositorio,
                                   [{"tipo": "intent", "cx_id": "no-existe"}])
            return False, "aceptó borrar algo que no está en el agente"
        except pipeline.PipelineError:
            return True, ""

    runner.check(2, "Pedir borrar algo que no existe en el agente se rechaza",
                 borrado_de_algo_inexistente_se_rechaza)

    def full_update_sin_mask_para_playbooks():
        texto = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(texto)
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "_patch_full_update")
        fuente = ast.get_source_segment(texto, funcion)
        return "updateMask" not in fuente.split('"""')[-1], \
            "el Full Update genérico manda updateMask"

    runner.check(2, "El Full Update genérico no manda updateMask",
                 full_update_sin_mask_para_playbooks)

    def entorno_si_manda_mask():
        texto = (REPO_ROOT / "act/act_cx_resources_deploy_cloudrun.py").read_text()
        arbol = ast.parse(texto)
        funcion = next(n for n in ast.walk(arbol)
                       if isinstance(n, ast.FunctionDef) and n.name == "_apuntar_entorno")
        return "updateMask" in ast.get_source_segment(texto, funcion), \
            "el PATCH del entorno no manda updateMask, y la API lo exige"

    runner.check(2, "El PATCH del entorno sí manda updateMask — es la excepción "
                    "inversa, sin él responde code:3",
                 entorno_si_manda_mask)

    def sin_cambios_lo_dice():
        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        if datos["operaciones"]:
            return True, "(hay cambios pendientes; no aplica en esta corrida)"
        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        return resultado["data"]["aplicadas"] == 0 and resultado["status"] == "ok", \
            "con cero cambios no lo reportó limpiamente"

    runner.check(2, "Sin cambios, el paso lo dice y no continúa como si hubiera algo",
                 sin_cambios_lo_dice)

    # ── Defensas que solo se disparan cuando algo va mal ─────────────────────
    #
    # Ninguna se había ejecutado nunca. Una defensa que no se ha probado es una
    # suposición: el día que haga falta es el día que se descubre si funciona.

    def cx_id_duplicado_para():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        archivos = original(contexto.gh.branch_head(contexto.rama))
        # Tiene que ser un archivo que de verdad sea un resource de este
        # agente: copiar uno sin cabecera no dispara nada, y copiar uno de otro
        # agente tampoco tiene por que — su clave lleva otro agente.
        repositorio, _ = pipeline.cargar_repositorio(contexto)
        propias = [e["ruta"] for por_tipo in repositorio["por_tipo"].values()
                   for e in por_tipo.values()]
        origen = next((r for r in propias if r in archivos), None)
        if origen is None:
            return True, "(el agente no tiene ningun resource en el repositorio)"

        copia = dict(archivos)
        copia[origen.replace(".yaml", "_copia.yaml")] = archivos[origen]
        contexto.gh.read_repo_files = lambda *_a, **_k: copia
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "acepto dos archivos con el mismo tipo y cx_id"
        except pipeline.PipelineError as error:
            return "cx_id" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Dos archivos con el mismo tipo y cx_id paran el pipeline — "
                    "duplicar un YAML y olvidar vaciar el id deja dos "
                    "reclamando el mismo resource",
                 cx_id_duplicado_para)

    def tipo_desconocido_da_error_explicito():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        contexto.gh.read_repo_files = lambda *_a, **_k: {
            "definitions/raro/x.yaml":
                b"metadata:\n  tipo: tipo_inventado\n  cx_id: abc\n"
                b"  agente: x\ndisplayName: x\n"}
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "aceptó un tipo que no existe"
        except pipeline.PipelineError as error:
            return "tipo_inventado" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Un YAML con un tipo que no existe da error nombrándolo, "
                    "no se vuelve invisible",
                 tipo_desconocido_da_error_explicito)

    def yaml_mal_formado_dice_que_archivo():
        contexto = pipeline.Contexto(project, agent_id)
        original = contexto.gh.read_repo_files
        contexto.gh.read_repo_files = lambda *_a, **_k: {
            "definitions/roto.yaml": b"metadata:\n  tipo: [sin cerrar\n"}
        try:
            pipeline.cargar_repositorio(contexto)
            return False, "aceptó un YAML mal formado"
        except pipeline.PipelineError as error:
            return "definitions/roto.yaml" in str(error), str(error)[:90]
        finally:
            contexto.gh.read_repo_files = original

    runner.check(2, "Un YAML mal formado dice qué archivo lo provocó",
                 yaml_mal_formado_dice_que_archivo)

    def rama_inexistente_falla_claro():
        cliente = store.get_client()
        mapeo = store.get_agent_mapping(cliente, project, agent_id)
        store.save_agent_mapping(cliente, project, agent_id, mapeo["region"],
                                 "rama-que-no-existe",
                                 mapeo.get("carpeta_raiz", "definitions"))
        try:
            pipeline.step_1_inventory(project, agent_id)
            return False, "no falló con una rama inexistente"
        except Exception as error:
            return "404" in str(error) or "not found" in str(error).lower(), \
                str(error)[:90]
        finally:
            store.save_agent_mapping(cliente, project, agent_id, mapeo["region"],
                                     mapeo["rama"],
                                     mapeo.get("carpeta_raiz", "definitions"))

    runner.check(2, "Una rama que no existe en el mapeo falla, no devuelve un "
                    "repositorio vacío",
                 rama_inexistente_falla_claro)

    def etiqueta_de_version_validada():
        malas = ["", "con espacios", "con/barra", "acentué", None]
        for mala in malas:
            try:
                pipeline.step_5_publish(project, agent_id, mala)
                return False, f"aceptó el nombre de versión {mala!r}"
            except ValueError:
                continue
            except Exception as error:
                return False, f"{mala!r} falló por otra razón: {type(error).__name__}"
        return True, ""

    runner.check(2, "Un nombre de versión inválido se rechaza antes de tocar nada",
                 etiqueta_de_version_validada)

    def url_de_repositorio_validada():
        for mala in ["", "no-es-una-url", "https://github.com/solo-usuario",
                     "https://gitlab.com/a/b/c/d"]:
            try:
                pipeline._repo_desde_url(mala)
                return False, f"aceptó {mala!r} como repositorio"
            except ValueError:
                continue
        buena = pipeline._repo_desde_url("https://github.com/usuario/repo.git")
        return buena == "usuario/repo", buena

    runner.check(2, "Una URL de repositorio que no lo es se rechaza",
                 url_de_repositorio_validada)

    def tests_solo_admite_dos_respuestas():
        for valor in ("ok", "", None, "SUPERADOS"):
            try:
                pipeline.step_4_validate_tests(project, agent_id, valor)
                return False, f"aceptó {valor!r} como resultado de los tests"
            except ValueError:
                continue
        return True, ""

    runner.check(2, "Declarar los tests solo admite 'superados' o 'fallidos'",
                 tests_solo_admite_dos_respuestas)



# ── Nivel 3 · Escritura real ─────────────────────────────────────────────────

def nivel_3(runner, project, agent_id, run_id):
    print("\nNIVEL 3 — Escritura real · contra el agente desechable")

    contexto = pipeline.Contexto(project, agent_id)
    etiqueta = f"{PREFIJO}_{run_id}"
    creados = []

    # Punto al que se devuelve la rama al terminar. Sin esto, un resource que
    # el nivel crea en CX y trae al repositorio sobrevive al borrado —
    # desaparece de CX pero su archivo se queda, y el inventario siguiente lo
    # reporta como cx_id fantasma para siempre. Encontrado ejecutando: el
    # Nivel 1 falló por el residuo que había dejado el Nivel 3.
    rama_al_empezar = contexto.gh.branch_head(contexto.rama)
    # También la principal: el nivel publica, y publicar fusiona una en
    # otra. Revertir solo la de trabajo las dejaba divergidas y la corrida
    # siguiente no podía fusionar.
    principal_al_empezar = contexto.gh.branch_head(contexto.rama_principal)

    def _desanclar_lo_de_las_pruebas(_inventario=None):
        """Delega en la compartida — ver `desanclar_lo_de_las_pruebas`."""
        return desanclar_lo_de_las_pruebas(contexto, project)

    def barrer_restos_previos():
        """Barrido al empezar: un finally no sobrevive a un SIGKILL, así que el
        residuo de una corrida muerta se limpia en la siguiente."""
        return barrer_cx_de_las_pruebas(contexto, project)

    runner.check(3, "Barrido de restos antes de empezar", barrer_restos_previos)

    def crear_intent_de_prueba():
        respuesta = cx.api_post(
            project, contexto.region, f"{contexto.parent}/intents",
            {"displayName": f"{etiqueta}_intent",
             "trainingPhrases": [{"parts": [{"text": "hola prueba"}], "repeatCount": 1}]},
        )
        if respuesta.status_code not in (200, 201):
            return False, f"{respuesta.status_code} {respuesta.text[:120]}"
        creados.append(respuesta.json()["name"])
        return True, ""

    runner.check(3, "Crear un resource real en el agente desechable",
                 crear_intent_de_prueba)

    def version_sin_display_name_se_detecta():
        """El bug de code:3 silencioso: la API devuelve 200 y la operación falla
        después. Sin polear, el paso se daría por bueno."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(el agente no tiene flows)"
        respuesta = cx.api_post(project, contexto.region,
                                f"{flows[0]['name']}/versions", {})
        if respuesta.status_code not in (200, 201):
            return True, f"la API ya lo rechazó de entrada ({respuesta.status_code})"
        try:
            cx.resolve_operation(project, contexto.region, respuesta)
            return False, "una versión sin displayName se dio por buena"
        except cx.ApiError as error:
            return True, f"detectado al polear: {str(error)[:70]}"

    runner.check(3, "Una versión sin displayName se detecta poleando la operación, "
                    "nunca por el 200 inicial",
                 version_sin_display_name_se_detecta)

    def produccion_no_se_mueve_en_el_paso_3():
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        antes = {
            e.get("displayName"): [c["version"] for c in e.get("versionConfigs", [])]
            for e in inventario.get("environment", {}).values()
        }
        pipeline.step_3_apply_to_cx(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        despues = {
            e.get("displayName"): [c["version"] for c in e.get("versionConfigs", [])]
            for e in inventario.get("environment", {}).values()
        }
        return antes == despues, "el Paso 3 movió el puntero de algún entorno"

    runner.check(3, "El Paso 3 no mueve el puntero de ningún entorno — escribe "
                    "solo en el borrador",
                 produccion_no_se_mueve_en_el_paso_3)

    def aplicar_dos_veces_es_idempotente():
        primera = pipeline.step_3_apply_to_cx(project, agent_id)["data"]
        segunda = pipeline.step_3_apply_to_cx(project, agent_id)["data"]
        return segunda["aplicadas"] == 0, (
            f"la segunda pasada volvió a aplicar {segunda['aplicadas']} "
            f"(la primera aplicó {primera['aplicadas']})"
        )

    runner.check(3, "Aplicar el mismo diff dos veces no vuelve a escribir",
                 aplicar_dos_veces_es_idempotente)

    def pull_deja_un_commit_y_solo_uno():
        datos = pipeline.step_1_inventory(project, agent_id)["data"]
        traibles = [{"tipo": x["tipo"], "cx_id": x["cx_id"]}
                    for x in datos["solo_cx"] if x["traible"]]
        if not traibles:
            return True, "(no hay nada que traer en este estado)"
        primera = pipeline.step_2_pull_to_repo(project, agent_id, traibles)["data"]
        segunda = pipeline.step_2_pull_to_repo(project, agent_id, traibles)["data"]
        return bool(primera["commit"]) and segunda["commit"] is None, (
            f"primera={primera['commit']} segunda={segunda['commit']}"
        )

    runner.check(3, "Traer al repositorio deja un solo commit, y repetirlo no crea "
                    "un segundo",
                 pull_deja_un_commit_y_solo_uno)

    def los_trece_tipos_ciclo_completo():
        """Create, update y delete real de cada tipo desplegable.

        Los tipos poco comunes pueden tener comportamiento propio que no se
        descubre nunca si solo se prueban los cuatro conocidos.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos, probados = [], []
        for tipo, spec in pipeline.TIPOS_DESPLEGABLES.items():
            if spec.get("singular"):
                continue  # el agente no se crea ni se borra desde aquí
            padre = contexto.parent
            if spec.get("padre"):
                candidatos = list(inventario.get(spec["padre"], {}).values())
                if not candidatos:
                    fallos.append(f"{tipo}: sin padre donde colgarlo")
                    continue
                padre = candidatos[0]["name"]

            # Sufijo propio: sin él choca con el resource que este mismo nivel
            # crea al empezar, y la API responde 409 AlreadyExists.
            cuerpo = {"displayName": f"{etiqueta}_ciclo_{tipo}"}
            if tipo == "entity_type":
                cuerpo.update({"kind": "KIND_MAP",
                               "entities": [{"value": "a", "synonyms": ["a"]}]})
            elif tipo == "webhook":
                cuerpo.update({"genericWebService": {"uri": "https://example.invalid/x"},
                               "timeout": "5s"})
            elif tipo == "generator":
                cuerpo.update({"promptText": {"text": "resume"}})
            elif tipo == "playbook":
                cuerpo.update({"goal": "objetivo de prueba",
                               "playbookType": "ROUTINE",
                               "instruction": {"steps": [{"text": "haz algo"}]}})
            elif tipo == "example":
                cuerpo.update({"actions": [{"userUtterance": {"text": "hola"}},
                                           {"agentUtterance": {"text": "hola"}}],
                               "conversationState": "OUTPUT_STATE_OK"})
            elif tipo == "tool":
                cuerpo.update({"description": "herramienta de prueba",
                               "openApiSpec": {"textSchema":
                                   "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n"}})

            creado = cx.api_post(project, contexto.region,
                                 f"{padre}/{spec['api']}", cuerpo)
            if creado.status_code not in (200, 201):
                fallos.append(f"{tipo} CREATE {creado.status_code}: "
                              f"{creado.text[:90]}")
                continue
            nombre = cx.resolve_operation(project, contexto.region, creado)["name"]

            actual = cx.api_get(project, contexto.region, nombre).json()
            actual["displayName"] = f"{etiqueta}_ciclo_{tipo}_mod"
            for campo in payloads.ignore_fields_for(tipo):
                actual.pop(campo, None)
            modificado = cx.api_patch(project, contexto.region, nombre, actual)
            if modificado.status_code not in (200, 201):
                fallos.append(f"{tipo} UPDATE {modificado.status_code}: "
                              f"{modificado.text[:90]}")

            cx.api_delete(project, contexto.region, nombre)
            if cx.api_get(project, contexto.region, nombre).status_code != 404:
                fallos.append(f"{tipo} DELETE no surtió efecto")
            probados.append(tipo)

        return not fallos, (f"probados {len(probados)} · " + " | ".join(fallos))

    runner.check(3, "Create, update y delete real de cada tipo desplegable, "
                    "confirmando el borrado leyendo el resultado",
                 los_trece_tipos_ciclo_completo)

    def el_ciclo_del_cx_id_se_cierra():
        """Un resource que nace en el repositorio recibe su id de CX y ese id
        vuelve al archivo.

        Es el ciclo completo de la cabecera: el archivo nace sin `cx_id`
        —no puede tenerlo, no existe en ningún sitio y el id lo asigna CX—, se
        sube, y el id que devuelve CX se escribe de vuelta en su `metadata`.

        Si el id no vuelve, la cabecera queda incompleta para siempre y cada
        deploy vuelve a tratar el archivo como inexistente en CX: un duplicado
        por pasada, contra la idempotencia de CLAUDE.md §3.4.
        """
        ruta = f"definitions/intents/{etiqueta}_ciclo.yaml"
        documento = {
            "metadata": {"tipo": "intent", "padre": None, "cx_id": None,
                         "agente": agent_id},
            "displayName": f"{etiqueta}_ciclo",
            "trainingPhrases": [{"parts": [{"text": "ciclo"}], "repeatCount": 1}],
        }
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: __import__("yaml").safe_dump(documento, allow_unicode=True,
                                               sort_keys=False)},
            f"test: resource nuevo sin cx_id ({etiqueta})",
        )

        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        if resultado["status"] != "ok":
            return False, f"el Paso 3 falló: {resultado['status']}"

        archivos = contexto.gh.read_repo_files(contexto.gh.branch_head(contexto.rama))
        if ruta not in archivos:
            return False, "el archivo desapareció del repositorio"
        guardado = (__import__("yaml").safe_load(archivos[ruta])
                    .get("metadata", {}).get("cx_id"))
        if not guardado:
            return False, ("el cx_id no volvió al archivo: la cabecera sigue "
                           "incompleta y el próximo deploy lo creará otra vez")

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["intent"])
        real = next((pipeline._cx_id_de(i) for i in inventario["intent"].values()
                     if i.get("displayName") == f"{etiqueta}_ciclo"), None)
        if guardado != real:
            return False, f"el archivo guarda {guardado} y CX dice {real}"

        # La prueba de verdad: el deploy siguiente no propone nada sobre él.
        pendientes = [o for o in pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
            if o["ruta"] == ruta]
        if pendientes:
            # El mensaje se construye solo cuando hay algo que contar: armarlo
            # siempre indexaría una lista vacía en el camino bueno.
            return False, (f"el segundo deploy propone "
                           f"{pendientes[0]['operacion']} sobre el mismo "
                           f"archivo: el ciclo no se cerró")
        return True, ""

    runner.check(3, "El cx_id que asigna CX vuelve al archivo, y el deploy "
                    "siguiente no vuelve a crear el resource",
                 el_ciclo_del_cx_id_se_cierra)

    def el_ciclo_se_cierra_en_todos_los_tipos():
        """El ciclo completo de la cabecera, barriendo todos los tipos.

        Se escribe un YAML nuevo de cada tipo desplegable —con `tipo`, con
        `padre` si cuelga de otro, y sin `cx_id`— en un solo commit. Se aplica
        una vez. Y se comprueba, tipo por tipo, que CX lo creó donde tocaba,
        que el id volvió al archivo, y que el deploy siguiente no propone nada
        sobre ninguno.

        Un tipo puede tener su propio comportamiento y no se descubre nunca si
        solo se prueba con el fácil, que es el que cuelga del agente.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        archivos, esperados = {}, {}

        for tipo, spec in pipeline.TIPOS_DESPLEGABLES.items():
            if spec.get("singular") or tipo not in CUERPO_MINIMO:
                continue
            padre_id = None
            if spec.get("padre"):
                padres = list(inventario.get(spec["padre"], {}))
                if not padres:
                    continue  # sin padre donde colgarlo, no aplica
                padre_id = padres[0]
            nombre = f"{etiqueta}_ciclo_{tipo}"
            ruta = f"definitions/{tipo}s/{nombre}.yaml"
            archivos[ruta] = __import__("yaml").safe_dump(
                {"metadata": {"tipo": tipo, "padre": padre_id, "cx_id": None,
                              "agente": agent_id},
                 "displayName": nombre, **CUERPO_MINIMO[tipo]},
                allow_unicode=True, sort_keys=False)
            esperados[tipo] = {"ruta": ruta, "nombre": nombre, "padre": padre_id}

        if not archivos:
            return False, "no se pudo fabricar ningún resource de prueba"

        contexto.gh.commit_files(
            contexto.rama, archivos,
            f"test: un resource nuevo de cada tipo, sin cx_id ({etiqueta})")

        resultado = pipeline.step_3_apply_to_cx(project, agent_id)
        if resultado["status"] != "ok":
            fallidas = [f"{o['tipo']}: {o.get('error', '')[:60]}"
                        for o in resultado["data"]["operaciones"]
                        if o.get("result") == "ERROR"]
            return False, f"el Paso 3 falló · {' | '.join(fallidas)}"

        arbol = contexto.gh.read_repo_files(contexto.gh.branch_head(contexto.rama))
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fallos = []
        for tipo, esperado in esperados.items():
            creado = next((i for i in inventario.get(tipo, {}).values()
                           if i.get("displayName") == esperado["nombre"]), None)
            if creado is None:
                fallos.append(f"{tipo}: no se creó en CX")
                continue
            crudo = arbol.get(esperado["ruta"])
            if crudo is None:
                fallos.append(f"{tipo}: su archivo desapareció del repositorio")
                continue
            meta = (__import__("yaml").safe_load(crudo).get("metadata") or {})
            if meta.get("cx_id") != pipeline._cx_id_de(creado):
                fallos.append(f"{tipo}: el archivo guarda {meta.get('cx_id')!r} "
                              f"y CX dice {pipeline._cx_id_de(creado)!r}")
            if esperado["padre"] and esperado["padre"] not in creado.get("name", ""):
                fallos.append(f"{tipo}: colgó de otro padre")

        pendientes = [o["tipo"] for o in pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
            if o.get("ruta") in {e["ruta"] for e in esperados.values()}]
        if pendientes:
            fallos.append(f"el 2º deploy vuelve a proponer: {sorted(set(pendientes))}")

        return not fallos, f"probados {len(esperados)} tipos · " + " | ".join(fallos)

    runner.check(3, "El ciclo de la cabecera se cierra en todos los tipos: nacen "
                    "sin cx_id, CX se lo da, vuelve al archivo, y el deploy "
                    "siguiente no propone nada",
                 el_ciclo_se_cierra_en_todos_los_tipos)

    def la_cabecera_nunca_viaja_a_cx():
        """El bloque `metadata` es del repositorio, no del agente.

        Se comprueba sobre el cuerpo que sale de verdad y sobre el resource
        leído de vuelta desde CX — no inspeccionando el código, que pasaría
        aunque la línea que lo quita fuera inalcanzable.
        """
        enviados = []
        original = cx.api_request

        def espia(method, project_, region, path, body=None, **kw):
            if method in ("POST", "PATCH") and isinstance(body, dict):
                enviados.append((path, body))
            return original(method, project_, region, path, body=body, **kw)

        cx.api_request = espia
        try:
            pipeline.step_3_apply_to_cx(project, agent_id)
        finally:
            cx.api_request = original

        con_cabecera = [p for p, b in enviados if "metadata" in b]
        if con_cabecera:
            return False, f"la cabecera viajó a la API en: {con_cabecera[:2]}"

        inventario, _, _ = pipeline.inventariar_cx(contexto)
        en_borrador = [
            item.get("displayName") for items in inventario.values()
            for item in items.values() if "metadata" in item
        ]
        return not en_borrador, (
            f"hay resources con metadata en el borrador: {en_borrador[:3]}"
        )

    runner.check(3, "La cabecera metadata no viaja a CX ni aparece en el "
                    "borrador — comprobado sobre el cuerpo enviado y sobre el "
                    "resource leído de vuelta",
                 la_cabecera_nunca_viaja_a_cx)

    def full_update_no_borra_los_handlers_del_flow():
        """El bug ya documentado: un PATCH parcial intenta borrar los
        eventHandlers que ningún YAML declara, y la API responde 400."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(el agente no tiene flows)"
        flow = flows[0]
        antes = len(cx.api_get(project, contexto.region, flow["name"])
                    .json().get("eventHandlers", []))
        if antes == 0:
            return True, "(el flow no tiene eventHandlers que preservar)"

        operacion = pipeline._operacion(
            "PATCH", "flow", pipeline._cx_id_de(flow),
            {"ruta": "sintetico", "display_name": flow["displayName"]},
            {"description": f"tocado por {etiqueta}"},
            remote_name=flow["name"],
        )
        pipeline._patch_full_update(contexto, operacion)
        despues = len(cx.api_get(project, contexto.region, flow["name"])
                      .json().get("eventHandlers", []))
        return antes == despues, (
            f"el Full Update pasó de {antes} a {despues} eventHandlers"
        )

    runner.check(3, "Full Update en un flow con eventHandlers implícitos no los "
                    "borra — es la reproducción del bug ya documentado",
                 full_update_no_borra_los_handlers_del_flow)

    def full_update_en_playbook_aplica_de_verdad():
        """El bug de §3.8: en europe-west1 el PATCH con updateMask devuelve 200
        y no aplica nada. Lo que se comprueba es que el Full Update sí aplica —
        leyendo el resultado, no el código de respuesta."""
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        playbooks = list(inventario.get("playbook", {}).values())
        if not playbooks:
            return True, "(el agente no tiene playbooks)"
        playbook = playbooks[0]
        nuevo = f"objetivo cambiado por {etiqueta}"
        operacion = pipeline._operacion(
            "PATCH", "playbook", pipeline._cx_id_de(playbook),
            {"ruta": "sintetico", "display_name": playbook["displayName"]},
            {"goal": nuevo}, remote_name=playbook["name"],
        )
        pipeline._patch_full_update(contexto, operacion)
        leido = cx.api_get(project, contexto.region, playbook["name"]).json()
        return leido.get("goal") == nuevo, (
            f"el cambio no llegó: goal = {leido.get('goal')!r}"
        )

    runner.check(3, "Full Update en un playbook aplica de verdad, confirmado "
                    "leyendo el objeto y no el código de respuesta",
                 full_update_en_playbook_aplica_de_verdad)

    def declarar_tests_da_una_huella_que_cambia():
        """Si la huella no cambiara al cambiar el borrador, el aviso de 'draft
        movido' del Paso 5 no avisaría de nada."""
        antes = pipeline.step_4_validate_tests(
            project, agent_id, "superados")["data"]["huella_borrador"]
        creado = cx.api_post(project, contexto.region, f"{contexto.parent}/intents",
                             {"displayName": f"{etiqueta}_huella"})
        if creado.status_code not in (200, 201):
            return False, f"no se pudo mover el borrador: {creado.status_code}"
        nombre = creado.json()["name"]
        try:
            despues = pipeline.step_4_validate_tests(
                project, agent_id, "superados")["data"]["huella_borrador"]
            return antes != despues, "la huella no cambió al mover el borrador"
        finally:
            cx.api_delete(project, contexto.region, nombre)

    def publicar_protege_lo_que_dice_proteger():
        """Un cambio aplicado al borrador NO puede llegar a los usuarios.

        Es la garantía central del sistema —para eso existe el Paso 5— y hasta
        el 2026-08-09 no la comprobaba nadie: el pipeline declaraba que solo
        `agent_config` y `generator` se ven al instante, y del resto lo daba por
        supuesto.

        Se mide preguntándole al agente por su entorno de producción y por su
        borrador, con una frase que no empareja en ninguno de los dos. Después
        se añade esa frase a un intent del borrador: el borrador tiene que
        empezar a emparejarla —si no, el cambio no surtió efecto y la prueba no
        observa nada— y producción tiene que seguir sin verla.

        El control no es decorativo: el primer intento usó una frase que el
        agente ya emparejaba con todo, así que el «después» no observaba ningún
        cambio y el resultado parecía concluyente sin serlo.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        entornos = list(inventario.get("environment", {}).values())
        intents = list(inventario.get("intent", {}).values())
        if not entornos or not intents:
            return True, "(el agente no tiene entorno o no tiene intents)"
        entorno = entornos[0]

        def empareja(base, texto):
            respuesta = cx.api_post(
                project, contexto.region,
                f"{base}/sessions/{uuid.uuid4().hex[:12]}:detectIntent",
                {"queryInput": {"text": {"text": texto}, "languageCode": "es"}},
            )
            if respuesta.status_code != 200:
                return None
            resultado = respuesta.json().get("queryResult", {})
            return (resultado.get("intent") or {}).get("displayName")

        # Una frase que no empareje **hoy**, ni en producción ni en el borrador.
        frase = next(
            (f for f in (f"xkcd qwerty zzz {run_id}", "qqq zzz xyzzy", "bcdfg hjklm")
             if not empareja(entorno["name"], f) and not empareja(contexto.parent, f)),
            None,
        )
        if frase is None:
            return True, ("(este agente empareja cualquier frase: sin una que no "
                          "empareje, el cambio no se puede observar)")

        intent = intents[0]
        original = {k: v for k, v in intent.items()
                    if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
        cuerpo = dict(original)
        cuerpo["trainingPhrases"] = list(cuerpo.get("trainingPhrases", [])) + [
            {"parts": [{"text": frase}], "repeatCount": 1}]
        if cx.api_patch(project, contexto.region, intent["name"],
                        cuerpo).status_code not in (200, 201):
            return False, "no se pudo cambiar el intent del borrador"

        try:
            # El entrenamiento del borrador tarda: se espera a que reaccione,
            # que es el control. Sin él, un "producción no lo ve" no dice nada.
            for _ in range(6):
                time.sleep(10)
                if empareja(contexto.parent, frase):
                    break
            else:
                return True, ("(el borrador no reaccionó al cambio en 60s: sin "
                              "control no se puede concluir nada)")
            en_produccion = empareja(entorno["name"], frase)
            return en_produccion is None, (
                f"el cambio llegó a producción sin publicar — empareja con "
                f"«{en_produccion}»")
        finally:
            cx.api_patch(project, contexto.region, intent["name"], original)

    runner.check(3, "Publicar protege lo que dice proteger: un cambio aplicado "
                    "al borrador no lo ven los usuarios hasta el Paso 5",
                 publicar_protege_lo_que_dice_proteger)

    runner.check(3, "La huella del borrador cambia cuando el borrador cambia — "
                    "sin eso, el aviso de 'draft movido' no avisa de nada",
                 declarar_tests_da_una_huella_que_cambia)

    def borrar_versiones_respeta_las_que_sirve_un_entorno():
        listado = pipeline.manage_versions(project, agent_id, "list")["data"]
        en_uso = [v["name"] for v in listado["versiones"] if v["en_uso"]]
        if not en_uso:
            return True, "(ninguna versión está en uso)"
        resultado = pipeline.manage_versions(project, agent_id, "delete",
                                             version_names=en_uso)["data"]
        sigue = pipeline.manage_versions(project, agent_id, "list")["data"]
        nombres = {v["name"] for v in sigue["versiones"]}
        return (not resultado["borradas"] and set(en_uso) <= nombres), (
            f"borró {resultado['borradas']} de las que sirve un entorno"
        )

    runner.check(3, "Borrar versiones se niega con las que un entorno está "
                    "sirviendo, y las deja intactas",
                 borrar_versiones_respeta_las_que_sirve_un_entorno)

    def borrar_una_version_libre_funciona():
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flows = list(inventario.get("flow", {}).values())
        if not flows:
            return True, "(sin flows)"
        creada = cx.api_post(project, contexto.region, f"{flows[0]['name']}/versions",
                             {"displayName": f"{etiqueta}_v"})
        if creada.status_code not in (200, 201):
            return False, f"no se pudo crear la versión: {creada.status_code}"
        nombre = cx.resolve_operation(project, contexto.region, creada)["name"]
        resultado = pipeline.manage_versions(project, agent_id, "delete",
                                             version_names=[nombre])["data"]
        desaparecio = cx.api_get(project, contexto.region, nombre).status_code == 404
        return nombre in resultado["borradas"] and desaparecio, (
            "la versión no se borró de verdad"
        )

    runner.check(3, "Borrar una versión libre funciona, y el borrado se confirma "
                    "leyendo",
                 borrar_una_version_libre_funciona)

    def publicar_hace_tres_cosas_en_orden():
        """Fusionar, crear la versión y apuntar producción — en ese orden.

        Si se promoviera antes de fusionar y el merge fallara, producción
        estaría sirviendo algo cuyo código no está en la rama principal.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        produccion = [e for e in inventario.get("environment", {}).values()
                      if e.get("displayName") == "production"]
        if not produccion:
            return False, "el agente desechable no tiene entorno production"
        antes = [c["version"] for c in produccion[0].get("versionConfigs", [])]

        pipeline.step_4_validate_tests(project, agent_id, "superados")
        resultado = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_pub")
        if resultado["status"] != "ok":
            return False, f"{resultado['status']}: {resultado['log'][-1:]}"

        registro = " | ".join(resultado["log"])
        orden_correcto = (registro.index("1/3") < registro.index("2/3")
                          < registro.index("3/3"))
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        despues = [c["version"] for c in
                   [e for e in inventario["environment"].values()
                    if e.get("displayName") == "production"][0]
                   .get("versionConfigs", [])]
        return orden_correcto and resultado["data"]["publicado"], (
            f"orden={orden_correcto} antes={len(antes)} después={len(despues)}"
        )

    runner.check(3, "Publicar hace tres cosas y en orden: fusionar, versionar y "
                    "apuntar producción",
                 publicar_hace_tres_cosas_en_orden)

    def publicar_solo_versiona_lo_que_difiere():
        """H4: el tiempo del paso tiene que ser proporcional al cambio, no al
        tamaño del agente — y cada deploy no puede quemar un hueco de versión en
        todos los playbooks contra un límite de 20.

        Lo que se cuenta ahora es lo que **difiere de lo que producción sirve**,
        no lo que quedó anotado en Firestore. Es la misma regla, con una fuente
        que no depende de que el cambio lo hiciera el pipeline.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        comparacion = pipeline._contenedores_cambiados(contexto, inventario)
        difieren = len(comparacion["cambiados"])
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        resultado = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_h4")
        if resultado["status"] != "ok":
            return False, resultado["status"]
        creadas = resultado["data"]["versiones_creadas"]
        versionables = sum(len(inventario.get(t, {}))
                           for t in pipeline.CONTENIDO_EN_LA_VERSION)
        return len(creadas) <= difieren, (
            f"{len(creadas)} versiones creadas con {difieren} contenedores que "
            f"difieren y {versionables} versionables en total"
        )

    runner.check(3, "Publicar versiona solo lo que difiere de producción, no el "
                    "agente entero (H4)",
                 publicar_solo_versiona_lo_que_difiere)

    def publicar_dos_veces_es_no_op():
        """3.31 y 3.45 — publicar sin ningún cambio: cero versiones creadas y el
        entorno **idéntico**, no solo parecido.

        Cero no es una optimización: los límites de versiones vivas de CX son
        reales y se agotan. Y el entorno tiene que quedar con la misma lista y
        en el mismo orden, o dos publicaciones seguidas sin cambios estarían
        reescribiendo producción para nada.
        """
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        primera = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_dos_a")
        entorno_tras_la_primera = versiones_fijadas_ahora(contexto)
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        segunda = pipeline.step_5_publish(project, agent_id, f"{etiqueta}_dos_b")
        entorno_tras_la_segunda = versiones_fijadas_ahora(contexto)
        if primera["status"] != "ok" or segunda["status"] != "ok":
            return False, f"{primera['status']} / {segunda['status']}"
        creadas = segunda["data"]["versiones_creadas"]
        igual = entorno_tras_la_primera == entorno_tras_la_segunda
        return not creadas and igual, (
            f"la segunda publicación creó {len(creadas)} versiones sin nada que "
            f"publicar · entorno idéntico={igual}"
        )

    runner.check(3, "Publicar sin ningún cambio: cero versiones creadas y el "
                    "entorno queda idéntico",
                 publicar_dos_veces_es_no_op)

    # ── Los dos recorridos completos ─────────────────────────────────────────
    #
    # Son la razón de ser del cambio: un cambio subido desde el repositorio y un
    # cambio hecho a mano en la consola de CX tienen que llegar **los dos** a
    # producción. Ninguno se da por bueno leyendo el log del paso: siempre
    # releyendo de CX qué versión fija el entorno y qué guarda esa versión.

    def _publicar(sufijo):
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        return pipeline.step_5_publish(project, agent_id, f"{etiqueta}_{sufijo}")

    def _lo_que_produccion_sirve(nombre_contenedor):
        """La versión que el entorno fija para un contenedor y su contenido.

        Releído de CX, nunca de la respuesta del paso: el log dice lo que el
        paso creyó hacer, y lo que se quiere demostrar es lo que quedó.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fijada = pipeline._versiones_fijadas(inventario).get(nombre_contenedor)
        if not fijada:
            return None, None
        version = inventario.get("version", {}).get(
            pipeline._clave_de_version({"name": fijada}))
        return fijada, version

    def de_github_a_produccion():
        """3.1 — commit en la rama → Paso 3 → borrador → Paso 5 → producción.

        Se confirma en los dos saltos: que el playbook está en el borrador con
        lo que se subió, y que la versión que el entorno fija guarda eso mismo.
        """
        nombre = f"{etiqueta}_gh"
        objetivo = f"objetivo desde el repositorio {run_id}"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        documento = {
            "metadata": {"tipo": "playbook", "padre": None, "cx_id": None,
                         "agente": agent_id},
            "displayName": nombre, "goal": objetivo, "playbookType": "ROUTINE",
            "instruction": {"steps": [{"text": "haz algo"}]},
        }
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: yaml.safe_dump(documento, allow_unicode=True, sort_keys=False)},
            f"test: playbook nuevo desde el repositorio ({etiqueta})")

        if pipeline.step_3_apply_to_cx(project, agent_id)["status"] != "ok":
            return False, "el Paso 3 falló"

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        creado = next((p for p in inventario["playbook"].values()
                       if p.get("displayName") == nombre), None)
        if creado is None:
            return False, "el playbook no llegó al borrador de CX"
        if creado.get("goal") != objetivo:
            return False, f"el borrador dice goal={creado.get('goal')!r}"

        resultado = _publicar("gh")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"

        fijada, version = _lo_que_produccion_sirve(creado["name"])
        if not fijada:
            return False, "producción no fija ninguna versión de ese playbook"
        publicado = (version or {}).get("playbook", {}).get("goal")
        return publicado == objetivo, (
            f"producción fija {fijada.rsplit('/', 2)[-2:]} y esa versión guarda "
            f"goal={publicado!r}, no {objetivo!r}")

    runner.check(3, "Recorrido completo GitHub → borrador → producción: lo que "
                    "se subió es lo que produce sirve, releído de CX",
                 de_github_a_produccion)

    def de_la_consola_de_cx_a_produccion():
        """3.2 — **la prueba que justifica el encargo entero.**

        Se edita un playbook directamente en CX, sin tocar el repositorio y sin
        pasar por el Paso 3, y se publica. Con el mecanismo anterior esto no
        creaba ninguna versión y el paso reportaba éxito igualmente: nadie
        había anotado nada en Firestore, así que la lista salía vacía y el
        cambio se quedaba en el borrador para siempre.
        """
        nombre = f"{etiqueta}_consola"
        # Punto de partida: existe y está publicado tal cual.
        contenedor_de_pruebas(contexto, "playbook", nombre, "estado inicial")
        if _publicar("consola_base")["status"] != "ok":
            return False, "no se pudo dejar el punto de partida publicado"
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        playbook = next(p for p in inventario["playbook"].values()
                        if p.get("displayName") == nombre)
        fijada_antes, _ = _lo_que_produccion_sirve(playbook["name"])
        if not fijada_antes:
            return False, "el punto de partida no quedó publicado"

        # El cambio: solo en CX. Ni commit, ni Paso 2, ni Paso 3.
        objetivo = f"editado a mano en la consola {run_id}"
        editado = contenedor_de_pruebas(contexto, "playbook", nombre, objetivo)
        esperado = editado.get("goal")

        with ContadorHttp() as contador:
            resultado = _publicar("consola")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        # Ni el Paso 2 ni el Paso 3 han corrido: no hay commit por medio.
        if any(c[0] == "POST" and c[1].endswith("/playbooks")
               for c in contador.escrituras()):
            return False, "el Paso 5 creó un playbook, que no es lo suyo"

        fijada_despues, version = _lo_que_produccion_sirve(playbook["name"])
        publicado = (version or {}).get("playbook", {}).get("goal")
        if fijada_despues == fijada_antes:
            return False, ("producción sigue fijando la misma versión: el "
                           "cambio hecho en la consola no llegó a publicarse")
        return publicado == esperado, (
            f"producción sirve goal={publicado!r} y en el borrador está "
            f"{esperado!r}")

    runner.check(3, "Recorrido completo consola de CX → producción: un cambio "
                    "que el pipeline no hizo también se publica",
                 de_la_consola_de_cx_a_produccion)

    def los_dos_origenes_en_la_misma_publicacion():
        """3.4 — uno cambiado desde el repositorio y otro desde la consola, en
        un solo Paso 5. Los dos tienen que llegar."""
        desde_cx = f"{etiqueta}_mix_cx"
        desde_repo = f"{etiqueta}_mix_repo"
        ruta = f"definitions/playbooks/{desde_repo}.yaml"

        # Punto de partida publicado para los dos.
        contenedor_de_pruebas(contexto, "playbook", desde_cx, "mix inicial")
        documento = {
            "metadata": {"tipo": "playbook", "padre": None, "cx_id": None,
                         "agente": agent_id},
            "displayName": desde_repo, "goal": "mix inicial",
            "playbookType": "ROUTINE",
            "instruction": {"steps": [{"text": "haz algo"}]},
        }
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: yaml.safe_dump(documento, allow_unicode=True, sort_keys=False)},
            f"test: base del mix ({etiqueta})")
        pipeline.step_3_apply_to_cx(project, agent_id)
        if _publicar("mix_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida"

        # Un cambio por cada vía, sin publicar entre medias.
        objetivo_cx = f"mix editado en la consola {run_id}"
        contenedor_de_pruebas(contexto, "playbook", desde_cx, objetivo_cx)

        archivos = contexto.gh.read_repo_files(
            contexto.gh.branch_head(contexto.rama))
        actualizado = yaml.safe_load(archivos[ruta])
        actualizado["goal"] = f"mix editado en el repositorio {run_id}"
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: yaml.safe_dump(actualizado, allow_unicode=True, sort_keys=False)},
            f"test: cambio del mix por repositorio ({etiqueta})")
        pipeline.step_3_apply_to_cx(project, agent_id)

        if _publicar("mix")["status"] != "ok":
            return False, "el Paso 5 falló"

        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fijadas = pipeline._versiones_fijadas(inventario)
        problemas = []
        for nombre, esperado in ((desde_cx, f"objetivo {objetivo_cx}"),
                                 (desde_repo, actualizado["goal"])):
            playbook = next((p for p in inventario["playbook"].values()
                             if p.get("displayName") == nombre), None)
            if playbook is None:
                problemas.append(f"{nombre} no está en el borrador")
                continue
            fijada = fijadas.get(playbook["name"])
            version = inventario.get("version", {}).get(
                pipeline._clave_de_version({"name": fijada or ""}))
            publicado = (version or {}).get("playbook", {}).get("goal")
            if publicado != esperado:
                problemas.append(
                    f"{nombre}: producción sirve {publicado!r} y no {esperado!r}")
        return not problemas, " · ".join(problemas)

    runner.check(3, "Los dos orígenes en la misma publicación: el cambio del "
                    "repositorio y el de la consola llegan los dos",
                 los_dos_origenes_en_la_misma_publicacion)

    def uno_de_tres_versiona_uno():
        """3.32 y 4.4 — con tres playbooks y uno modificado se crea versión de
        ese y de ninguno más, y los otros dos punteros no se mueven.

        Es la regla del mínimo consumo de versiones medida donde se rompería:
        versionar los tres quemaría dos huecos para nada y publicaría trabajo
        de contenedores que nadie quería publicar.
        """
        nombres = [f"{etiqueta}_tres_{i}" for i in range(3)]
        for nombre in nombres:
            contenedor_de_pruebas(contexto, "playbook", nombre, "base de los tres")
        if _publicar("tres_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida"
        antes = versiones_fijadas_ahora(contexto)

        contenedor_de_pruebas(contexto, "playbook", nombres[1],
                              f"solo este cambia {run_id}")
        resultado = _publicar("tres")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        despues = versiones_fijadas_ahora(contexto)

        creadas = resultado["data"]["versiones_creadas"]
        movidos = [c for c in despues if antes.get(c) != despues.get(c)]
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        el_cambiado = next(p["name"] for p in inventario["playbook"].values()
                           if p.get("displayName") == nombres[1])
        return (len(creadas) == 1 and movidos == [el_cambiado]), (
            f"{len(creadas)} versiones creadas y {len(movidos)} punteros "
            f"movidos: {[m.rsplit('/', 1)[-1] for m in movidos]}")

    runner.check(3, "Con tres playbooks y uno modificado se versiona ese y solo "
                    "ese; los otros dos punteros no se mueven",
                 uno_de_tres_versiona_uno)

    def se_publica_contra_la_fijada_no_contra_la_ultima():
        """3.41 — el caso 0.12 contra CX real.

        Se crea una versión a mano y no se publica —lo que deja el Paso 5 si
        muere entre crear y apuntar, o lo que hace alguien desde la consola—, y
        después se cambia el borrador. Si la comparación cogiera «la última
        versión creada», concluiría que no hay nada que hacer y el cambio no
        llegaría nunca a producción.
        """
        nombre = f"{etiqueta}_fijada"
        contenedor_de_pruebas(contexto, "playbook", nombre, "v3")
        if _publicar("fijada_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida"
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        playbook = next(p for p in inventario["playbook"].values()
                        if p.get("displayName") == nombre)
        fijada_antes, _ = _lo_que_produccion_sirve(playbook["name"])

        # Una versión más nueva que nadie publica. A partir de aquí, «la última
        # creada» y «la que el entorno fija» dejan de ser la misma.
        suelta = cx.api_post(project, contexto.region,
                             f"{playbook['name']}/versions",
                             {"description": f"{PREFIJO}_{run_id}_suelta"})
        if suelta.status_code not in (200, 201):
            return False, f"no se pudo crear la versión suelta: {suelta.status_code}"
        creada = cx.resolve_operation(project, contexto.region, suelta)["name"]

        objetivo = f"cambio posterior a la versión suelta {run_id}"
        contenedor_de_pruebas(contexto, "playbook", nombre, objetivo)

        resultado = _publicar("fijada")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        fijada_despues, version = _lo_que_produccion_sirve(playbook["name"])
        publicado = (version or {}).get("playbook", {}).get("goal")
        if fijada_despues == fijada_antes:
            return False, ("producción sigue fijando la versión de antes: se "
                           "comparó contra la última creada y el cambio se "
                           "quedó en el borrador")
        return publicado == f"objetivo {objetivo}", (
            f"la versión suelta era {creada.rsplit('/', 1)[-1]} · producción "
            f"fija ahora {fijada_despues.rsplit('/', 1)[-1]} con "
            f"goal={publicado!r}")

    runner.check(3, "Se publica comparando contra la versión que el entorno "
                    "fija, no contra la última creada",
                 se_publica_contra_la_fijada_no_contra_la_ultima)

    def lo_borrado_sale_del_entorno():
        """3.17 y 3.18 — un contenedor publicado que desaparece del borrador
        sale de producción, y no estrena ninguna versión suya.

        Hasta ahora el entorno solo sabía añadir o mantener: un puntero a algo
        borrado sobrevivía a cualquier número de publicaciones y producción
        seguía sirviendo una versión que todavía lo contenía, para siempre.
        """
        nombre = f"{etiqueta}_borrable"
        creado = contenedor_de_pruebas(contexto, "playbook", nombre, "va a morir")
        if _publicar("borrable_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida"
        if creado["name"] not in versiones_fijadas_ahora(contexto):
            return False, "el punto de partida no llegó a producción"

        # Se borra en la consola de CX: ni Paso 2 ni Paso 3 intervienen.
        respuesta = cx.api_delete(project, contexto.region, creado["name"])
        if respuesta.status_code not in (200, 204):
            return False, f"no se pudo borrar: {respuesta.status_code}"

        # El Paso 1 lo cuenta antes de que pase.
        avisados = pipeline.step_1_inventory(
            project, agent_id)["data"]["comparacion_produccion"]["borrados"]
        avisado = any(b["name"] == creado["name"] for b in avisados)

        resultado = _publicar("borrable")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        fijadas = versiones_fijadas_ahora(contexto)
        suyas = [v for v in resultado["data"]["versiones_creadas"]
                 if v.startswith(f"{creado['name']}/")]
        return (creado["name"] not in fijadas and not suyas and avisado), (
            f"avisado en el Paso 1={avisado} · sigue fijado="
            f"{creado['name'] in fijadas} · versiones nuevas suyas={len(suyas)}")

    runner.check(3, "Lo borrado del borrador sale del entorno de producción, y "
                    "no estrena ninguna versión suya",
                 lo_borrado_sale_del_entorno)

    def retirar_un_flow_alcanzable_se_explica():
        """3.34 — CX exige que el entorno fije una versión de todos los flows
        alcanzables desde el de inicio. Quitar uno que todavía se alcanza lo
        rechaza, y el paso tiene que decirlo con palabras, no propagar el error
        de la API.

        Se provoca sin borrar nada: se le pide a `_apuntar_entorno` que quite el
        puntero del flow de inicio declarándolo borrado. Borrar de verdad el
        flow de inicio no es posible —CX no deja— así que este es el único
        camino que llega al rechazo.
        """
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        produccion = pipeline._buscar_entorno(contexto, inventario,
                                              pipeline.ENTORNO_PRODUCCION)
        fijadas = pipeline._versiones_fijadas(inventario)
        de_flow = {c: v for c, v in fijadas.items() if "/flows/" in c}
        if not de_flow:
            return True, "(producción no fija ninguna versión de flow)"
        contenedor = next(iter(de_flow))
        sin_el_flow = [v for c, v in fijadas.items() if c != contenedor]
        borrados = [{"tipo": "flow", "cx_id": contenedor.rsplit("/", 1)[-1],
                     "name": contenedor, "display_name": "Default Start Flow"}]
        try:
            pipeline._apuntar_entorno(contexto, produccion, sin_el_flow,
                                      borrados=borrados)
        except pipeline.PipelineError as error:
            mensaje = str(error)
            claro = ("flow" in mensaje and "alcanz" in mensaje
                     and "Default Start Flow" in mensaje)
            return claro, f"el mensaje no se entiende: {mensaje[:200]}"
        finally:
            # Se deja como estaba pase lo que pase.
            pipeline._apuntar_entorno(contexto, produccion,
                                      sorted(fijadas.values()))
        return True, ("CX aceptó quitar el flow del entorno: la regla de la "
                      "cadena completa no se aplicó en este caso")

    runner.check(3, "Retirar de producción un flow que todavía se alcanza se "
                    "explica con palabras, no con el error de la API",
                 retirar_un_flow_alcanzable_se_explica)

    def un_example_versiona_su_playbook():
        """3.19 y 3.20 — un example no tiene versión propia: la tiene su
        playbook. Cambiarlo tiene que sacar el playbook como cambiado y crear
        una versión **del playbook**, no del example."""
        nombre = f"{etiqueta}_ex_pb"
        playbook = contenedor_de_pruebas(contexto, "playbook", nombre, "con examples")
        if _publicar("ex_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida"
        fijada_antes, _ = _lo_que_produccion_sirve(playbook["name"])

        respuesta = cx.api_post(
            project, contexto.region, f"{playbook['name']}/examples",
            {**CUERPO_MINIMO["example"], "displayName": f"{etiqueta}_ex"})
        if respuesta.status_code not in (200, 201):
            return False, f"no se pudo crear el example: {respuesta.status_code}"

        resultado = _publicar("ex")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        creadas = resultado["data"]["versiones_creadas"]
        del_playbook = [v for v in creadas if v.startswith(f"{playbook['name']}/")]
        fijada_despues, version = _lo_que_produccion_sirve(playbook["name"])
        ejemplos = len((version or {}).get("examples") or [])
        return (len(del_playbook) == 1 and fijada_despues != fijada_antes
                and ejemplos == 1), (
            f"versiones del playbook={len(del_playbook)} · el entorno se movió="
            f"{fijada_despues != fijada_antes} · examples dentro de la versión "
            f"publicada={ejemplos}")

    runner.check(3, "Añadir un example crea versión de su playbook —no del "
                    "example— y producción la sirve con el example dentro",
                 un_example_versiona_su_playbook)

    def los_tipos_sin_version_no_generan_ninguna():
        """3.28 y 3.29 — generator y agent_config no los versiona CX. Un cambio
        en ellos no puede crear versión ninguna, y el Paso 3 ya avisa de que los
        usuarios lo ven en cuanto se aplica."""
        respuesta = cx.api_post(
            project, contexto.region, f"{contexto.parent}/generators",
            {**CUERPO_MINIMO["generator"], "displayName": f"{etiqueta}_gen"})
        if respuesta.status_code not in (200, 201):
            return False, f"no se pudo crear el generator: {respuesta.status_code}"
        generador = respuesta.json()["name"]

        inventario, _, _ = pipeline.inventariar_cx(contexto)
        comparacion = pipeline._contenedores_cambiados(contexto, inventario)
        tipos = {f["tipo"] for lista in comparacion.values() for f in lista}
        resultado = _publicar("sin_version")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        de_generadores = [v for v in resultado["data"]["versiones_creadas"]
                          if "/generators/" in v]
        cx.api_delete(project, contexto.region, generador)
        return (not de_generadores
                and not tipos & set(pipeline.TIPOS_SIN_VERSION)), (
            f"versiones de generator creadas={len(de_generadores)} · tipos en "
            f"la comparación={sorted(tipos)}")

    runner.check(3, "Los tipos que CX no versiona no generan ninguna versión ni "
                    "aparecen en la comparación",
                 los_tipos_sin_version_no_generan_ninguna)

    def el_viaje_de_ida_y_vuelta_no_cambia_nada():
        """3.3 — CX → repositorio → CX.

        Se crea un resource en la consola, el Paso 2 lo trae con su cabecera, y
        el Paso 3 lo vuelve a aplicar. Si el viaje fuera fiel, el segundo tramo
        no tiene nada que hacer: ni una operación. Cualquier campo que se
        pierda o se invente por el camino sale aquí como un PATCH eterno.
        """
        nombre = f"{etiqueta}_vuelta"
        respuesta = cx.api_post(
            project, contexto.region, f"{contexto.parent}/intents",
            {**CUERPO_MINIMO["intent"], "displayName": nombre})
        if respuesta.status_code not in (200, 201):
            return False, f"no se pudo crear en CX: {respuesta.status_code}"
        cx_id = pipeline._cx_id_de(respuesta.json())

        traido = pipeline.step_2_pull_to_repo(
            project, agent_id, [{"tipo": "intent", "cx_id": cx_id}])["data"]
        filas = [t for t in traido["traidos"] if t["cx_id"] == cx_id]
        if not filas:
            return False, "el Paso 2 no lo trajo al repositorio"

        archivos = contexto.gh.read_repo_files(
            contexto.gh.branch_head(contexto.rama))
        documento = yaml.safe_load(archivos[filas[0]["ruta"]])
        cabecera = documento.get("metadata", {})
        problemas = []
        if cabecera.get("tipo") != "intent":
            problemas.append(f"tipo={cabecera.get('tipo')!r}")
        if cabecera.get("cx_id") != cx_id:
            problemas.append(f"cx_id={cabecera.get('cx_id')!r}")
        if cabecera.get("agente") != agent_id:
            problemas.append(f"agente={cabecera.get('agente')!r}")
        if "padre" not in cabecera:
            problemas.append("sin campo padre")
        if problemas:
            return False, "cabecera incompleta: " + " · ".join(problemas)

        plan = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        sobre_el = [o for o in plan["operaciones"] if o["cx_id"] == cx_id]
        return not sobre_el, (
            f"el viaje de vuelta propone {[o['operacion'] for o in sobre_el]} "
            f"sobre un resource que acaba de traerse tal cual")

    runner.check(3, "El viaje CX → repositorio → CX no cambia nada: lo traído "
                    "vuelve a aplicarse sin generar ninguna operación",
                 el_viaje_de_ida_y_vuelta_no_cambia_nada)

    def cada_cambio_se_versiona_donde_le_toca():
        """Matriz por tipo: qué contenedor sale como cambiado según qué se toque.

        Los hijos no tienen versión propia — la tiene su contenedor. Lo que se
        comprueba aquí es el **destino** de cada cambio, que es donde se juega
        el límite de cuota: versionar el contenedor equivocado publica una foto
        que no incluye el cambio y quema un hueco para nada.

        Se afirma sobre la comparación, que es lo que decide, y no publicando
        cada caso: que la comparación se traduce en publicación ya lo prueban
        los recorridos completos, y publicar catorce veces gastaría catorce
        versiones para demostrar lo mismo.

        **Hallazgo que corrige el encargo:** un webhook o un entity type que
        ningún flow referencia **no entra en el contenido de ninguna versión**.
        Verificado contra la API creándolos sueltos y viéndolos aparecer solo
        después de referenciarlos desde el flow. Sueltos se comportan como los
        tipos sin versión: los usuarios los ven al aplicarlos.
        """
        flow = contenedor_de_pruebas(contexto, "flow", f"{etiqueta}_matriz_flow",
                                     "base de la matriz")
        tool = contenedor_de_pruebas(contexto, "tool", f"{etiqueta}_matriz_tool",
                                     "base de la matriz")
        if _publicar("matriz_base")["status"] != "ok":
            return False, "no se pudo publicar el punto de partida de la matriz"

        def cambiados_ahora():
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            return {c["name"] for c in
                    pipeline._contenedores_cambiados(contexto, inventario)["cambiados"]}

        if cambiados_ahora():
            return False, "el punto de partida ya difiere: la matriz no mide nada"

        casos, fallos = [], []

        def probar(nombre, hacer, esperado, deshacer):
            creado = hacer()
            try:
                salieron = cambiados_ahora()
                casos.append(f"{nombre}→{len(salieron)}")
                if salieron != esperado:
                    fallos.append(
                        f"{nombre}: salió {sorted(n.rsplit('/', 2)[-2] for n in salieron)} "
                        f"y se esperaba {sorted(n.rsplit('/', 2)[-2] for n in esperado)}")
            finally:
                deshacer(creado)

        def borrar(item):
            if item is not None:
                cx.api_delete(project, contexto.region, item["name"])

        # page → versión de su flow
        probar("page",
               lambda: cx.api_post(project, contexto.region, f"{flow['name']}/pages",
                                   {"displayName": f"{etiqueta}_m_page"}).json(),
               {flow["name"]}, borrar)

        # transition route group → versión de su flow
        probar("transition_route_group",
               lambda: cx.api_post(
                   project, contexto.region,
                   f"{flow['name']}/transitionRouteGroups",
                   {"displayName": f"{etiqueta}_m_trg", "transitionRoutes": []}).json(),
               {flow["name"]}, borrar)

        # tool → versión suya
        def tocar_tool():
            return contenedor_de_pruebas(contexto, "tool",
                                         f"{etiqueta}_matriz_tool",
                                         f"tool cambiado {run_id}")
        probar("tool", tocar_tool, {tool["name"]},
               lambda _: contenedor_de_pruebas(contexto, "tool",
                                               f"{etiqueta}_matriz_tool",
                                               "base de la matriz"))

        # flow → versión suya
        def tocar_flow():
            return contenedor_de_pruebas(contexto, "flow",
                                         f"{etiqueta}_matriz_flow",
                                         f"flow cambiado {run_id}")
        probar("flow", tocar_flow, {flow["name"]},
               lambda _: contenedor_de_pruebas(contexto, "flow",
                                               f"{etiqueta}_matriz_flow",
                                               "base de la matriz"))

        # webhook y entity_type sueltos → ningún contenedor
        probar("webhook_suelto",
               lambda: cx.api_post(project, contexto.region,
                                   f"{contexto.parent}/webhooks",
                                   {**CUERPO_MINIMO["webhook"],
                                    "displayName": f"{etiqueta}_m_wh"}).json(),
               set(), borrar)
        probar("entity_type_suelto",
               lambda: cx.api_post(project, contexto.region,
                                   f"{contexto.parent}/entityTypes",
                                   {**CUERPO_MINIMO["entity_type"],
                                    "displayName": f"{etiqueta}_m_et"}).json(),
               set(), borrar)

        return not fallos, f"{' · '.join(casos)} || " + " · ".join(fallos)

    runner.check(3, "Cada cambio se versiona donde le toca: page y transition "
                    "route group en su flow, tool y flow en sí mismos, y lo que "
                    "ningún flow referencia en ninguno",
                 cada_cambio_se_versiona_donde_le_toca)

    def el_entorno_queda_legible_y_coherente():
        """3.40 — todos los punteros del entorno resuelven a versiones que
        existen. Un puntero roto no da error hasta que alguien lee producción,
        y entonces ya no se sabe desde cuándo estaba mal."""
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fijadas = pipeline._versiones_fijadas(inventario)
        rotos = []
        for contenedor, version in sorted(fijadas.items()):
            if cx.api_get(project, contexto.region, version).status_code != 200:
                rotos.append(version.rsplit("/agents/", 1)[-1])
        return not rotos, f"{len(rotos)} punteros rotos: {rotos[:3]}"

    runner.check(3, "El entorno de producción queda legible y coherente: todos "
                    "sus punteros resuelven a versiones que existen",
                 el_entorno_queda_legible_y_coherente)

    def el_gate_del_paso_4_aborta_si_no_se_declaro_superados():
        """3.36 — anti-regresión del gate que protege a los usuarios.

        Cambiar de dónde sale la lista de lo que se versiona no puede aflojar
        el gate: si los últimos tests declarados fueron `fallidos`, publicar
        tiene que abortar **antes de fusionar** y sin tocar nada, por mucho que
        haya contenedores que difieran de producción.

        Se comprueba releyendo el entorno y las dos ramas, no el status: un
        paso puede decir «aborted» después de haber escrito.
        """
        antes_entorno = versiones_fijadas_ahora(contexto)
        antes_ramas = (contexto.gh.branch_head(contexto.rama),
                       contexto.gh.branch_head(contexto.rama_principal))

        pipeline.step_4_validate_tests(project, agent_id, "fallidos")
        resultado = pipeline.step_5_publish(project, agent_id,
                                            f"{etiqueta}_gate4")
        despues_entorno = versiones_fijadas_ahora(contexto)
        despues_ramas = (contexto.gh.branch_head(contexto.rama),
                         contexto.gh.branch_head(contexto.rama_principal))
        # Se deja el gate como estaba para no romper los checks siguientes.
        pipeline.step_4_validate_tests(project, agent_id, "superados")

        return (resultado["status"] == "aborted"
                and not resultado["data"]["fusionado"]
                and not resultado["data"]["publicado"]
                and antes_entorno == despues_entorno
                and antes_ramas == despues_ramas), (
            f"status={resultado['status']} · fusionado="
            f"{resultado['data'].get('fusionado')} · entorno intacto="
            f"{antes_entorno == despues_entorno} · ramas intactas="
            f"{antes_ramas == despues_ramas}")

    runner.check(3, "El gate del Paso 4 sigue abortando si lo declarado no fue "
                    "'superados', sin fusionar ni tocar producción",
                 el_gate_del_paso_4_aborta_si_no_se_declaro_superados)

    def el_rollback_queda_registrado():
        cliente = store.get_client()
        previas = store.get_previous_versions(cliente, project, agent_id)
        return previas is not None and "version_names" in previas, (
            "no quedó registrado a qué apuntaba producción antes"
        )

    runner.check(3, "Publicar registra a qué versiones apuntaba producción antes "
                    "— es lo único que hace posible el rollback",
                 el_rollback_queda_registrado)

    def publicar_repetido_avisa_del_exceso_y_no_borra_nada():
        """Provoca el caso real: el contenedor supera su límite al publicar.

        El límite real de flow (20) es demasiado alto para forzarlo en una
        prueba — de ahí el límite bajado a 3 solo en memoria del proceso, sin
        tocar el archivo. Se publican cuatro cambios reales seguidos, cada uno
        con contenido distinto para que no sean no-ops.

        Publicar **ya no borra nada por su cuenta** (pedido explícito de Jero,
        2026-08-10): el contenedor se queda con las 4 versiones vivas, por
        encima de su límite de 3, y `step_5_publish` se limita a avisarlo en
        `data["poda_pendiente"]` — sin tocar CX. Borrar de verdad sigue siendo
        una acción aparte: se confirma aquí mismo llamando después a
        `manage_versions(action="delete", ...)` con las candidatas que el
        propio aviso señaló, y comprobando que la que producción sirve ahora
        **nunca** está entre ellas.
        """
        limite_original = dict(pipeline.LIMITE_VERSIONES)
        pipeline.LIMITE_VERSIONES["flow"] = 3
        try:
            ultimo_resultado = None
            for i in range(4):
                contexto = pipeline.Contexto(project, agent_id)
                inventario, _, _ = pipeline.inventariar_cx(contexto)
                flow = next(iter(inventario["flow"].values()))
                cuerpo = {k: v for k, v in flow.items()
                         if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
                cuerpo["description"] = f"{PREFIJO}_{run_id}_poda_{i}"
                cx.api_patch(project, contexto.region, flow["name"], cuerpo)
                pipeline.step_4_validate_tests(project, agent_id, "superados")
                r = pipeline.step_5_publish(project, agent_id,
                                           f"{PREFIJO}_{run_id}_poda_{i}")
                if r["status"] != "ok":
                    return False, f"publicación {i} falló: {r['data']}"
                ultimo_resultado = r

            contexto = pipeline.Contexto(project, agent_id)
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            flow = next(iter(inventario["flow"].values()))
            vivas_antes = cx.list_all_pages(project, contexto.region,
                                            f"{flow['name']}/versions", "versions")
            en_uso = {cf["version"]
                     for e in inventario["environment"].values()
                     for cf in e.get("versionConfigs", [])}
            # La versión **de este flow** que algún entorno sirve, no una
            # cualquiera del conjunto. Cogiendo un elemento suelto del set salía
            # casi siempre la de un playbook, y compararla después contra la
            # lista de versiones del flow daba «la versión en uso se borró» sin
            # que se hubiera borrado nada: el fallo aparecía solo cuando el
            # entorno fijaba varios contenedores, así que llevaba latente desde
            # que se escribió.
            servida = next((v for v in sorted(en_uso)
                            if v.startswith(f"{flow['name']}/versions/")), None)

            problemas = []
            if len(vivas_antes) < 4:
                problemas.append(
                    f"solo quedan {len(vivas_antes)} versiones — algo se borró "
                    f"solo, y no debía")

            poda_pendiente = (ultimo_resultado or {}).get("data", {}).get(
                "poda_pendiente") or []
            del_flow = next(
                (c for c in poda_pendiente if c["nombre_padre"] == flow["name"]),
                None)
            if not del_flow:
                problemas.append(
                    "step_5_publish no avisó del exceso de versiones del flow "
                    "en poda_pendiente")
            elif servida and servida in del_flow["candidatas"]:
                problemas.append(
                    "el aviso propone borrar la versión que producción sirve")

            if problemas:
                return False, " · ".join(problemas)

            # Confirmar el borrado de verdad, a mano — el camino que existe
            # para esto desde antes de esta noche, sin cambios.
            borrado = pipeline.manage_versions(
                project, agent_id, "delete",
                version_names=del_flow["candidatas"])["data"]
            vivas_despues = cx.list_all_pages(
                project, contexto.region, f"{flow['name']}/versions", "versions")
            problemas = []
            if len(vivas_despues) > 3:
                problemas.append(
                    f"quedan {len(vivas_despues)} versiones tras confirmar el "
                    f"borrado, el límite era 3")
            if servida and servida not in {v["name"] for v in vivas_despues}:
                problemas.append("la versión en uso se borró al confirmar")
            return not problemas, " · ".join(problemas) or (
                f"{len(borrado['borradas'])} borradas a mano tras el aviso")
        finally:
            pipeline.LIMITE_VERSIONES.clear()
            pipeline.LIMITE_VERSIONES.update(limite_original)

    runner.check(3, "Publicar repetido avisa del exceso de versiones del flow "
                    "sin borrar nada — y confirmarlo a mano sí borra, sin tocar "
                    "nunca la que producción sirve",
                 publicar_repetido_avisa_del_exceso_y_no_borra_nada)

    runner.skip(3, "Repetir los checks de Full Update en una región distinta de "
                   "europe-west1",
                "exige un segundo agente desechable en otra región. El bug de "
                "CLAUDE.md §3.8 solo está verificado en europe-west1 y sigue sin "
                "verificar fuera: con la región autodetectada, el pipeline puede "
                "acabar operando en otra sin que nadie lo haya comprobado")

    # ── Los diez que faltaban ────────────────────────────────────────────────

    def _yaml_de_playbook(nombre, objetivo, cx_id=None, agente=None):
        """El cuerpo mínimo de un playbook, con su cabecera."""
        return yaml.safe_dump(
            {"metadata": {"tipo": "playbook", "padre": None, "cx_id": cx_id,
                          "agente": agente or agent_id},
             "displayName": nombre, "goal": objetivo,
             "playbookType": "ROUTINE",
             "instruction": {"steps": [{"text": "haz algo"}]}},
            allow_unicode=True, sort_keys=False)

    def _cabecera_en_la_rama(ruta, distinto_de=..., intentos=5, espera=0.6):
        """La cabecera `metadata` de un archivo, leída de la rama de trabajo.

        `distinto_de` reintenta la lectura hasta que el `cx_id` deje de ser ese
        valor. Hace falta porque leer una rama recién escrita puede devolver el
        estado anterior —GitHub tarda un instante en publicar la referencia, el
        mismo retardo que obligó a encadenar commits por `base_sha` y a que
        `create_branch` confirme leyendo—. Sin esto, un check que comprueba «el
        id volvió al archivo» justo después de escribirlo falla por la latencia
        y acusa al pipeline de un defecto que no tiene: pasó exactamente eso, y
        reproducirlo aislado demostró que el paso sí lo había guardado.

        Con `distinto_de` sin dar, lee una vez y devuelve lo que haya.
        """
        for intento in range(intentos):
            archivos = contexto.gh.read_repo_files(
                contexto.gh.branch_head(contexto.rama))
            cabecera = ((yaml.safe_load(archivos[ruta]) or {}).get("metadata", {})
                        if ruta in archivos else None)
            if distinto_de is ... or (cabecera or {}).get("cx_id") != distinto_de:
                return cabecera
            if intento < intentos - 1:
                time.sleep(espera * (2 ** intento))
        return cabecera

    def lo_que_el_pipeline_dice_de_produccion_es_lo_que_cx_sirve():
        """Que la foto del pipeline y la realidad de CX sean la misma cosa.

        Todo el Paso 5 descansa en que `_versiones_fijadas` describe lo que los
        usuarios reciben. Si el pipeline leyera producción por un camino que
        divergiera del real, publicaría creyéndose otra cosa —y lo diría con un
        ✓— sin que nada lo delatara.

        Se lee dos veces por vías independientes: la del pipeline, y un LIST
        crudo del entorno que no pasa por ninguna función suya. Y no basta con
        que los punteros coincidan: un puntero puede resolver a una versión que
        existe y cuyo contenedor ya no.
        """
        del_pipeline = versiones_fijadas_ahora(contexto)

        crudo = {}
        for entorno in cx.list_all_pages(
                project, contexto.region,
                f"{contexto.parent}/environments", "environments"):
            if entorno.get("displayName") != pipeline.ENTORNO_PRODUCCION:
                continue
            for config in entorno.get("versionConfigs", []):
                version = config["version"]
                crudo[version.rsplit("/versions/", 1)[0]] = version

        if del_pipeline != crudo:
            return False, (
                f"divergen · el pipeline ve {len(del_pipeline)} punteros y CX "
                f"{len(crudo)} · solo el pipeline: "
                f"{sorted(set(del_pipeline) - set(crudo))[:2]} · solo CX: "
                f"{sorted(set(crudo) - set(del_pipeline))[:2]}")

        for contenedor, version in crudo.items():
            for ruta, que in ((version, "la versión fijada"),
                              (contenedor, "el contenedor de una versión fijada")):
                if cx.api_get(project, contexto.region, ruta).status_code != 200:
                    return False, f"{que} no existe: {ruta.rsplit('/agents/', 1)[-1]}"
        return True, f"{len(crudo)} punteros idénticos por las dos vías"

    runner.check(3, "Lo que el pipeline dice que produce sirve es exactamente lo "
                    "que CX sirve, leído por dos vías independientes",
                 lo_que_el_pipeline_dice_de_produccion_es_lo_que_cx_sirve)

    def el_paso_3_deja_el_cambio_en_el_borrador():
        """Las dos mitades, no solo una.

        Comprobar únicamente que producción no se movió deja pasar un Paso 3
        que no escribió nada en absoluto: «no tocó producción» lo cumple
        también el paso que no hizo nada. La otra mitad —que el cambio **está**
        en el borrador— se comprueba releyendo CX, nunca el resultado del paso.
        """
        nombre = f"{etiqueta}_draft"
        objetivo = f"objetivo que solo puede venir de este check ({run_id})"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        contexto.gh.commit_files(
            contexto.rama, {ruta: _yaml_de_playbook(nombre, objetivo)},
            f"test({PREFIJO}): playbook para comprobar que el Paso 3 llega al borrador")

        antes = versiones_fijadas_ahora(contexto)
        pipeline.step_3_apply_to_cx(project, agent_id)
        despues = versiones_fijadas_ahora(contexto)

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        en_el_borrador = next((p for p in inventario["playbook"].values()
                               if p.get("displayName") == nombre), None)
        problemas = []
        if en_el_borrador is None:
            problemas.append("no está en el borrador de CX tras el Paso 3")
        elif en_el_borrador.get("goal") != objetivo:
            problemas.append(f"está con otro contenido: {en_el_borrador.get('goal')!r}")
        if antes != despues:
            problemas.append("el Paso 3 movió algún puntero de producción")
        return not problemas, " · ".join(problemas)

    runner.check(3, "El Paso 3 deja el cambio en el borrador de verdad, y no "
                    "mueve producción — las dos mitades",
                 el_paso_3_deja_el_cambio_en_el_borrador)

    def el_cx_id_decide_patch_y_su_ausencia_post():
        """Sin id, se crea; con id, se actualiza. Nunca al revés.

        Es lo que separa «actualizar» de «duplicar»: si un archivo con id
        acabara en POST, cada deploy dejaría una copia más en el agente.
        """
        nombre = f"{etiqueta}_verbo"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        contexto.gh.commit_files(
            contexto.rama, {ruta: _yaml_de_playbook(nombre, "sin id todavía")},
            f"test({PREFIJO}): playbook sin cx_id, tiene que salir como POST")

        plan = pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
        sin_id = next((o for o in plan if o["ruta"] == ruta), None)
        if sin_id is None:
            return False, "el plan no propone nada para un archivo sin cx_id"
        if sin_id["operacion"] != "POST":
            return False, f"sin cx_id propone {sin_id['operacion']}, no POST"

        pipeline.step_3_apply_to_cx(project, agent_id, aplicar=[
            {"tipo": "playbook", "ruta": ruta}])
        cabecera = _cabecera_en_la_rama(ruta, distinto_de=None)
        if not (cabecera or {}).get("cx_id"):
            return False, "tras crearlo, el cx_id no volvió al archivo"

        # Ahora que tiene id, cambiarlo tiene que proponer PATCH.
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: _yaml_de_playbook(nombre, "ahora con id y contenido nuevo",
                                     cx_id=cabecera["cx_id"])},
            f"test({PREFIJO}): mismo playbook con cx_id, tiene que salir como PATCH")
        plan = pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]
        con_id = next((o for o in plan if o["ruta"] == ruta), None)
        if con_id is None:
            return False, "con cx_id y contenido distinto, el plan no propone nada"
        return con_id["operacion"] == "PATCH", (
            f"con cx_id propone {con_id['operacion']}, no PATCH")

    runner.check(3, "El cx_id decide el verbo: sin él POST, con él PATCH — "
                    "nunca al revés",
                 el_cx_id_decide_patch_y_su_ausencia_post)

    def un_cx_id_fantasma_se_recrea_y_deja_una_sola_copia():
        """El archivo apunta a un recurso que ya no existe en CX.

        Pasa de verdad: se borra algo en la consola y su YAML se queda con el
        id de un muerto. Un PATCH contra ese id fallaría para siempre; una
        recreación que no actualizara el archivo dejaría una copia nueva en
        cada deploy. Se comprueba lo tercero: se recrea, el id nuevo sustituye
        al viejo, y en CX queda **una sola** copia.
        """
        nombre = f"{etiqueta}_fantasma"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        contexto.gh.commit_files(
            contexto.rama, {ruta: _yaml_de_playbook(nombre, "nace para morir")},
            f"test({PREFIJO}): playbook que se borrará de CX dejando su id huérfano")
        pipeline.step_3_apply_to_cx(project, agent_id, aplicar=[
            {"tipo": "playbook", "ruta": ruta}])

        viejo = (_cabecera_en_la_rama(ruta, distinto_de=None) or {}).get("cx_id")
        if not viejo:
            return False, "no se llegó a crear con id"

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        creado = inventario["playbook"].get(viejo)
        if creado is None:
            return False, "el id guardado no corresponde a nada en CX"
        cx.api_delete(project, contexto.region, creado["name"])
        if cx.api_get(project, contexto.region, creado["name"]).status_code != 404:
            return False, "no se pudo borrar de CX para provocar el fantasma"

        pipeline.step_3_apply_to_cx(project, agent_id, aplicar=[
            {"tipo": "playbook", "cx_id": viejo, "ruta": ruta}])

        nuevo = (_cabecera_en_la_rama(ruta, distinto_de=viejo) or {}).get("cx_id")
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["playbook"])
        copias = [p for p in inventario["playbook"].values()
                  if p.get("displayName") == nombre]
        for copia in copias:
            creados.append(copia["name"])

        problemas = []
        if not nuevo:
            problemas.append("el archivo se quedó sin cx_id")
        elif nuevo == viejo:
            problemas.append(f"el archivo sigue con el id muerto {viejo[:8]}")
        elif nuevo not in inventario["playbook"]:
            problemas.append("el id nuevo del archivo no existe en CX")
        if len(copias) != 1:
            problemas.append(f"quedaron {len(copias)} copias en CX, no una")
        return not problemas, " · ".join(problemas)

    runner.check(3, "Un cx_id fantasma se recrea, el id nuevo sustituye al muerto "
                    "en el archivo, y queda una sola copia en CX",
                 un_cx_id_fantasma_se_recrea_y_deja_una_sola_copia)

    def el_mismo_cx_id_en_otro_archivo_avisa():
        """Un id que aparece hoy en un archivo distinto al de la última vez.

        Es el síntoma de un YAML copiado de otro repositorio sin vaciarle la
        cabecera. Sin el aviso, se aplicaría en silencio sobre el recurso
        equivocado — y el recurso equivocado es uno real.
        """
        nombre = f"{etiqueta}_mudanza"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        contexto.gh.commit_files(
            contexto.rama, {ruta: _yaml_de_playbook(nombre, "vive aquí de momento")},
            f"test({PREFIJO}): playbook que después cambiará de archivo")
        pipeline.step_3_apply_to_cx(project, agent_id, aplicar=[
            {"tipo": "playbook", "ruta": ruta}])
        cx_id = (_cabecera_en_la_rama(ruta, distinto_de=None) or {}).get("cx_id")
        if not cx_id:
            return False, "no se llegó a crear con id"

        otra = f"definitions/playbooks/{nombre}_mudado.yaml"
        contexto.gh.commit_files(
            contexto.rama,
            {ruta: "", otra: _yaml_de_playbook(nombre, "ahora vivo en otro archivo",
                                               cx_id=cx_id)},
            f"test({PREFIJO}): el mismo cx_id aparece en otro archivo")

        avisos = pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["avisos_cambio_archivo"]
        suyo = [a for a in avisos if a.get("cx_id") == cx_id]
        if not suyo:
            return False, ("el cx_id cambió de archivo y no se avisó: se "
                           "aplicaría en silencio sobre el recurso equivocado")
        return suyo[0]["archivo_ahora"] == otra, (
            f"el aviso señala {suyo[0]['archivo_ahora']}, no {otra}")

    runner.check(3, "El mismo cx_id en un archivo distinto al de la última vez "
                    "dispara el aviso",
                 el_mismo_cx_id_en_otro_archivo_avisa)

    def un_yaml_de_otro_agente_no_se_despliega_aqui():
        """La cabecera `agente` es lo que reparte los YAML entre agentes.

        Si no filtrara, un despliegue se llevaría por delante los recursos de
        otro agente del mismo repositorio. Se comprueba con dos archivos: uno
        de otro agente y otro sin campo `agente`. Ninguno puede entrar en el
        plan, y el plan tiene que seguir proponiendo lo que sí es de este.
        """
        ajeno = f"definitions/playbooks/{etiqueta}_ajeno.yaml"
        huerfano = f"definitions/playbooks/{etiqueta}_huerfano.yaml"
        propio = f"definitions/playbooks/{etiqueta}_propio.yaml"
        sin_agente = yaml.safe_dump(
            {"metadata": {"tipo": "playbook", "padre": None, "cx_id": None},
             "displayName": f"{etiqueta}_huerfano", "goal": "sin dueño",
             "playbookType": "ROUTINE",
             "instruction": {"steps": [{"text": "haz algo"}]}},
            allow_unicode=True, sort_keys=False)
        contexto.gh.commit_files(
            contexto.rama,
            {ajeno: _yaml_de_playbook(f"{etiqueta}_ajeno", "de otro agente",
                                      agente="00000000-0000-0000-0000-0000000000ff"),
             huerfano: sin_agente,
             propio: _yaml_de_playbook(f"{etiqueta}_propio", "de este agente")},
            f"test({PREFIJO}): tres playbooks, solo uno es de este agente")

        rutas = {o["ruta"] for o in pipeline.step_3_apply_to_cx(
            project, agent_id, dry_run=True)["data"]["operaciones"]}
        problemas = []
        if ajeno in rutas:
            problemas.append("el YAML de otro agente entró en el plan")
        if huerfano in rutas:
            problemas.append("el YAML sin campo agente entró en el plan")
        if propio not in rutas:
            problemas.append("el YAML de este agente NO entró: el filtro se pasa de largo")
        return not problemas, " · ".join(problemas)

    runner.check(3, "La cabecera agente reparte de verdad: ni el YAML de otro "
                    "agente ni el que no lo declara entran en el plan",
                 un_yaml_de_otro_agente_no_se_despliega_aqui)

    def un_contenedor_sin_publicar_sale_como_cambiado_contra_cx_real():
        """El caso «nunca publicado», contra CX de verdad y no en memoria.

        Tener versiones no es estar al día, y no tenerlas tampoco es un error:
        es lo normal la primera vez. Si un contenedor sin puntero saliera como
        «igual», su primera publicación no ocurriría nunca — el mismo fallo
        silencioso, entrando por otra puerta.
        """
        nombre = f"{etiqueta}_nunca_publicado"
        ruta = f"definitions/playbooks/{nombre}.yaml"
        contexto.gh.commit_files(
            contexto.rama, {ruta: _yaml_de_playbook(nombre, "todavía sin publicar")},
            f"test({PREFIJO}): playbook que nace sin versión ni puntero")
        pipeline.step_3_apply_to_cx(project, agent_id, aplicar=[
            {"tipo": "playbook", "ruta": ruta}])

        inventario, _, _ = pipeline.inventariar_cx(contexto)
        creado = next((p for p in inventario["playbook"].values()
                       if p.get("displayName") == nombre), None)
        if creado is None:
            return False, "no se llegó a crear en CX"
        creados.append(creado["name"])

        comparacion = pipeline._contenedores_cambiados(contexto, inventario)
        suyo = next((c for c in comparacion["cambiados"]
                     if c["name"] == creado["name"]), None)
        if suyo is None:
            return False, ("un contenedor sin puntero en el entorno no sale como "
                           "cambiado: su primera publicación no ocurriría nunca")
        if any(i["name"] == creado["name"] for i in comparacion["iguales"]):
            return False, "sale a la vez como cambiado y como igual"
        # El motivo también, no solo el grupo. Sin esto el check pasaba con el
        # defecto dentro: al romper la rama de «sin puntero», el contenedor
        # caía igualmente en `cambiados` por otro camino —el de «la versión
        # fijada ya no existe»— y el resultado parecía correcto por accidente.
        # Comprobarlo se descubrió inyectando ese defecto a propósito.
        if suyo.get("motivo") != "producción todavía no lo sirve":
            return False, (f"sale como cambiado pero por otro camino: "
                           f"{suyo.get('motivo')!r}")
        return True, f"motivo: {suyo.get('motivo')}"

    runner.check(3, "Un contenedor que existe pero que producción todavía no "
                    "sirve sale como cambiado, contra CX real",
                 un_contenedor_sin_publicar_sale_como_cambiado_contra_cx_real)

    def el_rollback_se_puede_rehacer_de_verdad():
        """Registrar a qué apuntaba producción no sirve si no se puede volver.

        El check hermano comprueba que el dato queda guardado. Este comprueba
        lo que ese dato promete: que con él se devuelve el entorno a donde
        estaba. Se hace el viaje entero —ida y vuelta— y se deja producción
        donde estaba al empezar, confirmándolo por lectura.

        **Exige que el registro sea de esta publicación, no uno cualquiera.**
        El registro vive en Firestore y sobrevive entre corridas: leerlo a
        secas hacía que el check pasara con el guardado roto, apoyándose en lo
        que dejó una corrida anterior. Se descubrió inyectando ese defecto: la
        prueba seguía en verde. Ahora se anota la marca de tiempo previa, se
        publica, y se exige que haya avanzado.
        """
        cliente = store.get_client()
        marca_antes = (store.get_previous_versions(cliente, project, agent_id)
                       or {}).get("guardado_en")

        pipeline.step_4_validate_tests(project, agent_id, "superados")
        publicacion = pipeline.step_5_publish(project, agent_id,
                                              f"{etiqueta}_rollback")
        if publicacion["status"] != "ok":
            return False, f"no se pudo publicar para provocar el registro: {publicacion['status']}"

        al_empezar = versiones_fijadas_ahora(contexto)
        previas = store.get_previous_versions(cliente, project, agent_id) or {}
        if previas.get("guardado_en") == marca_antes:
            return False, ("publicar no actualizó el registro de versiones "
                           "anteriores: el rollback se apoyaría en un dato viejo")
        nombres = previas.get("version_names") or []
        if not nombres:
            return False, "no hay ningún registro de versiones anteriores"

        vivas = [n for n in nombres
                 if cx.api_get(project, contexto.region, n).status_code == 200]
        if not vivas:
            return True, ("las versiones anteriores registradas ya no existen — "
                          "el rollback no es posible y el registro no lo oculta")

        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        entorno = pipeline._buscar_entorno(contexto, inventario,
                                           pipeline.ENTORNO_PRODUCCION)
        pipeline._apuntar_entorno(contexto, entorno, sorted(vivas))
        tras_volver = versiones_fijadas_ahora(contexto)

        # Y se deja como estaba, pase lo que pase con la comprobación.
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["environment"])
        entorno = pipeline._buscar_entorno(contexto, inventario,
                                           pipeline.ENTORNO_PRODUCCION)
        pipeline._apuntar_entorno(contexto, entorno, sorted(al_empezar.values()))
        restaurado = versiones_fijadas_ahora(contexto)

        esperado = {n.rsplit("/versions/", 1)[0]: n for n in sorted(vivas)}
        problemas = []
        if tras_volver != esperado:
            problemas.append("el entorno no quedó en las versiones anteriores")
        if restaurado != al_empezar:
            problemas.append("no se pudo devolver producción a donde estaba")
        return not problemas, " · ".join(problemas)

    runner.check(3, "El rollback se puede rehacer de verdad: con lo registrado "
                    "se devuelve el entorno y se vuelve a dejar como estaba",
                 el_rollback_se_puede_rehacer_de_verdad)

    def publicar_con_el_candado_tomado_no_toca_produccion():
        """Un Paso 3 en curso tiene que impedir que un Paso 5 publique encima.

        Es el caso real de dos pestañas abiertas. Publicar sobre un borrador a
        medio escribir subiría a producción un estado que nadie aprobó. El
        candado es por proyecto, así que se toma tal cual lo tomaría el Paso 3.
        """
        cliente = store.get_client()
        antes = versiones_fijadas_ahora(contexto)
        token = store.acquire_lock(cliente, project, agent_id,
                                   "aplicar en CX (simulado por el validador)")
        try:
            pipeline.step_4_validate_tests(project, agent_id, "superados")
            try:
                resultado = pipeline.step_5_publish(
                    project, agent_id, f"{etiqueta}_candado")
                paro = resultado["status"] not in ("ok",)
                detalle = f"status={resultado['status']}"
            except store.LockBusy as error:
                paro, detalle = True, f"LockBusy: {str(error)[:60]}"
        finally:
            store.release_lock(cliente, project, agent_id, token)

        despues = versiones_fijadas_ahora(contexto)
        if not paro:
            return False, "publicó con el candado de otra operación tomado"
        return antes == despues, (
            f"{detalle} pero producción se movió igualmente")

    runner.check(3, "Con el candado tomado por otra operación, publicar no llega "
                    "a tocar producción",
                 publicar_con_el_candado_tomado_no_toca_produccion)

    # ── Limpieza · va al final, y pase lo que pase antes ─────────────────────

    def limpiar_cx():
        """Desancla y borra todo lo del prefijo — ver `barrer_cx_de_las_pruebas`."""
        return barrer_cx_de_las_pruebas(contexto, project, creados)

    runner.check(3, "Cero residuo en CX: lo creado se borra y el borrado se "
                    "confirma leyendo el resultado",
                 limpiar_cx)

    def limpiar_repositorio():
        """Devuelve la rama de trabajo Y la principal al commit de partida.

        Las dos, no solo la de trabajo: el nivel prueba la publicación, y
        publicar fusiona una en otra. Revertir solo la de trabajo las dejaba
        divergidas —la principal conservaba el merge que la otra ya no tiene— y
        la corrida siguiente no podía fusionar. Las dos son desechables, y el
        guardarraíl del arranque garantiza que la principal no es una rama real.

        Es un force update, y por eso solo se hace contra el repositorio
        desechable. Revertir archivo por archivo dejaría fuera cualquiera que
        el nivel creara sin que este código lo supiera — que es justo lo que
        pasó: el nivel traía al repositorio un resource que luego borraba de
        CX, y el archivo se quedaba reclamando un cx_id que ya no existe.
        """
        fallos = []
        for rama, destino in ((contexto.rama, rama_al_empezar),
                              (contexto.rama_principal, principal_al_empezar)):
            if not destino or contexto.gh.branch_head(rama) == destino:
                continue
            respuesta = requests.patch(
                f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/{rama}",
                headers=contexto.gh._headers(),
                json={"sha": destino, "force": True}, timeout=30,
            )
            if respuesta.status_code != 200:
                fallos.append(f"{rama}: {respuesta.status_code}")
                continue
            # GitHub no devuelve el nuevo valor de la referencia al instante
            # tras forzarla: leerlo de inmediato daba el valor anterior y el
            # check declaraba un residuo que no existía. Se le da margen, pero
            # acotado — si tras varios intentos sigue sin volver, es real.
            for intento in range(5):
                if contexto.gh.branch_head(rama) == destino:
                    break
                time.sleep(1 + intento)
            else:
                fallos.append(f"{rama}: no volvió a {destino[:7]}")
        return not fallos, " · ".join(fallos)

    runner.check(3, "Cero residuo en el repositorio: la rama vuelve al commit en "
                    "el que estaba antes del nivel",
                 limpiar_repositorio)

    # ── El alta de un agente, provocada de verdad ───────────────────────────
    #
    # Es la única escritura del sistema que crea una rama, y hasta aquí solo se
    # había leído el código. Se ejecuta contra el repositorio desechable con un
    # agente inventado —un UUID que no existe en CX— porque lo que se prueba es
    # la resolución del destino, no CX: la región se pasa a mano para no salir
    # a buscar un agente que no está.
    cliente_alta = store.get_client()
    # El agente real: es el único que existe de verdad en CX, y la resolución
    # de la región necesita que exista. Su mapeo se guarda entero aquí y se
    # devuelve en el último check del bloque.
    mapeo_original = dict(store.get_agent_mapping(cliente_alta, project, agent_id))
    rama_del_alta = f"agente/{PREFIJO}_{run_id}"
    # Los inventados no llegan nunca a CX: sirven para las comprobaciones que
    # se resuelven antes de salir a la red, que es donde tienen que estar.
    agentes_inventados = []

    def el_alta_crea_la_rama_que_no_existia():
        """Provoca el caso que fallaba: dar de alta un agente sin rama.

        Antes, el alta solo comprobaba que la rama existiera (`branch_head`), y
        no existe ninguna la primera vez que se da de alta a un agente: fallaba
        con un 404 de git para todo agente nuevo. Se comprueba leyendo el
        efecto —que la referencia existe en GitHub y nace de la principal—, no
        lo que la función dice haber hecho.
        """
        if contexto.gh.branch_head_or_none(rama_del_alta) is not None:
            return False, f"{rama_del_alta} ya existía: la prueba no prueba nada"
        resultado = pipeline.register_agent(
            project, agent_id, rama=rama_del_alta,
            client=cliente_alta, gh=contexto.gh)["data"]
        despues = contexto.gh.branch_head_or_none(rama_del_alta)
        principal = contexto.gh.branch_head(contexto.rama_principal)
        mapeo = store.get_agent_mapping(cliente_alta, project, agent_id)
        problemas = []
        if despues is None:
            problemas.append("la rama no existe en GitHub tras el alta")
        elif despues != principal:
            problemas.append(f"la rama nace en {despues[:7]}, no en la principal")
        if not resultado["rama_creada"]:
            problemas.append("dice que no la creó")
        if resultado["region"] != mapeo_original["region"]:
            problemas.append(f"resolvió la región a {resultado['region']}")
        if mapeo["rama"] != rama_del_alta:
            problemas.append(f"el mapeo guarda {mapeo['rama']}")
        if mapeo["repo"] != contexto.repo:
            problemas.append("el repositorio no lo hereda del proyecto")
        return not problemas, " · ".join(problemas)

    runner.check(3, "Dar de alta un agente crea su rama de trabajo, que nace en "
                    "la principal y queda apuntada en su mapeo",
                 el_alta_crea_la_rama_que_no_existia)

    def dar_de_alta_dos_veces_no_duplica_nada():
        """Repetir el alta no puede mover una rama con trabajo dentro.

        Es el caso real de pulsar el botón dos veces, o de dos pestañas
        abiertas. Se mete un commit en la rama entre las dos pasadas para que
        moverla hacia atrás sea detectable: sin él la rama sigue en la punta de
        la principal y un reset pasaría desapercibido.
        """
        commit = contexto.gh.commit_files(
            rama_del_alta,
            {f"{PREFIJO}_{run_id}_alta.txt": "prueba de idempotencia\n"},
            f"test({PREFIJO}): commit para detectar un alta que mueve la rama",
        )
        resultado = pipeline.register_agent(
            project, agent_id, rama=rama_del_alta,
            client=cliente_alta, gh=contexto.gh)["data"]
        ahora = contexto.gh.branch_head(rama_del_alta)
        problemas = []
        if resultado["rama_creada"]:
            problemas.append("dice haberla creado otra vez")
        if ahora != commit:
            problemas.append(f"movió la rama de {commit[:7]} a {ahora[:7]}")
        return not problemas, " · ".join(problemas)

    runner.check(3, "Dar de alta dos veces no vuelve a crear la rama ni la mueve "
                    "hacia atrás",
                 dar_de_alta_dos_veces_no_duplica_nada)

    def _rechaza_el_alta(sufijo, rama):
        """Intenta un alta que debe rebotar sin escribir nada.

        Devuelve (rebotó, detalle). Comprueba además que el rechazo no deja al
        agente registrado a medias: rebotar y guardar sería peor que aceptar,
        porque el error diría una cosa y el estado otra.
        """
        otro = f"{PREFIJO}-{run_id}-{sufijo}"
        agentes_inventados.append(otro)
        try:
            pipeline.register_agent(project, otro, rama=rama,
                                    client=cliente_alta, gh=contexto.gh)
        except pipeline.PipelineError:
            existe = cliente_alta.collection(store.COL_AGENTES).document(
                store._doc_id(project, otro)).get().exists
            return not existe, "rebotó pero dejó el agente registrado" if existe else ""
        return False, f"aceptó dar de alta con rama {rama}"

    def dos_agentes_no_comparten_rama():
        """La colisión que el nombre propuesto hace fácil sin buscarla.

        Dos agentes con el mismo `displayName` proponen la misma rama, y crear
        una rama es idempotente: sin esta comprobación el segundo se quedaría
        con la del primero en silencio, y publicar uno arrastraría a la
        principal lo que el otro no hubiera publicado.

        Se pide la rama que el agente real tiene ahora mismo, así que el caso
        es el de verdad y no uno construido.
        """
        return _rechaza_el_alta("hermano", rama_del_alta)

    runner.check(3, "Dos agentes no pueden compartir rama de trabajo: publicar "
                    "uno arrastraría lo que el otro no publicó",
                 dos_agentes_no_comparten_rama)

    def la_rama_de_trabajo_no_puede_ser_la_principal():
        """Si lo fuera, el Paso 2 escribiría en la rama que se publica.

        Y el Paso 5 quedaría fusionando una rama consigo misma: un merge que
        siempre responde «nada que fusionar», así que el gate de publicar
        dejaría de significar nada sin que nada avisase.
        """
        return _rechaza_el_alta("principal", contexto.rama_principal)

    runner.check(3, "La rama de trabajo no puede ser la principal",
                 la_rama_de_trabajo_no_puede_ser_la_principal)

    def rechazar_un_alta_no_cuesta_una_vuelta_por_cx():
        """Los rechazos ocurren antes de salir a la red.

        Un nombre de rama inválido se puede rechazar sin preguntarle nada a
        nadie. Si la región se resolviera primero, rechazarlo costaría hasta 17
        peticiones —el barrido de regiones— para acabar diciendo que no, y con
        un agente inventado ni siquiera llegaría a decirlo: fallaría antes con
        un error sobre la región, que no es el problema.
        """
        llamadas = []
        original = cx.api_get
        cx.api_get = lambda *a, **k: (llamadas.append(a), original(*a, **k))[1]
        try:
            rebota, detalle = _rechaza_el_alta("sin-red", contexto.rama_principal)
        finally:
            cx.api_get = original
        if not rebota:
            return False, detalle
        return not llamadas, f"preguntó a CX {len(llamadas)} veces para decir que no"

    runner.check(3, "Rechazar un alta por el nombre de la rama no llega a "
                    "preguntarle nada a CX",
                 rechazar_un_alta_no_cuesta_una_vuelta_por_cx)

    def un_agente_sin_rama_manda_al_boton_no_a_la_herramienta():
        """Que el mensaje mande al sitio correcto.

        Hay dos ausencias distintas —el proyecto sin repositorio y el agente
        sin rama— y cada una se arregla en otro sitio. Mandar a la herramienta
        de vincular a quien solo necesita el botón del Paso 1 es pedirle que
        vuelva a vincular un repositorio que ya está vinculado.
        """
        huerfano = f"{PREFIJO}-{run_id}-sin-alta"
        try:
            pipeline.Contexto(project, huerfano, client=cliente_alta)
        except store.MappingNotFound as error:
            texto = str(error).lower()
            if "paso 1" in texto and "rama" in texto:
                return True, ""
            return False, f"el mensaje no menciona el botón del Paso 1: {error}"
        return False, "construyó el contexto de un agente que no está dado de alta"

    runner.check(3, "Un agente sin dar de alta, en un proyecto ya vinculado, "
                    "manda al botón del Paso 1 y no a la herramienta",
                 un_agente_sin_rama_manda_al_boton_no_a_la_herramienta)

    def limpiar_el_alta():
        """Devuelve el mapeo real y borra la rama y los agentes de prueba."""
        fallos = []
        store.save_agent_mapping(
            cliente_alta, project, agent_id, mapeo_original["region"],
            mapeo_original["rama"],
            carpeta_raiz=mapeo_original.get("carpeta_raiz", "definitions"))
        vuelto = store.get_agent_mapping(cliente_alta, project, agent_id)
        if vuelto["rama"] != mapeo_original["rama"]:
            fallos.append(f"el mapeo quedó en {vuelto['rama']}")
        contexto.gh.delete_branch(rama_del_alta)
        if contexto.gh.branch_head_or_none(rama_del_alta) is not None:
            fallos.append(f"{rama_del_alta}: sigue existiendo")
        for agente in agentes_inventados:
            referencia = cliente_alta.collection(store.COL_AGENTES).document(
                store._doc_id(project, agente))
            referencia.delete()
            if referencia.get().exists:
                fallos.append(f"{agente}: sigue registrado")
        return not fallos, " · ".join(fallos)

    runner.check(3, "Cero residuo del alta: el mapeo real vuelve a su rama y no "
                    "sobrevive ninguna rama ni agente de prueba",
                 limpiar_el_alta)


# ── Nivel 4 · Caos ───────────────────────────────────────────────────────────

def nivel_4(runner, project, agent_id, run_id, hermano=None):
    print("\nNIVEL 4 — Fallo inyectado y concurrencia")

    cliente = store.get_client()
    # Varios checks de este nivel escriben en el repositorio para provocar su
    # caso, y uno publica — que fusiona la rama de trabajo en la principal. Se
    # anotan las dos: antes solo se guardaba la de trabajo, así que la
    # principal se quedaba con la fusión dentro y nadie la devolvía.
    _contexto_inicial = pipeline.Contexto(project, agent_id)
    rama_al_empezar = _contexto_inicial.gh.branch_head(_contexto_inicial.rama)
    principal_al_empezar = _contexto_inicial.gh.branch_head(
        _contexto_inicial.rama_principal)

    def dos_invocaciones_concurrentes():
        primero = store.acquire_lock(cliente, project, agent_id, "prueba A")
        try:
            store.acquire_lock(cliente, project, agent_id, "prueba B")
            return False, "el segundo tomó un candado ya tomado"
        except store.LockBusy:
            return True, ""
        finally:
            store.release_lock(cliente, project, agent_id, primero)

    runner.check(4, "Dos invocaciones concurrentes sobre el mismo agente: solo "
                    "una procede",
                 dos_invocaciones_concurrentes)

    if hermano:
        def el_candado_cubre_a_los_agentes_hermanos():
            """El candado es del proyecto, no del agente.

            Lo que protege no es solo el agente: es también el repositorio, y
            ese lo comparten todos los agentes de un proyecto. Con un candado
            por agente, dos deploys hermanos escribirían en la misma rama de
            git sin verse.
            """
            primero = store.acquire_lock(cliente, project, agent_id, "deploy A")
            try:
                store.acquire_lock(cliente, project, hermano, "deploy B")
                return False, ("el hermano tomó el candado mientras el otro "
                               "escribía: los dos irían a la misma rama")
            except store.LockBusy:
                return True, ""
            finally:
                store.release_lock(cliente, project, agent_id, primero)

        runner.check(4, "Un deploy sobre un agente bloquea a sus hermanos del "
                        "mismo proyecto: comparten repositorio",
                     el_candado_cubre_a_los_agentes_hermanos)

    def el_candado_caduca_solo():
        token = store.acquire_lock(cliente, project, agent_id, "prueba TTL",
                                   ttl_seconds=-1)
        try:
            segundo = store.acquire_lock(cliente, project, agent_id, "tras caducar")
            store.release_lock(cliente, project, agent_id, segundo)
            return True, ""
        except store.LockBusy:
            return False, "un candado caducado siguió bloqueando"
        finally:
            store.release_lock(cliente, project, agent_id, token)

    runner.check(4, "Un candado caducado deja de bloquear — se libera por tiempo, "
                    "no porque el código llegue a soltarlo (un SIGKILL no ejecuta "
                    "ningún finally)",
                 el_candado_caduca_solo)

    def nadie_libera_el_candado_de_otro():
        token = store.acquire_lock(cliente, project, agent_id, "prueba dueño")
        try:
            robado = store.release_lock(cliente, project, agent_id, "token-inventado")
            return not robado, "un token ajeno liberó el candado"
        finally:
            store.release_lock(cliente, project, agent_id, token)

    runner.check(4, "Un token ajeno no libera el candado", nadie_libera_el_candado_de_otro)

    def el_candado_no_vive_en_memoria():
        texto = (REPO_ROOT / "act/utils/firestore_client_cloudrun.py").read_text()
        return "threading.Lock" not in texto, (
            "hay un threading.Lock, que es por proceso y no protege entre instancias"
        )

    runner.check(4, "El candado no es un threading.Lock — con más de una "
                    "instancia no protegería nada",
                 el_candado_no_vive_en_memoria)

    def el_progreso_sobrevive_al_contenedor():
        """Se anota un progreso y se lee con un cliente nuevo, como haría un
        contenedor recién arrancado.

        Comprobar que una función devuelve una lista no prueba nada: devolvería
        una lista vacía igual si el progreso se estuviera guardando en memoria
        del proceso, que es justo el fallo que este check existe para detectar.
        """
        marca = f"{PREFIJO}_{run_id}_progreso"
        store.record_resource_write(
            cliente, project, agent_id, "intent", marca,
            "sintetico/progreso.yaml", display_name=marca, operacion="PATCH",
        )
        try:
            otro_cliente = store.get_client()   # como un contenedor nuevo
            leidos = store.list_resource_records(otro_cliente, project, agent_id)
            encontrado = ("intent", marca) in leidos
            registro = store.get_resource_record(otro_cliente, project, agent_id,
                                                 "intent", marca)
            return (encontrado and registro is not None
                    and registro.get("archivo") == "sintetico/progreso.yaml"), (
                "el progreso anotado no se ve desde un cliente nuevo: no está "
                "sobreviviendo fuera del proceso"
            )
        finally:
            # Se borra de verdad, no se marca. Antes se «cerraba» quitándole la
            # marca de pendiente, que dejaba el documento sintético dentro de la
            # auditoría del agente para siempre.
            store._sub(cliente, project, agent_id, store.SUB_RESOURCES).document(
                store._resource_doc_id("intent", marca)
            ).delete()

    runner.check(4, "El progreso por resource vive en Firestore, no en memoria",
                 el_progreso_sobrevive_al_contenedor)

    def la_auditoria_no_tumba_la_operacion():
        class ClienteRoto:
            def collection(self, *_):
                raise RuntimeError("Firestore caído a propósito")
        resultado = store.record_run(ClienteRoto(), project, agent_id, 3, "ok", [])
        return resultado is False, (
            "record_run propagó el fallo — una operación correcta se contaría "
            "como error"
        )

    runner.check(4, "Si la auditoría falla, la operación sigue siendo correcta",
                 la_auditoria_no_tumba_la_operacion)

    def sin_fugas_entre_agentes():
        """Un contenedor de Cloud Run se reutiliza entre peticiones de agentes
        distintos. Un valor cacheado a nivel de módulo se filtraría."""
        cabeceras_a = cx.get_headers("proyecto-a")
        cabeceras_b = cx.get_headers("proyecto-b")
        return (cabeceras_a["x-goog-user-project"] == "proyecto-a"
                and cabeceras_b["x-goog-user-project"] == "proyecto-b"), \
            "la cabecera de cuota se cachea entre llamadas"

    runner.check(4, "La cabecera x-goog-user-project no se cachea entre agentes",
                 sin_fugas_entre_agentes)

    def reintento_solo_lo_pendiente():
        """Reintentar tras un fallo parcial reenvía lo fallido y lo no
        intentado, nunca lo que ya salió bien: repetirlo lo escribiría dos
        veces.

        Se fabrican tres resources nuevos, se reintenta declarando solo uno
        como pendiente, y se cuentan las escrituras HTTP reales. Confirmarlo
        por el resultado final no valdría: como las operaciones son
        idempotentes, reenviar las tres daría el mismo estado y ocultaría el
        fallo de seguimiento.
        """
        contexto = pipeline.Contexto(project, agent_id)
        rama0 = contexto.gh.branch_head(contexto.rama)
        rutas = {}
        for sufijo in ("uno", "dos", "tres"):
            nombre = f"{PREFIJO}_{run_id}_reint_{sufijo}"
            rutas[sufijo] = f"definitions/intents/{nombre}.yaml"
        contexto.gh.commit_files(contexto.rama, {
            ruta: __import__("yaml").safe_dump(
                {"metadata": {"tipo": "intent", "padre": None, "cx_id": None,
                              "agente": agent_id},
                 "displayName": pathlib_stem(ruta),
                 "trainingPhrases": [{"parts": [{"text": "hola"}],
                                      "repeatCount": 1}]},
                allow_unicode=True, sort_keys=False)
            for ruta in rutas.values()
        }, f"test: tres resources para el reintento ({run_id})")

        try:
            elegido = rutas["dos"]
            with ContadorHttp() as contador:
                pipeline.step_3_apply_to_cx(
                    project, agent_id,
                    aplicar=[{"tipo": "intent", "ruta": elegido}],
                    only_pending=[{"tipo": "intent", "ruta": elegido}],
                )
            creaciones = [c for c in contador.escrituras()
                          if c[0] == "POST" and c[1].endswith("/intents")]
            return len(creaciones) == 1, (
                f"{len(creaciones)} altas de intent en el reintento; se declaró "
                f"pendiente solo una. Reenviar las tres significa que el "
                f"seguimiento de lo ya aplicado no funciona"
            )
        finally:
            inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["intent"])
            for item in inventario.get("intent", {}).values():
                if str(item.get("displayName", "")).startswith(f"{PREFIJO}_{run_id}_reint"):
                    cx.api_delete(project, contexto.region, item["name"])
            requests.patch(
                f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/"
                f"{contexto.rama}", headers=contexto.gh._headers(),
                json={"sha": rama0, "force": True}, timeout=30)

    runner.check(4, "El reintento solo reenvía lo pendiente", reintento_solo_lo_pendiente)

    runner.skip(4, "SIGKILL a mitad de una escritura real del Paso 3",
                "exige lanzar el pipeline como subproceso y matarlo en el momento "
                "exacto de una escritura. La garantía que probaría —el candado se "
                "libera por caducidad— sí está cubierta arriba, sin depender del "
                "momento del disparo")

    def fallo_entre_crear_version_y_apuntar_entorno():
        """Se corta el Paso 5 justo después de crear la versión.

        Lo que se comprueba es si el reintento apunta el entorno a la versión
        que ya existe, o si crea otra — que dejaría la primera huérfana y el
        estado de CX ambiguo.
        """
        cliente = store.get_client()
        contexto = pipeline.Contexto(project, agent_id)

        # Si nada difiere de lo que producción sirve no se crea ninguna
        # versión, y el escenario —una versión huérfana tras el corte— no llega
        # a existir: el check pasaría sin haber probado nada. Se cambia un
        # playbook de verdad en el borrador para que el Paso 5 tenga qué
        # versionar. Se cambia en CX, no se anota en Firestore: es exactamente
        # lo que el Paso 5 mira ahora.
        contenedor_de_pruebas(contexto, "playbook", f"{PREFIJO}_{run_id}_corte",
                              f"{PREFIJO}_{run_id}_corte_1")
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        difieren_antes = pipeline._contenedores_cambiados(
            contexto, inventario)["cambiados"]
        if not difieren_antes:
            return False, "no se pudo dejar nada que difiriera de producción"

        original = pipeline._apuntar_entorno
        pipeline._apuntar_entorno = lambda *_a, **_k: (_ for _ in ()).throw(
            pipeline.PipelineError("corte inyectado antes de apuntar el entorno")
        )
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        try:
            pipeline.step_5_publish(project, agent_id, f"{PREFIJO}_{run_id}_corte")
            interrumpido = False
        except pipeline.PipelineError:
            interrumpido = True
        finally:
            pipeline._apuntar_entorno = original

        if not interrumpido:
            return False, "el corte no llegó a interrumpir el paso"

        # Lo que el corte dejó creado y sin fijar. Es contra esto contra lo que
        # se compara: el reintento tiene que usar exactamente estas, no otras.
        en_vuelo = store.get_inflight_versions(cliente, project, agent_id)
        if not en_vuelo or not en_vuelo.get("version_names"):
            return False, ("el corte no dejó anotada ninguna versión creada, "
                           "así que nada puede reutilizarla después")
        huerfanas = set(en_vuelo["version_names"])

        pipeline.step_4_validate_tests(project, agent_id, "superados")
        reintento = pipeline.step_5_publish(project, agent_id, f"{PREFIJO}_{run_id}_reintento")
        if reintento["status"] != "ok":
            return False, f"el reintento falló: {reintento['status']}"
        usadas = set(reintento["data"]["versiones_creadas"])
        return usadas == huerfanas, (
            f"con {len(difieren_antes)} contenedores distintos de producción, el "
            f"corte dejó {len(huerfanas)} versiones creadas y el reintento usó "
            f"{len(usadas)}, de las que {len(usadas - huerfanas)} son nuevas. "
            f"Las que no se reutilizan quedan huérfanas."
        )

    runner.check(4, "Tras un corte entre crear la versión y apuntar el entorno, "
                    "el reintento reutiliza la versión ya creada",
                 fallo_entre_crear_version_y_apuntar_entorno)

    def un_cambio_posterior_al_corte_tambien_se_versiona():
        """Publicar falla, tocas OTRA cosa, y reintentas.

        Lo que sobró del intento anterior cubre lo de antes, no lo nuevo. Si se
        da por buena la cobertura entera, el cambio nuevo no se versiona y no
        llega a producción nunca.

        Los dos cambios se hacen **en CX**, no anotándolos en Firestore: es lo
        que el Paso 5 mira ahora, y hacerlo así prueba además que el reintento
        ve un cambio que ningún paso del pipeline registró.
        """
        cliente = store.get_client()
        contexto = pipeline.Contexto(project, agent_id)
        store.clear_inflight_versions(cliente, project, agent_id)

        # 1 · Se cambia solo el playbook. Se corta al apuntar el entorno.
        contenedor_de_pruebas(contexto, "playbook",
                              f"{PREFIJO}_{run_id}_post_pb",
                              f"{PREFIJO}_{run_id}_post_1")
        original = pipeline._apuntar_entorno
        pipeline._apuntar_entorno = lambda *_a, **_k: (_ for _ in ()).throw(
            pipeline.PipelineError("corte inyectado"))
        pipeline.step_4_validate_tests(project, agent_id, "superados")
        try:
            pipeline.step_5_publish(project, agent_id, f"{PREFIJO}_{run_id}_antes")
        except pipeline.PipelineError:
            pass
        finally:
            pipeline._apuntar_entorno = original

        en_vuelo = store.get_inflight_versions(cliente, project, agent_id)
        if not en_vuelo or not en_vuelo.get("version_names"):
            return False, "el corte no dejó ninguna versión anotada"
        del_playbook = {v for v in en_vuelo["version_names"]
                        if "/playbooks/" in v}
        if not del_playbook:
            return False, "el corte no dejó ninguna versión del playbook"

        # 2 · Entre el fallo y el reintento se cambia ADEMÁS un flow.
        flow = contenedor_de_pruebas(contexto, "flow",
                                     f"{PREFIJO}_{run_id}_post_flow",
                                     f"{PREFIJO}_{run_id}_post_2")

        pipeline.step_4_validate_tests(project, agent_id, "superados")
        resultado = pipeline.step_5_publish(project, agent_id, f"{PREFIJO}_{run_id}_despues")
        if resultado["status"] != "ok":
            return False, f"el reintento falló: {resultado['status']}"

        fijadas = resultado["data"]["versiones_creadas"]
        padres = {v.rsplit("/versions/", 1)[0] for v in fijadas}
        tiene_flow = flow["name"] in padres
        reuso = bool(del_playbook & set(fijadas))

        return tiene_flow and reuso, (
            f"reutilizó lo del playbook: {reuso} · versionó el flow nuevo: "
            f"{tiene_flow}. Sin versionar el flow, su cambio no llega a "
            f"producción nunca"
        )

    runner.check(4, "Un cambio hecho entre el fallo y el reintento también se "
                    "versiona: reutilizar lo que sobró no puede darse por "
                    "cobertura completa",
                 un_cambio_posterior_al_corte_tambien_se_versiona)

    def el_gate_del_paso_4_aborta_si_el_borrador_se_movio():
        """La huella se toma al declarar los tests y se compara al publicar.

        La huella ya no llega como parámetro de quien llama — se lee de la
        última declaración del Paso 4 en Firestore. Para provocar el desajuste
        hay que declarar los tests y luego mover el borrador de verdad, igual
        que haría alguien editando en la consola entre el Paso 4 y el Paso 5.

        Aborta, no avisa: publicar subiría a usuarios reales algo que nadie
        validó. Y aborta antes del merge, así que no deja nada a medias.
        """
        contexto = pipeline.Contexto(project, agent_id)

        def foto():
            inventario, _, _ = pipeline.inventariar_cx(contexto)
            produccion = next(
                e for e in inventario["environment"].values()
                if e.get("displayName") == "production"
            )
            return {
                "produccion": [c["version"] for c in
                               produccion.get("versionConfigs", [])],
                "borrador": pipeline._huella_borrador(inventario),
                "rama": contexto.gh.branch_head(contexto.rama),
                "principal": contexto.gh.branch_head(contexto.rama_principal),
            }

        pipeline.step_4_validate_tests(project, agent_id, "superados")

        # Mueve el borrador de verdad después de declarar los tests: la huella
        # que quedó guardada en el Paso 4 deja de corresponder a lo que hay
        # ahora en CX. Mismo patrón que usa la prueba de poda de versiones más
        # arriba para provocar un cambio real y no un no-op.
        inventario, _, _ = pipeline.inventariar_cx(contexto, tipos=["flow"])
        flow = next(iter(inventario["flow"].values()))
        cuerpo = {k: v for k, v in flow.items()
                 if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
        cuerpo["description"] = f"{PREFIJO}_{run_id}_huella_vieja"
        cx.api_patch(project, contexto.region, flow["name"], cuerpo)

        antes = foto()
        resultado = pipeline.step_5_publish(
            project, agent_id, f"{PREFIJO}_{run_id}_huella_vieja",
        )
        despues = foto()

        # Abortar no es revertir: lo que el Paso 3 aplicó sigue en el borrador,
        # y ni el repositorio ni producción se mueven. Simplemente no avanza.
        cambiado = [k for k in antes if antes[k] != despues[k]]
        return (resultado["status"] == "aborted"
                and not resultado["data"]["fusionado"]
                and not resultado["data"]["publicado"]
                and not cambiado), (
            f"status={resultado['status']} · cambió: {cambiado or 'nada'}"
        )

    runner.check(4, "Abortar por borrador movido no revierte nada: el borrador "
                    "conserva lo aplicado, y producción, la rama de trabajo y la "
                    "principal quedan intactas. Simplemente no avanza",
                 el_gate_del_paso_4_aborta_si_el_borrador_se_movio)

    def se_detecta_el_conflicto_de_los_dos_lados():
        """El repositorio cambió y CX también, por separado.

        Con dos estados no se puede distinguir de un cambio normal: hace falta
        saber cómo quedó CX la última vez que escribió el pipeline. Se provoca
        el caso tocando un resource directamente en CX, como haría alguien
        editando en la consola.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        repositorio, _ = pipeline.cargar_repositorio(contexto)

        # Un resource emparejado y ya escrito por el pipeline alguna vez.
        #
        # Y que además **admita de verdad** el campo con el que se le va a
        # tocar: no todos los tipos tienen `description`. En un entity_type, CX
        # responde 200 y descarta el campo en silencio, así que el toque «por
        # fuera» no cambia nada y no hay conflicto que detectar — el check
        # fallaba sin decir por qué, y solo cuando le tocaba ese tipo de entre
        # los cientos de fichas. Se comprueba leyendo el efecto, no el código
        # de respuesta.
        auditados = store.list_resource_records(cliente, project, agent_id)
        elegibles = [
            (t, c) for (t, c), reg in auditados.items()
            if reg.get("huella_cx") and c in inventario.get(t, {})
            and c in repositorio["por_tipo"].get(t, {})
        ]
        if not elegibles:
            return False, ("ningún resource tiene huella guardada de la última "
                           "escritura: sin ese tercer punto el conflicto no se "
                           "puede detectar para ninguno")

        tipo = cx_id = remoto = None
        descartados = []
        for candidato_tipo, candidato_id in elegibles:
            item = inventario[candidato_tipo][candidato_id]
            antes = pipeline.huella_resource(item)
            cuerpo = {k: v for k, v in item.items()
                      if k not in pipeline.CAMPOS_LEIDOS_NO_ENVIADOS}
            cuerpo["description"] = f"tocado por fuera {run_id}"
            externo = cx.api_patch(project, contexto.region, item["name"], cuerpo)
            if externo.status_code not in (200, 201):
                descartados.append(f"{candidato_tipo}: {externo.status_code}")
                continue
            # El efecto, no la respuesta: si la huella no cambió, CX ignoró el
            # campo y este resource no sirve para provocar el caso.
            releido = cx.api_get(project, contexto.region, item["name"])
            if releido.status_code != 200 or \
                    pipeline.huella_resource(releido.json()) == antes:
                descartados.append(f"{candidato_tipo}: no admite `description`")
                continue
            tipo, cx_id, remoto = candidato_tipo, candidato_id, item
            break

        if remoto is None:
            return False, ("ningún resource admitió el toque externo: " +
                           " · ".join(descartados[:4]))

        # Y se cambia también el repositorio, para que el diff proponga algo.
        entrada = repositorio["por_tipo"][tipo][cx_id]
        documento = dict(entrada["documento"])
        documento["description"] = f"tocado en el repo {run_id}"
        contexto.gh.commit_files(
            contexto.rama,
            {entrada["ruta"]: __import__("yaml").safe_dump(
                documento, allow_unicode=True, sort_keys=False)},
            f"test: provocar un conflicto en {tipo}/{cx_id}",
        )

        datos = pipeline.step_3_apply_to_cx(project, agent_id, dry_run=True)["data"]
        conflictos = datos.get("conflictos", [])
        return any(c["cx_id"] == cx_id for c in conflictos), (
            f"{len(conflictos)} conflictos detectados, ninguno de {tipo}/{cx_id}"
        )

    runner.check(4, "Un resource cambiado a la vez en el repositorio y en CX se "
                    "señala como conflicto, no se resuelve en silencio a favor "
                    "del repositorio",
                 se_detecta_el_conflicto_de_los_dos_lados)

    def si_no_se_puede_comparar_un_flow_el_paso_para():
        """4.1 — nunca publicar a ciegas.

        Si `compareVersions` falla, no se sabe si el flow cambió. Tratarlo como
        «sin cambios» sería exactamente el fallo que todo esto corrige, entrando
        por la puerta de un error de red: el paso diría que fue bien y el cambio
        se quedaría en el borrador.

        Se inyecta el fallo solo en ese endpoint, para que el resto del paso
        funcione igual que siempre y el corte no lo provoque otra cosa.
        """
        contexto = pipeline.Contexto(project, agent_id)
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        fijadas = pipeline._versiones_fijadas(inventario)
        if not any("/flows/" in c for c in fijadas):
            return True, "(producción no fija ninguna versión de flow)"

        original = cx.api_request

        def rompe_solo_la_comparacion(method, proj, region, path, *args, **kwargs):
            if path.endswith(":compareVersions"):
                return _RespuestaFalsa(503, {"error": "servicio no disponible"})
            return original(method, proj, region, path, *args, **kwargs)

        cx.api_request = rompe_solo_la_comparacion
        try:
            pipeline._contenedores_cambiados(contexto, inventario)
            return False, ("la comparación falló y se siguió adelante: el flow "
                           "se habría dado por publicado sin serlo")
        except pipeline.PipelineError as error:
            mensaje = str(error)
            return ("503" in mensaje and "no se publica" in mensaje.lower()), \
                f"el mensaje no explica por qué se para: {mensaje[:180]}"
        finally:
            cx.api_request = original

    runner.check(4, "Si no se puede comparar un flow, el paso para y lo dice — "
                    "nunca publica asumiendo que no cambió",
                 si_no_se_puede_comparar_un_flow_el_paso_para)

    def ninguna_version_creada_sobra():
        """4.4 — la cuota, contada.

        Ninguna versión creada puede corresponder a un contenedor que no
        difería de lo que producción sirve. Es la regla del mínimo consumo
        medida sobre el resultado, no sobre la intención.
        """
        contexto = pipeline.Contexto(project, agent_id)
        contenedor_de_pruebas(contexto, "playbook", f"{PREFIJO}_{run_id}_cuota",
                              f"cuota {run_id}")
        inventario, _, _ = pipeline.inventariar_cx(contexto)
        comparacion = pipeline._contenedores_cambiados(contexto, inventario)
        difieren = {c["name"] for c in comparacion["cambiados"]}
        al_dia = {c["name"] for c in comparacion["iguales"]}

        pipeline.step_4_validate_tests(project, agent_id, "superados")
        resultado = pipeline.step_5_publish(project, agent_id,
                                            f"{PREFIJO}_{run_id}_cuota")
        if resultado["status"] != "ok":
            return False, f"el Paso 5 falló: {resultado['status']}"
        creadas = resultado["data"]["versiones_creadas"]
        padres = {v.rsplit("/versions/", 1)[0] for v in creadas}
        sobran = padres & al_dia
        fuera = padres - difieren
        return not sobran and not fuera, (
            f"{len(creadas)} versiones creadas · {len(sobran)} de contenedores "
            f"que no cambiaron · {len(fuera)} de contenedores que ni siquiera "
            f"estaban en la lista")

    runner.check(4, "Cuota: ninguna versión creada corresponde a un contenedor "
                    "que no cambió",
                 ninguna_version_creada_sobra)

    def limpiar_cx_del_nivel_4():
        """El barrido de CX que este nivel no tenía.

        Se descubrió comparando una foto del agente antes y después de una
        corrida entera: el nivel había dejado cuatro resources vivos y cuatro
        punteros suyos en el entorno de producción, y la corrida declaraba
        «cero residuo» — porque su única limpieza era la de las ramas. El Nivel
        3 sí sabía desanclar antes de borrar; aquí ese conocimiento
        sencillamente no estaba.

        Usa la misma función que el Nivel 3, no una copia: es lo único que
        impide que los dos vuelvan a discrepar.

        El contexto se construye aquí, fresco. El del principio del nivel se
        creó antes de que varios checks movieran las ramas, y barrer es
        exactamente el momento en que hay que leer el estado de ahora.
        """
        return barrer_cx_de_las_pruebas(
            pipeline.Contexto(project, agent_id), project)

    runner.check(4, "Cero residuo en CX: este nivel también desancla y borra lo "
                    "que creó, confirmándolo leyendo",
                 limpiar_cx_del_nivel_4)

    def limpiar_repositorio_del_nivel_4():
        """Devuelve las dos ramas al punto en que empezó el nivel.

        Va **la última** del nivel a propósito. Estaba en medio —el décimo de
        catorce— y los cuatro checks siguientes seguían escribiendo: uno de
        ellos publica, que fusiona la rama de trabajo en la principal. Así que
        la suite entera dejaba el repositorio desplazado aunque cada nivel
        declarase su limpieza en verde.

        No lo vio nadie porque cada nivel comprueba su limpieza contra el punto
        en que él empezó, y ninguno comparaba el repositorio antes y después de
        la corrida completa.
        """
        contexto = pipeline.Contexto(project, agent_id)
        fallos = []
        for rama, destino in ((contexto.rama, rama_al_empezar),
                              (contexto.rama_principal, principal_al_empezar)):
            if contexto.gh.branch_head(rama) == destino:
                continue
            respuesta = requests.patch(
                f"https://api.github.com/repos/{contexto.repo}/git/refs/heads/"
                f"{rama}",
                headers=contexto.gh._headers(),
                json={"sha": destino, "force": True}, timeout=30,
            )
            if respuesta.status_code != 200:
                fallos.append(f"{rama}: {respuesta.status_code}")
                continue
            # GitHub no devuelve el nuevo valor de la referencia al instante
            # tras forzarla: leerlo de inmediato daba el valor anterior y el
            # check declaraba un residuo que no existía. Se le da margen, pero
            # acotado — si tras varios intentos sigue sin volver, es real.
            for intento in range(5):
                if contexto.gh.branch_head(rama) == destino:
                    break
                time.sleep(1 + intento)
            else:
                fallos.append(f"{rama}: no volvió a {destino[:7]}")
        return not fallos, " · ".join(fallos)

    runner.check(4, "Cero residuo: las dos ramas vuelven al commit en el que "
                    "estaban antes del nivel",
                 limpiar_repositorio_del_nivel_4)


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
    fuera = [n for n in niveles if not 0 <= n <= 4]
    if fuera:
        raise SystemExit(
            f"Niveles válidos: 0 a 4. Recibido {fuera}. La validación contra un "
            f"Cloud Run real es de la Fase 6, no de esta."
        )
    return sorted(niveles)


def _huella_del_repositorio(project, agent_id):
    """Dónde está cada rama del destino, para comparar antes y después.

    Las dos ramas, no solo la de trabajo: publicar fusiona una en otra, así que
    una corrida puede dejar la principal movida sin tocar la de trabajo.
    """
    contexto = pipeline.Contexto(project, agent_id)
    return {contexto.rama: contexto.gh.branch_head(contexto.rama),
            contexto.rama_principal:
                contexto.gh.branch_head(contexto.rama_principal)}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smoke test del pipeline de deploy Cloud Run."
    )
    parser.add_argument("--project", help="Proyecto GCP del agente")
    parser.add_argument("--agent", help="ID del agente CX desechable")
    parser.add_argument("--agente-hermano", dest="hermano",
                        help="Segundo agente desechable del mismo proyecto, "
                             "para probar que comparten repositorio sin mezclarse")
    parser.add_argument("--levels", default="0",
                        help="Niveles a ejecutar: '0', '0-2', '3,4'")
    parser.add_argument("--solo",
                        help="Ejecuta solo los checks cuyo nombre contenga este "
                             "texto. Para depurar uno suelto, o para comprobar "
                             "que caza el defecto que dice cazar sin pagar el "
                             "nivel entero. Lo omitido se declara al final: una "
                             "corrida filtrada nunca se lee como completa.")
    args = parser.parse_args(argv)

    niveles = parse_levels(args.levels)
    runner = CheckRunner(solo=args.solo)
    run_id = uuid.uuid4().hex[:8]

    necesita_destino = any(n in niveles for n in (1, 2, 3, 4))
    if necesita_destino and not (args.project and args.agent):
        parser.error(
            "Los niveles 1 a 4 exigen --project y --agent. No hay valor por "
            "defecto: un default silencioso convierte una prueba en una "
            "escritura sobre un agente real."
        )

    region = None
    if necesita_destino:
        region, nombre = exigir_agente_desechable(args.project, args.agent)
        if 3 in niveles:
            # El Nivel 3 publica de verdad, y publicar fusiona en la principal.
            exigir_rama_principal_desechable(args.project)
        print(f"Destino: {nombre} · {args.project} · {region} · corrida {run_id}")

    # La foto del repositorio antes de tocar nada. Cada nivel comprueba su
    # propia limpieza contra el punto en que él empezó, y eso no demuestra que
    # el conjunto no deje nada: el Nivel 4 declaraba su limpieza en verde y aun
    # así la suite entera dejaba las dos ramas desplazadas —su limpieza era el
    # décimo check de catorce, y cuatro seguían escribiendo detrás—. Nadie lo
    # vio hasta que algo comparó el antes y el después de la corrida completa.
    huella_inicial = None
    if necesita_destino:
        huella_inicial = _huella_del_repositorio(args.project, args.agent)

    if 0 in niveles:
        nivel_0(runner)
    if 1 in niveles:
        nivel_1(runner, args.project, args.agent, region, run_id, args.hermano)
    if 2 in niveles:
        nivel_2(runner, args.project, args.agent)
    if 3 in niveles:
        nivel_3(runner, args.project, args.agent, run_id)
    if 4 in niveles:
        nivel_4(runner, args.project, args.agent, run_id, args.hermano)

    if huella_inicial is not None:
        def la_corrida_entera_no_deja_rastro():
            final = _huella_del_repositorio(args.project, args.agent)
            if final == huella_inicial:
                return True, ""
            movidas = [f"{rama}: {huella_inicial[rama][:7]} → {sha[:7]}"
                       for rama, sha in final.items()
                       if huella_inicial.get(rama) != sha]
            return False, " · ".join(movidas) or f"{huella_inicial} → {final}"

        runner.check(max(niveles), "La corrida entera devuelve el repositorio "
                                   "como lo encontró, no solo cada nivel el suyo",
                     la_corrida_entera_no_deja_rastro)

    c = runner.counts()
    print(f"\nRESUMEN: {c[PASS]} PASS · {c[FAIL]} FAIL · {c[SKIP]} SKIP")
    if runner.solo:
        # Se dice siempre, y con el número: sin esta línea, el resumen de una
        # corrida filtrada es indistinguible del de una completa.
        print(f"CORRIDA FILTRADA por «{runner.solo}» — {runner.omitidos} checks "
              f"no se ejecutaron. Esto NO es una validación completa.")
    if c[SKIP]:
        print("Los SKIP no son cobertura: cada uno dice arriba qué falta para "
              "poder ejecutarlo.")
    print("La validación contra un Cloud Run real no está aquí: es de la Fase 6, "
          "que valida el servidor desplegado.")
    return 1 if runner.failed() else 0


if __name__ == "__main__":
    raise SystemExit(main())
