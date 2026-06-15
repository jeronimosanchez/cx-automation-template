#!/usr/bin/env python3
"""
act/push_entity_types.py — Crear/upsert Entity Types de Dialogflow CX.

Patron `LIST -> diff -> PATCH/POST` (Sprint 3, Task 4). Top-level del
agente.

Soporta los 3 `kind` posibles del schema:
  - KIND_MAP: entries con value + synonyms[]
  - KIND_LIST: entries solo con value
  - KIND_REGEXP: entries con value=<regex pattern>

Uso:
  python act/push_entity_types.py --file=definitions/entity_types/example_entity_type.yaml --dry-run
  python act/push_entity_types.py --all --dry-run
  python act/push_entity_types.py --all --only Test_Color --dry-run
"""
import argparse
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
ENTITY_TYPES_DIR = REPO_ROOT / "definitions" / "entity_types"

ENTITY_TYPE_IGNORE_FIELDS = ["name", "createTime", "updateTime"]


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


def list_entity_types(cfg, headers):
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{parent_path(cfg)}/entityTypes",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST /entityTypes fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("entityTypes", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def get_entity_type(cfg, headers, name):
    r = requests.get(f"{base_url(cfg)}/{name}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {name} fallo: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def create_entity_type(cfg, headers, body, dry_run=False):
    print(f"  + POST {body['displayName']} (kind={body.get('kind')})")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(
        f"{base_url(cfg)}/{parent_path(cfg)}/entityTypes",
        headers=headers, json=body,
    )
    if r.status_code == 200:
        print("     OK Creado")
        return True
    print(f"     ERR POST {r.status_code}: {r.text[:300]}")
    return False


def patch_entity_type(cfg, headers, name, payload, update_mask, dry_run=False):
    short = name.split("/")[-1]
    mask_str = ",".join(update_mask)
    print(f"  ~ PATCH {short} mask=[{mask_str}]")
    if dry_run:
        print("     (dry-run, no se envia PATCH)")
        return True
    params = {"updateMask": mask_str}
    r = requests.patch(
        f"{base_url(cfg)}/{name}",
        headers=headers, params=params, json=payload,
    )
    if r.status_code == 200:
        print("     OK Actualizado")
        return True
    print(f"     ERR PATCH {r.status_code}: {r.text[:300]}")
    return False


def upsert_entity_type(cfg, headers, body, existing_by_name, dry_run=False):
    remote_summary = existing_by_name.get(body["displayName"])
    if remote_summary is None:
        ok = create_entity_type(cfg, headers, body, dry_run)
        return "created" if ok else "failed"

    try:
        remote = get_entity_type(cfg, headers, remote_summary["name"])
    except RuntimeError as e:
        print(f"  ERR {e}")
        return "failed"

    result: DiffResult = diff_resource(
        body, remote, ignore_fields=ENTITY_TYPE_IGNORE_FIELDS,
    )
    if not result.needs_update:
        print(f"  = {body['displayName']} (unchanged)")
        return "unchanged"

    print(f"  d  diff detectado: mask={result.update_mask}")
    ok = patch_entity_type(
        cfg, headers,
        name=remote["name"],
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=dry_run,
    )
    return "updated" if ok else "failed"


def load_entity_type_yaml(file_path: Path) -> dict:
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} no contiene un dict YAML al top-level.")
    if "displayName" not in data:
        raise ValueError(
            f"{file_path} no tiene 'displayName' al top-level."
        )
    if "kind" not in data:
        raise ValueError(
            f"{file_path} no tiene 'kind'. Valores validos: "
            "KIND_MAP, KIND_LIST, KIND_REGEXP."
        )
    return data


def discover_entity_type_files():
    if not ENTITY_TYPES_DIR.exists():
        return []
    return sorted(ENTITY_TYPES_DIR.glob("*.yaml")) + sorted(ENTITY_TYPES_DIR.glob("*.yml"))


def main():
    ap = argparse.ArgumentParser(
        description="Crear/upsert Entity Types de Dialogflow CX (idempotente).",
    )
    ap.add_argument("--file", help="Path a un YAML de Entity Type")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs en definitions/entity_types/")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--only", help="displayName del Entity Type a procesar")
    args = ap.parse_args()

    if not args.file and not args.all:
        ap.error("debes pasar --file <path> o --all")
    if args.file and args.all:
        ap.error("--file y --all son excluyentes")

    cfg = load_agent_config()
    print("Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = REPO_ROOT / file_path
        yaml_files = [file_path]
    else:
        yaml_files = discover_entity_type_files()
        if not yaml_files:
            print(f"  No hay YAMLs en {ENTITY_TYPES_DIR}. Nada que hacer.")
            return 0

    bodies = []
    for fp in yaml_files:
        try:
            body = load_entity_type_yaml(fp)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERR {fp.name}: {e}")
            return 1
        if args.only and body.get("displayName") != args.only:
            continue
        bodies.append((fp, body))
    if args.only and not bodies:
        print(f"  ERR --only '{args.only}' no machea ningun YAML cargado.")
        return 1

    print("\nLIST de Entity Types remotos del agente (paginado)...")
    try:
        remote_ets = list_entity_types(cfg, headers)
    except RuntimeError as e:
        print(f"  ERR {e}")
        return 1
    existing_by_name = {e["displayName"]: e for e in remote_ets}
    print(f"   ok {len(remote_ets)} Entity Type(s) remotos detectados")

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\nProcesando {len(bodies)} Entity Type(s) {mode}...\n")
    for fp, body in bodies:
        print(f"  [{fp.name}]")
        action = upsert_entity_type(cfg, headers, body, existing_by_name, args.dry_run)
        stats[action] += 1

    print(
        f"\n{'='*55}\n"
        f"created={stats['created']}  "
        f"updated={stats['updated']}  "
        f"unchanged={stats['unchanged']}  "
        f"failed={stats['failed']}"
        f"\n{'='*55}"
    )
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
