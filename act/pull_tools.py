#!/usr/bin/env python3
"""
act/pull_tools.py — Exporta Tools de CX -> YAMLs locales.

Espejo READ-ONLY de push_tools.py (Sprint 5, PR6). Solo GET; nunca
POST/PATCH/DELETE.

Particularidades vs los otros pull scripts:
  - Filtra BUILTIN_TOOL (decision Fase 0: code-interpreter no se exporta).
    Los builtins NO se eliminan del repo; simplemente no se persisten YAMLs
    locales para ellos. Se logean como "ignored builtin".
  - Formato two-file por tool customized:
      definitions/tools/<slug>.yaml          # metadata (displayName, toolType, ...)
      definitions/tools/<slug>_openapi.yaml  # solo el textSchema OpenAPI 3.0
    El YAML metadata referencia el openapi via `openapi_spec_file: <name>`.
    push_tools.load_tool_yaml inyecta el contenido como texto crudo en
    openApiSpec.textSchema (round-trip-clean).

Uso:
  python act/pull_tools.py --dry-run
  python act/pull_tools.py
  python act/pull_tools.py --only PetalDataTool
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

from push_tools import (  # noqa: E402
    TOOLS_DIR,
    build_headers,
    get_token,
    get_tool,
    list_tools,
    load_agent_config,
)


PULL_STRIP_FIELDS = ("name", "createTime", "updateTime")
BUILTIN_TYPE = "BUILTIN_TOOL"

_CANONICAL_ORDER = (
    "displayName",
    "description",
    "toolType",
    "openapi_spec_file",
)


def slugify(display_name: str) -> str:
    s = display_name.strip().lower()
    s = re.sub(r"[\s/\\]+", "_", s)
    s = re.sub(r"[^a-z0-9._-]", "", s)
    s = s.strip("_.-")
    return s or "unnamed"


def is_builtin(tool: dict) -> bool:
    return tool.get("toolType") == BUILTIN_TYPE


def cx_to_local(remote: dict, openapi_filename: str) -> tuple[dict, str]:
    """Transforma respuesta de CX al formato two-file.

    Devuelve (tool_metadata_dict, openapi_text). El metadata referencia el
    openapi via `openapi_spec_file`. El openapi_text es el contenido crudo
    de openApiSpec.textSchema (string OpenAPI 3.0).

    Si remote no tiene openApiSpec.textSchema (caso raro para CUSTOMIZED,
    posible para BUILTIN aunque ya filtrados antes), openapi_text == "".
    """
    stripped = {k: v for k, v in remote.items() if k not in PULL_STRIP_FIELDS}

    openapi_text = ""
    api_spec = stripped.pop("openApiSpec", None)
    if isinstance(api_spec, dict) and "textSchema" in api_spec:
        openapi_text = api_spec["textSchema"] or ""

    if openapi_text:
        stripped["openapi_spec_file"] = openapi_filename

    ordered: dict = {}
    for k in _CANONICAL_ORDER:
        if k in stripped:
            ordered[k] = stripped.pop(k)
    ordered.update(stripped)
    return ordered, openapi_text


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
        description="Exporta Tools de CX -> definitions/tools/<slug>.yaml + <slug>_openapi.yaml.",
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; lista que escribiria.")
    ap.add_argument("--only", help="displayName del Tool a procesar")
    args = ap.parse_args()

    cfg = load_agent_config()
    print("\U0001f511 Token via `gcloud auth print-access-token`...")
    token = get_token()
    headers = build_headers(cfg, token)

    print("\n\U0001f4dc LIST de Tools remotos (paginado)...")
    summaries = list_tools(cfg, headers)
    print(f"   ✓ {len(summaries)} Tool(s) remotos detectados (custom + builtin)")

    # Filtrar BUILTIN antes de cualquier procesado (decision Fase 0).
    customized = []
    builtin_count = 0
    for s in summaries:
        if is_builtin(s):
            builtin_count += 1
            print(f"   · ignored builtin: {s.get('displayName', '?')}")
            continue
        customized.append(s)

    if args.only:
        customized = [s for s in customized if s.get("displayName") == args.only]
        if not customized:
            print(f"  ⚠ --only '{args.only}' no machea ningun Tool customized remoto.")
            return 1

    if not customized:
        print(
            f"\n{'='*55}\n"
            f"📊 customized=0  written=0  ignored_builtin={builtin_count}  skipped=0\n"
            f"{'='*55}\n"
            "Nada que exportar."
        )
        return 0

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"written": 0, "ignored_builtin": builtin_count, "skipped": 0}
    mode = "(DRY-RUN)" if args.dry_run else ""
    print(f"\n📝 Procesando {len(customized)} Tool(s) customized {mode}...\n")

    for s in customized:
        dn = s.get("displayName", "?")
        try:
            full = get_tool(cfg, headers, s["name"])
        except RuntimeError as e:
            print(f"  ❌ {dn}: {e}")
            stats["skipped"] += 1
            continue

        slug = slugify(dn)
        openapi_filename = f"{slug}_openapi.yaml"
        meta, openapi_text = cx_to_local(full, openapi_filename=openapi_filename)

        meta_path = TOOLS_DIR / f"{slug}.yaml"
        spec_path = TOOLS_DIR / openapi_filename
        meta_text = dump_yaml(meta)

        if args.dry_run:
            print(f"  [DRY] would write {meta_path.relative_to(TOOLS_DIR.parent.parent)}  ({len(meta_text)} bytes)")
            if openapi_text:
                print(f"  [DRY] would write {spec_path.relative_to(TOOLS_DIR.parent.parent)}  ({len(openapi_text)} bytes, OpenAPI textSchema)")
        else:
            meta_path.write_text(meta_text)
            if openapi_text:
                spec_path.write_text(openapi_text)
                print(f"  ✓ {dn} -> {meta_path.name} + {spec_path.name}")
            else:
                print(f"  ✓ {dn} -> {meta_path.name}  (sin openApiSpec)")
            stats["written"] += 1

    print(
        f"\n{'='*55}\n"
        f"📊 written={stats['written']}  ignored_builtin={stats['ignored_builtin']}  skipped={stats['skipped']}\n"
        f"{'='*55}"
    )
    return 0 if stats["skipped"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
