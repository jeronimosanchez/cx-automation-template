#!/usr/bin/env python3
"""
act/pull_versions.py — Exporta Versions de CX como manifest-only.

Espejo READ-ONLY de push_versions.py (Sprint 5, PR11). Solo GET; nunca
POST/PATCH/DELETE.

DIFERENCIA CLAVE vs los otros pull scripts: Versions son INMUTABLES
en CX. No hay PATCH. POST crea siempre un snapshot nuevo. Por eso este
pull NO sirve como fuente para un round-trip via push: si alguien
quisiera "re-aplicar" un YAML versionado, push crearia una version
distinta con id nuevo, no recuperaria el snapshot original.

Decision de diseño (Fase 0 Sprint 5): los YAMLs se escriben en
sub-carpetas `definitions/versions/<flow_slug>/<version_displayName>.yaml`.
`push_versions.discover_version_files()` solo mira el nivel superior
(`VERSIONS_DIR.glob("*.yaml")`, NO recursivo), asi que estos manifests
NO se le filtran a push como YAMLs ejecutables. Es exportacion solo-
lectura, para auditoria/history visibility.

Campos persistidos (incluye read-only informativos):
  - flow_displayName  (local-only — identifica el flow padre)
  - id                (numerico, asignado por CX — NO UUID)
  - displayName       (etiqueta humana, ej. "ci-8")
  - description       (suele contener SHA del commit, via deploy.yml)
  - state             (SUCCEEDED / FAILED / RUNNING — informativo)
  - createTime        (timestamp — informativo)
  - nluSettings       (snapshot del NLU del flow en el momento — informativo)

Uso:
  python act/pull_versions.py --dry-run
  python act/pull_versions.py
  python act/pull_versions.py --only ci-8
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

from push_versions import (  # noqa: E402
    VERSIONS_DIR,
    build_headers,
    get_token,
    list_flows,
    list_versions,
    load_agent_config,
)


# Strip 'name' (lo extraemos como 'id'). Los demas campos read-only
# (state, createTime, nluSettings) los preservamos como informativos.
PULL_STRIP_FIELDS = ("name",)

# Orden canonico para el manifest.
_CANONICAL_ORDER = (
    "flow_displayName",
    "id",
    "displayName",
    "description",
    "state",
    "createTime",
    "nluSettings",
)


def slugify(display_name: str) -> str:
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_.-")
    return s or "unnamed"


def cx_to_local(remote: dict, parent_flow_display_name: str) -> dict:
    """Transforma respuesta CX a manifest local.

    - Extrae UUID/numeric-id del `name` como campo `id`.
    - Inyecta `flow_displayName` (local-only — identifica el flow padre).
    - Preserva read-only informativos (state, createTime, nluSettings).
    - Reordena segun _CANONICAL_ORDER; claves desconocidas al final.
    """
    version_id = ""
    name = remote.get("name", "")
    if isinstance(name, str) and name:
        version_id = name.rsplit("/", 1)[-1]

    stripped = {k: v for k, v in remote.items() if k not in PULL_STRIP_FIELDS}
    stripped["flow_displayName"] = parent_flow_display_name
    if version_id:
        stripped["id"] = version_id

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
        description="Exporta Versions de CX como manifest -> definitions/versions/<flow>/<displayName>.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName de la Version a procesar (ej. ci-8)")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Flows remotos (para iterar sus Versions)...")
    flows = list_flows(cfg, headers)
    print(f"   ✓ {len(flows)} Flow(s) remotos detectados")

    all_versions: list[tuple[str, str, dict]] = []  # (flow_dn, flow_name, version)
    for fl in flows:
        fname = fl["name"]
        fdn = fl.get("displayName", "?")
        try:
            vs = list_versions(cfg, headers, fname)
        except RuntimeError as e:
            print(f"  ⚠ {fdn}: {e}")
            continue
        for v in vs:
            all_versions.append((fdn, fname, v))
        print(f"   • {fdn}: {len(vs)} version(s)")

    if args.only:
        all_versions = [t for t in all_versions if t[2].get("displayName") == args.only]
        if not all_versions:
            print(f"  ⚠ --only '{args.only}' no machea ninguna Version remota.")
            return 1

    if not all_versions:
        print(
            f"\n{'='*55}\n"
            f"📊 pulled=0  written=0  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"pulled": 0, "written": 0, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(all_versions)} Version(s) {mode}...\n")

    for flow_dn, _flow_name, version in all_versions:
        dn = version.get("displayName", "?")
        local = cx_to_local(version, parent_flow_display_name=flow_dn)
        stats["pulled"] += 1

        flow_subdir = VERSIONS_DIR / slugify(flow_dn)
        out_path = flow_subdir / f"{slugify(dn)}.yaml"
        text = dump_yaml(local)
        state = local.get("state", "?")

        if args.dry_run:
            print(f"  [DRY] would write {out_path.relative_to(VERSIONS_DIR.parent.parent)}  ({len(text)} bytes, state={state})")
        else:
            flow_subdir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text)
            print(f"  ✓ {flow_dn}/{dn} -> {out_path.relative_to(VERSIONS_DIR.parent.parent)}  (state={state})")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 pulled={stats['pulled']}  written={stats['written']}  skipped={stats['skipped']}\n"
        f"{'='*55}\n"
        "ℹ Versions son inmutables — no aplica round-trip via push."
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
