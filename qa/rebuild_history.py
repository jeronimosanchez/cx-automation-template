#!/usr/bin/env python3
"""qa/rebuild_history.py — Genera qa/history.json para la vista Histórico del dashboard.

Reemplaza las ~25 llamadas a GitHub API (1 por directorio + 1 por meta.json)
que hacía openHistorial() en el navegador. Resultado: 1 fetch al JSON estático,
sin rate limit ni latencia.

Modos:
  Solo backfill (lista todos los dirs de gh-pages, no añade nuevos):
      python qa/rebuild_history.py --out /tmp/history.json

  En CI (añade un run local no publicado todavía):
      python qa/rebuild_history.py \\
          --include-local "${STAMP}" "gh_publish/${STAMP}/qa_latest.meta.json" \\
          --out "gh_publish/history.json"
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API_URL = "https://api.github.com/repos/jeronimosanchez/cx-automation-template/contents/qa?ref=gh-pages"
GH_PAGES_URL = "https://jeronimosanchez.github.io/cx-automation-template/qa"


def fetch_json(url, token=None, timeout=30):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent", "rebuild_history.py")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"WARN: fetch failed {url}: {e}", file=sys.stderr)
        return None


def list_dirs(token=None):
    """Devuelve lista de directorios YYYYMMDD_HHMMSS en /qa/ de gh-pages."""
    data = fetch_json(API_URL, token=token)
    if not isinstance(data, list):
        return []
    dirs = []
    for f in data:
        if f.get("type") != "dir":
            continue
        name = f.get("name", "")
        if len(name) == 15 and name[:8].isdigit() and name[8] == "_" and name[9:].isdigit():
            dirs.append(name)
    return dirs


def fetch_meta(dir_name):
    """Lee qa_latest.meta.json del directorio en gh-pages (CDN público, sin rate limit)."""
    return fetch_json(f"{GH_PAGES_URL}/{dir_name}/qa_latest.meta.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-local",
        nargs=2,
        metavar=("STAMP", "META_PATH"),
        help="Añade un meta.json local todavía no publicado en gh-pages (uso en CI).",
    )
    ap.add_argument("--out", required=True, help="Path de salida del history.json.")
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    new_dir = args.include_local[0] if args.include_local else None

    dirs = list_dirs(token=token)
    print(f"[rebuild_history] Encontrados {len(dirs)} directorios en gh-pages/qa/")

    entries = []
    for d in dirs:
        if d == new_dir:
            continue  # se añade abajo desde la copia local
        meta = fetch_meta(d)
        if meta:
            meta["dir"] = d
            entries.append(meta)

    if args.include_local:
        stamp, meta_path = args.include_local
        with open(meta_path) as f:
            meta = json.load(f)
        meta["dir"] = stamp
        entries.append(meta)
        print(f"[rebuild_history] Añadida entrada local {stamp}")

    entries.sort(key=lambda x: x.get("ts_file") or x.get("dir") or "", reverse=True)

    with open(args.out, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)

    print(f"[rebuild_history] Escritas {len(entries)} entradas en {args.out}")


if __name__ == "__main__":
    main()
