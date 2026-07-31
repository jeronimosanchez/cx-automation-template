"""
act/cx_payloads.py — Construcción de payloads para la API de Dialogflow CX.

Workaround para el bug de `europe-west1` (§3.8 del CLAUDE.md):

    PATCH con `updateMask` sobre Playbooks falla silenciosamente en la región
    `europe-west1` — la API devuelve 200 pero los cambios no se aplican.
    La única solución validada es el **Full Update**: GET del objeto completo →
    modificar los campos deseados → PATCH del objeto completo SIN `updateMask`.

    `build_full_update_body()` implementa el merge local+remote necesario para
    ese Full Update, garantizando que:
      - los campos read-only (que la API rechaza como input) quedan excluidos,
      - los campos que el YAML local no menciona se preservan del remoto,
      - los campos editados localmente sobreescriben el valor remoto.

Este módulo no hace llamadas a la API. Solo construye el body resultante.
"""

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Campos read-only del recurso Playbook.
# La API los devuelve en GET/LIST pero los rechaza si se incluyen en PATCH/POST.
# Recuperados de act/push_playbooks.py (git 4b0b932^) y validados en producción.
PLAYBOOK_IGNORE_FIELDS = ["name", "tokenCount", "createTime", "updateTime"]


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def build_full_update_body(remote: dict, local: dict) -> dict:
    """Construye el body para Full Update (workaround bug §3.8).

    Algoritmo:
      1. Toma el objeto remoto como base (preserva campos que el YAML local
         no declara — evita borrar campos desconocidos por error).
      2. Aplica overlay con el objeto local (los campos editados sobreescriben).
      3. Elimina todos los campos read-only de PLAYBOOK_IGNORE_FIELDS (la API
         devuelve 400 si se incluyen en el PATCH).

    Args:
        remote: objeto Playbook completo devuelto por GET /playbooks/{id}.
        local:  dict cargado desde el YAML de definitions/playbooks/.

    Returns:
        dict listo para enviar como body de PATCH sin `updateMask`.
    """
    merged = dict(remote)
    merged.update(local)
    for field in PLAYBOOK_IGNORE_FIELDS:
        merged.pop(field, None)
    return merged
