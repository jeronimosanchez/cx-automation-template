#!/usr/bin/env python3
"""
act/act_cx_resources_deploy_cloudrun.py — Backend del pipeline de deploy ACT
en su variante Cloud Run.

Hace real lo que docs/panels/act_cx_resources_deploy_v2.html describe: cinco
pasos —Inventario, Traer al repositorio, Aplicar en CX, Validar tests,
Publicar— más tres capacidades que no pertenecen a ningún paso numerado:
Descubrimiento, Vincular proyecto y repositorio (con el alta de cada agente) y
Versiones existentes. Ocho funciones públicas en total; el servidor de la fase
siguiente delega en ellas y no reimplementa nada.

Cinco cosas separan esto del pipeline local (act/act_cx_resources_deploy.py),
que sigue siendo el único camino real a producción y no se toca:

1. **Proyecto, agente y región nunca son constantes.** Los dos primeros llegan
   por parámetro; la región se resuelve por agente desde Firestore (S4). En el
   local, `LOCATION = "europe-west1"` estaba cableada.

2. **El emparejamiento va por `tipo` + `cx_id`, no por `displayName`** (S18).
   Un nombre puede cambiar a propósito; el identificador que asigna CX no. La
   clave lleva el tipo porque un `cx_id` solo es único dentro de su tipo:
   verificado con caso real — el Playbook orquestador de Petal y el Intent
   "Default Welcome Intent" comparten el ID 00000000-…-000000000000.

3. **La estructura de carpetas del repositorio es libre** (S19). El tipo lo
   declara el propio YAML en su bloque `metadata`; el servidor lee todos los
   YAML recursivamente y agrupa por ese campo. Un YAML sin `metadata` no es un
   resource del pipeline y se ignora sin ruido.

4. **El diff nunca propone borrar.** En el local hacía "POST lo que falta,
   PATCH lo que cambió, DELETE lo que sobra", así que un recurso creado a mano
   en la consola de CX se borraba en el siguiente deploy sin que nadie lo
   pidiera — y con un repositorio recién creado proponía borrar el agente
   entero. Aquí borrar se decide en el Paso 2 y se aplica en el Paso 3.

5. **El repositorio se lee y se escribe por la API de GitHub**, no desde un
   árbol de git en disco: en el contenedor no hay repositorio ni git.
"""

import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.utils import cx_client_cloudrun as cx
from act.utils import cx_payloads_cloudrun as payloads
from act.utils import firestore_client_cloudrun as store
from act.utils.github_app_client_cloudrun import GitHubAppClient


# ── Tabla de recursos ────────────────────────────────────────────────────────
#
# Los 13 tipos que la API de CX admite hoy, verificados contra su discovery
# document real. `api` es el segmento de ruta, `key` el campo del JSON que
# contiene los ítems en la respuesta LIST, `padre` el tipo del que cuelga
# cuando no cuelga del agente directamente, y `carpeta` dónde escribe el pull
# un resource nuevo.
#
# La lista está abierta: un proyecto puede declarar tipos adicionales en su
# cx-deploy.yaml con su endpoint (S15).

RESOURCE_TYPES = {
    "entity_type": {"api": "entityTypes", "key": "entityTypes",
                    "carpeta": "definitions/entity_types"},
    "intent": {"api": "intents", "key": "intents",
               "carpeta": "definitions/intents"},
    "webhook": {"api": "webhooks", "key": "webhooks",
                "carpeta": "definitions/webhooks"},
    "tool": {"api": "tools", "key": "tools",
             "carpeta": "definitions/tools"},
    "generator": {"api": "generators", "key": "generators",
                  "carpeta": "definitions/generators"},
    "playbook": {"api": "playbooks", "key": "playbooks",
                 "carpeta": "definitions/playbooks"},
    "example": {"api": "examples", "key": "examples", "padre": "playbook",
                "carpeta": "definitions/examples"},
    "flow": {"api": "flows", "key": "flows",
             "carpeta": "definitions/flows"},
    "page": {"api": "pages", "key": "pages", "padre": "flow",
             "carpeta": "definitions/pages"},
    # Existe en los dos niveles: colgando del agente y colgando de cada flow.
    # Listar solo uno dejaría fuera resources reales sin decirlo.
    "transition_route_group": {"api": "transitionRouteGroups",
                               "key": "transitionRouteGroups",
                               "padre": "flow", "tambien_en_agente": True,
                               "carpeta": "definitions/transition_route_groups"},
    "agent_config": {"api": "", "key": "", "singular": True,
                     "carpeta": "definitions/config"},
    "environment": {"api": "environments", "key": "environments",
                    "carpeta": "definitions/environments"},
    # Las versiones cuelgan de los tres contenedores, y **cada uno devuelve la
    # suya con una clave distinta** — verificado contra la API el 2026-08-09.
    # Declararlas solo bajo `flow` con la clave `versions` hacía que las de
    # playbook y tool fueran invisibles: el listado pedía `versions`, recibía
    # una lista vacía, y el pipeline concluía que no existían. Se acumulaban
    # una por publicación hasta el límite de CX (100 en un playbook), y ahí
    # publicar dejaba de funcionar con un error que no mencionaba versiones.
    "version": {"api": "versions",
                "padres": (("flow", "versions"),
                           ("playbook", "playbookVersions"),
                           ("tool", "toolVersions")),
                "carpeta": "definitions/versions"},
}

# Los tipos referenciados por otros van primero: si un playbook apunta a un
# webhook, el webhook tiene que existir antes del PATCH del playbook.
DEPLOY_ORDER = [
    "entity_type", "intent", "webhook", "tool", "generator",
    "transition_route_group", "playbook", "example", "flow", "page",
    "agent_config",
]

# Environments y Versions no salen del diff: se manejan en el Paso 5.
TIPOS_NO_DESPLEGABLES = ("environment", "version")

# Tipos que el pipeline COMPARA pero nunca ESCRIBE: se suben a mano.
#
# Un tool es el único resource que guarda un secreto —la clave del backend— y
# CX no la devuelve al leer: manda "REDACTED" si hay clave y nada si no la hay.
# Eso deja al Full Update sin forma segura de tocarlo: mandar el marcador puede
# escribir la palabra "REDACTED" como clave, y omitirlo puede borrarla. Las dos
# roturas son silenciosas — el tool empieza a dar 401 y nada lo explica.
#
# Y el coste de excluirlos es casi cero, medido sobre el historial real:
#
#     Petal V2    4 de 107 commits tocan tools    3,7 %  (dos son del pipeline)
#     Petal 1.1   7 de 439 commits                1,6 %
#
# Automatizar algo que cambia dos veces no ahorra nada, y aquí encima arriesga.
# La regla que queda: **el pipeline despliega contenido; los secretos los pone
# una persona.**
#
# SIGUEN SALIENDO EN EL PASO 1. Excluirlos de aplicar, no de mirar: si
# desaparecieran del inventario dejarías de enterarte de que un tool cambió en
# CX o de que el repo y CX divergen, que es peor que el problema que se quita.
TIPOS_SOLO_A_MANO = ("tool",)

# La tabla que consulta todo lo que escribe un resource, que hoy es solo el
# Paso 3. No contiene `environment`, así que ningún camino de escritura puede
# construir una URL con `/environments/` aunque se le pida: no es una
# comprobación que pueda fallar, es una entrada que no existe. La única función
# que sabe escribir esa URL es `_apuntar_entorno`, y solo la alcanza el Paso 5.
TIPOS_DESPLEGABLES = {
    tipo: spec for tipo, spec in RESOURCE_TYPES.items()
    if tipo not in TIPOS_NO_DESPLEGABLES and tipo not in TIPOS_SOLO_A_MANO
}

# Tipos que CX no puede congelar en una versión: lo que se les aplique lo ven
# los usuarios en el acto, sin pasar por el gate del Paso 4.
TIPOS_SIN_VERSION = ("agent_config", "generator")


ENTORNO_PRODUCCION = "production"

# Lo que la cuenta de servicio necesita sobre CADA proyecto que vaya a manejar.
# Sin organización no hay ningún sitio donde concederlo una sola vez —los
# proyectos sueltos no cuelgan de nada común—, así que esto se repite por
# proyecto y el panel tiene que poder decirlo cuando se tropieza con uno nuevo.
#
# Los tres, y ninguno sobra:
#   browser                      → `resourcemanager.projects.list`, que es lo
#                                  único que hace que el proyecto aparezca en el
#                                  desplegable. `dialogflow.admin` da `.get`
#                                  pero no `.list`.
#   dialogflow.admin             → leer y escribir el agente.
#   serviceusage...Consumer      → `serviceusage.services.use`, que exige la
#                                  cabecera `x-goog-user-project` de TODA
#                                  llamada a CX. `dialogflow.admin` NO lo
#                                  incluye: sin él todo sale 403 aunque el
#                                  primero esté concedido (hallazgo X1,
#                                  `docs/cloudrun_diseno_servidor.md §8.4`).
ROLES_DEL_ALTA = (
    "roles/browser",
    "roles/dialogflow.admin",
    "roles/serviceusage.serviceUsageConsumer",
)

# Marcas de que una rama principal es provisional. No es una lista de nombres
# prohibidos: es una señal para que publicar no diga "✓" en silencio cuando el
# código va a parar a una rama de pruebas en vez de a la real del repositorio.
MARCAS_RAMA_NO_DEFINITIVA = ("prueba", "desechable", "sandbox", "temporal")

ETIQUETA_VERSION_VALIDA = re.compile(r"^[A-Za-z0-9_-]+$")

CAMPOS_LEIDOS_NO_ENVIADOS = ("name", "createTime", "updateTime", "tokenCount",
                             "state", "satisfiesPzi", "satisfiesPzs")


class PipelineError(RuntimeError):
    """Fallo que detiene el paso en curso."""


# ── Sobre de respuesta ───────────────────────────────────────────────────────

def step_result(status, log, data=None):
    """El mismo sobre para los nueve puntos de entrada.

    El panel espera exactamente esta forma: `status` para decidir si el paso
    avanza, `log` para llenar la caja de registro, `data` para pintar lo
    específico de cada pantalla.
    """
    return {"status": status, "log": log, "data": data or {}}


def _emit(log, on_log, linea):
    """Añade una línea al registro y la emite en el momento.

    El registro se ve llenar una caja de tamaño fijo mientras el paso corre,
    así que no puede construirse entero y devolverse al final. El transporte
    —respuesta única o streaming— lo decide quien llama; aquí solo se avisa
    de cada línea según ocurre.
    """
    log.append(linea)
    if on_log:
        on_log(linea)
    return linea


def _ahora():
    return datetime.now(timezone.utc)


def _slug(valor):
    """Nombre de archivo a partir de un displayName, estable y sin sorpresas."""
    normalizado = unicodedata.normalize("NFKD", valor or "")
    ascii_only = normalizado.encode("ascii", "ignore").decode("ascii")
    limpio = re.sub(r"[^A-Za-z0-9]+", "_", ascii_only).strip("_").lower()
    return limpio or "sin_nombre"


def _clave_de_version(item):
    """Identifica una versión sin confundirla con la de otro contenedor.

    `flows/A/versions/1` y `playbooks/B/versions/1` son dos versiones distintas
    con el mismo número. La clave es `<contenedor>/<número>`.
    """
    partes = (item.get("name") or "").split("/")
    return f"{partes[-3]}/{partes[-1]}" if len(partes) >= 3 else _cx_id_de(item)


def _cx_id_de(item):
    """El identificador que asigna CX, extraído de su ruta completa."""
    return (item.get("name") or "").rsplit("/", 1)[-1]


# ── Contexto: de project + agent a todo lo demás ─────────────────────────────

class Contexto:
    """Todo lo que un paso necesita saber de su destino.

    Se construye en el momento de actuar, no se hereda de un paso anterior:
    cada paso recalcula en fresco contra el estado real de CX y del
    repositorio, así que no hay foto guardada que pueda estar desincronizada.
    """

    def __init__(self, project, agent_id, client=None, gh=None):
        if not project or not agent_id:
            raise ValueError(
                "Todo paso exige project y agent_id explícitos — no hay "
                "valores por defecto."
            )
        self.project = project
        self.agent_id = agent_id
        self.store = client or store.get_client()
        try:
            mapeo = store.get_agent_mapping(self.store, project, agent_id)
        except store.MappingNotFound:
            # Con el repositorio del proyecto hay dos ausencias distintas y la
            # salida de cada una es otra: si el proyecto no está vinculado hace
            # falta la herramienta; si lo está, al agente solo le falta su rama
            # de trabajo, y eso se resuelve con el botón del Paso 1. Mandar a la
            # herramienta a quien solo necesita el botón manda a vincular otra
            # vez un repositorio que ya está vinculado.
            try:
                store.get_project_mapping(self.store, project)
            except store.MappingNotFound:
                raise
            raise store.MappingNotFound(
                f"El agente {agent_id} todavía no tiene rama de trabajo en el "
                f"repositorio del proyecto {project}. Dale de alta desde el "
                f"Paso 1 — el repositorio ya está vinculado, solo falta su rama."
            ) from None
        self.region = mapeo["region"]
        self.carpeta_raiz = mapeo.get("carpeta_raiz", "definitions")
        self.repo = mapeo["repo"]
        self.rama = mapeo["rama"]
        self.rama_principal = mapeo.get("rama_principal", "main")
        self.gh = gh or GitHubAppClient(self.repo)
        self._agente_slug = None

    @property
    def agente_slug(self):
        """Nombre legible del agente, para la carpeta del repositorio.

        Se pide a CX la primera vez que hace falta y se guarda en el contexto:
        solo lo necesita el Paso 2, y pedirlo siempre añadiría una llamada a
        todos los demás.
        """
        if self._agente_slug is None:
            respuesta = cx.api_get(self.project, self.region, self.parent)
            nombre = (respuesta.json().get("displayName", "")
                      if respuesta.status_code == 200 else "")
            self._agente_slug = _slug(nombre) or self.agent_id
        return self._agente_slug

    @property
    def parent(self):
        return cx.build_parent(self.project, self.region, self.agent_id)


# ── Lectura del repositorio ──────────────────────────────────────────────────

def cargar_repositorio(contexto, on_log=None, log=None):
    """Todos los YAML del repositorio, agrupados por el `tipo` que declaran.

    Un YAML sin bloque `metadata` no es un resource del pipeline: se ignora.
    Los resources se declaran de forma explícita al crearlos, así que la
    ausencia del bloque no es un error que haya que perseguir — hay YAML en el
    repositorio que nunca fueron resources (taxonomías, configuraciones de
    scoring, specs OpenAPI).

    **El repositorio es del proyecto, no del agente**, así que contiene los
    archivos de todos sus agentes. Lo que devuelve en `por_tipo` es solo lo del
    agente de este contexto; el resto se cuenta aparte:

      `otros_agentes`  — pertenecen a otro agente del mismo proyecto. No son un
                         problema: son el motivo de que el repositorio se
                         comparta.
      `sin_agente`     — tienen cabecera pero no dicen de quién son. No pueden
                         aplicarse en ningún agente y no aparecerían en ninguna
                         vista, así que se cuentan explícitamente: es el único
                         momento que lee el repositorio entero antes de
                         repartirlo por agente.
    """
    log = log if log is not None else []
    commit_sha = contexto.gh.branch_head(contexto.rama)
    # Todo el repositorio en una petición, no una por archivo. Con el
    # repositorio compartido entre los agentes de un proyecto, leer blob a
    # blob crece con cada agente que se añade y agota el límite de la API.
    archivos = contexto.gh.read_repo_files(commit_sha)

    recursos = {tipo: {} for tipo in RESOURCE_TYPES}
    sin_cx_id = []
    sin_agente = []
    otros_agentes = []
    duplicados = []
    ignorados = 0
    vistos = {}   # (agente, tipo, cx_id) -> ruta

    for ruta, crudo in archivos.items():
        try:
            documento = yaml.safe_load(crudo)
        except yaml.YAMLError as error:
            raise PipelineError(
                f"{ruta} no es YAML válido: {error}"
            ) from error

        metadata = payloads.read_metadata(documento)
        if not metadata:
            ignorados += 1
            continue

        tipo = metadata.get("tipo")
        if tipo not in RESOURCE_TYPES:
            raise PipelineError(
                f"{ruta} declara tipo '{tipo}', que no existe. "
                f"Tipos válidos: {', '.join(sorted(RESOURCE_TYPES))}."
            )

        agente = metadata.get("agente")
        entrada = {
            "ruta": ruta,
            "documento": documento,
            "tipo": tipo,
            "padre": metadata.get("padre"),
            "agente": agente,
            "display_name": documento.get("displayName", ""),
        }

        if not agente:
            # Sin dueño: no se puede aplicar en ningún agente, y filtrando por
            # agente desaparecería de todas las vistas sin dejar rastro.
            sin_agente.append(entrada)
            continue

        cx_id = metadata.get("cx_id")

        # La clave lleva el agente porque CX reutiliza los mismos
        # identificadores en todos: verificado con dos agentes reales del mismo
        # proyecto — su Default Start Flow y su Default Welcome Intent
        # comparten cx_id. Sin el agente en la clave, la defensa de duplicados
        # saltaría el primer día con los resources que CX crea solo por existir.
        if cx_id:
            clave = (agente, tipo, cx_id)
            if clave in vistos:
                duplicados.append(
                    f"{tipo}/{cx_id} del agente {agente}: "
                    f"{vistos[clave]} y {ruta}"
                )
                continue
            vistos[clave] = ruta

        if agente != contexto.agent_id:
            otros_agentes.append(entrada)
            continue

        if not cx_id:
            sin_cx_id.append(entrada)
            continue
        entrada["cx_id"] = cx_id
        recursos[tipo][cx_id] = entrada

    if duplicados:
        # Duplicar un archivo para crear una variante es natural; olvidarse de
        # vaciar el cx_id deja dos YAML reclamando el mismo resource de CX, y
        # el último en aplicarse gana sin que nadie lo note.
        raise PipelineError(
            "Hay archivos distintos del mismo agente con el mismo tipo y "
            "cx_id — vacía el cx_id del que sea nuevo:\n  "
            + "\n  ".join(duplicados)
        )

    _emit(log, on_log,
          f"✓ {contexto.rama} · commit {commit_sha[:7]} · "
          f"{len(archivos)} archivos YAML")
    if ignorados:
        _emit(log, on_log,
              f"· {ignorados} YAML sin bloque metadata — no son resources")
    if otros_agentes:
        _emit(log, on_log,
              f"· {len(otros_agentes)} archivos de otros agentes del proyecto")
    if sin_agente:
        _emit(log, on_log,
              f"⚠ {len(sin_agente)} archivos con cabecera pero sin agente: no "
              f"pueden aplicarse en ninguno. Escribe `agente` en su metadata")

    return {"por_tipo": recursos, "sin_cx_id": sin_cx_id,
            "sin_agente": sin_agente, "otros_agentes": otros_agentes,
            "commit": commit_sha, "total_archivos": len(archivos)}, log


# ── Lectura de CX ────────────────────────────────────────────────────────────

def _listar_tipo(contexto, tipo, padres):
    spec = RESOURCE_TYPES[tipo]

    if spec.get("singular"):
        respuesta = cx.api_get(contexto.project, contexto.region, contexto.parent)
        if respuesta.status_code != 200:
            raise PipelineError(
                f"GET del agente falló: {respuesta.status_code} "
                f"{respuesta.text[:200]}"
            )
        return [respuesta.json()]

    if spec.get("padres"):
        items = []
        for tipo_padre, clave in spec["padres"]:
            for padre in padres.get(tipo_padre, []):
                items.extend(cx.list_all_pages(
                    contexto.project, contexto.region,
                    f"{padre['name']}/{spec['api']}", clave,
                ))
        return items

    if spec.get("padre"):
        items = []
        for padre in padres.get(spec["padre"], []):
            items.extend(cx.list_all_pages(
                contexto.project, contexto.region,
                f"{padre['name']}/{spec['api']}", spec["key"],
            ))
        if spec.get("tambien_en_agente"):
            items.extend(cx.list_all_pages(
                contexto.project, contexto.region,
                f"{contexto.parent}/{spec['api']}", spec["key"],
            ))
        return items

    return cx.list_all_pages(
        contexto.project, contexto.region,
        f"{contexto.parent}/{spec['api']}", spec["key"],
    )


