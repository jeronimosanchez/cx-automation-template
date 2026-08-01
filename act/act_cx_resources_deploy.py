#!/usr/bin/env python3
"""
act/act_cx_resources_deploy.py — Orquestador del pipeline de deploy a Dialogflow CX.

Ejecuta los 8 pasos definidos en docs/panels/act_cx_resources_deploy.html:

    1. Inventario CX          5. Snapshot del agente
    2. Push a GitHub staging  6. Validación de tests
    3. Diff GitHub vs CX      7. Gate QA — staging
    4. Confirmar deploy       8. Aprobar producción

Cada paso es una función fina que orquesta; el trabajo real sobre recursos
vive en las funciones por tipo (inventory_*, diff_*, deploy_*).

Funciona completo por CLI, sin server.py ni el panel. El proyecto y el
agente son obligatorios y no tienen valor por defecto — el pipeline opera
sobre más de un agente y adivinar el destino sería el peor fallo posible.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.utils import cx_client
from act.utils.cx_payloads import build_full_update_body

DEFINITIONS_DIR = REPO_ROOT / "definitions"
DATA_DIR = REPO_ROOT / "docs" / "data"
LOGS_DIR = REPO_ROOT / "logs"

STAGING_BRANCH = "staging"
# El Paso 3 compara contra lo que está subido a GitHub, no contra el disco.
DEFINITIONS_REF = "origin/staging"
MAIN_BRANCH = "main"
STAGING_ENVIRONMENT = "staging"
PRODUCTION_ENVIRONMENT = "production"

# La API no expone ninguna señal de cuándo termina de propagarse un entorno
# (GET /deployments vuelve vacío), así que el paso lo dice en vez de fingir
# certeza o esperar con un sleep().
PROPAGATION_NOTICE = (
    "El cambio se ha aplicado, pero puede tardar unos minutos en propagarse a "
    "todos los usuarios. Si pruebas producción ahora mismo y ves comportamiento "
    "antiguo, espera y reintenta antes de asumir que el deploy falló."
)


# ── Tabla de recursos ────────────────────────────────────────────────────────
#
# `api` es el segmento de ruta bajo el agente; `key` el campo del JSON que
# contiene los ítems en la respuesta LIST; `definitions` la carpeta local.
# `nested_under` marca los tipos que no cuelgan del agente directamente.

RESOURCE_TYPES = {
    "entity_types":  {"api": "entityTypes",  "key": "entityTypes",  "definitions": "entity_types"},
    "intents":       {"api": "intents",      "key": "intents",      "definitions": "intents"},
    "webhooks":      {"api": "webhooks",     "key": "webhooks",     "definitions": "webhooks"},
    "tools":         {"api": "tools",        "key": "tools",        "definitions": "tools"},
    "generators":    {"api": "generators",   "key": "generators",   "definitions": "generators"},
    "playbooks":     {"api": "playbooks",    "key": "playbooks",    "definitions": "playbooks",
                      "full_update": True},
    "examples":      {"api": "examples",     "key": "examples",     "definitions": "examples",
                      "nested_under": "playbooks"},
    "flows":         {"api": "flows",        "key": "flows",        "definitions": "flows"},
    "pages":         {"api": "pages",        "key": "pages",        "definitions": "pages",
                      "nested_under": "flows"},
    "agent_config":  {"api": "",             "key": "",             "definitions": "config",
                      "singular": True},
    "environments":  {"api": "environments", "key": "environments", "definitions": "environments"},
    "versions":      {"api": "versions",     "key": "versions",     "definitions": "versions",
                      "nested_under": "flows"},
}

# Los tipos referenciados por otros van primero: si un playbook apunta a un
# webhook, el webhook tiene que existir antes del PATCH del playbook.
# Pages queda fuera (Regla 9: definitions/pages/ está vacío, enfoque generativo).
# Environments y Versions no se despliegan aquí — son los Pasos 5 a 8.
DEPLOY_ORDER = [
    "entity_types", "intents", "webhooks", "tools", "generators",
    "playbooks", "examples", "flows", "agent_config",
]


class PipelineError(RuntimeError):
    """Fallo que detiene el pipeline."""


# ── Utilidades ───────────────────────────────────────────────────────────────

def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _slug(value):
    return "".join(char if char.isalnum() or char in "-_" else "-" for char in value)


def inventory_path(project, agent_id):
    """Ruta del inventario, con proyecto y agente en el nombre.

    Sin ellos, correr el pipeline sobre un agente y luego sobre otro
    sobrescribiría el inventario del primero y el diff del Paso 3 se
    calcularía contra el agente equivocado, sin ningún error visible.
    """
    return DATA_DIR / f"act_cx_draft_resources_inventory_{_slug(project)}_{_slug(agent_id)}.json"


def log_path(project, agent_id):
    return LOGS_DIR / f"deploy_{_slug(project)}_{_slug(agent_id)}_{_timestamp()}.log"


def write_run_log(project, agent_id, lines):
    """Historial persistente de cada ejecución real — la terminal se pierde al cerrarla."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path(project, agent_id)
    path.write_text("\n".join(lines) + "\n")
    return path


