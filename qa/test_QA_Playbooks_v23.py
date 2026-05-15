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

    {"id": "TC-C30", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Referencia implícita sin contexto",
     "turns": [{"user": "Las de siempre", "checks": ["cuales|refiere|que flores|que producto"]}],
     "not_expected": ["ramo|bouton|precio"]},

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

    {"id": "TC-C38", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cambio de idioma",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "I want the medium one", "checks": ["cuantos|cantidad|medium|mediano"]},
     ],
     "not_expected": []},

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
     "name": "Negación ambigua — toma iniciativa",
     "turns": [
         {"user": "Quiero flores", "checks": ["ocasion|motivo|tipo|flor|color"]},
         {"user": "No sé, lo que tú veas", "checks": ["ramo|bouton|rosa|opcion|popular|precio"]},
     ],
     "not_expected": ["ocasion|motivo|color"]},

    {"id": "TC-C42", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Confirmación ambigua — trata como sí",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "1", "checks": ["confirma|resumen"]},
         {"user": "Supongo que sí", "checks": ["email|correo|checkout|direccion"]},
     ],
     "not_expected": ["confirma|estas seguro|seguro"]},

    {"id": "TC-C43", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cancelación ambigua — no cancela ni confirma",
     "turns": [
         {"user": "Quiero rosas rojas para cumpleaños", "checks": ["talla|tamano|S|M|L|opcion"]},
         {"user": "El mediano", "checks": ["cu.ntos|cantidad"]},
         {"user": "1", "checks": ["confirma|resumen"]},
         {"user": "Mmm no sé", "checks": ["cambiar|dejar|algo|modificar"]},
     ],
     "not_expected": ["email|correo|checkout"]},

    # =====================================================
    # ANTI-REGRESION — DECORACION / INVENTARIO (S60, 15 may 2026)
    # Origen: repro brief S60. Ver qa/repro_margaritas_20260515.txt
    # Bug raiz: tool call con tipo='ramo' (minuscula) + ocasion=Decoracion
    # no encuentra Ramo de Margaritas (Decoracion en Categoria_Uso, no en Ocasion).
    # Agente improvisa "no tengo X" con alternativas que no son del producto pedido.
    # =====================================================
    {"id": "TC-DECO-01", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Margaritas para decorar — debe encontrar margaritas reales (no Tulipanes/Narcisos/Astromelias)",
     "turns": [
         {"user": "quiero un ramo de margaritas para decorar mi recibidor",
          "checks": ["Ramo de Margarita|Cesta.{0,20}Margarita"]},
     ],
     "not_expected": ["no tengo.{0,40}margarit", "no tenemos.{0,40}margarit"]},

    {"id": "TC-DECO-02", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Rosas para decorar — debe encontrar rosas reales (no falso positivo del eco)",
     "turns": [
         {"user": "quiero un ramo de rosas para decorar mi salon",
          "checks": ["Ramo de Rosa|Rosa.{0,10}Roj|Rosa.{0,10}Blanc|Rosa.{0,10}Rosa|Rosa.{0,10}Multi"]},
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
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


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


def check_turn(response_text, checks, not_expected):
    results = {"pass": True, "details": []}
    for check_str in checks:
        patterns = check_str.split("|")
        found = any(re.search(p, response_text, re.IGNORECASE) for p in patterns)
        if not found:
            results["pass"] = False
            results["details"].append(f"FAIL: esperaba [{check_str}]")
        else:
            matched = [p for p in patterns if re.search(p, response_text, re.IGNORECASE)]
            results["details"].append(f"OK: encontrado [{matched[0]}]")
    for neg in not_expected:
        if re.search(neg, response_text, re.IGNORECASE):
            results["pass"] = False
            results["details"].append(f"FAIL: NO deberia contener [{neg}]")
    return results


def run_single(token, test, run_num=1):
    session_id = str(uuid.uuid4())
    all_pass = True
    turn_results = []
    for i, turn in enumerate(test["turns"]):
        user_text = turn["user"].replace("{RUN}", f"{RUN_ID}_{run_num}")
        result = detect_intent(token, session_id, user_text)
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
    return {"pass": all_pass, "turns": turn_results}


def run_test(token, test, num_runs):
    runs = []
    for run_num in range(num_runs):
        r = run_single(token, test, run_num + 1)
        runs.append(r)
    pass_count = sum(1 for r in runs if r["pass"])
    if pass_count == num_runs:
        status = "PASS"
    elif pass_count == 0:
        status = "FAIL"
    else:
        status = "INESTABLE"
    return {
        "id": test["id"], "name": test["name"], "type": test["type"],
        "group": test["group"], "status": status,
        "pass_count": pass_count, "total_runs": num_runs,
        "runs": runs
    }


def print_result(r):
    icons = {"PASS": "\u2705", "FAIL": "\u274c", "INESTABLE": "\u26a0\ufe0f"}
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
                prefix = "      OK" if d.startswith("OK") else "      FAIL"
                print(f"    {prefix}: {d[4:]}")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_html(results, ts, txt_file):
    total = len(results)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_inst = sum(1 for r in results if r["status"] == "INESTABLE")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    pct = int((n_pass / total) * 100) if total else 0
    bar_g = f"{(n_pass/total)*100:.1f}" if total else "0"
    bar_y = f"{(n_inst/total)*100:.1f}" if total else "0"
    bar_r = f"{(n_fail/total)*100:.1f}" if total else "0"
    groups = sorted(set(r["group"].split(">")[0] for r in results))
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
.card.c-pass .n{{color:#22c55e}}.card.c-fail .n{{color:#ef4444}}.card.c-total .n{{color:#c8f060}}.card.c-inst .n{{color:#f59e0b}}.card.c-pct .n{{color:#888}}
.bar{{background:#1a1a1a;border-radius:6px;height:8px;margin-bottom:20px;overflow:hidden;display:flex}}
.bar-g{{background:#22c55e}}.bar-y{{background:#f59e0b}}.bar-r{{background:#ef4444}}
.dl{{display:inline-block;font-size:11px;padding:5px 14px;border-radius:5px;background:#c8f06022;color:#c8f060;border:1px solid #c8f06044;cursor:pointer;margin-bottom:16px;text-decoration:none}}
.dl:hover{{background:#c8f06033}}
.filter-bar{{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}}
.fbtn{{font-size:11px;padding:4px 12px;border-radius:5px;background:#1a1a1a;border:1px solid #282828;color:#777;cursor:pointer;transition:all .15s}}
.fbtn:hover{{border-color:#444;color:#ccc}}.fbtn.active{{border-color:#c8f060;color:#c8f060;background:#c8f06011}}
.t{{background:#141414;border:1px solid #222;border-radius:8px;margin-bottom:8px;overflow:hidden;transition:border-color .2s}}
.t:hover{{border-color:#333}}
.t.sb-pass{{border-left:3px solid #22c55e}}.t.sb-fail{{border-left:3px solid #ef4444}}.t.sb-inst{{border-left:3px solid #f59e0b}}
.th{{padding:10px 14px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;user-select:none}}
.th:hover{{background:#1a1a1a}}
.th-left{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.tid{{color:#c8f060;font-weight:500;font-size:12px;font-family:'DM Mono',monospace}}
.tname{{font-size:13px;color:#ccc}}
.tgroup{{font-size:10px;padding:2px 6px;border-radius:3px;background:#333;color:#999;font-family:'DM Mono',monospace}}
.truns{{font-size:10px;color:#777;font-family:'DM Mono',monospace}}
.b{{font-size:10px;padding:3px 8px;border-radius:4px;font-weight:600;letter-spacing:.3px}}
.b-p{{background:#22c55e22;color:#22c55e}}.b-f{{background:#ef444422;color:#ef4444}}.b-i{{background:#f59e0b22;color:#f59e0b}}
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
<div class="card c-pct"><div class="n">{pct}%</div><div class="l">Tasa</div></div>
</div>
<div class="bar"><div class="bar-g" style="width:{bar_g}%"></div><div class="bar-y" style="width:{bar_y}%"></div><div class="bar-r" style="width:{bar_r}%"></div></div>
<a class="dl" href="{txt_file}" download>\u2b07 TXT para Claude</a>
<div class="filter-bar">
<div class="fbtn" onclick="filterBy('all')">Todos</div>
<div class="fbtn" onclick="filterBy('PASS')">\u2705 Pass</div>
<div class="fbtn" onclick="filterBy('INESTABLE')">\u26a0\ufe0f Inestable</div>
<div class="fbtn" onclick="filterBy('FAIL')">\u274c Fail</div>
<div class="fbtn" onclick="filterByType('REG')">Regresi\u00f3n</div>
<div class="fbtn" onclick="filterByType('NEW')">Registro</div>
<div class="fbtn" onclick="filterByType('EDGE')">Metodolog\u00eda</div>"""
    for g in groups:
        h += f'\n<div class="fbtn" onclick="filterByGroup(\'{g}\')">{g}</div>'
    h += "\n</div>\n"
    for r in results:
        sb = {"PASS": "sb-pass", "FAIL": "sb-fail", "INESTABLE": "sb-inst"}[r["status"]]
        bc = {"PASS": "b-p", "FAIL": "b-f", "INESTABLE": "b-i"}[r["status"]]
        badge = f'<span class="b {bc}">{r["status"]}</span>'
        h += f"""<div class="t {sb}" data-status="{r['status']}" data-group="{r['group']}" data-type="{r['type']}">
<div class="th" onclick="toggle(this)">
<div class="th-left"><span class="tid">{r['id']}</span><span class="tname">{esc(r['name'])}</span><span class="tgroup">{r['group']}</span><span class="truns">{r['pass_count']}/{r['total_runs']}</span></div>
<div style="display:flex;gap:5px;align-items:center">{badge}<span class="arrow">\u25b6</span></div>
</div><div class="tbody">\n"""
        for ri, run in enumerate(r["runs"]):
            h += f'<div class="run-header {"rp" if run["pass"] else "rf"}">{"✅" if run["pass"] else "❌"} Run {ri+1}</div>\n'
            for t in run["turns"]:
                gi = t["params"].get("grupo_intent", "")
                gi_html = f'<div class="turn-params">$grupo_intent: <span>{gi}</span></div>' if gi else ""
                checks_html = "".join(f'<div class="turn-check {"ok" if d.startswith("OK") else "fail"}">{"✅" if d.startswith("OK") else "❌"} {esc(d[4:])}</div>' for d in t["checks"]["details"])
                h += f"""<div class="turn"><div class="turn-num">Turno {t['turn']}{" ⚠️" if not t["checks"]["pass"] else ""}</div>
<div class="turn-user"><div class="label">Usuario</div><div class="text">{esc(t['user'])}</div></div>
<div class="turn-agent"><div class="label">Agente</div><div class="text">{esc(t['agent'])}</div></div>
{gi_html}{checks_html}</div>\n"""
        h += "</div></div>\n"
    h += """<script>
function toggle(el){el.nextElementSibling.classList.toggle('open');el.querySelector('.arrow').classList.toggle('open')}
function filterBy(s){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>{if(s==='all'){t.classList.remove('hidden')}else{t.classList.toggle('hidden',t.dataset.status!==s)}});if(s!=='all')document.querySelectorAll('.card[data-filter="'+s+'"]').forEach(c=>c.classList.add('active'))}
function filterByGroup(g){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',!t.dataset.group.includes(g)))}
function filterByType(tp){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',t.dataset.type!==tp))}
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
    print(f"\n{'='*60}\nRESUMEN QA\n{'='*60}")
    print(f"Scripts: Orq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}")
    print(f"Fecha: {ts} | Runs: {RUNS}/TC")
    print(f"Total: {total} | \u2705 PASS: {n_pass} | \u26a0\ufe0f INESTABLE: {n_inst} | \u274c FAIL: {n_fail}\n{'='*60}")
    if n_fail > 0 or n_inst > 0:
        print("\nNO PASS:")
        for r in results:
            if r["status"] != "PASS":
                icon = "\u274c" if r["status"] == "FAIL" else "\u26a0\ufe0f"
                print(f"  {icon} {r['id']} [{r['group']}] \u2014 {r['name']}: {r['status']} ({r['pass_count']}/{r['total_runs']})")
    if IS_CI:
        out_dir = Path("./reports")
    elif IS_CLOUD_SHELL:
        out_dir = Path(".")
    else:
        out_dir = Path.home() / "petal-qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"qa_{ts_file}.txt"
    html_path = out_dir / f"qa_{ts_file}.html"
    with open(txt_path, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
    with open(html_path, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, txt_path.name))
    print(f"\n  TXT: {txt_path}\n  HTML: {html_path}")
    if IS_CI:
        # Latest copies sin timestamp, para URL fija publicada en GitHub Pages.
        latest_txt = out_dir / "qa_latest.txt"
        latest_html = out_dir / "qa_latest.html"
        with open(latest_txt, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
        with open(latest_html, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, latest_txt.name))
        print(f"  TXT (latest): {latest_txt}\n  HTML (latest): {latest_html}")
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
