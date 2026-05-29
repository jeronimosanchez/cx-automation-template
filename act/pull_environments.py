#!/usr/bin/env python3
"""
act/pull_environments.py — Exporta Environments de CX -> YAMLs locales.

Espejo READ-ONLY de push_environments.py (Sprint 5, PR12). Solo GET;
nunca POST/PATCH/DELETE.

Uso:
  python act/pull_environments.py --dry-run
  python act/pull_environments.py
  python act/pull_environments.py --only Production
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

from push_environments import (  # noqa: E402
    ENVIRONMENTS_DIR,
    build_headers,
    get_environment,
    get_token,
    list_environments,
    load_agent_config,
)


# Mismos read-only que ENVIRONMENT_IGNORE_FIELDS del push (incluye lastUpdateTime).
PULL_STRIP_FIELDS = ("name", "createTime", "updateTime", "lastUpdateTime")

_CANONICAL_ORDER = (
    "displayName",
    "description",
    "versionConfigs",
    "testCasesConfig",
    "webhookConfig",
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
        description="Exporta Environments de CX -> definitions/environments/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Environment a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Environments remotos (paginado)...")
    summaries = list_environments(cfg, headers)
    print(f"   ✓ {len(summaries)} Environment(s) remotos detectados")

    if args.only:
        summaries = [s for s in summaries if s.get("displayName") == args.only]
        if not summaries:
            print(f"  ⚠ --only '{args.only}' no machea ningun Environment remoto.")
            return 1

    if not summaries:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    ENVIRONMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(summaries)} Environment(s) {mode}...\n")

    for s in summaries:
        dn = s.get("displayName", "?")
        try:
            full = get_environment(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full)
        stats["pulled"] += 1

        slug = slugify(dn)
        out_path = ENVIRONMENTS_DIR / f"{slug}.yaml"
        text = dump_yaml(local)

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(ENVIRONMENTS_DIR.parent.parent)}  ({len(text)} bytes)")
        else:
            out_path.write_text(text)
            print(f"  ✓ {dn} -> {out_path.relative_to(ENVIRONMENTS_DIR.parent.parent)}")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
