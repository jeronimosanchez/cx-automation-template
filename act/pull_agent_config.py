#!/usr/bin/env python3
"""
act/pull_agent_config.py — Exporta config del agente CX -> YAML local.

Espejo READ-ONLY de push_agent_config.py (Sprint 5, PR1). Solo GET; nunca
PATCH/POST/DELETE. Reescribe SOLO el bloque `agent_definition:` de
definitions/agent.yaml; el resto del fichero (project, location, agent_id,
api, tool, playbooks, ...) y los comentarios se preservan via edicion
string-surgical (sin libreria YAML adicional).

Decisiones tecnicas no negociables:
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project (heredado de agent.yaml).
  - Read-only del lado pull: name, createTime, updateTime, tokenCount,
    satisfiesPzi.
  - Transformacion inversa al push:
        startPlaybook (full path) -> start_playbook_id (UUID).

Uso:
  python act/pull_agent_config.py --dry-run   # imprime que escribiria
  python act/pull_agent_config.py             # escribe (solo bloque agent_definition:)
"""
import argparse
import os
import sys
from pathlib import Path

import yaml

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from push_agent_config import (  # noqa: E402
    AGENT_YAML_DEFAULT,
    REPO_ROOT,
    build_headers,
    get_agent,
    get_token,
    load_yaml,
)


# Campos del recurso Agent que NO se persisten en el YAML local.
# Superset de AGENT_IGNORE_FIELDS de push_agent_config (anade satisfiesPzi,
# que es read-only de Google y no debe entrar al YAML versionado).
PULL_STRIP_FIELDS = ("name", "createTime", "updateTime", "tokenCount", "satisfiesPzi")

MARKER = "# === DO NOT EDIT — exported from CX by pull_agent_config.py ==="

# Orden canonico de las claves de agent_definition (segun convencion local
# observada en definitions/agent.yaml). Claves desconocidas se anexan al final.
_CANONICAL_ORDER = (
    "displayName",
    "defaultLanguageCode",
    "timeZone",
    "speechToTextSettings",
    "advancedSettings",
    "start_playbook_id",
    "enableMultiLanguageTraining",
)


def cx_to_local(remote: dict) -> dict:
    """Transforma respuesta de CX a la forma del YAML local.

    - Strippea PULL_STRIP_FIELDS (read-only).
    - startPlaybook (full path) -> start_playbook_id (solo UUID).
    - Preserva claves desconocidas para forward-compat con cambios de CX.
    - Reordena segun _CANONICAL_ORDER; lo desconocido al final.
    """
    out: dict = {}
    for k, v in remote.items():
        if k in PULL_STRIP_FIELDS:
            continue
        if k == "startPlaybook":
            pb_uuid = v.rsplit("/", 1)[-1] if isinstance(v, str) else v
            out["start_playbook_id"] = pb_uuid
            continue
        out[k] = v

    ordered: dict = {}
    for k in _CANONICAL_ORDER:
        if k in out:
            ordered[k] = out.pop(k)
    ordered.update(out)
    return ordered


def dump_block(agent_definition: dict) -> str:
    """Renderiza el bloque agent_definition: con MARKER, listo para inyectar."""
    body = yaml.safe_dump(
        {"agent_definition": agent_definition},
        sort_keys=False,
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
    )
    return f"{MARKER}\n{body}"


def surgical_write(yaml_path: Path, agent_definition: dict) -> tuple[str, str]:
    """Reemplaza el bloque agent_definition: en yaml_path (string-surgical).

    Reglas:
    - Si MARKER ya existe en el fichero, corta desde la linea del MARKER.
    - Si no, corta desde la linea `agent_definition:` (asume que es el ultimo
      top-level key del fichero, convencion del proyecto).
    - El nuevo bloque incluye siempre el MARKER (idempotente en re-runs).

    Devuelve (texto_antes, texto_despues) sin tocar el fichero — el caller
    decide si escribir.
    """
    text = yaml_path.read_text()
    lines = text.splitlines(keepends=True)

    cut_at = None
    for i, line in enumerate(lines):
        if line.strip() == MARKER:
            cut_at = i
            break
    if cut_at is None:
        for i, line in enumerate(lines):
            if line.startswith("agent_definition:"):
                cut_at = i
                break
    if cut_at is None:
        raise RuntimeError(
            f"{yaml_path}: no se encontro ni MARKER ni `agent_definition:`. "
            "El fichero no respeta la convencion esperada."
        )

    head = "".join(lines[:cut_at])
    if head and not head.endswith("\n"):
        head += "\n"
    new_text = head + dump_block(agent_definition)
    return text, new_text


def main():
    ap = argparse.ArgumentParser(
        description="Exporta agent config de CX → bloque agent_definition: en YAML local.",
    )
    ap.add_argument("--file", default=str(AGENT_YAML_DEFAULT),
                    help="YAML destino (default: definitions/agent.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; imprime el nuevo bloque.")
    args = ap.parse_args()

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path

    cfg = load_yaml(file_path)
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print(f"\n\U0001f4dc GET agent {cfg['agent_id']}...")
    remote = get_agent(cfg, headers)
    print(f"   ✓ remote keys: {sorted(remote.keys())}")

    local = cx_to_local(remote)
    print(f"   ✓ local keys:  {list(local.keys())}")

    _, new_text = surgical_write(file_path, local)

    if args.dry_run:
        print(f"\n📝 DRY-RUN — bloque que se escribiria en {file_path}:\n")
        print(dump_block(local), end="")
        return 0

    file_path.write_text(new_text)
    print(f"\n✅ Escrito: {file_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
