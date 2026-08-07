"""
act/utils/cx_payloads_cloudrun.py — Adaptación entre los YAML del repositorio
y los cuerpos que acepta la API de Dialogflow CX.

Clon de act/utils/cx_payloads.py, ampliado con la regla de `metadata` (S18) y
con la comparación que el pipeline local tenía dentro del script de deploy.
Todo lo de aquí es puro: no hace ninguna llamada de red. Es deliberado — es lo
que permite que act/tests/test_cx_payloads_cloudrun.py cubra la lógica de
comparación sin depender de un agente real.

Dos cosas que este módulo resuelve y el original no:

1. **El bloque `metadata` nunca viaja a CX ni entra en la comparación** (S18).
   Cada YAML lleva `metadata: {tipo, padre, cx_id}` y el resto de sus campos
   sueltos al mismo nivel. Todo lo que está dentro de `metadata` se excluye;
   lo que está fuera se compara y se envía.

2. **Full Update sin `updateMask`**, heredado del original. En Playbooks es
   obligatorio por el bug de europe-west1 (CLAUDE.md §3.8); en el resto de
   tipos es lo correcto por otra razón — sin `updateMask` la API interpreta el
   body como el objeto entero, así que hay que mandarlo entero o borra lo que
   no se menciona. La excepción es Environments, que exige `updateMask`.
"""

METADATA_KEY = "metadata"


# Campos read-only del recurso Playbook. La API los devuelve en GET/LIST pero
# los rechaza en PATCH/POST.
PLAYBOOK_IGNORE_FIELDS = ["name", "tokenCount", "createTime", "updateTime"]

# Campos read-only del recurso Agent. `satisfiesPzi` / `satisfiesPzs` los añade
# Google y no se pueden enviar; `name` es la ruta que asigna la API.
AGENT_IGNORE_FIELDS = ["name", "satisfiesPzi", "satisfiesPzs"]

# `state` (ej. SUCCEEDED) es de solo lectura y no estaba en la lista conocida.
# Hay que leerlo para confirmar que una versión terminó bien, pero excluirlo de
# lo que se compara y se envía, igual que el resto de campos de solo lectura.
VERSION_IGNORE_FIELDS = ["name", "createTime", "state"]

DEFAULT_IGNORE_FIELDS = ["name"]

IGNORE_FIELDS_BY_TYPE = {
    "playbook": PLAYBOOK_IGNORE_FIELDS,
    "agent_config": AGENT_IGNORE_FIELDS,
    "version": VERSION_IGNORE_FIELDS,
}


# Campos que el YAML declara para uso local y que la API no conoce. Enviarlos
# haría que rechazara la llamada; compararlos haría que cada recurso saliera
# siempre como PATCH.
#
# NOTA: §12 del diseño pide una regla única —todo lo de dentro de `metadata`
# se excluye, todo lo de fuera se envía— y esta lista la contradice. Se
# mantiene porque los YAML reales todavía llevan estos campos fuera de
# `metadata` (verificado en definitions/examples/, que declaran `playbook` e
# `id` al nivel superior). Retirar la lista exige moverlos antes dentro de
# `metadata`, que es tocar los YAML.
LOCAL_ONLY_FIELDS = {
    "example": ("id", "playbook"),
    "page": ("flow",),
    "tool": ("openapi_spec_file",),
    "agent_config": ("start_playbook_id",),
}


# Campos cuya lista es un conjunto de referencias, no una secuencia: declaran a
# qué recursos puede llamar este, y el orden no significa nada. CX los devuelve
# en un orden propio. El resto de listas (instruction.steps, actions de los
# examples) sí son secuencias, y compararlas como conjunto ocultaría
# reordenaciones reales.
UNORDERED_FIELDS = ("referencedPlaybooks", "referencedTools", "referencedFlows")


# ── metadata ─────────────────────────────────────────────────────────────────

def read_metadata(document):
    """El bloque `metadata` de un YAML, o None si no lo lleva.

    Un YAML sin `metadata` no es un resource del pipeline: se ignora sin
    ruido. Los resources se declaran de forma explícita al crearlos, así que
    la ausencia del bloque no es un error que haya que perseguir.
    """
    if not isinstance(document, dict):
        return None
    metadata = document.get(METADATA_KEY)
    return metadata if isinstance(metadata, dict) else None


def strip_metadata(document):
    """El documento sin su bloque `metadata`, listo para comparar o enviar."""
    return {k: v for k, v in document.items() if k != METADATA_KEY}


def comparable_local(tipo, document):
    """Lo que del YAML se compara contra CX: sin `metadata` y sin campos locales."""
    local_only = LOCAL_ONLY_FIELDS.get(tipo, ())
    return {
        k: v for k, v in strip_metadata(document).items()
        if k not in local_only
    }


# ── Comparación ──────────────────────────────────────────────────────────────

def _is_empty(value):
    return value in (None, [], {}, "")


def same_references(local_value, remote_value):
    """Si dos listas de referencias contienen lo mismo, en cualquier orden."""
    if not isinstance(local_value, list) or not isinstance(remote_value, list):
        return False
    return sorted(map(str, local_value)) == sorted(map(str, remote_value))


def differs(remote, local):
    """Si algún campo declarado en el YAML no coincide con el remoto.

    Compara solo los campos que el YAML declara: los que no menciona se
    preservan del remoto, así que su valor no es una diferencia.

    Un campo vacío en el YAML y ausente en la respuesta de la API son lo
    mismo — CX omite los campos con valor por defecto en vez de devolverlos
    vacíos. Sin esta equivalencia, `inputParameterDefinitions: []` frente a un
    remoto que no trae el campo se lee como diferencia, el recurso sale como
    PATCH en cada ejecución y se rompe la idempotencia (CLAUDE.md §3.4).
    """
    for field, value in local.items():
        remote_value = remote.get(field)
        if remote_value == value:
            continue
        if _is_empty(value) and _is_empty(remote_value):
            continue
        if field in UNORDERED_FIELDS and same_references(value, remote_value):
            continue
        # Mismo criterio un nivel más abajo: si el YAML solo declara una
        # subclave (openApiSpec.textSchema), las que no menciona se preservan
        # del remoto (openApiSpec.authentication) y no son una diferencia.
        if isinstance(value, dict) and isinstance(remote_value, dict):
            if not differs(remote_value, value):
                continue
        return True
    return False


# ── Cuerpos para la API ──────────────────────────────────────────────────────

def build_full_update_body(remote, local, ignore_fields=None):
    """Cuerpo del Full Update: remoto como base, local por encima, sin read-only.

    1. Parte del objeto remoto, para preservar los campos que el YAML no
       declara — sin esto, un PATCH sin updateMask los borraría.
    2. Superpone el local, que es lo que se quiere cambiar.
    3. Quita los campos de solo lectura, que la API rechaza como entrada.
    """
    merged = dict(remote)
    merged.update(local)
    fields = ignore_fields if ignore_fields is not None else PLAYBOOK_IGNORE_FIELDS
    for field in fields:
        merged.pop(field, None)
    return merged


def build_create_body(tipo, document):
    """Cuerpo del POST: el YAML sin `metadata` ni campos locales."""
    body = comparable_local(tipo, document)
    for field in IGNORE_FIELDS_BY_TYPE.get(tipo, DEFAULT_IGNORE_FIELDS):
        body.pop(field, None)
    return body


def ignore_fields_for(tipo):
    return IGNORE_FIELDS_BY_TYPE.get(tipo, DEFAULT_IGNORE_FIELDS)
