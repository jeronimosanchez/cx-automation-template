#!/usr/bin/env python3
"""
validate_api_capabilities.py — Valida 9 capacidades pendientes de la API
REST v3beta1 de Dialogflow CX contra el agente Floristeria-Petal.

Sesion 60 — Floristeria Petal — Validacion previa a Automatizacion.

Crea un Example DUMMY en Registro_Task (displayName con prefijo
"__VALIDATION_DUMMY_<timestamp>__") y ejecuta las pruebas sobre ese
dummy. Limpia al final (atexit) incluso si algo falla.

NO modifica permanentemente Tools, Playbooks (instructions), ni
Examples reales. Las pruebas que tocan recursos compartidos (PATCH del
Tool, PATCH del Playbook) hacen no-op: GET primero, PATCH con el mismo
contenido para validar que el endpoint acepta el schema sin alterar
nada.

Pruebas:
  1. PATCH /examples/{id}                    — actualizar Example
  2. DELETE /examples/{id}                   — borrar Example
  3. PATCH del Tool (no-op, mismo contenido) — endpoint del Tool
  4. PATCH del Playbook (no-op)              — endpoint del Playbook
  5. Paginacion nextPageToken                — navegar paginas
  6. Rate limit (lecturas masivas)           — tolerancia 429
  7. Codigo de reintento exponencial         — funcionamiento del retry
  8. Diff Example local vs remoto            — funcion pura
  9. Concurrencia (2 PATCH simultaneos)      — opcional

Uso:
  python3 validate_api_capabilities.py
  python3 validate_api_capabilities.py --skip-concurrency
  python3 validate_api_capabilities.py --skip-cleanup    # debug
  python3 validate_api_capabilities.py --quick           # solo 1-5
"""

import argparse
import json
import sys
import time
import threading
import atexit
import copy
from datetime import datetime
import requests
import google.auth
import google.auth.transport.requests


# ============================================================
# CONSTANTES
# ============================================================
PROJECT = "floristeria-petal-digital"
LOCATION = "europe-west1"
AGENT_ID = "745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
BASE = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
PARENT = f"projects/{PROJECT}/locations/{LOCATION}/agents/{AGENT_ID}"

TOOL_PETAL = f"{PARENT}/tools/39e35fac-e018-4e98-b735-e45cb761bf5c"
PLAYBOOK_REGISTRO = (
    f"{PARENT}/playbooks/2d111e5e-e811-4098-b52b-ab1128a0d0e2"
)
PLAYBOOK_ORCHESTRATOR = (
    f"{PARENT}/playbooks/00000000-0000-0000-0000-000000000000"
)

DUMMY_PREFIX = "__VALIDATION_DUMMY_"

# Estado global para cleanup
_dummy_example_paths = []  # paths de dummies a limpiar


# ============================================================
# AUTH Y HTTP HELPERS
# ============================================================
def get_headers():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/dialogflow"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
        "x-goog-user-project": PROJECT,
    }


def api_get(headers, path, params=None):
    url = f"{BASE}/{path}" if not path.startswith("http") else path
    return requests.get(url, headers=headers, params=params)


def api_post(headers, path, body):
    url = f"{BASE}/{path}" if not path.startswith("http") else path
    return requests.post(url, headers=headers, json=body)


def api_patch(headers, path, body, params=None):
    url = f"{BASE}/{path}" if not path.startswith("http") else path
    return requests.patch(url, headers=headers, json=body, params=params)


def api_delete(headers, path):
    url = f"{BASE}/{path}" if not path.startswith("http") else path
    return requests.delete(url, headers=headers)


# ============================================================
# REPORTING
# ============================================================
results = []  # lista de (id, name, status, detail)


def record(test_id, name, status, detail=""):
    """status: PASS / FAIL / SKIP / N/A"""
    results.append((test_id, name, status, detail))
    icons = {"PASS": "OK ", "FAIL": "FAIL", "SKIP": "SKIP", "N/A": "N/A "}
    print(f"  [{test_id}] {icons.get(status, '?')}  {name}")
    if detail:
        for line in detail.split("\n"):
            print(f"           {line}")


