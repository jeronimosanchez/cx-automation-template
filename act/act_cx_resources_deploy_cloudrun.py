#!/usr/bin/env python3
"""
act/act_cx_resources_deploy_cloudrun.py — Backend del pipeline de deploy ACT
en su variante Cloud Run.

Hace real lo que docs/panels/act_cx_resources_deploy_v2.html describe: cinco
pasos —Inventario, Traer al repositorio, Aplicar en CX, Validar tests,
Publicar— más cuatro capacidades que no pertenecen a ningún paso numerado:
Descubrimiento, Vincular agente y repositorio, Versiones existentes y
desplegar un resource suelto. Nueve funciones públicas en total; el servidor
de la fase siguiente delega en ellas y no reimplementa nada.

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
    "version": {"api": "versions", "key": "versions", "padre": "flow",
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

# La tabla que consulta todo lo que escribe un resource — el Paso 3 y la
# herramienta de desplegar uno suelto. No contiene `environment`, así que
# ningún camino de escritura puede construir una URL con `/environments/`
# aunque se le pida: no es una comprobación que pueda fallar, es una entrada
# que no existe (S20). La única función que sabe escribir esa URL es
# `_apuntar_entorno`, y solo la alcanza el Paso 5.
TIPOS_DESPLEGABLES = {
    tipo: spec for tipo, spec in RESOURCE_TYPES.items()
    if tipo not in TIPOS_NO_DESPLEGABLES
}

# Tipos que CX no puede congelar en una versión: lo que se les aplique lo ven
# los usuarios en el acto, sin pasar por el gate del Paso 4.
TIPOS_SIN_VERSION = ("agent_config", "generator")

ENTORNO_PRODUCCION = "production"

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
        mapeo = store.get_agent_mapping(self.store, project, agent_id)
        self.region = mapeo["region"]
        self.repo = mapeo["repo"]
        self.rama = mapeo["rama"]
        self.rama_principal = mapeo.get("rama_principal", "main")
        self.gh = gh or GitHubAppClient(self.repo)

    @property
    def parent(self):
        return cx.build_parent(self.project, self.region, self.agent_id)


# ── Lectura del repositorio ──────────────────────────────────────────────────

def cargar_repositorio(contexto, on_log=None, log=None):
    """Todos los YAML del repositorio, agrupados por el `tipo` que declaran.

    Devuelve (recursos, commit_sha, total_archivos). `recursos` es
    {tipo: {cx_id: {"ruta", "documento", "display_name"}}} más una lista
    aparte para los que aún no tienen `cx_id`.

    Un YAML sin bloque `metadata` no es un resource del pipeline: se ignora.
    Los resources se declaran de forma explícita al crearlos, así que la
    ausencia del bloque no es un error que haya que perseguir — hay YAML en el
    repositorio que nunca fueron resources (taxonomías, configuraciones de
    scoring, specs OpenAPI).
    """
    log = log if log is not None else []
    commit_sha = contexto.gh.branch_head(contexto.rama)
    archivos = contexto.gh.list_tree(commit_sha)

    recursos = {tipo: {} for tipo in RESOURCE_TYPES}
    sin_cx_id = []
    duplicados = []
    ignorados = 0

    for archivo in archivos:
        crudo = contexto.gh.read_blob(archivo["sha"])
        try:
            documento = yaml.safe_load(crudo)
        except yaml.YAMLError as error:
            raise PipelineError(
                f"{archivo['path']} no es YAML válido: {error}"
            ) from error

        metadata = payloads.read_metadata(documento)
        if not metadata:
            ignorados += 1
            continue

        tipo = metadata.get("tipo")
        if tipo not in RESOURCE_TYPES:
            raise PipelineError(
                f"{archivo['path']} declara tipo '{tipo}', que no existe. "
                f"Tipos válidos: {', '.join(sorted(RESOURCE_TYPES))}."
            )

        entrada = {
            "ruta": archivo["path"],
            "documento": documento,
            "tipo": tipo,
            "padre": metadata.get("padre"),
            "display_name": documento.get("displayName", ""),
        }

        cx_id = metadata.get("cx_id")
        if not cx_id:
            sin_cx_id.append(entrada)
            continue

        if cx_id in recursos[tipo]:
            duplicados.append(
                f"{tipo}/{cx_id}: {recursos[tipo][cx_id]['ruta']} y {archivo['path']}"
            )
            continue
        entrada["cx_id"] = cx_id
        recursos[tipo][cx_id] = entrada

    if duplicados:
        # Duplicar un archivo para crear una variante es natural; olvidarse de
        # vaciar el cx_id deja dos YAML reclamando el mismo resource de CX, y
        # el último en aplicarse gana sin que nadie lo note.
        raise PipelineError(
            "Hay archivos distintos con el mismo tipo y cx_id — vacía el "
            "cx_id del que sea nuevo:\n  " + "\n  ".join(duplicados)
        )

    _emit(log, on_log,
          f"✓ {contexto.rama} · commit {commit_sha[:7]} · "
          f"{len(archivos)} archivos YAML")
    if ignorados:
        _emit(log, on_log,
              f"· {ignorados} YAML sin bloque metadata — no son resources")

    return {"por_tipo": recursos, "sin_cx_id": sin_cx_id,
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
        inventario[tipo] = {_cx_id_de(item): item for item in items}
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


# Las versiones no son definiciones: son fotos que crea el Paso 5. No tienen
# archivo en el repositorio ni deberían tenerlo, así que no entran en el
# reparto de tres grupos — si entraran, cada versión aparecería como "solo en
# CX" y el Paso 2 ofrecería traérselas al repositorio, que no significa nada.
# Se inventarían igual porque el Paso 5 y el desplegable de versiones las
# necesitan; simplemente se cuentan aparte.
TIPOS_FUERA_DEL_REPARTO = ("version",)


def emparejar(inventario, repositorio):
    """Reparte todo lo leído en los tres grupos que pinta el Paso 1.

    Ningún resource cae en dos grupos: la suma de los tres cuadra con lo
    leído, que es uno de los criterios de validación del paso.
    """
    emparejados, solo_cx, solo_repo = [], [], []

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
            else:
                solo_cx.append({
                    **fila,
                    "nativo": es_nativo(tipo, item),
                    "traible": not es_nativo(tipo, item),
                })

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
            "solo_repo": solo_repo}


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
            if cx_id not in remotos:
                operaciones.append(_operacion("POST", tipo, cx_id, entrada, local))
            elif payloads.differs(remotos[cx_id], local):
                operacion = _operacion(
                    "PATCH", tipo, cx_id, entrada, local,
                    remote_name=remotos[cx_id].get("name"),
                )
                _marcar_conflicto(operacion, remotos[cx_id], auditoria)
                operaciones.append(operacion)

    for entrada in repositorio["sin_cx_id"]:
        if entrada["tipo"] in TIPOS_NO_DESPLEGABLES:
            continue
        local = payloads.comparable_local(entrada["tipo"], entrada["documento"])
        operaciones.append(_operacion(
            "POST", entrada["tipo"], None, entrada, local
        ))

    operaciones.extend(
        _operaciones_de_borrado(inventario, repositorio, eliminar)
    )

    operaciones.sort(key=lambda op: (
        DEPLOY_ORDER.index(op["tipo"]) if op["tipo"] in DEPLOY_ORDER
        else len(DEPLOY_ORDER)
    ))
    return operaciones


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


def _operaciones_de_borrado(inventario, repositorio, eliminar):
    """Convierte en operaciones las eliminaciones decididas en el Paso 2.

    Cada una se comprueba contra el estado real antes de aceptarla: tiene que
    existir en CX y no tener archivo en el repositorio, que es la única
    categoría que el Paso 2 ofrece borrar. Sin esta comprobación, el servidor
    estaría borrando lo que le pidan sin mirar.
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
        operaciones.append({
            "operacion": "DELETE",
            "tipo": tipo,
            "cx_id": cx_id,
            "ruta": None,
            "padre": None,
            "resource": remoto.get("displayName", cx_id),
            "local": None,
            "remote_name": remoto.get("name"),
            "sin_version": tipo in TIPOS_SIN_VERSION,
            "result": None,
        })
    return operaciones


