#!/usr/bin/env python3
"""
act/deploy.py — Deploy interactivo local para Petal CX.

⚠️  CLAUDE CODE — PROTOCOLO OBLIGATORIO ANTES DE EJECUTAR ESTE SCRIPT:
    1. Pregunta a Jero qué cambios quiere deployar.
    2. Pregunta si quiere crear snapshot y con qué nombre.
    3. Muestra el resumen y espera confirmación explícita ("sí", "hazlo").
    4. Solo entonces ejecuta.
    NUNCA ejecutar este script sin permiso explícito de Jero.
    "seguimos", "vamos", "continúa" NO son autorización para ejecutar.

Flujo:
  1. Lee git diff para detectar qué cambió en definitions/
  2. Muestra resumen automático de cambios
  3. Pregunta si crear snapshot y con qué nombre
  4. Ejecuta los push_*.py necesarios en orden topológico
  5. Si se pidió snapshot → crea Version y actualiza staging

Uso:
  python act/deploy.py
  python act/deploy.py --dry-run
"""

import subprocess
import sys
import time
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_YAML = REPO_ROOT / "definitions" / "agent.yaml"
ACT_DIR = REPO_ROOT / "act"

# Orden topológico de deploy (igual que deploy.yml)
DEPLOY_STEPS = [
    ("definitions/agent.yaml",      ["python", "act/push_agent_config.py"]),
    ("definitions/entity_types/",   ["python", "act/push_entity_types.py", "--all"]),
    ("definitions/intents/",        ["python", "act/push_intents.py", "--all"]),
    ("definitions/webhooks/",       ["python", "act/push_webhooks.py", "--all"]),
    ("definitions/generators/",     ["python", "act/push_generators.py", "--all"]),
    ("definitions/tools/",          ["python", "act/push_tools.py", "--all"]),
    ("definitions/flows/",          ["python", "act/push_flows.py", "--all"]),
    ("definitions/pages/",          ["python", "act/push_pages.py", "--all"]),
    ("definitions/playbooks/",      ["python", "act/push_playbooks.py", "--all"]),
    ("definitions/examples/",       ["python", "act/push_examples.py", "--all"]),
]

# IDs de los Environments (de definitions/environments/)
STAGING_ENV_ID  = "90ce0a8c-7e68-4526-ada5-ce8b600628fd"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_agent_config():
    with open(AGENT_YAML) as f:
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
    return (
        f"projects/{cfg['project']}/locations/{cfg['location']}"
        f"/agents/{cfg['agent_id']}"
    )


def base_url(cfg):
    return cfg["api"]["base_v3beta1"]


# ---------------------------------------------------------------------------
# 1. Detectar cambios
# ---------------------------------------------------------------------------

def get_changed_files():
    """Devuelve lista de archivos modificados respecto al último commit."""
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    files = [f.strip() for f in r.stdout.splitlines() if f.strip()]

    # También untracked en definitions/ (nuevos archivos no staged)
    r2 = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "definitions/"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    files += [f.strip() for f in r2.stdout.splitlines() if f.strip()]
    return files


def describe_changes(changed_files):
    """Genera resumen legible a partir de los archivos cambiados."""
    areas = []
    area_map = {
        "definitions/playbooks/":   "playbooks",
        "definitions/examples/":    "examples",
        "definitions/flows/":       "flows",
        "definitions/pages/":       "pages",
        "definitions/intents/":     "intents",
        "definitions/entity_types/":"entity types",
        "definitions/tools/":       "tools",
        "definitions/webhooks/":    "webhooks",
        "definitions/generators/":  "generators",
        "definitions/agent.yaml":   "agent config",
    }
    seen = set()
    for f in changed_files:
        for prefix, label in area_map.items():
            if f.startswith(prefix) and label not in seen:
                seen.add(label)
                areas.append(label)
    if not areas:
        return "sin cambios en definitions/"
    return "cambios en: " + ", ".join(areas)


def which_steps_to_run(changed_files):
    """Devuelve solo los pasos cuya área tiene cambios."""
    steps = []
    for prefix, cmd in DEPLOY_STEPS:
        if any(f.startswith(prefix) or f == prefix.rstrip("/") for f in changed_files):
            steps.append(cmd)
    return steps


# ---------------------------------------------------------------------------
# 2. Ejecutar push scripts
# ---------------------------------------------------------------------------

def run_step(cmd, dry_run=False):
    label = " ".join(cmd[1:])
    print(f"\n  → {label}")
    if dry_run:
        print("    (dry-run — no se ejecuta)")
        return True
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# 3. Crear Version y actualizar staging
# ---------------------------------------------------------------------------

def create_version(cfg, headers, display_name, description, dry_run=False):
    """Crea Version vía push_versions.py y devuelve True/False."""
    cmd = [
        "python", "act/push_versions.py",
        "--create",
        f"--display-name={display_name}",
        f"--description={description}",
    ]
    if dry_run:
        cmd.append("--dry-run")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    return r.returncode == 0


