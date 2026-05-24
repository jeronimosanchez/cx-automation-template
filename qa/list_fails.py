#!/usr/bin/env python3
"""
qa/list_fails.py — Lista los FAILs de un run y su estado de análisis manual.

Útil para saber qué TCs necesitan análisis. Usado por la skill /qa-tc-analyzer
en modo batch.

Uso:
    python qa/list_fails.py                     # último run de gh-pages
    python qa/list_fails.py --ts 20260518_192907 # run específico
    python qa/list_fails.py --logs-dir PATH      # carpeta local
    python qa/list_fails.py --only-pending       # solo FAILs sin .md
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

GH_PAGES_BASE = "https://jeronimosanchez.github.io/cx-automation-template/qa"
TC_ANALYSIS_DIR = Path(__file__).parent / "tc_analysis"


def find_latest_local_logs():
    petal_qa = Path.home() / "petal-qa"
    if not petal_qa.exists():
        return None
    log_dirs = sorted(
        [d for d in petal_qa.glob("qa_*_logs") if d.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return log_dirs[0] if log_dirs else None


def list_tc_ids():
    sys.path.insert(0, str(Path(__file__).parent))
    from test_QA_Playbooks_v23 import TESTS
    return [t["id"] for t in TESTS]


def load_log_local(logs_dir, tc_id):
    p = logs_dir / f"{tc_id}.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))
    return None


def load_log_ghpages(ts, tc_id):
    url = f"{GH_PAGES_BASE}/{ts}/qa_latest_logs/{tc_id}.json"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return None


def has_analysis(tc_id):
    md = TC_ANALYSIS_DIR / f"{tc_id}.md"
    return md.exists() and md.stat().st_size > 100  # un MD muy corto no cuenta


def get_latest_ghpages_ts():
    try:
        with urllib.request.urlopen(f"{GH_PAGES_BASE}/", timeout=5) as r:
            content = r.read().decode("utf-8")
        import re
        timestamps = re.findall(r"20\d{6}_\d{6}", content)
        if timestamps:
            return sorted(set(timestamps), reverse=True)[0]
    except Exception as e:
        print(f"  [WARN] No pude leer índice de gh-pages: {e}", file=sys.stderr)
    return None


def main():
    parser = argparse.ArgumentParser(description="Lista FAILs y su estado de análisis")
    parser.add_argument("--ts", help="Timestamp del run en gh-pages")
    parser.add_argument("--logs-dir", help="Carpeta local de JSONs")
    parser.add_argument("--only-pending", action="store_true", help="Solo FAILs sin .md")
    parser.add_argument("--format", choices=["table", "ids"], default="table", help="Output format")
    args = parser.parse_args()

    if args.logs_dir:
        logs_dir = Path(args.logs_dir)
        if not logs_dir.exists():
            print(f"ERROR: no existe {logs_dir}", file=sys.stderr)
            sys.exit(1)
        source = f"local: {logs_dir}"
        loader = lambda tc_id: load_log_local(logs_dir, tc_id)
    elif args.ts:
        source = f"gh-pages: {args.ts}"
        loader = lambda tc_id: load_log_ghpages(args.ts, tc_id)
    else:
        # Intentar local primero, luego gh-pages
        logs_dir = find_latest_local_logs()
        if logs_dir:
            source = f"local (más reciente): {logs_dir}"
            loader = lambda tc_id: load_log_local(logs_dir, tc_id)
        else:
            ts = get_latest_ghpages_ts()
            if not ts:
                print("ERROR: ni logs locales ni gh-pages accesibles", file=sys.stderr)
                sys.exit(1)
            source = f"gh-pages (último): {ts}"
            loader = lambda tc_id: load_log_ghpages(ts, tc_id)

    print(f"Fuente: {source}\n")

    fails = []
    inestables = []
    for tc_id in list_tc_ids():
        log = loader(tc_id)
        if not log:
            continue
        status = log.get("status", "?")
        if status == "FAIL":
            fails.append({
                "tc_id": tc_id,
                "tc_name": log.get("tc_name", "")[:60],
                "group": log.get("group", ""),
                "has_md": has_analysis(tc_id),
                "n_turns": len(log["runs"][0]["turns"]) if log.get("runs") else 0,
            })
        elif status == "INESTABLE":
            inestables.append({
                "tc_id": tc_id,
                "tc_name": log.get("tc_name", "")[:60],
                "has_md": has_analysis(tc_id),
            })

    # Si solo queremos los pendientes
    if args.only_pending:
        fails = [f for f in fails if not f["has_md"]]

    if args.format == "ids":
        # Imprime solo los IDs separados por espacio (útil para scripting)
        print(" ".join(f["tc_id"] for f in fails))
        return

    # Formato tabla
    if not fails and not inestables:
        print("✅ Ningún FAIL ni INESTABLE en este run.")
        return

    if fails:
        print(f"❌ {len(fails)} FAIL{'s' if len(fails)!=1 else ''}:\n")
        print(f"  {'TC ID':<25} {'Grupo':<15} {'Turnos':<8} {'.md análisis':<20} Nombre")
        print(f"  {'-'*25} {'-'*15} {'-'*8} {'-'*20} {'-'*40}")
        for f in fails:
            md_status = "✅ existe" if f["has_md"] else "❌ PENDIENTE"
            print(f"  {f['tc_id']:<25} {f['group']:<15} {f['n_turns']:<8} {md_status:<20} {f['tc_name']}")
        print()

    if inestables:
        print(f"⚠️  {len(inestables)} INESTABLE{'s' if len(inestables)!=1 else ''}:")
        for i in inestables:
            md_status = "✅ existe" if i["has_md"] else "❌ pendiente"
            print(f"  {i['tc_id']} - {md_status} - {i['tc_name']}")
        print()

    pending = [f for f in fails if not f["has_md"]]
    if pending:
        print(f"📋 {len(pending)} FAIL{'s' if len(pending)!=1 else ''} sin análisis manual:")
        print(f"   {' '.join(f['tc_id'] for f in pending)}")
        print()


if __name__ == "__main__":
    main()
