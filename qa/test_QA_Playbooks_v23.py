#!/usr/bin/env python3
"""
test_QA_Playbooks_v23.py — Testing automatizado Dialogflow CX
Sesión 60 — 29 tests: 15 base + 14 metodología Compra

Sprint 6 (14 mayo 2026): integrado al pipeline ACT vía .github/workflows/qa.yml.
Adaptaciones para CI: detección GITHUB_ACTIONS, output a ./reports en CI,
URL con environments/- (Default Environment de CX), sin webbrowser en CI.
Referencia: EP-QA-02 (ACT_Backlog).
Archivo original en ~/petal-sheet-api/ — NO modificar el original, solo esta copia.

Uso:
  python3 test_QA_Playbooks_v23.py                    # Los 29 tests
  python3 test_QA_Playbooks_v23.py --type REG          # Solo regresión
  python3 test_QA_Playbooks_v23.py --type NEW          # Solo registro
  python3 test_QA_Playbooks_v23.py --type EDGE         # Solo metodología
  python3 test_QA_Playbooks_v23.py --test TC-C29       # Un caso específico
  python3 test_QA_Playbooks_v23.py --runs 1            # 1 run por TC
  python3 test_QA_Playbooks_v23.py --list

v23 — 06 mayo 2026: Refresco variables de versión post-revert v40→v39 (S59).
                    NO se modifican TCs ni lógica. Solo header cosmético.
                    Objetivo: regresión sobre Compra v39 + Orq v65 + Registro v7.
v22 — 19 abril 2026: (entrada previa, sin cambios documentados respecto a v21)
v21 — 14 abril 2026: +14 TCs metodología Compra (zona gris, edges)
v20 — 14 abril 2026: Registro v12, Checkout v32, Orq v56, Compra v17
"""

import argparse, json, sys, subprocess, requests, uuid, os, time, re, webbrowser, platform
from datetime import datetime
from pathlib import Path

PROJECT = "floristeria-petal-digital"
LOCATION = "europe-west1"
AGENT_ID = "745375ba-ac7e-4eb8-b8a0-d742891f2aa4"
BASE = f"https://{LOCATION}-dialogflow.googleapis.com/v3beta1"
AGENT = f"projects/{PROJECT}/locations/{LOCATION}/agents/{AGENT_ID}"

SCRIPT_VERSION = "v23"
ORQ_VERSION = "v65"
COMPRA_VERSION = "v39"
CHECKOUT_VERSION = "v33"  # VERIFICAR contra CX antes de correr
REGISTRO_VERSION = "v7 (Task)"
RUNS = 3
RUN_ID = str(int(time.time()))[-6:]

# Leyenda de grupos para tooltips en chips de filtro (US-QA-06-07 v2: tooltip en vez de panel)
GROUP_LEGEND = {
    "G1": "Info de negocio (horario, dirección)",
    "G2": "Info de catálogo (precio, qué hay)",
    "G3": "Recomendación / sugerencia",
    "G4": "Saludo",
    "G5": "Compra directa con producto concreto",
    "G6": "Consulta de perfil que requiere identificación (saldo, etc.)",
    "G7": "Registro / onboarding cliente nuevo",
    "ESP": "Espontáneo (email fuera de flujo, pedir humano)",
    "COMPRA-ZG": "Compra Zona Gris (casos ambiguos)",
    "COMPRA-INV": "Compra Inventario (bugs específicos de catálogo)",
}

IS_CLOUD_SHELL = os.environ.get("CLOUD_SHELL") == "true" or os.path.exists("/google/devshell")
IS_CI = os.environ.get("GITHUB_ACTIONS") == "true"