def get_latest_version_name(cfg, headers):
    """LIST versions del Default Start Flow y devuelve el name de la más reciente."""
    flow_id = "00000000-0000-0000-0000-000000000000"
    flow_path = f"{parent_path(cfg)}/flows/{flow_id}"
    r = requests.get(
        f"{base_url(cfg)}/{flow_path}/versions",
        headers=headers,
        params={"pageSize": 100},
    )
    if r.status_code != 200:
        print(f"  ERR LIST versions: {r.status_code} {r.text[:200]}")
        return None
    versions = r.json().get("versions", [])
    if not versions:
        return None
    latest = max(versions, key=lambda v: v.get("createTime", ""))
    return latest["name"]


def update_staging(cfg, headers, version_name, env_id=STAGING_ENV_ID, dry_run=False):
    """PATCH el Environment staging para apuntar a version_name."""
    env_path = f"{parent_path(cfg)}/environments/{env_id}"
    body = {"versionConfigs": [{"version": version_name}]}
    print(f"\n  → PATCH staging → {version_name.split('/')[-1]}")
    if dry_run:
        print("    (dry-run — no se envía PATCH)")
        return True
    r = requests.patch(
        f"{base_url(cfg)}/{env_path}",
        headers=headers,
        json=body,
    )
    if r.status_code == 200:
        print("    OK staging actualizado")
        return True
    print(f"    ERR PATCH {r.status_code}: {r.text[:300]}")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def ask(prompt, default=None):
    """Pregunta interactiva. Devuelve la respuesta en minúsculas."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAbortado.")
        sys.exit(0)
    return answer.lower() if answer else (default or "")


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Deploy interactivo local para Petal CX.")
    ap.add_argument("--dry-run", action="store_true", help="Muestra qué haría sin ejecutar nada")
    args = ap.parse_args()

    dry_run = args.dry_run
    mode = " (DRY-RUN)" if dry_run else ""

    print(f"\n{'='*55}")
    print(f"  Petal Deploy{mode}")
    print(f"{'='*55}\n")

    # 1. Detectar cambios
    changed = get_changed_files()
    summary = describe_changes(changed)
    steps = which_steps_to_run(changed)

    print(f"Cambios detectados: {summary}")
    if changed:
        for f in changed:
            print(f"  {f}")

    if not steps:
        print("\nNingún cambio en definitions/ que requiera deploy.")
        print("Si hay cambios sin staged, haz `git add` primero.")
        return 0

    print(f"\nPasos a ejecutar ({len(steps)}):")
    for cmd in steps:
        print(f"  {' '.join(cmd[1:])}")

    # 2. Snapshot
    print()
    create_snap = ask("¿Crear snapshot?", default="s") in ("s", "si", "sí", "y", "yes")
    snap_name = None

    if create_snap:
        default_name = summary.replace("cambios en: ", "").replace(", ", "-").replace(" ", "-")
        snap_name = ask("Nombre del snapshot", default=default_name) or default_name
        # Limpiar caracteres no válidos
        snap_name = snap_name.replace(" ", "-").replace("/", "-")[:50]
        print(f"  Snapshot: {snap_name}")

    # 3. Confirmar
    print(f"\nResumen:")
    print(f"  Draft       → se actualiza con los cambios")
    if create_snap:
        print(f"  Snapshot    → {snap_name}")
        print(f"  staging     → apuntará al nuevo snapshot")
    print(f"  production  → sin cambios")
    print()

    confirm = ask("¿Continuar?", default="s")
    if confirm not in ("s", "si", "sí", "y", "yes"):
        print("Abortado.")
        return 0

    print(f"\n{'─'*55}")
    print("Ejecutando deploy...\n")

    # 4. Ejecutar push scripts
    cfg = load_agent_config()
    token = get_token()
    headers = build_headers(cfg, token)

    for cmd in steps:
        ok = run_step(cmd, dry_run=dry_run)
        if not ok:
            print(f"\n  ERR {' '.join(cmd)} falló. Abortando.")
            return 1

    # 5. Crear snapshot y actualizar staging
    if create_snap:
        print(f"\n{'─'*55}")
        print("Creando snapshot...\n")
        ok = create_version(cfg, headers, snap_name, f"Deploy manual: {summary}", dry_run=dry_run)
        if not ok:
            print("  ERR No se pudo crear el snapshot.")
            return 1

        if not dry_run:
            print("\nObteniendo nombre de la version recién creada...")
            time.sleep(2)  # pequeña espera para que la LRO complete
            version_name = get_latest_version_name(cfg, headers)
            if not version_name:
                print("  ERR No se pudo obtener el nombre de la version.")
                return 1
            ok = update_staging(cfg, headers, version_name, dry_run=dry_run)
            if not ok:
                return 1

    print(f"\n{'='*55}")
    print("  Deploy completado.")
    if create_snap and not dry_run:
        print(f"  staging → {snap_name}")
    print(f"{'='*55}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