def inventariar_cx(contexto, on_log=None, log=None, tipos=None):
    """Foto del borrador del agente: los 13 tipos, agrupados por tipo y cx_id.

    Lee el borrador, no lo que ven los usuarios. Es una foto de ese instante,
    no una suscripción: si el agente cambia después, hay que repetir el paso.

    `tipos` acota qué se lee. Lo usa la herramienta de desplegar un resource
    suelto, que solo necesita su propio tipo y el padre del que cuelga — y
    que, al no pedir nunca `environment`, tampoco llega a construir una URL de
    entorno ni para leerla.
    """
    log = log if log is not None else []
    inventario = {}
    padres = {}
    desglose = []

    pedidos = tipos or list(RESOURCE_TYPES)
    # Los tipos que cuelgan de otro necesitan a su padre listado antes.
    orden = [t for t in ("flow", "playbook") if t in pedidos] + [
        t for t in pedidos if t not in ("flow", "playbook")
    ]

    for tipo in orden:
        items = _listar_tipo(contexto, tipo, padres)
        padres[tipo] = items
        # Las versiones se numeran **dentro de cada contenedor**: el flow tiene
        # su v1 y el playbook la suya. Guardarlas por el número a secas hacía
        # que una pisara a la otra en silencio — hoy el flow iba por la 152 y el
        # playbook por la 109, así que el solape era cuestión de tiempo. Su
        # clave lleva el contenedor delante. No afecta al emparejamiento con el
        # repositorio: las versiones no entran en el reparto.
        inventario[tipo] = {
            (_clave_de_version(item) if tipo == "version" else _cx_id_de(item)): item
            for item in items
        }
        if items:
            desglose.append(f"{tipo} ({len(items)})")

    total = sum(len(items) for items in inventario.values())
    _emit(log, on_log, "✓ " + " · ".join(desglose))
    _emit(log, on_log, f"✓ {total} resources en el borrador")
    return inventario, total, log


# ── Emparejamiento ───────────────────────────────────────────────────────────

def es_nativo(tipo, item):
    """Herramientas que trae la plataforma: existen en CX y no se pueden traer.

    Sin este filtro aparecerían en "solo en CX" en cada deploy para siempre.
    """
    return tipo == "tool" and item.get("toolType") == "BUILTIN_TOOL"


# Ni las versiones ni los entornos son definiciones: son **estado de
# despliegue** que crea y mueve el Paso 5. No tienen archivo en el repositorio
# ni deberían tenerlo, así que no entran en el reparto de tres grupos — si
# entraran, cada uno aparecería como "solo en CX" y el Paso 2 ofrecería
# traérselo, que no significa nada. Se inventarían igual porque el Paso 5 y el
# desplegable de versiones los necesitan; simplemente se cuentan aparte.
#
# El entorno se añadió después de verlo: un agente recién dado de alta enseñaba
# «solo en CX: 2» con el tool nativo y el entorno `production` dentro, y ese
# contador ya no podía bajar de 2 nunca. Un contador que siempre marca lo mismo
# no dice nada; el valor de este es que llegue a cero, para que el día que
# marque uno signifique que apareció algo que nadie puso.
#
# Y traerlo era peor que inútil: `environment` está en `TIPOS_NO_DESPLEGABLES`,
# así que el YAML resultante no lo podría aplicar el Paso 3 jamás — un archivo
# muerto en el repositorio, ofrecido por el propio panel.
TIPOS_FUERA_DEL_REPARTO = ("version", "environment")


def describir_lo_retirado(borrados, solo_repo, contexto=None):
    """Dice cómo se llama, y si su archivo sigue vivo, lo que producción sirve
    y el borrador ya no tiene.

    **El nombre.** Sale normalmente de la foto congelada de la versión que el
    entorno fija. No sirve en el caso más frecuente: borrar un contenedor en la
    consola de CX **se lleva por delante sus versiones**. Verificado contra la
    API — el contenedor contesta `404` y su lista de versiones contesta `200`
    con la lista vacía. El entorno se queda apuntando a algo evaporado, y no
    hay foto de la que leer nada. Queda el archivo del repositorio, que todavía
    lo describe. Sin esto el aviso decía «Playbook · ced5bc20-ac6e-4126-b3d5-
    118a981f7638»: exacto e inútil, porque nadie decide sobre un identificador.

    Solo rellena el nombre que falta: si la versión lo dio, ese gana — es el de
    lo que producción sirve de verdad.

    Y hay una tercera fuente, que es la que salva el caso peor. Borrar en la
    consola de CX y dejar el archivo hace que el Paso 3 recree el resource con
    un identificador **nuevo**, y que escriba ese identificador nuevo en la
    cabecera del archivo. A partir de ahí el viejo no está en ningún sitio: ni
    en CX, ni en sus versiones, ni en el archivo que antes lo describía. Pero
    el pipeline lleva un registro de cada resource que escribe, con su nombre,
    y ese registro no se borra con nada de eso. Es la única memoria de cómo se
    llamaba lo que producción sigue sirviendo.

    Si tampoco ahí hay nada —un resource que el pipeline nunca escribió— se
    queda el identificador: inventar un nombre sería peor que no darlo.

    **La ruta.** Es la que decide qué va a pasar después, y son dos finales
    opuestos. Si el archivo sigue en el repositorio, el Paso 3 vuelve a crear
    el resource en CX — y CX le asigna un identificador **nuevo**, así que no
    es el que volvió: es otro con el mismo nombre, y el puntero viejo se queda
    en producción señalando a nada. Si el archivo tampoco está, el borrado es
    completo. Sin este dato el aviso solo contaba una de las dos historias, y
    quien borra en la consola de CX se lleva la sorpresa una pasada después.

    Modifica `borrados` en el sitio y no devuelve nada.
    """
    del_repositorio = {
        (f.get("tipo"), f.get("cx_id")): f
        for f in solo_repo or ()
    }
    for borrado in borrados or ():
        archivo = del_repositorio.get(
            (borrado.get("tipo"), borrado.get("cx_id"))) or {}
        if not borrado.get("display_name"):
            borrado["display_name"] = archivo.get("display_name", "")
        if not borrado.get("display_name") and contexto is not None:
            # Nunca propaga un fallo: sin este nombre el aviso sale con el
            # identificador, que es feo pero cierto. Parar el Paso 1 porque
            # Firestore no conteste sería cambiar un aviso pobre por ninguno.
            try:
                registro = store.get_resource_record(
                    contexto.store, contexto.project, contexto.agent_id,
                    borrado.get("tipo"), borrado.get("cx_id")) or {}
                borrado["display_name"] = registro.get("display_name") or ""
            except Exception:
                pass
        # `None` es «tampoco está en el repositorio», que es una respuesta, no
        # un dato que falte: es la diferencia entre un borrado completo y uno
        # que el Paso 3 va a deshacer.
        borrado["ruta"] = archivo.get("ruta")


def emparejar(inventario, repositorio):
    """Reparte todo lo leído en los tres grupos que pinta el Paso 1.

    Ningún resource cae en dos grupos: la suma de los tres cuadra con lo
    leído, que es uno de los criterios de validación del paso.

    Los nativos de la plataforma salen aparte, en `nativos`: existen en CX,
    no se pueden traer, y contarlos entre lo pendiente dejaba el número
    clavado en 1 para siempre.
    """
    emparejados, solo_cx, solo_repo, nativos = [], [], [], []

    for tipo, items in inventario.items():
        if tipo in TIPOS_FUERA_DEL_REPARTO:
            continue
        del_repo = repositorio["por_tipo"].get(tipo, {})
        for cx_id, item in items.items():
            fila = {
                "tipo": tipo,
                "cx_id": cx_id,
                "display_name": item.get("displayName", ""),
                "name": item.get("name", ""),
            }
            if cx_id in del_repo:
                emparejados.append({**fila, "ruta": del_repo[cx_id]["ruta"]})
            elif es_nativo(tipo, item):
                # Fuera del reparto, no marcado dentro de él. Estaba en "solo
                # en CX" con la etiqueta «no se puede traer», y eso dejaba el
                # contador clavado en 1 en todos los agentes para siempre. Un
                # número que nunca puede bajar a cero no informa de nada; el
                # valor de este es justo que llegue a cero, para que el día que
                # marque uno signifique que apareció algo que nadie puso.
                #
                # No se pierde nada: son iguales en todo agente de CX, no se
                # pueden traer ni desplegar ni versionar, y verlos no habilita
                # ninguna acción. Quien quiera consultarlos los tiene en la
                # consola, que es donde se gestionan.
                nativos.append(fila)
            else:
                solo_cx.append({**fila, "nativo": False, "traible": True})

    for tipo, del_repo in repositorio["por_tipo"].items():
        if tipo in TIPOS_FUERA_DEL_REPARTO:
            continue
        for cx_id, entrada in del_repo.items():
            if cx_id not in inventario.get(tipo, {}):
                solo_repo.append({
                    "tipo": tipo, "cx_id": cx_id, "ruta": entrada["ruta"],
                    "display_name": entrada["display_name"],
                    "motivo": "cx_id fantasma",
                })

    for entrada in repositorio["sin_cx_id"]:
        solo_repo.append({
            "tipo": entrada["tipo"], "cx_id": None, "ruta": entrada["ruta"],
            "display_name": entrada["display_name"], "motivo": "sin cx_id",
        })

    return {"emparejados": emparejados, "solo_cx": solo_cx,
            "solo_repo": solo_repo, "nativos": nativos}


# ── Diff ─────────────────────────────────────────────────────────────────────

def calcular_diff(contexto, inventario, repositorio, eliminar=()):
    """Lo que el repositorio va a escribir en el agente.

    Solo crear y modificar. Un resource que existe en el agente y no en el
    repositorio no genera un borrado: eso se decide en el Paso 2 y llega aquí
    ya decidido, en `eliminar`.

    Cada modificación se marca además si es un **conflicto**: el repositorio
    cambió y CX también, por separado. Ver `_marcar_conflicto`.
    """
    operaciones = []
    auditoria = _auditoria_previa(contexto)

    for tipo, del_repo in repositorio["por_tipo"].items():
        if tipo in TIPOS_NO_DESPLEGABLES:
            continue
        remotos = inventario.get(tipo, {})
        for cx_id, entrada in del_repo.items():
            local = payloads.comparable_local(tipo, entrada["documento"])
            # Los de TIPOS_SOLO_A_MANO no generan operación. Se siguen
            # comparando, pero eso lo hace `avisos_a_mano`, que es a quien
            # pregunta el panel.
            if tipo in TIPOS_SOLO_A_MANO:
                continue
            if cx_id not in remotos:
                operaciones.append(_operacion("POST", tipo, cx_id, entrada, local))
            elif payloads.differs(remotos[cx_id], local):
                operacion = _operacion(
                    "PATCH", tipo, cx_id, entrada, local,
                    remote_name=remotos[cx_id].get("name"),
                )
                _marcar_conflicto(operacion, remotos[cx_id], auditoria)
                operacion["movimiento"] = _quien_se_movio(
                    operacion, remotos[cx_id], auditoria
                )
                operaciones.append(operacion)

    for entrada in repositorio["sin_cx_id"]:
        if entrada["tipo"] in TIPOS_NO_DESPLEGABLES:
            continue
        if entrada["tipo"] in TIPOS_SOLO_A_MANO:
            continue
        local = payloads.comparable_local(entrada["tipo"], entrada["documento"])
        operaciones.append(_operacion(
            "POST", entrada["tipo"], None, entrada, local
        ))

    operaciones.extend(
        _operaciones_de_borrado(inventario, repositorio, eliminar)
    )
    # Y lo que está en CX sin que ningún archivo lo reclame, como candidato.
    pedidos = {(p.get("tipo"), p.get("cx_id")) for p in eliminar or ()}
    operaciones.extend(
        _huerfanos_borrables(inventario, repositorio, pedidos)
    )

    operaciones.sort(key=lambda op: (
        DEPLOY_ORDER.index(op["tipo"]) if op["tipo"] in DEPLOY_ORDER
        else len(DEPLOY_ORDER)
    ))
    return operaciones


def avisos_a_mano(inventario, repositorio):
    """Los resources que el pipeline compara pero no escribe: ver TIPOS_SOLO_A_MANO.

    Se calcula aparte del diff a propósito. `calcular_diff` devuelve lo que se va
    a APLICAR, y meter aquí dentro cosas que no se aplican es cómo se cuela una
    escritura por accidente el día que alguien recorra la lista sin mirar.

    Lo que devuelve es informativo: el panel lo enseña para que sepas que ese
    tool difiere y hay que subirlo a mano.
    """
    avisos = []
    for tipo in TIPOS_SOLO_A_MANO:
        del_repo = repositorio["por_tipo"].get(tipo, {})
        remotos = inventario.get(tipo, {})
        for cx_id, entrada in del_repo.items():
            local = payloads.comparable_local(tipo, entrada["documento"])
            if cx_id in remotos and not payloads.differs(remotos[cx_id], local):
                continue
            avisos.append({
                "tipo": tipo, "cx_id": cx_id, "ruta": entrada["ruta"],
                "display_name": entrada["display_name"],
                # La misma clave que usa `_operacion`: un consumidor no debería tener
                # que saber de dónde salió la fila para leerla.
                "operacion": "POST" if cx_id not in remotos else "PATCH",
                "motivo": "guarda un secreto que CX no devuelve",
            })
    for entrada in repositorio.get("sin_cx_id", ()):
        if entrada["tipo"] in TIPOS_SOLO_A_MANO:
            avisos.append({
                "tipo": entrada["tipo"], "cx_id": None, "ruta": entrada["ruta"],
                "display_name": entrada["display_name"], "operacion": "POST",
                "motivo": "guarda un secreto que CX no devuelve",
            })
    return avisos


def _operacion(verbo, tipo, cx_id, entrada, local, remote_name=None):
    return {
        "operacion": verbo,
        "tipo": tipo,
        "cx_id": cx_id,
        "ruta": entrada["ruta"],
        "padre": entrada.get("padre"),
        "resource": entrada.get("display_name") or entrada["ruta"],
        "local": local,
        "remote_name": remote_name,
        "sin_version": tipo in TIPOS_SIN_VERSION,
        "conflicto": False,
        "cambio_externo": None,
        # Cuál de los dos lados cambió: "repo", "cx", "ambos" o None si no se
        # sabe. Decide en qué paso se ofrece esta fila. Ver `_quien_se_movio`.
        "movimiento": None,
        # Crear y modificar salen del repositorio: nadie las ofrece, se
        # deducen. Solo los borrados se ofrecen para que alguien decida.
        "candidato": False,
        "result": None,
    }


def huella_resource(item):
    """Resumen estable del contenido de un resource de CX.

    Es el tercer punto de referencia del diff: se guarda tras cada escritura y
    se compara en la siguiente para saber si CX cambió por fuera del pipeline.

    Se hace con el contenido y no con una marca de tiempo del servidor porque
    la API no la da — verificado contra CX real: ni el GET ni el PATCH
    devuelven `updateTime` en ninguno de los tipos. Se excluyen los campos que
    la API gestiona por su cuenta, que cambiarían la huella sin que nadie haya
    tocado nada.
    """
    if not isinstance(item, dict) or not item:
        return None
    comparable = {k: v for k, v in item.items()
                  if k not in CAMPOS_LEIDOS_NO_ENVIADOS}
    serializado = json.dumps(comparable, sort_keys=True, ensure_ascii=False,
                             default=str)
    return hashlib.sha256(serializado.encode()).hexdigest()[:32]


def huella_local(local):
    """Lo mismo, para lo que el repositorio declara de un resource.

    Es el gemelo de `huella_resource`, y existe aparte a propósito: `differs`
    compara **solo los campos que el YAML declara**, así que el payload local
    es un subconjunto del remoto y las dos huellas nunca darían lo mismo
    aunque el repositorio y CX estuviesen de acuerdo.

    Por eso ninguna se compara con la otra. Cada una mide un lado **contra su
    propio pasado** —el repo de ahora contra el repo de la última escritura, CX
    de ahora contra CX de la última escritura— y de ahí sale quién se movió.
    Cruzarlas daría «los dos cambiaron» siempre.
    """
    if not isinstance(local, dict) or not local:
        return None
    serializado = json.dumps(local, sort_keys=True, ensure_ascii=False,
                             default=str)
    return hashlib.sha256(serializado.encode()).hexdigest()[:32]


def _auditoria_previa(contexto):
    """Cómo quedó cada resource la última vez que escribió el pipeline.

    Devuelve un diccionario vacío si no hay contexto o si la consulta falla:
    sin este dato el diff sigue funcionando exactamente como antes, solo deja
    de poder distinguir un conflicto. Que la auditoría no esté disponible no
    puede impedir un deploy.
    """
    if contexto is None or getattr(contexto, "store", None) is None:
        return {}
    try:
        return store.list_resource_records(
            contexto.store, contexto.project, contexto.agent_id
        )
    except Exception:
        return {}


def _marcar_conflicto(operacion, remoto, auditoria):
    """Marca la operación si el repositorio y CX cambiaron por separado.

    El diff solo ve dos estados —repositorio y CX— y con dos no se puede
    distinguir "el repositorio avanzó" de "los dos avanzaron". El tercer punto
    es cómo quedó CX la última vez que escribió el pipeline: si la marca de
    modificación de CX ya no es esa, alguien lo tocó por fuera, típicamente
    editando en la consola.

    No decide nada: marca. Resolver un conflicto en silencio a favor del
    repositorio perdería un cambio hecho a propósito por la otra vía, que es
    exactamente lo que pasaba hasta ahora.

    Sin registro previo no se marca: un resource que el pipeline nunca escribió
    no tiene con qué compararse, y tratarlo como conflicto convertiría el
    primer deploy de cada resource en un aviso.
    """
    registro = auditoria.get((operacion["tipo"], operacion["cx_id"]))
    if not registro or not registro.get("huella_cx"):
        return
    actual = huella_resource(remoto)
    if actual and actual != registro["huella_cx"]:
        operacion["conflicto"] = True
        operacion["cambio_externo"] = {
            "huella_cx_ahora": actual,
            "huella_tras_la_ultima_escritura": registro["huella_cx"],
            "archivo": registro.get("archivo"),
        }


def _quien_se_movio(operacion, remoto, auditoria):
    """Cuál de los dos lados cambió desde la última vez que escribió el pipeline.

    Devuelve `"repo"`, `"cx"`, `"ambos"` o `None`, y es lo que decide **en qué
    paso** se ofrece la fila: lo que se movió en el repositorio se lleva a CX
    (Paso 3), lo que se movió en CX se trae al repositorio (Paso 2), y lo que
    se movió en los dos no puede ir a ninguno sin borrar el trabajo del otro
    lado.

    `None` significa «no se sabe», no «no se movió nada». Pasa con los
    resources escritos antes de que existiera `huella_repo` y con los que el
    pipeline nunca escribió. Se devuelve aparte en vez de adivinar porque las
    dos direcciones no cuestan lo mismo: llevar a CX de más se ve y se corrige,
    traer al repositorio de más **sobrescribe un archivo** y se lleva por
    delante lo que hubiera dentro. Quien lo reciba debe tratarlo como hasta
    ahora — ofrecerlo en el Paso 3 y nunca traerlo solo.
    """
    registro = auditoria.get((operacion["tipo"], operacion["cx_id"]))
    if not registro:
        return None
    previa_cx = registro.get("huella_cx")
    previa_repo = registro.get("huella_repo")
    if not previa_cx or not previa_repo:
        return None

    cx_ahora = huella_resource(remoto)
    repo_ahora = huella_local(operacion["local"])
    if not cx_ahora or not repo_ahora:
        return None

    se_movio_cx = cx_ahora != previa_cx
    se_movio_repo = repo_ahora != previa_repo
    if se_movio_cx and se_movio_repo:
        return "ambos"
    if se_movio_cx:
        return "cx"
    if se_movio_repo:
        return "repo"
    # Difieren pero ninguno se ha movido desde la última escritura: el
    # pipeline los dejó ya distintos. Pasa cuando una escritura falló a medias.
    # No es ninguno de los tres casos y adivinar aquí sería inventar.
    return None