TESTS = [
    # =====================================================
    # BASE — REGRESIÓN
    # =====================================================
    {"id": "TC-R01", "type": "REG", "group": "G1",
     "name": "Info negocio - horario",
     "turns": [{"user": "A que hora abris?", "checks": ["horario|lunes|sabado|9|20"]}],
     "not_expected": ["email", "correo"]},

    {"id": "TC-R02", "type": "REG", "group": "G2",
     "name": "Info catalogo - precio tulipanes",
     "turns": [{"user": "Cuanto cuestan los tulipanes?", "checks": ["euro|precio|tulipan"]}],
     "not_expected": ["email", "correo"]},

    {"id": "TC-R03", "type": "REG", "group": "G4",
     "name": "Saludo",
     "turns": [{"user": "Hola", "checks": ["hola|bienvenid|ayudar|Petal"]}],
     "not_expected": ["email", "correo"]},

    {"id": "TC-R04", "type": "REG", "group": "G5",
     "name": "Compra directa sin email",
     "turns": [{"user": "Quiero comprar rosas rojas", "checks": ["rosas|rosa|Ramo|Boutonniere|ocasi"]}],
     "not_expected": ["email", "correo"]},

    {"id": "TC-R06", "type": "REG", "group": "ESP",
     "name": "Email espontaneo",
     "turns": [{"user": "Mi email es ana@email.com", "checks": ["Ana|hola|ayudar|bienvenid|puedo|Hola"]}],
     "not_expected": []},

    {"id": "TC-N01", "type": "REG", "group": "G3",
     "name": "Recomendacion - transfiere a Compra",
     "turns": [{"user": "Necesito flores para un cumpleanos", "checks": ["regalo|presupuesto|ocasion|opciones|suger|buscar"]}],
     "not_expected": ["email", "correo"]},

    {"id": "TC-N03", "type": "REG", "group": "G6",
     "name": "Requiere perfil - pide email",
     "turns": [{"user": "Quiero ver mi saldo", "checks": ["email|correo"]}],
     "not_expected": []},

    {"id": "TC-E01", "type": "REG", "group": "ESP",
     "name": "Hablar con humano - sin pedir email",
     "turns": [{"user": "Quiero hablar con una persona", "checks": []}],
     "not_expected": ["email", "correo"]},

    # =====================================================
    # BASE — REGISTRO
    # =====================================================
    {"id": "TC-REG01", "type": "NEW", "group": "G7",
     "name": "Registro completo happy path desde Orquestador",
     "turns": [
         {"user": "Quiero registrarme", "checks": ["registr|nombre|email|correo|bienvenid|cuenta"]},
         {"user": "nuevoreg01_r{RUN}@test.com", "checks": ["nombre|como te llam"]},
         {"user": "Maria", "checks": ["apellido"]},
         {"user": "Garcia Lopez", "checks": ["particular|empresa|tipo"]},
         {"user": "particular", "checks": ["direcci|calle|domicilio|completa"]},
         {"user": "Calle Alcala 42, 28014 Madrid", "checks": ["portal|planta|letra|telefono"]},
         {"user": "No, es bajo", "checks": ["telefono|contacto"]},
         {"user": "612345678", "checks": ["correcto|revisa|datos|Nombre|Maria|registro"]},
         {"user": "Si, correcto", "checks": ["registrad|perfecto|Maria|ayudar|puedo"]},
     ],
     "not_expected": []},

    {"id": "TC-REG02", "type": "NEW", "group": "G7>ERR",
     "name": "Registro con email invalido desde Orquestador",
     "turns": [
         {"user": "Quiero registrarme", "checks": ["registr|nombre|email|correo|bienvenid|cuenta"]},
         {"user": "esto no es un email", "checks": ["valido|correo|email|@|formato"]},
         {"user": "ahora tampoco", "checks": ["valido|correo|email|@|formato|intent"]},
     ],
     "not_expected": []},

    {"id": "TC-REG03", "type": "NEW", "group": "G7>CANCEL",
     "name": "Registro cancelado a mitad desde Orquestador",
     "turns": [
         {"user": "Quiero registrarme", "checks": ["registr|nombre|email|correo|bienvenid|cuenta"]},
         {"user": "nuevoreg03_r{RUN}@test.com", "checks": ["nombre|como te llam"]},
         {"user": "Dejalo, no quiero registrarme", "checks": ["seguro|cancelar|entendido|pronto|registr"]},
     ],
     "not_expected": []},

    {"id": "TC-REG04", "type": "NEW", "group": "G5>CK>REG",
     "name": "Flujo COMPLETO: Compra → Checkout → Registro_Task → completa pedido",
     "turns": [
         {"user": "Quiero comprar un ramo de rosas rojas para un cumpleanos", "checks": ["rosas|Ramo|rosa"]},
         {"user": "El mediano", "checks": ["M|mediano|cantidad|cuantos|confirma"]},
         {"user": "1", "checks": ["confirma|resumen|Rosas|Ramo|email|correo"]},
         {"user": "nuevoreg04_r{RUN}@test.com", "checks": ["encontr|registr|otro|cuenta"]},
         {"user": "Si, registrame con ese", "checks": ["nombre|registr|datos|empezar|como"]},
         {"user": "Laura", "checks": ["apellido"]},
         {"user": "Martinez", "checks": ["particular|empresa|tipo"]},
         {"user": "particular", "checks": ["direcci|calle|domicilio|completa"]},
         {"user": "Avenida de la Paz 15, 08017 Barcelona", "checks": ["portal|planta|letra|telefono"]},
         {"user": "No", "checks": ["telefono|contacto"]},
         {"user": "933456789", "checks": ["correcto|revisa|datos|Nombre|Laura|registro"]},
         {"user": "Si, correcto", "checks": ["registrad|perfecto|Laura|continuamos"]},
         {"user": "Si, confirmo", "checks": ["pedido|Laura|Rosas|entrega|simulada|perfecto|euro|referencia"]},
     ],
     "not_expected": []},

    # =====================================================
    # TC-REG05 DEPRECADO (sesion 52, 18 abril 2026)
    # Razon: el flujo que validaba (Compra -> Checkout -> email-no-encontrado -> rechazo)
    # ya no existe en el estado actual del sistema. Tras multiples refactorizaciones
    # (email-tardio en Checkout, Registro_Task, PASO 1.5 Orquestador, Compra v28),
    # el caso funcional queda cubierto por TC-REG04. Mantener este test generaba
    # ruido (FAIL permanente) sin aportar cobertura nueva.
    # Backlog: task registrada como Hecho.
    # Se conserva comentado para rastreabilidad historica.
    # -----------------------------------------------------
    # {"id": "TC-REG05", "type": "NEW", "group": "G5>CK>CANCEL",
    #  "name": "Compra -> Checkout -> email no encontrado -> no quiere registrarse",
    #  "turns": [
    #      {"user": "Quiero comprar un ramo de rosas rojas", "checks": ["rosas|Ramo|rosa"]},
    #      {"user": "El pequeno", "checks": ["S|pequeno|cantidad|cuantos|confirma"]},
    #      {"user": "1", "checks": ["confirma|resumen|Rosas|Ramo|email|correo"]},
    #      {"user": "Si", "checks": ["email|correo"]},
    #      {"user": "noexiste999@test.com", "checks": ["encontr|registr|otro|cuenta"]},
    #      {"user": "No, dejalo", "checks": ["pronto|entendido|hasta|despedida|lament"]},
    #  ],
    #  "not_expected": []},

    {"id": "TC-REG06", "type": "NEW", "group": "G7>POST",
     "name": "Post-registro: Orquestador retoma y ofrece ayuda",
     "turns": [
         {"user": "Quiero registrarme", "checks": ["registr|nombre|email|correo|bienvenid|cuenta"]},
         {"user": "nuevoreg06_r{RUN}@test.com", "checks": ["nombre|como te llam"]},
         {"user": "Pedro", "checks": ["apellido"]},
         {"user": "Sanchez", "checks": ["particular|empresa|tipo"]},
         {"user": "particular", "checks": ["direcci|calle|domicilio|completa"]},
         {"user": "Gran Via 50, 28013 Madrid", "checks": ["portal|planta|letra|telefono"]},
         {"user": "No tengo portal", "checks": ["telefono|contacto"]},
         {"user": "No tengo", "checks": ["correcto|revisa|datos|Nombre|Pedro|registro"]},
         {"user": "Si, correcto", "checks": ["registrad|perfecto|Pedro|ayudar|puedo"]},
         {"user": "Quiero comprar rosas", "checks": ["rosas|rosa|Ramo|color|tipo|ocasi"]},
     ],
     "not_expected": []},

    {"id": "TC-E04", "type": "REG", "group": "G6>SALDO",
     "name": "Consulta saldo con email valido",
     "turns": [
         {"user": "Quiero ver mi saldo", "checks": ["email|correo"]},
         {"user": "ana@email.com", "checks": ["Ana|saldo|300|pago|pendiente|Hola"]},
     ],
     "not_expected": []},

    # =====================================================
    # METODOLOGÍA — COMPRA ZONA GRIS
    # =====================================================
    {"id": "TC-C29", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Ambigüedad total sin datos",
     "turns": [{"user": "Algo bonito para mi madre", "checks": ["tipo|flor|presupuesto|color|ocasion"]}],
     "not_expected": []},

    {"id": "TC-C31", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Presupuesto sin producto",
     "turns": [{"user": "Algo no muy caro", "checks": ["ocasion|tipo|flor|motivo"]}],
     "not_expected": []},

    {"id": "TC-C32", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cantidad ambigua — un par",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "Un par", "checks": ["2|dos|confirma|refiere"]},
     ],
     "not_expected": []},

    {"id": "TC-C33", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cantidad ambigua — varios",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "Varios", "checks": ["cuantos|exactamente|numero|unidades"]},
     ],
     "not_expected": ["confirma|resumen"]},

    {"id": "TC-C34", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cantidad por función",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "Para llenar una mesa", "checks": ["cuantos|numero|exactamente|unidades"]},
     ],
     "not_expected": ["confirma|resumen"]},

    {"id": "TC-C35", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Ocasión ambigua emocional",
     "turns": [{"user": "Es para alguien especial", "checks": ["ocasion|celebra|regalo|cumpleanos|boda|tipo"]}],
     "not_expected": []},

    {"id": "TC-C36", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Urgencia sin ocasión",
     "turns": [{"user": "Necesito flores para mañana", "checks": ["ocasion|motivo|tipo|flor|mente|especial"]}],
     "not_expected": []},

    {"id": "TC-C37", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Input numérico fuera de contexto",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El 3", "checks": ["refiere|cual|opcion|talla|tamano"]},
     ],
     "not_expected": ["confirma|resumen"]},

    {"id": "TC-C39", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Emoji solo",
     "turns": [{"user": "🌹", "checks": ["rosa|rosas|ocasion|motivo|color|flor|ayudar"]}],
     "not_expected": []},

    {"id": "TC-C40", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Pregunta out of scope en PASO 2",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "¿Cuál es vuestra política de devoluciones?", "checks": ["devolucion|cambio|politica|plazo|scope"]},
     ],
     "not_expected": []},

    {"id": "TC-C41", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Delegación ambigua — salta al siguiente slot",
     "turns": [
         {"user": "Quiero flores", "checks": ["ocasion|motivo|tipo|flor|color"]},
         {"user": "No sé, lo que tú veas", "checks": ["tipo|flor|color|preferencia|gustar|prefieres"]},
     ],
     "not_expected": ["ocasion|motivo|celebra"]},

    {"id": "TC-C42", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Handoff Compra → Checkout (pide email tras cantidad)",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "1", "checks": ["correo|email|pedido|confirma|resumen"]},
     ],
     "not_expected": []},

    {"id": "TC-C43", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Input ambiguo en PASO 0 Checkout — no cancela, re-pide email",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "1", "checks": ["correo|email|pedido|confirma|resumen"]},
         {"user": "Mmm no sé", "checks": ["correo|email|arroba|nombre@"]},
     ],
     "not_expected": ["cancelar|adios|pronto|otro producto"]},

    # =====================================================
    # ANTI-REGRESION — DECORACION / INVENTARIO (S60, 15 may 2026)
    # Origen: repro brief S60. Ver qa/repro_margaritas_20260515.txt
    # Bug raiz: tool call con tipo='ramo' (minuscula) + ocasion=Decoracion
    # no encuentra Ramo de Margaritas (Decoracion en Categoria_Uso, no en Ocasion).
    # Agente improvisa "no tengo X" con alternativas que no son del producto pedido.
    # =====================================================
    {"id": "TC-DECO-01", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Margaritas para decorar — el catalogo debe mostrar margaritas reales (formato producto -- talla)",
     "turns": [
         {"user": "quiero un ramo de margaritas para decorar mi recibidor",
          "checks": ["Margarita.{0,40}--.{0,5}[SMLX]|Margarita.{0,80}euros"]},
     ],
     "not_expected": ["no tengo.{0,40}margarit", "no tenemos.{0,40}margarit"]},

    {"id": "TC-DECO-02", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Rosas para decorar — el catalogo debe mostrar rosas reales (formato producto -- talla)",
     "turns": [
         {"user": "quiero un ramo de rosas para decorar mi salon",
          "checks": ["Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,80}euros"]},
     ],
     "not_expected": ["no tengo.{0,40}rosa", "no tenemos.{0,40}rosa"]},
]


