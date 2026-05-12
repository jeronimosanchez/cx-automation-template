#!/usr/bin/env python3
"""
src/pull_intents.py — Exporta Intents de CX -> YAMLs locales.

Espejo READ-ONLY de push_intents.py (Sprint 5, PR3). Solo GET; nunca
POST/PATCH/DELETE. Escribe un YAML por Intent en
definitions/intents/<slug>.yaml, con la forma exacta que espera el push.

Decisiones tecnicas no negociables (heredadas):
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project.
  - Read-only del lado pull: name, createTime, updateTime.

Uso:
  python src/pull_intents.py --dry-run   # lista que escribiria, sin tocar FS
  python src/pull_intents.py             # escribe los YAMLs
  python src/pull_intents.py --only "Default Welcome Intent"
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

from push_intents import (  # noqa: E402
    INTENTS_DIR,
    build_headers,
    get_intent,
    get_token,
    list_intents,
    load_agent_config,
)


PULL_STRIP_FIELDS = ("name", "createTime", "updateTime")

# Orden canonico de claves. Claves desconocidas al final (forward-compat).
_CANONICAL_ORDER = (
    "displayName",
    "priority",
    "isFallback",
    "trainingPhrases",
    "parameters",
    "labels",
    "description",
)


def slugify(display_name: str) -> str:
    """displayName -> nombre de fichero seguro (lowercase, underscores)."""
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict) -> dict:
    """Strippea read-only y reordena segun _CANONICAL_ORDER."""
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
        description="Exporta Intents de CX -> definitions/intents/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Intent a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Intents remotos (paginado)...")
    summaries = list_intents(cfg, headers)
    print(f"   ✓ {len(summaries)} Intent(s) remotos detectados")

    if args.only:
        summaries = [s for s in summaries if s.get("displayName") == args.only]
        if not summaries:
            print(f"  ⚠ --only '{args.only}' no machea ningun Intent remoto.")
            return 1

    if not summaries:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    INTENTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(summaries)} Intent(s) {mode}...\n")

    for s in summaries:
        dn = s.get("displayName", "?")
        try:
            full = get_intent(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full)
        stats["pulled"] += 1

        slug = slugify(dn)
        out_path = INTENTS_DIR / f"{slug}.yaml"
        text = dump_yaml(local)
        n_phrases = len(local.get("trainingPhrases", []) or [])

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(INTENTS_DIR.parent.parent)}  ({len(text)} bytes, trainingPhrases={n_phrases})")
        else:
            out_path.write_text(text)
            print(f"  ✓ {dn} -> {out_path.relative_to(INTENTS_DIR.parent.parent)}  (trainingPhrases={n_phrases})")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