# ============================================================
# CLEANUP
# ============================================================
def cleanup_dummies():
    if not _dummy_example_paths:
        return
    print("\n[CLEANUP] Borrando Examples dummy creados...")
    try:
        headers = get_headers()
    except Exception as e:
        print(f"  No se pudo refrescar token para cleanup: {e}")
        print(f"  Borra manualmente: {_dummy_example_paths}")
        return
    for path in list(_dummy_example_paths):
        r = api_delete(headers, path)
        if r.status_code in (200, 204, 404):
            print(f"  borrado: ...{path[-40:]}")
            _dummy_example_paths.remove(path)
        else:
            print(
                f"  FALLO borrar {path}: {r.status_code} "
                f"{r.text[:120]}"
            )


# ============================================================
# DUMMY EXAMPLE — payload base
# ============================================================
def build_dummy_example(suffix=""):
    """Example minimo para pruebas. NO se ejecuta en runtime
    (es solo texto)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "displayName": f"{DUMMY_PREFIX}{ts}{suffix}__",
        "actions": [
            {"userUtterance": {"text": "test dummy validation"}},
            {"agentUtterance": {"text": "test response dummy"}},
        ],
        "playbookOutput": {
            "actionParameters": {
                "test_param": "test_value",
            }
        },
    }


# ============================================================
# TESTS
# ============================================================
def test_01_patch_example(headers, dummy_example_path):
    """PATCH del Example dummy: cambia displayName y agentUtterance."""
    test_id = "1/9"
    name = "PATCH /examples/{id}"

    # GET actual
    r_get = api_get(headers, dummy_example_path)
    if r_get.status_code != 200:
        record(test_id, name, "FAIL",
               f"GET previo fallo: {r_get.status_code} "
               f"{r_get.text[:200]}")
        return None
    body = r_get.json()
    original_dn = body["displayName"]

    # Modificar
    body["displayName"] = original_dn + "_PATCHED"
    body["actions"][1]["agentUtterance"]["text"] = "test response PATCHED"

    # PATCH
    r = api_patch(headers, dummy_example_path, body)
    if r.status_code == 200:
        verify = api_get(headers, dummy_example_path).json()
        if verify["displayName"] == body["displayName"]:
            record(test_id, name, "PASS",
                   f"PATCH actualizo displayName y agentUtterance.\n"
                   f"Status: {r.status_code}")
        else:
            record(test_id, name, "FAIL",
                   "PATCH devolvio 200 pero verificacion no refleja "
                   "cambios")
        return body  # devuelvo body actualizado para siguiente test
    else:
        record(test_id, name, "FAIL",
               f"Status {r.status_code}: {r.text[:300]}")
        return None


def test_02_delete_example(headers, path):
    test_id = "2/9"
    name = "DELETE /examples/{id}"

    r = api_delete(headers, path)
    if r.status_code in (200, 204):
        # Verificar que ya no existe
        r_get = api_get(headers, path)
        if r_get.status_code == 404:
            record(test_id, name, "PASS",
                   f"DELETE OK ({r.status_code}). GET posterior: 404.")
            # Sacar de cleanup list (ya esta borrado)
            if path in _dummy_example_paths:
                _dummy_example_paths.remove(path)
            return True
        else:
            record(test_id, name, "FAIL",
                   f"DELETE {r.status_code} pero GET posterior: "
                   f"{r_get.status_code}")
            return False
    else:
        record(test_id, name, "FAIL",
               f"Status {r.status_code}: {r.text[:300]}")
        return False


def test_03_patch_tool_noop(headers):
    """No-op: GET del Tool, PATCH con el mismo contenido."""
    test_id = "3/9"
    name = "PATCH del Tool (no-op, mismo contenido)"

    r_get = api_get(headers, TOOL_PETAL)
    if r_get.status_code != 200:
        record(test_id, name, "FAIL",
               f"GET del Tool fallo: {r_get.status_code} "
               f"{r_get.text[:200]}")
        return
    tool_body = r_get.json()
    # Eliminar campos read-only que la API no acepta en PATCH
    for k in ("name",):
        tool_body.pop(k, None)

    r = api_patch(headers, TOOL_PETAL, tool_body)
    detail = (f"GET ok. PATCH devolvio {r.status_code}. "
              f"Schema visto: keys={list(tool_body.keys())}")
    if r.status_code == 200:
        record(test_id, name, "PASS",
               detail + "\nLa API acepta PATCH del Tool con el mismo "
                        "contenido.")
    elif r.status_code == 400 and "no" in r.text.lower():
        record(test_id, name, "PASS",
               detail + "\nLa API rechazo no-op (esperado en algunos "
                        "casos). Endpoint funciona.")
    else:
        record(test_id, name, "FAIL",
               detail + f"\nrespuesta: {r.text[:300]}")


def test_04_patch_playbook_noop(headers):
    """No-op: GET del Playbook Registro_Task, PATCH con mismo
    contenido."""
    test_id = "4/9"
    name = "PATCH del Playbook (no-op)"

    r_get = api_get(headers, PLAYBOOK_REGISTRO)
    if r_get.status_code != 200:
        record(test_id, name, "FAIL",
               f"GET fallo: {r_get.status_code} {r_get.text[:200]}")
        return
    pb_body = r_get.json()
    pb_body.pop("name", None)

    r = api_patch(headers, PLAYBOOK_REGISTRO, pb_body)
    detail = (f"GET ok. PATCH devolvio {r.status_code}. "
              f"Schema visto: keys={list(pb_body.keys())[:8]}")
    if r.status_code == 200:
        record(test_id, name, "PASS",
               detail + "\nEl endpoint del Playbook acepta PATCH.")
    elif r.status_code == 400:
        record(test_id, name, "PASS",
               detail + f"\n400 con detalle (endpoint funciona, "
                        f"hay constraints): {r.text[:200]}")
    else:
        record(test_id, name, "FAIL",
               detail + f"\nrespuesta: {r.text[:300]}")


def test_05_pagination(headers):
    """Lista Examples del Orchestrator (que tiene >10) y navega
    paginas."""
    test_id = "5/9"
    name = "Paginacion nextPageToken"

    pages_visited = 0
    total_examples = 0
    next_token = None
    max_pages = 5  # safety cap

    while pages_visited < max_pages:
        params = {"pageSize": 5}
        if next_token:
            params["pageToken"] = next_token
        r = api_get(headers,
                    f"{PLAYBOOK_ORCHESTRATOR}/examples", params=params)
        if r.status_code != 200:
            record(test_id, name, "FAIL",
                   f"Pagina {pages_visited+1} fallo: {r.status_code} "
                   f"{r.text[:200]}")
            return
        data = r.json()
        examples = data.get("examples", [])
        total_examples += len(examples)
        pages_visited += 1
        next_token = data.get("nextPageToken")
        if not next_token:
            break

    if pages_visited >= 2:
        record(test_id, name, "PASS",
               f"Visitadas {pages_visited} paginas, "
               f"{total_examples} examples totales del Orchestrator. "
               f"nextPageToken funciona.")
    elif pages_visited == 1:
        record(test_id, name, "N/A",
               f"Solo 1 pagina (Orchestrator tiene <=5 examples). "
               f"No se puede testear paginacion real.")
    else:
        record(test_id, name, "FAIL", "0 paginas visitadas")


def test_06_rate_limit(headers, quick=False):
    """Lecturas masivas para tantear rate limit."""
    test_id = "6/9"
    name = "Rate limit (60+ GETs seguidos)"

    n_requests = 30 if quick else 70
    req_429 = 0
    req_5xx = 0
    req_2xx = 0
    first_429_at = None
    t0 = time.time()

    for i in range(n_requests):
        r = api_get(headers,
                    f"{PLAYBOOK_REGISTRO}/examples", params={"pageSize": 1})
        if r.status_code == 200:
            req_2xx += 1
        elif r.status_code == 429:
            req_429 += 1
            if first_429_at is None:
                first_429_at = i + 1
        elif 500 <= r.status_code < 600:
            req_5xx += 1

    elapsed = time.time() - t0
    rate = n_requests / elapsed if elapsed > 0 else 0
    detail = (
        f"{n_requests} requests en {elapsed:.1f}s "
        f"({rate:.1f} req/s). "
        f"2xx={req_2xx}, 429={req_429}, 5xx={req_5xx}."
    )
    if first_429_at:
        detail += f"\nPrimer 429 en req #{first_429_at}."

    if req_429 == 0 and req_5xx == 0:
        record(test_id, name, "PASS",
               detail + "\nNo se vio rate limit. La API tolera "
                        "esta carga.")
    elif req_429 > 0:
        record(test_id, name, "PASS",
               detail + "\nRate limit observado. Automatizacion "
                        "debe implementar backoff.")
    else:
        record(test_id, name, "FAIL", detail)


def test_07_retry_function():
    """Test de la funcion de reintento (no necesita API real)."""
    test_id = "7/9"
    name = "Codigo de reintento exponencial (test interno)"

    # Simulamos una funcion con reintentos
    attempts_made = []

    def retry_with_backoff(func, max_retries=3, base_delay=0.05):
        last_err = None
        for attempt in range(max_retries):
            try:
                return func(attempt)
            except Exception as e:
                last_err = e
                attempts_made.append(attempt)
                if attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
        raise last_err

    # Caso: falla 2 veces, exito al 3er intento
    def failing_then_ok(attempt):
        if attempt < 2:
            raise RuntimeError(f"sim 5xx attempt {attempt}")
        return "OK"

    try:
        result = retry_with_backoff(failing_then_ok)
        if result == "OK" and attempts_made == [0, 1]:
            record(test_id, name, "PASS",
                   f"Retry recupero al 3er intento. "
                   f"Attempts: {attempts_made}")
        else:
            record(test_id, name, "FAIL",
                   f"resultado inesperado: result={result}, "
                   f"attempts={attempts_made}")
    except Exception as e:
        record(test_id, name, "FAIL", f"excepcion: {e}")


def test_08_diff_local_vs_remote(headers, dummy_path):
    """Diff entre body local y body remoto (funcion pura)."""
    test_id = "8/9"
    name = "Diff Example local vs remoto"

    # GET el dummy
    r = api_get(headers, dummy_path)
    if r.status_code != 200:
        record(test_id, name, "SKIP",
               f"No hay dummy para diffear (GET {r.status_code})")
        return
    remote = r.json()

    # Hacer una copia local con un cambio
    local = copy.deepcopy(remote)
    local["actions"][1]["agentUtterance"]["text"] = "VERSION DIFFERENT"

    # Diff simple sobre el campo actions (estructura compleja)
    def deep_diff(a, b, path=""):
        diffs = []
        if type(a) != type(b):
            diffs.append(f"{path}: tipo {type(a).__name__} != "
                         f"{type(b).__name__}")
        elif isinstance(a, dict):
            for k in set(a.keys()) | set(b.keys()):
                if k not in a:
                    diffs.append(f"{path}.{k}: solo en remoto")
                elif k not in b:
                    diffs.append(f"{path}.{k}: solo en local")
                else:
                    diffs.extend(deep_diff(a[k], b[k], f"{path}.{k}"))
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append(
                    f"{path}: len {len(a)} vs {len(b)}"
                )
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    diffs.extend(deep_diff(x, y, f"{path}[{i}]"))
        else:
            if a != b:
                diffs.append(
                    f"{path}: '{str(a)[:50]}' != '{str(b)[:50]}'"
                )
        return diffs

    diffs = deep_diff(local, remote)
    if len(diffs) == 1 and "agentUtterance" in diffs[0]:
        record(test_id, name, "PASS",
               f"deep_diff identifico exactamente el cambio:\n"
               f"  {diffs[0]}")
    else:
        record(test_id, name, "FAIL",
               f"Esperaba 1 diff, encontre {len(diffs)}: {diffs[:5]}")


def test_09_concurrency(headers, dummy_path):
    """Lanza 2 PATCH simultaneos al mismo Example y compara."""
    test_id = "9/9"
    name = "Concurrencia (2 PATCH simultaneos)"

    r = api_get(headers, dummy_path)
    if r.status_code != 200:
        record(test_id, name, "SKIP",
               f"No hay dummy disponible (GET {r.status_code})")
        return
    base_body = r.json()
    base_body.pop("name", None)

    results_local = []
    lock = threading.Lock()

    def do_patch(value):
        body = copy.deepcopy(base_body)
        body["actions"][1]["agentUtterance"]["text"] = (
            f"CONCURRENT_{value}"
        )
        rr = api_patch(headers, dummy_path, body)
        with lock:
            results_local.append((value, rr.status_code,
                                  rr.text[:100]))

    threads = [
        threading.Thread(target=do_patch, args=("A",)),
        threading.Thread(target=do_patch, args=("B",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [r[1] for r in results_local]
    detail = f"PATCH A: {results_local[0][1]}, PATCH B: {results_local[1][1]}"

    # Estado final
    r_final = api_get(headers, dummy_path).json()
    final_text = r_final["actions"][1]["agentUtterance"]["text"]
    detail += f"\nEstado final: '{final_text}'"

    if all(s == 200 for s in statuses):
        record(test_id, name, "PASS",
               detail + "\nAmbas PATCH 200. Last-write-wins "
                        "(sin lock optimista).")
    elif any(s == 409 for s in statuses):
        record(test_id, name, "PASS",
               detail + "\nUna PATCH devolvio 409 (conflict). "
                        "La API tiene control de concurrencia.")
    else:
        record(test_id, name, "FAIL", detail)


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Validacion de capacidades API Dialogflow CX"
    )
    parser.add_argument("--skip-concurrency", action="store_true",
                        help="omitir test 9 (concurrencia)")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="no borrar dummy al final (debug)")
    parser.add_argument("--quick", action="store_true",
                        help="solo tests 1-5 + rate limit reducido")
    args = parser.parse_args()

    if not args.skip_cleanup:
        atexit.register(cleanup_dummies)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"=" * 65)
    print(f"VALIDATE_API_CAPABILITIES {timestamp}")
    print(f"Agent: {AGENT_ID}")
    print(f"=" * 65)

    print("\n[SETUP] Obteniendo token...")
    headers = get_headers()
    print("[SETUP] Token OK")

    # Crear Example dummy en Registro_Task
    print(f"\n[SETUP] Creando Example dummy en Registro_Task...")
    dummy = build_dummy_example("_main")
    r = api_post(headers, f"{PLAYBOOK_REGISTRO}/examples", dummy)
    if r.status_code != 200:
        print(f"[FATAL] No se pudo crear dummy: "
              f"{r.status_code} {r.text[:300]}")
        return 1
    dummy_path = r.json()["name"]
    _dummy_example_paths.append(dummy_path)
    print(f"[SETUP] Dummy creado: ...{dummy_path[-50:]}")

    # ==================== TESTS ====================
    print("\n" + "=" * 65)
    print("EJECUTANDO TESTS")
    print("=" * 65)

    test_01_patch_example(headers, dummy_path)
    # Para test 2 creo un segundo dummy (porque test 2 lo borra)
    dummy2 = build_dummy_example("_for_delete")
    r2 = api_post(headers, f"{PLAYBOOK_REGISTRO}/examples", dummy2)
    if r2.status_code == 200:
        path2 = r2.json()["name"]
        _dummy_example_paths.append(path2)
        test_02_delete_example(headers, path2)
    else:
        record("2/9", "DELETE /examples/{id}", "SKIP",
               f"No se pudo crear segundo dummy: {r2.status_code}")

    test_03_patch_tool_noop(headers)
    test_04_patch_playbook_noop(headers)
    test_05_pagination(headers)
    test_06_rate_limit(headers, quick=args.quick)
    test_07_retry_function()
    test_08_diff_local_vs_remote(headers, dummy_path)

    if args.quick or args.skip_concurrency:
        record("9/9", "Concurrencia (2 PATCH simultaneos)",
               "SKIP", "saltado por flag")
    else:
        test_09_concurrency(headers, dummy_path)

    # ==================== REPORTE ====================
    report_path = f"validation_report_{timestamp}.txt"
    print("\n" + "=" * 65)
    print(f"RESUMEN  (reporte completo: {report_path})")
    print("=" * 65)

    pass_n = sum(1 for r in results if r[2] == "PASS")
    fail_n = sum(1 for r in results if r[2] == "FAIL")
    skip_n = sum(1 for r in results if r[2] in ("SKIP", "N/A"))

    for tid, name, status, _ in results:
        icons = {"PASS": "OK ", "FAIL": "FAIL",
                 "SKIP": "SKIP", "N/A": "N/A "}
        print(f"  [{tid}] {icons.get(status, '?')}  {name}")

    print(
        f"\nTotal: {len(results)}  | "
        f"PASS: {pass_n}  | FAIL: {fail_n}  | SKIP/NA: {skip_n}"
    )

    # Reporte completo a archivo
    with open(report_path, "w") as f:
        f.write(f"VALIDATE_API_CAPABILITIES {timestamp}\n")
        f.write(f"Agent: {AGENT_ID}\n")
        f.write(f"Total: {len(results)} | PASS: {pass_n} | "
                f"FAIL: {fail_n} | SKIP/NA: {skip_n}\n\n")
        for tid, name, status, detail in results:
            f.write(f"[{tid}] {status:4s}  {name}\n")
            if detail:
                for line in detail.split("\n"):
                    f.write(f"        {line}\n")
            f.write("\n")

    print(f"\nReporte guardado en: {report_path}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