# ── Escritura en CX ──────────────────────────────────────────────────────────

def _ruta_padre(contexto, operacion, inventario):
    """Dónde cuelga un resource: del agente, o de su playbook o flow."""
    spec = TIPOS_DESPLEGABLES[operacion["tipo"]]
    if not spec.get("padre"):
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


def aplicar_operaciones(contexto, operaciones, inventario, on_log=None, log=None):
    """Aplica en orden y se para en el primer fallo.

    Cada operación queda con su resultado —OK, ERROR o NO_INTENTADO— para que
    un reintento pueda reenviar solo lo que falló y lo que no se llegó a
    intentar, nunca lo que ya salió bien: repetirlo lo escribiría dos veces.
    """
    log = log if log is not None else []
    fallo = False

    for operacion in operaciones:
        etiqueta = f"{operacion['tipo']}/{operacion['resource']}"
        if fallo:
            operacion["result"] = "NO_INTENTADO"
            _emit(log, on_log, f"—     {etiqueta}")
            continue
        try:
            creado = _aplicar_operacion(contexto, operacion, inventario)
            operacion["result"] = "OK"
            if operacion["operacion"] == "POST" and creado.get("name"):
                operacion["cx_id"] = _cx_id_de(creado)
            _emit(log, on_log, f"OK    {operacion['operacion']} {etiqueta}")
            if operacion["cx_id"]:
                store.record_resource_write(
                    contexto.store, contexto.project, contexto.agent_id,
                    operacion["tipo"], operacion["cx_id"], operacion["ruta"],
                    display_name=operacion["resource"],
                    operacion=operacion["operacion"],
                    # Cómo queda CX tras esta escritura. Es contra esto contra
                    # lo que el diff siguiente detecta un cambio externo.
                    huella_cx=huella_resource(creado),
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

    return step_result("ok", log, {
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
    })


# ── 2 · Traer al repositorio ─────────────────────────────────────────────────

def _ruta_destino(tipo, item, inventario):
    """Dónde escribe el pull un resource que solo existe en CX.

    La carpeta la fija el tipo. Los examples van además a una subcarpeta por
    playbook padre: el servidor conoce el padre, y agruparlos es lo que hace
    navegable una carpeta con decenas de archivos.
    """
    spec = RESOURCE_TYPES[tipo]
    nombre = f"{_slug(item.get('displayName'))}.yaml"
    if tipo == "example":
        padre_id = (item.get("name") or "").split("/playbooks/")[-1].split("/")[0]
        padre = inventario.get("playbook", {}).get(padre_id, {})
        return f"{spec['carpeta']}/{_slug(padre.get('displayName'))}/{nombre}"
    return f"{spec['carpeta']}/{nombre}"


def _yaml_para_repo(tipo, item, padre_id=None):
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
        },
        **cuerpo,
    }
    return yaml.safe_dump(documento, allow_unicode=True, sort_keys=False)


