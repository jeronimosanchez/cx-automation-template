#!/usr/bin/env python3
"""
qap/surgical_run.py — Ejecución quirúrgica de TCs y publicación selectiva en gh-pages.

Propósito
---------
Permite lanzar SOLO los TCs que necesitas (no los 51 completos) contra CX, en
paralelo, revisar los resultados en local, y — cuando das el OK — publicarlos en
gh-pages como un run completo nuevo, mergeando con el último run histórico.

El resultado en gh-pages es indistinguible de un run completo (todos los TCs,
stats correctas, histórico intacto) pero solo pagas el coste de API de los TCs
que lanzaste.

Resuelve el "surgical run gap" registrado como épica en QAP: hasta ahora la única
forma de actualizar gh-pages era relanzar los 51 TCs vía CI/CD (~0,30€ + minutos).

Uso
---
    # Paso 1 — correr solo los TCs que necesitas (en paralelo)
    python3 qap/surgical_run.py --test TC-URGENCIA-01,TC-URGENCIA-03 --runs 2 --workers 5

    # → Corre, muestra resultados en terminal, guarda JSONs en local.
    #   NO toca gh-pages. Revisas los resultados con calma.

    # Paso 2 — cuando hayas revisado, publicar (mergea + push a gh-pages)
    python3 qap/surgical_run.py --publish

    # Variantes del publish:
    python3 qap/surgical_run.py --publish --dry-run        # construye todo pero NO hace push
    python3 qap/surgical_run.py --publish --base-ts 20260531_092913  # fija el run base a mergear

Argumentos
----------
    --test     IDs separados por coma (ej: TC-URGENCIA-01,TC-URGENCIA-03). Obligatorio en modo run.
    --runs     Número de runs por TC. Obligatorio en modo run (sin default oculto).
    --workers  TCs ejecutados en paralelo simultáneamente (default 8). Subir si quieres más
               velocidad; bajar si la API de CX devuelve quota errors.
    --publish  Activa el modo publicación: mergea el último run quirúrgico con el último run
               completo de gh-pages y publica como run nuevo.
    --base-ts  (solo con --publish) Timestamp del run base a mergear. Default: el más reciente.
    --dry-run  (solo con --publish) Construye el HTML mergeado y lo deja en /tmp, pero NO
               hace push a gh-pages. Para previsualizar.

Diseño y contrato (LEER si algo falla)
--------------------------------------
Este script NO parsea el HTML de gh-pages. Construye el HTML mergeado regenerándolo
desde cero a partir de los JSON de datos, usando generate_html() — la MISMA función
que usa el runner principal y el CI. Por eso no hay acoplamiento al layout del HTML:
si el formato del HTML cambia, cambia en generate_html() y este script produce el
formato nuevo automáticamente.

El acoplamiento real es al CONTRATO JSON (más estable que el HTML):
  1. URL de logs en gh-pages:  qa/{TS}/qa_latest_logs/{tc_id}.json
  2. Schema de cada log:        campos tc_id, tc_name, group, type, status,
                                pass_count, total_runs, runs[{pass, turns}]
  3. qa/history.json:           lista de runs (lo regenera rebuild_history.py)
  4. Descubrir último TS:       regex 20\\d{6}_\\d{6} en el índice qa/

Antes de publicar, el script ejecuta un PREFLIGHT que valida este contrato. Si algo
no encaja (run base vacío, schema cambiado, etc.) ABORTA y dice exactamente qué se
rompió y qué hay que tocar — en vez de publicar un HTML roto en silencio.

Si el preflight te dice que el schema cambió, el fix es actualizar:
  - REQUIRED_LOG_FIELDS / REQUIRED_RUN_FIELDS (en este archivo), y
  - log_to_result() en qap/regenerate_html.py
para reflejar el nuevo schema de generate_reports() en test_qa_playbooks.py.

Limitación conocida: al regenerar desde JSON, los bloques de análisis manual
(qa/tc_analysis/{ts}/*.md) solo se incrustan si existen localmente para el TS nuevo.
Un run quirúrgico produce un TS nuevo sin esos MDs → HTML limpio sin análisis. Es el
comportamiento esperado (igual que un run completo recién corrido).

Contexto
--------
Parte del sistema QAP de Petal (cx-automation-template). El runner principal es
test_qa_playbooks.py — este script lo complementa SIN modificarlo. Reutiliza:
  - de test_qa_playbooks.py: get_token, run_test, print_result, generate_html,
    generate_txt, TESTS, constantes de versión
  - de regenerate_html.py: fetch_log_from_ghpages, log_to_result, GH_PAGES_BASE
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# --- Imports del runner principal y del regenerador (reutilización, no duplicación) ---
sys.path.insert(0, str(Path(__file__).parent))
from test_qa_playbooks import (  # noqa: E402
    TESTS,
    get_token,
    run_test,
    print_result,
    generate_html,
    generate_txt,
    ORQ_VERSION,
    COMPRA_VERSION,
    CHECKOUT_VERSION,
    REGISTRO_VERSION,
    SCRIPT_VERSION,
)
from regenerate_html import (  # noqa: E402
    fetch_log_from_ghpages,
    log_to_result,
    GH_PAGES_BASE,
)

# ------------------------------------------------------------------------------
# Constantes
# ------------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
PETAL_QA_DIR = Path.home() / "petal-qa"
STATE_FILE = PETAL_QA_DIR / ".surgical_last_run.json"
GH_PAGES_INDEX = f"{GH_PAGES_BASE}/"
WORKTREE_DIR = Path("/tmp/ghp_surgical")

# Contrato JSON que valida el preflight. Si generate_reports() en
# test_qa_playbooks.py cambia el schema de logs, actualizar estas listas.
REQUIRED_LOG_FIELDS = ["tc_id", "tc_name", "group", "type", "status",
                       "pass_count", "total_runs", "runs"]
REQUIRED_RUN_FIELDS = ["pass", "turns"]


def _abort(msg):
    """Imprime un error claro y termina con código 1."""
    print(f"\n❌ ABORTADO: {msg}", file=sys.stderr)
    sys.exit(1)


# ==============================================================================
# PASO 1 — RUN (ejecución quirúrgica en paralelo)
# ==============================================================================

def _build_log_data(r):
    """Replica la estructura de log JSON de generate_reports() (test_qa_playbooks.py
    ~línea 2917) para que los JSONs quirúrgicos sean idénticos a los del runner."""
    return {
        "tc_id": r["id"], "tc_name": r["name"],
        "group": r["group"], "type": r["type"],
        "status": r["status"], "pass_count": r["pass_count"], "total_runs": r["total_runs"],
        "runs": [{
            "run_id": ri + 1, "pass": run["pass"],
            "turns": [{
                "turn": turn["turn"], "user": turn["user"], "agent": turn["agent"],
                "playbook": turn.get("playbook", ""),
                "params": turn["params"], "checks": turn["checks"],
                "trace": turn.get("trace", {}),
            } for turn in run["turns"]],
        } for ri, run in enumerate(r["runs"])],
        "metadata": {
            "orquestador": ORQ_VERSION, "compra": COMPRA_VERSION,
            "checkout": CHECKOUT_VERSION, "registro": REGISTRO_VERSION,
            "script": SCRIPT_VERSION,
        },
    }


def cmd_run(args):
    if not args.test:
        _abort("Falta --test con los IDs a correr (ej: --test TC-URGENCIA-01,TC-URGENCIA-03)")
    if args.runs is None:
        _abort("Falta --runs. Defínelo siempre (ej: --runs 2). No hay default oculto.")

    wanted = [tid.strip() for tid in args.test.split(",") if tid.strip()]
    tests = [t for t in TESTS if t["id"] in wanted]
    found_ids = {t["id"] for t in tests}
    missing = [tid for tid in wanted if tid not in found_ids]
    if missing:
        _abort(f"TCs no encontrados en TESTS: {', '.join(missing)}")
    if not tests:
        _abort("Ningún TC válido para correr.")

    workers = max(1, min(args.workers, 15))
    print(f"QA Quirúrgico — {len(tests)} TCs × {args.runs} runs × {workers} workers paralelos")
    print(f"Orq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}\n")

    token = get_token()

    # Ejecución en paralelo: cada worker corre un TC completo (con sus N runs internos).
    # Seguro porque cada run_single() crea su propio session_id (uuid) — sin estado
    # compartido entre hilos. El token es read-only.
    results = [None] * len(tests)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_to_idx = {ex.submit(run_test, token, test, args.runs): i
                      for i, test in enumerate(tests)}
        for fut in as_completed(fut_to_idx):
            i = fut_to_idx[fut]
            try:
                results[i] = fut.result()
            except Exception as e:  # noqa: BLE001
                _abort(f"Fallo ejecutando {tests[i]['id']}: {e}")
            r = results[i]
            print(f"  {r['id']:18s} {r['status']:10s} ({r['pass_count']}/{r['total_runs']})")

    print()
    for r in results:
        print_result(r)

    # Guardar JSONs en carpeta dedicada + state file para el paso publish.
    ts_file = datetime.now().strftime("%Y%m%d_%H%M%S")
    logs_dir = PETAL_QA_DIR / f"surgical_{ts_file}_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        with open(logs_dir / f'{r["id"]}.json', "w", encoding="utf-8") as f:
            json.dump(_build_log_data(r), f, indent=2, ensure_ascii=False)

    state = {
        "ts_file": ts_file,
        "logs_dir": str(logs_dir),
        "tc_ids": [r["id"] for r in results],
        "runs": args.runs,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    PETAL_QA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_other = len(results) - n_pass - n_fail
    print(f"\n{'='*60}")
    print(f"Run quirúrgico guardado: {logs_dir}")
    print(f"Total: {len(results)} | ✅ {n_pass} | ❌ {n_fail} | otros {n_other}")
    print(f"\nPara publicar en gh-pages:  python3 qap/surgical_run.py --publish")
    print(f"{'='*60}")


# ==============================================================================
# PASO 2 — PUBLISH (merge con run base + push a gh-pages)
# ==============================================================================

def _discover_latest_ts():
    """Descubre el TS más reciente en gh-pages parseando el índice qa/.
    Contrato 4: regex 20\\d{6}_\\d{6}. Si cambia el patrón de nombres, actualizar aquí."""
    try:
        with urllib.request.urlopen(GH_PAGES_INDEX, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        _abort(f"No se pudo leer el índice de gh-pages ({GH_PAGES_INDEX}): {e}")
    stamps = re.findall(r"(20\d{6}_\d{6})", html)
    if not stamps:
        _abort("PREFLIGHT (contrato 4): el índice de gh-pages no contiene ningún TS con "
               "patrón 20\\d{6}_\\d{6}. ¿Cambió el formato de nombres de run? "
               "Revisar _discover_latest_ts().")
    return sorted(set(stamps))[-1]


def _validate_log_schema(log, source):
    """PREFLIGHT contrato 2: valida que un log tenga el schema esperado."""
    missing = [f for f in REQUIRED_LOG_FIELDS if f not in log]
    if missing:
        _abort(f"PREFLIGHT (contrato 2): el JSON de {source} no tiene los campos {missing}. "
               f"Probablemente cambió el schema de logs en test_qa_playbooks.py "
               f"(generate_reports, ~línea 2917). Actualiza REQUIRED_LOG_FIELDS en "
               f"surgical_run.py y log_to_result() en regenerate_html.py.")
    for run in log.get("runs", []):
        rmissing = [f for f in REQUIRED_RUN_FIELDS if f not in run]
        if rmissing:
            _abort(f"PREFLIGHT (contrato 2): un run de {source} no tiene {rmissing}. "
                   f"Schema de runs cambiado. Actualiza REQUIRED_RUN_FIELDS.")


def _fetch_base_meta(base_ts):
    """Descarga el meta.json del run base para heredar runs_per_tc."""
    url = f"{GH_PAGES_BASE}/{base_ts}/qa_latest.meta.json"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def cmd_publish(args):
    # --- 1. Cargar estado del último run quirúrgico ---
    if not STATE_FILE.exists():
        _abort("No hay run quirúrgico previo (falta el state file). Corre primero el paso 1:\n"
               "  python3 qap/surgical_run.py --test TC-XXX --runs N")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    logs_dir = Path(state["logs_dir"])
    if not logs_dir.exists():
        _abort(f"La carpeta de logs del run quirúrgico no existe: {logs_dir}. "
               f"Relanza el paso 1.")

    surgical_ids = set(state["tc_ids"])
    print(f"Run quirúrgico a publicar: {state['ts_file']} — {len(surgical_ids)} TCs "
          f"({', '.join(sorted(surgical_ids))})")

    # --- 2. Cargar resultados quirúrgicos locales ---
    surgical_results = {}
    for tc_id in surgical_ids:
        p = logs_dir / f"{tc_id}.json"
        if not p.exists():
            _abort(f"Falta el JSON quirúrgico de {tc_id} en {logs_dir}.")
        log = json.loads(p.read_text(encoding="utf-8"))
        _validate_log_schema(log, f"quirúrgico {tc_id}")
        surgical_results[tc_id] = log_to_result(log)

    # --- 3. Descubrir run base + PREFLIGHT de descarga ---
    base_ts = args.base_ts or _discover_latest_ts()
    print(f"Run base (gh-pages): {base_ts}")
    print("PREFLIGHT — descargando JSONs del run base y validando contrato...")

    base_results = {}
    n_ok, n_fail = 0, 0
    for test in TESTS:
        log = fetch_log_from_ghpages(base_ts, test["id"])
        if log is None:
            n_fail += 1
            continue
        _validate_log_schema(log, f"base {test['id']}")
        base_results[test["id"]] = log_to_result(log)
        n_ok += 1

    # PREFLIGHT contrato 1: el run base no puede venir vacío.
    if n_ok == 0:
        _abort(f"PREFLIGHT (contrato 1): no se descargó ningún JSON del run base {base_ts}. "
               f"¿Cambió la URL qa/{{TS}}/qa_latest_logs/{{tc_id}}.json? "
               f"Revisar fetch_log_from_ghpages() en regenerate_html.py.")
    # Coherencia: todos los TCs quirúrgicos deben existir en base (si no, son TCs nuevos).
    nuevos = surgical_ids - set(base_results.keys())
    if nuevos:
        print(f"  ⚠️  TCs quirúrgicos no presentes en el run base (se añadirán como nuevos): "
              f"{', '.join(sorted(nuevos))}")
    print(f"  Base: {n_ok} TCs descargados, {n_fail} no disponibles en gh-pages.")

    # --- 4. Merge: base + override quirúrgico, preservando el orden de TESTS ---
    merged = []
    overridden = []
    for test in TESTS:
        tid = test["id"]
        if tid in surgical_results:
            merged.append(surgical_results[tid])
            if tid in base_results:
                overridden.append(tid)
        elif tid in base_results:
            merged.append(base_results[tid])
    # Sanidad: no debemos perder TCs respecto al base.
    if len(merged) < n_ok:
        _abort(f"El merge produciría {len(merged)} TCs pero el base tenía {n_ok}. "
               f"Abortado para no publicar un run incompleto.")
    print(f"  Merge: {len(merged)} TCs totales — {len(overridden)} sobreescritos por el run quirúrgico.")

    # --- 5. Generar artefactos del nuevo run ---
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")  # UTC, igual que el CI
    ts_display = datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_file_meta = datetime.now().strftime("%Y%m%d_%H%M")

    total = len(merged)
    n_pass = sum(1 for r in merged if r["status"] == "PASS")
    n_inst = sum(1 for r in merged if r["status"] == "INESTABLE")
    n_fail_m = sum(1 for r in merged if r["status"] == "FAIL")
    pct_val = int((n_pass / total) * 100) if total else 0

    base_meta = _fetch_base_meta(base_ts)
    runs_per_tc = base_meta.get("runs_per_tc", state["runs"]) if base_meta else state["runs"]

    meta = {
        "timestamp": ts_display, "ts_file": ts_file_meta,
        "total": total, "pass": n_pass, "inst": n_inst, "fail": n_fail_m,
        "pct": pct_val, "runs_per_tc": runs_per_tc,
        "versions": {
            "orquestador": ORQ_VERSION, "compra": COMPRA_VERSION,
            "checkout": CHECKOUT_VERSION, "registro": REGISTRO_VERSION,
            "script": SCRIPT_VERSION,
        },
        "surgical": {
            "base_ts": base_ts, "overridden": overridden, "runs": state["runs"],
        },
    }

    # Construir el run en una carpeta de staging local.
    staging = Path("/tmp") / f"surgical_publish_{stamp}"
    if staging.exists():
        shutil.rmtree(staging)
    run_dir = staging / "qa" / stamp
    logs_out = run_dir / "qa_latest_logs"
    logs_out.mkdir(parents=True, exist_ok=True)

    # JSONs por TC (mismo schema que el runner).
    src_by_id = {}
    for test in TESTS:
        tid = test["id"]
        if tid in surgical_results:
            src_by_id[tid] = logs_dir / f"{tid}.json"
    for r in merged:
        tid = r["id"]
        if tid in src_by_id:
            shutil.copy2(src_by_id[tid], logs_out / f"{tid}.json")
        else:
            # Reconstruir el JSON del base desde el result (ya validado).
            log = fetch_log_from_ghpages(base_ts, tid)
            if log:
                with open(logs_out / f"{tid}.json", "w", encoding="utf-8") as f:
                    json.dump(log, f, indent=2, ensure_ascii=False)

    html = generate_html(merged, ts_display, "qa_latest.txt", logs_dir_name="qa_latest_logs")
    txt = generate_txt(merged, ts_display)
    (run_dir / "qa_latest.html").write_text(html, encoding="utf-8")
    (run_dir / "qa_latest.txt").write_text(txt, encoding="utf-8")
    (run_dir / "qa_latest.meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  Artefactos generados en staging: {run_dir}")
    print(f"  HTML mergeado: {run_dir / 'qa_latest.html'}")
    print(f"  Stats: Total {total} | ✅ {n_pass} | ⚠️ {n_inst} | ❌ {n_fail_m} | {pct_val}%")

    if args.dry_run:
        # Copia de previsualización fuera del staging (que podríamos limpiar).
        preview = Path("/tmp") / f"qa_surgical_preview_{stamp}.html"
        shutil.copy2(run_dir / "qa_latest.html", preview)
        print(f"\n--dry-run: NO se hace push. Previsualización:\n  {preview}")
        return

    # --- 6. Push a gh-pages vía worktree ---
    _publish_to_ghpages(staging, stamp, meta, run_dir)


def _run_git(args_list, cwd=None, check=True, capture=False):
    return subprocess.run(["git", *args_list], cwd=cwd or REPO_ROOT,
                          check=check, capture_output=capture, text=True)


def _publish_to_ghpages(staging, stamp, meta, run_dir):
    print("\nPublicando en gh-pages vía worktree...")

    # Limpiar worktree previo si quedó colgado.
    _run_git(["worktree", "remove", "--force", str(WORKTREE_DIR)], check=False)
    if WORKTREE_DIR.exists():
        shutil.rmtree(WORKTREE_DIR, ignore_errors=True)

    _run_git(["fetch", "origin", "gh-pages"])
    # Worktree detached en origin/gh-pages (no necesitamos rama local).
    _run_git(["worktree", "add", "--force", "--detach", str(WORKTREE_DIR), "origin/gh-pages"])

    try:
        qa_dir = WORKTREE_DIR / "qa"
        dest_run = qa_dir / stamp
        if dest_run.exists():
            shutil.rmtree(dest_run)
        shutil.copytree(run_dir, dest_run)

        # Actualizar index.html (misma lógica que el CI: fila tras <!-- RUNS -->).
        _update_index(qa_dir / "index.html", stamp, meta)

        # Regenerar history.json igual que el CI.
        meta_path = dest_run / "qa_latest.meta.json"
        history_out = qa_dir / "history.json"
        subprocess.run(
            ["python3", str(REPO_ROOT / "qap" / "rebuild_history.py"),
             "--include-local", stamp, str(meta_path),
             "--out", str(history_out)],
            check=True,
        )

        _run_git(["add", "-A"], cwd=WORKTREE_DIR)
        commit_msg = (f"qa(surgical): run {stamp} — "
                      f"{len(meta['surgical']['overridden'])} TCs actualizados sobre base "
                      f"{meta['surgical']['base_ts']}")
        _run_git(["commit", "-m", commit_msg], cwd=WORKTREE_DIR)
        _run_git(["push", "origin", "HEAD:gh-pages"], cwd=WORKTREE_DIR)

        url = f"https://jeronimosanchez.github.io/cx-automation-template/qa/{stamp}/qa_latest.html"
        print(f"\n✅ Publicado. Disponible en ~1 min:\n  {url}")
    finally:
        _run_git(["worktree", "remove", "--force", str(WORKTREE_DIR)], check=False)


def _update_index(index_path, stamp, meta):
    """Inserta una fila para el run nuevo en qa/index.html (orden DESC, arriba).
    Replica la lógica del workflow qa.yml."""
    summary = (f"Total: {meta['total']} | PASS: {meta['pass']} | "
               f"INESTABLE: {meta['inst']} | FAIL: {meta['fail']}")
    new_row = (f'<tr><td>{stamp}</td><td><code>surgical</code></td>'
               f'<td>{summary}</td><td><a href="{stamp}/qa_latest.html">Ver</a></td></tr>')
    if index_path.exists() and index_path.stat().st_size > 0:
        content = index_path.read_text(encoding="utf-8")
        if "<!-- RUNS -->" in content:
            content = content.replace("<!-- RUNS -->", "<!-- RUNS -->\n" + new_row)
        else:
            # Fallback defensivo: si no está el placeholder, no rompemos el index.
            print("  ⚠️  index.html sin placeholder <!-- RUNS -->; fila no insertada. "
                  "Revisar formato del index.")
    else:
        content = (
            '<!DOCTYPE html>\n<html lang="es"><head><meta charset="utf-8">'
            '<title>Petal QA</title></head><body>'
            '<h1>Petal QA — Historico de runs</h1>'
            '<table><thead><tr><th>Fecha (UTC)</th><th>Commit</th>'
            '<th>Resultado</th><th>Reporte</th></tr></thead><tbody>'
            '<!-- RUNS -->\n' + new_row +
            '</tbody></table></body></html>'
        )
    index_path.write_text(content, encoding="utf-8")


# ==============================================================================
# main
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="QA Petal — ejecución quirúrgica de TCs + publicación selectiva en gh-pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--test", help="TCs a correr, separados por coma (ej: TC-URGENCIA-01,TC-URGENCIA-03)")
    parser.add_argument("--runs", type=int, default=None, help="Runs por TC (obligatorio en modo run)")
    parser.add_argument("--workers", type=int, default=8, help="TCs en paralelo (default 8, máx 15)")
    parser.add_argument("--publish", action="store_true", help="Modo publicación: mergea y publica en gh-pages")
    parser.add_argument("--base-ts", dest="base_ts", help="(publish) TS del run base a mergear (default: el más reciente)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="(publish) Construye pero NO hace push")
    args = parser.parse_args()

    if args.publish:
        cmd_publish(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
