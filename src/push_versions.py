#!/usr/bin/env python3
"""
src/push_versions.py — Crear / listar Versions de Dialogflow CX.

Sprint 4, Task 2. Diferencia clave con los demas push_*.py: las Versions
son **inmutables**. Solo POST (crea snapshot nuevo) o GET / LIST. NO hay
PATCH.

Endpoint:
  GET  /flows/{f}/versions           - lista versiones del flow
  POST /flows/{f}/versions           - crea snapshot inmutable

Modos CLI:
  - `--list`:   lista versiones existentes (todos los flows o uno).
  - `--create`: crea snapshot nuevo. Acepta:
       a) `--description "..."` (+ `--flow <displayName>`)
                   -> crea ad-hoc en el flow indicado (o Default Start Flow).
                   Caso usado por `.github/workflows/deploy.yml`.
       b) `--file <yaml>`         -> lee body desde YAML declarativo.
       c) `--all`                 -> procesa todos los YAMLs en
                                     definitions/versions/.
  - `--dry-run`: muestra el POST sin enviarlo (solo aplica a --create).

Schema YAML (definitions/versions/*.yaml):
  flow_displayName: "Default Start Flow"   # campo local-only (resuelve flow_id)
  displayName: "v1.0.0"                    # REQUERIDO por la API
  description: "Initial release"

Decisiones tecnicas no negociables:
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project.
  - 0 PATCH/POST reales en Sprint 4 sobre Versions de Petal (solo --dry-run).
  - POST /versions es un LRO: el 200 contiene un Operation, no la Version.
    Hay que polear GET /operations/{id} hasta done=true para detectar
    fallos asincronos (p.ej. "Version display name should be specified").
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"
VERSIONS_DIR = REPO_ROOT / "definitions" / "versions"

DEFAULT_FLOW_DISPLAY_NAME = "Default Start Flow"
_LOCAL_ONLY_FIELDS = {"flow_displayName"}


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
    """LIST /flows con paginacion."""
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
    """Devuelve el path completo del flow cuyo displayName coincide."""
    flows = list_flows(cfg, headers)
    for f in flows:
        if f.get("displayName") == flow_display_name:
            return f["name"]
    raise RuntimeError(
        f"Flow con displayName='{flow_display_name}' no encontrado. "
        f"Flows visibles: {[f.get('displayName') for f in flows]}"
    )


def list_versions(cfg, headers, flow_name):
    """LIST /flows/{flow_id}/versions con paginacion."""
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{flow_name}/versions",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST {flow_name}/versions fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("versions", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


_OP_POLL_INTERVAL_SECONDS = 3
_OP_POLL_TIMEOUT_SECONDS = 180


def wait_for_operation(cfg, headers, op_name, timeout=_OP_POLL_TIMEOUT_SECONDS):
    """Polea GET /v3beta1/{op_name} hasta done=true.

    Devuelve el dict `error` (Status) si la operation fallo, o None si
    completo OK. Levanta TimeoutError si excede `timeout`.
    """
    deadline = time.monotonic() + timeout
    while True:
        r = requests.get(f"{base_url(cfg)}/{op_name}", headers=headers)
        if r.status_code != 200:
            return {"code": r.status_code, "message": r.text[:300]}
        data = r.json()
        if data.get("done"):
            return data.get("error")
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Operation {op_name.split('/')[-1]} no completo en {timeout}s"
            )
        time.sleep(_OP_POLL_INTERVAL_SECONDS)


def create_version(cfg, headers, flow_name, body, dry_run=False):
    """POST /flows/{flow_id}/versions. Crea un snapshot inmutable.

    El POST devuelve un Operation LRO (no la Version). Hay que polear
    GET /operations/{id} hasta done=true para detectar fallos async.
    """
    label = body.get("displayName") or "(auto)"
    desc = body.get("description", "")
    print(f"  + POST version '{label}' on flow={flow_name.split('/')[-1]}")
    if desc:
        print(f"    desc: {desc[:80]}")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(
        f"{base_url(cfg)}/{flow_name}/versions",
        headers=headers, json=body,
    )
    if r.status_code not in (200, 201):
        print(f"     ERR POST {r.status_code}: {r.text[:300]}")
        return False

    try:
        payload = r.json()
    except ValueError:
        payload = {}
    op_name = payload.get("name", "")
    if "/operations/" in op_name:
        print(f"     LRO iniciada, polling {op_name.split('/')[-1]}...")
        try:
            error = wait_for_operation(cfg, headers, op_name)
        except TimeoutError as e:
            print(f"     ERR {e}")
            return False
        if error:
            code = error.get("code")
            msg = error.get("message", "")[:200]
            print(f"     ERR Operation fallo: code={code} msg={msg}")
            return False

    print("     OK Snapshot creado")
    return True


def split_local_fields(raw_body: dict):
    """Separa flow_displayName del body API."""
    flow = raw_body.get("flow_displayName")
    api_body = {k: v for k, v in raw_body.items() if k not in _LOCAL_ONLY_FIELDS}
    return api_body, flow


def load_version_yaml(file_path: Path) -> dict:
    """Carga YAML de Version. Requiere flow_displayName y description."""
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path} no contiene un dict YAML al top-level.")
    if "flow_displayName" not in data:
        raise ValueError(
            f"{file_path} no tiene 'flow_displayName'. Las Versions estan "
            "anidadas bajo Flow."
        )
    if "description" not in data:
        raise ValueError(
            f"{file_path} no tiene 'description'. Es el campo principal "
            "para identificar el snapshot."
        )
    return data


def discover_version_files():
    if not VERSIONS_DIR.exists():
        return []
    return sorted(VERSIONS_DIR.glob("*.yaml")) + sorted(VERSIONS_DIR.glob("*.yml"))


def cmd_list(cfg, headers, flow_filter):
    """`--list`: imprime versiones de uno o todos los flows."""
    flows = list_flows(cfg, headers)
    if flow_filter:
        flows = [f for f in flows if f.get("displayName") == flow_filter]
        if not flows:
            print(f"  ERR Flow '{flow_filter}' no encontrado.")
            return 1
    print(f"\nFlows: {len(flows)}")
    for flow in flows:
        flow_dn = flow.get("displayName", "?")
        flow_name = flow["name"]
        print(f"\n  Flow: {flow_dn}")
        try:
            versions = list_versions(cfg, headers, flow_name)
        except RuntimeError as e:
            print(f"    ERR {e}")
            continue
        if not versions:
            print(f"    (sin versiones)")
            continue
        for v in versions:
            v_dn = v.get("displayName", "?")
            v_state = v.get("state", "?")
            v_create = v.get("createTime", "?")
            print(f"    - {v_dn}  state={v_state}  created={v_create}")
    return 0


def cmd_create(cfg, headers, args):
    """`--create`: crea uno o mas snapshots de version.

    Modos:
      a) --description "..."  -> ad-hoc (deploy.yml)
      b) --file <yaml>        -> declarativo
      c) --all                -> procesa todos los YAMLs
    """
    items = []  # tuplas (flow_displayName, api_body)

    if args.description:
        # Modo ad-hoc (deploy.yml). flow opcional, default Default Start Flow.
        flow_dn = args.flow or DEFAULT_FLOW_DISPLAY_NAME
        body = {"description": args.description}
        if args.display_name:
            body["displayName"] = args.display_name
        items.append((flow_dn, body))
    elif args.file:
        fp = Path(args.file)
        if not fp.is_absolute():
            fp = REPO_ROOT / fp
        try:
            data = load_version_yaml(fp)
        except (FileNotFoundError, ValueError) as e:
            print(f"  ERR {fp.name}: {e}")
            return 1
        api_body, flow_dn = split_local_fields(data)
        items.append((flow_dn, api_body))
    elif args.all:
        files = discover_version_files()
        if not files:
            print(f"  No hay YAMLs en {VERSIONS_DIR}. Nada que hacer.")
            return 0
        for fp in files:
            try:
                data = load_version_yaml(fp)
            except (FileNotFoundError, ValueError) as e:
                print(f"  ERR {fp.name}: {e}")
                return 1
            api_body, flow_dn = split_local_fields(data)
            items.append((flow_dn, api_body))
    else:
        print("  ERR --create requiere --description, --file o --all.")
        return 1

    # Agrupar por flow para evitar resolver flow_id mas de una vez por flow.
    grouped: dict = {}
    for flow_dn, body in items:
        grouped.setdefault(flow_dn, []).append(body)

    stats = {"created": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""

    for flow_dn, bodies in grouped.items():
        print(f"\nResolviendo flow '{flow_dn}'...")
        try:
            flow_name = resolve_flow_id(cfg, headers, flow_dn)
        except RuntimeError as e:
            print(f"  ERR {e}")
            for _ in bodies:
                stats["failed"] += 1
            continue
        print(f"   ok flow_id={flow_name.split('/')[-1]}")
        print(f"\nCreando {len(bodies)} version(es) en '{flow_dn}' {mode}...\n")
        for body in bodies:
            ok = create_version(cfg, headers, flow_name, body, args.dry_run)
            stats["created" if ok else "failed"] += 1

    print(
        f"\n{'='*55}\n"
        f"created={stats['created']}  failed={stats['failed']}"
        f"\n{'='*55}"
    )
    return 0 if stats["failed"] == 0 else 1


def main():
    ap = argparse.ArgumentParser(
        description="Crear / listar Versions de Dialogflow CX (immutables).",
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", dest="list_mode", action="store_true",
                      help="Lista versiones existentes")
    mode.add_argument("--create", action="store_true",
                      help="Crea una nueva version snapshot")

    # --create options:
    ap.add_argument("--description",
                    help="Descripcion de la nueva version (modo ad-hoc, deploy.yml)")
    ap.add_argument("--display-name",
                    help="displayName opcional para la version (modo ad-hoc)")
    ap.add_argument("--file", help="Path a YAML de version (modo declarativo)")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs en definitions/versions/")
    ap.add_argument("--dry-run", action="store_true",
                    help="No envia POST; muestra que se haria")
    ap.add_argument("--flow",
                    help="Filtrar por flow (--list) o destino (--create)")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    if args.list_mode:
        return cmd_list(cfg, headers, args.flow)
    return cmd_create(cfg, headers, args)


if __name__ == "__main__":
    sys.exit(main())
