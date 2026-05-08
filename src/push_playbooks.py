#!/usr/bin/env python3
"""
src/push_playbooks.py — Crear/upsert Playbooks de Dialogflow CX.

Patron `LIST -> diff -> PATCH/POST` (Sprint 2, Task 4). Misma firma que
`push_examples.py` y `push_tools.py` para los 4 push_*.py del template.

Decisiones tecnicas no negociables:
  - Auth: `gcloud auth print-access-token` (NO google.auth.default).
  - Header obligatorio x-goog-user-project (definitions/agent.yaml).
  - PATCH parcial con updateMask. Sin full-update.
  - `src/diff.py` es la fuente de verdad para el diff.

Constraint Sprint 2: Cualquier cambio real en Playbooks de Petal
requiere aprobacion humana explicita. Por defecto este modulo se
ejecuta solo con `--dry-run` durante Sprint 2.

Uso:
  python src/push_playbooks.py --file=definitions/playbooks/handoff.yaml --dry-run
  python src/push_playbooks.py --all --dry-run
  python src/push_playbooks.py --all --only Handoff --dry-run

Schema YAML esperado (definitions/playbooks/<displayName>.yaml):
  displayName: "Handoff"
  goal: "..."
  instruction: { steps: [...] }
  inputParameterDefinitions: [...]
  outputParameterDefinitions: [...]
  referencedTools: [...]
  playbookType: PLAYBOOK_TYPE_TASK | ROUTINE | ...
  codeBlock: {}                  # opcional
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

# Permitir import directo desde src/ tanto al ejecutar el script
# como al importarlo desde un test.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from diff import DiffResult, diff_resource  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"
PLAYBOOKS_DIR = REPO_ROOT / "definitions" / "playbooks"

# Campos read-only del recurso Playbook. NO entran en diff ni updateMask.
PLAYBOOK_IGNORE_FIELDS = ["name", "tokenCount", "createTime", "updateTime"]


def load_agent_config(path=AGENT_YAML_DEFAULT):
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


def parent_path(cfg):
    return f"projects/{cfg['project']}/locations/{cfg['location']}/agents/{cfg['agent_id']}"


def base_url(cfg):
    return cfg["api"]["base_v3beta1"]


def list_playbooks(cfg, headers):
    """LIST /playbooks con paginacion."""
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{parent_path(cfg)}/playbooks",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST /playbooks fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("playbooks", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def get_playbook(cfg, headers, name):
    """GET /playbooks/{id} para obtener el body completo (LIST a veces
    devuelve resumen; algunos campos solo aparecen en GET)."""
    r = requests.get(f"{base_url(cfg)}/{name}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {name} fallo: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def create_playbook(cfg, headers, body, dry_run=False):
    print(f"  ➕ POST {body['displayName']}")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(
        f"{base_url(cfg)}/{parent_path(cfg)}/playbooks",
        headers=headers, json=body,
    )
    if r.status_code == 200:
        print("     ✅ Creado")
        return True
    print(f"     ❌ Error POST {r.status_code}: {r.text[:300]}")
    return False


def patch_playbook(cfg, headers, name, payload, update_mask, dry_run=False):
    short = name.split("/")[-1]
    mask_str = ",".join(update_mask)
    print(f"  ✏️  PATCH {short} mask=[{mask_str}]")
    if dry_run:
        print("     (dry-run, no se envia PATCH)")
        return True
    params = {"updateMask": mask_str}
    r = requests.patch(
        f"{base_url(cfg)}/{name}",
        headers=headers, params=params, json=payload,
    )
    if r.status_code == 200:
        print("     ✅ Actualizado")
        return True
    print(f"     ❌ Error PATCH {r.status_code}: {r.text[:300]}")
    return False


def upsert_playbook(cfg, headers, body, existing_by_name, dry_run=False):
    """LIST -> diff -> PATCH/POST. Devuelve la accion: 'created' |
    'updated' | 'unchanged' | 'failed'.
    """
    remote_summary = existing_by_name.get(body["displayName"])
    if remote_summary is None:
        ok = create_playbook(cfg, headers, body, dry_run)
        return "created" if ok else "failed"

    # GET completo del Playbook remoto para diff fiable (LIST a veces
    # omite campos como instruction.steps).
    try:
        remote = get_playbook(cfg, headers, remote_summary["name"])
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return "failed"

    result: DiffResult = diff_resource(
        body, remote, ignore_fields=PLAYBOOK_IGNORE_FIELDS,
    )
    if not result.needs_update:
        print(f"  = {body['displayName']} (unchanged)")
        return "unchanged"

    print(f"  Δ  diff detectado: mask={result.update_mask}")
    ok = patch_playbook(
        cfg, headers,
        name=remote["name"],
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=dry_run,
    )
    return "updated" if ok else "failed"


def load_playbook_yaml(file_path: Path) -> dict:
    """Carga un YAML de Playbook y devuelve su body."""
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} no contiene un dict YAML al top-level.")
    if "displayName" not in data:
        raise ValueError(
            f"{file_path} no tiene 'displayName' al top-level. "
            "Schema esperado: campos del Playbook directamente al top-level."
        )
    return data


def discover_playbook_files(only_display_name=None):
    """Devuelve la lista de YAMLs en definitions/playbooks/."""
    if not PLAYBOOKS_DIR.exists():
        return []
    files = sorted(PLAYBOOKS_DIR.glob("*.yaml")) + sorted(PLAYBOOKS_DIR.glob("*.yml"))
    return files


def main():
    ap = argparse.ArgumentParser(
        description="Crear/upsert Playbooks de Dialogflow CX (idempotente).",
    )
    ap.add_argument("--file", help="Path a un YAML de Playbook (relativo al repo o absoluto)")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs en definitions/playbooks/")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--only", help="displayName del Playbook a procesar (filtro con --all)")
    args = ap.parse_args()

    if not args.file and not args.all:
        ap.error("debes pasar --file <path> o --all")
    if args.file and args.all:
        ap.error("--file y --all son excluyentes")

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    # Resolver lista de YAMLs
    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = REPO_ROOT / file_path
        yaml_files = [file_path]
    else:
        yaml_files = discover_playbook_files()
        if not yaml_files:
            print(f"  ⚠  No hay YAMLs en {PLAYBOOKS_DIR}. Nada que hacer.")
            return 0

    # Cargar bodies y filtrar por --only si aplica
    bodies = []
    for fp in yaml_files:
        try:
            body = load_playbook_yaml(fp)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ❌ {fp.name}: {e}")
            return 1
        if args.only and body.get("displayName") != args.only:
            continue
        bodies.append((fp, body))
    if args.only and not bodies:
        print(f"  ❌ --only '{args.only}' no machea ningun YAML cargado.")
        return 1

    print(f"\n\U0001f4dc LIST de Playbooks remotos del agente (paginado)...")
    try:
        remote_playbooks = list_playbooks(cfg, headers)
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return 1
    existing_by_name = {pb["displayName"]: pb for pb in remote_playbooks}
    print(f"   ✓ {len(remote_playbooks)} Playbook(s) remotos detectados")

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n\U0001f4dd Procesando {len(bodies)} Playbook(s) {mode}...\n")
    for fp, body in bodies:
        print(f"  \U0001f4c4 {fp.name}")
        action = upsert_playbook(cfg, headers, body, existing_by_name, args.dry_run)
        stats[action] += 1

    print(
        f"\n{'='*55}\n"
        f"\U0001f4ca created={stats['created']}  "
        f"updated={stats['updated']}  "
        f"unchanged={stats['unchanged']}  "
        f"failed={stats['failed']}"
        f"\n{'='*55}"
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