def quien_depende_de(inventario, repositorio, tipo, cx_id):
    """Quién se va con un resource si se borra, y quién se queda roto.

    Son dos cosas distintas y conviene no mezclarlas:

    **Hijos** — cuelgan de él y CX los borra con él. Los examples de un
    playbook desaparecen cuando el playbook desaparece: eso no es un error,
    es lo que tiene que pasar. Pero hay que decirlo, porque «borro un
    playbook» y «borro un playbook y sus once examples» son decisiones
    distintas y desde el panel se ven iguales.

    **Referencias** — lo mencionan desde fuera y se quedan apuntando a nada.
    Un example de otro playbook con un `playbookTransition` hacia este; el
    playbook que lo invoca. CX rechaza el borrado si existen —«Examples/Flows/
    Pages/Playbooks are referencing the playbook»— pero lo dice con una
    excepción de Java cuando ya has pulsado, y sin nombrar ni una.

    Se busca en los dos sitios porque cuentan cosas distintas: el repositorio
    dice qué archivos habría que tocar, y CX qué va a rechazar. Y no cuesta
    ninguna llamada: los dos están leídos desde el principio del paso.
    """
    aguja = str(cx_id)
    hijos, referencias = [], []

    def mira(donde, otro_tipo, otro_id, cuerpo, ruta, nombre, padre):
        if otro_tipo == tipo and otro_id == cx_id:
            return
        # El identificador aparece en el `name` de todo lo que cuelga de él;
        # eso es parentesco, no referencia, y se cuenta aparte.
        sin_name = {k: v for k, v in (cuerpo or {}).items() if k != "name"}
        if padre == cx_id:
            hijos.append({"donde": donde, "tipo": otro_tipo, "cx_id": otro_id,
                          "ruta": ruta, "display_name": nombre})
        elif aguja in json.dumps(sin_name, ensure_ascii=False, default=str):
            referencias.append({"donde": donde, "tipo": otro_tipo, "cx_id": otro_id,
                                "ruta": ruta, "display_name": nombre})

    for otro_tipo, entradas in (repositorio.get("por_tipo") or {}).items():
        for otro_id, entrada in entradas.items():
            doc = entrada.get("documento") or {}
            mira("repositorio", otro_tipo, otro_id, doc, entrada.get("ruta"),
                 entrada.get("display_name", ""),
                 (doc.get("metadata") or {}).get("padre"))

    for otro_tipo, items in inventario.items():
        if not isinstance(items, dict):
            continue
        for otro_id, item in items.items():
            if not isinstance(item, dict):
                continue
            padre = (_padre_id_de(otro_tipo, item)
                     if RESOURCE_TYPES.get(otro_tipo, {}).get("padre") else None)
            mira("CX", otro_tipo, otro_id, item, None,
                 item.get("displayName", ""), padre)

    return {"hijos": hijos, "referencias": referencias}


def _operacion_de_borrado(tipo, cx_id, remoto, candidato=False):
    """Una fila DELETE del plan, con la misma forma que las demás.

    `candidato` distingue las que se ofrecen de las que se han pedido: un
    huérfano aparece en el plan para que alguien decida, y hasta que no se
    marca no se borra nada.
    """
    return {
        "operacion": "DELETE",
        "tipo": tipo,
        "cx_id": cx_id,
        "ruta": None,
        # De quién cuelga, capturado ANTES de borrarlo: después ya no existe
        # en el agente y el Paso 5 no sabría qué versionar.
        "padre": (_padre_id_de(tipo, remoto)
                  if RESOURCE_TYPES[tipo].get("padre") else None),
        "resource": remoto.get("displayName", cx_id),
        "local": None,
        "remote_name": remoto.get("name"),
        "sin_version": tipo in TIPOS_SIN_VERSION,
        # Las mismas claves que pone _operacion(): los dos caminos tienen que
        # producir la misma forma, o el resto del código tendría que acordarse
        # de cuál le falta a cuál.
        "conflicto": False,
        "cambio_externo": None,
        # Un borrado no tiene dirección que averiguar: no viene de ningún lado,
        # lo decide una persona. La clave está igual porque quien lee el plan
        # no sabe de qué constructor salió cada fila, y no debería saberlo.
        "movimiento": None,
        "candidato": candidato,
        "result": None,
    }


def _operaciones_de_borrado(inventario, repositorio, eliminar):
    """Las eliminaciones pedidas explícitamente.

    Cada una se comprueba contra el estado real antes de aceptarla: tiene que
    existir en CX y no tener archivo en el repositorio. Sin esta comprobación,
    el servidor estaría borrando lo que le pidan sin mirar.
    """
    operaciones = []
    for peticion in eliminar or ():
        tipo, cx_id = peticion.get("tipo"), peticion.get("cx_id")
        remoto = inventario.get(tipo, {}).get(cx_id)
        if remoto is None:
            raise PipelineError(
                f"Se pidió borrar {tipo}/{cx_id} y no existe en el agente."
            )
        if cx_id in repositorio["por_tipo"].get(tipo, {}):
            raise PipelineError(
                f"Se pidió borrar {tipo}/{cx_id}, pero tiene archivo en el "
                f"repositorio. Quita antes el YAML."
            )
        operaciones.append(_operacion_de_borrado(tipo, cx_id, remoto))
    return operaciones


def _huerfanos_borrables(inventario, repositorio, ya_pedidos):
    """Lo que está en CX y ningún archivo del repositorio reclama.

    Salen aquí, en el plan, y no como una nota traída del Paso 2. El motivo es
    de coherencia y de memoria a partes iguales:

    - **Coherencia.** El Paso 2 se anuncia como «escribe en el repositorio» y
      ofrecía una salida que escribía en CX, en el paso siguiente. Cada paso
      ofrece ahora solo lo que él mismo hace.
    - **Memoria.** La decisión se tomaba en un paso y se ejecutaba en otro, con
      la nota viviendo en el navegador entre medias. Una recarga la perdía, y
      seis borrados marcados se evaporaron así sin que nadie lo notara.

    Y borrar de CX lo que el repositorio no tiene **es** hacer que CX se
    parezca al repositorio, que es exactamente lo que dice el Paso 3.

    Van marcados como candidatos: aparecer no es lo mismo que aplicarse.
    """
    operaciones = []
    for tipo, items in inventario.items():
        if tipo in TIPOS_NO_DESPLEGABLES or not isinstance(items, dict):
            continue
        del_repo = repositorio["por_tipo"].get(tipo, {})
        for cx_id, item in items.items():
            if not isinstance(item, dict) or cx_id in del_repo:
                continue
            if (tipo, cx_id) in ya_pedidos:
                continue
            # Lo nativo de la plataforma no se borra: no lo creó nadie y
            # ofrecerlo sería ofrecer romper el agente.
            if es_nativo(tipo, item):
                continue
            operaciones.append(
                _operacion_de_borrado(tipo, cx_id, item, candidato=True))
    return operaciones


# ── Escritura en CX ──────────────────────────────────────────────────────────

PADRE_AGENTE = "agente"


def _ruta_padre(contexto, operacion, inventario):
    """Dónde cuelga un resource: del agente, o de su playbook o flow.

    Hay tipos que pueden colgar de las dos cosas — un transition route group
    existe tanto bajo un flow como directamente bajo el agente. Para poder
    distinguirlo, la cabecera dice `padre: "agente"` en ese caso: con el campo
    vacío, "cuelga del agente" y "no cuelga de nada" se escribían igual y el
    resource no se podía crear.
    """
    spec = TIPOS_DESPLEGABLES[operacion["tipo"]]
    if not spec.get("padre"):
        return contexto.parent
    if operacion.get("padre") == PADRE_AGENTE:
        if not spec.get("tambien_en_agente"):
            raise PipelineError(
                f"{operacion['ruta']} declara que cuelga del agente, pero un "
                f"{operacion['tipo']} solo puede colgar de un {spec['padre']}."
            )
        return contexto.parent
    padre_id = operacion.get("padre")
    padre = inventario.get(spec["padre"], {}).get(padre_id)
    if padre is None:
        raise PipelineError(
            f"{operacion['ruta']} declara padre {padre_id}, que no existe en "
            f"el agente como {spec['padre']}."
        )
    return padre["name"]


def _aplicar_operacion(contexto, operacion, inventario):
    # De TIPOS_DESPLEGABLES, no de RESOURCE_TYPES: es lo que hace imposible
    # que una escritura de resource acabe apuntando a un entorno.
    spec = TIPOS_DESPLEGABLES[operacion["tipo"]]

    if operacion["operacion"] == "DELETE":
        respuesta = cx.api_delete(
            contexto.project, contexto.region, operacion["remote_name"]
        )
    elif operacion["operacion"] == "POST":
        padre = _ruta_padre(contexto, operacion, inventario)
        cuerpo = payloads.build_create_body(operacion["tipo"], {
            **operacion["local"], "metadata": {},
        })
        respuesta = cx.api_post(
            contexto.project, contexto.region, f"{padre}/{spec['api']}", cuerpo
        )
    else:
        respuesta = _patch_full_update(contexto, operacion)

    if respuesta.status_code not in (200, 201):
        raise PipelineError(
            f"{operacion['operacion']} {operacion['tipo']}/{operacion['resource']} "
            f"falló: {respuesta.status_code} {respuesta.text[:200]}"
        )
    return cx.resolve_operation(contexto.project, contexto.region, respuesta)


def _patch_full_update(contexto, operacion):
    """GET completo → merge → PATCH sin updateMask.

    En Playbooks es obligatorio: el PATCH con updateMask falla en silencio en
    europe-west1 (CLAUDE.md §3.8). En el resto de tipos es lo correcto por otra
    razón — sin updateMask la API interpreta el body como el objeto entero, así
    que mandar solo los campos del YAML equivale a pedir que borre los demás.

    Environments es la excepción al revés —exige updateMask y sin él responde
    code:3— pero no pasa por aquí: no está en TIPOS_DESPLEGABLES, y el único
    sitio que los escribe es `_apuntar_entorno`, que sí manda la máscara.
    """
    actual = cx.api_get(
        contexto.project, contexto.region, operacion["remote_name"]
    )
    if actual.status_code != 200:
        raise PipelineError(
            f"GET previo al Full Update de {operacion['resource']} falló: "
            f"{actual.status_code} {actual.text[:200]}"
        )
    cuerpo = payloads.build_full_update_body(
        actual.json(), operacion["local"],
        ignore_fields=payloads.ignore_fields_for(operacion["tipo"]),
    )
    return cx.api_patch(
        contexto.project, contexto.region, operacion["remote_name"], cuerpo
    )


def _documento_de(repositorio, ruta):
    """El YAML original de un archivo del repositorio, por su ruta."""
    for entrada in repositorio.get("sin_cx_id", []):
        if entrada["ruta"] == ruta:
            return entrada["documento"]
    for por_tipo in repositorio.get("por_tipo", {}).values():
        for entrada in por_tipo.values():
            if entrada["ruta"] == ruta:
                return entrada["documento"]
    return None


def _guardar_cx_id(contexto, operacion, repositorio, on_log, log, base_sha=None):
    """Escribe en el repositorio el `cx_id` que CX acaba de asignar.

    Es lo que cierra el ciclo del resource. Un resource que nace en el
    repositorio no puede llevar `cx_id`: no existe en ningún sitio hasta que
    se sube, y el id lo asigna CX, nunca nosotros. Si ese id no vuelve al
    archivo, la cabecera se queda incompleta para siempre y el deploy
    siguiente vuelve a tratarlo como inexistente y lo crea otra vez — un
    duplicado por cada pasada, contra la idempotencia de CLAUDE.md §3.4.

    Un commit por resource, no uno para todos: si el paso falla a mitad, los
    ids de los que sí llegaron a crearse ya están guardados y no se pierden.

    Un fallo al guardar **no tumba la operación**: el resource ya existe en CX,
    y decir que el paso falló sería mentir sobre lo que pasó. Se avisa con la
    ruta y el id exactos para poder escribirlo a mano.
    """
    documento = _documento_de(repositorio, operacion["ruta"])
    if documento is None:
        _emit(log, on_log,
              f"⚠ No se encontró {operacion['ruta']} para guardarle el cx_id "
              f"{operacion['cx_id']} — escríbelo a mano en su metadata")
        operacion["cx_id_sin_guardar"] = True
        return base_sha

    metadata = dict(documento.get("metadata") or {})
    metadata["cx_id"] = operacion["cx_id"]
    actualizado = {"metadata": metadata,
                   **{k: v for k, v in documento.items() if k != "metadata"}}

    try:
        commit = contexto.gh.commit_files(
            contexto.rama,
            {operacion["ruta"]: yaml.safe_dump(actualizado, allow_unicode=True,
                                               sort_keys=False)},
            f"chore(cx_id): {operacion['tipo']}/{operacion['resource']} "
            f"creado en CX como {operacion['cx_id']}",
            base_sha=base_sha,
        )
        _emit(log, on_log,
              f"      cx_id guardado en {operacion['ruta']}"
              + (f" · commit {commit[:7]}" if commit else ""))
        return commit or base_sha
    except Exception as error:
        # El resource ya está en CX. Reportar el paso como fallido asustaría
        # más de lo que corresponde: lo que falta es una línea en un archivo.
        _emit(log, on_log,
              f"⚠ {operacion['tipo']}/{operacion['resource']} se creó en CX "
              f"como {operacion['cx_id']}, pero no se pudo guardar el cx_id en "
              f"{operacion['ruta']}: {error}. Escríbelo a mano en su metadata, "
              f"o el próximo deploy lo creará otra vez.")
        operacion["cx_id_sin_guardar"] = True
        return base_sha


def aplicar_operaciones(contexto, operaciones, inventario, repositorio=None,
                        on_log=None, log=None):
    """Aplica en orden y se para en el primer fallo.

    Cada operación queda con su resultado —OK, ERROR o NO_INTENTADO— para que
    un reintento pueda reenviar solo lo que falló y lo que no se llegó a
    intentar, nunca lo que ya salió bien: repetirlo lo escribiría dos veces.
    """
    log = log if log is not None else []
    fallo = False
    # Encadena los commits del cx_id: cada uno parte del anterior en vez de
    # releer la rama, que puede devolver el estado de antes.
    ultimo_commit = None

    for operacion in operaciones:
        etiqueta = f"{operacion['tipo']}/{operacion['resource']}"
        if fallo:
            operacion["result"] = "NO_INTENTADO"
            _emit(log, on_log, f"—     {etiqueta}")
            continue
        try:
            creado = _aplicar_operacion(contexto, operacion, inventario)
            operacion["result"] = "OK"
            _emit(log, on_log, f"OK    {operacion['operacion']} {etiqueta}")
            if operacion["operacion"] == "POST" and creado.get("name"):
                # El id lo acaba de asignar CX. Vuelve al archivo aquí mismo,
                # no al final: si el paso muere después, este ya está a salvo.
                operacion["cx_id"] = _cx_id_de(creado)
                if repositorio is not None and operacion["ruta"]:
                    ultimo_commit = _guardar_cx_id(
                        contexto, operacion, repositorio, on_log, log,
                        base_sha=ultimo_commit)
            if operacion["cx_id"]:
                store.record_resource_write(
                    contexto.store, contexto.project, contexto.agent_id,
                    operacion["tipo"], operacion["cx_id"], operacion["ruta"],
                    display_name=operacion["resource"],
                    operacion=operacion["operacion"],
                    # Cómo queda CX tras esta escritura. Es contra esto contra
                    # lo que el diff siguiente detecta un cambio externo.
                    huella_cx=huella_resource(creado),
                    # Y cómo queda el repositorio: lo que se acaba de mandar es
                    # exactamente lo que el archivo dice ahora mismo.
                    huella_repo=huella_local(operacion["local"]),
                    # De quién cuelga. Al publicar, un resource borrado ya no
                    # está en el agente: sin este dato no habría forma de saber
                    # qué playbook o flow hay que versionar para que el borrado
                    # llegue a producción.
                    padre=operacion.get("padre"),
                )
        except PipelineError as error:
            operacion["result"] = "ERROR"
            operacion["error"] = str(error)
            fallo = True
            _emit(log, on_log, f"ERROR {etiqueta}: {error}")

    return operaciones, fallo, log


# ── Avisos ───────────────────────────────────────────────────────────────────

def avisar_cambio_de_archivo(contexto, operaciones):
    """Avisa si un `cx_id` aparece hoy en un archivo distinto al de la última vez.

    El disparador es siempre el archivo, nunca el nombre: un renombrado
    legítimo —mismo archivo, displayName distinto— no dispara nada. Comparar
    por nombre reintroduciría la fragilidad que el emparejamiento por `cx_id`
    eliminó. Sin este aviso, un `cx_id` copiado de otro repositorio sin vaciar
    se aplicaría en silencio sobre el recurso equivocado.
    """
    avisos = []
    for operacion in operaciones:
        if not operacion.get("cx_id") or not operacion.get("ruta"):
            continue
        anterior = store.get_resource_record(
            contexto.store, contexto.project, contexto.agent_id,
            operacion["tipo"], operacion["cx_id"],
        )
        if anterior and anterior.get("archivo") and \
                anterior["archivo"] != operacion["ruta"]:
            avisos.append({
                "tipo": operacion["tipo"],
                "cx_id": operacion["cx_id"],
                "archivo_antes": anterior["archivo"],
                "archivo_ahora": operacion["ruta"],
                "nombre_antes": anterior.get("display_name"),
                "nombre_ahora": operacion["resource"],
            })
    return avisos


# ── 1 · Inventario ───────────────────────────────────────────────────────────