def run_git(*args, check=True):
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise PipelineError(f"git {' '.join(args)} falló: {result.stderr.strip()}")
    return result


def step_result(status, log, data=None):
    return {"status": status, "log": log, "data": data or {}}


# ── Definiciones locales ─────────────────────────────────────────────────────

def definitions_belong_to(project, agent_id, ref=DEFINITIONS_REF):
    """Si definitions/ describe al agente seleccionado.

    definitions/ solo tiene contenido real para el agente de referencia. Para
    cualquier otro, aplicar estos YAMLs sería desplegar el agente equivocado
    encima — de ahí que el diff salga vacío con aviso en vez de fallar.
    """
    try:
        config = yaml.safe_load(_git_file_contents(ref, "definitions/agent.yaml")) or {}
    except PipelineError:
        return False
    return config.get("project") == project and config.get("agent_id") == agent_id


def fetch_definitions_ref(ref=DEFINITIONS_REF):
    """Actualiza la referencia remota antes de leerla.

    Sin el fetch, se leería la última copia local de la rama, que puede
    llevar días sin refrescar — el diff saldría contra código viejo sin
    ningún aviso.
    """
    remote, _, branch = ref.partition("/")
    if not branch:
        return
    result = run_git("fetch", remote, branch, check=False)
    if result.returncode != 0:
        raise PipelineError(
            f"No se pudo actualizar {ref}: {result.stderr.strip()}"
        )


def _git_tree_files(ref, directory):
    result = run_git("ls-tree", "-r", "--name-only", ref, "--", directory, check=False)
    if result.returncode != 0:
        raise PipelineError(
            f"No se pudo leer {directory} en {ref}: {result.stderr.strip()}. "
            f"¿Existe la rama?"
        )
    return [line for line in result.stdout.splitlines() if line.endswith(".yaml")]


def _git_file_contents(ref, path):
    result = run_git("show", f"{ref}:{path}", check=False)
    if result.returncode != 0:
        raise PipelineError(f"No se pudo leer {path} en {ref}: {result.stderr.strip()}")
    return result.stdout


def load_definitions(resource_type, ref=DEFINITIONS_REF):
    """YAMLs de un tipo, indexados por displayName.

    Se leen del árbol de `ref` (por defecto origin/staging), no del disco.
    El pipeline solo despliega lo que está commiteado y subido: si leyera el
    working tree, podría aplicar a CX un cambio que no existe en ninguna
    rama, y el agente quedaría sin respaldo en el historial de git.

    Con ref=None lee del disco — solo para inspección local, nunca para el
    Paso 3.
    """
    if resource_type == "agent_config":
        return _load_agent_config(ref)

    directory = f"definitions/{RESOURCE_TYPES[resource_type]['definitions']}"

    if ref is None:
        paths = sorted(
            str(path.relative_to(REPO_ROOT))
            for path in (REPO_ROOT / directory).rglob("*.yaml")
        ) if (REPO_ROOT / directory).exists() else []
        contents = ((path, (REPO_ROOT / path).read_text()) for path in paths)
    else:
        contents = ((path, _git_file_contents(ref, path))
                    for path in sorted(_git_tree_files(ref, directory)))

    definitions = {}
    for _, text in contents:
        document = yaml.safe_load(text)
        if not isinstance(document, dict):
            continue
        display_name = document.get("displayName")
        if display_name:
            definitions[display_name] = document
    return definitions


def _load_agent_config(ref=DEFINITIONS_REF):
    path = "definitions/agent.yaml"
    if ref is None:
        agent_file = REPO_ROOT / path
        if not agent_file.exists():
            return {}
        text = agent_file.read_text()
    else:
        text = _git_file_contents(ref, path)
    config = yaml.safe_load(text) or {}
    definition = config.get("agent_definition")
    return {definition["displayName"]: definition} if definition else {}


# Compatibilidad para inspección local — el Paso 3 usa load_definitions(ref).
def load_local_definitions(resource_type):
    return load_definitions(resource_type, ref=None)


# ── Inventario — una función por tipo ────────────────────────────────────────
#
# El matching del diff usa displayName como clave: los YAMLs locales no
# tienen `name` (ese campo es la ruta completa que asigna CX al crear el
# recurso, con un UUID que el repo no puede conocer de antemano).

def _list_resources(project, agent_id, resource_type):
    spec = RESOURCE_TYPES[resource_type]
    parent = cx_client.build_parent(project, agent_id)

    if spec.get("singular"):
        response = cx_client.api_get(project, parent)
        if response.status_code != 200:
            raise PipelineError(
                f"GET del agente falló: {response.status_code} {response.text[:200]}"
            )
        return [response.json()]

    if spec.get("nested_under"):
        parent_type = spec["nested_under"]
        items = []
        for container in _list_resources(project, agent_id, parent_type):
            items.extend(
                cx_client.list_all_pages(
                    project, f"{container['name']}/{spec['api']}", spec["key"]
                )
            )
        return items

    return cx_client.list_all_pages(project, f"{parent}/{spec['api']}", spec["key"])


def inventory_entity_types(project, agent_id):
    return _list_resources(project, agent_id, "entity_types")


