"""diff.py — Funcion pura para comparar recursos locales vs remotos.

Diseno (Sprint 2, Task 2): NO hace red, NO tiene side effects. Recibe
dos diccionarios (local + remoto) y devuelve un DiffResult listo para
construir un PATCH con updateMask de la API CX (v3beta1).

Politica de PATCH:
- updateMask incluye solo los paths que cambian (idempotencia real).
- Si un campo existe en local pero NO en remoto -> entra en mask.
- Si un campo existe en remoto pero NO en local -> NO entra en mask
  (PATCH no borra; eso lo hace DELETE explicito).
- Listas se comparan con `==` (orden importa). Si cualquier elemento
  cambia se manda la lista entera bajo su path padre.
- ignore_fields permite excluir campos read-only (`tokenCount`,
  `name`, `createTime`, `updateTime`...). Funciona como prefix-match:
  si ignore="meta", se ignora `meta` y cualquier `meta.*`.

Concurrencia: sin proteccion (last-write-wins). Sprint 4 anade
`concurrency: 1` en GitHub Actions.

Ejemplo:
  >>> from src.diff import diff_resource
  >>> r = diff_resource(
  ...     local={"displayName": "X", "tokenCount": 7},
  ...     remote={"displayName": "Y", "tokenCount": 99},
  ...     ignore_fields=["tokenCount"],
  ... )
  >>> r.needs_update
  True
  >>> r.update_mask
  ['displayName']
  >>> r.patch_payload
  {'displayName': 'X'}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional


@dataclass
class DiffResult:
    needs_update: bool
    update_mask: List[str] = field(default_factory=list)
    patch_payload: dict = field(default_factory=dict)


def _path_is_ignored(path: str, ignore: Iterable[str]) -> bool:
    """True si path coincide o desciende de un campo en ignore.

    ignore=["meta"] cubre `meta` y `meta.x`, `meta.x.y`...
    ignore=["name"] cubre `name` pero NO `foo.name`.
    """
    for ig in ignore:
        if path == ig or path.startswith(ig + "."):
            return True
    return False


def _walk(local: Any, remote: Any, ignore: Iterable[str], prefix: str) -> List[tuple]:
    """Recursivamente compara local vs remote y devuelve lista de
    (path, valor_local) para cada diff encontrado.

    Solo recurre en dicts. Listas y escalares se comparan como bloque.
    """
    diffs: List[tuple] = []

    if not isinstance(local, dict) or not isinstance(remote, dict):
        if local != remote:
            diffs.append((prefix, local))
        return diffs

    for key, local_v in local.items():
        path = f"{prefix}.{key}" if prefix else key
        if _path_is_ignored(path, ignore):
            continue

        if key not in remote:
            diffs.append((path, local_v))
            continue

        remote_v = remote[key]
        if isinstance(local_v, dict) and isinstance(remote_v, dict):
            diffs.extend(_walk(local_v, remote_v, ignore, path))
        elif local_v != remote_v:
            diffs.append((path, local_v))

    return diffs


def _build_payload(diffs: List[tuple]) -> dict:
    """Reconstruye un dict anidado a partir de paths con notacion punto."""
    payload: dict = {}
    for path, value in diffs:
        parts = path.split(".")
        cursor = payload
        for p in parts[:-1]:
            if p not in cursor or not isinstance(cursor[p], dict):
                cursor[p] = {}
            cursor = cursor[p]
        cursor[parts[-1]] = value
    return payload


def diff_resource(
    local: dict,
    remote: dict,
    ignore_fields: Optional[List[str]] = None,
) -> DiffResult:
    """Compara dos recursos y devuelve DiffResult listo para PATCH.

    Args:
        local: definicion local (la verdad declarativa, ej. desde YAML).
        remote: estado actual del recurso en la API.
        ignore_fields: lista de paths a ignorar (read-only). Match
            exacto + prefijo. Default `None` -> sin exclusiones.

    Returns:
        DiffResult con `needs_update`, `update_mask`, `patch_payload`.
    """
    if not isinstance(local, dict) or not isinstance(remote, dict):
        raise TypeError("local y remote deben ser dict.")

    ignore = list(ignore_fields or [])
    diffs = _walk(local, remote, ignore, prefix="")

    if not diffs:
        return DiffResult(needs_update=False, update_mask=[], patch_payload={})

    update_mask = [path for path, _ in diffs]
    patch_payload = _build_payload(diffs)
    return DiffResult(
        needs_update=True,
        update_mask=update_mask,
        patch_payload=patch_payload,
    )