def step_1_inventory(project, agent_id, client=None, gh=None, on_log=None):
    """Lee el agente, lee el repositorio y empareja. No escribe nada.

    Es la única pantalla que no escribe, y por eso es donde se elige el
    agente: equivocarse aquí no cuesta nada.
    """
    log = []
    contexto = Contexto(project, agent_id, client=client, gh=gh)
    _emit(log, on_log, f"· Comprobando conexión · {project} / {agent_id}")

    respuesta = cx.api_get(contexto.project, contexto.region, contexto.parent)
    if respuesta.status_code != 200:
        raise PipelineError(
            f"No se pudo acceder al agente en {contexto.region}: "
            f"{respuesta.status_code} {respuesta.text[:200]}"
        )
    _emit(log, on_log, "✓ Credenciales válidas · acceso al agente confirmado")

    _emit(log, on_log, "· Leyendo Dialogflow CX")
    inventario, total_cx, _ = inventariar_cx(contexto, on_log, log)

    _emit(log, on_log, "· Leyendo el repositorio")
    repositorio, _ = cargar_repositorio(contexto, on_log, log)

    grupos = emparejar(inventario, repositorio)
    _emit(log, on_log,
          f"✓ Emparejados {len(grupos['emparejados'])} · "
          f"solo en CX {len(grupos['solo_cx'])} · "
          f"solo en el repositorio {len(grupos['solo_repo'])}")

    # El total que tiene que cuadrar con las tres tarjetas es el del reparto,
    # sin las versiones: son fotos del propio pipeline, no definiciones que
    # ningún archivo deba reclamar. Se devuelven aparte para que el panel
    # pueda enseñarlas en su propio desplegable sin mezclarlas con la deriva.
    versiones = len(inventario.get("version", {}))

    # Sin entorno de producción, el Paso 5 no tiene dónde publicar y falla —
    # pero fallaba al final, después de haber recorrido el pipeline entero y de
    # haber escrito ya en el agente. El dato está aquí desde siempre: el
    # inventario lee los entornos junto con todo lo demás. Solo faltaba mirarlo
    # y decirlo en el único sitio donde todavía no cuesta nada arreglarlo.
    tiene_produccion = any(
        item.get("displayName") == ENTORNO_PRODUCCION
        for item in inventario.get("environment", {}).values()
    )
    if not tiene_produccion:
        _emit(log, on_log,
              f"⚠ El agente no tiene un entorno '{ENTORNO_PRODUCCION}'. Créalo "
              f"en la consola de CX — sin él el Paso 5 no puede publicar")

    # Qué distancia hay entre el borrador y lo que producción sirve. Es la misma
    # comparación que usará el Paso 5 para decidir qué versionar, hecha aquí solo
    # para contarlo: si un contenedor va a desaparecer de producción, esto es lo
    # único que lo dice antes de que pase, y el Paso 1 es el sitio donde saberlo
    # todavía no cuesta nada.
    store.save_commit_visto(contexto.store, project, agent_id,
                            repositorio["commit"])

    comparacion = _contenedores_cambiados(contexto, inventario, on_log, log)
    describir_lo_retirado(comparacion["borrados"], grupos["solo_repo"],
                          contexto)
    for borrado in comparacion["borrados"]:
        _emit(log, on_log,
              f"⚠ {borrado['tipo']} «{borrado['display_name'] or borrado['cx_id']}» "
              f"lo sirve producción y ya no está en el borrador — publicar lo "
              f"retira")

    # Cuáles de los emparejados difieren del repositorio. Las tres tarjetas
    # responden a **dónde está** cada cosa, no a **si cambió**: un resource que
    # está en los dos sitios cae en «emparejados» tanto si coincide como si el
    # archivo dice otra cosa, y ahí se vuelve indistinguible.
    #
    # Salió probándolo: un playbook modificado en el repositorio no aparecía
    # por ninguna parte en el Paso 1 —«solo en el repositorio: 1», que era el
    # nuevo— y el cambio solo se veía en el Paso 3, con dos operaciones. Quien
    # mira el Paso 1 concluye que hay un cambio cuando hay dos.
    #
    # Y es un hueco raro, porque el paso ya dice qué difiere frente a
    # **producción**: miraba hacia un lado y no hacia el otro. No cuesta
    # ninguna llamada — el inventario y el repositorio ya están leídos.
    operaciones = calcular_diff(contexto, inventario, repositorio)
    difieren = [
        {"tipo": o["tipo"], "cx_id": o["cx_id"], "ruta": o["ruta"],
         "display_name": o["resource"], "operacion": o["operacion"],
         "conflicto": o["conflicto"],
         # De qué lado vino el cambio, y por tanto en qué paso se resuelve.
         "movimiento": o["movimiento"]}
        for o in operaciones if o["operacion"] == "PATCH"
    ]
    if difieren:
        _emit(log, on_log,
              f"· {len(difieren)} de los emparejados difieren del repositorio "
              f"— el Paso 3 los actualizaría")

    return step_result("ok", log, {
        "tiene_entorno_produccion": tiene_produccion,
        "comparacion_produccion": comparacion,
        # De los emparejados, cuáles dicen algo distinto en el repositorio.
        "difieren_del_repositorio": difieren,
        "project": project,
        "agent_id": agent_id,
        "region": contexto.region,
        "repo": contexto.repo,
        "rama": contexto.rama,
        "commit": repositorio["commit"],
        "total_cx": len(grupos["emparejados"]) + len(grupos["solo_cx"]),
        "total_borrador": total_cx,
        "versiones": versiones,
        "total_archivos": repositorio["total_archivos"],
        "emparejados": grupos["emparejados"],
        "solo_cx": grupos["solo_cx"],
        "solo_repo": grupos["solo_repo"],
        # Los archivos que no dicen de quién son. No entran en las tres
        # tarjetas —no pertenecen a ningún agente— pero tampoco pueden
        # desaparecer: es el único momento que lee el repositorio entero antes
        # de repartirlo, y en cualquier otro punto ya se han filtrado.
        "sin_agente": [
            {"ruta": e["ruta"], "tipo": e["tipo"],
             "display_name": e["display_name"],
             "motivo": "sin campo agente"}
            for e in repositorio["sin_agente"]
        ],
        # Los de otros agentes del proyecto. Se cuentan para que las cifras
        # cuadren, no se enseñan como pendientes de nada.
        "otros_agentes": len(repositorio["otros_agentes"]),
        # Los nativos de la plataforma. Se cuentan para que las cifras cuadren
        # y para poder verlos si se quiere, pero no entran en «solo en CX»: no
        # son algo pendiente de traer, son algo que CX pone y nadie gestiona.
        "nativos": grupos["nativos"],
    })


# ── 2 · Traer al repositorio ─────────────────────────────────────────────────

def _ruta_destino(tipo, item, inventario, agente_slug, raiz="definitions"):
    """Dónde escribe el pull un resource que solo existe en CX.

    La primera carpeta es la del agente. Al pipeline la estructura le da igual
    —empareja por la cabecera, no por la ruta— pero el nombre del archivo sí
    tiene que ser único, y en un repositorio compartido no lo era: verificado
    con dos agentes reales, sus "Default Start Flow" y "Default Welcome Intent"
    caían en la misma ruta y el segundo pisaba al primero.

    Se usa el nombre del agente y no su identificador porque quien abra el
    repositorio tiene que entender qué mira. Si el agente se renombra, la
    carpeta queda desfasada y no pasa nada: la verdad está en la cabecera.

    Los examples van además a una subcarpeta por playbook padre — agruparlos es
    lo que hace navegable una carpeta con decenas de archivos.
    """
    spec = RESOURCE_TYPES[tipo]
    carpeta = spec["carpeta"].replace("definitions", f"{raiz}/{agente_slug}", 1)
    nombre = f"{_slug(item.get('displayName'))}.yaml"
    if tipo == "example":
        padre_id = (item.get("name") or "").split("/playbooks/")[-1].split("/")[0]
        padre = inventario.get("playbook", {}).get(padre_id, {})
        return f"{carpeta}/{_slug(padre.get('displayName'))}/{nombre}"
    return f"{carpeta}/{nombre}"


def _yaml_para_repo(tipo, item, padre_id=None, agente=None):
    """El YAML tal como queda en el repositorio, con su cabecera de metadata.

    Los campos que la API devuelve pero no acepta como entrada se quitan: si
    volvieran en el siguiente deploy, la escritura fallaría.
    """
    cuerpo = {k: v for k, v in item.items()
              if k not in CAMPOS_LEIDOS_NO_ENVIADOS}
    documento = {
        "metadata": {
            "tipo": tipo,
            "padre": padre_id,
            "cx_id": _cx_id_de(item),
            # De qué agente es. El repositorio es del proyecto y lo comparten
            # todos sus agentes, así que sin este campo el archivo no se puede
            # colocar en ninguno.
            "agente": agente,
        },
        **cuerpo,
    }
    return yaml.safe_dump(documento, allow_unicode=True, sort_keys=False)


def _huella_del_archivo(tipo, texto_yaml):
    """La huella del repositorio a partir del texto del archivo, no del objeto.

    Se hace la ida y la vuelta —volcar a YAML y volver a leerlo— porque es lo
    que hará el diff siguiente, que solo tiene el archivo. Calcularla sobre el
    objeto de CX daría otra cosa en cuanto el volcado normalizara algo, y el
    resource saldría como movido en el repositorio nada más traerlo.
    """
    try:
        documento = yaml.safe_load(texto_yaml)
    except yaml.YAMLError:
        return None
    if not isinstance(documento, dict):
        return None
    return huella_local(payloads.comparable_local(tipo, documento))


def _commit_que_dejo_el_pipeline(contexto):
    """El último commit de la rama que el propio pipeline vio o escribió.

    Cada paso vuelve a preguntar la punta de la rama, y eso está bien: el Paso
    2 escribe commits y el Paso 3 tiene que ver lo que se acaba de traer. Lo
    que nadie miraba es si además se movió **por otro sitio**.

    La diferencia importa porque cambia quién decide. Que la rama avance por
    los commits del pipeline es el pipeline funcionando: lo que aparece en el
    plan es lo que se acaba de pedir. Que avance por un empujón de fuera es
    otra cosa — el plan pasa a incluir cambios que quien mira el panel no ha
    visto nunca, y los aplicaría creyendo que aprueba solo lo suyo.

    Se lee del historial de ejecuciones, no de lo que mande el panel: el panel
    puede llevar horas abierto, y preguntarle a él por el estado sería
    preguntárselo a quien tiene la foto más vieja.

    Devuelve `None` si no hay ninguna ejecución con commit anotado — un agente
    recién estrenado, o un historial podado. Sin referencia no se avisa: un
    aviso que salta sin saber es ruido, y el ruido se aprende a ignorar.
    """
    return store.get_commit_visto(contexto.store, contexto.project,
                                  contexto.agent_id)


def _mensaje_del_paso_2(traidos, borrados, agent_id):
    """El mensaje del commit dice lo que el commit hace, en las dos direcciones.

    Un solo commit puede traer y borrar a la vez, y decir solo «traer N» sobre
    un commit que además borra archivos deja el historial mintiendo justo donde
    se va a mirar cuando algo falte.
    """
    partes = []
    if traidos:
        partes.append(f"traer {len(traidos)} resources")
    if borrados:
        partes.append(f"borrar {len(borrados)} archivos sin resource en CX")
    etiqueta = "pull" if traidos and not borrados else (
        "limpieza" if borrados and not traidos else "sync")
    return f"chore({etiqueta}): {' y '.join(partes)} de {agent_id}"


def step_2_pull_to_repo(project, agent_id, traer, borrar=(), client=None,
                        gh=None, on_log=None):
    """Escribe en el repositorio los resources que solo existen en el agente.

    Va antes de aplicar nada a propósito: si primero se completa el
    repositorio, lo que se despliegue después sale de un retrato fiel del
    agente, no de uno con piezas de menos.

    Todo lo que se trae en la misma llamada entra en un único commit — un
    archivo por petición no es atómico y puede dejar el repositorio a medias.
    """
    log = []
    contexto = Contexto(project, agent_id, client=client, gh=gh)

    with store.agent_lock(contexto.store, project, agent_id, "traer al repositorio"):
        inventario, _, _ = inventariar_cx(contexto, on_log, log)
        repositorio, _ = cargar_repositorio(contexto, on_log, log)

        # De qué lado vino cada cambio. Es lo que decide si un resource que ya
        # tiene archivo se puede sobrescribir: solo cuando el que se movió fue
        # CX. No cuesta ninguna llamada — el inventario y el repositorio ya
        # están leídos.
        movimientos = {(o["tipo"], o["cx_id"]): o["movimiento"]
                       for o in calcular_diff(contexto, inventario, repositorio)}

        archivos = {}
        traidos = []
        for peticion in traer or ():
            tipo, cx_id = peticion.get("tipo"), peticion.get("cx_id")
            item = inventario.get(tipo, {}).get(cx_id)
            if item is None:
                raise PipelineError(
                    f"Se pidió traer {tipo}/{cx_id} y no existe en el agente."
                )
            if es_nativo(tipo, item):
                raise PipelineError(
                    f"{tipo}/{cx_id} es nativo de la plataforma y no se puede "
                    f"traer al repositorio."
                )
            if cx_id in repositorio["por_tipo"].get(tipo, {}):
                # Hasta aquí llegaba el paso: un archivo existente no se tocaba
                # nunca, y lo editado en la consola de CX no tenía forma de
                # volver. Ahora se sobrescribe, pero **solo** si el repositorio
                # no se ha movido desde la última escritura del pipeline: si se
                # movieron los dos, traer borraría el trabajo del repositorio,
                # y esa decisión no es de un paso automático.
                if movimientos.get((tipo, cx_id)) != "cx":
                    _emit(log, on_log,
                          f"· {tipo}/{cx_id} ya tiene archivo — se omite")
                    continue
                _emit(log, on_log,
                      f"· {tipo}/{cx_id} se editó en CX — se sobrescribe el "
                      f"archivo")

            padre_id = None
            if RESOURCE_TYPES[tipo].get("padre"):
                padre_id = _padre_id_de(tipo, item)
            ruta = _ruta_destino(tipo, item, inventario, contexto.agente_slug,
                                 contexto.carpeta_raiz)
            archivos[ruta] = _yaml_para_repo(tipo, item, padre_id,
                                             agente=agent_id)
            traidos.append({"tipo": tipo, "cx_id": cx_id, "ruta": ruta,
                            "display_name": item.get("displayName", ""),
                            # Cómo está el resource en CX ahora mismo. Sin
                            # anotarlo, traer un resource dejaría su registro
                            # sin huella y la detección de conflicto quedaría
                            # ciega justo para lo que se acaba de traer.
                            "huella": huella_resource(item),
                            # Y cómo queda el archivo. Se calcula releyendo el
                            # YAML que se acaba de escribir, no el objeto de
                            # CX, porque es exactamente lo que hará el diff
                            # siguiente al cargar el repositorio: si la ida y
                            # la vuelta no dieran lo mismo, el resource
                            # aparecería como movido nada más traerlo.
                            "huella_repo": _huella_del_archivo(
                                tipo, archivos[ruta])})
            _emit(log, on_log, f"✓ {ruta}")

        # Y lo contrario: archivos que describen algo que ya no está en CX.
        #
        # Solo se admiten los de `cx_id fantasma` — tienen cabecera con un
        # identificador que el agente ya no reconoce. Un archivo **sin**
        # `cx_id` es otra cosa: algo recién escrito que todavía no ha subido, y
        # ofrecer borrarlo sería ofrecer tirar el trabajo que se acaba de
        # hacer. Y si el resource sigue vivo en CX se rechaza también: borrar
        # su archivo lo dejaría huérfano y la pasada siguiente propondría
        # traerlo de vuelta, dando vueltas sin que nadie decida nada.
        #
        # Sin esto, borrar en la consola de CX no borraba nada: el archivo
        # sobrevivía y el Paso 3 recreaba el resource con un identificador
        # nuevo. Este es el único sitio del pipeline que escribe en el
        # repositorio, así que es donde tiene que estar.
        borrados_del_repo = []
        for peticion in borrar or ():
            tipo, cx_id = peticion.get("tipo"), peticion.get("cx_id")
            if not cx_id:
                raise PipelineError(
                    f"Se pidió borrar del repositorio un {tipo} sin cx_id. Un "
                    f"archivo sin cx_id no ha llegado nunca a CX: no es un "
                    f"resto de algo borrado, es trabajo sin subir."
                )
            if inventario.get(tipo, {}).get(cx_id) is not None:
                raise PipelineError(
                    f"Se pidió borrar del repositorio {tipo}/{cx_id} y ese "
                    f"resource sigue existiendo en CX. Bórralo primero de CX, "
                    f"o su archivo se quedaría sin dueño."
                )
            entrada = repositorio["por_tipo"].get(tipo, {}).get(cx_id)
            if entrada is None:
                raise PipelineError(
                    f"Se pidió borrar del repositorio {tipo}/{cx_id} y ningún "
                    f"archivo lo reclama."
                )
            archivos[entrada["ruta"]] = None
            borrados_del_repo.append({
                "tipo": tipo, "cx_id": cx_id, "ruta": entrada["ruta"],
                "display_name": entrada.get("display_name", ""),
            })
            _emit(log, on_log, f"✗ {entrada['ruta']} — se borra del repositorio")

        if not archivos:
            _emit(log, on_log, "· Nada que traer ni que borrar")
            return step_result("ok", log,
                               {"traidos": [], "borrados_del_repo": [],
                                "commit": None})

        mensaje = _mensaje_del_paso_2(traidos, borrados_del_repo, agent_id)
        commit = contexto.gh.commit_files(contexto.rama, archivos, mensaje)
        if commit:
            _emit(log, on_log, f"✓ commit {commit[:7]} en {contexto.rama}")
        else:
            _emit(log, on_log, "· Sin cambios reales — no se creó commit")

        for traido in traidos:
            store.record_resource_write(
                contexto.store, project, agent_id, traido["tipo"],
                traido["cx_id"], traido["ruta"],
                display_name=traido["display_name"], operacion="PULL",
                huella_cx=traido["huella"],
                huella_repo=traido["huella_repo"],
            )

        store.save_commit_visto(contexto.store, project, agent_id,
                                commit or repositorio["commit"])
        _emit(log, on_log,
              "Repositorio actualizado — haz `git pull` en local antes de "
              "seguir trabajando")

    resultado = step_result("ok", log, {
        "traidos": traidos, "borrados_del_repo": borrados_del_repo,
        "commit": commit, "repo": contexto.repo, "rama": contexto.rama,
    })
    store.record_run(contexto.store, project, agent_id, 2, "ok", log,
                     resultado["data"])
    return resultado


def _padre_id_de(tipo, item):
    """El cx_id del padre, sacado de la propia ruta del recurso en CX.

    Si el tipo admite colgar directamente del agente y su ruta no menciona
    ningún padre, se declara así explícitamente en vez de dejarlo vacío: con
    el campo vacío no habría forma de saber si cuelga del agente o si el dato
    se perdió, y el resource no se podría volver a crear desde el repositorio.
    """
    spec = RESOURCE_TYPES[tipo]
    segmento = {"playbook": "/playbooks/", "flow": "/flows/"}[spec["padre"]]
    nombre = item.get("name") or ""
    if segmento not in nombre:
        return PADRE_AGENTE if spec.get("tambien_en_agente") else None
    return nombre.split(segmento)[-1].split("/")[0]


# ── 3 · Aplicar en CX ────────────────────────────────────────────────────────