def inventory_intents(project, agent_id):
    return _list_resources(project, agent_id, "intents")


def inventory_webhooks(project, agent_id):
    return _list_resources(project, agent_id, "webhooks")


def inventory_tools(project, agent_id):
    return _list_resources(project, agent_id, "tools")


def inventory_generators(project, agent_id):
    return _list_resources(project, agent_id, "generators")


def inventory_playbooks(project, agent_id):
    return _list_resources(project, agent_id, "playbooks")


def inventory_examples(project, agent_id):
    return _list_resources(project, agent_id, "examples")


def inventory_flows(project, agent_id):
    return _list_resources(project, agent_id, "flows")


def inventory_pages(project, agent_id):
    return _list_resources(project, agent_id, "pages")


def inventory_agent_config(project, agent_id):
    return _list_resources(project, agent_id, "agent_config")


def inventory_environments(project, agent_id):
    return _list_resources(project, agent_id, "environments")


def inventory_versions(project, agent_id):
    return _list_resources(project, agent_id, "versions")


INVENTORY_FUNCTIONS = {
    "entity_types": inventory_entity_types,
    "intents": inventory_intents,
    "webhooks": inventory_webhooks,
    "tools": inventory_tools,
    "generators": inventory_generators,
    "playbooks": inventory_playbooks,
    "examples": inventory_examples,
    "flows": inventory_flows,
    "pages": inventory_pages,
    "agent_config": inventory_agent_config,
    "environments": inventory_environments,
    "versions": inventory_versions,
}


# ── Diff — una función por tipo ──────────────────────────────────────────────

def _diff_generic(resource_type, remote_items, local_definitions):
    """POST lo que falta en CX, PATCH lo que cambió, DELETE lo que sobra.

    Las tres operaciones son mutuamente excluyentes por recurso: un recurso
    no puede ser nuevo y modificado a la vez.
    """
    remote_by_name = {
        item.get("displayName"): item
        for item in remote_items
        if item.get("displayName")
    }
    operations = []

    for display_name, local in local_definitions.items():
        comparable = _comparable_local(resource_type, local)
        remote = remote_by_name.get(display_name)
        if remote is None:
            operations.append({
                "type": resource_type, "resource": display_name,
                "operation": "POST", "local": comparable, "source": local,
            })
        elif _differs(remote, comparable):
            operations.append({
                "type": resource_type, "resource": display_name,
                "operation": "PATCH", "local": comparable,
                "source": local, "remote_name": remote["name"],
            })

    for display_name, remote in remote_by_name.items():
        if display_name not in local_definitions:
            operations.append({
                "type": resource_type, "resource": display_name,
                "operation": "DELETE", "remote_name": remote["name"],
            })

    return operations


# Campos que existen en los YAML del repo pero no en el recurso de la API
# (verificado contra el discovery document). Comparar por ellos hacía que
# cada recurso saliera siempre como PATCH, y mandarlos en el body haría que
# la API rechazara la llamada.
LOCAL_ONLY_FIELDS = {
    "examples": ("id", "playbook"),
    "tools": ("openapi_spec_file",),
    "agent_config": ("start_playbook_id",),
}


def _is_empty(value):
    return value in (None, [], {}, "")


def _comparable_local(resource_type, local):
    ignorados = LOCAL_ONLY_FIELDS.get(resource_type, ())
    return {k: v for k, v in local.items() if k not in ignorados}


def _differs(remote, local):
    """Si algún campo declarado en el YAML local no coincide con el remoto.

    Compara solo los campos que el local declara: los que no menciona se
    preservan del remoto, así que su valor no es una diferencia.

    Un campo vacío en el YAML y ausente en la respuesta de la API son lo
    mismo — CX omite los campos vacíos en lugar de devolverlos vacíos. Sin
    esta equivalencia, `inputParameterDefinitions: []` frente a un remoto
    que no trae el campo se lee como diferencia y el recurso sale como
    PATCH en cada ejecución, rompiendo la idempotencia.
    """
    for field, value in local.items():
        remote_value = remote.get(field)
        if remote_value == value:
            continue
        if _is_empty(value) and _is_empty(remote_value):
            continue
        return True
    return False


def diff_entity_types(remote_items, local_definitions):
    return _diff_generic("entity_types", remote_items, local_definitions)


def diff_intents(remote_items, local_definitions):
    return _diff_generic("intents", remote_items, local_definitions)


def diff_webhooks(remote_items, local_definitions):
    return _diff_generic("webhooks", remote_items, local_definitions)


def diff_tools(remote_items, local_definitions):
    """Los tools integrados de la plataforma no son recursos del repo.

    Sin este filtro salen como DELETE por no estar en definitions/, y el
    Paso 4 intentaría borrar un tool que CX provee (code-interpreter).
    """
    propios = [t for t in remote_items if t.get("toolType") != "BUILTIN_TOOL"]
    return _diff_generic("tools", propios, local_definitions)


def diff_generators(remote_items, local_definitions):
    return _diff_generic("generators", remote_items, local_definitions)


def diff_playbooks(remote_items, local_definitions):
    return _diff_generic("playbooks", remote_items, local_definitions)


