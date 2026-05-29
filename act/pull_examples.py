#!/usr/bin/env python3
"""
act/pull_examples.py — Exporta Examples de CX -> YAMLs locales.

Espejo READ-ONLY de push_examples.py refactorizado en PR10a. Solo GET;
nunca POST/PATCH/DELETE.

Los Examples son sub-recursos de Playbooks: el script itera todos los
playbooks, lista sus examples, y escribe cada uno como
  definitions/examples/<playbook_slug>/<example_slug>.yaml
con los campos local-only `playbook` (parent resolver) y `id` (UUID,
rename-resistant lookup).

Round-trip-clean: tras correr este pull, `push_examples.py --all
--dry-run` debe reportar unchanged=N para los N examples.

Uso:
  python act/pull_examples.py --dry-run
  python act/pull_examples.py
  python act/pull_examples.py --only "Ex_Reg_01"
"""
import argparse
import os
import re
import sys
from pathlib import Path

import yaml

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from push_examples import (  # noqa: E402
    EXAMPLES_DIR,
    build_headers,
    get_token,
    list_examples,
    list_playbooks,
    load_agent_config,
)


# Read-only del lado pull. `name` se extrae como `id` (NO se persiste el
# path completo); el resto se descarta.
PULL_STRIP_FIELDS = ("name", "tokenCount", "createTime", "updateTime")

# Orden canonico de claves en el YAML de salida.
# playbook + id van primero (local-only, contrato del push refactorizado);
# despues los campos API del example en orden natural.
_CANONICAL_ORDER = (
    "playbook",
    "id",
    "displayName",
    "description",
    "actions",
    "playbookInput",
    "playbookOutput",
    "conversationState",
    "tokenCount",  # ignorado por strip, pero si por algun motivo apareciera, va aqui
)


def slugify(display_name: str) -> str:
    """displayName -> nombre de fichero seguro.

    Reglas: lowercase, espacios/slashes/dashes-largos -> _, drop non-alnum,
    colapsa underscores multiples, strip trailing separators, fallback
    'unnamed'.
    """
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = re.sub(r"_+", "_", s)         # colapsa _ multiples (de chars eliminados)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict, parent_playbook_display_name: str) -> dict:
    """Transforma respuesta de CX al formato pull-friendly.

    - Strippea PULL_STRIP_FIELDS pero extrae el UUID del `name` como `id`.
    - Inyecta `playbook` (local-only) con el displayName del padre.
    - Reordena segun _CANONICAL_ORDER; claves desconocidas al final.
    """
    # Extraer UUID del name antes de strippear
    example_id = ""
    name = remote.get("name", "")
    if isinstance(name, str) and name:
        example_id = name.rsplit("/", 1)[-1]

    stripped = {k: v for k, v in remote.items() if k not in PULL_STRIP_FIELDS}
    # Inyectar local-only
    stripped["playbook"] = parent_playbook_display_name
    if example_id:
        stripped["id"] = example_id

    ordered: dict = {}
    for k in _CANONICAL_ORDER:
        if k in stripped:
            ordered[k] = stripped.pop(k)
    ordered.update(stripped)
    return ordered


# ----------------------------------------------------------------
# Dumper custom: usa bloque literal `|` para strings multi-linea
# (acciones de examples pueden tener agentUtterance.text largos).
# ----------------------------------------------------------------
class _ExampleYAMLDumper(yaml.SafeDumper):
    pass


def _multiline_str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_ExampleYAMLDumper.add_representer(str, _multiline_str_representer)


def dump_yaml(body: dict) -> str:
    return yaml.dump(
        body,
        Dumper=_ExampleYAMLDumper,
        sort_keys=False,
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
        width=1000,
    )


def main():
    ap = argparse.ArgumentParser(
        description="Exporta Examples de CX -> definitions/examples/<playbook>/<example>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Example a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Playbooks remotos (para iterar sus Examples)...")
    # list_playbooks devuelve tuples (name, displayName)
    playbooks = list_playbooks(cfg, headers)
    print(f"   ✓ {len(playbooks)} Playbook(s) remotos detectados")

    # Recolectar todos los examples agrupados por playbook padre.
    # Estructura: [(playbook_display_name, playbook_name, example_summary), ...]
    all_examples: list[tuple[str, str, dict]] = []
    for pb_name, pb_dn in playbooks:
        try:
            exs = list_examples(cfg, headers, pb_name)
        except RuntimeError as e:
            print(f"  ⚠ {pb_dn}: {e}")
            continue
        for ex in exs:
            all_examples.append((pb_dn, pb_name, ex))
        print(f"   • {pb_dn}: {len(exs)} example(s)")

    if args.only:
        all_examples = [t for t in all_examples if t[2].get("displayName") == args.only]
        if not all_examples:
            print(f"  ⚠ --only '{args.only}' no machea ningun Example remoto.")
            return 1

    if not all_examples:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(all_examples)} Example(s) {mode}...\n")

    for pb_dn, _pb_name, summary in all_examples:
        dn = summary.get("displayName", "?")
        # Para Examples, LIST ya devuelve el body completo (no hace falta GET
        # adicional por example — el endpoint list devuelve datos completos
        # incluyendo actions).
        full = summary
        local = cx_to_local(full, parent_playbook_display_name=pb_dn)
        stats["pulled"] += 1

        playbook_subdir = EXAMPLES_DIR / slugify(pb_dn)
        out_path = playbook_subdir / f"{slugify(dn)}.yaml"
        text = dump_yaml(local)
        n_actions = len(local.get("actions", []) or [])

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(EXAMPLES_DIR.parent.parent)}  ({len(text)} bytes, actions={n_actions})")
        else:
            playbook_subdir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text)
            print(f"  ✓ {pb_dn}/{dn} -> {out_path.relative_to(EXAMPLES_DIR.parent.parent)}  (actions={n_actions})")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