def step_3_apply_to_cx(project, agent_id, aplicar=None, eliminar=(),
                       dry_run=False, only_pending=None, client=None, gh=None,
                       on_log=None):
    """Escribe en el borrador del agente lo que se haya marcado.

    El diff se recalcula aquí, en fresco, contra el estado real de CX y del
    repositorio: el servidor no acepta la lista de operaciones que le mande el
    panel (S1). Lo que llega del panel es solo qué resources se marcaron —
    `aplicar` como lista de {tipo, cx_id}— y qué se decidió borrar en el Paso 2.

    No toca producción ni el repositorio.
    """
    log = []
    contexto = Contexto(project, agent_id, client=client, gh=gh)

    inventario, _, _ = inventariar_cx(contexto, on_log, log)
    repositorio, _ = cargar_repositorio(contexto, on_log, log)
    operaciones = calcular_diff(contexto, inventario, repositorio, eliminar)

    if aplicar is not None:
        # Un resource que aún no existe en CX no tiene id —y es correcto que no
        # lo tenga—, así que lo identifica su archivo. Marcar por (tipo, id)
        # metía a todas las creaciones de un tipo en la misma tupla
        # (tipo, None) y marcar una las aplicaba todas.
        por_id = {(m.get("tipo"), m.get("cx_id")) for m in aplicar
                  if m.get("cx_id")}
        por_ruta = {(m.get("tipo"), m.get("ruta")) for m in aplicar
                    if m.get("ruta")}
        operaciones = [
            op for op in operaciones
            if (op["cx_id"] and (op["tipo"], op["cx_id"]) in por_id)
            or (op["ruta"] and (op["tipo"], op["ruta"]) in por_ruta)
        ]
    elif not dry_run:
        # Sin lista de marcados no se borra ningún candidato. «Aplica todo lo
        # que diga el plan» es una orden razonable para crear y modificar —eso
        # sale del repositorio, que es la fuente— pero un borrado no sale de
        # ningún sitio: lo elige una persona, y una a una.
        operaciones = [op for op in operaciones if not op.get("candidato")]
    if only_pending:
        pendientes = {(p.get("tipo"), p.get("cx_id")) for p in only_pending}
        operaciones = [op for op in operaciones
                       if (op["tipo"], op["cx_id"]) in pendientes]

    avisos = avisar_cambio_de_archivo(contexto, operaciones)
    for aviso in avisos:
        _emit(log, on_log,
              f"⚠ {aviso['tipo']}/{aviso['cx_id']} cambió de archivo: "
              f"{aviso['archivo_antes']} → {aviso['archivo_ahora']}")

    # ¿Se movió la rama por fuera del pipeline desde el paso anterior?
    ultimo_visto = _commit_que_dejo_el_pipeline(contexto)
    rama_movida = None
    if ultimo_visto and ultimo_visto != repositorio["commit"]:
        rama_movida = {"antes": ultimo_visto, "ahora": repositorio["commit"]}
        _emit(log, on_log,
              f"⚠ La rama {contexto.rama} se movió por fuera del pipeline: "
              f"{ultimo_visto[:7]} → {repositorio['commit'][:7]}. Este plan "
              f"incluye lo que haya subido quien la movió, y eso no salió en "
              f"el Paso 1. Revísalo antes de aplicar")

    # Quién se va con cada borrado y quién se queda roto. Se mira aquí, en el
    # plan, porque es el único momento en que todavía no cuesta nada: CX
    # rechaza borrar lo que otros referencian, pero lo dice con una excepción
    # de Java cuando ya has pulsado, sin nombrar ni una de ellas.
    dependencias = []
    for op in operaciones:
        if op["operacion"] != "DELETE":
            continue
        d = quien_depende_de(inventario, repositorio, op["tipo"], op["cx_id"])
        if not d["hijos"] and not d["referencias"]:
            continue
        dependencias.append({"tipo": op["tipo"], "cx_id": op["cx_id"],
                             "resource": op.get("resource"), **d})
        if d["hijos"]:
            _emit(log, on_log,
                  f"· Borrar {op['tipo']}/{op.get('resource')} se lleva "
                  f"{len(d['hijos'])} resources que cuelgan de él")
        if d["referencias"]:
            nombres = ", ".join(sorted({r.get("display_name") or r["cx_id"]
                                        for r in d["referencias"]}))[:110]
            _emit(log, on_log,
                  f"⚠ {op['tipo']}/{op.get('resource')} lo referencian "
                  f"{len(d['referencias'])} resources ({nombres}). CX rechaza "
                  f"borrar lo que otros referencian: quita antes esas "
                  f"referencias o el borrado fallará")

    conflictos = [op for op in operaciones if op["conflicto"]]
    for conflicto in conflictos:
        _emit(log, on_log,
              f"⚠ CONFLICTO en {conflicto['tipo']}/{conflicto['resource']}: "
              f"cambió en el repositorio y también en CX por fuera del "
              f"pipeline. Aplicarlo se lleva por delante el cambio de CX")

    # Lo que se movió en CX no se lleva **a** CX: se trae al repositorio, y eso
    # es el Paso 2. Aplicarlo desde aquí revertiría en silencio lo que alguien
    # escribió en la consola — el fallo que el enrutado viene a cerrar. Que el
    # panel no lo ofrezca es interfaz; esto es lo que lo impide, porque el
    # servidor no se fía de la lista que le manden (S1).
    no_aplicables = [op for op in operaciones
                     if op["movimiento"] in ("cx", "ambos")]
    for op in no_aplicables:
        _emit(log, on_log,
              f"⚠ {op['tipo']}/{op['resource']} no se aplica desde aquí: "
              + ("cambió en los dos sitios por separado — decide cuál "
                 "conservar" if op["movimiento"] == "ambos" else
                 "la última escritura fue en CX — tráelo en el Paso 2"))
    if no_aplicables and not dry_run:
        raise PipelineError(
            f"{len(no_aplicables)} resources no se pueden aplicar desde el "
            f"Paso 3: " + ", ".join(
                f"{op['tipo']}/{op['resource']}" for op in no_aplicables[:5])
            + ". Lo que se editó en CX se trae al repositorio en el Paso 2; lo "
              "que cambió en los dos sitios se resuelve a mano antes de mover "
              "nada."
        )

    sin_version = sorted({op["tipo"] for op in operaciones if op["sin_version"]})
    if sin_version:
        _emit(log, on_log,
              f"⚠ Cambios que no admiten versión ({', '.join(sin_version)}): "
              f"los usuarios los verán en cuanto se apliquen")

    if dry_run:
        _emit(log, on_log, f"[dry-run] Plan de {len(operaciones)} operaciones:")
        for operacion in operaciones:
            _emit(log, on_log,
                  f"  {operacion['operacion']} {operacion['tipo']}/"
                  f"{operacion['resource']}")
        return step_result("ok", log, {
            "operaciones": operaciones, "dry_run": True,
            "avisos_cambio_archivo": avisos, "sin_version": sin_version,
            "conflictos": conflictos, "dependencias_de_borrado": dependencias,
            # Las que difieren pero no van en esta dirección: las de CX se
            # traen en el Paso 2 y las de los dos lados las resuelve una
            # persona. Viajan al panel para que las pinte sin casilla — se ven,
            # pero no se pueden marcar.
            "no_aplicables": no_aplicables,
            # De qué commit salió ESTE plan. Cada paso vuelve a preguntar la
            # punta de la rama, así que el commit del Paso 1 puede no ser el
            # que se acaba de leer aquí. El panel enlaza cada archivo a este
            # commit: si enlazara a la rama —o al commit del Paso 1— podría
            # abrir un contenido distinto del que la tabla describe, que es
            # exactamente el engaño que el enlace venía a evitar.
            "repo": contexto.repo,
            "rama": contexto.rama,
            "commit": repositorio["commit"],
            # `None` cuando la rama está donde el pipeline la dejó.
            "rama_movida": rama_movida,
        })

    if not operaciones:
        _emit(log, on_log, "· Nada que aplicar")
        return step_result("ok", log, {"operaciones": [], "aplicadas": 0,
                                       "fallo": False})

    with store.agent_lock(contexto.store, project, agent_id, "aplicar en CX"):
        resultados, fallo, _ = aplicar_operaciones(
            contexto, operaciones, inventario, repositorio, on_log, log
        )

    _emit(log, on_log,
          "Deploy parcial — el borrador quedó a medias" if fallo
          else "Deploy completado")

    resultado = step_result("error" if fallo else "ok", log, {
        "operaciones": resultados,
        "aplicadas": sum(1 for op in resultados if op["result"] == "OK"),
        "fallo": fallo,
        "avisos_cambio_archivo": avisos,
        "sin_version": sin_version,
        "conflictos": conflictos,
    })
    cabeza = contexto.gh.branch_head(contexto.rama)
    store.save_commit_visto(contexto.store, project, agent_id, cabeza)
    store.record_run(contexto.store, project, agent_id, 3,
                     resultado["status"], log,
                     {"aplicadas": resultado["data"]["aplicadas"],
                      "commit": cabeza})
    return resultado


# ── 4 · Validar tests ────────────────────────────────────────────────────────

def step_4_validate_tests(project, agent_id, resultado, client=None, gh=None,
                          on_log=None):
    """Registra la declaración de quien lo usa. No comprueba ni escribe nada.

    El panel no lanza los tests ni conoce su resultado: los lanza quien lo
    usa, fuera del panel, y aquí solo declara cómo han ido. Es la limitación
    conocida del paso, y está dicha con esas palabras a propósito para que
    nadie confunda el botón con una verificación.

    Devuelve además la huella del borrador en este momento, que el Paso 5
    compara para avisar si el borrador se movió después de declarar los tests.
    """
    log = []
    if resultado not in ("superados", "fallidos"):
        raise ValueError(
            "El resultado de los tests se declara como 'superados' o "
            f"'fallidos'. Recibido: {resultado!r}"
        )
    contexto = Contexto(project, agent_id, client=client, gh=gh)
    inventario, total, _ = inventariar_cx(contexto, on_log, log)
    huella = _huella_borrador(inventario)

    _emit(log, on_log, f"Tests declarados {resultado} · {total} resources en el borrador")
    store.record_run(contexto.store, project, agent_id, 4, "ok", log,
                     {"declarado": resultado, "huella": huella})

    return step_result("ok", log, {
        "declarado": resultado,
        "huella_borrador": huella,
        "avanza": resultado == "superados",
    })


# Lo que NO es el borrador, y por tanto no entra en su huella. Las versiones
# son fotos que crea el Paso 5 y los entornos son punteros que mueve el Paso 5:
# ninguno de los dos es estado editable, y contarlos hacía que **el pipeline se
# invalidara a sí mismo**.
#
# El caso real: el Paso 5 hace tres cosas seguidas —fusionar, versionar,
# apuntar— y murió en la tercera porque el agente no tenía entorno de
# producción. Al reintentar, el gate del Paso 4 abortó diciendo «el borrador se
# movió»: no se había movido, lo que había cambiado eran las tres versiones que
# él mismo acababa de crear. Un Paso 5 a medias quedaba irreintentable
# justamente en el momento más delicado, con la rama ya fusionada.
TIPOS_FUERA_DE_LA_HUELLA = ("version", "environment")


def _huella_borrador(inventario):
    """Marca del estado del borrador, para detectar si se movió después.

    Se construye con el **contenido** de cada resource, no con su fecha de
    modificación: verificado contra la API real, CX no devuelve `updateTime`
    en ningún tipo. Con la fecha, la huella se reducía a la lista de nombres y
    solo cambiaba al añadir o quitar un resource — nunca al modificar uno, que
    es justo el caso que el gate del Paso 5 tiene que detectar.

    Y solo del borrador: versiones y entornos quedan fuera — ver
    `TIPOS_FUERA_DE_LA_HUELLA`.
    """
    marcas = []
    for tipo in sorted(inventario):
        if tipo in TIPOS_FUERA_DE_LA_HUELLA:
            continue
        for cx_id, item in sorted(inventario[tipo].items()):
            marcas.append(f"{tipo}:{cx_id}:{huella_resource(item)}")
    return hashlib.sha256("|".join(marcas).encode()).hexdigest()[:16]


# ── Comparación borrador ↔ producción ────────────────────────────────────────
#
# La segunda comparación del pipeline, y la que no hay que confundir con la
# primera. `calcular_diff` mira **repositorio ↔ borrador** y alimenta los Pasos
# 2 y 3. Esta mira **borrador ↔ lo que el entorno de producción sirve**, y
# alimenta el Paso 5. El borrador es el punto común; cada una mira a un lado.
#
# Por qué existe: hasta ahora el Paso 5 decidía qué versionar leyendo una lista
# de Firestore que solo se rellenaba desde el Paso 3. Un cambio hecho a mano en
# la consola de CX entra en el mismo borrador, pero no deja anotación ninguna:
# la lista salía vacía, no se creaba ninguna versión, y el paso reportaba éxito.
# Fallaba en silencio diciendo que fue bien. Mirando el borrador da igual quién
# hizo el cambio, porque el borrador es el mismo para los dos.

# Los tres contenedores que CX sabe congelar en una versión, y dónde guarda cada
# versión el contenido de su contenedor. Verificado contra la API el 2026-08-11:
#
#   flow      → la versión NO guarda contenido. Sus únicas claves son
#               ['createTime','displayName','name','nluSettings','state'], así
#               que un flow no se puede comparar leyendo su versión. Para eso
#               existe `compareVersions`.
#   playbook  → el LIST de versiones ya devuelve `playbook` y `examples` en
#               línea: comparar no cuesta ninguna llamada extra.
#   tool      → el LIST ya devuelve `tool` en línea: tampoco cuesta ninguna.
CONTENIDO_EN_LA_VERSION = {"flow": None, "playbook": "playbook", "tool": "tool"}

# Hijos que no tienen versión propia y viajan dentro de la de su contenedor. Un
# playbook y sus examples son un solo contenedor a efectos de versión: si cambia
# un example —o se borra— el playbook ha cambiado, y su versión tiene que
# rehacerse. Los hijos de un flow no hacen falta aquí: el contenido que devuelve
# `compareVersions` ya trae sus pages y sus transition route groups dentro.
HIJOS_EN_LA_VERSION = {"playbook": ("example", "examples")}

# Cómo se nombra el borrador en el lenguaje del endpoint de comparación. No es
# una versión que exista: es la forma que tiene CX de decir «el estado editable».
VERSION_BORRADOR = "0"


def _versiones_fijadas(inventario, entorno=ENTORNO_PRODUCCION):
    """Qué versión FIJA el entorno para cada contenedor: {contenedor: versión}.

    **La que el entorno fija, nunca la última creada.** No son lo mismo: se
    puede crear una versión y no llegar a publicarla —el Paso 5 muere entre
    crearla y apuntar el entorno, o alguien la crea a mano en la consola—, y en
    ese momento existe una versión más nueva que la que producción sirve. Una
    comparación que cogiera «la última» concluiría que no hay nada que hacer, y
    el cambio no llegaría nunca a producción: exactamente el mismo fallo
    silencioso que esta comparación viene a corregir, entrando por otra puerta.

    Un agente sin ese entorno devuelve un diccionario vacío en vez de fallar: el
    Paso 1 usa esto solo para informar, y ahí todavía no toca romper nada. Sin
    punteros, todo el borrador sale como pendiente de publicar, que es la
    lectura correcta de un agente que nunca se publicó.
    """
    for item in inventario.get("environment", {}).values():
        if item.get("displayName") != entorno:
            continue
        return {
            config["version"].rsplit("/versions/", 1)[0]: config["version"]
            for config in item.get("versionConfigs", [])
            if config.get("version")
        }
    return {}


def _tipo_de_contenedor(nombre):
    """De qué tipo es un contenedor, leído de su propia ruta en CX.

    El segmento que precede a su id (`/flows/`, `/playbooks/`, `/tools/`) es el
    mismo `RESOURCE_TYPES[tipo]["api"]` que construye esas rutas en el resto del
    archivo, así que traducirlo con esa fuente evita una tabla nueva que se
    desincronice de cómo CX nombra las cosas.
    """
    for tipo in CONTENIDO_EN_LA_VERSION:
        if f"/{RESOURCE_TYPES[tipo]['api']}/" in (nombre or ""):
            return tipo
    return None


def _hijos_en_el_borrador(inventario, tipo, contenedor_id):
    """Los hijos que viajan dentro de la versión del contenedor, por su cx_id."""
    par = HIJOS_EN_LA_VERSION.get(tipo)
    if not par:
        return {}
    tipo_hijo, _ = par
    return {
        cx_id: hijo
        for cx_id, hijo in inventario.get(tipo_hijo, {}).items()
        if _padre_id_de(tipo_hijo, hijo) == contenedor_id
    }


def _hijos_en_la_version(version, tipo):
    """Los mismos hijos, tal como quedaron congelados dentro de la versión.

    La clave puede no venir: CX omite `examples` cuando el playbook no tenía
    ninguno, en vez de devolver una lista vacía. Tratar la ausencia como «cero
    hijos» es lo que hace que añadir el primer example salga como cambio.
    """
    par = HIJOS_EN_LA_VERSION.get(tipo)
    if not par:
        return {}
    _, clave = par
    return {_cx_id_de(hijo): hijo for hijo in (version.get(clave) or [])}


REFERENCIA_EN_TEXTO = re.compile(r"\$\{(PLAYBOOK|TOOL|FLOW):([^}]+)\}")

# Lo que la API devuelve en lugar de un secreto al leerlo. No es un valor: es
# la marca de que no piensa enseñarlo.
SECRETO_OCULTO = "REDACTED"


def _mapa_de_nombres(inventario):
    """De nombre visible a identificador, por tipo. Para resolver referencias."""
    prefijos = {"playbook": "PLAYBOOK", "tool": "TOOL", "flow": "FLOW"}
    mapa = {}
    for tipo, prefijo in prefijos.items():
        for cx_id, item in (inventario.get(tipo) or {}).items():
            if isinstance(item, dict) and item.get("displayName"):
                mapa[(prefijo, item["displayName"])] = cx_id
    return mapa


def _mismo_idioma(valor, nombres):
    """El mismo contenido escrito siempre igual, para poder compararlo.

    CX devuelve **lo mismo de dos formas** según de dónde se lea, y sin
    igualarlo antes la comparación encuentra cambios donde no los hay:

    - Una referencia entre resources sale por nombre en el borrador
      (`${PLAYBOOK:Handoff}`) y resuelta a identificador en la versión
      congelada. Se pasa todo a identificador, que es lo que no cambia si
      alguien renombra el destino.
    - Un secreto sale como `REDACTED` al leer el borrador y entero dentro de la
      versión. Ese campo **no se compara nunca**: la API no enseña el del
      borrador, así que un cambio de clave no es detectable por aquí venga como
      venga. Fingir que se compara es lo que dejaba el tool marcado como
      cambiado para siempre.

    Sin esto, cualquier playbook que mencione a otro salía como distinto de
    producción en cada publicación, y el Paso 5 lo versionaba de nuevo cada vez
    — quemando huecos de un límite que en CX es real (100 por playbook).
    """
    if isinstance(valor, str):
        return REFERENCIA_EN_TEXTO.sub(
            lambda m: "${%s:%s}" % (
                m.group(1), nombres.get((m.group(1), m.group(2)), m.group(2))),
            valor)
    if isinstance(valor, list):
        return [_mismo_idioma(v, nombres) for v in valor]
    if isinstance(valor, dict):
        return {k: (SECRETO_OCULTO if isinstance(v, str) and k == "apiKey"
                    else _mismo_idioma(v, nombres))
                for k, v in valor.items()}
    return valor


def _huella_contenedor(item, hijos, nombres=None):
    """Resumen estable del contenido de un contenedor junto con sus hijos.

    Se apoya en `huella_resource`, que ya excluye los campos que la API gestiona
    por su cuenta (`CAMPOS_LEIDOS_NO_ENVIADOS`). Comparar en crudo haría que
    `createTime` o `tokenCount` sacaran todo como cambiado siempre.

    Y antes de eso, los dos lados se pasan al mismo idioma: ver `_mismo_idioma`.

    Los hijos entran por su identificador y ordenados por él, no por su
    posición: CX no garantiza el orden del LIST, y así la huella no depende de
    en qué orden lleguen. El identificador es el mismo dentro y fuera de la
    versión —verificado contra la API: el example congelado conserva el id que
    tiene en el borrador—, así que un cambio de contenido de un hijo concreto se
    ve, y no solo un cambio en el conjunto.
    """
    nombres = nombres or {}
    marcas = [huella_resource(_mismo_idioma(item, nombres)) or ""]
    for cx_id, hijo in sorted(hijos.items()):
        marcas.append(f"{cx_id}:{huella_resource(_mismo_idioma(hijo, nombres))}")
    return hashlib.sha256("|".join(marcas).encode()).hexdigest()[:32]


def _misma_foto_de_flow(contexto, version_name, flow_name):
    """Compara una versión de flow con el borrador de ese mismo flow.

    Una versión de flow no guarda contenido, así que no se puede comparar
    leyéndola. CX tiene un endpoint hecho justo para esto: `compareVersions`
    contra `versions/0`, que es como nombra el borrador.

    Verificado contra la API: cuando nada ha cambiado, los dos JSON son
    **idénticos byte a byte** —los genera CX con el mismo serializador en los
    dos lados—, así que no hace falta normalizar nada.

    El contenido que devuelve trae el flow, sus pages, sus transition route
    groups y los intents, entity types y webhooks que el flow **referencia**. Un
    cambio en cualquiera de ellos sale por aquí sin tratamiento aparte. Un
    webhook o un entity type que ningún flow referencia no aparece en el
    contenido de ninguno — comprobado creando los dos y viéndolos entrar solo
    después de referenciarlos.

    Es un `POST`, pero no muta nada: solo compara y devuelve las dos fotos.

    Devuelve True, False, o None si la versión ya no existe.
    """
    respuesta = cx.api_request(
        "POST", contexto.project, contexto.region,
        f"{version_name}:compareVersions",
        body={"targetVersion": f"{flow_name}/versions/{VERSION_BORRADOR}"},
    )
    if respuesta.status_code == 404:
        return None
    if respuesta.status_code != 200:
        # Nunca «asumo que no cambió»: dar por bueno un fallo de comparación es
        # publicar a ciegas, que es el defecto que todo esto viene a corregir.
        raise PipelineError(
            f"No se pudo comparar el flow "
            f"{flow_name.rsplit('/', 1)[-1]} con la versión que producción "
            f"sirve: {respuesta.status_code} {respuesta.text[:200]}. No se "
            f"publica sin saber si cambió."
        )
    cuerpo = respuesta.json()
    return (cuerpo.get("baseVersionContentJson")
            == cuerpo.get("targetVersionContentJson"))


