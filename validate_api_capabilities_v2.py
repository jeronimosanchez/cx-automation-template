#!/usr/bin/env python3
"""
validate_api_capabilities_v2.py

Extension del v1 con 4 tests adicionales que Automatizacion ACT
necesita validar antes de Sprint 2.

Tests nuevos:
  10. PATCH con updateMask        — CRITICO para Sprint 2
  11. POST displayName duplicado  — CRITICO para Sprint 2
  12. Tamano maximo de Example    — informativo
  13. Paginacion profunda forzada — informativo

NO repite los 9 tests del v1. Si quieres re-ejecutarlos, corre el v1.

Uso:
  python3 validate_api_capabilities_v2.py
  python3 validate_api_capabilities_v2.py --critical-only  # solo 10-11
  python3 validate_api_capabilities_v2.py --skip-cleanup
"""

import argparse
import sys
import time
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
PLAYBOOK_REGISTRO = (
    f"{PARENT}/playbooks/2d111e5e-e811-4098-b52b-ab1128a0d0e2"
)
PLAYBOOK_ORCHESTRATOR = (
    f"{PARENT}/playbooks/00000000-0000-0000-0000-000000000000"
)

DUMMY_PREFIX = "__VALIDATION_V2_DUMMY_"

_dummy_paths = []  # cleanup tracking


# ============================================================
# AUTH Y HTTP
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
results = []


def record(test_id, name, status, detail=""):
    results.append((test_id, name, status, detail))
    icons = {"PASS": "OK ", "FAIL": "FAIL",
             "SKIP": "SKIP", "N/A": "N/A ", "INFO": "INFO"}
    print(f"  [{test_id}] {icons.get(status, '?')}  {name}")
    if detail:
        for line in detail.split("\n"):
            print(f"           {line}")


# ============================================================
# CLEANUP
# ============================================================
def cleanup_dummies():
    if not _dummy_paths:
        return
    print("\n[CLEANUP] Borrando Examples dummy v2...")
    try:
        headers = get_headers()
    except Exception as e:
        print(f"  No se pudo refrescar token para cleanup: {e}")
        print(f"  Borra manualmente: {_dummy_paths}")
        return
    for path in list(_dummy_paths):
        r = api_delete(headers, path)
        if r.status_code in (200, 204, 404):
            print(f"  borrado: ...{path[-40:]}")
            _dummy_paths.remove(path)
        else:
            print(
                f"  FALLO borrar {path}: {r.status_code} "
                f"{r.text[:120]}"
            )


# ============================================================
# DUMMY EXAMPLE BUILDERS
# ============================================================
def build_minimal_example(suffix=""):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return {
        "displayName": f"{DUMMY_PREFIX}{ts}{suffix}__",
        "actions": [
            {"userUtterance": {"text": "test v2 dummy"}},
            {"agentUtterance": {"text": "test v2 response"}},
        ],
        "playbookOutput": {"actionParameters": {"k": "v"}},
    }