def diff_examples(remote_items, local_definitions):
    return _diff_generic("examples", remote_items, local_definitions)


def diff_flows(remote_items, local_definitions):
    return _diff_generic("flows", remote_items, local_definitions)


def diff_pages(remote_items, local_definitions):
    """Fuera de alcance (Regla 9): definitions/pages/ está vacío — Petal usa
    el enfoque generativo, donde los Playbooks sustituyen la navegación."""
    return []


def diff_agent_config(remote_items, local_definitions):
    return _diff_generic("agent_config", remote_items, local_definitions)


def diff_environments(remote_items, local_definitions):
    """Los entornos los mueven los Pasos 5 a 8, no el deploy del Paso 4."""
    return []


def diff_versions(remote_items, local_definitions):
    """Las versiones las crea el Paso 5 — no se despliegan desde definitions/."""
    return []


DIFF_FUNCTIONS = {
    "entity_types": diff_entity_types,
    "intents": diff_intents,
    "webhooks": diff_webhooks,
    "tools": diff_tools,
    "generators": diff_generators,
    "playbooks": diff_playbooks,
    "examples": diff_examples,
    "flows": diff_flows,
    "pages": diff_pages,
    "agent_config": diff_agent_config,
    "environments": diff_environments,
    "versions": diff_versions,
}


# ── Deploy — una función por tipo ────────────────────────────────────────────

def _deploy_generic(project, agent_id, operation, full_update=False):
    spec = RESOURCE_TYPES[operation["type"]]
    parent = cx_client.build_parent(project, agent_id)

    if operation["operation"] == "DELETE":
        response = cx_client.api_delete(project, operation["remote_name"])
    elif operation["operation"] == "POST":
        response = cx_client.api_post(
            project, f"{parent}/{spec['api']}", operation["local"]
        )
    elif full_update:
        response = _patch_full_update(project, operation)
    else:
        response = cx_client.api_patch(
            project, operation["remote_name"], operation["local"]
        )

    if response.status_code not in (200, 201):
        raise PipelineError(
            f"{operation['operation']} {operation['resource']} falló: "
            f"{response.status_code} {response.text[:200]}"
        )
    return response.json() if response.text else {}


def _patch_full_update(project, operation):
    """GET completo → merge → PATCH sin updateMask.

    PATCH con updateMask falla silenciosamente en europe-west1 (bug del
    backend, §3.8): devuelve 200 pero no aplica los cambios.
    """
    current = cx_client.api_get(project, operation["remote_name"])
    if current.status_code != 200:
        raise PipelineError(
            f"GET previo a Full Update de {operation['resource']} falló: "
            f"{current.status_code} {current.text[:200]}"
        )
    body = build_full_update_body(current.json(), operation["local"])
    return cx_client.api_patch(project, operation["remote_name"], body)