def _misma_foto(contexto, inventario, version_name, tipo, contenedor):
    """Si una versión concreta guarda exactamente el borrador de su contenedor.

    Devuelve True, False, o **None si esa versión ya no existe**, que no es lo
    mismo que «distinta»: quien pregunta tiene que poder tratarlo como una
    referencia perdida.

    Es el único criterio de comparación del archivo, y lo usan los dos sitios
    que lo necesitan —qué versionar y qué versión sobrante sigue valiendo—, para
    que no puedan discrepar.
    """
    if tipo == "flow":
        return _misma_foto_de_flow(contexto, version_name, contenedor["name"])

    version = inventario.get("version", {}).get(
        _clave_de_version({"name": version_name})
    )
    congelado = (version or {}).get(CONTENIDO_EN_LA_VERSION[tipo])
    if not isinstance(congelado, dict):
        return None
    # El mapa sale del borrador, que es donde están todos los resources vivos:
    # una referencia por nombre solo puede apuntar a algo que existe ahora.
    nombres = _mapa_de_nombres(inventario)
    return (
        _huella_contenedor(congelado, _hijos_en_la_version(version, tipo), nombres)
        == _huella_contenedor(
            contenedor, _hijos_en_el_borrador(inventario, tipo, _cx_id_de(contenedor)),
            nombres
        )
    )


def _contenedores_cambiados(contexto, inventario, on_log=None, log=None):
    """Qué contenedores difieren de lo que producción sirve ahora mismo.

    Devuelve tres listas, y las tres importan:

      `cambiados` — contenedores del borrador cuyo contenido no coincide con la
                    versión que el entorno fija, **o que no tienen ninguna
                    versión fijada todavía**. Es lo que el Paso 5 versiona.
      `borrados`  — contenedores que el entorno fija y que ya no están en el
                    borrador. Producción los sirve y no existen.
      `iguales`   — el resto. Están para poder afirmar que no se versiona de
                    más, que es lo que sostiene la regla del mínimo consumo de
                    versiones.

    **Se versiona solo lo que difiere, nunca el agente entero.** Los límites de
    versiones vivas de CX son reales —20 por flow, 100 por playbook, 50 por
    tool, el de playbook confirmado reventando en 100 con `FAILED_PRECONDITION`—
    y versionar todo quemaría un hueco en cada contenedor en cada publicación,
    además de publicar trabajo a medias de contenedores que nadie quería
    publicar.

    El coste está acotado por los contenedores **publicados**, no por el tamaño
    del agente: los playbooks y los tools se comparan con lo que el inventario
    ya trajo, y solo los flows fijados cuestan una llamada cada uno.

    Los tipos que CX no versiona (`TIPOS_SIN_VERSION`) no aparecen nunca aquí:
    solo se recorren los tres contenedores de `CONTENIDO_EN_LA_VERSION`. Los
    tools nativos de la plataforma tampoco: no admiten versión, así que
    proponerlos sería proponer una llamada que CX rechaza.

    El orden es estable —por tipo y por identificador— para que dos lecturas del
    mismo estado se puedan comparar entre sí.
    """
    log = log if log is not None else []
    fijadas = _versiones_fijadas(inventario)
    cambiados, iguales, borrados = [], [], []

    for tipo in CONTENIDO_EN_LA_VERSION:
        for cx_id, item in sorted(inventario.get(tipo, {}).items()):
            if es_nativo(tipo, item):
                continue
            fila = {"tipo": tipo, "cx_id": cx_id, "name": item.get("name"),
                    "display_name": item.get("displayName", "")}
            fijada = fijadas.get(item.get("name"))
            if not fijada:
                # Tener versiones y no estar fijado no es estar al día: sin
                # puntero, producción no lo sirve.
                cambiados.append(
                    {**fila, "version_fijada": None,
                     "motivo": "producción todavía no lo sirve"})
                continue
            coincide = _misma_foto(contexto, inventario, fijada, tipo, item)
            if coincide is None:
                cambiados.append(
                    {**fila, "version_fijada": fijada,
                     "motivo": "la versión que el entorno fija ya no existe"})
            elif coincide:
                iguales.append({**fila, "version_fijada": fijada})
            else:
                cambiados.append(
                    {**fila, "version_fijada": fijada,
                     "motivo": "el borrador difiere de lo que producción sirve"})

    en_el_borrador = {
        item.get("name")
        for tipo in CONTENIDO_EN_LA_VERSION
        for item in inventario.get(tipo, {}).values()
    }
    for contenedor, fijada in sorted(fijadas.items()):
        if contenedor in en_el_borrador:
            continue
        tipo = _tipo_de_contenedor(contenedor)
        version = inventario.get("version", {}).get(
            _clave_de_version({"name": fijada})
        )
        congelado = (version or {}).get(CONTENIDO_EN_LA_VERSION.get(tipo) or "")
        borrados.append({
            "tipo": tipo,
            "cx_id": contenedor.rsplit("/", 1)[-1],
            "name": contenedor,
            # El nombre visible sale de la foto congelada cuando la versión
            # todavía existe. Si también la borraron, queda el identificador:
            # decir "" sería más limpio de leer y menos útil de buscar.
            "display_name": (congelado.get("displayName", "")
                             if isinstance(congelado, dict) else ""),
            "version_fijada": fijada,
        })

    if cambiados or borrados:
        _emit(log, on_log,
              f"· Frente a producción · {len(cambiados)} contenedores "
              f"difieren · {len(borrados)} borrados · {len(iguales)} al día")
    return {"cambiados": cambiados, "borrados": borrados, "iguales": iguales}


# ── 5 · Publicar en producción ───────────────────────────────────────────────

def step_5_publish(project, agent_id, version_label,
                   client=None, gh=None, on_log=None):
    """Fusiona, crea la versión y apunta producción a ella, en ese orden.

    El orden no es decorativo: si se promoviera antes de fusionar y el merge
    fallara, producción estaría sirviendo algo cuyo código no está en la rama
    principal, y nadie podría reconstruir después qué está corriendo.

    Versiona solo lo que el diff tocó desde la última publicación (H4), no el
    agente entero: así el tiempo del paso es proporcional al cambio y no al
    tamaño del agente, y no se quema un hueco de versión en cada playbook a
    cada deploy contra un límite de 20.
    """
    log = []
    if not ETIQUETA_VERSION_VALIDA.match(version_label or ""):
        raise ValueError(
            "El nombre de la versión admite letras, dígitos, guiones y guiones "
            f"bajos. Recibido: {version_label!r}"
        )
    contexto = Contexto(project, agent_id, client=client, gh=gh)

    with store.agent_lock(contexto.store, project, agent_id, "publicar en producción"):
        inventario, _, _ = inventariar_cx(contexto, on_log, log)

        # El gate del Paso 4 queda atado al borrador exacto que se aprobó, y
        # atado también a que ese Paso 4 haya declarado "superados" — no basta
        # con que exista una huella, porque quien llama podría haber declarado
        # "fallidos" y aun así traer esa misma huella hasta aquí. Se lee de
        # Firestore, no de un parámetro que confía en quien invoca la función:
        # así nadie puede saltarse el candado con solo omitir un argumento.
        #
        # Salir por aquí no deja nada a medias: es lo primero que se comprueba,
        # antes del merge y antes de crear ninguna versión.
        huella_ahora = _huella_borrador(inventario)
        ultimo_paso_4 = next(
            (r for r in store.list_runs(contexto.store, project, agent_id)
             if r["paso"] == 4),
            None,
        )
        if ultimo_paso_4 is None:
            _emit(log, on_log,
                  "⚠ No se ha declarado ningún resultado de tests para este "
                  "agente. No se publica: vuelve al Paso 4 y declara el "
                  "resultado antes de publicar.")
            return step_result("aborted", log, {
                "fusionado": False, "publicado": False,
                "motivo": "no se ha declarado ningún resultado de tests para este agente",
                "huella_ahora": huella_ahora,
            })
        declarado = (ultimo_paso_4.get("data") or {}).get("declarado")
        if declarado != "superados":
            _emit(log, on_log,
                  f"⚠ Los últimos tests declarados fueron {declarado!r}. No se "
                  "publica: vuelve al Paso 4, valida el borrador actual y "
                  "declara 'superados' antes de publicar.")
            return step_result("aborted", log, {
                "fusionado": False, "publicado": False,
                "motivo": f"los últimos tests declarados fueron {declarado!r}",
                "huella_ahora": huella_ahora,
            })
        huella_al_validar = (ultimo_paso_4.get("data") or {}).get("huella")
        if huella_ahora != huella_al_validar:
            _emit(log, on_log,
                  "⚠ El borrador ha cambiado desde que se declararon los tests. "
                  "No se publica: lo que subiría no es lo que se probó. Vuelve "
                  "al Paso 4, valida el borrador actual y repite.")
            return step_result("aborted", log, {
                "fusionado": False, "publicado": False,
                "motivo": "el borrador se movió después de declarar los tests",
                "huella_al_validar": huella_al_validar,
                "huella_ahora": huella_ahora,
            })

        # Sin entorno de producción no hay dónde publicar, y eso se sabe ahora
        # —el inventario ya está leído— no en el tercer acto.
        #
        # El Paso 1 avisaba de esto desde hace tiempo, pero avisar no bastó:
        # ocurrió de verdad. Se recorrieron los Pasos 2, 3 y 4 con el aviso ya
        # dado, y el Paso 5 lo descubrió **después** de fusionar la rama en la
        # principal y de crear tres versiones. Un aviso cuatro pasos antes de
        # que importe se lee y se olvida; lo que protege es negarse aquí.
        #
        # Y no se crea automáticamente a propósito: el panel despliega, no crea
        # infraestructura. Un entorno nace con las versiones que fija, y elegir
        # esas versiones es una decisión de quien publica, no del paso que las
        # publica.
        if not any(item.get("displayName") == ENTORNO_PRODUCCION
                   for item in inventario.get("environment", {}).values()):
            _emit(log, on_log,
                  f"⚠ Este agente no tiene un entorno llamado "
                  f"'{ENTORNO_PRODUCCION}'. No se publica, y no se ha tocado "
                  f"nada: no se ha fusionado la rama ni se ha creado ninguna "
                  f"versión. Créalo en la consola de Dialogflow CX —el panel "
                  f"despliega, no crea infraestructura— y vuelve a empezar "
                  f"desde el Paso 1.")
            return step_result("aborted", log, {
                "fusionado": False, "publicado": False,
                "motivo": f"el agente no tiene un entorno '{ENTORNO_PRODUCCION}'",
                "falta_entorno_produccion": True,
            })

        # La rama principal de un proyecto puede quedarse apuntando a una de
        # pruebas mientras se construye —es deliberado, para no ensuciar la
        # real—, pero entonces publicar deja el código donde nadie lo mira, y
        # el paso dice "✓ fusionado" igual. Se avisa en CADA publicación, no
        # una vez: el día que esto importe, quien publique no se va a acordar
        # de una nota escrita meses antes.
        if any(m in contexto.rama_principal.lower()
               for m in MARCAS_RAMA_NO_DEFINITIVA):
            _emit(log, on_log,
                  f"⚠ La rama principal de este proyecto es "
                  f"«{contexto.rama_principal}», que no parece la definitiva. "
                  f"El código se fusiona ahí, no en la rama real del "
                  f"repositorio — cámbialo en el registro del proyecto cuando "
                  f"este destino pase a ser de verdad.")

        _emit(log, on_log,
              f"· 1/3 Fusionando {contexto.rama} en {contexto.rama_principal}")
        fusionado, detalle = contexto.gh.merge_branches(
            contexto.rama_principal, contexto.rama,
            f"Publicar {version_label} en producción",
        )
        if not fusionado:
            _emit(log, on_log,
                  f"El merge falló — no se toca producción: {detalle}")
            return step_result("conflict", log,
                               {"fusionado": False, "publicado": False})
        _emit(log, on_log, f"✓ {contexto.rama} → {contexto.rama_principal}")

        # Qué versionar se decide **mirando el borrador**, no recordando lo que
        # escribió el pipeline. Es lo único que hace que un cambio hecho a mano
        # en la consola de CX llegue a producción: entra en el mismo borrador,
        # y comparar el borrador no distingue quién lo puso ahí.
        comparacion = _contenedores_cambiados(contexto, inventario, on_log, log)
        cambiados = comparacion["cambiados"]
        borrados = comparacion["borrados"]

        # Un intento anterior pudo crear las versiones y morir antes de fijar
        # el entorno. Esas versiones existen en CX y no las sirve nadie: si el
        # reintento crea otras, las primeras quedan huérfanas, consumiendo
        # hueco contra el límite por playbook sin que nada las reclame.
        _emit(log, on_log,
              f"· 2/3 Versionando · {len(cambiados)} contenedores difieren de "
              f"lo que producción sirve")
        for borrado in borrados:
            _emit(log, on_log,
                  f"⚠ {borrado['tipo']} «{borrado['display_name'] or borrado['cx_id']}» "
                  f"ya no está en el borrador y producción lo sirve — se retira "
                  f"del entorno")
        reutilizables, faltan = _versiones_reutilizables(
            contexto, inventario, cambiados, on_log, log
        )
        nuevas, fallo = [], False
        if faltan:
            nuevas, fallo = _crear_versiones(
                contexto, cambiados, version_label, on_log, log, solo=faltan,
            )
        versiones = reutilizables + nuevas
        if versiones:
            store.save_inflight_versions(
                contexto.store, project, agent_id, versiones, version_label
            )
        if fallo:
            return step_result("error", log, {
                "fusionado": True, "publicado": False,
                "versiones_creadas": versiones,
            })

        _emit(log, on_log, "· 3/3 Apuntando producción")
        produccion = _buscar_entorno(contexto, inventario, ENTORNO_PRODUCCION)
        anteriores = [c["version"] for c in produccion.get("versionConfigs", [])]
        store.save_previous_versions(
            contexto.store, project, agent_id, anteriores, ENTORNO_PRODUCCION
        )

        # Regla de la cadena completa: el entorno tiene que quedar apuntando a
        # todo, no solo a lo nuevo. Lo que no cambió conserva la versión que ya
        # tenía; lo que cambió estrena la recién creada; lo que ya no está en el
        # borrador sale.
        finales = _combinar_versiones(
            anteriores, versiones, excluir=[b["name"] for b in borrados]
        )
        _apuntar_entorno(contexto, produccion, finales, borrados=borrados)
        if versiones:
            _emit(log, on_log,
                  f"✓ Producción sirviendo {version_label} · "
                  f"{len(versiones)} versiones nuevas · {len(finales)} fijadas")
        else:
            # Anunciar la etiqueta sin haber creado ninguna versión daría a
            # entender que existe. Se llega aquí de dos formas: porque nada
            # difería de lo que producción ya sirve —lo normal cuando se
            # republica sin cambios—, o porque lo aplicado es de tipos que CX no
            # versiona (agent_config, generators, y los webhooks o entity types
            # que ningún flow referencia).
            _emit(log, on_log,
                  "✓ Publicado · no se creó ninguna versión: nada difería de lo "
                  "que producción ya sirve, o lo aplicado es de tipos que CX no "
                  f"versiona ({len(finales)} versiones fijadas)")

        store.clear_inflight_versions(contexto.store, project, agent_id)

        # Publicar nunca borra nada por su cuenta — pedido explícito de Jero
        # (2026-08-10): esta función antes podaba versiones automáticamente
        # al superar el límite, y eso no es lo que se pidió. Ahora solo avisa
        # de qué contenedores se pasaron de su límite y qué versiones se
        # borrarían; borrar de verdad exige una llamada aparte y explícita a
        # `manage_versions(action="delete", version_names=[...])`, que ya
        # releía "en uso" fresco dentro de su propio candado antes de este
        # cambio (fix de esta misma noche) — sigue siendo el único camino de
        # borrado, y sigue exigiendo nombrar cada versión, nunca "todas".
        tocados = [(c["name"], c["tipo"]) for c in cambiados]
        poda_pendiente = _contenedores_sobre_limite(contexto, tocados)
        if poda_pendiente:
            total = sum(len(c["candidatas"]) for c in poda_pendiente)
            _emit(log, on_log,
                  f"⚠ {total} versión(es) en {len(poda_pendiente)} "
                  f"contenedor(es) superan su límite — no se han borrado. "
                  f"Revísalo en «administrar versiones» y bórralas a mano "
                  f"cuando quieras.")

    resultado = step_result("ok", log, {
        "fusionado": True, "publicado": True, "version": version_label,
        "versiones_creadas": versiones, "versiones_anteriores": anteriores,
        "repo": contexto.repo, "rama_principal": contexto.rama_principal,
        "poda_pendiente": poda_pendiente,
        # Qué se publicó y qué se retiró, para que el resultado se pueda
        # contrastar sin volver a leer el agente.
        "contenedores_cambiados": cambiados,
        "contenedores_retirados": borrados,
    })
    store.record_run(contexto.store, project, agent_id, 5, "ok", log,
                     {"version": version_label})
    return resultado


# Límites reales de versiones vivas por contenedor, para la poda automática.
# flow y playbook: documentados por Google (docs.cloud.google.com/dialogflow/
# quotas, 2026-07-29) y el de playbook además confirmado contra CX real —
# reventó exactamente en 100 con FAILED_PRECONDITION. tool no está
# documentado: se midió hasta 77 sin rechazo (el intento se cortó por cuota de
# peticiones por minuto, no por el límite de versiones) y se decidió podar a
# 50 con margen de sobra sobre lo medido, en vez de seguir midiendo más caro.
LIMITE_VERSIONES = {"flow": 20, "playbook": 100, "tool": 50}

# A partir de qué fracción del límite se avisa en el listado, antes de que la
# poda automática del Paso 5 llegue a actuar. 80% deja margen real de reacción
# — para un flow (límite 20) avisa a partir de 16, no a partir de 19 — sin
# ensuciar el listado con contenedores que todavía están lejos de un problema.
UMBRAL_AVISO_LIMITE_VERSIONES = 0.8


def _versiones_en_uso(contexto):
    """Versiones que algún entorno sirve ahora mismo, releído fresco de CX.

    **Nunca de una foto guardada antes.** Se descubrió con una prueba real:
    calcular esto una vez al principio de `step_5_publish` y reutilizarlo más
    tarde para decidir qué podar deja una foto desactualizada si el mismo
    contenedor se republica varias veces seguidas en la misma corrida — y
    **borró una versión que producción tenía fijada de verdad**. Quien llama
    a esto tiene que hacerlo justo antes de decidir qué borrar, no antes: es
    la única forma de que "en uso" signifique lo que CX dice ahora, no lo que
    decía al principio de la función que llama.
    """
    entornos = cx.list_all_pages(
        contexto.project, contexto.region, f"{contexto.parent}/environments",
        "environments",
    )
    return {cf["version"] for entorno in entornos
            for cf in entorno.get("versionConfigs", [])}


