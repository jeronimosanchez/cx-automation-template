#!/usr/bin/env python3
"""
act/push_tools.py — Crear/upsert Tools (OpenAPI-based) de Dialogflow CX.

Patron `LIST -> diff -> PATCH/POST` (Sprint 2, Task 5). Misma firma que
`push_examples.py` y `push_playbooks.py` para los 4 push_*.py.

Decisiones tecnicas no negociables:
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project (definitions/agent.yaml).
  - PATCH parcial con updateMask. Sin full-update.
  - `act/diff.py` es la fuente de verdad para el diff.

Uso:
  python act/push_tools.py --file=definitions/tools/petaldatatool.yaml --dry-run
  python act/push_tools.py --all --dry-run
  python act/push_tools.py --all --only PetalDataTool --dry-run

Schema YAML esperado (definitions/tools/<displayName>.yaml):
  displayName: "PetalDataTool"
  description: "..."
  toolType: CUSTOMIZED_TOOL              # o lo que aplique
  # Una de las dos opciones para la OpenAPI spec:
  openapi_spec_file: petaldatatool_openapi.yaml   # ruta relativa al YAML
  # O bien:
  openApiSpec:
    textSchema: |
      openapi: 3.0.0
      info: ...
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

# Permitir import directo desde act/.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from diff import DiffResult, diff_resource  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"
TOOLS_DIR = REPO_ROOT / "definitions" / "tools"

# Campos read-only del recurso Tool. NO entran en diff ni updateMask.
TOOL_IGNORE_FIELDS = ["name", "createTime", "updateTime"]


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


def list_tools(cfg, headers):
    """LIST /tools con paginacion."""
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{parent_path(cfg)}/tools",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST /tools fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("tools", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def get_tool(cfg, headers, name):
    """GET /tools/{id} para obtener body completo (LIST a veces omite
    campos como `openApiSpec.textSchema`)."""
    r = requests.get(f"{base_url(cfg)}/{name}", headers=headers)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {name} fallo: {r.status_code} {r.text[:300]}"
        )
    return r.json()


def create_tool(cfg, headers, body, dry_run=False):
    print(f"  ➕ POST {body['displayName']}")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(
        f"{base_url(cfg)}/{parent_path(cfg)}/tools",
        headers=headers, json=body,
    )
    if r.status_code == 200:
        print("     ✅ Creado")
        return True
    print(f"     ❌ Error POST {r.status_code}: {r.text[:300]}")
    return False


def patch_tool(cfg, headers, name, payload, update_mask, dry_run=False):
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


def upsert_tool(cfg, headers, body, existing_by_name, dry_run=False):
    """LIST -> diff -> PATCH/POST. Devuelve la accion."""
    remote_summary = existing_by_name.get(body["displayName"])
    if remote_summary is None:
        ok = create_tool(cfg, headers, body, dry_run)
        return "created" if ok else "failed"

    try:
        remote = get_tool(cfg, headers, remote_summary["name"])
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return "failed"

    result: DiffResult = diff_resource(
        body, remote, ignore_fields=TOOL_IGNORE_FIELDS,
    )
    if not result.needs_update:
        print(f"  = {body['displayName']} (unchanged)")
        return "unchanged"

    print(f"  Δ  diff detectado: mask={result.update_mask}")
    if dry_run:
        for path in result.update_mask:
            print(f"     - path: {path}")
        print(
            "     ⚠ Sprint 2 constraint: NO PATCH real sobre Tools. "
            "Revisa el diff y pide aprobacion humana antes de aplicar."
        )

    ok = patch_tool(
        cfg, headers,
        name=remote["name"],
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=dry_run,
    )
    return "updated" if ok else "failed"


def load_tool_yaml(file_path: Path) -> dict:
    """Carga un YAML de Tool y devuelve el body listo para PATCH/POST.

    Soporta dos formas para la OpenAPI spec:
      1) `openapi_spec_file: <ruta-relativa>` -> se carga el fichero
         como TEXTO crudo y se inyecta en `openApiSpec.textSchema`.
      2) `openApiSpec.textSchema: |` inline -> se usa tal cual.

    El campo `openapi_spec_file` se elimina del body antes de devolver.
    """
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} no contiene un dict YAML al top-level.")
    if "displayName" not in data:
        raise ValueError(f"{file_path} no tiene 'displayName' al top-level.")

    spec_file = data.pop("openapi_spec_file", None)
    if spec_file:
        spec_path = file_path.parent / spec_file
        if not spec_path.exists():
            raise ValueError(
                f"{file_path}: openapi_spec_file '{spec_file}' no existe "
                f"(buscado en {spec_path})"
            )
        with open(spec_path) as fs:
            text_schema = fs.read()
        data.setdefault("openApiSpec", {})["textSchema"] = text_schema

    if "openApiSpec" not in data or "textSchema" not in data["openApiSpec"]:
        raise ValueError(
            f"{file_path}: falta openApiSpec.textSchema. Provee "
            "`openapi_spec_file` o el textSchema inline."
        )
    return data


def discover_tool_files():
    """Devuelve la lista de YAMLs en definitions/tools/, excluyendo los
    sub-ficheros referenciados como `openapi_spec_file`."""
    if not TOOLS_DIR.exists():
        return []
    candidates = sorted(TOOLS_DIR.glob("*.yaml")) + sorted(TOOLS_DIR.glob("*.yml"))
    # Filtrar sub-ficheros que no son wrappers (sin displayName al top-level).
    files = []
    for fp in candidates:
        try:
            with open(fp) as f:
                head = yaml.safe_load(f)
        except yaml.YAMLError:
            continue
        if isinstance(head, dict) and "displayName" in head:
            files.append(fp)
    return files


def main():
    ap = argparse.ArgumentParser(
        description="Crear/upsert Tools de Dialogflow CX (idempotente).",
    )
    ap.add_argument("--file", help="Path a un YAML de Tool (relativo al repo o absoluto)")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs en definitions/tools/")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--only", help="displayName del Tool a procesar (filtro con --all)")
    args = ap.parse_args()

    if not args.file and not args.all:
        ap.error("debes pasar --file <path> o --all")
    if args.file and args.all:
        ap.error("--file y --all son excluyentes")

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = REPO_ROOT / file_path
        yaml_files = [file_path]
    else:
        yaml_files = discover_tool_files()
        if not yaml_files:
            print(f"  ⚠  No hay YAMLs de Tools en {TOOLS_DIR}. Nada que hacer.")
            return 0

    bodies = []
    for fp in yaml_files:
        try:
            body = load_tool_yaml(fp)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ❌ {fp.name}: {e}")
            return 1
        if args.only and body.get("displayName") != args.only:
            continue
        bodies.append((fp, body))
    if args.only and not bodies:
        print(f"  ❌ --only '{args.only}' no machea ningun YAML cargado.")
        return 1

    print(f"\n\U0001f4dc LIST de Tools remotos del agente (paginado)...")
    try:
        remote_tools = list_tools(cfg, headers)
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return 1
    existing_by_name = {t["displayName"]: t for t in remote_tools}
    print(f"   ✓ {len(remote_tools)} Tool(s) remotos detectados")

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n\U0001f4dd Procesando {len(bodies)} Tool(s) {mode}...\n")
    for fp, body in bodies:
        print(f"  \U0001f4c4 {fp.name}")
        action = upsert_tool(cfg, headers, body, existing_by_name, args.dry_run)
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
