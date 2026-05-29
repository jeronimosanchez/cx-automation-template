#!/usr/bin/env python3
"""
act/pull_flows.py — Exporta Flows de CX -> YAMLs locales.

Espejo READ-ONLY de push_flows.py (Sprint 5, PR7). Solo GET; nunca
POST/PATCH/DELETE. Escribe un YAML por Flow en
definitions/flows/<slug>.yaml.

Uso:
  python act/pull_flows.py --dry-run
  python act/pull_flows.py
  python act/pull_flows.py --only "Default Start Flow"
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

from push_flows import (  # noqa: E402
    FLOWS_DIR,
    build_headers,
    get_flow,
    get_token,
    list_flows,
    load_agent_config,
)


PULL_STRIP_FIELDS = ("name", "createTime", "updateTime")

_CANONICAL_ORDER = (
    "displayName",
    "description",
    "transitionRoutes",
    "eventHandlers",
    "transitionRouteGroups",
    "nluSettings",
    "knowledgeConnectorSettings",
    "advancedSettings",
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


def dump_yaml(body: dict) -> str:
    return yaml.safe_dump(
        body,
        sort_keys=False,
        indent=2,
        allow_unicode=True,
        default_flow_style=False,
    )


def main():
    ap = argparse.ArgumentParser(
        description="Exporta Flows de CX -> definitions/flows/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Flow a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Flows remotos (paginado)...")
    summaries = list_flows(cfg, headers)
    print(f"   ✓ {len(summaries)} Flow(s) remotos detectados")

    if args.only:
        summaries = [s for s in summaries if s.get("displayName") == args.only]
        if not summaries:
            print(f"  ⚠ --only '{args.only}' no machea ningun Flow remoto.")
            return 1

    if not summaries:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(summaries)} Flow(s) {mode}...\n")

    for s in summaries:
        dn = s.get("displayName", "?")
        try:
            full = get_flow(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full)
        stats["pulled"] += 1

        slug = slugify(dn)
        out_path = FLOWS_DIR / f"{slug}.yaml"
        text = dump_yaml(local)

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(FLOWS_DIR.parent.parent)}  ({len(text)} bytes)")
        else:
            out_path.write_text(text)
            print(f"  ✓ {dn} -> {out_path.relative_to(FLOWS_DIR.parent.parent)}")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