def _contenedores_sobre_limite(contexto, tocados):
    """Contenedores tocados en esta publicación que superan su límite de
    versiones — dice cuáles se borrarían y cuáles, pero nunca borra nada.

    **No borra — solo informa.** Hasta el 2026-08-10 esta función sí borraba
    automáticamente al publicar; se retiró por pedido explícito de Jero:
    ningún borrado ocurre nunca sin una acción aparte y consciente suya.
    Borrar de verdad sigue siendo `manage_versions(action="delete", ...)`,
    con `en_uso` releído fresco dentro de su propio candado, exigiendo
    nombrar cada versión — nunca "todas las que sobren".

    `en_uso` se relee aquí mismo mediante `_versiones_en_uso` para que la
    lista de candidatas sea correcta en el momento de mostrarla — aunque,
    al no borrar, ya no hay ninguna ventana de carrera que proteger.
    """
    en_uso = _versiones_en_uso(contexto)
    claves = dict(RESOURCE_TYPES["version"].get("padres") or ())
    resultado = []

    for nombre_padre, tipo in tocados:
        limite = LIMITE_VERSIONES.get(tipo)
        clave = claves.get(tipo)
        if not limite or not clave:
            continue
        vivas = cx.list_all_pages(
            contexto.project, contexto.region, f"{nombre_padre}/versions", clave
        )
        exceso = len(vivas) - limite
        if exceso <= 0:
            continue
        # Más antigua primero. El número de versión no sirve de desempate por
        # sí solo — CX no lo reutiliza tras un borrado, pero createTime es el
        # orden real y es lo único que compara contenedores nunca comparables
        # entre sí (dos v1 de contenedores distintos no son "iguales de viejas").
        candidatas = sorted(
            (v for v in vivas if v["name"] not in en_uso),
            key=lambda v: v.get("createTime") or "",
        )[:exceso]
        resultado.append({
            "nombre_padre": nombre_padre, "tipo": tipo,
            "vivas": len(vivas), "limite": limite,
            "candidatas": [v["name"] for v in candidatas],
        })
    return resultado


def _versiones_reutilizables(contexto, inventario, cambiados, on_log, log):
    """Versiones que un intento anterior creó y no llegó a fijar en el entorno.

    Devuelve (reutilizables, contenedores_que_siguen_faltando).

    Reutilizar lo que sobró evita crear versiones duplicadas y quemar huecos
    contra el límite por playbook. Pero **no basta con que sobren**: hay que
    comprobar dos cosas antes de darlas por buenas, y cada una tapa un camino
    por el que se publicaría algo equivocado sin ningún aviso.

    1. **Que su contenedor siga necesitando versión.** Si ya no difiere de lo
       que producción sirve, esa versión no la pide nadie: fijarla sería
       publicar una foto que nadie pidió. Se deja fuera y se reporta huérfana.

    2. **Que sean una foto del borrador de ahora.** Si el resource se volvió a
       escribir después de crearse la versión, esa versión retrata el borrador
       anterior. Reutilizarla publicaría el cambio antiguo y daría el nuevo por
       publicado — el mismo fallo que todo esto viene a arreglar, entrando por
       otra puerta.

    La segunda comprobación **es la misma comparación de contenido** que decide
    qué versionar, no una regla aparte: una versión sobrante vale si su
    contenido coincide con el borrador actual, y punto. Antes se deducía de
    marcas de tiempo —comparar cuándo se escribió cada pendiente contra cuándo
    se creó la versión—, que era una forma indirecta de preguntar lo mismo y
    dependía de que Firestore tuviera esas marcas. Que la versión ya no exista
    sale del mismo sitio: el inventario lista todas las que hay, así que no
    estar en él **es** no existir, y no cuesta una llamada por versión.

    Lo que no cubran queda como "sigue faltando", y el paso crea solo eso.
    """
    anotadas = store.get_inflight_versions(
        contexto.store, contexto.project, contexto.agent_id
    )
    por_contenedor = {c["name"]: c for c in cambiados}
    necesarios = set(por_contenedor)

    if not anotadas or not anotadas.get("version_names"):
        return [], necesarios

    reutilizables, huerfanas, caducadas, muertas = [], [], [], []

    for nombre in anotadas["version_names"]:
        padre = nombre.rsplit("/versions/", 1)[0]
        contenedor = por_contenedor.get(padre)
        if contenedor is None:
            huerfanas.append(nombre)
            continue
        item = inventario.get(contenedor["tipo"], {}).get(contenedor["cx_id"])
        coincide = (None if item is None else
                    _misma_foto(contexto, inventario, nombre,
                                contenedor["tipo"], item))
        if coincide is None:
            muertas.append(nombre)
        elif coincide:
            reutilizables.append(nombre)
        else:
            caducadas.append(nombre)

    if reutilizables:
        _emit(log, on_log,
              f"· Reutilizando {len(reutilizables)} versiones que un intento "
              f"anterior dejó creadas sin fijar, etiquetadas "
              f"'{anotadas.get('etiqueta')}'")
    for lista, motivo in ((caducadas, "su contenido ya no es el del borrador"),
                          (huerfanas, "su contenedor ya no necesita versión"),
                          (muertas, "ya no existen en el agente")):
        if lista:
            _emit(log, on_log,
                  f"· {len(lista)} versiones del intento anterior no se "
                  f"reutilizan: {motivo}")
    if huerfanas:
        _emit(log, on_log,
              f"⚠ {len(huerfanas)} versiones quedan sin usar en el agente y "
              f"nadie las reclama — bórralas desde el desplegable de versiones")

    cubiertos = {n.rsplit("/versions/", 1)[0] for n in reutilizables}
    return reutilizables, necesarios - cubiertos


def _crear_versiones(contexto, cambiados, etiqueta, on_log, log, solo=None):
    """Crea una versión por cada contenedor que difiere de lo que produce sirve.

    Recibe los contenedores ya calculados: aquí no se decide qué versionar, solo
    se versiona. Quien lo decide es `_contenedores_cambiados`, comparando.

    Registra cada versión con su resultado y se para en el primer fallo, igual
    que el Paso 3. El bucle del pipeline local no lo hacía: si fallaba a mitad,
    lanzaba el error y las versiones ya creadas quedaban huérfanas, sin
    registrar ni limpiar.
    """
    objetivos = sorted((c["name"], c["tipo"]) for c in cambiados)
    if solo is not None:
        objetivos = [o for o in objetivos if o[0] in solo]
    creadas = []

    for nombre_padre, tipo in objetivos:
        cuerpo = {"displayName": etiqueta} if tipo == "flow" else {"description": etiqueta}
        try:
            respuesta = cx.api_post(
                contexto.project, contexto.region, f"{nombre_padre}/versions", cuerpo
            )
            if respuesta.status_code == 404:
                # Los tools que trae la plataforma no son versionables.
                _emit(log, on_log, f"—     {nombre_padre.rsplit('/', 1)[-1]} no versionable")
                continue
            if respuesta.status_code not in (200, 201):
                raise PipelineError(
                    f"POST /versions de {nombre_padre} falló: "
                    f"{respuesta.status_code} {respuesta.text[:200]}"
                )
            creada = cx.resolve_operation(
                contexto.project, contexto.region, respuesta
            )
            creadas.append(creada["name"])
            _emit(log, on_log, f"OK    versión de {nombre_padre.rsplit('/', 1)[-1]}")
        except (PipelineError, cx.ApiError, cx.OperationTimeout) as error:
            _emit(log, on_log, f"ERROR {nombre_padre}: {error}")
            _emit(log, on_log,
                  f"Se pararon las versiones — {len(creadas)} ya creadas, "
                  f"ninguna fijada en ningún entorno")
            return creadas, True

    return creadas, False


def _por_nombre(inventario, tipo):
    return [(item["name"], item) for item in inventario.get(tipo, {}).values()]


def _combinar_versiones(anteriores, nuevas, excluir=()):
    """Une lo que ya estaba fijado con lo recién creado, una versión por padre.

    Sin esto, apuntar solo a lo nuevo dejaría fuera del entorno todo lo que no
    cambió, y el PATCH del entorno falla porque exige la cadena completa.

    `excluir` es lo que hay que **restar**: los contenedores que ya no están en
    el borrador. Sin poder restar, esto solo sabía añadir o mantener, y un
    puntero a algo borrado sobrevivía a cualquier número de publicaciones —
    producción seguía sirviendo una versión que todavía lo contenía, para
    siempre y sin que nada lo dijera.

    El orden es estable —alfabético por nombre de versión— para que dos
    publicaciones seguidas sin cambios escriban exactamente la misma lista.
    """
    excluidos = set(excluir)
    por_padre = {}
    for nombre in list(anteriores) + list(nuevas):
        padre = nombre.rsplit("/versions/", 1)[0]
        if padre in excluidos:
            continue
        por_padre[padre] = nombre
    return sorted(por_padre.values())


def _buscar_entorno(contexto, inventario, display_name):
    for item in inventario.get("environment", {}).values():
        if item.get("displayName") == display_name:
            return item
    raise PipelineError(
        f"El agente no tiene un entorno llamado '{display_name}'. Créalo en la "
        f"consola de CX — el panel despliega, no crea infraestructura."
    )


def _apuntar_entorno(contexto, entorno, version_names, borrados=()):
    """PATCH del entorno con updateMask — el único tipo que lo exige.

    `borrados` solo sirve para explicar un rechazo. Un entorno tiene que incluir
    la versión de **todos los flows alcanzables desde el flow de inicio**
    —documentado por Google: *"Otherwise, an error will be returned"*—, así que
    quitar el puntero de un flow que todavía se alcanza hace que CX rechace el
    PATCH con un mensaje suyo, que no menciona ni qué flow ni por qué. Sin
    traducirlo, publicar fallaría con un error críptico justo en el paso final.
    Un playbook o un tool sí se pueden retirar sin más.
    """
    cuerpo = dict(entorno)
    cuerpo["versionConfigs"] = [{"version": nombre} for nombre in version_names]
    for campo in CAMPOS_LEIDOS_NO_ENVIADOS:
        cuerpo.pop(campo, None)
    def _no_deja_quitar_ese_flow(detalle):
        """Traduce el rechazo, si es que había un flow entre lo que se retira.

        El rechazo llega por dos vías distintas y hay que cubrir las dos: un
        estado HTTP de error, o —lo que ocurre de verdad, medido contra la
        API— un `200` cuya operación falla después con `code:3` y el mensaje
        *"Version must be provided for start resource …"*. Mirar solo el
        estado inicial dejaba el error críptico saliendo por el otro lado, que
        es el mismo patrón del bug de `displayName` en `POST /versions`.
        """
        flows_retirados = [b for b in borrados if b.get("tipo") == "flow"]
        if not flows_retirados:
            return None
        nombres = ", ".join(
            b.get("display_name") or b.get("cx_id") for b in flows_retirados
        )
        return PipelineError(
            f"CX no deja retirar de producción el flow {nombres}: un entorno "
            f"tiene que fijar una versión de todos los flows que se alcanzan "
            f"desde el flow de inicio, y ese todavía se alcanza. Quita antes lo "
            f"que lleva hasta él en el borrador, o déjalo publicado. Respuesta "
            f"de CX: {detalle}"
        )

    respuesta = cx.api_patch(
        contexto.project, contexto.region, entorno["name"], cuerpo,
        params={"updateMask": "versionConfigs"},
    )
    if respuesta.status_code not in (200, 201):
        detalle = f"{respuesta.status_code} {respuesta.text[:200]}"
        raise (_no_deja_quitar_ese_flow(detalle)
               or PipelineError(f"PATCH del entorno falló: {detalle}"))
    try:
        return cx.resolve_operation(contexto.project, contexto.region, respuesta)
    except cx.ApiError as error:
        traducido = _no_deja_quitar_ese_flow(str(error)[:300])
        if traducido is None:
            raise
        raise traducido from error


# ── 6 · Descubrimiento ───────────────────────────────────────────────────────

def discover(project=None, client=None, on_log=None):
    """Rellena los desplegables del panel: proyectos y, si se da uno, agentes.

    Cada agente viene con el repositorio que le corresponde según el mapeo. Un
    agente sin repositorio se incluye igual, marcado como tal — omitirlo lo
    haría invisible justo cuando hace falta vincularlo.
    """
    log = []
    firestore_client = client or store.get_client()

    if not project:
        proyectos = cx.list_gcp_projects()
        # El proyecto donde vive este servidor no es un destino: ahí están
        # Cloud Run y Firestore, no agentes, y el pipeline nunca despliega
        # sobre sí mismo. Ofrecerlo en el desplegable era ruido que solo se
        # descubre eligiéndolo y encontrando la lista de agentes vacía.
        #
        # Se excluye por ser el suyo y no por una lista escrita a mano: un id
        # en el código habría que acordarse de cambiarlo el día que el
        # servidor se mude, y nadie se acuerda de eso.
        propio = store.proyecto_del_servidor()
        fuera = [p for p in proyectos if p.get("project_id") == propio]
        proyectos = [p for p in proyectos if p.get("project_id") != propio]
        _emit(log, on_log, f"✓ {len(proyectos)} proyectos GCP" +
              (f" (fuera {fuera[0].get('project_id')}: es donde corre este servidor)" if fuera else ""))
        return step_result("ok", log, {"proyectos": proyectos, "agentes": []})

    # El repositorio es del proyecto: o lo tienen todos sus agentes, o ninguno.
    try:
        proyecto = store.get_project_mapping(firestore_client, project)
    except store.MappingNotFound:
        proyecto = None

    registrados = {m["agent_id"]: m for m in
                   store.list_agent_mappings(firestore_client, project)}
    # El cliente pregunta a todas las regiones de CX a la vez y dice cuáles no
    # contestaron. Esa lista viaja hasta el panel en vez de quedarse aquí: un
    # desplegable al que le falta un agente porque su región no respondió es
    # indistinguible de uno completo, y quien lo mira concluye que el agente no
    # existe.
    encontrados, regiones_caidas = cx.list_cx_agents_everywhere(project)
    agentes = []
    for agente in encontrados:
        registro = registrados.get(agente["agentId"])
        agentes.append({
            **agente,
            # El repositorio lo hereda del proyecto; la rama de trabajo es suya
            # — publicar un agente no puede arrastrar lo que sus hermanos
            # tengan sin publicar.
            "repo": proyecto["repo"] if proyecto else None,
            "rama": registro["rama"] if registro else None,
            "vinculado": proyecto is not None,
            # Un agente del proyecto que todavía no se ha dado de alta: hereda
            # el repositorio, pero le faltan su región y su rama. Se incluye
            # marcado, nunca se omite.
            "registrado": registro is not None,
            # La rama que se le crearía. Se manda aunque no se vaya a usar para
            # que el Paso 1 pueda enseñar qué va a pasar *antes* de que pase:
            # el alta es una escritura y se ve entera antes de pulsarla.
            "rama_propuesta": None if registro else rama_propuesta(
                agente["agentId"], agente.get("displayName")),
        })
    _emit(log, on_log,
          f"✓ {len(agentes)} agentes · repositorio del proyecto: "
          f"{proyecto['repo'] if proyecto else 'sin vincular'} · "
          f"{sum(1 for a in agentes if a['registrado'])} dados de alta")
    for caida in regiones_caidas:
        _emit(log, on_log,
              f"⚠ la región {caida['region']} no contestó: {caida['error']} · "
              f"si falta un agente, puede vivir ahí")

    return step_result("ok", log, {
        "proyectos": [], "agentes": agentes,
        "repo": proyecto["repo"] if proyecto else None,
        "rama_principal": proyecto["rama_principal"] if proyecto else None,
        "ninguno_vinculado": proyecto is None,
        "regiones_sin_contestar": regiones_caidas,
    })


# ── 7 · Vincular proyecto y repositorio · alta de agente ─────────────────────

# Reglas de un identificador de proyecto GCP, según su documentación: 6 a 30
# caracteres, minúsculas, dígitos y guiones, empezando por letra y sin terminar
# en guión. Es lo único que se puede exigir aquí con certeza — ver
# `_comprobar_proyecto_existe`.
#
# Termina en `\Z` y no en `$` a propósito: en Python `$` **también casa justo
# antes de un salto de línea final**, así que `"mi-proyecto-505310\n"` pasaba
# por identificador bien formado. Y no se quedaba en un detalle: ese salto
# viajaba hasta el comando IAM, que se parte en dos líneas —`gcloud projects
# add-iam-policy-binding mi-proyecto` y, aparte, `--member=…`— y deja de
# funcionar al pegarlo, que es lo único que ese comando tiene que saber hacer.
ID_PROYECTO_VALIDO = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")


def _aviso_sin_confirmar(project, porque):
    """El aviso de «no se ha podido comprobar», diciendo qué pasó de verdad.

    Se separa del aviso del 403 porque no dicen lo mismo. El 403 sí tiene una
    causa conocida —el servidor todavía no tiene permiso sobre el proyecto— y
    una salida: el comando de abajo. Un 500, un 429 o un corte de red no son
    eso, y anunciarlos con el texto del 403 manda a conceder permisos para
    arreglar algo que no son permisos.
    """
    return (
        f"⚠ No se ha podido comprobar el proyecto {project}: {porque}. El alta "
        f"sigue, pero nadie ha confirmado el identificador: si tras ejecutar el "
        f"comando el proyecto no aparece en el desplegable, revísalo letra por "
        f"letra."
    )


def _comprobar_proyecto_existe(project):
    """Lo poco que se puede afirmar del proyecto antes de vincularlo.

    **No se puede comprobar que exista, y conviene entender por qué.** Quien
    pregunta es el servidor, con su cuenta de servicio, y un proyecto recién
    creado todavía no le ha concedido nada — es justo la situación para la que
    existe esta herramienta. Resource Manager responde **403 tanto si el
    proyecto no existe como si existe y falta permiso**, a propósito, para no
    revelar qué proyectos hay. Desde aquí, un proyecto nuevo legítimo y un
    identificador mal escrito son indistinguibles.

    Un primer intento sí bloqueaba ante el 403, y bloqueaba justo el caso
    normal: dar de alta un proyecto al que el servidor aún no llega.

    Así que se valida solo la forma, que es lo único cierto, y un 404 —que sí
    es inequívoco— se rechaza. El resto se deja pasar y se avisa: la
    confirmación de verdad llega después, cuando tras conceder los permisos el
    proyecto aparece o no aparece en el desplegable.

    **El 404 es una red de seguridad, no la defensa.** Comprobado contra la API
    real (2026-08-12): Resource Manager v1 contesta **403** a un identificador
    que no existe, igual que a uno existente sin permiso. Así que la errata que
    dio origen a esta función —`royecto-fake-505310`, sin la `p`— sigue pasando
    por aquí con un aviso, porque tiene forma válida; lo único que la detiene es
    el `gcloud` de después, que falla sobre un proyecto inexistente. Si algún
    día la API pasara a devolver 404, esto sí podría rechazarla: el Nivel 1 lo
    vigila con un check que pregunta por un identificador inventado.

    Devuelve un aviso para el log, o None si no hay nada que advertir.
    """
    if not ID_PROYECTO_VALIDO.match(project or ""):
        # `!r` y no «comillas»: lo que suele sobrar es un espacio o un salto de
        # línea al final, y entre comillas tipográficas no se ve. Quien lee el
        # error tiene que poder ver el carácter que sobra.
        raise PipelineError(
            f"{project!r} no tiene forma de identificador de proyecto GCP: van "
            f"entre 6 y 30 caracteres, en minúsculas, con dígitos y guiones, "
            f"empezando por letra. Es el ID que aparece en la columna «ID» de "
            f"la consola, no el nombre visible."
        )

    try:
        respuesta = requests.get(
            f"{cx.RESOURCE_MANAGER_BASE}/projects/{project}",
            headers={"Authorization": f"Bearer {cx.get_token()}",
                     "Content-Type": "application/json"},
            timeout=30,
        )
    except requests.exceptions.RequestException as error:
        # Un corte de red o un timeout son «no se ha podido comprobar», que es
        # un estado que esta función ya sabe contestar. Antes subían como
        # excepción y tumbaban el alta entera por un transitorio, y encima con
        # un 500 mudo: el servidor no traduce `ConnectionError`, así que lo
        # contesta como «Fallo interno del servidor», que no menciona ni el
        # proyecto ni qué hacer. Esta comprobación no bloquea nada por
        # definición — que se caiga la red no puede bloquear más que ella.
        return _aviso_sin_confirmar(project, f"la petición no llegó ({error})")

    if respuesta.status_code == 200:
        # El 200 no basta: un proyecto **en la papelera** lo devuelve durante
        # los 30 días que tarda en borrarse de verdad. Y `list_gcp_projects`
        # solo cuenta los `ACTIVE`, así que vincular uno así decía «Proyecto
        # vinculado ✓» sobre algo que no iba a aparecer nunca en el desplegable
        # — exactamente el fallo que esta función existe para evitar, con otro
        # disfraz.
        try:
            estado = (respuesta.json() or {}).get("lifecycleState") or "ACTIVE"
        except ValueError:
            estado = "ACTIVE"
        if estado != "ACTIVE":
            raise PipelineError(
                f"El proyecto «{project}» existe pero está pendiente de borrado "
                f"({estado}), así que no aparecerá en el desplegable ni podrá "
                f"desplegarse. Restáuralo desde la consola de Google Cloud "
                f"—«Recursos pendientes de eliminación»— o usa otro proyecto."
            )
        return None
    if respuesta.status_code == 404:
        raise PipelineError(
            f"El proyecto «{project}» no existe. Comprueba el identificador: "
            f"es el ID de la columna «ID» de la consola, no el nombre visible."
        )
    if respuesta.status_code == 403:
        return (
            f"⚠ Este servidor todavía no ve el proyecto {project} — es lo normal "
            f"antes de concederle los permisos de abajo. No se ha podido confirmar "
            f"que el identificador sea correcto: si tras ejecutar el comando el "
            f"proyecto no aparece en el desplegable, revísalo letra por letra."
        )
    # Cualquier otro estado —500, 429, 401— no es «falta permiso», y decirlo
    # con esas palabras manda a conceder roles para arreglar algo que no son
    # roles. Se avisa de lo que pasó de verdad y se sigue, que es lo que ya
    # hace esta función con todo lo que no puede confirmar.
    return _aviso_sin_confirmar(
        project, f"Resource Manager contestó {respuesta.status_code}")