def step_2_pull_to_repo(project, agent_id, traer, client=None, gh=None,
                        on_log=None):
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
                _emit(log, on_log,
                      f"· {tipo}/{cx_id} ya tiene archivo — se omite")
                continue

            padre_id = None
            if RESOURCE_TYPES[tipo].get("padre"):
                padre_id = _padre_id_de(tipo, item)
            ruta = _ruta_destino(tipo, item, inventario)
            archivos[ruta] = _yaml_para_repo(tipo, item, padre_id)
            traidos.append({"tipo": tipo, "cx_id": cx_id, "ruta": ruta,
                            "display_name": item.get("displayName", "")})
            _emit(log, on_log, f"✓ {ruta}")

        if not archivos:
            _emit(log, on_log, "· Nada que traer")
            return step_result("ok", log, {"traidos": [], "commit": None})

        mensaje = (f"chore(pull): traer {len(archivos)} resources de "
                   f"{agent_id} al repositorio")
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
            )

        _emit(log, on_log,
              "Repositorio actualizado — haz `git pull` en local antes de "
              "seguir trabajando")

    resultado = step_result("ok", log, {
        "traidos": traidos, "commit": commit, "repo": contexto.repo,
        "rama": contexto.rama,
    })
    store.record_run(contexto.store, project, agent_id, 2, "ok", log,
                     resultado["data"])
    return resultado


