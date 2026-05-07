#!/usr/bin/env python3
"""
src/push_examples.py — Crear/upsert Examples en un Playbook de Dialogflow CX.

Decisiones tecnicas no negociables (Sprint 1):
  - Auth: `gcloud auth print-access-token` (NO google.auth.default).
  - Header obligatorio x-goog-user-project (definido en definitions/agent.yaml).
  - Constantes especificas del proyecto en YAML, no hardcoded.

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
import subprocess
import sys
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML_DEFAULT = REPO_ROOT / "definitions" / "agent.yaml"


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
        print("     (dry-run, no se envia)")
        return True
    r = requests.post(f"{base_url(cfg)}/{parent}/examples", headers=headers, json=body)
    if r.status_code == 200:
        print("     ✅ Creado")
        return True
    print(f"     ❌ Error {r.status_code}: {r.text}")
    return False


def main():
    ap = argparse.ArgumentParser(description="Crear/upsert Examples en un Playbook de CX.")
    ap.add_argument("--playbook", help="displayName del Playbook destino")
    ap.add_argument("--file", help="Path al YAML de Examples (relativo al repo o absoluto)")
    ap.add_argument("--dry-run", action="store_true", help="No envia POST")
    ap.add_argument("--list-playbooks", action="store_true", help="Listar Playbooks del agente y salir")
    ap.add_argument("--only", help="ID del Example a crear (filtra por campo `id` del YAML)")
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

    stats = {"OK": 0, "FAIL": 0}
    print(f"\n\U0001f4dd Creando {len(examples)} Example(s) {'(DRY-RUN)' if args.dry_run else ''}...\n")
    for ex in examples:
        body = {k: v for k, v in ex.items() if k != "id"}
        body = inject_tool_path(body, cfg)
        ok = create_example(cfg, headers, parent, body, args.dry_run)
        stats["OK" if ok else "FAIL"] += 1

    print(f"\n{'='*50}\n\U0001f4ca OK: {stats['OK']}  FAIL: {stats['FAIL']}\n{'='*50}")
    return 0 if stats["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