def build_large_example(n_actions, suffix=""):
    """Example con n_actions intercaladas user/agent."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    actions = []
    for i in range(n_actions):
        if i % 2 == 0:
            actions.append({"userUtterance": {"text": f"u_{i}"}})
        else:
            actions.append({"agentUtterance": {"text": f"a_{i}"}})
    return {
        "displayName": f"{DUMMY_PREFIX}{ts}_LARGE_{n_actions}{suffix}__",
        "actions": actions,
        "playbookOutput": {"actionParameters": {"size": str(n_actions)}},
    }


def create_dummy(headers, body, track=True):
    r = api_post(headers, f"{PLAYBOOK_REGISTRO}/examples", body)
    if r.status_code == 200:
        path = r.json()["name"]
        if track:
            _dummy_paths.append(path)
        return path, r
    return None, r


# ============================================================
# TEST 10 — PATCH con updateMask (CRITICO Sprint 2)
# ============================================================
def test_10_patch_updatemask(headers):
    test_id = "10/13"
    name = "PATCH con updateMask (parcial, solo 1 campo)"

    # Crear dummy con displayName y agentUtterance conocidos
    path, r = create_dummy(headers, build_minimal_example("_um"))
    if not path:
        record(test_id, name, "FAIL",
               f"No se pudo crear dummy: {r.status_code} {r.text[:200]}")
        return

    # GET para tener ETag/version si la API los expone
    r_get = api_get(headers, path)
    body = r_get.json()
    original_dn = body["displayName"]
    original_text = body["actions"][1]["agentUtterance"]["text"]

    # PATCH solo cambiando displayName, con updateMask=displayName
    patch_body = copy.deepcopy(body)
    patch_body["displayName"] = original_dn + "_PATCHED_DN"
    patch_body["actions"][1]["agentUtterance"]["text"] = "TEXT_SHOULD_NOT_CHANGE"
    patch_body.pop("name", None)

    r = api_patch(headers, path, patch_body,
                  params={"updateMask": "displayName"})

    if r.status_code != 200:
        record(test_id, name, "FAIL",
               f"PATCH con updateMask devolvio {r.status_code}: "
               f"{r.text[:300]}")
        return

    # Verificar: displayName debe haber cambiado, agentUtterance NO
    r_verify = api_get(headers, path)
    verify = r_verify.json()
    new_dn = verify["displayName"]
    new_text = verify["actions"][1]["agentUtterance"]["text"]

    dn_changed = (new_dn != original_dn)
    text_unchanged = (new_text == original_text)

    if dn_changed and text_unchanged:
        record(test_id, name, "PASS",
               f"updateMask RESPETADO. Solo displayName cambio.\n"
               f"  Recommendation: Sprint 2 puede usar PATCH parcial para "
               f"reducir tokens y conflictos.\n"
               f"  Schema observado: PATCH ?updateMask=campo OK.")
    elif dn_changed and not text_unchanged:
        record(test_id, name, "FAIL",
               f"updateMask IGNORADO. Ambos campos cambiaron.\n"
               f"  Recommendation: Sprint 2 debe enviar PATCH completo "
               f"siempre, no usar updateMask.\n"
               f"  displayName: {original_dn} -> {new_dn}\n"
               f"  text: '{original_text}' -> '{new_text}'")
    else:
        record(test_id, name, "FAIL",
               f"Comportamiento inesperado.\n"
               f"  dn_changed={dn_changed}, text_unchanged={text_unchanged}")


# ============================================================
# TEST 11 — POST displayName duplicado (CRITICO Sprint 2)
# ============================================================
def test_11_post_duplicate_displayname(headers):
    test_id = "11/13"
    name = "POST con displayName duplicado"

    # Crear primer dummy
    path1, r1 = create_dummy(headers, build_minimal_example("_dup1"))
    if not path1:
        record(test_id, name, "FAIL",
               f"No se pudo crear dummy primario: {r1.status_code}")
        return

    # Coger su displayName
    r_get = api_get(headers, path1)
    duplicate_dn = r_get.json()["displayName"]

    # Intentar crear OTRO con mismo displayName
    body2 = build_minimal_example("_dup2")
    body2["displayName"] = duplicate_dn  # mismo nombre
    path2, r2 = create_dummy(headers, body2)

    if r2.status_code == 409:
        record(test_id, name, "PASS",
               f"API rechaza con 409 Conflict.\n"
               f"  Recommendation: Sprint 2 puede confiar en la API para "
               f"detectar duplicados. LIST + check existence puede saltarse.\n"
               f"  Mensaje: {r2.text[:200]}")
    elif r2.status_code == 200 and path2:
        # Comprobar si quedaron 2 con mismo displayName
        record(test_id, name, "PASS",
               f"API ACEPTA duplicados (200 OK, dos Examples con mismo "
               f"displayName).\n"
               f"  Recommendation: Sprint 2 DEBE hacer LIST previo y "
               f"comparar por displayName ANTES de crear. La API NO "
               f"tiene unique constraint en displayName.\n"
               f"  IDs duplicados: ...{path1[-12:]} y ...{path2[-12:]}",
               )
    elif r2.status_code == 400:
        record(test_id, name, "PASS",
               f"API rechaza con 400.\n"
               f"  Mensaje: {r2.text[:300]}\n"
               f"  Recommendation: Sprint 2 maneja como conflicto.")
    else:
        record(test_id, name, "FAIL",
               f"Status inesperado {r2.status_code}: {r2.text[:300]}")


# ============================================================
# TEST 12 — Tamano maximo de Example (informativo)
# ============================================================
def test_12_max_size(headers):
    test_id = "12/13"
    name = "Tamano maximo de Example (numero de actions)"

    sizes_to_try = [50, 200, 500, 1000]
    last_ok_size = 0
    first_fail_size = None
    first_fail_status = None
    first_fail_msg = ""

    for n in sizes_to_try:
        body = build_large_example(n, "_size")
        path, r = create_dummy(headers, body)
        if r.status_code == 200:
            last_ok_size = n
        else:
            first_fail_size = n
            first_fail_status = r.status_code
            first_fail_msg = r.text[:200]
            break

    if first_fail_size is None:
        record(test_id, name, "INFO",
               f"Acepto hasta {last_ok_size} actions sin fallar. "
               f"Limite real esta por encima.\n"
               f"  Recommendation: Sprint 2 no necesita preocuparse por "
               f"tamano de Examples normales (10-50 actions).")
    else:
        record(test_id, name, "INFO",
               f"OK hasta {last_ok_size} actions. Fallo a {first_fail_size}: "
               f"{first_fail_status}.\n"
               f"  Mensaje: {first_fail_msg}\n"
               f"  Recommendation: Sprint 2 limita a {last_ok_size} actions "
               f"por Example o split.")


# ============================================================
# TEST 13 — Paginacion profunda forzada (informativo)
# ============================================================
def test_13_deep_pagination(headers):
    test_id = "13/13"
    name = "Paginacion profunda con pageSize=1"

    pages_visited = 0
    total_examples = 0
    next_token = None
    max_pages = 20  # safety
    t0 = time.time()
    page_response_times = []

    while pages_visited < max_pages:
        params = {"pageSize": 1}
        if next_token:
            params["pageToken"] = next_token
        t_req = time.time()
        r = api_get(headers,
                    f"{PLAYBOOK_ORCHESTRATOR}/examples", params=params)
        page_response_times.append(time.time() - t_req)

        if r.status_code != 200:
            record(test_id, name, "FAIL",
                   f"Pagina {pages_visited+1} fallo: {r.status_code}")
            return
        data = r.json()
        examples = data.get("examples", [])
        total_examples += len(examples)
        pages_visited += 1
        next_token = data.get("nextPageToken")
        if not next_token:
            break

    elapsed = time.time() - t0
    avg_t = sum(page_response_times) / len(page_response_times) \
            if page_response_times else 0

    record(test_id, name, "PASS",
           f"{pages_visited} paginas con pageSize=1. "
           f"{total_examples} examples totales. "
           f"Total: {elapsed:.2f}s. Avg req: {avg_t*1000:.0f}ms.\n"
           f"  Recommendation: Sprint 2 use pageSize=20-50 (default 100) "
           f"para evitar overhead de tokens.")


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--critical-only", action="store_true",
                        help="solo tests 10 y 11 (criticos para Sprint 2)")
    parser.add_argument("--skip-cleanup", action="store_true",
                        help="no borrar dummies al final (debug)")
    args = parser.parse_args()

    if not args.skip_cleanup:
        atexit.register(cleanup_dummies)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"=" * 65)
    print(f"VALIDATE_API_CAPABILITIES_V2 {timestamp}")
    print(f"Tests adicionales para Sprint 2 de Automatizacion")
    print(f"=" * 65)

    print("\n[SETUP] Obteniendo token...")
    headers = get_headers()
    print("[SETUP] Token OK")

    print("\n" + "=" * 65)
    print("EJECUTANDO TESTS")
    print("=" * 65)

    test_10_patch_updatemask(headers)
    test_11_post_duplicate_displayname(headers)

    if not args.critical_only:
        test_12_max_size(headers)
        test_13_deep_pagination(headers)
    else:
        record("12/13", "Tamano maximo Example", "SKIP",
               "saltado por --critical-only")
        record("13/13", "Paginacion profunda", "SKIP",
               "saltado por --critical-only")

    # Reporte
    report_path = f"validation_report_v2_{timestamp}.txt"
    print("\n" + "=" * 65)
    print(f"RESUMEN  (reporte: {report_path})")
    print("=" * 65)

    pass_n = sum(1 for r in results if r[2] == "PASS")
    fail_n = sum(1 for r in results if r[2] == "FAIL")
    info_n = sum(1 for r in results if r[2] == "INFO")
    skip_n = sum(1 for r in results if r[2] in ("SKIP", "N/A"))

    for tid, name, status, _ in results:
        icons = {"PASS": "OK ", "FAIL": "FAIL", "SKIP": "SKIP",
                 "N/A": "N/A ", "INFO": "INFO"}
        print(f"  [{tid}] {icons.get(status, '?')}  {name}")

    print(
        f"\nTotal: {len(results)}  | PASS: {pass_n}  | FAIL: {fail_n}  "
        f"| INFO: {info_n}  | SKIP: {skip_n}"
    )

    with open(report_path, "w") as f:
        f.write(f"VALIDATE_API_CAPABILITIES_V2 {timestamp}\n")
        f.write(f"Agent: {AGENT_ID}\n")
        f.write(
            f"Total: {len(results)} | PASS: {pass_n} | FAIL: {fail_n}"
            f" | INFO: {info_n} | SKIP: {skip_n}\n\n"
        )
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
