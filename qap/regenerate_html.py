#!/usr/bin/env python3
"""
qap/regenerate_html.py — Regenera el HTML del QA SIN llamar a CX.

Lee los JSONs de un run previo (local o de gh-pages) + los MDs de qa/tc_analysis/
y genera un HTML actualizado usando generate_html() del runner principal.

Útil para:
- Iterar análisis sin gastar API calls de CX (~0€)
- Aplicar cambios a MDs y ver el resultado en segundos
- Workflow Claude: edit MD → regenerate_html → ver dashboard

Uso:
    # Modo 1: usar logs locales (carpeta más reciente en ~/petal-qa/)
    python qap/regenerate_html.py

    # Modo 2: usar logs de gh-pages (run específico)
    python qap/regenerate_html.py --ts 20260518_192907

    # Modo 3: usar carpeta arbitraria
    python qap/regenerate_html.py --logs-dir /path/to/logs

Salida: HTML regenerado en /tmp/qa_regen_{TS}.html
"""
import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Importar generate_html del runner principal
sys.path.insert(0, str(Path(__file__).parent))
from test_qa_playbooks import generate_html


GH_PAGES_BASE = "https://jeronimosanchez.github.io/cx-automation-template/qa"


def find_latest_local_logs():
    """Busca la carpeta de logs más reciente en ~/petal-qa/."""
    petal_qa = Path.home() / "petal-qa"
    if not petal_qa.exists():
        return None
    log_dirs = sorted(
        [d for d in petal_qa.glob("qa_*_logs") if d.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return log_dirs[0] if log_dirs else None


def list_ghpages_tcs(ts):
    """Lista los TCs disponibles para un timestamp dado en gh-pages."""
    # Intentamos descargar uno conocido para validar
    url = f"{GH_PAGES_BASE}/{ts}/qa_latest_logs/"
    # GitHub Pages no permite listing → usamos lista hardcodeada del TESTS dict
    from test_qa_playbooks import TESTS
    return [t["id"] for t in TESTS]


def fetch_log_from_ghpages(ts, tc_id):
    """Descarga un JSON de log desde gh-pages."""
    url = f"{GH_PAGES_BASE}/{ts}/qa_latest_logs/{tc_id}.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            if r.status == 200:
                return json.loads(r.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  [WARN] No se pudo leer {tc_id}: {e}", file=sys.stderr)
    return None


def load_results_from_local(logs_dir):
    """Carga results desde una carpeta local de JSONs."""
    results = []
    for json_file in sorted(logs_dir.glob("*.json")):
        with open(json_file, encoding="utf-8") as f:
            log = json.load(f)
        results.append(log_to_result(log))
    return results


def load_results_from_ghpages(ts):
    """Carga results bajando JSONs desde gh-pages para un TS dado."""
    results = []
    tc_ids = list_ghpages_tcs(ts)
    print(f"  Descargando {len(tc_ids)} JSONs desde gh-pages...")
    for tc_id in tc_ids:
        log = fetch_log_from_ghpages(ts, tc_id)
        if log:
            results.append(log_to_result(log))
    return results


def log_to_result(log):
    """Convierte la estructura JSON de log a la estructura result de generate_html."""
    return {
        "id": log["tc_id"],
        "name": log["tc_name"],
        "group": log["group"],
        "type": log["type"],
        "status": log["status"],
        "pass_count": log["pass_count"],
        "total_runs": log["total_runs"],
        "runs": [
            {"pass": run["pass"], "turns": run["turns"]}
            for run in log["runs"]
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Regenera HTML del QA sin llamar a CX")
    parser.add_argument("--ts", help="Timestamp del run en gh-pages (ej: 20260518_192907)")
    parser.add_argument("--logs-dir", help="Carpeta local de JSONs")
    parser.add_argument("--out", default=None, help="Ruta de salida (default: /tmp/qa_regen_{TS}.html)")
    args = parser.parse_args()

    if args.logs_dir:
        logs_dir = Path(args.logs_dir)
        if not logs_dir.exists():
            print(f"ERROR: no existe {logs_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"Cargando logs desde {logs_dir}")
        results = load_results_from_local(logs_dir)
        # Detectar timestamp del nombre de la carpeta
        name = logs_dir.name  # ej: qa_20260518_1929_logs
        ts = name.replace("qa_", "").replace("_logs", "") if name.startswith("qa_") else "regen"
        logs_dir_name = logs_dir.name
    elif args.ts:
        ts = args.ts
        print(f"Descargando logs de gh-pages: {ts}")
        results = load_results_from_ghpages(ts)
        logs_dir_name = f"qa_latest_logs"  # nombre del subfolder en gh-pages
    else:
        # Modo default: logs locales más recientes
        logs_dir = find_latest_local_logs()
        if not logs_dir:
            print("ERROR: no se encontraron logs locales en ~/petal-qa/. Usa --ts o --logs-dir.", file=sys.stderr)
            sys.exit(1)
        print(f"Cargando logs locales más recientes: {logs_dir}")
        results = load_results_from_local(logs_dir)
        name = logs_dir.name
        ts = name.replace("qa_", "").replace("_logs", "") if name.startswith("qa_") else "regen"
        logs_dir_name = logs_dir.name

    if not results:
        print("ERROR: no se cargaron resultados", file=sys.stderr)
        sys.exit(1)

    # Ordenar PASS arriba, FAIL abajo
    order = {"PASS": 0, "INESTABLE": 1, "FAIL": 2, "QUOTA_ERROR": 3}
    results.sort(key=lambda r: order.get(r["status"], 99))

    # Stats
    total = len(results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_inst = sum(1 for r in results if r["status"] == "INESTABLE")
    print(f"  Cargados: {total} TCs ({n_pass} PASS, {n_inst} INESTABLE, {n_fail} FAIL)")

    # Formatear ts para display
    ts_display = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}" if len(ts) >= 13 and "_" in ts else ts

    # Generar HTML
    # Pasamos ts compacto original como ts_compact_override para que generate_html
    # encuentre los MDs en qa/tc_analysis/{ts_compact}/ con precisión de segundos.
    # Antes pasábamos ts_display que perdía los segundos al re-comprimir
    # ("2026-05-27 22:47" → "20260527_2247" en vez del original "20260527_224705").
    print("  Generando HTML...")
    html = generate_html(
        results, ts_display, "regen.txt",
        logs_dir_name=logs_dir_name,
        ts_compact_override=ts,
    )

    # Guardar
    out_path = args.out if args.out else f"/tmp/qa_regen_{ts}.html"
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"OK: {out_path} ({len(html)} bytes)")
    print(f"\nVer en navegador: file://{out_path}")
    return out_path


if __name__ == "__main__":
    main()
