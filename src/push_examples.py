#!/usr/bin/env python3
"""
src/push_examples.py — Crear/upsert Examples en un Playbook de Dialogflow CX.

Idempotencia (Sprint 2, Task 3 — refactor PR10a Sprint 5): patron
`LIST -> diff -> PATCH/POST`.
- LIST de Examples del Playbook target (paginado).
- Match por `id` (UUID, rename-resistant) y fallback a `displayName`.
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

Schema YAML — one example per file, anidado por playbook (PR10a Sprint 5):
  # definitions/examples/<playbook_slug>/<example_slug>.yaml
  playbook: Registro_Task        # local-only — resuelve el playbook padre
  id: 084bc84b-...               # local-only — UUID del example en CX
                                 #   (rename-resistant: si cambias displayName
                                 #    pero mantienes id, push hace PATCH en
                                 #    lugar de crear duplicado)
  displayName: Registro completo
  actions: [...]
  playbookInput: {...}
  playbookOutput: {...}

Uso:
  python src/push_examples.py --list-playbooks
  python src/push_examples.py --file=definitions/examples/registro_task/ex_reg_01.yaml --dry-run
  python src/push_examples.py --all --dry-run
  python src/push_examples.py --all --only "Ex_Reg_01"  # filtra por displayName
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
EXAMPLES_DIR = REPO_ROOT / "definitions" / "examples"

# Campos read-only del recurso Example. NO entran en diff ni updateMask.
EXAMPLE_IGNORE_FIELDS = ["name", "tokenCount", "createTime", "updateTime"]

# Campos local-only del YAML: existen para que push resuelva parent/lookup
# pero NO se envian al API.
_LOCAL_ONLY_FIELDS = {"playbook", "id"}


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


def split_local_fields(raw_body):
    """Separa campos local-only (playbook, id) del body que va al API.
    Devuelve (api_body, playbook_name, example_id).
    """
    playbook = raw_body.get("playbook")
    example_id = raw_body.get("id")
    api_body = {k: v for k, v in raw_body.items() if k not in _LOCAL_ONLY_FIELDS}
    return api_body, playbook, example_id


def find_existing_example(remote_examples, example_id, display_name):
    """Lookup rename-resistant: primero por id (UUID), fallback a displayName.

    - Si example_id no es None, busca un remoto cuyo `name` termine en ese id.
    - Si no encuentra (o example_id es None), busca por displayName.
    - Devuelve el dict remoto completo o None.
    """
    if example_id:
        for ex in remote_examples:
            if ex.get("name", "").rsplit("/", 1)[-1] == example_id:
                return ex
    for ex in remote_examples:
        if ex.get("displayName") == display_name:
            return ex
    return None


def upsert_example(cfg, headers, parent, body, example_id, remote_examples, dry_run=False):
    """LIST -> diff -> PATCH/POST. Devuelve la accion ejecutada:
    'created' | 'updated' | 'unchanged' | 'failed'.

    body es el api_body (sin campos local-only). example_id es el UUID
    para lookup rename-resistant; puede ser None (push se basara solo
    en displayName, perdiendo rename-resistance).
    """
    remote = find_existing_example(remote_examples, example_id, body["displayName"])
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


def discover_example_files():
    """Descubre todos los YAMLs recursivamente (subcarpetas por playbook).

    Tras PR10a, el layout es:
      definitions/examples/<playbook_slug>/<example_slug>.yaml

    Excluye .gitkeep y cualquier no-yaml.
    """
    if not EXAMPLES_DIR.is_dir():
        return []
    return sorted(EXAMPLES_DIR.rglob("*.yaml"))


def load_example_yaml(file_path):
    """Carga un YAML de un Example individual.

    Schema (PR10a):
      playbook: <displayName>     (local-only, requerido)
      id: <uuid>                  (local-only, opcional pero recomendado)
      displayName: <str>          (api body, requerido)
      actions: [...]              (api body)
      playbookInput: {...}        (api body)
      playbookOutput: {...}       (api body)

    Devuelve (playbook_name, example_id, api_body).
    """
    with open(file_path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{file_path}: YAML no contiene un dict al top-level.")
    if not data.get("playbook"):
        raise ValueError(f"{file_path}: falta clave 'playbook' al top-level.")
    if not data.get("displayName"):
        raise ValueError(f"{file_path}: falta clave 'displayName' al top-level.")
    api_body, playbook, example_id = split_local_fields(data)
    return playbook, example_id, api_body


def process_examples_for_playbook(cfg, headers, playbook_name, examples_with_ids, dry_run):
    """Resuelve el Playbook, lista remotos y hace upsert. Devuelve stats.

    examples_with_ids es lista de (example_id, api_body) tuples.
    """
    print(f"\n\U0001f50d Resolviendo Playbook '{playbook_name}'...")
    parent = find_playbook(cfg, headers, playbook_name)
    if not parent:
        return {"created": 0, "updated": 0, "unchanged": 0, "failed": len(examples_with_ids)}
    print(f"   ✓ ID {parent.split('/')[-1]}")

    print(f"\n\U0001f4dc LIST de Examples remotos del Playbook (paginado)...")
    try:
        remote_examples = list_examples(cfg, headers, parent)
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return {"created": 0, "updated": 0, "unchanged": 0, "failed": len(examples_with_ids)}
    print(f"   ✓ {len(remote_examples)} Example(s) remotos detectados")

    stats = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
    mode = "(DRY-RUN)" if dry_run else ""
    print(f"\n\U0001f4dd Procesando {len(examples_with_ids)} Example(s) {mode}...\n")
    for example_id, body in examples_with_ids:
        body = inject_tool_path(body, cfg)
        action = upsert_example(cfg, headers, parent, body, example_id, remote_examples, dry_run)
        stats[action] += 1
    return stats


def main():
    ap = argparse.ArgumentParser(description="Crear/upsert Examples en un Playbook de CX (idempotente).")
    ap.add_argument("--file", help="Path a un YAML de Example individual (relativo al repo o absoluto). El playbook padre se lee del propio YAML.")
    ap.add_argument("--all", action="store_true",
                    help="Procesar todos los YAMLs recursivamente en definitions/examples/<playbook>/")
    ap.add_argument("--dry-run", action="store_true", help="No envia POST/PATCH; muestra que se haria")
    ap.add_argument("--list-playbooks", action="store_true", help="Listar Playbooks del agente y salir")
    ap.add_argument("--only", help="displayName del Example a procesar (filtra YAMLs antes de procesar; internamente la API usa el id local)")
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

    if args.all and args.file:
        ap.error("--all y --file son excluyentes")
    if not args.all and not args.file:
        ap.error("debes pasar --file <path> o --all (o usa --list-playbooks)")

    # 1) Cargar YAMLs (uno o todos), agrupar por playbook.
    if args.all:
        yaml_files = discover_example_files()
    else:
        file_path = Path(args.file)
        if not file_path.is_absolute():
            file_path = REPO_ROOT / file_path
        yaml_files = [file_path]

    if not yaml_files:
        print(f"  ⚠  No hay YAMLs en {EXAMPLES_DIR}. Nada que hacer.")
        return 0

    grouped: dict[str, list[tuple]] = {}  # playbook_name -> [(example_id, api_body), ...]
    load_failed = 0
    for fp in yaml_files:
        print(f"\n\U0001f4c4 Cargando {fp}...")
        try:
            playbook_name, example_id, api_body = load_example_yaml(fp)
        except (ValueError, FileNotFoundError) as e:
            print(f"  ❌ {e}")
            load_failed += 1
            continue
        if args.only and api_body.get("displayName") != args.only:
            continue
        grouped.setdefault(playbook_name, []).append((example_id, api_body))

    if args.only and not grouped:
        print(f"  ❌ --only '{args.only}' no machea ningun YAML cargado.")
        return 1

    if not grouped:
        if load_failed:
            return 1
        print("  ⚠  Nada que procesar tras el filtro.")
        return 0

    # 2) Por cada playbook: LIST remoto, upsert sus examples.
    total = {"created": 0, "updated": 0, "unchanged": 0, "failed": load_failed}
    for playbook_name, examples_with_ids in grouped.items():
        stats = process_examples_for_playbook(
            cfg, headers, playbook_name, examples_with_ids, args.dry_run,
        )
        for k in total:
            if k in stats:
                total[k] += stats[k]

    print(
        f"\n{'='*55}\n"
        f"\U0001f4ca [TOTAL] created={total['created']}  "
        f"updated={total['updated']}  "
        f"unchanged={total['unchanged']}  "
        f"failed={total['failed']}"
        f"\n{'='*55}"
    )
    return 0 if total["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