def deploy_entity_types(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_intents(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_webhooks(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_tools(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_generators(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_playbooks(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation, full_update=True)


def deploy_examples(project, agent_id, operation):
    """Los examples cuelgan de su playbook, no del agente."""
    if operation["operation"] == "POST":
        playbook_name = _resolve_playbook_name(
            project, agent_id, operation["local"].get("playbook")
        )
        response = cx_client.api_post(
            project, f"{playbook_name}/examples", operation["local"]
        )
        if response.status_code not in (200, 201):
            raise PipelineError(
                f"POST example {operation['resource']} falló: "
                f"{response.status_code} {response.text[:200]}"
            )
        return response.json()
    return _deploy_generic(project, agent_id, operation)


def _resolve_playbook_name(project, agent_id, playbook_display_name):
    for playbook in inventory_playbooks(project, agent_id):
        if playbook.get("displayName") == playbook_display_name:
            return playbook["name"]
    raise PipelineError(
        f"El example referencia el playbook '{playbook_display_name}', "
        f"que no existe en CX."
    )


def deploy_flows(project, agent_id, operation):
    return _deploy_generic(project, agent_id, operation)


def deploy_agent_config(project, agent_id, operation):
    """El agente es un objeto único: siempre PATCH sobre sí mismo."""
    parent = cx_client.build_parent(project, agent_id)
    response = cx_client.api_patch(project, parent, operation["local"])
    if response.status_code != 200:
        raise PipelineError(
            f"PATCH del agent config falló: "
            f"{response.status_code} {response.text[:200]}"
        )
    return response.json()


DEPLOY_FUNCTIONS = {
    "entity_types": deploy_entity_types,
    "intents": deploy_intents,
    "webhooks": deploy_webhooks,
    "tools": deploy_tools,
    "generators": deploy_generators,
    "playbooks": deploy_playbooks,
    "examples": deploy_examples,
    "flows": deploy_flows,
    "agent_config": deploy_agent_config,
}


# ── Entornos y versiones ─────────────────────────────────────────────────────

def find_environment(project, agent_id, display_name):
    for environment in inventory_environments(project, agent_id):
        if environment.get("displayName", "").lower() == display_name.lower():
            return environment
    return None


def default_flow_name(project, agent_id):
    flows = inventory_flows(project, agent_id)
    if not flows:
        raise PipelineError("El agente no tiene ningún flow — no se puede versionar.")
    return flows[0]["name"]


def point_environment_at_versions(project, environment, version_names):
    """Fija en el entorno el conjunto completo de versiones.

    Tres cosas que la API exige aquí y que no son obvias:
      - updateMask es obligatorio (al revés que en Playbooks, §3.8).
      - la respuesta es una operación asíncrona, no el entorno.
      - las versiones viajan juntas: un playbook fijado sin la versión del
        tool que referencia hace fallar el PATCH entero.
    """
    body = {"versionConfigs": [{"version": name} for name in version_names]}
    response = cx_client.api_patch(
        project, environment["name"], body, params={"updateMask": "versionConfigs"}
    )
    if response.status_code != 200:
        raise PipelineError(
            f"PATCH del entorno {environment.get('displayName')} falló: "
            f"{response.status_code} {response.text[:200]}"
        )
    cx_client.resolve_operation(project, response)
    return verify_environment_versions(project, environment["name"], version_names)


def verify_environment_versions(project, environment_name, expected_names):
    """Un 200 confirma que la petición se aceptó, no que el estado sea correcto."""
    current = cx_client.api_get(project, environment_name)
    if current.status_code != 200:
        raise PipelineError(f"GET del entorno falló: {current.status_code}")
    applied = {config["version"] for config in current.json().get("versionConfigs", [])}
    faltan = set(expected_names) - applied
    if faltan:
        raise PipelineError(
            f"El entorno no quedó con las versiones esperadas — faltan {len(faltan)}: "
            f"{sorted(name.rsplit('/', 3)[-3:] for name in faltan)[:3]}"
        )
    return current.json()


def referenced_tool_names(project, agent_id):
    """Tools que algún playbook referencia — los que el entorno va a exigir."""
    referenced = set()
    for playbook in inventory_playbooks(project, agent_id):
        referenced.update(playbook.get("referencedTools", []))
    return sorted(referenced)


def create_versions_for_snapshot(project, agent_id, display_name):
    """Crea la cadena completa de versiones y devuelve sus rutas.

    Flow, playbooks y tools tienen endpoints de versión independientes. El
    entorno los necesita los tres: fijar solo una capa hace fallar el PATCH.
    """
    version_names = []

    for flow in inventory_flows(project, agent_id):
        response = cx_client.api_post(
            project, f"{flow['name']}/versions", {"displayName": display_name}
        )
        if response.status_code not in (200, 201):
            raise PipelineError(
                f"POST /versions del flow {flow.get('displayName')} falló: "
                f"{response.status_code} {response.text[:200]}"
            )
        created = cx_client.resolve_operation(project, response)
        version_names.append(created["name"])

    for playbook in inventory_playbooks(project, agent_id):
        response = cx_client.api_post(
            project, f"{playbook['name']}/versions", {"description": display_name}
        )
        if response.status_code not in (200, 201):
            raise PipelineError(
                f"POST /versions del playbook {playbook.get('displayName')} falló: "
                f"{response.status_code} {response.text[:200]}"
            )
        version_names.append(cx_client.resolve_operation(project, response)["name"])

    for tool_name in referenced_tool_names(project, agent_id):
        response = cx_client.api_post(project, f"{tool_name}/versions", {})
        # Los tools integrados de CX (code-interpreter) no son versionables:
        # devuelven 404 y no hay nada que fijar para ellos en el entorno.
        if response.status_code == 404:
            continue
        if response.status_code not in (200, 201):
            raise PipelineError(
                f"POST /versions del tool {tool_name} falló: "
                f"{response.status_code} {response.text[:200]}"
            )
        version_names.append(cx_client.resolve_operation(project, response)["name"])

    return version_names


def restore_draft_from_versions(project, version_names):
    """Devuelve el draft a un conjunto de versiones.

    Cada tipo usa su propio verbo: los flows se cargan con :load, los
    playbooks se restauran con :restore.
    """
    for version_name in version_names:
        verb = "restore" if "/playbooks/" in version_name else "load"
        if "/tools/" in version_name:
            continue
        response = cx_client.api_post(project, f"{version_name}:{verb}", {})
        if response.status_code not in (200, 201):
            raise PipelineError(
                f"Restaurar el draft desde {version_name} falló: "
                f"{response.status_code} {response.text[:200]}"
            )
        cx_client.resolve_operation(project, response)


# ── Paso 1 — Inventario CX ───────────────────────────────────────────────────

def preflight_check(project, agent_id):
    """Auth y conectividad antes de las 12 llamadas LIST.

    Sin esto, un fallo de credenciales aparece a mitad del inventario y no
    queda claro en qué recurso falló.
    """
    cx_client.get_token()
    response = cx_client.api_get(project, cx_client.build_parent(project, agent_id))
    if response.status_code != 200:
        raise PipelineError(
            f"No se puede acceder al agente {agent_id} del proyecto {project}: "
            f"{response.status_code} {response.text[:200]}"
        )
    return response.json()


def step_1_inventory(project, agent_id, dry_run=False):
    log = [f"Paso 1 — Inventario CX · {project} / {agent_id}"]

    agent = preflight_check(project, agent_id)
    log.append(f"Pre-flight OK — agente '{agent.get('displayName', agent_id)}' accesible")

    if dry_run:
        log.append("[dry-run] No se ejecutan las 12 llamadas LIST")
        return step_result("ok", log, {"dry_run": True})

    resources, totals = {}, {}
    for resource_type, fetch in INVENTORY_FUNCTIONS.items():
        items = fetch(project, agent_id)
        resources[resource_type] = items
        totals[resource_type] = len(items)
        log.append(f"LIST {resource_type}: {len(items)}")

    _verify_inventory_integrity(resources, totals)

    if sum(totals.values()) == 0:
        log.append(
            "Aviso: el agente no tiene ningún recurso. "
            "Es legítimo en un agente recién creado — el pipeline continúa."
        )

    inventory = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agent": {"project": project, "agent_id": agent_id, "location": cx_client.LOCATION},
        "totals": totals,
        "resources": resources,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = inventory_path(project, agent_id)
    path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False))
    log.append(f"Inventario escrito en {path.relative_to(REPO_ROOT)}")

    return step_result("ok", log, {"totals": totals, "inventory_path": str(path)})


def _verify_inventory_integrity(resources, totals):
    for resource_type in RESOURCE_TYPES:
        items = resources.get(resource_type)
        if items is None:
            raise PipelineError(
                f"El tipo {resource_type} no se pudo listar — inventario incompleto."
            )
        if totals[resource_type] != len(items):
            raise PipelineError(
                f"Conteo incoherente en {resource_type}: "
                f"{totals[resource_type]} declarados, {len(items)} reales."
            )
        for item in items:
            if not item.get("name"):
                raise PipelineError(
                    f"Un recurso de {resource_type} no tiene 'name' — "
                    f"el diff lo necesita para operar sobre él."
                )


def load_inventory(project, agent_id):
    path = inventory_path(project, agent_id)
    if not path.exists():
        raise PipelineError(
            f"No existe el inventario de {project}/{agent_id}. "
            f"Ejecuta el Paso 1 antes del Paso 3."
        )
    return json.loads(path.read_text())


# ── Paso 2 — Push a GitHub staging ───────────────────────────────────────────

def pending_commits():
    run_git("fetch", "origin", STAGING_BRANCH, check=False)
    result = run_git(
        "log", f"origin/{STAGING_BRANCH}..{STAGING_BRANCH}", "--oneline", check=False
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def step_2_push_staging(project, agent_id, dry_run=False):
    log = [f"Paso 2 — Push a GitHub {STAGING_BRANCH}"]
    commits = pending_commits()

    if not commits:
        log.append("origin/staging ya está al día — 0 commits pendientes")
        return step_result("ok", log, {"pushed": False, "commits": []})

    log.append(f"{len(commits)} commits pendientes:")
    log.extend(f"  {commit}" for commit in commits)

    if dry_run:
        log.append("[dry-run] No se ejecuta git push")
        return step_result("ok", log, {"pushed": False, "commits": commits})

    result = run_git("push", "origin", STAGING_BRANCH, check=False)
    if result.returncode != 0:
        raise PipelineError(
            f"git push origin {STAGING_BRANCH} falló: {result.stderr.strip()}"
        )

    log.append("Push completado")
    return step_result("ok", log, {"pushed": True, "commits": commits})


# ── Paso 3 — Diff GitHub vs CX ───────────────────────────────────────────────

def step_3_diff(project, agent_id, dry_run=False, ref=DEFINITIONS_REF):
    log = [f"Paso 3 — Diff GitHub vs CX · {project} / {agent_id}"]
    fetch_definitions_ref(ref)
    log.append(f"definitions/ leído de {ref} — no del disco")

    if not definitions_belong_to(project, agent_id, ref):
        log.append(
            "Aviso: no hay definiciones locales para este agente. "
            "definitions/ describe otro agente — no se propone ninguna operación."
        )
        return step_result("ok", log, {"operations": [], "no_local_definitions": True})

    inventory = load_inventory(project, agent_id)
    operations = []

    for resource_type, diff in DIFF_FUNCTIONS.items():
        remote_items = inventory["resources"].get(resource_type, [])
        local_definitions = load_definitions(resource_type, ref=ref)
        type_operations = diff(remote_items, local_definitions)
        operations.extend(type_operations)
        log.append(f"diff {resource_type}: {len(type_operations)} operaciones")

    if not operations:
        log.append("Sin cambios detectados — el pipeline termina aquí")
        return step_result("ok", log, {"operations": [], "has_changes": False})

    summary = {"POST": 0, "PATCH": 0, "DELETE": 0}
    for operation in operations:
        summary[operation["operation"]] += 1
    log.append(
        f"Total: {len(operations)} operaciones "
        f"({summary['POST']} POST, {summary['PATCH']} PATCH, {summary['DELETE']} DELETE)"
    )

    warnings = unversionable_warnings(operations)
    log.extend(warnings)

    return step_result("ok", log, {
        "operations": operations, "has_changes": True, "summary": summary,
        "warnings": warnings,
    })


# Tipos sin ningún mecanismo de versión: no hay entorno que los aísle, así que
# un cambio en ellos es visible en draft, staging y producción a la vez.
UNVERSIONABLE_TYPES = ("agent_config", "generators")


def unversionable_warnings(operations):
    afectados = sorted({
        operation["type"] for operation in operations
        if operation["type"] in UNVERSIONABLE_TYPES
    })
    if not afectados:
        return []
    nombres = " / ".join(
        "Agent Config" if tipo == "agent_config" else "Generators" for tipo in afectados
    )
    return [
        f"AVISO — Este deploy incluye cambios en {nombres} — sin staging posible. "
        f"Serán visibles en todos los entornos a la vez al confirmar."
    ]


# ── Paso 4 — Confirmar deploy ────────────────────────────────────────────────

def step_4_deploy(project, agent_id, operations=None, dry_run=False, only_pending=False):
    log = [f"Paso 4 — Deploy · {project} / {agent_id}"]

    if operations is None:
        operations = step_3_diff(project, agent_id)["data"].get("operations", [])
    if only_pending:
        operations = [
            operation for operation in operations
            if operation.get("result") in (None, "ERROR", "NO_INTENTADO")
        ]

    ordered = sorted(
        operations,
        key=lambda operation: DEPLOY_ORDER.index(operation["type"])
        if operation["type"] in DEPLOY_ORDER else len(DEPLOY_ORDER),
    )

    log.extend(unversionable_warnings(ordered))

    if dry_run:
        log.append(f"[dry-run] Plan de {len(ordered)} operaciones en este orden:")
        log.extend(
            f"  {operation['operation']} {operation['type']}/{operation['resource']}"
            for operation in ordered
        )
        return step_result("ok", log, {"operations": ordered, "dry_run": True})

    results, failed = [], False
    for operation in ordered:
        if failed:
            operation["result"] = "NO_INTENTADO"
            log.append(f"—     {operation['type']}/{operation['resource']}")
        else:
            try:
                DEPLOY_FUNCTIONS[operation["type"]](project, agent_id, operation)
                operation["result"] = "OK"
                log.append(
                    f"OK    {operation['operation']} "
                    f"{operation['type']}/{operation['resource']}"
                )
            except PipelineError as error:
                operation["result"] = "ERROR"
                operation["error"] = str(error)
                failed = True
                log.append(f"ERROR {operation['type']}/{operation['resource']}: {error}")
        results.append(operation)

    status = "error" if failed else "ok"
    log.append("Deploy parcial — el draft quedó a medias" if failed else "Deploy completado")
    write_run_log(project, agent_id, log)

    return step_result(status, log, {
        "operations": results,
        "applied": sum(1 for item in results if item.get("result") == "OK"),
        "failed": failed,
    })


# ── Paso 5 — Snapshot del agente ─────────────────────────────────────────────

def generate_snapshot_name():
    return f"deploy_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M')}"


def step_5_snapshot(project, agent_id, name=None, dry_run=False):
    log = [f"Paso 5 — Snapshot · {project} / {agent_id}"]

    # displayName nunca se omite: sin él la API responde 200 OK y la operation
    # falla en silencio con code:3.
    display_name = (name or "").strip() or generate_snapshot_name()
    log.append(f"displayName del snapshot: {display_name}")

    if dry_run:
        log.append("[dry-run] No se crea la versión")
        return step_result("ok", log, {"snapshot_name": display_name, "dry_run": True})

    environment = find_environment(project, agent_id, STAGING_ENVIRONMENT)
    if environment is None:
        raise PipelineError(
            f"No existe el entorno '{STAGING_ENVIRONMENT}' en este agente."
        )

    previous = [
        config["version"] for config in environment.get("versionConfigs", [])
    ]
    version_names = create_versions_for_snapshot(project, agent_id, display_name)
    log.append(f"Snapshot creado — {len(version_names)} versiones:")
    log.extend(f"  {name.rsplit('/', 3)[-3]}/{name.rsplit('/', 1)[-1]}"
               for name in version_names)

    point_environment_at_versions(project, environment, version_names)
    log.append(
        f"Entorno {STAGING_ENVIRONMENT} fijado y verificado con las "
        f"{len(version_names)} versiones"
    )
    write_run_log(project, agent_id, log)

    return step_result("ok", log, {
        "snapshot_name": display_name,
        "version_names": version_names,
        "previous_versions": previous,
    })


# ── Pasos 6 y 7 — Gates humanos ──────────────────────────────────────────────

def _rollback_staging(project, agent_id, previous_versions, log):
    if not previous_versions:
        raise PipelineError(
            "No hay versiones anteriores registradas — no se puede hacer rollback."
        )
    environment = find_environment(project, agent_id, STAGING_ENVIRONMENT)
    point_environment_at_versions(project, environment, previous_versions)
    log.append(
        f"Entorno {STAGING_ENVIRONMENT} devuelto a {len(previous_versions)} versiones"
    )
    restore_draft_from_versions(project, previous_versions)
    log.append("Draft restaurado desde esas mismas versiones")


def step_6_validate_tests(project, agent_id, decision="passed",
                          previous_versions=None, dry_run=False):
    """Punto de decisión: no ejecuta tests ni llama a la API si se avanza."""
    log = [f"Paso 6 — Validación de tests · decisión: {decision}"]

    if decision == "passed":
        log.append("Tests superados — avanza al Paso 7 sin ninguna llamada a la API")
        return step_result("ok", log, {"advance": True})

    if decision == "cancelled":
        log.append("Rollback cancelado — staging y draft quedan sin tocar")
        return step_result("ok", log, {"advance": False, "rolled_back": False})

    if dry_run:
        log.append("[dry-run] No se ejecuta el rollback")
        return step_result("ok", log, {"advance": False, "dry_run": True})

    _rollback_staging(project, agent_id, previous_versions, log)
    log.append("Pipeline abortado — producción no se ha tocado")
    write_run_log(project, agent_id, log)
    return step_result("aborted", log, {"advance": False, "rolled_back": True})


def step_7_qa_gate(project, agent_id, decision="validated",
                   previous_versions=None, dry_run=False):
    log = [f"Paso 7 — Gate QA staging · decisión: {decision}"]

    if decision == "validated":
        log.append("Validado — avanza al Paso 8 sin ninguna llamada a la API")
        return step_result("ok", log, {"advance": True})

    if dry_run:
        log.append("[dry-run] No se ejecuta el rollback")
        return step_result("ok", log, {"advance": False, "dry_run": True})

    _rollback_staging(project, agent_id, previous_versions, log)
    log.append("Pipeline abortado — no hay camino para continuar")
    write_run_log(project, agent_id, log)
    return step_result("aborted", log, {"advance": False, "rolled_back": True})


# ── Paso 8 — Aprobar producción ──────────────────────────────────────────────

def merge_staging_into_main():
    result = subprocess.run(
        ["gh", "pr", "merge", STAGING_BRANCH, "--merge", "--body", ""],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()


def step_8_approve_production(project, agent_id, version_names=None, dry_run=False):
    """Merge primero, promoción después.

    Si la promoción fuera primero y el merge fallara, producción quedaría
    apuntando a un snapshot cuyo código no está en main.
    """
    log = [f"Paso 8 — Aprobar producción · {project} / {agent_id}"]

    if dry_run:
        log.append(f"[dry-run] 1. merge {STAGING_BRANCH} → {MAIN_BRANCH}")
        log.append(f"[dry-run] 2. PATCH /environments/{PRODUCTION_ENVIRONMENT}")
        return step_result("ok", log, {"dry_run": True})

    merged, detail = merge_staging_into_main()
    if not merged:
        log.append(f"El merge falló — no se toca producción: {detail}")
        return step_result("conflict", log, {"merged": False, "promoted": False})
    log.append(f"Merge {STAGING_BRANCH} → {MAIN_BRANCH} completado")

    staging = find_environment(project, agent_id, STAGING_ENVIRONMENT)
    if staging is None:
        raise PipelineError(f"No existe el entorno '{STAGING_ENVIRONMENT}'.")
    versions = version_names or [
        config["version"] for config in staging.get("versionConfigs", [])
    ]
    if not versions:
        raise PipelineError("El entorno staging no apunta a ninguna versión.")

    production = find_environment(project, agent_id, PRODUCTION_ENVIRONMENT)
    if production is None:
        raise PipelineError(f"No existe el entorno '{PRODUCTION_ENVIRONMENT}'.")

    point_environment_at_versions(project, production, versions)
    log.append(
        f"Producción promovida a las mismas {len(versions)} versiones que staging"
    )
    log.append(PROPAGATION_NOTICE)
    write_run_log(project, agent_id, log)

    return step_result("ok", log, {
        "merged": True, "promoted": True, "version_names": versions,
        "notice": PROPAGATION_NOTICE,
    })


STEP_FUNCTIONS = {
    1: step_1_inventory,
    2: step_2_push_staging,
    3: step_3_diff,
    4: step_4_deploy,
    5: step_5_snapshot,
    6: step_6_validate_tests,
    7: step_7_qa_gate,
    8: step_8_approve_production,
}


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Pipeline de deploy de recursos CX (8 pasos)."
    )
    parser.add_argument("--project", required=True, help="ID del proyecto GCP")
    parser.add_argument("--agent", required=True, help="ID del agente de Dialogflow CX")
    parser.add_argument(
        "--step", type=int, choices=range(1, 9),
        help="Ejecuta un solo paso. Sin este flag, recorre del 1 al 3.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Previsualiza sin escribir")
    parser.add_argument("--snapshot-name", help="displayName del snapshot (Paso 5)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    steps = [args.step] if args.step else [1, 2, 3]

    try:
        for number in steps:
            step = STEP_FUNCTIONS[number]
            if number == 5:
                result = step(args.project, args.agent,
                              name=args.snapshot_name, dry_run=args.dry_run)
            else:
                result = step(args.project, args.agent, dry_run=args.dry_run)

            print("\n".join(result["log"]))
            if result["status"] not in ("ok",):
                return 1
            if number == 3 and not result["data"].get("has_changes", True):
                return 0
    except (PipelineError, cx_client.AuthError, cx_client.ApiError,
            cx_client.OperationTimeout) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