# === API ===

def get_token():
    try:
        r = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except Exception as e:
        print(f"ERROR auth: {e}")
        print("  gcloud auth login && gcloud config set project floristeria-petal-digital")
        sys.exit(1)


def detect_intent(token, session_id, text):
    url = f"{BASE}/{AGENT}/environments/-/sessions/{session_id}:detectIntent"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "x-goog-user-project": PROJECT}
    body = {"queryInput": {"text": {"text": text}, "languageCode": "es"}}
    time.sleep(1.5)  # Throttle: LLM quota limit in europe-west1
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            # Quota exhausted — retry after backoff
            if "quota" in resp.text.lower() or "FailedPrecondition" in resp.text:
                wait = 5 * (attempt + 1)
                time.sleep(wait)
                continue
            # Other 4xx — not retryable
            return {"error": f"{resp.status_code}: {resp.text[:200]}", "is_quota_error": False}
        except Exception as e:
            return {"error": str(e), "is_quota_error": False}
    # All retries exhausted — quota error
    return {"error": f"QUOTA_EXHAUSTED after 3 retries: {resp.status_code}", "is_quota_error": True}


def extract_response(result):
    texts, playbook, params = [], "unknown", {}
    if "error" in result:
        return f"ERROR: {result['error']}", "error", {}
    qr = result.get("queryResult", {})
    for msg in qr.get("responseMessages", []):
        if "text" in msg:
            texts.extend(msg["text"].get("text", []))
    info = qr.get("currentPlaybook", "")
    if info:
        playbook = info.split("/")[-1] if "/" in info else info
    params = qr.get("parameters", {})
    return " ".join(texts), playbook, params


def _split_check_detail(d):
    """Split 'OK: msg' or 'FAIL: msg' into (status, msg). Tolera prefijos de longitud variable."""
    parts = d.split(": ", 1)
    status = parts[0]
    msg = parts[1] if len(parts) > 1 else d
    return status, msg


def check_turn(response_text, checks, not_expected):
    """Evalúa la respuesta del AGENTE contra checks positivos y negativos.

    Prefijos consistentes (los checks SIEMPRE evalúan al agente, nunca al usuario):
      - 'OK: Agente dijo [X]'           → regla positiva cumplida
      - 'FAIL: Agente debía decir [X]'  → regla positiva fallada
      - 'FAIL: Agente NO debía decir [X]' → regla negativa fallada
    """
    results = {"pass": True, "details": []}
    for check_str in checks:
        patterns = check_str.split("|")
        found = any(re.search(p, response_text, re.IGNORECASE) for p in patterns)
        if not found:
            results["pass"] = False
            results["details"].append(f"FAIL: Agente debía decir [{check_str}]")
        else:
            matched = [p for p in patterns if re.search(p, response_text, re.IGNORECASE)]
            results["details"].append(f"OK: Agente dijo [{matched[0]}]")
    for neg in not_expected:
        if re.search(neg, response_text, re.IGNORECASE):
            results["pass"] = False
            results["details"].append(f"FAIL: Agente NO debía decir [{neg}]")
    return results


def run_single(token, test, run_num=1):
    session_id = str(uuid.uuid4())
    all_pass = True
    has_quota_error = False
    turn_results = []
    for i, turn in enumerate(test["turns"]):
        user_text = turn["user"].replace("{RUN}", f"{RUN_ID}_{run_num}")
        result = detect_intent(token, session_id, user_text)
        if result.get("is_quota_error"):
            has_quota_error = True
        response_text, playbook, params = extract_response(result)
        checks = turn.get("checks", [])
        not_exp = test.get("not_expected", []) if i == 0 else []
        turn_check = check_turn(response_text, checks, not_exp)
        if not turn_check["pass"]:
            all_pass = False
        turn_results.append({
            "turn": i + 1, "user": user_text,
            "agent": response_text[:500], "playbook": playbook,
            "params": params, "checks": turn_check
        })
    return {"pass": all_pass, "turns": turn_results, "quota_error": has_quota_error}


def run_test(token, test, num_runs):
    runs = []
    for run_num in range(num_runs):
        r = run_single(token, test, run_num + 1)
        runs.append(r)
    pass_count = sum(1 for r in runs if r["pass"])
    quota_errors = sum(1 for r in runs if r.get("quota_error"))
    valid_runs = num_runs - quota_errors
    if valid_runs == 0:
        status = "QUOTA_ERROR"
    elif pass_count == valid_runs:
        status = "PASS"
    elif pass_count == 0 and quota_errors == 0:
        status = "FAIL"
    elif pass_count == 0 and quota_errors > 0:
        status = "QUOTA_ERROR"
    else:
        status = "INESTABLE"
    return {
        "id": test["id"], "name": test["name"], "type": test["type"],
        "group": test["group"], "status": status,
        "pass_count": pass_count, "total_runs": num_runs,
        "valid_runs": valid_runs, "quota_errors": quota_errors,
        "runs": runs
    }


def print_result(r):
    icons = {"PASS": "\u2705", "FAIL": "\u274c", "INESTABLE": "\u26a0\ufe0f", "QUOTA_ERROR": "\u26a1"}
    emoji = icons.get(r["status"], "?")
    print(f"\n{'='*60}")
    print(f"{r['id']} [{r['type']}] [{r['group']}] \u2014 {r['name']}")
    print(f"Resultado: {emoji} {r['status']} ({r['pass_count']}/{r['total_runs']})")
    print(f"{'='*60}")
    for ri, run in enumerate(r["runs"]):
        run_icon = "\u2705" if run["pass"] else "\u274c"
        print(f"\n  --- Run {ri+1}: {run_icon} ---")
        for t in run["turns"]:
            print(f"  Turno {t['turn']}:")
            print(f"    User: {t['user']}")
            print(f"    Agent: {t['agent'][:200]}")
            gi = t["params"].get("grupo_intent", "")
            if gi:
                print(f"    $grupo_intent: {gi}")
            for d in t["checks"]["details"]:
                status, msg = _split_check_detail(d)
                print(f"      {status}: {msg}")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================
