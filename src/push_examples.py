#!/usr/bin/env python3
"""
src/push_examples.py — Crear/upsert Examples en un Playbook de Dialogflow CX.

Idempotencia (Sprint 2, Task 3): patron `LIST -> diff -> PATCH/POST`.
- LIST de Examples del Playbook target (paginado).
- Match por displayName.
- Si no existe -> POST.
- Si existe -> diff vs local (ignorando campos read-only) -> PATCH parcial
  con updateMask SOLO si hay cambios.
- Reporta al final: created / updated / unchanged / failed.

Decisiones tecnicas no negociables (Sprint 1):
  - Auth: `gcloud auth print-access-token` (NO google.auth.default).
  - Header obligatorio x-goog-user-project (definido en definitions/agent.yaml).
  - Constantes especificas del proyecto en YAML, no hardcoded.

Concurrencia (Sprint 2): asumir last-write-wins. La proteccion real
(`concurrency: 1` en GitHub Actions) llega en Sprint 4.

Uso:
  python src/push_examples.py --list-playbooks
  python src/push_examples.py --playbook=Registro_Task --file=definitions/examples/registro_task.yaml --dry-run
  python src/push_examples.py --playbook=Registro_Task --file=definitions/examples/registro_task.yaml
  python src/push_examples.py --playbook=Registro_Task --file=definitions/examples/registro_task.yaml --only EX_REG_01

Schema YAML esperado (definitions/examples/<playbook>.yaml):
  playbook: Registro_Task
  examples:
    - id: EX_REG_01
      displayName: "..."
      actions: [...]
      playbookOutput: { actionParameters: {...} }
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

# Permitir import directo desde src/ tanto al ejecutar el script
# (`python src/push_examples.py`) como al importarlo desde un test.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from diff import DiffResult, diff_resource  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"

# Campos read-only del recurso Example. NO entran en diff ni updateMask.
EXAMPLE_IGNORE_FIELDS = ["name", "tokenCount", "createTime", "updateTime"]


def load_agent_config(path=AGENT_YAML_DEFAULT):
    with open(path) as f:
        return yaml.safe_load(f)


def get_token():
    """Token via gcloud — decision tecnica no negociable."""
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
    r = requests.get(f"{base_url(cfg)}/{parent_path(cfg)}/playbooks", headers=headers)
    if r.status_code != 200:
        print(f"  ❌ Error listando playbooks {r.status_code}: {r.text}")
        return []
    return [(pb["name"], pb.get("displayName", "")) for pb in r.json().get("playbooks", [])]


def find_playbook(cfg, headers, display_name):
    pbs = list_playbooks(cfg, headers)
    matches = [name for name, dn in pbs if dn.lower() == display_name.lower()]
    if not matches:
        print(f"  ❌ Playbook con displayName '{display_name}' no encontrado")
        if pbs:
            print("     Disponibles:")
            for _, dn in pbs:
                print(f"       - {dn}")
        return None
    if len(matches) > 1:
        print(f"  ⚠  {len(matches)} playbooks con '{display_name}'. Uso el primero.")
    return matches[0]


def list_examples(cfg, headers, parent_playbook):
    """LIST /examples del Playbook con paginacion (nextPageToken).

    Devuelve lista plana de dicts (cada uno con `name`, `displayName`,
    `actions`, etc., tal como los devuelve la API).
    """
    items = []
    next_token = None
    page = 0
    while True:
        page += 1
        params = {"pageSize": 100}
        if next_token:
            params["pageToken"] = next_token
        r = requests.get(
            f"{base_url(cfg)}/{parent_playbook}/examples",
            headers=headers, params=params,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"LIST /examples fallo en pagina {page}: "
                f"{r.status_code} {r.text[:300]}"
            )
        data = r.json()
        items.extend(data.get("examples", []))
        next_token = data.get("nextPageToken")
        if not next_token:
            break
    return items


def inject_tool_path(example, cfg):
    """Inyecta el campo 'tool' (full path) en cada toolUse si no esta presente.
    El YAML deja el campo fuera para mantenerlo agnostico al agente."""
    tool_path = f"{parent_path(cfg)}/tools/{cfg['tool']['id']}"
    for action in example.get("actions", []) or []:
        if "toolUse" in action and "tool" not in action["toolUse"]:
            action["toolUse"]["tool"] = tool_path
    return example


def create_example(cfg, headers, parent, body, dry_run=False):
    print(f"  ➕ {body['displayName']}")
    if dry_run:
        print("     (dry-run, no se envia POST)")
        return True
    r = requests.post(f"{base_url(cfg)}/{parent}/examples", headers=headers, json=body)
    if r.status_code == 200:
        print("     ✅ Creado")
        return True
    print(f"     ❌ Error POST {r.status_code}: {r.text[:300]}")
    return False


def patch_example(cfg, headers, name, payload, update_mask, dry_run=False):
    """PATCH parcial con updateMask. payload es el sub-dict de campos
    cambiados; update_mask es la lista de paths con notacion punto.
    """
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


def upsert_example(cfg, headers, parent, body, existing_by_name, dry_run=False):
    """LIST -> diff -> PATCH/POST. Devuelve la accion ejecutada:
    'created' | 'updated' | 'unchanged' | 'failed'.
    """
    remote = existing_by_name.get(body["displayName"])
    if remote is None:
        ok = create_example(cfg, headers, parent, body, dry_run)
        return "created" if ok else "failed"

    result: DiffResult = diff_resource(
        body, remote, ignore_fields=EXAMPLE_IGNORE_FIELDS,
    )
    if not result.needs_update:
        print(f"  = {body['displayName']} (unchanged)")
        return "unchanged"

    ok = patch_example(
        cfg, headers,
        name=remote["name"],
        payload=result.patch_payload,
        update_mask=result.update_mask,
        dry_run=dry_run,
    )
    return "updated" if ok else "failed"


def main():
    ap = argparse.ArgumentParser(description="Crear/upsert Examples en un Playbook de CX (idempotente).")
    ap.add_argument("--playbook", help="displayName del Playbook destino")
    ap.add_argument("--file", help="Path al YAML de Examples (relativo al repo o absoluto)")
    ap.add_argument("--dry-run", action="store_true", help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--list-playbooks", action="store_true", help="Listar Playbooks del agente y salir")
    ap.add_argument("--only", help="ID del Example a procesar (filtra por campo `id` del YAML)")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    if args.list_playbooks:
        print(f"\n\U0001f4cb Playbooks del agente {cfg['agent_id']}:")
        for name, dn in list_playbooks(cfg, headers):
            print(f"   {dn:35s}  ID: {name.split('/')[-1]}")
        return 0

    if not args.playbook or not args.file:
        ap.error("--playbook y --file son obligatorios (o usa --list-playbooks)")

    file_path = Path(args.file)
    if not file_path.is_absolute():
        file_path = REPO_ROOT / file_path
    print(f"\n\U0001f4c4 Cargando {file_path}...")
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not data or "examples" not in data:
        print("  ❌ El YAML no contiene clave 'examples'.")
        return 1

    print(f"\n\U0001f50d Resolviendo Playbook '{args.playbook}'...")
    parent = find_playbook(cfg, headers, args.playbook)
    if not parent:
        return 1
    print(f"   ✓ ID {parent.split('/')[-1]}")

    examples = data["examples"]
    if args.only:
        examples = [e for e in examples if e.get("id") == args.only]
        if not examples:
            print(f"  ❌ --only {args.only} no encontrado en el YAML.")
            return 1

    print(f"\n\U0001f4dc LIST de Examples remotos del Playbook (paginado)...")
    try:
        remote_examples = list_examples(cfg, headers, parent)
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return 1
    existing_by_name = {ex["displayName"]: ex for ex in remote_examples}
    print(f"   ✓ {len(remote_examples)} Example(s) remotos detectados")

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n\U0001f4dd Procesando {len(examples)} Example(s) {mode}...\n")
    for ex in examples:
        body = {k: v for k, v in ex.items() if k != "id"}
        body = inject_tool_path(body, cfg)
        action = upsert_example(cfg, headers, parent, body, existing_by_name, args.dry_run)
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
