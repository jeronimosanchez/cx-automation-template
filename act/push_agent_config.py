#!/usr/bin/env python3
"""
act/push_agent_config.py — Sincroniza la configuracion global del agente.

Patron `GET -> diff -> PATCH` (Sprint 2, Task 6). NO hay LIST: solo
hay un agente identificado por `agent_id`. Es el unico de los cuatro
push_*.py que NO sigue el flujo LIST primero.

Decisiones tecnicas no negociables:
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project (definitions/agent.yaml).
  - PATCH parcial con updateMask. Sin full-update.
  - `act/diff.py` es la fuente de verdad para el diff.

Constraint Sprint 2: Sin PATCH real sobre Agent Config de Petal en este
sprint. Default operativo = `--dry-run`. Si los campos read-only no
estan bien identificados y el dry-run reporta diff sospechoso, se
loguea el diff completo y se ESCALA — NO se inventa la lista de
ignore_fields.

Uso:
  python act/push_agent_config.py --dry-run
  python act/push_agent_config.py --file=definitions/agent.yaml --dry-run

Schema YAML esperado (extension de definitions/agent.yaml):
  project: ...
  location: ...
  agent_id: ...
  api: { ... }
  ...
  agent_definition:
    displayName: "..."
    defaultLanguageCode: "es"
    timeZone: "..."
    speechToTextSettings: { ... }
    advancedSettings: { ... }
    start_playbook_id: "<uuid>"     # se resuelve a startPlaybook (full path)
    enableMultiLanguageTraining: true
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from diff import DiffResult, diff_resource  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"

# Campos read-only conocidos del recurso Agent. NO inventamos esta lista:
# si aparece un campo nuevo en remoto que el dry-run marca como diff y NO
# esta en la spec del brief como editable, se ESCALA en lugar de anadirlo
# silenciosamente.
AGENT_IGNORE_FIELDS = ["name", "createTime", "updateTime", "tokenCount"]


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def get_token():
    r = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def build_headers(cfg, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    extra = (cfg.get("api") or {}).get("required_headers") or {}
    headers.update(extra)
    return headers


def agent_path(cfg):
    return (
        f"projects/{cfg['project']}/locations/{cfg['location']}"
        f"/agents/{cfg['agent_id']}"
    )


def base_url(cfg):
    return cfg["api"]["base_v3beta1"]


def get_agent(cfg, headers):
    r = requests.get(f"{base_url(cfg)}/{agent_path(cfg)}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET agent fallo: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def patch_agent(cfg, headers, payload, update_mask, dry_run=False):
    mask_str = ",".join(update_mask)
    print(f"  ✏️  PATCH agent mask=[{mask_str}]")
    if dry_run:
        print("     (dry-run, no se envia PATCH)")
        return True
    params = {"updateMask": mask_str}
    r = requests.patch(
        f"{base_url(cfg)}/{agent_path(cfg)}",
        headers=headers, params=params, json=payload,
    )
    if r.status_code == 200:
        print("     ✅ Actualizado")
        return True
    print(f"     ❌ Error PATCH {r.status_code}: {r.text[:300]}")
    return False


def resolve_local_body(cfg, agent_definition):
    """Convierte el bloque `agent_definition` del YAML en un body listo
    para diffear contra la respuesta del GET de la API.

    Transformaciones:
    - `start_playbook_id` (UUID) -> `startPlaybook` (full path).
    """
    body = dict(agent_definition)  # shallow copy
    pb_id = body.pop("start_playbook_id", None)
    if pb_id and "startPlaybook" not in body:
        body["startPlaybook"] = f"{agent_path(cfg)}/playbooks/{pb_id}"
    return body


def main():
    ap = argparse.ArgumentParser(
        description="Sincroniza la config global del agente (GET -> diff -> PATCH).",
    )
    ap.add_argument("--file", default=str(AGENT_YAML_DEFAULT),
                    help="YAML con bloque `agent_definition` (default: definitions/agent.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia PATCH; muestra que se haria")
    args = ap.parse_args()

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path

    cfg = load_yaml(file_path)
    if "agent_definition" not in cfg:
        print(f"  ❌ {file_path} no tiene bloque `agent_definition`.")
        return 1

    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print(f"\n\U0001f4dc GET agent {cfg['agent_id']}...")
    try:
        remote = get_agent(cfg, headers)
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return 1
    print(f"   ✓ remote keys: {list(remote.keys())}")

    local = resolve_local_body(cfg, cfg["agent_definition"])
    print(f"   ✓ local keys:  {list(local.keys())}")

    result: DiffResult = diff_resource(
        local, remote, ignore_fields=AGENT_IGNORE_FIELDS,
    )

    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n\U0001f4dd Comparando local vs remote {mode}...\n")

    if not result.needs_update:
        print(f"  = {cfg['agent_id']} (unchanged)")
        print(
            f"\n{'='*55}\n"
            f"\U0001f4ca created=0  updated=0  unchanged=1  failed=0"
            f"\n{'='*55}"
        )
        return 0

    # Diff detectado. Loguear al detalle ANTES de pedir aprobacion.
    print(f"  Δ  diff detectado: mask={result.update_mask}")
    print("     Detalles del diff:")
    print(json.dumps(result.patch_payload, indent=2, ensure_ascii=False))

    # Constraint Sprint 2: NO PATCH real sobre Agent Config de Petal.
    if dry_run := args.dry_run:
        print(
            "\n     ⚠ Sprint 2 constraint: NO PATCH real sobre Agent "
            "Config. Si el diff tiene campos read-only no documentados, "
            "ESCALAR — no anadir a AGENT_IGNORE_FIELDS sin aprobacion."
        )
        print(
            f"\n{'='*55}\n"
            f"\U0001f4ca created=0  updated=1 (dry-run)  unchanged=0  failed=0"
            f"\n{'='*55}"
        )
        return 0

    ok = patch_agent(
        cfg, headers,
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=False,
    )
    print(
        f"\n{'='*55}\n"
        f"\U0001f4ca created=0  updated={1 if ok else 0}  "
        f"unchanged=0  failed={0 if ok else 1}"
        f"\n{'='*55}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