# Análisis enriquecido por TC (EP-QA-06): carga desde qa/tc_analysis/*.md
# ============================================================

TC_ANALYSIS_DIR = Path(__file__).parent / "tc_analysis"


def _parse_frontmatter(text):
    """Parse YAML front-matter simple. Devuelve (meta_dict, body_str)."""
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            fm = text[3:end].strip()
            for line in fm.split("\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip()
            body = text[end + 4:].lstrip("\n")
    return meta, body


def _load_tc_analysis(tc_id):
    """Lee qa/tc_analysis/{tc_id}.md → {meta, turnos: {1: md, 2: md...}} o None."""
    path = TC_ANALYSIS_DIR / f"{tc_id}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    turnos = {}
    parts = re.split(r"^##\s+T(\d+)\s*$", body, flags=re.MULTILINE)
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            try:
                turnos[int(parts[i])] = parts[i + 1].strip()
            except (ValueError, IndexError):
                pass
    return {"meta": meta, "turnos": turnos, "body": body}


def _load_resumen():
    """Lee qa/tc_analysis/_resumen.md → str (markdown) o None."""
    path = TC_ANALYSIS_DIR / "_resumen.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    _, body = _parse_frontmatter(text)
    return body


def _md_to_html(text):
    """Conversión Markdown → HTML mínima para análisis MD (bold/italic/code/links/listas/tablas/headings)."""
    if not text:
        return ""
    # Escape HTML primero (luego re-insertamos las etiquetas que generamos)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = text.split("\n")
    out = []
    in_table = False
    table_buf = []
    in_list = False

    def flush_table():
        if not table_buf:
            return ""
        # Detectar header (primera fila) y separador (segunda con ---)
        rows = table_buf
        if len(rows) < 2:
            return "\n".join(rows)
        # Es tabla MD si la 2ª fila tiene "---"
        if not re.match(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", rows[1]):
            return "\n".join(rows)
        header_cells = [c.strip() for c in rows[0].strip("|").split("|")]
        body_rows = rows[2:]
        html = '<table class="md-table"><thead><tr>'
        for c in header_cells:
            html += f"<th>{_md_inline(c)}</th>"
        html += "</tr></thead><tbody>"
        for row in body_rows:
            cells = [c.strip() for c in row.strip("|").split("|")]
            html += "<tr>"
            for c in cells:
                html += f"<td>{_md_inline(c)}</td>"
            html += "</tr>"
        html += "</tbody></table>"
        return html

    for line in lines:
        stripped = line.strip()
        # Tablas (líneas con |)
        if "|" in stripped and stripped.startswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            in_table = True
            table_buf.append(stripped)
            continue
        elif in_table:
            out.append(flush_table())
            table_buf = []
            in_table = False
        # Headings
        if stripped.startswith("### "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h4>{_md_inline(stripped[4:])}</h4>")
            continue
        if stripped.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h3>{_md_inline(stripped[3:])}</h3>")
            continue
        if stripped.startswith("# "):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2>{_md_inline(stripped[2:])}</h2>")
            continue
        # Listas
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_md_inline(stripped[2:])}</li>")
            continue
        # Línea vacía → cierra lista, separador de párrafo
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("")
            continue
        # Párrafo
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{_md_inline(stripped)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append(flush_table())
    return "\n".join(out)


def _md_inline(text):
    """Aplica formato inline de markdown: **bold**, *italic*, `code`, [texto](url)."""
    # Bold **text** (antes que italic para no canibalizar **)
    text = re.sub(r"\*\*([^\*\n]+)\*\*", r"<strong>\1</strong>", text)
    # Italic *text*
    text = re.sub(r"(?<![\*])\*([^\*\n]+)\*(?![\*])", r"<em>\1</em>", text)
    # Inline code `text`
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    # Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def generate_html(results, ts, txt_file):
    total = len(results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_inst = sum(1 for r in results if r["status"] == "INESTABLE")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_quota = sum(1 for r in results if r["status"] == "QUOTA_ERROR")
    pct = int((n_pass / total) * 100) if total else 0
    bar_g = f"{(n_pass/total)*100:.1f}" if total else "0"
    bar_y = f"{(n_inst/total)*100:.1f}" if total else "0"
    bar_r = f"{(n_fail/total)*100:.1f}" if total else "0"
    groups = sorted(set(r["group"].split(">")[0] for r in results))
    quota_card = f'<div class="card c-quota" data-filter="QUOTA_ERROR" onclick="filterBy(\'QUOTA_ERROR\')"><div class="n">{n_quota}</div><div class="l">Quota</div></div>' if n_quota > 0 else ''
    h = f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<title>QA Petal {ts}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'DM Sans',sans-serif;background:#0e0e0e;color:#e0e0e0;padding:20px;max-width:960px;margin:0 auto}}
h1{{color:#c8f060;font-size:22px;font-weight:600;margin-bottom:4px}}
.sub{{color:#666;font-size:12px;margin-bottom:20px;font-family:'DM Mono',monospace}}
.hdr{{background:#141414;border:1px solid #222;border-radius:8px;padding:12px 16px;margin-bottom:16px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px 20px;font-size:12px;color:#777}}
.hdr b{{color:#bbb}}
.cards{{display:flex;gap:10px;margin-bottom:16px}}
.card{{background:#1a1a1a;border-radius:8px;padding:12px 18px;flex:1;text-align:center;cursor:pointer;transition:all .2s;border:1px solid transparent}}
.card:hover{{border-color:#444}}.card.active{{border-color:#c8f060}}
.card .n{{font-size:28px;font-weight:600}}.card .l{{font-size:10px;color:#666;text-transform:uppercase;letter-spacing:.5px}}
.card.c-pass .n{{color:#22c55e}}.card.c-fail .n{{color:#ef4444}}.card.c-total .n{{color:#c8f060}}.card.c-inst .n{{color:#f59e0b}}.card.c-quota .n{{color:#f97316}}.card.c-pct .n{{color:#888}}
.bar{{background:#1a1a1a;border-radius:6px;height:8px;margin-bottom:20px;overflow:hidden;display:flex}}
.bar-g{{background:#22c55e}}.bar-y{{background:#f59e0b}}.bar-r{{background:#ef4444}}
.dl{{display:inline-block;font-size:11px;padding:5px 14px;border-radius:5px;background:#c8f06022;color:#c8f060;border:1px solid #c8f06044;cursor:pointer;margin-bottom:16px;text-decoration:none}}
.dl:hover{{background:#c8f06033}}
.filter-bar{{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}}
.fbtn{{font-size:11px;padding:4px 12px;border-radius:5px;background:#1a1a1a;border:1px solid #282828;color:#777;cursor:pointer;transition:all .15s;position:relative}}
.fbtn[data-legend]:hover::after{{content:attr(data-legend);position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);background:#1f1f1f;color:#c8f060;padding:6px 10px;border-radius:4px;font-size:11px;white-space:nowrap;border:1px solid #444;z-index:10;pointer-events:none;font-weight:normal;box-shadow:0 2px 8px rgba(0,0,0,.4)}}
.fbtn[data-legend]:hover::before{{content:"";position:absolute;bottom:calc(100% + 1px);left:50%;transform:translateX(-50%);border:5px solid transparent;border-top-color:#444;z-index:10;pointer-events:none}}
.fbtn:hover{{border-color:#444;color:#ccc}}.fbtn.active{{border-color:#c8f060;color:#c8f060;background:#c8f06011}}
.t{{background:#141414;border:1px solid #222;border-radius:8px;margin-bottom:8px;overflow:hidden;transition:border-color .2s}}
.t:hover{{border-color:#333}}
.t.sb-pass{{border-left:3px solid #22c55e}}.t.sb-fail{{border-left:3px solid #ef4444}}.t.sb-inst{{border-left:3px solid #f59e0b}}.t.sb-quota{{border-left:3px solid #f97316}}
.th{{padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}}
.th:hover{{background:#1a1a1a}}
.th-left{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.tid{{color:#c8f060;font-weight:500;font-size:12px;font-family:'DM Mono',monospace}}
.tname{{font-size:13px;color:#ccc}}
.tgroup{{font-size:10px;padding:2px 6px;border-radius:3px;background:#333;color:#999;font-family:'DM Mono',monospace}}
.truns{{font-size:10px;color:#777;font-family:'DM Mono',monospace}}
.b{{font-size:10px;padding:3px 8px;border-radius:4px;font-weight:600;letter-spacing:.3px}}
.b-p{{background:#22c55e22;color:#22c55e}}.b-f{{background:#ef444422;color:#ef4444}}.b-i{{background:#f59e0b22;color:#f59e0b}}.b-q{{background:#f9731622;color:#f97316}}
.arrow{{transition:transform .2s;color:#555;font-size:14px}}.arrow.open{{transform:rotate(90deg)}}
.tbody{{display:none;padding:0 14px 14px;border-top:1px solid #1e1e1e}}.tbody.open{{display:block}}
.run-header{{font-size:11px;font-weight:600;color:#888;margin:12px 0 6px;padding:4px 8px;background:#111;border-radius:4px;font-family:'DM Mono',monospace}}
.run-header.rp{{color:#22c55e}}.run-header.rf{{color:#ef4444}}
.turn{{margin:6px 0;padding:10px 12px;background:#0e0e0e;border-radius:6px;border:1px solid #1e1e1e}}
.turn-num{{font-size:10px;color:#555;font-family:'DM Mono',monospace;margin-bottom:6px}}
.turn-user .label{{color:#8b8bf5;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.turn-user .text{{color:#ddd;font-size:13px;margin-top:2px}}
.turn-agent .label{{color:#c8f060;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.turn-agent .text{{color:#aaa;font-size:12px;margin-top:2px;line-height:1.5;max-height:120px;overflow-y:auto}}
.turn-params{{font-size:11px;color:#666;font-family:'DM Mono',monospace;margin-top:4px}}
.turn-params span{{color:#f59e0b}}
.turn-check{{margin-top:6px;font-size:11px}}.turn-check.ok{{color:#22c55e}}.turn-check.fail{{color:#ef4444}}
.turn-agent.has-fail{{border-left:3px solid #ef4444;padding-left:10px;margin-left:-2px}}
.turn-agent.has-ok{{border-left:3px solid #22c55e;padding-left:10px;margin-left:-2px}}
.veredicto{{margin:10px 0 14px;padding:10px 12px;background:#1a1612;border-radius:6px;border-left:3px solid #c8f060}}
.veredicto .v-lbl{{font-size:10px;color:#c8f060;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}}
.veredicto .v-txt{{font-size:13px;color:#ddd;line-height:1.55}}
.veredicto .v-tipo{{font-size:11px;color:#888;font-family:'DM Mono',monospace;margin-top:6px}}
.veredicto .v-tipo span{{color:#f59e0b}}
.ta-table{{width:100%;border-collapse:collapse;margin:8px 0}}
.ta-table th,.ta-table td{{vertical-align:top;border:1px solid #1e1e1e;padding:8px 10px}}
.ta-table th{{background:#111;color:#888;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;text-align:left}}
.ta-th-turno{{background:#1a1a1a !important;color:#c8f060 !important;font-family:'DM Mono',monospace}}
.ta-col-left{{width:42%;background:#0e0e0e}}
.ta-col-right{{width:58%;background:#111}}
.ta-run-block{{margin-bottom:8px;padding-bottom:8px;border-bottom:1px dashed #222}}
.ta-run-block:last-child{{border-bottom:none;margin-bottom:0;padding-bottom:0}}
.ta-run-tag{{display:inline-block;font-size:9px;padding:2px 6px;border-radius:3px;background:#222;color:#888;font-family:'DM Mono',monospace;margin-bottom:4px}}
.ta-run-tag.ok{{background:#22c55e22;color:#22c55e}}.ta-run-tag.fail{{background:#ef444422;color:#ef4444}}
.ta-user{{color:#8b8bf5;font-size:12px;margin-bottom:6px}}
.ta-user .lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;display:block;margin-bottom:2px}}
.ta-agent{{color:#aaa;font-size:12px;line-height:1.5;margin-bottom:6px}}
.ta-agent .lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;color:#c8f060;display:block;margin-bottom:2px}}
.ta-checks{{margin-top:4px}}
.ta-checks .turn-check{{margin-top:2px;font-size:10px}}
.ta-right h2,.ta-right h3,.ta-right h4{{color:#c8f060;font-size:12px;font-weight:600;margin:8px 0 4px}}
.ta-right h2{{font-size:14px}}.ta-right h4{{font-size:11px;color:#888}}
.ta-right p{{font-size:12px;color:#bbb;line-height:1.6;margin:4px 0}}
.ta-right ul{{margin:4px 0 4px 16px}}
.ta-right li{{font-size:12px;color:#bbb;line-height:1.55;margin:2px 0}}
.ta-right code{{background:#222;color:#c8f060;padding:1px 5px;border-radius:3px;font-size:11px;font-family:'DM Mono',monospace}}
.ta-right strong{{color:#ddd}}
.ta-right em{{color:#aaa;font-style:italic}}
.ta-right a{{color:#c8f060;text-decoration:none}}.ta-right a:hover{{text-decoration:underline}}
.ta-right .md-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}}
.ta-right .md-table th,.ta-right .md-table td{{border:1px solid #1e1e1e;padding:5px 7px;text-align:left}}
.ta-right .md-table th{{background:#1a1a1a;color:#c8f060;font-weight:600}}
.ta-right .md-table tr:nth-child(even){{background:#0e0e0e}}
.resumen-section{{margin:32px 0 16px;padding:18px 20px;background:#141414;border:1px solid #222;border-radius:8px;border-left:3px solid #c8f060}}
.resumen-section h2,.resumen-section h3,.resumen-section h4{{color:#c8f060;margin:14px 0 8px}}
.resumen-section h2{{font-size:18px;font-weight:600}}
.resumen-section h3{{font-size:14px;font-weight:600;color:#bbb}}
.resumen-section h4{{font-size:12px;color:#888}}
.resumen-section p{{font-size:13px;color:#bbb;line-height:1.6;margin:6px 0}}
.resumen-section ul{{margin:6px 0 10px 18px}}
.resumen-section li{{font-size:13px;color:#bbb;line-height:1.55;margin:3px 0}}
.resumen-section code{{background:#222;color:#c8f060;padding:1px 5px;border-radius:3px;font-size:12px;font-family:'DM Mono',monospace}}
.resumen-section strong{{color:#ddd}}
.resumen-section em{{color:#aaa;font-style:italic}}
.resumen-section .md-table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:12px}}
.resumen-section .md-table th,.resumen-section .md-table td{{border:1px solid #222;padding:8px 10px;text-align:left;vertical-align:top}}
.resumen-section .md-table th{{background:#1a1a1a;color:#c8f060;font-weight:600}}
.resumen-section .md-table tr:nth-child(even){{background:#0e0e0e}}
.actions-bar{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.modal{{position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:100;display:flex;align-items:center;justify-content:center}}
.modal.hidden{{display:none}}
.modal-overlay{{position:absolute;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7)}}
.modal-content{{position:relative;background:#141414;border:1px solid #333;border-radius:8px;padding:24px;max-width:880px;width:90%;max-height:80vh;overflow-y:auto}}
.modal-content h2{{color:#c8f060;font-size:18px;margin-bottom:14px}}
.modal-close{{position:absolute;top:10px;right:14px;background:none;border:none;color:#888;font-size:24px;cursor:pointer;line-height:1}}
.modal-close:hover{{color:#fff}}
.hist-table{{width:100%;border-collapse:collapse;font-size:12px}}
.hist-table th,.hist-table td{{border:1px solid #222;padding:8px 10px;text-align:left}}
.hist-table th{{background:#1a1a1a;color:#888;font-size:10px;text-transform:uppercase;letter-spacing:.5px;font-weight:600}}
.hist-table td.ok{{color:#22c55e;font-weight:600}}
.hist-table td.inst{{color:#f59e0b;font-weight:600}}
.hist-table td.fail{{color:#ef4444;font-weight:600}}
.hist-table tr:hover{{background:#1a1a1a}}
.hist-table tr.current{{background:#c8f06011}}
.hist-table tr.current td:first-child::after{{content:" ★";color:#c8f060}}
.hist-table a{{color:#c8f060;text-decoration:none}}.hist-table a:hover{{text-decoration:underline}}
.hist-loading{{padding:30px;text-align:center;color:#888}}
.grupos-legend{{margin:8px 0 16px;background:#141414;border:1px solid #222;border-radius:8px;padding:0}}
.grupos-legend summary{{cursor:pointer;padding:10px 14px;font-size:12px;color:#c8f060;font-weight:500;list-style:none;user-select:none}}
.grupos-legend summary::-webkit-details-marker{{display:none}}
.grupos-legend summary::before{{content:"▶ ";color:#555;font-size:10px;margin-right:4px}}
.grupos-legend[open] summary::before{{content:"▼ "}}
.grupos-legend[open] summary{{border-bottom:1px solid #1e1e1e}}
.legend-table{{width:100%;border-collapse:collapse;margin:0}}
.legend-table th{{background:#1a1a1a;color:#888;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:8px 14px;text-align:left;font-weight:600}}
.legend-table td{{padding:8px 14px;font-size:12px;border-top:1px solid #1e1e1e}}
.legend-table td:first-child{{width:160px;color:#c8f060;font-family:'DM Mono',monospace;font-size:11px}}
.legend-table code{{background:#222;color:#c8f060;padding:1px 5px;border-radius:3px;font-size:11px}}
.legend-table tr:nth-child(even){{background:#0e0e0e}}
.legend-note{{font-size:11px;color:#666;padding:10px 14px;border-top:1px solid #1e1e1e;margin:0}}
.backfilled-tag{{font-size:9px;background:#444;color:#bbb;padding:1px 5px;border-radius:3px;margin-left:6px;text-transform:uppercase;letter-spacing:.3px;font-family:'DM Mono',monospace}}
.hidden{{display:none!important}}
</style></head><body>
<h1>QA Report \u2014 Florister\u00eda Petal</h1>
<p class="sub">{ts} \u00b7 {RUNS} runs/TC \u00b7 {'Cloud Shell' if IS_CLOUD_SHELL else platform.node()}</p>
<div class="hdr">
<div><b>Orquestador:</b> {ORQ_VERSION}</div><div><b>Compra:</b> {COMPRA_VERSION}</div><div><b>Checkout:</b> {CHECKOUT_VERSION}</div>
<div><b>Registro:</b> {REGISTRO_VERSION}</div><div><b>QA Script:</b> {SCRIPT_VERSION}</div><div><b>Tests:</b> {total} \u00d7 {RUNS} runs</div>
</div>
<div class="cards">
<div class="card c-total" onclick="filterBy('all')"><div class="n">{total}</div><div class="l">Total</div></div>
<div class="card c-pass" data-filter="PASS" onclick="filterBy('PASS')"><div class="n">{n_pass}</div><div class="l">Pass</div></div>
<div class="card c-inst" data-filter="INESTABLE" onclick="filterBy('INESTABLE')"><div class="n">{n_inst}</div><div class="l">Inestable</div></div>
<div class="card c-fail" data-filter="FAIL" onclick="filterBy('FAIL')"><div class="n">{n_fail}</div><div class="l">Fail</div></div>
{quota_card}<div class="card c-pct"><div class="n">{pct}%</div><div class="l">Tasa</div></div>
</div>
<div class="bar"><div class="bar-g" style="width:{bar_g}%"></div><div class="bar-y" style="width:{bar_y}%"></div><div class="bar-r" style="width:{bar_r}%"></div></div>
<div class="actions-bar">
<a class="dl" href="{txt_file}" download>\u2b07 TXT para Claude</a>
<a class="dl" onclick="openHistorial()" style="cursor:pointer">\U0001f4ca Hist\u00f3rico</a>
</div>
<div class="filter-bar">
<div class="fbtn" onclick="filterBy('all')">Todos</div>
<div class="fbtn" onclick="filterBy('PASS')">\u2705 Pass</div>
<div class="fbtn" onclick="filterBy('INESTABLE')">\u26a0\ufe0f Inestable</div>
<div class="fbtn" onclick="filterBy('FAIL')">\u274c Fail</div>
<div class="fbtn" onclick="filterBy('QUOTA_ERROR')">\u26a1 Quota</div>
<div class="fbtn" onclick="filterByType('REG')">Regresi\u00f3n</div>
<div class="fbtn" onclick="filterByType('NEW')">Registro</div>
<div class="fbtn" onclick="filterByType('EDGE')">Metodolog\u00eda</div>"""
    for g in groups:
        legend = GROUP_LEGEND.get(g, "")
        legend_attr = f' data-legend="{esc(legend)}" title="{esc(legend)}"' if legend else ""
        h += f'\n<div class="fbtn"{legend_attr} onclick="filterByGroup(\'{g}\')">{g}</div>'
    h += "\n</div>\n"

    for r in results:
        sb = {"PASS": "sb-pass", "FAIL": "sb-fail", "INESTABLE": "sb-inst", "QUOTA_ERROR": "sb-quota"}.get(r["status"], "sb-inst")
        bc = {"PASS": "b-p", "FAIL": "b-f", "INESTABLE": "b-i", "QUOTA_ERROR": "b-q"}.get(r["status"], "b-i")
        badge = f'<span class="b {bc}">{r["status"]}</span>'
        h += f"""<div class="t {sb}" data-status="{r['status']}" data-group="{r['group']}" data-type="{r['type']}">
<div class="th" onclick="toggle(this)">
<div class="th-left"><span class="tid">{r['id']}</span><span class="tname">{esc(r['name'])}</span><span class="tgroup">{r['group']}</span><span class="truns">{r['pass_count']}/{r['total_runs']}</span></div>
<div style="display:flex;gap:5px;align-items:center">{badge}<span class="arrow">\u25b6</span></div>
</div><div class="tbody">\n"""
        analysis = _load_tc_analysis(r["id"])
        if analysis:
            # === Render enriquecido con análisis manual (qa/tc_analysis/{TC-ID}.md) ===
            meta = analysis["meta"]
            veredicto = meta.get("veredicto", "")
            tipo_clas = meta.get("tipo", "")
            if veredicto:
                h += '<div class="veredicto"><div class="v-lbl">Veredicto</div>'
                h += f'<div class="v-txt">{_md_inline(esc(veredicto))}</div>'
                if tipo_clas:
                    h += f'<div class="v-tipo">Tipo: <span>{esc(tipo_clas)}</span></div>'
                h += '</div>\n'
            n_turns = max((len(run["turns"]) for run in r["runs"]), default=0)
            for tn in range(1, n_turns + 1):
                runs_at_turn = []
                for ri, run in enumerate(r["runs"]):
                    if tn - 1 < len(run["turns"]):
                        runs_at_turn.append((ri, run, run["turns"][tn - 1]))
                if not runs_at_turn:
                    continue
                turn_analysis_md = analysis["turnos"].get(tn, "")
                turn_analysis_html = _md_to_html(turn_analysis_md) if turn_analysis_md else '<p><em>Sin análisis para este turno.</em></p>'
                user_text = esc(runs_at_turn[0][2]["user"])
                left_html = f'<div class="ta-user"><span class="lbl">Usuario (T{tn})</span>{user_text}</div>'
                for ri, run, t in runs_at_turn:
                    run_pass = t["checks"]["pass"]
                    run_tag_cls = "ok" if run_pass else "fail"
                    run_tag_icon = "✅" if run_pass else "❌"
                    run_tag = f'<span class="ta-run-tag {run_tag_cls}">Run {ri+1} · {run_tag_icon}</span>'
                    gi = t["params"].get("grupo_intent", "")
                    gi_html = f'<div class="turn-params">$grupo_intent: <span>{esc(gi)}</span></div>' if gi else ""
                    has_fail = any(d.startswith("FAIL") for d in t["checks"]["details"])
                    agent_cls = "has-fail" if has_fail else "has-ok"
                    checks_html = ""
                    for d in t["checks"]["details"]:
                        st, msg = _split_check_detail(d)
                        c_cls = "ok" if st == "OK" else "fail"
                        c_icon = "✅" if st == "OK" else "❌"
                        checks_html += f'<div class="turn-check {c_cls}">{c_icon} {esc(msg)}</div>'
                    left_html += f'<div class="ta-run-block">{run_tag}<div class="ta-agent {agent_cls}"><span class="lbl">Agente</span>{esc(t["agent"])}{gi_html}<div class="ta-checks">{checks_html}</div></div></div>'
                h += '<table class="ta-table"><tr>'
                h += f'<th colspan="2" class="ta-th-turno">Turno {tn}</th></tr><tr>'
                h += f'<td class="ta-col-left">{left_html}</td>'
                h += f'<td class="ta-col-right"><div class="ta-right">{turn_analysis_html}</div></td>'
                h += '</tr></table>\n'
        else:
            # === Render clásico (TCs sin análisis manual) — checks dentro de turn-agent ===
            for ri, run in enumerate(r["runs"]):
                h += f'<div class="run-header {"rp" if run["pass"] else "rf"}">{"✅" if run["pass"] else "❌"} Run {ri+1}</div>\n'
                for t in run["turns"]:
                    gi = t["params"].get("grupo_intent", "")
                    gi_html = f'<div class="turn-params">$grupo_intent: <span>{esc(gi)}</span></div>' if gi else ""
                    has_fail = any(d.startswith("FAIL") for d in t["checks"]["details"])
                    agent_cls = "has-fail" if has_fail else "has-ok"
                    checks_html = ""
                    for d in t["checks"]["details"]:
                        st, msg = _split_check_detail(d)
                        c_cls = "ok" if st == "OK" else "fail"
                        c_icon = "✅" if st == "OK" else "❌"
                        checks_html += f'<div class="turn-check {c_cls}">{c_icon} {esc(msg)}</div>'
                    h += f"""<div class="turn"><div class="turn-num">Turno {t['turn']}{" ⚠️" if not t["checks"]["pass"] else ""}</div>
<div class="turn-user"><div class="label">Usuario</div><div class="text">{esc(t['user'])}</div></div>
<div class="turn-agent {agent_cls}"><div class="label">Agente</div><div class="text">{esc(t['agent'])}</div>{checks_html}</div>
{gi_html}</div>\n"""
        h += "</div></div>\n"
    # Resumen agrupado por causa (carga qa/tc_analysis/_resumen.md si existe)
    resumen_md = _load_resumen()
    if resumen_md:
        h += f'<div class="resumen-section">{_md_to_html(resumen_md)}</div>\n'
        h += "</div></div>\n"
    # Modal Histórico (US-QA-06-06): tabla de runs anteriores con métricas
    h += """
<div id="historial-modal" class="modal hidden">
  <div class="modal-overlay" onclick="closeHistorial()"></div>
  <div class="modal-content">
    <button class="modal-close" onclick="closeHistorial()">&times;</button>
    <h2>Histórico de QA Runs</h2>
    <div id="hist-loading" class="hist-loading">Cargando histórico...</div>
    <table id="hist-table" class="hist-table hidden">
      <thead><tr><th>Fecha/hora</th><th>Total</th><th>Pass</th><th>Inestables</th><th>Fail</th><th>Tasa</th><th>Reporte</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>
</div>
<script>
function toggle(el){el.nextElementSibling.classList.toggle('open');el.querySelector('.arrow').classList.toggle('open')}
function filterBy(s){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>{if(s==='all'){t.classList.remove('hidden')}else{t.classList.toggle('hidden',t.dataset.status!==s)}});if(s!=='all')document.querySelectorAll('.card[data-filter="'+s+'"]').forEach(c=>c.classList.add('active'))}
function filterByGroup(g){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',!t.dataset.group.includes(g)))}
function filterByType(tp){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',t.dataset.type!==tp))}

const REPO_API='https://api.github.com/repos/jeronimosanchez/cx-automation-template/contents/qa?ref=gh-pages';
async function openHistorial(){
  const modal=document.getElementById('historial-modal');
  const loading=document.getElementById('hist-loading');
  const table=document.getElementById('hist-table');
  modal.classList.remove('hidden');
  loading.classList.remove('hidden');
  loading.textContent='Cargando histórico...';
  table.classList.add('hidden');
  try{
    const list=await fetch(REPO_API).then(r=>r.json());
    if(!Array.isArray(list)) throw new Error('No se pudo listar archivos');
    // Archivos .meta.json directos en /qa/
    const directMetas=list.filter(f=>f.type==='file' && f.name.endsWith('.meta.json')).map(f=>({file:f, parent:null}));
    // Subcarpetas con formato YYYYMMDD_HHMMSS
    const dirs=list.filter(f=>f.type==='dir' && /^\\d{8}_\\d{6}$/.test(f.name));
    // Para cada subcarpeta, buscar qa_latest.meta.json o qa_*.meta.json dentro
    const subMetaResults=(await Promise.all(dirs.map(async d=>{
      try{
        const subList=await fetch(d.url).then(r=>r.json());
        const latest=subList.find(f=>f.name==='qa_latest.meta.json') || subList.find(f=>f.name.endsWith('.meta.json'));
        if(latest) return {file:latest, parent:d.name};
      }catch(_){return null;}
      return null;
    }))).filter(Boolean);
    const allMetas=[...directMetas, ...subMetaResults];
    if(allMetas.length===0){loading.textContent='No hay metadatos históricos disponibles (esperar próximos runs).'; return;}
    const data=await Promise.all(allMetas.map(async item=>{
      try{
        const m=await fetch(item.file.download_url).then(r=>r.json());
        if(item.parent){m._url=`../${item.parent}/qa_latest.html`;}
        else{m._url=item.file.name.replace('.meta.json','.html');}
        return m;
      }catch(_){return null;}
    }));
    // Dedupe por ts_file, prefiriendo el primero
    const seen=new Set();
    const rows=data.filter(Boolean).filter(m=>{const k=m.ts_file||m._url; if(seen.has(k))return false; seen.add(k); return true;}).sort((a,b)=>(b.ts_file||'').localeCompare(a.ts_file||''));
    const currentTs=document.title.match(/\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}/);
    const tbody=table.querySelector('tbody');
    tbody.innerHTML='';
    rows.forEach(m=>{
      const tr=document.createElement('tr');
      if(currentTs && m.timestamp===currentTs[0]) tr.classList.add('current');
      const backfilled=m.backfilled?' <span class="backfilled-tag">retroactivo</span>':'';
      tr.innerHTML=`<td>${m.timestamp||'?'}${backfilled}</td><td>${m.total??'?'}</td><td class="ok">${m.pass??'?'}</td><td class="inst">${m.inst??'?'}</td><td class="fail">${m.fail??'?'}</td><td>${m.pct??'?'}%</td><td><a href="${m._url}">Ver</a></td>`;
      tbody.appendChild(tr);
    });
    loading.classList.add('hidden');
    table.classList.remove('hidden');
  }catch(e){
    loading.textContent='Error cargando histórico: '+e.message;
  }
}
function closeHistorial(){document.getElementById('historial-modal').classList.add('hidden')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeHistorial()});
</script></body></html>"""
    return h


def generate_txt(results, ts):
    total = len(results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_inst = sum(1 for r in results if r["status"] == "INESTABLE")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    t = f"QA Petal \u2014 {ts}\nOrq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}\nScript: {SCRIPT_VERSION} | Runs: {RUNS}/TC\nTotal: {total} | PASS: {n_pass} | INESTABLE: {n_inst} | FAIL: {n_fail}\n\n"
    for r in results:
        t += f"{r['id']} [{r['type']}] [{r['group']}] \u2014 {r['name']}: {r['status']} ({r['pass_count']}/{r['total_runs']})\n"
        for ri, run in enumerate(r["runs"]):
            t += f"  Run {ri+1}: {'PASS' if run['pass'] else 'FAIL'}\n"
            for turn in run["turns"]:
                t += f"    T{turn['turn']} User: {turn['user']}\n    T{turn['turn']} Agent: {turn['agent'][:300]}\n"
                gi = turn["params"].get("grupo_intent", "")
                if gi: t += f"    T{turn['turn']} $grupo_intent: {gi}\n"
                for d in turn["checks"]["details"]: t += f"      {d}\n"
        t += "\n"
    if n_fail > 0 or n_inst > 0:
        t += "NO PASS:\n"
        for r in results:
            if r["status"] != "PASS":
                t += f"  {r['id']} [{r['group']}] \u2014 {r['name']}: {r['status']} ({r['pass_count']}/{r['total_runs']})\n"
    return t


def generate_reports(results):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ts_file = datetime.now().strftime("%Y%m%d_%H%M")
    total = len(results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_inst = sum(1 for r in results if r["status"] == "INESTABLE")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_quota = sum(1 for r in results if r["status"] == "QUOTA_ERROR")
    print(f"\n{'='*60}\nRESUMEN QA\n{'='*60}")
    print(f"Scripts: Orq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}")
    print(f"Fecha: {ts} | Runs: {RUNS}/TC")
    print(f"Total: {total} | \u2705 PASS: {n_pass} | \u26a0\ufe0f INESTABLE: {n_inst} | \u274c FAIL: {n_fail}", end="")
    if n_quota > 0:
        print(f" | \u26a1 QUOTA_ERROR: {n_quota}", end="")
    print(f"\n{'='*60}")
    if n_fail > 0 or n_inst > 0 or n_quota > 0:
        print("\nNO PASS:")
        for r in results:
            if r["status"] != "PASS":
                icons = {"FAIL": "\u274c", "INESTABLE": "\u26a0\ufe0f", "QUOTA_ERROR": "\u26a1"}
                icon = icons.get(r["status"], "?")
                suffix = ""
                if r.get("quota_errors", 0) > 0:
                    suffix = f" [quota errors: {r['quota_errors']}/{r['total_runs']}]"
                print(f"  {icon} {r['id']} [{r['group']}] \u2014 {r['name']}: {r['status']} ({r['pass_count']}/{r['total_runs']}){suffix}")
    if IS_CI:
        out_dir = Path("./reports")
    elif IS_CLOUD_SHELL:
        out_dir = Path(".")
    else:
        out_dir = Path.home() / "petal-qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"qa_{ts_file}.txt"
    html_path = out_dir / f"qa_{ts_file}.html"
    meta_path = out_dir / f"qa_{ts_file}.meta.json"
    pct_val = int((n_pass / total) * 100) if total else 0
    meta = {
        "timestamp": ts, "ts_file": ts_file,
        "total": total, "pass": n_pass, "inst": n_inst, "fail": n_fail,
        "pct": pct_val, "runs_per_tc": RUNS,
        "versions": {
            "orquestador": ORQ_VERSION, "compra": COMPRA_VERSION,
            "checkout": CHECKOUT_VERSION, "registro": REGISTRO_VERSION,
            "script": SCRIPT_VERSION,
        },
    }
    with open(txt_path, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
    with open(html_path, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, txt_path.name))
    with open(meta_path, "w", encoding="utf-8") as f: json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"\n  TXT: {txt_path}\n  HTML: {html_path}\n  META: {meta_path}")
    if IS_CI:
        # Latest copies sin timestamp, para URL fija publicada en GitHub Pages.
        latest_txt = out_dir / "qa_latest.txt"
        latest_html = out_dir / "qa_latest.html"
        latest_meta = out_dir / "qa_latest.meta.json"
        with open(latest_txt, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
        with open(latest_html, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, latest_txt.name))
        with open(latest_meta, "w", encoding="utf-8") as f: json.dump(meta, f, indent=2, ensure_ascii=False)
        print(f"  TXT (latest): {latest_txt}\n  HTML (latest): {latest_html}\n  META (latest): {latest_meta}")
        return
    if IS_CLOUD_SHELL:
        subprocess.run("fuser -k 8080/tcp 2>/dev/null", shell=True, capture_output=True)
        try: os.remove("index.html")
        except: pass
        try: os.symlink(str(html_path), "index.html")
        except: pass
        subprocess.Popen(["python3", "-m", "http.server", "8080"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"\n  \U0001f310 Web Preview \u2192 port 8080 \u2192 {html_path.name}\n  Parar: fuser -k 8080/tcp")
    else:
        print(f"\n  \U0001f310 Abriendo en navegador...")
        webbrowser.open(html_path.resolve().as_uri())


def main():
    global RUNS
    parser = argparse.ArgumentParser(description="QA Petal v23 \u2014 29 tests")
    parser.add_argument("--test", help="Ejecutar solo un TC (ej: TC-C29)")
    parser.add_argument("--type", help="Filtrar: REG, NEW, EDGE")
    parser.add_argument("--runs", type=int, default=3, help="Runs por TC (default 3)")
    parser.add_argument("--list", action="store_true", help="Listar TCs")
    args = parser.parse_args()
    RUNS = max(1, min(args.runs, 5))
    if args.list:
        for t in TESTS:
            print(f"  {t['id']:12s} [{t['type']:4s}] [{t['group']:12s}] {t['name']}")
        return
    tests = TESTS
    if args.test:
        tests = [t for t in TESTS if t["id"] == args.test]
        if not tests: print(f"TC {args.test} no encontrado."); return
    elif args.type:
        tests = [t for t in TESTS if t["type"] == args.type]
        if not tests: print(f"Tipo {args.type} no encontrado."); return
    env = "Cloud Shell" if IS_CLOUD_SHELL else f"Local ({platform.system()})"
    print(f"QA Petal v23 \u2014 {env}")
    print(f"Orq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}")
    print(f"Ejecutando {len(tests)} tests \u00d7 {RUNS} runs...\n")
    token = get_token()
    results = []
    for test in tests:
        print(f"  {test['id']} \u2014 {test['name']}...", end="", flush=True)
        r = run_test(token, test, RUNS)
        results.append(r)
        print(f" {r['status']} ({r['pass_count']}/{r['total_runs']})")
    for r in results: print_result(r)
    generate_reports(results)


if __name__ == "__main__":
    main()