def _padre_id_de(tipo, item):
    """El cx_id del padre, sacado de la propia ruta del recurso en CX."""
    spec = RESOURCE_TYPES[tipo]
    segmento = {"playbook": "/playbooks/", "flow": "/flows/"}[spec["padre"]]
    nombre = item.get("name") or ""
    if segmento not in nombre:
        return None
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
        marcados = {(m.get("tipo"), m.get("cx_id")) for m in aplicar}
        operaciones = [
            op for op in operaciones
            if (op["tipo"], op["cx_id"]) in marcados
            or (op["cx_id"] is None and (op["tipo"], op["ruta"]) in
                {(m.get("tipo"), m.get("ruta")) for m in aplicar})
        ]
    if only_pending:
        pendientes = {(p.get("tipo"), p.get("cx_id")) for p in only_pending}
        operaciones = [op for op in operaciones
                       if (op["tipo"], op["cx_id"]) in pendientes]

    avisos = avisar_cambio_de_archivo(contexto, operaciones)
    for aviso in avisos:
        _emit(log, on_log,
              f"⚠ {aviso['tipo']}/{aviso['cx_id']} cambió de archivo: "
              f"{aviso['archivo_antes']} → {aviso['archivo_ahora']}")

    conflictos = [op for op in operaciones if op["conflicto"]]
    for conflicto in conflictos:
        _emit(log, on_log,
              f"⚠ CONFLICTO en {conflicto['tipo']}/{conflicto['resource']}: "
              f"cambió en el repositorio y también en CX por fuera del "
              f"pipeline. Aplicarlo se lleva por delante el cambio de CX")

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
            "conflictos": conflictos,
        })

    if not operaciones:
        _emit(log, on_log, "· Nada que aplicar")
        return step_result("ok", log, {"operaciones": [], "aplicadas": 0,
                                       "fallo": False})

    with store.agent_lock(contexto.store, project, agent_id, "aplicar en CX"):
        resultados, fallo, _ = aplicar_operaciones(
            contexto, operaciones, inventario, on_log, log
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
    store.record_run(contexto.store, project, agent_id, 3,
                     resultado["status"], log, {"aplicadas": resultado["data"]["aplicadas"]})
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


def _huella_borrador(inventario):
    """Marca del estado del borrador, para detectar si se movió después.

    Se construye con los tiempos de última modificación que devuelve la API,
    no con el contenido entero: basta para saber que algo cambió, y no obliga
    a guardar una copia del agente.
    """
    marcas = []
    for tipo in sorted(inventario):
        for cx_id, item in sorted(inventario[tipo].items()):
            marcas.append(f"{tipo}:{cx_id}:{item.get('updateTime', '')}")
    return hashlib.sha256("|".join(marcas).encode()).hexdigest()[:16]


# ── 5 · Publicar en producción ───────────────────────────────────────────────

def step_5_publish(project, agent_id, version_label, huella_al_validar=None,
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

        # El gate del Paso 4 queda atado al borrador exacto que se aprobó. Si
        # el borrador se movió entre declarar los tests y publicar, publicar
        # subiría a usuarios reales algo que nadie validó — así que se aborta
        # antes de tocar nada, no se avisa y se sigue.
        #
        # Salir por aquí no deja nada a medias: es lo primero que se comprueba,
        # antes del merge y antes de crear ninguna versión.
        if huella_al_validar and _huella_borrador(inventario) != huella_al_validar:
            _emit(log, on_log,
                  "⚠ El borrador ha cambiado desde que se declararon los tests. "
                  "No se publica: lo que subiría no es lo que se probó. Vuelve "
                  "al Paso 4, valida el borrador actual y repite.")
            return step_result("aborted", log, {
                "fusionado": False, "publicado": False,
                "motivo": "el borrador se movió después de declarar los tests",
                "huella_al_validar": huella_al_validar,
                "huella_ahora": _huella_borrador(inventario),
            })

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

        pendientes = store.list_pending_publication(
            contexto.store, project, agent_id
        )

        # Un intento anterior pudo crear las versiones y morir antes de fijar
        # el entorno. Esas versiones existen en CX y no las sirve nadie: si el
        # reintento crea otras, las primeras quedan huérfanas, consumiendo
        # hueco contra el límite por playbook sin que nada las reclame.
        versiones = _versiones_reutilizables(contexto, on_log, log)
        if versiones:
            fallo = False
        else:
            _emit(log, on_log,
                  f"· 2/3 Creando versiones · {len(pendientes)} resources tocados "
                  f"desde la última publicación")
            versiones, fallo = _crear_versiones(
                contexto, inventario, pendientes, version_label, on_log, log
            )
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
        # tenía; lo que cambió estrena la recién creada.
        finales = _combinar_versiones(anteriores, versiones)
        _apuntar_entorno(contexto, produccion, finales)
        _emit(log, on_log,
              f"✓ Producción sirviendo {version_label} · "
              f"{len(finales)} versiones fijadas")

        store.mark_published(contexto.store, project, agent_id, pendientes)
        store.clear_inflight_versions(contexto.store, project, agent_id)

    resultado = step_result("ok", log, {
        "fusionado": True, "publicado": True, "version": version_label,
        "versiones_creadas": versiones, "versiones_anteriores": anteriores,
        "repo": contexto.repo, "rama_principal": contexto.rama_principal,
    })
    store.record_run(contexto.store, project, agent_id, 5, "ok", log,
                     {"version": version_label})
    return resultado


def _versiones_reutilizables(contexto, on_log, log):
    """Versiones que un intento anterior creó y no llegó a fijar en el entorno.

    Se comprueba que sigan existiendo en CX antes de reutilizarlas: si alguien
    las borró a mano entre medias, reutilizar una ruta muerta haría fallar el
    PATCH del entorno con un error que no diría por qué.
    """
    anotadas = store.get_inflight_versions(
        contexto.store, contexto.project, contexto.agent_id
    )
    if not anotadas or not anotadas.get("version_names"):
        return []

    vivas = [
        nombre for nombre in anotadas["version_names"]
        if cx.api_get(contexto.project, contexto.region, nombre).status_code == 200
    ]
    if not vivas:
        store.clear_inflight_versions(
            contexto.store, contexto.project, contexto.agent_id
        )
        return []

    _emit(log, on_log,
          f"· 2/3 Reutilizando {len(vivas)} versiones que un intento anterior "
          f"dejó creadas sin fijar ({anotadas.get('etiqueta')})")
    return vivas


def _crear_versiones(contexto, inventario, pendientes, etiqueta, on_log, log):
    """Crea una versión por cada padre versionable que el diff tocó.

    Registra cada versión con su resultado y se para en el primer fallo, igual
    que el Paso 3. El bucle del pipeline local no lo hacía: si fallaba a mitad,
    lanzaba el error y las versiones ya creadas quedaban huérfanas, sin
    registrar ni limpiar.
    """
    objetivos = _padres_versionables(inventario, pendientes)
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
        except PipelineError as error:
            _emit(log, on_log, f"ERROR {nombre_padre}: {error}")
            _emit(log, on_log,
                  f"Se pararon las versiones — {len(creadas)} ya creadas, "
                  f"ninguna fijada en ningún entorno")
            return creadas, True

    return creadas, False


def _padres_versionables(inventario, pendientes):
    """Qué flows, playbooks y tools hay que versionar por lo que se tocó.

    Un example no tiene versión propia: la tiene su playbook. Una page, la
    suya el flow. Por eso lo tocado se traduce a su padre versionable antes de
    crear nada.
    """
    objetivos = set()
    for pendiente in pendientes:
        tipo, cx_id = pendiente.get("tipo"), pendiente.get("cx_id")
        if tipo in ("playbook", "flow", "tool"):
            item = inventario.get(tipo, {}).get(cx_id)
            if item:
                objetivos.add((item["name"], tipo))
        elif tipo == "example":
            for nombre, item in _por_nombre(inventario, "playbook"):
                if cx_id in inventario.get("example", {}) and \
                        nombre in (inventario["example"][cx_id].get("name") or ""):
                    objetivos.add((nombre, "playbook"))
        elif tipo in ("page", "transition_route_group"):
            for nombre, item in _por_nombre(inventario, "flow"):
                hijo = inventario.get(tipo, {}).get(cx_id, {})
                if nombre in (hijo.get("name") or ""):
                    objetivos.add((nombre, "flow"))
    return sorted(objetivos)


def _por_nombre(inventario, tipo):
    return [(item["name"], item) for item in inventario.get(tipo, {}).values()]


def _combinar_versiones(anteriores, nuevas):
    """Une lo que ya estaba fijado con lo recién creado, una versión por padre.

    Sin esto, apuntar solo a lo nuevo dejaría fuera del entorno todo lo que no
    cambió, y el PATCH del entorno falla porque exige la cadena completa.
    """
    por_padre = {}
    for nombre in list(anteriores) + list(nuevas):
        padre = nombre.rsplit("/versions/", 1)[0]
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


def _apuntar_entorno(contexto, entorno, version_names):
    """PATCH del entorno con updateMask — el único tipo que lo exige."""
    cuerpo = dict(entorno)
    cuerpo["versionConfigs"] = [{"version": nombre} for nombre in version_names]
    for campo in CAMPOS_LEIDOS_NO_ENVIADOS:
        cuerpo.pop(campo, None)
    respuesta = cx.api_patch(
        contexto.project, contexto.region, entorno["name"], cuerpo,
        params={"updateMask": "versionConfigs"},
    )
    if respuesta.status_code not in (200, 201):
        raise PipelineError(
            f"PATCH del entorno falló: {respuesta.status_code} "
            f"{respuesta.text[:200]}"
        )
    return cx.resolve_operation(contexto.project, contexto.region, respuesta)


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
        _emit(log, on_log, f"✓ {len(proyectos)} proyectos GCP")
        return step_result("ok", log, {"proyectos": proyectos, "agentes": []})

    mapeos = {m["agent_id"]: m for m in
              store.list_agent_mappings(firestore_client, project)}
    agentes = []
    for agente in cx.list_cx_agents_everywhere(project):
        mapeo = mapeos.get(agente["agentId"])
        agentes.append({
            **agente,
            "repo": mapeo["repo"] if mapeo else None,
            "rama": mapeo["rama"] if mapeo else None,
            "vinculado": mapeo is not None,
        })
    _emit(log, on_log,
          f"✓ {len(agentes)} agentes · "
          f"{sum(1 for a in agentes if a['vinculado'])} con repositorio")

    return step_result("ok", log, {
        "proyectos": [], "agentes": agentes,
        "ninguno_vinculado": bool(agentes) and not any(
            a["vinculado"] for a in agentes),
    })


# ── 7 · Vincular agente y repositorio ────────────────────────────────────────

def link_agent_repo(project, agent_id, repo_url, rama="staging",
                    rama_principal="main", client=None, gh=None, on_log=None):
    """Onboarding de un proyecto nuevo: detecta la región, registra y trae.

    Con dos datos —ID del agente y URL del repositorio— deja el pipeline
    listo. Lo único que no hace es conceder IAM: devuelve el comando exacto
    para ejecutarlo a mano una vez, fuera del panel (S6b).
    """
    log = []
    firestore_client = client or store.get_client()
    repo = _repo_desde_url(repo_url)

    _emit(log, on_log, f"· Detectando la región de {agent_id}")
    region = cx.detect_agent_region(project, agent_id)
    _emit(log, on_log, f"✓ Región detectada: {region}")

    github = gh or GitHubAppClient(repo)
    github.branch_head(rama)
    _emit(log, on_log, f"✓ Acceso al repositorio {repo}, rama {rama}")

    store.save_agent_mapping(firestore_client, project, agent_id, region, repo,
                             rama, rama_principal)
    _emit(log, on_log, "✓ Mapeo agente → repositorio registrado")

    marcador = yaml.safe_dump({
        "project": project, "agent_id": agent_id, "region": region,
        "rama": rama, "rama_principal": rama_principal,
        "vinculado_en": _ahora().isoformat(),
    }, allow_unicode=True, sort_keys=False)
    commit = github.commit_files(
        rama, {"cx-deploy.yaml": marcador},
        f"chore(onboarding): marcar el repositorio como proyecto CX {agent_id}",
    )
    if commit:
        _emit(log, on_log, f"✓ cx-deploy.yaml · commit {commit[:7]}")

    comando_iam = (
        f"gcloud projects add-iam-policy-binding {project} "
        f"--member=serviceAccount:$ACT_SERVICE_ACCOUNT "
        f"--role=roles/dialogflow.admin"
    )
    _emit(log, on_log,
          "Falta un paso manual: ejecuta el comando IAM que devuelve este paso")

    return step_result("ok", log, {
        "project": project, "agent_id": agent_id, "region": region,
        "repo": repo, "rama": rama, "commit": commit,
        "comando_iam": comando_iam,
    })


def _repo_desde_url(repo_url):
    """De una URL de GitHub a 'owner/nombre'."""
    limpio = (repo_url or "").strip().rstrip("/")
    limpio = re.sub(r"^https?://github\.com/", "", limpio)
    limpio = re.sub(r"\.git$", "", limpio)
    if not re.match(r"^[^/]+/[^/]+$", limpio):
        raise ValueError(
            f"No se reconoce como repositorio de GitHub: {repo_url!r}. "
            f"Formato esperado: https://github.com/usuario/repo"
        )
    return limpio


# ── 8 · Versiones existentes ─────────────────────────────────────────────────

def manage_versions(project, agent_id, action="list", version_names=None,
                    client=None, gh=None, on_log=None):
    """Lista las versiones que guarda el agente, o borra las que se marquen.

    Las que un entorno está sirviendo no se pueden borrar: se devuelven
    marcadas para que el panel no deje marcarlas.
    """
    log = []
    contexto = Contexto(project, agent_id, client=client, gh=gh)
    inventario, _, _ = inventariar_cx(contexto, on_log, log)

    en_uso = set()
    for entorno in inventario.get("environment", {}).values():
        for config in entorno.get("versionConfigs", []):
            en_uso.add(config["version"])

    if action == "list":
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
        _emit(log, on_log,
              f"✓ {len(versiones)} versiones · {len(en_uso)} en uso")
        return step_result("ok", log, {"versiones": versiones})

    if action != "delete":
        raise ValueError(
            f"Acción no reconocida: {action!r}. Solo 'list' o 'delete'."
        )

    borradas, protegidas = [], []
    with store.agent_lock(contexto.store, project, agent_id, "borrar versiones"):
        for nombre in version_names or ():
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


# ── 9 · Desplegar un resource suelto ─────────────────────────────────────────

def deploy_single_resource(project, agent_id, tipo, cx_id, client=None, gh=None,
                           on_log=None):
    """Aplica un solo YAML en el borrador, sin pasar por el diff completo.

    Sirve para iterar rápido sobre un resource mientras se ajusta. Lee el
    archivo del repositorio por su `metadata.cx_id` y el estado actual de CX
    en el momento de llamar — no depende de ninguna foto de un paso anterior.

    **Nunca puede llegar a producción.** No es una comprobación que pueda
    fallar: la URL que construye es siempre la del borrador
    (`.../{tipo}/{cx_id}`), y en ningún camino de este código existe una
    variable o parámetro por el que pueda aparecer `/environments/`. Es una
    capacidad que el código no tiene, no una regla que haya que respetar.
    """
    log = []
    # Contra TIPOS_DESPLEGABLES, no contra RESOURCE_TYPES: la tabla que esta
    # función consulta no contiene `environment`, así que el tipo que llegue
    # nunca puede resolver a un endpoint de entorno.
    if tipo not in TIPOS_DESPLEGABLES:
        raise ValueError(
            f"Esta herramienta no despliega '{tipo}'. Tipos que admite: "
            f"{', '.join(sorted(TIPOS_DESPLEGABLES))}."
        )
    contexto = Contexto(project, agent_id, client=client, gh=gh)

    # Solo su tipo y el padre del que cuelga: ni pide entornos ni los lee.
    necesarios = [tipo]
    padre = TIPOS_DESPLEGABLES[tipo].get("padre")
    if padre:
        necesarios.insert(0, padre)
    inventario, _, _ = inventariar_cx(contexto, on_log, log, tipos=necesarios)
    repositorio, _ = cargar_repositorio(contexto, on_log, log)

    entrada = repositorio["por_tipo"].get(tipo, {}).get(cx_id)
    if entrada is None:
        raise PipelineError(
            f"Ningún archivo del repositorio declara {tipo} con cx_id {cx_id}."
        )

    remoto = inventario.get(tipo, {}).get(cx_id)
    local = payloads.comparable_local(tipo, entrada["documento"])
    if remoto is None:
        operacion = _operacion("POST", tipo, cx_id, entrada, local)
    elif not payloads.differs(remoto, local):
        _emit(log, on_log, f"· {tipo}/{cx_id} ya coincide — nada que aplicar")
        return step_result("ok", log, {"aplicado": False, "ruta": entrada["ruta"]})
    else:
        operacion = _operacion("PATCH", tipo, cx_id, entrada, local,
                               remote_name=remoto["name"])

    with store.agent_lock(contexto.store, project, agent_id,
                          f"desplegar {tipo}/{cx_id}"):
        resultados, fallo, _ = aplicar_operaciones(
            contexto, [operacion], inventario, on_log, log
        )

    resultado = step_result("error" if fallo else "ok", log, {
        "aplicado": not fallo, "ruta": entrada["ruta"],
        "operacion": resultados[0],
    })
    store.record_run(contexto.store, project, agent_id, "deploy-resource",
                     resultado["status"], log, {"tipo": tipo, "cx_id": cx_id})
    return resultado