def rama_propuesta(agent_id, display_name=None):
    """El nombre de rama que el sistema propone para un agente.

    Vive aquí y no en el panel para que los dos digan lo mismo: el panel enseña
    esta propuesta antes de escribir nada, y el alta escribe exactamente lo que
    se enseñó. Si cada uno la calculara por su cuenta, la rama que se crea
    podría no ser la que se leyó en pantalla.
    """
    return f"agente/{_slug(display_name) if display_name else agent_id}"


def _resolver_region(project, agent_id, pista=None):
    """La región del agente, comprobando primero la que llega del listado.

    El desplegable del panel ya trae la región de cada agente —listarlos obliga
    a recorrer las regiones de todos modos—, así que lo normal es acertar con
    una sola petición en vez de las 17 del barrido. Se comprueba y no se cree:
    una región equivocada guardada produce 404 sin contexto en todos los pasos
    siguientes.
    """
    if pista:
        respuesta = cx.api_get(project, pista,
                               cx.build_parent(project, pista, agent_id))
        if respuesta.status_code == 200:
            return pista
    return cx.detect_agent_region(project, agent_id)


def register_agent(project, agent_id, region=None, rama=None,
                   carpeta_raiz="definitions", client=None, gh=None,
                   on_log=None):
    """Da de alta un agente en un proyecto que ya tiene repositorio.

    Es lo que dispara el botón del Paso 1 cuando el agente elegido todavía no
    tiene rama de trabajo. Apunta su región y su rama, y crea esa rama en el
    repositorio.

    **Es una escritura, y por eso es un botón y no un efecto de mirar.** El
    desplegable del Paso 1 lista todos los agentes del proyecto, en todas las
    regiones, incluidos los que nadie piensa gestionar: dar de alta al elegir
    dejaría una rama permanente y visible para todo el equipo cada vez que
    alguien pincha la fila de al lado. El Paso 1 sigue sin escribir nada; lo
    que escribe es esto, cuando se pulsa.
    """
    log = []
    firestore_client = client or store.get_client()

    # Sin repositorio de proyecto no hay de dónde colgar la rama. Es el caso de
    # la herramienta, no el del botón, y se dice con ese nombre.
    try:
        proyecto = store.get_project_mapping(firestore_client, project)
    except store.MappingNotFound:
        raise PipelineError(
            f"El proyecto {project} no tiene repositorio vinculado todavía. "
            f"Vincúlalo primero desde la herramienta «Vincular proyecto y "
            f"repositorio»; el alta de un agente cuelga de él."
        ) from None

    # Todo lo que se puede rechazar sin salir a la red, antes de salir a la
    # red: un nombre de rama inválido no debería costar una vuelta por CX para
    # que le digan que no.
    rama = rama or rama_propuesta(agent_id)

    # La rama de trabajo no puede ser la principal. Si lo fuera, el Paso 2
    # escribiría directamente en la rama que se publica —rompiendo su promesa
    # de no tocarla nunca— y el Paso 5 se quedaría fusionando una rama consigo
    # misma, que es un no-op permanente: el orden «fusionar y solo después
    # publicar» dejaría de significar nada sin que nada avisara.
    if rama == proyecto["rama_principal"]:
        raise PipelineError(
            f"La rama de trabajo no puede ser la principal ({rama}). El Paso 2 "
            f"escribe en la de trabajo y el Paso 5 la fusiona en la principal: "
            f"siendo la misma, publicar dejaría de ser una decisión."
        )

    # Dos agentes no pueden compartir rama: publicar uno arrastraría a la
    # principal lo que el otro tuviera sin publicar. Y la colisión es fácil sin
    # buscarla — dos agentes con el mismo displayName proponen el mismo nombre,
    # y `create_branch` es idempotente, así que sin esta comprobación la
    # compartirían en silencio en vez de fallar.
    hermanos = [m for m in store.list_agent_mappings(firestore_client, project)
                if m.get("rama") == rama and m.get("agent_id") != agent_id]
    if hermanos:
        raise PipelineError(
            f"La rama {rama} ya es la del agente {hermanos[0]['agent_id']}. Dos "
            f"agentes no pueden compartir rama de trabajo: publicar uno "
            f"arrastraría lo que el otro no ha publicado. Elige otro nombre."
        )

    region = _resolver_region(project, agent_id, region)
    _emit(log, on_log, f"✓ Región del agente: {region}")

    github = gh or GitHubAppClient(proyecto["repo"])
    sha, creada = github.create_branch(rama, proyecto["rama_principal"])
    _emit(log, on_log,
          f"{'✓ Rama creada' if creada else '· La rama ya existía'}: {rama} "
          f"· commit {sha[:7]}")

    # Después de la rama, no antes: un alta guardada cuya rama no existe deja
    # el Paso 1 muriendo con un 404 de git, que no explica nada de lo que pasa.
    store.save_agent_mapping(firestore_client, project, agent_id, region, rama,
                             carpeta_raiz=carpeta_raiz)
    _emit(log, on_log, f"✓ Agente dado de alta · {proyecto['repo']} · {rama}")

    return step_result("ok", log, {
        "project": project, "agent_id": agent_id, "region": region,
        "repo": proyecto["repo"], "rama": rama, "rama_creada": creada,
        "carpeta_raiz": carpeta_raiz,
    })


def link_project_repo(project, repo_url, rama_principal="main",
                      client=None, gh=None, on_log=None):
    """Vincula un proyecto GCP con su repositorio. Una vez por proyecto.

    El repositorio es del proyecto, no del agente: todos los agentes
    relacionados de un mismo proyecto viven dentro, cada uno con su rama. Por
    eso esta herramienta no pregunta por ningún agente — los agentes se dan de
    alta uno a uno desde el Paso 1, con su botón, la primera vez que se elige
    cada uno.

    Tampoco trae nada: traer lo que ya existe en CX es el Paso 2 del pipeline
    normal, y hacerlo aquí sería un segundo camino para lo mismo.

    Lo único que no hace es conceder IAM: devuelve el comando exacto para
    ejecutarlo a mano una vez, fuera del panel (S6b). El permiso es de
    proyecto, así que se concede aquí y cubre a todos sus agentes.
    """
    log = []
    firestore_client = client or store.get_client()
    repo = _repo_desde_url(repo_url)

    # Se comprobaba el repositorio y no el proyecto, y esa asimetría dejó
    # registrar `royecto-fake-505310` —sin la `p`— con un «Proyecto vinculado
    # ✓» encima. Lo que se puede afirmar aquí es menos de lo que parece: ver
    # `_comprobar_proyecto_existe`.
    aviso = _comprobar_proyecto_existe(project)
    _emit(log, on_log, aviso or f"✓ El proyecto {project} existe y se ve desde aquí")

    # La rama principal tiene que existir ya: la creó quien creó el
    # repositorio, y es de donde nacen las ramas de los agentes. Se lee antes
    # de escribir nada para no registrar un vínculo con un repositorio al que
    # no se llega.
    github = gh or GitHubAppClient(repo)
    github.branch_head(rama_principal)
    _emit(log, on_log, f"✓ Acceso al repositorio {repo}, rama {rama_principal}")

    # La cuenta de servicio se averigua **antes de escribir**, por lo mismo que
    # el repositorio se lee antes: sin ella no hay comando IAM que devolver, y
    # el alta sin ese comando no sirve de nada. Preguntándola al final, un fallo
    # aquí dejaba el proyecto ya vinculado en Firestore y la herramienta
    # reportando error, sin comando y sin que nada dijera que el vínculo sí
    # había quedado escrito. No es hipotético: fue el estado que dejó cada alta
    # hecha desde Cloud Run mientras `runtime_service_account` no sabía
    # preguntarle al servidor de metadatos.
    cuenta = cx.runtime_service_account()

    # Un proyecto tiene un solo repositorio. Vincular dos veces el mismo no es
    # un error —es lo que pasa al abrir la herramienta por costumbre—; cambiarlo
    # por otro sí, porque dejaría a los agentes ya dados de alta apuntando a
    # ramas de un repositorio distinto del que dice su proyecto.
    try:
        ya = store.get_project_mapping(firestore_client, project)
        if ya["repo"] != repo:
            raise PipelineError(
                f"El proyecto {project} ya está vinculado a {ya['repo']}. Un "
                f"proyecto tiene un solo repositorio, y todos sus agentes viven "
                f"dentro. Para usar otro, desvincula el proyecto primero."
            )
        # Revincular no reescribe el documento, así que tampoco cambia la rama
        # principal — y devolver la que se pidió hacía que la respuesta dijera
        # `master` mientras Firestore seguía guardando `main`. Peor todavía:
        # `branch_head` acaba de confirmar que la rama pedida existe, así que
        # nada delataba que no se había guardado. Se devuelve lo que hay
        # guardado, y si no es lo que se pidió se dice.
        if ya["rama_principal"] != rama_principal:
            _emit(log, on_log,
                  f"⚠ La rama principal del proyecto sigue siendo "
                  f"{ya['rama_principal']}, no {rama_principal}: vincular de "
                  f"nuevo no la cambia. Para cambiarla, desvincula el proyecto "
                  f"primero.")
        rama_principal = ya["rama_principal"]
        _emit(log, on_log, f"· El proyecto ya estaba vinculado a {repo}")
        nuevo = False
    except store.MappingNotFound:
        store.save_project_mapping(firestore_client, project, repo,
                                   rama_principal)
        _emit(log, on_log, "✓ Repositorio del proyecto registrado")
        nuevo = True

    # Vincular no escribe nada en el repositorio. Antes dejaba un marcador
    # `cx-deploy.yaml` en la raíz (S23) que decía de qué proyecto era el
    # repositorio; se retiró el 2026-08-08 porque nadie lo leía nunca —se
    # escribía y no se consultaba— y encima el Paso 1 lo contaba como un YAML
    # más. El vínculo vive donde se consulta, en el registro del proyecto. Si
    # algún día hace falta declarar algo por repositorio, el archivo se crea
    # entonces, junto con quien lo lea.

    # Los tres, no uno. `dialogflow.admin` **no incluye**
    # `serviceusage.services.use`, que es lo que exige la cabecera
    # `x-goog-user-project` de toda llamada a CX: sin el segundo rol, todas
    # salen con 403 aunque el primero esté concedido (hallazgo X1,
    # `docs/cloudrun_diseno_servidor.md §8.4`). Y `roles/browser` es lo que
    # hace que el proyecto aparezca en el desplegable, porque `dialogflow.admin`
    # da `resourcemanager.projects.get` pero no `.list`. Este comando devolvía
    # solo el primero: quien lo siguiera al pie de la letra se quedaba con un
    # proyecto invisible y con 403 en cuanto lo escribía a mano.
    comando_iam = " && \\\n".join(
        f"gcloud projects add-iam-policy-binding {project} "
        f"--member=serviceAccount:{cuenta} --role={rol}"
        for rol in ROLES_DEL_ALTA
    )
    _emit(log, on_log,
          "Falta un paso manual: ejecuta el comando IAM que devuelve este paso")

    return step_result("ok", log, {
        "project": project, "repo": repo, "rama_principal": rama_principal,
        "ya_estaba": not nuevo, "comando_iam": comando_iam,
    })


def _repo_desde_url(repo_url):
    """De una URL de GitHub a 'owner/nombre'.

    Ni `@` ni `:` en las dos mitades, y eso es lo que rechaza la forma SSH.
    `git@github.com:owner/repo.git` no lleva `//`, así que la comprobación
    anterior lo daba por bueno y devolvía `git@github.com:owner/repo` como
    nombre de repositorio: GitHub contestaba 404 sobre esa ruta imposible tres
    llamadas más tarde, y el mensaje hablaba de una rama que no existe en vez
    de la URL que estaba mal. Un nombre de usuario o de repositorio de GitHub
    no puede llevar ninguno de los dos caracteres, así que esto no rechaza
    nada legítimo.
    """
    limpio = (repo_url or "").strip().rstrip("/")
    limpio = re.sub(r"^https?://github\.com/", "", limpio)
    limpio = re.sub(r"\.git$", "", limpio)
    if not re.match(r"^[^/@:]+/[^/@:]+$", limpio):
        raise ValueError(
            f"No se reconoce como repositorio de GitHub: {repo_url!r}. "
            f"Formato esperado: https://github.com/usuario/repo"
        )
    return limpio


# ── 8 · Versiones existentes ─────────────────────────────────────────────────

def _contenedores_de_versiones(inventario):
    """Agrupa las versiones ya existentes por su contenedor padre y tipo.

    El `name` de una versión trae el padre incrustado en la ruta: todo lo
    que precede a `/versions/<id>` es el nombre completo del flow, playbook
    o tool que la contiene — el mismo recorte que ya usan
    `_combinar_versiones` y `_versiones_reutilizables`. Para saber de qué
    *tipo* es ese padre no hace falta una tabla nueva: el segmento justo
    antes de su propio id (`/flows/`, `/playbooks/`, `/tools/`) es el mismo
    `RESOURCE_TYPES[tipo]["api"]` que ya construye esas rutas en el resto
    del archivo, así que traducirlo con esa misma fuente evita que se
    desincronice de cómo CX nombra las cosas.

    Devuelve {(nombre_padre, tipo): vivas}.
    """
    tipos_con_version = dict(RESOURCE_TYPES["version"].get("padres") or ()).keys()
    segmento_a_tipo = {f"/{RESOURCE_TYPES[t]['api']}/": t for t in tipos_con_version}

    conteo = {}
    for item in inventario.get("version", {}).values():
        nombre_padre = (item.get("name") or "").rsplit("/versions/", 1)[0]
        tipo = next((t for segmento, t in segmento_a_tipo.items()
                    if segmento in nombre_padre), None)
        if not tipo:
            continue
        clave = (nombre_padre, tipo)
        conteo[clave] = conteo.get(clave, 0) + 1
    return conteo


def manage_versions(project, agent_id, action="list", version_names=None,
                    client=None, gh=None, on_log=None):
    """Lista las versiones que guarda el agente, o borra las que se marquen.

    Las que un entorno está sirviendo no se pueden borrar: se devuelven
    marcadas para que el panel no deje marcarlas.
    """
    log = []
    contexto = Contexto(project, agent_id, client=client, gh=gh)
    inventario, _, _ = inventariar_cx(contexto, on_log, log)

    if action == "list":
        # Foto de lo que ya se acaba de leer — vale para mostrar en el panel,
        # no decide ningún borrado, así que no hace falta releerla fresca.
        en_uso = {cf["version"] for entorno in inventario.get("environment", {}).values()
                  for cf in entorno.get("versionConfigs", [])}
        versiones = [
            {
                "name": item["name"],
                "display_name": item.get("displayName", ""),
                "descripcion": item.get("description", ""),
                "creada": item.get("createTime", ""),
                "estado": item.get("state", ""),
                "en_uso": item["name"] in en_uso,
            }
            for item in inventario.get("version", {}).values()
        ]

        # Aviso proactivo: cuántas versiones vivas tiene cada contenedor frente
        # a su límite, para que el panel pueda mostrar algo tipo "18/20". Es
        # de solo lectura, igual que `_contenedores_sobre_limite` — nada en
        # este archivo borra versiones salvo que se le nombren explícitamente
        # vía `action="delete"`, nunca de forma automática.
        contenedores_cerca_del_limite = [
            {"nombre_padre": nombre_padre, "tipo": tipo, "vivas": vivas,
             "limite": LIMITE_VERSIONES[tipo]}
            for (nombre_padre, tipo), vivas in _contenedores_de_versiones(inventario).items()
            if tipo in LIMITE_VERSIONES
            and vivas >= LIMITE_VERSIONES[tipo] * UMBRAL_AVISO_LIMITE_VERSIONES
        ]

        _emit(log, on_log,
              f"✓ {len(versiones)} versiones · {len(en_uso)} en uso")
        if contenedores_cerca_del_limite:
            _emit(log, on_log,
                  f"⚠ {len(contenedores_cerca_del_limite)} contenedores cerca "
                  f"de su límite de versiones")
        return step_result("ok", log, {
            "versiones": versiones,
            "contenedores_cerca_del_limite": contenedores_cerca_del_limite,
        })

    if action != "delete":
        raise ValueError(
            f"Acción no reconocida: {action!r}. Solo 'list' o 'delete'."
        )

    borradas, protegidas = [], []
    with store.agent_lock(contexto.store, project, agent_id, "borrar versiones"):
        # Releída aquí dentro, no la de arriba: esa es de antes del candado,
        # y un publish concurrente puede haber puesto en uso justo la versión
        # que se está a punto de borrar. Mismo motivo que _versiones_en_uso.
        en_uso = _versiones_en_uso(contexto)
        for nombre in version_names or ():
            # La ruta llega del cliente, así que se comprueba contra el destino
            # elegido antes de tocarla. Sin esto, una petición con la ruta de
            # otro agente borraba sus versiones con el token del servicio —
            # incluida la que ese agente estuviera sirviendo en producción,
            # porque `en_uso` se calcula sobre el agente del contexto, no sobre
            # el afectado. Es la regla C3: el servidor construye o comprueba
            # todas las rutas, nunca las obedece.
            if not nombre.startswith(f"{contexto.parent}/"):
                raise PipelineError(
                    f"La versión {nombre} no pertenece al agente {agent_id}. "
                    f"Esta herramienta solo borra versiones del agente elegido."
                )
            if nombre in en_uso:
                protegidas.append(nombre)
                _emit(log, on_log,
                      f"—     {nombre.rsplit('/', 1)[-1]} la sirve un entorno")
                continue
            respuesta = cx.api_delete(contexto.project, contexto.region, nombre)
            if respuesta.status_code not in (200, 204):
                raise PipelineError(
                    f"DELETE de {nombre} falló: {respuesta.status_code} "
                    f"{respuesta.text[:200]}"
                )
            borradas.append(nombre)
            _emit(log, on_log, f"OK    borrada {nombre.rsplit('/', 1)[-1]}")

    return step_result("ok", log, {"borradas": borradas,
                                   "protegidas": protegidas})
