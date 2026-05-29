#!/usr/bin/env python3
"""
act/push_pages.py — Crear/upsert Pages de Dialogflow CX (anidadas bajo Flow).

Patron `LIST -> diff -> PATCH/POST` (Sprint 3, Task 2). A diferencia de
Flows/Intents/EntityTypes/Webhooks/Generators, las Pages son sub-recursos
de un Flow concreto. El YAML local declara `parent_flow_displayName` y
este modulo resuelve el flow_id por LIST /flows.

Decisiones tecnicas no negociables (Sprint 2/3):
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project (definitions/agent.yaml).
  - PATCH parcial con updateMask (idempotencia).
  - `act/diff.py` es la fuente de verdad para el diff.

Constraint Sprint 3: Petal NO usa Pages reales (Playbook-only). Este
modulo se ejecuta SIEMPRE con --dry-run en Sprint 3. Validacion completa
diferida a un proyecto Flow-based.

Uso:
  python act/push_pages.py --file=definitions/pages/example_page.yaml --dry-run
  python act/push_pages.py --all --dry-run
  python act/push_pages.py --all --flow Test_Flow --dry-run
  python act/push_pages.py --all --only Test_Page --dry-run
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
PAGES_DIR = REPO_ROOT / "definitions" / "pages"

# Campos que el YAML declara para resolver el padre, NO van al body de la API.
_LOCAL_ONLY_FIELDS = {"parent_flow_displayName"}

# Campos read-only del recurso Page. NO entran en diff ni updateMask.
PAGE_IGNORE_FIELDS = ["name", "createTime", "updateTime"]


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


def list_flows(cfg, headers):
    """LIST /flows con paginacion. Igual que push_flows.py pero local
    para evitar dependencia circular."""
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{parent_path(cfg)}/flows",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST /flows fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("flows", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def resolve_flow_id(cfg, headers, flow_display_name):
    """Devuelve el `name` (path completo) del flow cuyo displayName
    coincide. Lanza RuntimeError si no se encuentra."""
    flows = list_flows(cfg, headers)
    for f in flows:
        if f.get("displayName") == flow_display_name:
            return f["name"]
    raise RuntimeError(
        f"Flow padre con displayName='{flow_display_name}' no "
        f"encontrado. Flows visibles: "
        f"{[f.get('displayName') for f in flows]}"
    )


def list_pages(cfg, headers, flow_name):
    """LIST /flows/{flow_id}/pages con paginacion. flow_name es el
    path completo del flow (`projects/.../flows/<id>`)."""
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{flow_name}/pages",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST {flow_name}/pages fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("pages", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def get_page(cfg, headers, name):
    """GET /pages/{id} para obtener el body completo."""
    r = requests.get(f"{base_url(cfg)}/{name}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {name} fallo: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def create_page(cfg, headers, flow_name, body, dry_run=False):
    print(f"  + POST {body['displayName']} (flow={flow_name.split('/')[-1]})")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(
        f"{base_url(cfg)}/{flow_name}/pages",
        headers=headers, json=body,
    )
    if r.status_code == 200:
        print("     OK Creado")
        return True
    print(f"     ERR POST {r.status_code}: {r.text[:300]}")
    return False


def patch_page(cfg, headers, name, payload, update_mask, dry_run=False):
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


def upsert_page(cfg, headers, flow_name, body, existing_by_name, dry_run=False):
    """LIST -> diff -> PATCH/POST. flow_name es el path completo del
    flow padre. body NO debe contener campos local-only."""
    remote_summary = existing_by_name.get(body["displayName"])
    if remote_summary is None:
        ok = create_page(cfg, headers, flow_name, body, dry_run)
        return "created" if ok else "failed"

    try:
        remote = get_page(cfg, headers, remote_summary["name"])
    except RuntimeError as e:
        print(f"  ERR {e}")
        return "failed"

    result: DiffResult = diff_resource(
        body, remote, ignore_fields=PAGE_IGNORE_FIELDS,
    )
    if not result.needs_update:
        print(f"  = {body['displayName']} (unchanged)")
        return "unchanged"

    print(f"  d  diff detectado: mask={result.update_mask}")
    ok = patch_page(
        cfg, headers,
        name=remote["name"],
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=dry_run,
    )
    return "updated" if ok else "failed"


def split_local_fields(raw_body: dict):
    """Separa campos locales (parent_flow_displayName) del body que va
    a la API. Devuelve (api_body, parent_flow_display_name)."""
    parent_flow = raw_body.get("parent_flow_displayName")
    api_body = {k: v for k, v in raw_body.items() if k not in _LOCAL_ONLY_FIELDS}
    return api_body, parent_flow


def load_page_yaml(file_path: Path) -> dict:
    """Carga un YAML de Page. Debe tener `parent_flow_displayName` y
    `displayName`. Devuelve el dict completo (incluyendo el campo
    local). Es responsabilidad del caller separar campos locales."""
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} no contiene un dict YAML al top-level.")
    if "displayName" not in data:
        raise ValueError(
            f"{file_path} no tiene 'displayName' al top-level."
        )
    if "parent_flow_displayName" not in data:
        raise ValueError(
            f"{file_path} no tiene 'parent_flow_displayName' al top-level. "
            "Las Pages requieren saber el Flow padre."
        )
    return data


def discover_page_files():
    if not PAGES_DIR.exists():
        return []
    return sorted(PAGES_DIR.glob("*.yaml")) + sorted(PAGES_DIR.glob("*.yml"))


def main():
    ap = argparse.ArgumentParser(
        description="Crear/upsert Pages de Dialogflow CX (idempotente).",
    )
    ap.add_argument("--file", help="Path a un YAML de Page")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs en definitions/pages/")
    ap.add_argument("--flow", help="Filtrar a un flow padre (displayName)")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--only", help="displayName de la Page a procesar")
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
        yaml_files = discover_page_files()
        if not yaml_files:
            print(f"  No hay YAMLs en {PAGES_DIR}. Nada que hacer.")
            return 0

    raw_bodies = []
    for fp in yaml_files:
        try:
            data = load_page_yaml(fp)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERR {fp.name}: {e}")
            return 1
        if args.only and data.get("displayName") != args.only:
            continue
        if args.flow and data.get("parent_flow_displayName") != args.flow:
            continue
        raw_bodies.append((fp, data))
    if (args.only or args.flow) and not raw_bodies:
        print(f"  ERR ningun YAML coincide con los filtros aplicados.")
        return 1

    # Agrupar por flow padre. Resolver flow_id una sola vez por flow.
    grouped: dict = {}
    for fp, data in raw_bodies:
        api_body, parent_flow = split_local_fields(data)
        grouped.setdefault(parent_flow, []).append((fp, api_body))

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""

    for parent_flow, items in grouped.items():
        print(f"\nResolviendo flow padre '{parent_flow}'...")
        try:
            flow_name = resolve_flow_id(cfg, headers, parent_flow)
        except RuntimeError as e:
            print(f"  ERR {e}")
            for _ in items:
                stats["failed"] += 1
            continue
        print(f"   ok flow_id={flow_name.split('/')[-1]}")

        print(f"LIST de Pages remotas del flow (paginado)...")
        try:
            remote_pages = list_pages(cfg, headers, flow_name)
        except RuntimeError as e:
            print(f"  ERR {e}")
            for _ in items:
                stats["failed"] += 1
            continue
        existing_by_name = {p["displayName"]: p for p in remote_pages}
        print(f"   ok {len(remote_pages)} Page(s) remotas detectadas")

        print(f"\nProcesando {len(items)} Page(s) bajo '{parent_flow}' {mode}...\n")
        for fp, body in items:
            print(f"  [{fp.name}]")
            action = upsert_page(
                cfg, headers, flow_name, body, existing_by_name, args.dry_run,
            )
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
