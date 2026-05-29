#!/usr/bin/env python3
"""
act/pull_pages.py — Exporta Pages de CX -> YAMLs locales.

Espejo READ-ONLY de push_pages.py (Sprint 5, PR8). Solo GET; nunca
POST/PATCH/DELETE.

A diferencia de los otros pull scripts, Pages son sub-recursos de Flows:
el script lista TODOS los flows, luego lista las pages de cada flow, y
escribe cada page como definitions/pages/<slug>.yaml inyectando el campo
local-only `parent_flow_displayName` (que push_pages.py consume para
resolver el flow padre).

Slug strategy: `<flow_slug>__<page_slug>` para evitar colisiones cuando
dos flows tienen pages con el mismo displayName.

Uso:
  python act/pull_pages.py --dry-run
  python act/pull_pages.py
  python act/pull_pages.py --only "Welcome Page"
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

from push_pages import (  # noqa: E402
    PAGES_DIR,
    build_headers,
    get_page,
    get_token,
    list_flows,
    list_pages,
    load_agent_config,
)


PULL_STRIP_FIELDS = ("name", "createTime", "updateTime")

# parent_flow_displayName se inyecta primero (es el contrato del push);
# despues el resto en orden canonico.
_CANONICAL_ORDER = (
    "parent_flow_displayName",
    "displayName",
    "entryFulfillment",
    "form",
    "transitionRouteGroups",
    "transitionRoutes",
    "eventHandlers",
    "advancedSettings",
)


def slugify(display_name: str) -> str:
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict, parent_flow_display_name: str) -> dict:
    """Strippea read-only, inyecta parent_flow_displayName y reordena."""
    stripped = {k: v for k, v in remote.items() if k not in PULL_STRIP_FIELDS}
    stripped["parent_flow_displayName"] = parent_flow_display_name
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
        description="Exporta Pages de CX (anidadas bajo Flow) -> definitions/pages/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName de la Page a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Flows remotos (para iterar sus Pages)...")
    flows = list_flows(cfg, headers)
    print(f"   ✓ {len(flows)} Flow(s) remotos detectados")

    # Recolectar todas las pages junto con su flow padre.
    all_pages: list[tuple[str, str, dict]] = []  # (flow_display_name, flow_name, page_summary)
    for fl in flows:
        fname = fl["name"]
        fdn = fl.get("displayName", "?")
        try:
            pages = list_pages(cfg, headers, fname)
        except RuntimeError as e:
            print(f"  ⚠ {fdn}: {e}")
            continue
        for p in pages:
            all_pages.append((fdn, fname, p))
        print(f"   • {fdn}: {len(pages)} page(s)")

    if args.only:
        all_pages = [t for t in all_pages if t[2].get("displayName") == args.only]
        if not all_pages:
            print(f"  ⚠ --only '{args.only}' no machea ninguna Page remota.")
            return 1

    if not all_pages:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(all_pages)} Page(s) {mode}...\n")

    for flow_dn, _flow_name, summary in all_pages:
        dn = summary.get("displayName", "?")
        try:
            full = get_page(cfg, headers, summary["name"])
        except RuntimeError as e:
            print(f"  ❌ {flow_dn}/{dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full, parent_flow_display_name=flow_dn)
        stats["pulled"] += 1

        # Slug evita colisiones cross-flow: <flow_slug>__<page_slug>
        slug = f"{slugify(flow_dn)}__{slugify(dn)}"
        out_path = PAGES_DIR / f"{slug}.yaml"
        text = dump_yaml(local)

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(PAGES_DIR.parent.parent)}  ({len(text)} bytes, flow={flow_dn})")
        else:
            out_path.write_text(text)
            print(f"  ✓ {flow_dn}/{dn} -> {out_path.relative_to(PAGES_DIR.parent.parent)}")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
