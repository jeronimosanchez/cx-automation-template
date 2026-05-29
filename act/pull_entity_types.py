#!/usr/bin/env python3
"""
act/pull_entity_types.py — Exporta Entity Types de CX -> YAMLs locales.

Espejo READ-ONLY de push_entity_types.py (Sprint 5, PR2). Solo GET; nunca
POST/PATCH/DELETE. Escribe un YAML por Entity Type en
definitions/entity_types/<slug>.yaml, con la forma exacta que espera el
push (displayName, kind, entities, ...).

Decisiones tecnicas no negociables (heredadas):
  - Auth: `gcloud auth print-access-token`.
  - Header obligatorio x-goog-user-project.
  - Read-only del lado pull: name, createTime, updateTime.

Uso:
  python act/pull_entity_types.py --dry-run   # lista que escribiria, sin tocar FS
  python act/pull_entity_types.py             # escribe los YAMLs
  python act/pull_entity_types.py --only Color
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

from push_entity_types import (  # noqa: E402
    ENTITY_TYPES_DIR,
    build_headers,
    get_entity_type,
    get_token,
    list_entity_types,
    load_agent_config,
)


# Read-only del lado pull. Superset de ENTITY_TYPE_IGNORE_FIELDS del push
# (el push usa el mismo set para diff; aqui lo usamos para no escribir).
PULL_STRIP_FIELDS = ("name", "createTime", "updateTime")

# Orden canonico de claves en el YAML de salida. Claves desconocidas al final.
_CANONICAL_ORDER = ("displayName", "kind", "autoExpansionMode", "entities", "excludedPhrases", "enableFuzzyExtraction", "redact")


def slugify(display_name: str) -> str:
    """Convierte un displayName en un nombre de fichero seguro.

    Reglas: lowercase, espacios y separadores -> underscore, elimina chars
    no [a-z0-9._-]. No protege contra colisiones — si dos displayNames
    diferentes producen el mismo slug, el segundo sobrescribe el primero.
    """
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict) -> dict:
    """Strippea PULL_STRIP_FIELDS y reordena segun _CANONICAL_ORDER.

    Preserva claves desconocidas para forward-compat con cambios de CX.
    """
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
        description="Exporta Entity Types de CX -> definitions/entity_types/<slug>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Entity Type a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Entity Types remotos (paginado)...")
    summaries = list_entity_types(cfg, headers)
    print(f"   ✓ {len(summaries)} Entity Type(s) remotos detectados")

    if args.only:
        summaries = [s for s in summaries if s.get("displayName") == args.only]
        if not summaries:
            print(f"  ⚠ --only '{args.only}' no machea ningun Entity Type remoto.")
            return 1

    if not summaries:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    ENTITY_TYPES_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(summaries)} Entity Type(s) {mode}...\n")

    for s in summaries:
        dn = s.get("displayName", "?")
        try:
            full = get_entity_type(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue
        local = cx_to_local(full)
        stats["pulled"] += 1

        slug = slugify(dn)
        out_path = ENTITY_TYPES_DIR / f"{slug}.yaml"
        text = dump_yaml(local)

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(ENTITY_TYPES_DIR.parent.parent)}  ({len(text)} bytes, kind={local.get('kind')})")
        else:
            out_path.write_text(text)
            print(f"  ✓ {dn} -> {out_path.relative_to(ENTITY_TYPES_DIR.parent.parent)}")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
