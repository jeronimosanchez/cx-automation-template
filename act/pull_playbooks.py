#!/usr/bin/env python3
"""
act/pull_playbooks.py — Exporta Playbooks de CX -> YAMLs locales.

Espejo READ-ONLY de push_playbooks.py (Sprint 5, PR9). Solo GET; nunca
POST/PATCH/DELETE.

Sobre el bug §3.8 (region europe-west1, PATCH+updateMask falla en
Playbooks): este pull es read-only, asi que no toca el bug. Pero el
round-trip-check con `push_playbooks.py --dry-run` debe reportar
unchanged=N para los N playbooks — si reportara updated=X, en
produccion el push fallaria con el bug. Por eso el cx_to_local strippea
EXACTAMENTE los read-only declarados en PLAYBOOK_IGNORE_FIELDS del push.

YAML output:
  - Bloque literal `|` para strings multi-linea (instruction.steps[].text
    suele tener miles de chars en espanol — mucho mas legible asi).
  - allow_unicode=True para preservar caracteres espanoles sin escape.
  - sort_keys=False para mantener el orden canonico.

Uso:
  python act/pull_playbooks.py --dry-run
  python act/pull_playbooks.py
  python act/pull_playbooks.py --only Handoff
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

from push_playbooks import (  # noqa: E402
    PLAYBOOKS_DIR,
    build_headers,
    get_playbook,
    get_token,
    list_playbooks,
    load_agent_config,
)


# Mismos read-only que PLAYBOOK_IGNORE_FIELDS de push (incluye tokenCount,
# que CX calcula y devuelve pero no acepta como input).
PULL_STRIP_FIELDS = ("name", "tokenCount", "createTime", "updateTime")

_CANONICAL_ORDER = (
    "displayName",
    "goal",
    "playbookType",
    "referencedTools",
    "referencedPlaybooks",
    "referencedFlows",
    "inputParameterDefinitions",
    "outputParameterDefinitions",
    "instruction",
)


def slugify(display_name: str) -> str:
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict) -> dict:
    stripped = {k: v for k, v in remote.items() if k not in PULL_STRIP_FIELDS}
    ordered: dict = {}
    for k in _CANONICAL_ORDER:
        if k in stripped:
            ordered[k] = stripped.pop(k)
    ordered.update(stripped)
    return ordered


# ----------------------------------------------------------------
# Dumper custom: usa bloque literal `|` para strings multi-linea.
# Scoped a este modulo via subclase de SafeDumper para no contaminar
# el dump global de PyYAML.
# ----------------------------------------------------------------
class _PlaybookYAMLDumper(yaml.SafeDumper):
    pass


def _multiline_str_representer(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_PlaybookYAMLDumper.add_representer(str, _multiline_str_representer)


def dump_yaml(body: dict) -> str:
    return yaml.dump(
        body,
        Dumper=_PlaybookYAMLDumper,
        sort_keys=False,
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
        width=1000,  # evita que PyYAML rompa lineas largas con folding
    )


def main():
    ap = argparse.ArgumentParser(
        description="Exporta Playbooks de CX -> definitions/playbooks/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Playbook a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Playbooks remotos (paginado)...")
    summaries = list_playbooks(cfg, headers)
    print(f"   ✓ {len(summaries)} Playbook(s) remotos detectados")

    if args.only:
        summaries = [s for s in summaries if s.get("displayName") == args.only]
        if not summaries:
            print(f"  ⚠ --only '{args.only}' no machea ningun Playbook remoto.")
            return 1

    if not summaries:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    PLAYBOOKS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(summaries)} Playbook(s) {mode}...\n")

    for s in summaries:
        dn = s.get("displayName", "?")
        try:
            full = get_playbook(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full)
        stats["pulled"] += 1

        slug = slugify(dn)
        out_path = PLAYBOOKS_DIR / f"{slug}.yaml"
        text = dump_yaml(local)
        n_steps = len((local.get("instruction") or {}).get("steps", []) or [])
        n_tools = len(local.get("referencedTools", []) or [])

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(PLAYBOOKS_DIR.parent.parent)}  ({len(text)} bytes, steps={n_steps}, refTools={n_tools})")
        else:
            out_path.write_text(text)
            print(f"  ✓ {dn} -> {out_path.relative_to(PLAYBOOKS_DIR.parent.parent)}  (steps={n_steps}, refTools={n_tools})")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
