#!/usr/bin/env python3
"""
test_qa_playbooks.py — Testing automatizado Dialogflow CX
Sesión 60 — 29 tests: 15 base + 14 metodología Compra

Sprint 6 (14 mayo 2026): integrado al pipeline ACT vía .github/workflows/qa.yml.
Adaptaciones para CI: detección GITHUB_ACTIONS, output a ./reports en CI,
URL con environments/- (Default Environment de CX), sin webbrowser en CI.
Referencia: EP-QA-02 (ACT_Backlog).
Archivo original en ~/petal-sheet-api/ — NO modificar el original, solo esta copia.

Uso:
  python3 test_qa_playbooks.py                    # Los 29 tests
  python3 test_qa_playbooks.py --type REG          # Solo regresión
  python3 test_qa_playbooks.py --type NEW          # Solo registro
  python3 test_qa_playbooks.py --type EDGE         # Solo metodología
  python3 test_qa_playbooks.py --test TC-C29       # Un caso específico
  python3 test_qa_playbooks.py --runs 1            # 1 run por TC
  python3 test_qa_playbooks.py --list

v23 — 06 mayo 2026: Refresco variables de versión post-revert v40→v39 (S59).
                    NO se modifican TCs ni lógica. Solo header cosmético.
                    Objetivo: regresión sobre Compra v39 + Orq v65 + Registro v7.
v22 — 19 abril 2026: (entrada previa, sin cambios documentados respecto a v21)
v21 — 14 abril 2026: +14 TCs metodología Compra (zona gris, edges)
v20 — 14 abril 2026: Registro v12, Checkout v32, Orq v56, Compra v17
"""

import argparse, json, sys, subprocess, requests, uuid, os, time, re, webbrowser, platform, shutil, threading
from concurrent.futures import ThreadPoolExecutor
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

# --- Contexto temporal de España (se calcula una vez al arrancar el runner) ---
def _temporal_ctx():
    """Devuelve hora_actual, dia_semana y entrega_hoy_posible según la hora real de Madrid."""
    try:
        from zoneinfo import ZoneInfo
        now = __import__("datetime").datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        import datetime as _dt
        now = _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc)
    _dias = {0: "lunes", 1: "martes", 2: "miercoles", 3: "jueves",
             4: "viernes", 5: "sabado", 6: "domingo"}
    return {
        "hora_actual": now.strftime("%H:%M"),
        "dia_semana": _dias[now.weekday()],
        "entrega_hoy_posible": "si" if now.hour < 14 else "no",
    }

_CTX = _temporal_ctx()  # {"hora_actual": "HH:MM", "dia_semana": "...", "entrega_hoy_posible": "si/no"}
# -------------------------------------------------------------------------------

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
     "name": "Margaritas para decorar — el catalogo debe mostrar margaritas reales (formato producto -- talla, acepta -- / — / –)",
     "turns": [
         {"user": "quiero un ramo de margaritas para decorar mi recibidor",
          "checks": ["Margarita.{0,40}--.{0,5}[SMLX]|Margarita.{0,40}—.{0,5}[SMLX]|Margarita.{0,40}–.{0,5}[SMLX]|Margarita.{0,80}euros"]},
     ],
     "not_expected": ["no tengo.{0,40}margarit", "no tenemos.{0,40}margarit"]},

    {"id": "TC-DECO-02", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Rosas para decorar — el catalogo debe mostrar rosas reales (formato producto -- talla, acepta -- / — / –)",
     "turns": [
         {"user": "quiero un ramo de rosas para decorar mi salon",
          "checks": ["Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,40}—.{0,5}[SMLX]|Rosa.{0,40}–.{0,5}[SMLX]|Rosa.{0,80}euros"]},
     ],
     "not_expected": ["no tengo.{0,40}rosa", "no tenemos.{0,40}rosa"]},

    # =====================================================
    # TIER 1 — NUEVOS HAPPY PATHS Y EDGE CASES (16 may, sesion post-Met-S63)
    # 8 TCs alta probabilidad de uso real: modos de tono no cubiertos,
    # refinamiento, cambio de opinion, frustracion, variantes S/M/L.
    # =====================================================

    {"id": "TC-FUNERAL-01", "type": "NEW", "group": "G5",
     "name": "Modo solemne — corona para funeral",
     "turns": [
         {"user": "necesito una corona para un funeral",
          "checks": ["corona|funebr|ceremonia|pesame|familia|opciones|tipo|encaja"]},
     ],
     "not_expected": ["mira,|genial|fenomenal|🌸"]},

    {"id": "TC-PRESUPUESTO-01", "type": "NEW", "group": "G5",
     "name": "Presupuesto duro — precio_max explicito",
     "turns": [
         {"user": "quiero rosas maximo 30 euros",
          "checks": ["rosa|ramo|opcion|euro|22|25|presupuesto"]},
     ],
     "not_expected": ["132|premium.{0,30}euros"]},

    {"id": "TC-COLOR-01", "type": "NEW", "group": "G5",
     "name": "Compra con color especifico no-rojo (tulipanes blancos)",
     "turns": [
         {"user": "quiero tulipanes blancos",
          "checks": ["Tulipan|tulipan|blanc|euro|opcion"]},
     ],
     "not_expected": ["no tengo.{0,40}tulipan"]},

    {"id": "TC-REFINAR-01", "type": "NEW", "group": "G5",
     "name": "Refinamiento de precio mid-flow — mas baratas",
     "turns": [
         {"user": "quiero un ramo de rosas para cumpleaños",
          "checks": ["ramo|rosa|opcion|tamano|euro"]},
         {"user": "mas baratas",
          "checks": ["rosa|ramo|euro|22|menos|menor|opcion"]},
     ],
     "not_expected": []},

    {"id": "TC-BODA-01", "type": "NEW", "group": "G5",
     "name": "Modo Boda — ramo nupcial",
     "turns": [
         {"user": "quiero un ramo de novia para mi boda",
          "checks": ["ramo|novia|boda|opcion|encaja|propongo"]},
     ],
     "not_expected": ["🌸"]},

    {"id": "TC-CAMBIO-OP-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Cambio de opinion mid-flow — usuario abandona tras seleccionar",
     "turns": [
         {"user": "quiero rosas rojas para cumpleaños",
          "checks": ["rosa|ramo|opcion|tamano"]},
         {"user": "el mediano",
          "checks": ["cu.ntos|cantidad|M|37"]},
         {"user": "uy, mejor no, dejalo",
          "checks": ["pronto|hasta|gracias|otro momento|ayudar|algo mas|entendido"]},
     ],
     "not_expected": ["email|correo|checkout|direccion|confirma"]},

    {"id": "TC-FRUSTRACION-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Multiples rechazos consecutivos — debe escalar o reformular",
     "turns": [
         {"user": "quiero rosas",
          "checks": ["rosa|ramo|opcion|tamano|ocasion"]},
         {"user": "no me gustan",
          "checks": ["otra|alternativ|otras|propongo|encaja|tipo"]},
         {"user": "tampoco me convencen, dame otras",
          "checks": ["propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano"],
          "desc": "Segundo rechazo consecutivo — el agente debía proponer alternativa por tipo u ocasión, o escalar al equipo"},
         {"user": "ninguna me gusta",
          "checks": ["equipo|persona|humano|hablar|asistente|encontrar|contacto|disculpa|otra ocasion"]},
     ],
     "not_expected": ["Tienes algún color en mente.{0,80}Tienes algún color en mente"]},

    {"id": "TC-VARIANTES-SML-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "TT-11 Caso B — 3 variantes S/M/L del mismo producto, eleccion por tamano coloquial",
     "turns": [
         {"user": "quiero un ramo de rosas rojas para cumpleaños",
          "checks": ["ramo|rosa|opcion|tamano|S|M|L|X"]},
         {"user": "la mediana",
          "checks": ["M|mediano|cu.ntos|cantidad|euro|37"]},
     ],
     "not_expected": ["confirma.{0,30}es correcto"]},

    # =====================================================
    # TIER 2 — EDGE CASES ADICIONALES (16 may, sesion post-Met-S63)
    # 13 TCs de robustez/escalacion/casos limite. Cortos (1-3 turnos).
    # =====================================================

    # --- Tier 2A: alta probabilidad (>40%) ---

    {"id": "TC-ROBUSTEZ-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Robustez parser — input en MAYUSCULAS sin acentos",
     "turns": [
         {"user": "QUIERO ROSAS ROJAS PARA CUMPLEANOS",
          "checks": ["rosa|ramo|opcion|tamano"]},
     ],
     "not_expected": ["no entiendo|disculpa.{0,30}no"]},

    {"id": "TC-STOCK-EXCESO-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "TT-25 — cantidad > stock disponible, agente debe avisar",
     "turns": [
         {"user": "quiero un ramo de rosas rojas pequeño",
          "checks": ["rosa|ramo|opcion|tamano|S"]},
         {"user": "el pequeño",
          "checks": ["cu.ntos|cantidad"]},
         {"user": "50",
          "checks": ["stock|disponible|solo|quedan|menos|tengo|prefieres|continuamos"]},
     ],
     "not_expected": ["pedido confirmado|checkout|email"]},

    {"id": "TC-URGENCIA-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Entrega urgente — hora exacta ('quiero rosas para hoy a las 18:00')",
     "turns": [
         {"user": "quiero un ramo de rosas para hoy a las 18:00",
          "checks": ["hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano"],
          "desc": "El agente debía reconocer la urgencia horaria y verificar el plazo de entrega antes de mostrar catálogo"},
     ],
     "not_expected": []},

    {"id": "TC-URGENCIA-02", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Entrega urgente — urgencia sin fecha, usuario confirma mañana por la mañana",
     "turns": [
         {"user": "lo necesito urgente, ¿en cuánto tiempo entregáis?",
          "checks": ["plazo|24h|24 horas|entrega|hora|tiempo"],
          "desc": "El agente debía informar sobre el plazo de entrega antes de continuar con la compra"},
         {"user": "mañana por la mañana",
          "checks": ["mañana|perfecto|posible|24h|llega|pedido"]},
     ],
     "not_expected": []},

    {"id": "TC-URGENCIA-03", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Entrega urgente — plazo viernes, agente confirma viabilidad y politica de envio",
     "turns": [
         {"user": "lo necesito para este viernes",
          "checks": ["24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo"],
          "desc": "El agente debía confirmar la viabilidad de entrega para el viernes antes de mostrar catálogo"},
     ],
     "not_expected": []},

    {"id": "TC-FRUSTRACION-LEX-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Lexico negativo del usuario — agente reconoce frustracion",
     "turns": [
         {"user": "quiero rosas",
          "checks": ["rosa|ramo|opcion|tamano|ocasion"]},
         {"user": "esto no funciona, que desastre",
          "checks": ["disculp|entend|alternativ|equipo|persona|propong|reformul|tipo"]},
     ],
     "not_expected": []},

    {"id": "TC-MULTI-SLOT-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Parseo multi-info en un solo input — extraccion robusta",
     "turns": [
         {"user": "hola, quiero un ramo de rosas rojas maximo 40 euros para mi boda",
          "checks": ["rosa|ramo|boda|euro|opcion|tamano"]},
     ],
     "not_expected": ["no entiendo|ocasion.*especial.{0,40}\\?"]},

    # --- Tier 2B: media probabilidad (20-30%) ---

    {"id": "TC-DESPEDIDA-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Despedida abrupta — cierre amable sin pedido completo",
     "turns": [
         {"user": "quiero rosas",
          "checks": ["rosa|ramo|opcion|tamano|ocasion"]},
         {"user": "déjalo, gracias",
          "checks": ["pronto|hasta|gracias|otro momento|ayudar|algo mas|entendido"]},
     ],
     "not_expected": ["email|correo|checkout"]},

    {"id": "TC-DIR-CUSTOM-01", "type": "EDGE", "group": "G5>CK",
     "name": "Override direccion habitual — cliente identificado pide otra direccion",
     "turns": [
         {"user": "mi email es ana@email.com y quiero un ramo de rosas rojas talla M para regalo, pero envialo a la oficina, no a mi casa",
          "checks": ["rosa|ramo|oficina|otra direcc|nueva direcc|Ana|opcion"]},
     ],
     "not_expected": []},

    {"id": "TC-MULTI-PRODUCTO-01", "type": "EDGE", "group": "COMPRA-INV",
     "name": "Pedido multi-item — ECO RESUMEN muestra total antes de confirmar",
     "turns": [
         {"user": "quiero un ramo de rosas y un centro de mesa para mi casa",
          "checks": ["centro.{0,80}ramo|ramo.{0,80}centro|empez.{0,20}por|uno.{0,20}vez|un producto"]},
         {"user": "el ramo de rosas morado de 37 euros",
          "checks": ["morado|anotado"],
          "desc": "El agente anota el primer producto (ramo morado 37€) y pide el segundo"},
         {"user": "el centro de tulipanes de 28 euros",
          "checks": ["65"],
          "desc": "El agente debía mostrar el resumen con el total calculado (37 + 28 = 65€) antes de pedir confirmación"},
     ],
     "not_expected": []},

    # --- Tier 2C: baja probabilidad (<20%) ---

    {"id": "TC-MOROSO-01", "type": "EDGE", "group": "G6>DEUDA",
     "name": "Cliente con deuda detectada — handoff a Gestion_Deuda",
     "turns": [
         {"user": "mi email es pedro.moroso@test.com quiero comprar rosas",
          "checks": ["deud|pago|pendiente|equipo|persona|gestion|saldo|email|verific"]},
     ],
     "not_expected": []},

    {"id": "TC-DEVOLUCION-01", "type": "EDGE", "group": "G6",
     "name": "Solicitud de devolucion — out-of-scope, deriva a Handoff",
     "turns": [
         {"user": "quiero devolver mi pedido",
          "checks": ["devolucion|equipo|persona|humano|reclamacion|email|correo|contacto|gestion"]},
     ],
     "not_expected": ["claro, te devuelvo|procesado"]},

    {"id": "TC-SIGNOS-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Input solo signos de puntuacion — robustez",
     "turns": [
         {"user": "???",
          "checks": ["entend|aclar|pregunta|ayudar|claro|repite|escribe|cuent"]},
     ],
     "not_expected": []},

    {"id": "TC-INSULTO-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Lexico abusivo — agente mantiene tono profesional, no repite",
     "turns": [
         {"user": "esto es una mierda, que porqueria",
          "checks": ["disculp|lament|entend|equipo|persona|propong|reformul|ayudar"]},
     ],
     "not_expected": ["mierda|porqueria"]},

    {"id": "TC-IMPOSIBLE-01", "type": "EDGE", "group": "COMPRA-ZG",
     "name": "Peticion fuera de scope — descuento del 50%",
     "turns": [
         {"user": "hacedme un descuento del 50%",
          "checks": ["no puedo|disculp|equipo|persona|precio|sin descuento|venta|cliente|comercial|aplicar|no tenemos|ayudar"]},
     ],
     "not_expected": ["50%.{0,30}aplicado|claro, descuento"]},
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


def detect_intent(token, session_id, text, session_params=None):
    url = f"{BASE}/{AGENT}/environments/-/sessions/{session_id}:detectIntent"
    body = {"queryInput": {"text": {"text": text}, "languageCode": "es"}}
    if session_params:
        fields = {k: {"stringValue": str(v)} for k, v in session_params.items()}
        body["queryParams"] = {"parameters": {"fields": fields}}
    time.sleep(1.5)  # Throttle: LLM quota limit in europe-west1
    current_token = token
    for attempt in range(3):
        try:
            headers = {"Authorization": f"Bearer {current_token}", "Content-Type": "application/json", "x-goog-user-project": PROJECT}
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            # Token expirado — refrescar y reintentar
            if resp.status_code == 401:
                current_token = get_token()
                continue
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
    trace = {}  # info extra de la API (playbook, actions, intent, etc.) — US-QA-09 trace capture
    if "error" in result:
        return f"ERROR: {result['error']}", "error", {}, {}
    qr = result.get("queryResult", {})
    for msg in qr.get("responseMessages", []):
        if "text" in msg:
            texts.extend(msg["text"].get("text", []))
    info = qr.get("currentPlaybook", "")
    if info:
        playbook = info.split("/")[-1] if "/" in info else info
    params = qr.get("parameters", {})
    # Capturar trace: playbook actual, intent matched, examples/tools si la API los expone
    trace["currentPlaybook"] = playbook
    if "match" in qr:
        m = qr["match"]
        if "intent" in m and isinstance(m["intent"], dict):
            trace["intent"] = m["intent"].get("displayName", "")
        if "matchType" in m:
            trace["matchType"] = m["matchType"]
        if "confidence" in m:
            trace["confidence"] = m["confidence"]
    # currentPage (en CX-Flows clásico; en Playbooks suele venir vacío pero por si acaso)
    if "currentPage" in qr:
        cp = qr["currentPage"]
        if isinstance(cp, dict):
            trace["currentPage"] = cp.get("displayName", "")
    # generativeInfo (Conversational Agents / Playbooks) — contiene el trace real de ejecución.
    # NOTA: executionSequence y actions en queryResult raíz NO se populan para agentes Playbook;
    # los datos están en queryResult.generativeInfo.actionTracingInfo.actions
    if "generativeInfo" in qr:
        gi = qr["generativeInfo"]
        trace["currentPlaybooks"] = gi.get("currentPlaybooks", [])
        ati = gi.get("actionTracingInfo", {})
        trace["actions"] = ati.get("actions", [])
        trace["conversationState"] = ati.get("conversationState", "")
    if "diagnosticInfo" in qr:
        trace["diagnosticInfo_keys"] = list(qr["diagnosticInfo"].keys()) if isinstance(qr["diagnosticInfo"], dict) else None
    return " ".join(texts), playbook, params, trace


def _split_check_detail(d):
    """Split 'OK: msg' or 'FAIL: msg' into (status, msg). Tolera prefijos de longitud variable."""
    parts = d.split(": ", 1)
    status = parts[0]
    msg = parts[1] if len(parts) > 1 else d
    return status, msg


def _check_msg_to_tokens(msg):
    """Extrae tokens legibles de un check msg como 'Agente debía decir [regex|tokens]'.
    Devuelve (prefix, tokens_list, raw_regex) o (None, None, None) si no hay regex."""
    m = re.match(r'^(.*?)\[(.+)\](.*)$', msg, re.DOTALL)
    if not m:
        return None, None, None
    prefix = m.group(1).strip()
    raw = m.group(2)
    parts = raw.split('|')
    tokens = []
    for p in parts:
        p = p.strip()
        p = re.sub(r'\.\{0,\d+\}', '…', p)
        p = re.sub(r'\.\{1,\d+\}', '…', p)
        p = re.sub(r'\.\*', '…', p)
        p = re.sub(r'[\\^$()?+]', '', p)
        p = p.strip('…').strip()
        if p:
            tokens.append(p)
    return prefix, tokens, raw


import unicodedata


def _strip_accents(s):
    """Elimina tildes/diacríticos de un string para matching case+accent-insensitive.
    'ocasión' → 'ocasion', 'cumpleaños' → 'cumpleanos', 'política' → 'politica'.

    Resuelve falsos negativos donde el agente responde con tilde y el regex del
    test no la incluye (ej. check 'ocasion' vs respuesta 'ocasión').
    """
    if not s:
        return s
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def check_turn(response_text, checks, not_expected):
    """Evalúa la respuesta del AGENTE contra checks positivos y negativos.

    Prefijos consistentes (los checks SIEMPRE evalúan al agente, nunca al usuario):
      - 'OK: Agente dijo [X]'           → regla positiva cumplida
      - 'FAIL: Agente debía decir [X]'  → regla positiva fallada
      - 'FAIL: Agente NO debía decir [X]' → regla negativa fallada

    Matching insensible a tildes: la respuesta y los patrones se normalizan con
    NFD antes de aplicar re.search. Garantiza que 'ocasion' matchea 'ocasión'.
    Los mensajes de detalles preservan el patrón ORIGINAL (con/sin tildes) para
    legibilidad en el HTML.
    """
    results = {"pass": True, "details": []}
    response_norm = _strip_accents(response_text)
    for check_str in checks:
        patterns = check_str.split("|")
        patterns_norm = [_strip_accents(p) for p in patterns]
        found = any(re.search(pn, response_norm, re.IGNORECASE) for pn in patterns_norm)
        if not found:
            results["pass"] = False
            results["details"].append(f"FAIL: Agente debía decir [{check_str}]")
        else:
            matched = [p for p, pn in zip(patterns, patterns_norm)
                       if re.search(pn, response_norm, re.IGNORECASE)]
            results["details"].append(f"OK: Agente dijo [{matched[0]}]")
    for neg in not_expected:
        neg_norm = _strip_accents(neg)
        if re.search(neg_norm, response_norm, re.IGNORECASE):
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
        # Inject session_params only on first turn (session start)
        sp = turn.get("session_params") if i == 0 else None
        result = detect_intent(token, session_id, user_text, session_params=sp)
        if result.get("is_quota_error"):
            has_quota_error = True
        response_text, playbook, params, trace = extract_response(result)
        checks = turn.get("checks", [])
        not_exp = test.get("not_expected", []) if i == 0 else []
        turn_check = check_turn(response_text, checks, not_exp)
        if not turn_check["pass"]:
            all_pass = False
        turn_results.append({
            "turn": i + 1, "user": user_text,
            "agent": response_text[:500], "playbook": playbook,
            "params": params, "checks": turn_check,
            "trace": trace,  # US-QA-09: capturar trace del API para análisis profundo
            "desc": turn.get("desc", ""),  # descripción en lenguaje natural del check
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


def _load_tc_analysis(tc_id, run_ts=None):
    """Lee qa/tc_analysis/{run_ts}/{tc_id}.md → {meta, turnos, recomendacion} o None.

    run_ts: timestamp compacto del run (ej: '20260525_1254'). Cuando se pasa,
    busca en la subcarpeta run-scoped. Si es None, busca en el directorio raíz
    (modo legado / compatibilidad).

    Secciones reconocidas en el MD:
      - Front-matter YAML (entre ---): meta (status, tipo, estimacion...)
      - ## T1, ## T2...: análisis técnico por turno (va en columna derecha)
      - ## Recomendación (o Recomendacion sin tilde): acción a tomar (banda inferior)
    """
    if run_ts:
        path = TC_ANALYSIS_DIR / run_ts / f"{tc_id}.md"
    else:
        path = TC_ANALYSIS_DIR / f"{tc_id}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    # Extraer sección Recomendación (acepta con y sin tilde)
    rec_match = re.search(r"^##\s+Recomendaci[oó]n\s*$(.+?)(?=^##\s|\Z)", body, flags=re.MULTILINE | re.DOTALL)
    recomendacion = rec_match.group(1).strip() if rec_match else ""
    body_sin_rec = re.sub(r"^##\s+Recomendaci[oó]n\s*$.*?(?=^##\s|\Z)", "", body, flags=re.MULTILINE | re.DOTALL)
    turnos = {}
    parts = re.split(r"^##\s+T(\d+)\s*$", body_sin_rec, flags=re.MULTILINE)
    if len(parts) > 1:
        for i in range(1, len(parts), 2):
            try:
                turnos[int(parts[i])] = parts[i + 1].strip()
            except (ValueError, IndexError):
                pass
    return {"meta": meta, "turnos": turnos, "body": body, "recomendacion": recomendacion}


def _extract_flow_table(turno_md):
    """Extrae las filas de la tabla 'Turnos vs Problemas detectados' del análisis manual.

    Devuelve lista de dicts [{step, problem}] o None si no hay tabla.
    Reconoce tablas Markdown con headers que contienen 'Quién'+'Acción'+'Problema'.
    """
    if not turno_md:
        return None
    # Buscar tabla con headers Quién / Acción / Problema
    lines = turno_md.split("\n")
    table_start = None
    for i, line in enumerate(lines):
        norm = _strip_accents(line.lower())
        if "|" in line and "quien" in norm and "accion" in norm and "problema" in norm:
            table_start = i
            break
    if table_start is None:
        return None
    # Header line, separator line, then data rows
    rows = []
    for line in lines[table_start + 2:]:
        line = line.strip()
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        # cells: [#, Quién, Acción/Texto, Problema detectado]
        num, quien, accion, problema = cells[0], cells[1], cells[2], cells[3]
        step = f"<strong>{quien}</strong>: {accion}" if quien else accion
        if num and num != "-":
            step = f'<span style="color:#666;margin-right:6px">{num}</span>' + step
        rows.append({"step": step, "problem": problema})
    return rows if rows else None


def _md_inline_to_html(text):
    """Conversión inline de Markdown a HTML (negrita, cursiva, code) para celdas de tabla."""
    if not text:
        return ""
    # **bold**
    text = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", text)
    # *italic* o _italic_
    text = re.sub(r"(?<!\*)\*([^\*]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
    # `code`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


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


# Mapeo emoji → (clase CSS, color hex). Usado por _postprocess_capa_blocks.
_CAPA_EMOJI_MAP = {
    "🔴": "rojo",
    "🟢": "verde",
    "🟡": "amarillo",
    "⚪": "na",
}


_ESTADO_BADGE_MAP = {
    "verificada": ("verificada", "✓ verificada"),
    "supuesta":   ("supuesta",   "? supuesta"),
    "N/A":        ("na",         "N/A"),
}


def _postprocess_capa_blocks(html):
    """Detecta bloques de capa en el HTML renderizado del análisis ('Causa raíz')
    y los envuelve en divs estructurados con header (emoji + título + badge),
    fuente debajo, y descripción debajo.

    Formato NUEVO esperado del MD:
      🔴 N. **Capa Nombre** [verificada]

      `Read X`

      Descripción del problema...

      ⚪ N. **Capa Nombre** [N/A]

      Razón breve.

    Las capas en formato VIEJO (sin emoji al inicio del párrafo) se dejan intactas.
    """
    if not html:
        return html

    # Patrón VERBOSE: <p>EMOJI N. <strong>Capa Nombre</strong> [estado]</p>
    # Seguido de uno o varios <p>...</p> con fuente y descripción aparte.
    capa_line_re = re.compile(
        r'<p>(🔴|🟢|🟡|⚪)\s+(\d+)\.\s+<strong>([^<]+?)</strong>\s*\[(verificada|supuesta|N/A)\]'
        r'(?:\s*[·•∙]\s*(?P<fuente_inline>.+?))?\s*</p>'
    )
    # Patrón COMPACTO: <p>EMOJI N. <strong>Capa Nombre</strong> [SEPARADOR] ESTADO [SEPARADOR] — descripción inline</p>
    # Todo en un solo <p>. Acepta tanto "· estado —" como "[estado] —".
    capa_line_compact_re = re.compile(
        r'<p>(🔴|🟢|🟡|⚪)\s+(\d+)\.\s+<strong>([^<]+?)</strong>\s*'
        r'(?:[·•∙]\s*(?P<estado1>verificada|supuesta|N/A)|\[(?P<estado2>verificada|supuesta|N/A)\])\s*'
        r'[—\-–]\s*(?P<desc>.+?)\s*</p>',
        re.DOTALL
    )
    # Patrón ALT: <p><strong>Capa N — Nombre:</strong> EMOJI [estado · fuente] [descripción opcional]</p>
    # Variante donde el sub-agente puso emoji DESPUÉS del título en lugar de antes.
    # La descripción es opcional (puede estar vacía o en un <p> siguiente, que consumimos
    # con consume_following_blocks).
    capa_line_alt_re = re.compile(
        r'<p><strong>Capa\s+(\d+)\s*[—\-–]\s*([^<]+?):</strong>\s*'
        r'(🔴|🟢|🟡|⚪)\s*'
        r'(?:\[(?P<estado>verificada|supuesta|N/A)[^\]]*\]|(?P<estado2>N/A))\s*'
        r'(?P<desc>.*?)</p>',
        re.DOTALL
    )

    def consume_following_blocks(full_html, start_pos):
        """Consume bloques HTML (<p>, <table>, <pre>, <ul>, <ol>, <blockquote>)
        después de una cabecera de capa, hasta encontrar otra cabecera o salir.
        Devuelve (fuente_html, desc_html, end_pos).
        - fuente_html: si el primer <p> es SOLO <code>...</code>, ese es la fuente
        - desc_html: el resto del contenido (párrafos, tablas, listas, etc.) bajo la capa
        """
        fuente = ""
        desc_parts = []
        pos = start_pos
        # Tags consumibles como contenido de la capa (en orden de probabilidad)
        block_re = re.compile(
            r'\s*(<p>(.*?)</p>|<table[^>]*>.*?</table>|<pre>.*?</pre>|<ul>.*?</ul>|<ol>.*?</ol>|<blockquote>.*?</blockquote>)',
            re.DOTALL
        )
        # Detectar si el siguiente <p> es otra cabecera de capa (verbose/compact/alt)
        header_marker_re = re.compile(
            r'^(🔴|🟢|🟡|⚪)\s+\d+\.\s+<strong>'      # verbose/compact: emoji al inicio
            r'|^<strong>Capa\s+\d+\s*[—\-–]'          # alt: <strong>Capa N — Nombre:</strong>
        )
        p_tag_re = re.compile(r'\s*<p>(.*?)</p>', re.DOTALL)

        first = True
        while True:
            # Primero comprobamos si el siguiente bloque es un <p> con cabecera de capa
            mp = p_tag_re.match(full_html, pos)
            if mp and header_marker_re.match(mp.group(1)):
                break
            m = block_re.match(full_html, pos)
            if not m:
                break
            block_html = m.group(1).strip()
            # Si el primer bloque es <p><code>...</code></p>, es la fuente
            if first and block_html.startswith('<p>') and block_html.endswith('</p>'):
                inner = block_html[3:-4].strip()
                if re.fullmatch(r'<code>[^<]+</code>', inner):
                    fuente = inner
                    pos = m.end()
                    first = False
                    continue
            # Si es <p>...</p>, lo wrapeamos con clase capa-desc-p (mantiene estilos)
            if block_html.startswith('<p>') and block_html.endswith('</p>'):
                inner = block_html[3:-4].strip()
                desc_parts.append(f'<p class="capa-desc-p">{inner}</p>')
            else:
                # Tabla / pre / lista / blockquote: lo incluimos tal cual
                desc_parts.append(block_html)
            pos = m.end()
            first = False

        desc_html = "".join(desc_parts)
        return fuente, desc_html, pos

    # Recolectar todos los matches (verbose, compacto, alt), ordenados por posición.
    all_matches = []
    for m in capa_line_re.finditer(html):
        all_matches.append(("verbose", m))
    for m in capa_line_compact_re.finditer(html):
        all_matches.append(("compact", m))
    for m in capa_line_alt_re.finditer(html):
        all_matches.append(("alt", m))
    all_matches.sort(key=lambda x: x[1].start())

    result = []
    last_pos = 0
    for kind, m in all_matches:
        if m.start() < last_pos:
            continue
        result.append(html[last_pos:m.start()])

        if kind == "verbose":
            emoji = m.group(1)
            num = m.group(2)
            nombre = m.group(3).strip()
            estado = m.group(4)
        elif kind == "compact":
            emoji = m.group(1)
            num = m.group(2)
            nombre = m.group(3).strip()
            estado = m.groupdict().get("estado1") or m.groupdict().get("estado2") or "N/A"
        else:  # kind == "alt": <strong>Capa N — Nombre:</strong> EMOJI [estado] ...
            num = m.group(1)
            nombre = "Capa " + m.group(2).strip()
            emoji = m.group(3)
            estado = m.groupdict().get("estado") or m.groupdict().get("estado2") or "N/A"
        color = _CAPA_EMOJI_MAP.get(emoji, "na")
        badge_cls, badge_txt = _ESTADO_BADGE_MAP.get(estado, ("na", estado))

        if kind == "verbose":
            fuente_html, desc_html, end_pos = consume_following_blocks(html, m.end())
            # Si la capa traía la fuente inline (· `Read X` en la misma línea), usarla
            inline_f = m.groupdict().get("fuente_inline")
            if inline_f and not fuente_html:
                fuente_html = inline_f
        else:
            fuente_html = ""
            desc_inline = (m.groupdict().get("desc") or "").strip()
            # Limpiar separador inicial residual
            desc_inline = re.sub(r'^\s*[—\-–]\s*', '', desc_inline)
            desc_html = f'<p class="capa-desc-p">{desc_inline}</p>' if desc_inline else ""
            end_pos = m.end()
            # Si es alt, consumir también los siguientes <p>/<table>/etc como descripción adicional
            if kind == "alt":
                extra_fuente, extra_desc, end_pos = consume_following_blocks(html, m.end())
                if extra_desc:
                    desc_html += extra_desc

        block = (
            f'<div class="capa-block capa-{color}">'
            f'<div class="capa-header">'
            f'<span class="capa-emoji">{emoji}</span>'
            f'<span class="capa-titulo"><strong>{num}. {nombre}</strong></span>'
            f'<span class="capa-badge capa-badge-{badge_cls}">{badge_txt}</span>'
            f'</div>'
        )
        if fuente_html:
            block += f'<div class="capa-fuente">{fuente_html}</div>'
        if desc_html:
            block += f'<div class="capa-desc">{desc_html}</div>'
        block += '</div>'

        result.append(block)
        last_pos = end_pos

    result.append(html[last_pos:])
    html_out = "".join(result)

    # Recalcular "Resumen visual" desde las capas realmente envueltas en el HTML.
    # Evita que el texto del MD (escrito por el sub-agente) muestre conteos
    # incorrectos cuando éste se equivoca o cuando alguna capa usa un formato
    # exótico que no se envuelve.
    cnt_rojo = len(re.findall(r'class="capa-block capa-rojo"', html_out))
    cnt_verde = len(re.findall(r'class="capa-block capa-verde"', html_out))
    cnt_amarillo = len(re.findall(r'class="capa-block capa-amarillo"', html_out))
    cnt_na = len(re.findall(r'class="capa-block capa-na"', html_out))
    if cnt_rojo + cnt_verde + cnt_amarillo + cnt_na > 0:
        real_resumen = (
            f'{cnt_rojo} 🔴 problema · {cnt_verde} 🟢 ok · '
            f'{cnt_amarillo} 🟡 supuesta · {cnt_na} ⚪ N/A'
        )
        # Reemplazar la línea "Resumen visual: ..." declarada por el sub-agente
        # con el conteo real. Aceptamos varias formas de separador y emoji order.
        html_out = re.sub(
            r'(<p[^>]*><strong>Resumen visual:</strong>)\s*[^<]*?(</p>)',
            lambda m: f'{m.group(1)} {real_resumen}{m.group(2)}',
            html_out,
            count=1,
        )
    return html_out


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


def _compute_metodologia_kpis(results):
    """Calcula KPIs de QA desde los results para la modal Metodología.

    Devuelve dict con: flakiness, orquestador, compra, cobertura_grupos, cobertura_modos.
    """
    total = len(results)
    # 1. FLAKINESS
    inestables = [r for r in results if r["status"] == "INESTABLE"]
    flak_pct = round(100 * len(inestables) / total, 1) if total else 0
    flak_tcs = [r["id"] for r in inestables]
    # 2. ORQUESTADOR — % TCs donde grupo_intent observado coincide con grupo declarado del TC
    orq_total = 0
    orq_ok = 0
    orq_errors = []
    for r in results:
        if not r["runs"]:
            continue
        # Tomar primer turno del primer run (T1 es donde el Orquestador clasifica)
        try:
            t1 = r["runs"][0]["turns"][0]
        except (IndexError, KeyError):
            continue
        params = t1.get("params") or {}
        gi_observed = params.get("grupo_intent", "")
        gi_expected = r.get("group", "")
        if not gi_expected:
            continue
        orq_total += 1
        # Match exacto O el observado contiene el esperado (G5 puede ser COMPRA-INV/ZG en sub-estados)
        if gi_observed == gi_expected or gi_expected in gi_observed:
            orq_ok += 1
        else:
            orq_errors.append({"tc": r["id"], "expected": gi_expected, "observed": gi_observed or "(vacío)"})
    orq_pct = round(100 * orq_ok / orq_total, 1) if orq_total else 0
    # 3. COMPRA — slot-filling rate (% turnos con cada slot)
    turnos_total = 0
    n_producto = 0
    n_ocasion = 0
    n_modo = 0
    for r in results:
        for run in r["runs"]:
            for turn in run["turns"]:
                turnos_total += 1
                params = turn.get("params") or {}
                if params.get("producto"):
                    n_producto += 1
                if params.get("ocasion_detectada"):
                    n_ocasion += 1
                if params.get("modo_tono"):
                    n_modo += 1
    pct_producto = round(100 * n_producto / turnos_total, 1) if turnos_total else 0
    pct_ocasion = round(100 * n_ocasion / turnos_total, 1) if turnos_total else 0
    pct_modo = round(100 * n_modo / turnos_total, 1) if turnos_total else 0
    # 4. COBERTURA GRUPOS — qué grupos del Orquestador tienen TCs
    grupos_esperados = ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    grupos_nombre = {
        "G1": "Saludo", "G2": "Info negocio", "G3": "Consulta",
        "G4": "Gestión pedido", "G5": "Compra", "G6": "Queja", "G7": "Registro"
    }
    grupos_count = {g: 0 for g in grupos_esperados}
    for r in results:
        grupo = r.get("group", "")
        # Mapear sub-grupos al principal (COMPRA-INV/ZG → G5, G7-ERR/CANCEL/etc → G7)
        if grupo.startswith("G5") or grupo.startswith("COMPRA"):
            grupos_count["G5"] += 1
        elif grupo.startswith("G7"):
            grupos_count["G7"] += 1
        elif grupo in grupos_count:
            grupos_count[grupo] += 1
    cobertura_grupos = []
    for g in grupos_esperados:
        c = grupos_count[g]
        status = "ok" if c >= 3 else ("low" if c >= 1 else "missing")
        cobertura_grupos.append({"grupo": g, "nombre": grupos_nombre[g], "count": c, "status": status})
    grupos_ok = sum(1 for g in cobertura_grupos if g["status"] == "ok")
    pct_grupos = round(100 * grupos_ok / len(grupos_esperados), 0)
    # 5. COBERTURA MODOS DE TONO — qué modos se han usado
    modos_observados = {}
    for r in results:
        for run in r["runs"]:
            for turn in run["turns"]:
                params = turn.get("params") or {}
                modo = params.get("modo_tono", "")
                if modo:
                    modos_observados[modo] = modos_observados.get(modo, 0) + 1
    # Modos esperados según petal_cx_orchestrator.yaml líneas 157, 167-170, 192-195
    # Solo hay 3 modos definidos en el sistema: estandar (default), solemne (funeral), corporativo (oficina/empresa)
    modos_esperados = ["estandar", "solemne", "corporativo"]
    cobertura_modos = []
    for m in modos_esperados:
        c = modos_observados.get(m, 0)
        status = "ok" if c >= 1 else "missing"
        cobertura_modos.append({"modo": m, "count": c, "status": status})
    # Modos NO esperados pero observados (info útil)
    for m in modos_observados:
        if m not in modos_esperados:
            cobertura_modos.append({"modo": m, "count": modos_observados[m], "status": "extra"})
    modos_ok = sum(1 for m in cobertura_modos if m["status"] == "ok")
    pct_modos = round(100 * modos_ok / len(modos_esperados), 0)
    return {
        "flakiness": {"pct": flak_pct, "count": len(inestables), "total": total, "tcs": flak_tcs},
        "orquestador": {"pct": orq_pct, "ok": orq_ok, "total": orq_total, "errors": orq_errors[:5]},
        "compra": {"producto": pct_producto, "ocasion": pct_ocasion, "modo_tono": pct_modo, "turnos": turnos_total},
        "cobertura_grupos": {"items": cobertura_grupos, "pct": pct_grupos, "ok": grupos_ok, "total": len(grupos_esperados)},
        "cobertura_modos": {"items": cobertura_modos, "pct": pct_modos, "ok": modos_ok, "total": len(modos_esperados)},
    }


def _load_previous_meta(out_dir=None):
    """Lee el meta.json del run anterior (penúltimo qa_*.meta.json) para cálculo de regresión.

    Devuelve dict con métricas previas o None si no hay run anterior.
    """
    try:
        from pathlib import Path
        if out_dir is None:
            out_dir = Path.home() / "petal-qa"
        metas = sorted(out_dir.glob("qa_*.meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(metas) < 2:
            return None  # solo hay 1 (el actual) o ninguno
        prev = json.load(open(metas[1]))  # penúltimo
        return prev
    except Exception:
        return None


def _render_patterns_html(md):
    """Renders _patterns_*.md with the sketch-based visual structure.

      RESUMEN — 3 stat bullets
      Per-pattern card (2-col):
        header: pattern name (no ROI in header)
        left:  TCs afectados list
        right: ROI clickable (tooltip) · CAUSA rows · RECOMENDACIÓN
      TCS SIN PATRÓN — same 2-col card: left=TC list, right=CAUSA DE NO PATRÓN
      RESUMEN EJECUTIVO
    """
    def _esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _inline(s):
        return _md_inline(_esc(s))

    def _strip_dots(s):
        return re.sub(r"[🔴🟢🟡⚪✅✔]\s*", "", s).strip()

    out = []

    # ── Parse TC list ─────────────────────────────────────────────────────
    tc_m = re.search(r"TCs analizados en este batch:\s*(.+)", md)
    tc_list = [t.strip() for t in tc_m.group(1).split(",")] if tc_m else []

    # ── Parse ## sections ─────────────────────────────────────────────────
    parts = re.split(r"\n## ", "\n" + md.strip())
    pattern_secs, no_pat_sec, summary_sec = [], None, None
    for part in parts[1:]:
        lines = part.split("\n")
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        t_low = title.lower()
        if "patr" in t_low and "sin" not in t_low:
            pattern_secs.append((title, body))
        elif "sin patr" in t_low:
            no_pat_sec = (title, body)
        elif "resumen" in t_low:
            summary_sec = (title, body)

    # ── Count TCs with pattern ────────────────────────────────────────────
    tcs_con_patron = set()
    for _, body in pattern_secs:
        tcs_m_c = re.search(r"\*\*TCs:\*\*\s*(.+)", body)
        if tcs_m_c:
            for tc in re.findall(r"TC-\S+", tcs_m_c.group(1)):
                tcs_con_patron.add(tc)

    # ── RESUMEN (stats block) ─────────────────────────────────────────────
    out.append('<div class="pat-resumen">')
    out.append('<div class="pat-resumen-title">RESUMEN</div>')
    out.append(f'<div class="pat-resumen-stat">• Tests analizados en este batch: <strong>{len(tc_list)}</strong></div>')
    out.append(f'<div class="pat-resumen-stat">• TCs con patrón: <strong>{len(tcs_con_patron)}</strong></div>')
    out.append(f'<div class="pat-resumen-stat">• Patrones: <strong>{len(pattern_secs)}</strong></div>')
    out.append('</div>')

    # ── Pattern cards ─────────────────────────────────────────────────────
    if not pattern_secs:
        out.append('<p class="pat-empty">No hay patrón detectado</p>')

    for pat_title, pat_body in pattern_secs:
        # ROI value + tooltip (from ROI table row)
        roi_val_m = re.search(r"(\d+)\s*TCs/h", pat_body)
        roi_val = roi_val_m.group(1) if roi_val_m else ""
        roi_tip = ""
        roi_table_m = re.search(
            r"### ROI del patrón\n\s*\|[^\n]+\n\|[-| ]+\n(\|[^\n]+)", pat_body
        )
        if roi_table_m:
            cells = [c.strip() for c in roi_table_m.group(1).strip("|").split("|")]
            if len(cells) >= 3:
                tcs_res = re.sub(r"\*\*", "", cells[1]).strip()
                esfuerzo = re.sub(r"\*\*", "", cells[2]).strip()
                roi_tip = f"{tcs_res} en {esfuerzo}"

        # TCs list
        tcs_m = re.search(r"\*\*TCs:\*\*\s*(.+)", pat_body)
        tc_items = re.findall(r"TC-[\w-]+", tcs_m.group(1)) if tcs_m else []

        # Causa rows (from reason table)
        causa_rows = []
        reason_m = re.search(r"\| Razón[^\n]*\n\|[-| ]+\n((?:\|[^\n]+\n?)+)", pat_body)
        if reason_m:
            for row in reason_m.group(1).strip().split("\n"):
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) >= 3:
                    label = re.sub(r"\*\*", "", cells[0]).strip()
                    detalle = _strip_dots(cells[2])
                    causa_rows.append((label, detalle))

        # Recomendación
        rec_m = re.search(r"\*\*Recomendación de secuencia:\*\*\s*(.+)", pat_body)
        rec_text = rec_m.group(1).strip() if rec_m else ""

        # ── Card ──────────────────────────────────────────────────────────
        out.append('<div class="pat-card">')

        # Header: only title (ROI moved to right column)
        out.append('<div class="pat-card-hdr">')
        out.append(f'<div class="pat-card-title">{_inline(pat_title)}</div>')
        out.append('</div>')

        # Body: 2 columns
        out.append('<div class="pat-card-body">')

        # Left — TCs afectados
        out.append('<div class="pat-card-left">')
        out.append('<div class="pat-col-lbl">TCs afectados</div>')
        for tc in tc_items:
            out.append(f'<div class="pat-tc-item">{_esc(tc)}</div>')
        out.append('</div>')

        # Right — ROI (clickable) · CAUSA · RECOMENDACIÓN
        out.append('<div class="pat-card-right">')
        if roi_val:
            tcs_part = roi_tip.split(" en ")[0].strip() if " en " in roi_tip else roi_tip
            esf_part = roi_tip.split(" en ")[1].strip() if " en " in roi_tip else ""
            out.append(
                f'<div class="pat-roi-btn"'
                f' data-roi-val="{_esc(roi_val)}"'
                f' data-roi-tcs="{_esc(tcs_part)}"'
                f' data-roi-esf="{_esc(esf_part)}">'
                f'ROI: {_esc(roi_val)} TCs/h'
                f'<span class="pat-roi-q" onclick="openRoiModal(this.parentElement)">?</span>'
                f'</div>'
            )
        if causa_rows:
            out.append('<div class="pat-col-lbl">CAUSA</div>')
            for label, detalle in causa_rows:
                out.append(
                    f'<div class="pat-causa-row">'
                    f'<span class="pat-causa-lbl">{_esc(label)}:</span> {_inline(detalle)}'
                    f'</div>'
                )
        if rec_text:
            out.append('<div class="pat-col-lbl pat-rec-lbl">RECOMENDACIÓN</div>')
            out.append(f'<div class="pat-rec-text">{_inline(rec_text)}</div>')
        out.append('</div>')  # right

        out.append('</div>')  # body
        out.append('</div>')  # card

    # ── TCS SIN PATRÓN — same 2-col card structure ────────────────────────
    if no_pat_sec:
        # Parse the table: | TC | Por qué no forma patrón |
        no_pat_rows = []
        tbl_m = re.search(r"\| TC[^\n]*\n\|[-| ]+\n((?:\|[^\n]+\n?)+)", no_pat_sec[1])
        if tbl_m:
            for row in tbl_m.group(1).strip().split("\n"):
                cells = [c.strip() for c in row.strip("|").split("|")]
                if len(cells) >= 2:
                    tc_id = re.sub(r"\*\*", "", cells[0]).strip()
                    razon = cells[1].strip()
                    if tc_id:
                        no_pat_rows.append((tc_id, razon))

        if no_pat_rows:
            out.append('<div class="pat-card">')
            out.append('<div class="pat-card-hdr">')
            out.append('<div class="pat-card-title">TCs sin patrón</div>')
            out.append('</div>')
            out.append('<div class="pat-card-body">')
            # Left — TC list
            out.append('<div class="pat-card-left">')
            out.append('<div class="pat-col-lbl">TCs</div>')
            for tc_id, _ in no_pat_rows:
                out.append(f'<div class="pat-tc-item pat-tc-nopattern">{_esc(tc_id)}</div>')
            out.append('</div>')
            # Right — Causa de no patrón
            out.append('<div class="pat-card-right">')
            out.append('<div class="pat-col-lbl">CAUSA DE NO PATRÓN</div>')
            for tc_id, razon in no_pat_rows:
                out.append(
                    f'<div class="pat-causa-row">'
                    f'<span class="pat-causa-lbl">{_esc(tc_id)}:</span> {_inline(razon)}'
                    f'</div>'
                )
            out.append('</div>')
            out.append('</div>')  # body
            out.append('</div>')  # card
        else:
            out.append('<div class="pat-section">')
            out.append('<div class="pat-sh">TCS SIN PATRÓN</div>')
            out.append(_md_to_html(no_pat_sec[1]))
            out.append('</div>')

    # ── ORDEN DE EJECUCIÓN (WIP) ──────────────────────────────────────────
    if summary_sec:
        out.append('<div class="pat-section">')
        out.append('<div class="pat-sh">ORDEN DE EJECUCIÓN</div>')
        out.append('<div class="pat-wip">⚙️ <em>Work in progress</em> — la lógica de priorización (patrón vs. TC individual primero) se implementará en una próxima versión del skill.</div>')
        out.append('</div>')

    # ── ROI modal (position:fixed, funciona desde cualquier lugar del DOM) ─
    out.append(
        '<div id="roi-modal-overlay" class="roi-modal-overlay" onclick="closeRoiModal()">'
        '<div class="roi-modal" onclick="event.stopPropagation()">'
        '<div class="roi-modal-hdr">'
        '<span class="roi-modal-ttl">ROI — Tasa de resolución</span>'
        '<span class="roi-modal-x" onclick="closeRoiModal()">×</span>'
        '</div>'
        '<div class="roi-modal-body" id="roi-modal-body"></div>'
        '</div>'
        '</div>'
    )

    return "\n".join(out)


def generate_html(results, ts, txt_file, logs_dir_name=None, ts_compact_override=None):
    """
    Genera el HTML del dashboard.

    Args:
        results: lista de TC results
        ts: timestamp (puede venir como display "YYYY-MM-DD HH:MM" o compacto "YYYYMMDD_HHMMSS")
        txt_file: archivo txt asociado (legacy)
        logs_dir_name: nombre de la carpeta de logs (para botones JSON)
        ts_compact_override: si se pasa, se usa como _ts_compact en lugar de derivarlo del ts.
            Útil cuando ts viene formateado para display (sin segundos) pero se necesita
            el ts compacto original para localizar los MDs en qa/tc_analysis/{ts_compact}/.
    """
    # Lookup: (tc_id, turn_number) → desc en lenguaje natural
    _tc_turn_desc = {}
    for _tc in TESTS:
        for _ti, _turn in enumerate(_tc.get("turns", []), 1):
            if _turn.get("desc"):
                _tc_turn_desc[(_tc["id"], _ti)] = _turn["desc"]

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
    # [v1.1 Cambio F] Cargar bloque de patrones cruzados si existe
    # Los análisis y patrones son run-scoped: se guardan en qa/tc_analysis/{ts_compact}/
    # El skill escribe _patterns_<TS>.md en esa subcarpeta al ejecutar el análisis.
    import glob as _glob
    # ts_compact: "20260525_1254" — usado como nombre de subcarpeta run-scoped
    # Si se pasa override (desde regenerate_html.py), se usa directamente para
    # preservar la precisión de segundos. Si no, se deriva del ts (que puede venir
    # como display "YYYY-MM-DD HH:MM" sin segundos).
    if ts_compact_override:
        _ts_compact = ts_compact_override
    else:
        _ts_compact = ts.replace("-", "").replace(" ", "_").replace(":", "")
    patterns_block = ""
    has_legacy_analyses = False
    try:
        _analysis_run_dir = os.path.join(os.path.dirname(__file__), "tc_analysis", _ts_compact)
        # Buscar _patterns_*.md dentro de la subcarpeta del run
        _patterns_matches = _glob.glob(os.path.join(_analysis_run_dir, "_patterns_*.md"))
        if _patterns_matches:
            with open(sorted(_patterns_matches)[-1], "r", encoding="utf-8") as _pf:
                _patterns_md = _pf.read()
            _patterns_html = _render_patterns_html(_patterns_md)
            # Extraer stats para el header colapsable
            import re as _re2
            _n_pat = len(_re2.findall(r'^## Patrón', _patterns_md, _re2.MULTILINE))
            _roi_m = _re2.search(r'(\d+)\s*TCs/h', _patterns_md)
            _roi_str = f"ROI {_roi_m.group(1)} TCs/h" if _roi_m else ""
            _ntcs_m = _re2.search(r'\|\s*TC-\S+\s*\([^)]+\)\s*\|\s*(\d+)\s*TCs', _patterns_md)
            _n_tcs = _ntcs_m.group(1) if _ntcs_m else ""
            _stats_parts = [f"{_n_pat} patrón{'es' if _n_pat != 1 else ''} detectado{'s' if _n_pat != 1 else ''}"]
            if _n_tcs: _stats_parts.append(f"{_n_tcs} TCs afectados")
            if _roi_str: _stats_parts.append(_roi_str)
            _header_stats = " · ".join(_stats_parts)
            patterns_block = (
                f'<div class="patterns-block">'
                f'<div class="patterns-th" onclick="togglePatterns()">'
                f'<span class="patterns-icon">⚠️</span>'
                f'<span class="patterns-title">Patrones cruzados</span>'
                f'<span class="patterns-stats">{_header_stats}</span>'
                f'<span class="patterns-arrow">▶</span>'
                f'</div>'
                f'<div class="patterns-body">{_patterns_html}</div>'
                f'</div>'
            )
        # Detectar análisis con formato viejo (7 capas v1.0) para mostrar la nota solo si aplica
        _all_analyses = _glob.glob(os.path.join(_analysis_run_dir, "TC-*.md"))
        for _a in _all_analyses:
            try:
                with open(_a, "r", encoding="utf-8") as _af:
                    _content = _af.read()
                # Heurística: formato viejo usa "Capa Playbook" (v1.0); nuevo usa "Capa Comportamiento" (v1.1)
                if "Capa Playbook" in _content and "Capa Comportamiento" not in _content:
                    has_legacy_analyses = True
                    break
            except Exception:
                continue
    except Exception:
        patterns_block = ""
        has_legacy_analyses = False
    # Nota sobre formato de capas, condicional a que existan análisis legacy
    legacy_note = ('<p class="layer-format-note" style="font-size:11px;color:#888;margin-bottom:12px">'
                   'Algunos análisis usan formato de 7 capas (v1.0). Los nuevos usan 9 capas (v1.1).'
                   '</p>') if has_legacy_analyses else ""
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
.dl-disabled{{background:#1a1a1a !important;color:#666 !important;border-color:#374151 !important;cursor:not-allowed !important}}
.dl-disabled:hover{{background:#1a1a1a !important}}
.optimize-panel{{background:#141414;border:1px solid #222;border-radius:8px;padding:16px;margin-bottom:16px}}
.optimize-panel.hidden{{display:none}}
.optimize-panel-header{{display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap}}
.optimize-panel-title{{color:#c8f060;font-size:12px;font-family:'DM Mono',monospace;letter-spacing:.3px;flex:1}}
.optimize-panel-header .dl{{margin-bottom:0}}
.run-feedback{{color:#c8f060;font-size:11px;font-family:'DM Mono',monospace;opacity:0;transition:opacity .2s}}
.run-feedback.visible{{opacity:1}}
.optimize-table{{width:100%;border-collapse:collapse;font-size:11px}}
.optimize-table th{{background:#1a1a1a;color:#c8f060;font-weight:600;padding:8px 10px;text-align:left;border-bottom:1px solid #222;text-transform:uppercase;letter-spacing:.3px;font-size:10px}}
.optimize-table td{{padding:8px 10px;border-bottom:1px solid #1a1a1a;color:#ddd;vertical-align:top}}
.optimize-table tr:hover{{background:#1a1a1a}}
.optimize-table td:first-child{{width:30px;text-align:center}}
.optimize-table td:nth-child(2){{font-family:'DM Mono',monospace;color:#c8f060;font-size:11px;white-space:nowrap}}
.optimize-table td:nth-child(4),.optimize-table td:nth-child(5){{color:#aaa;font-size:10px;line-height:1.4}}
.optimize-table input[type=checkbox]{{accent-color:#c8f060;cursor:pointer;width:14px;height:14px}}
.filter-bar{{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}}
.filter-row{{display:flex;gap:6px;flex-wrap:wrap;align-items:center;padding:6px 0;border-bottom:1px solid #1a1a1a}}
.filter-row:last-child{{border-bottom:none}}
.filter-label{{font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:#666;font-weight:700;min-width:80px;font-family:'DM Mono',monospace}}
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
/* Tag de tipo en header del TC (sustituye al veredicto) */
.tipo-tag{{font-size:10px;padding:2px 8px;border-radius:3px;background:#f9731622;color:#f97316;font-family:'DM Mono',monospace;font-weight:600}}
/* Banda de recomendación al final del TC */
/* Banda de DIAGNÓSTICO — mismo ancho/letra que .recomendacion, color azul */
.diagnostico,.dimensionamiento{{margin:14px 0 4px;padding:14px 16px;background:#0c172f;border:1px solid #1e3a5f;border-left:4px solid #3b82f6;border-radius:6px}}
.dimensionamiento{{margin-top:8px;background:#0a1322}}
.diagnostico.pendiente{{background:#1a1a1a;border-color:#444;border-left-color:#777}}
.diagnostico .diag-band-title{{color:#93c5fd}}
.diagnostico .diag-tag{{background:#3b82f622;color:#93c5fd}}
.diagnostico .diag-band-content p{{font-size:11px;color:#cce;line-height:1.5;margin:3px 0}}
.diagnostico .diag-band-content ul{{margin:4px 0 4px 16px}}
.diagnostico .diag-band-content li{{font-size:11px;color:#cce;line-height:1.45;margin:2px 0}}
.diagnostico .diag-band-content code{{background:#1a2e3a;color:#93c5fd;padding:1px 4px;border-radius:3px;font-size:10px;font-family:'DM Mono',monospace}}
.diagnostico .diag-band-content strong{{color:#93c5fd;font-weight:600}}
.diagnostico .diag-band-content h2,.diagnostico .diag-band-content h3,.diagnostico .diag-band-content h4{{color:#3b82f6;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin:6px 0 3px}}
.diagnostico .diag-band-content h4:first-child{{margin-top:0}}
.diagnostico .diag-band-content .md-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}}
.diagnostico .diag-band-content .md-table th,.diagnostico .diag-band-content .md-table td{{border:1px solid #1a3a5f;padding:5px 7px;text-align:left;vertical-align:top}}
.diagnostico .diag-band-content .md-table th{{background:#0c172f;color:#93c5fd;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.3px}}
.diagnostico .diag-band-content .md-table tr:nth-child(even){{background:#0a1530}}
.diagnostico .wip-disclaimer-sm{{font-size:10px;color:#7a7a7a;margin-top:10px;padding-top:8px;border-top:1px solid #1a3a5f;font-style:italic}}
/* Dimensionamiento: hereda el estilo del contenido del diagnóstico */
.dimensionamiento .diag-band-title{{color:#93c5fd}}
.dimensionamiento .diag-band-content p{{font-size:11px;color:#cce;line-height:1.5;margin:3px 0}}
.dimensionamiento .diag-band-content code{{background:#1a2e3a;color:#93c5fd;padding:1px 4px;border-radius:3px;font-size:10px;font-family:'DM Mono',monospace}}
.dimensionamiento .diag-band-content strong{{color:#93c5fd;font-weight:600}}
.dimensionamiento .diag-band-content h2,.dimensionamiento .diag-band-content h3,.dimensionamiento .diag-band-content h4{{color:#3b82f6;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin:6px 0 3px}}
.dimensionamiento .diag-band-content h4:first-child{{margin-top:0}}
.dimensionamiento .diag-band-content .md-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}}
.dimensionamiento .diag-band-content .md-table th,.dimensionamiento .diag-band-content .md-table td{{border:1px solid #1a3a5f;padding:5px 7px;text-align:left;vertical-align:top}}
.dimensionamiento .diag-band-content .md-table th{{background:#0c172f;color:#93c5fd;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.3px}}
.dimensionamiento .diag-band-content .md-table tr:nth-child(even){{background:#0a1530}}
.recomendacion{{margin:14px 0 4px;padding:14px 16px;background:#0c1f0c;border:1px solid #1e3a1e;border-left:4px solid #22c55e;border-radius:6px}}
.recomendacion.fail{{background:#1f0e0c;border-color:#3a1e1e;border-left-color:#ef4444}}
.recomendacion.fail .rec-title{{color:#fca5a5}}
.recomendacion.fail .rec-icon{{filter:none}}
.recomendacion.pass{{background:#0c1f0c;border-color:#1e3a1e;border-left-color:#22c55e}}
.rec-header{{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.rec-icon{{font-size:18px}}
.rec-title{{color:#22c55e;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.8px}}
.rec-tag{{display:inline-block;font-size:10px;padding:2px 8px;border-radius:3px;background:#22c55e22;color:#22c55e;font-family:'DM Mono',monospace;font-weight:600}}
.rec-content p{{font-size:11px;color:#cce;line-height:1.5;margin:3px 0}}
.rec-content ul{{margin:4px 0 4px 16px}}
.rec-content li{{font-size:11px;color:#cce;line-height:1.45;margin:2px 0}}
.rec-content code{{background:#1a2e1a;color:#86efac;padding:1px 4px;border-radius:3px;font-size:10px;font-family:'DM Mono',monospace}}
.rec-content strong{{color:#86efac;font-weight:600}}
.rec-content h2,.rec-content h3,.rec-content h4{{color:#22c55e;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;margin:6px 0 3px}}
.rec-content .md-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}}
.rec-content .md-table th,.rec-content .md-table td{{border:1px solid #1a3a1a;padding:5px 7px;text-align:left;vertical-align:top}}
.rec-content .md-table th{{background:#0c1f0c;color:#86efac;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.3px}}
.rec-content .md-table tr:nth-child(even){{background:#0a1a0a}}
.solucion-recomendada{{margin:0 0 10px;padding:10px 12px;background:#1a2e1a;border:1px solid #22c55e44;border-left:4px solid #22c55e;border-radius:5px}}
.solucion-recomendada .sr-label{{display:block;font-size:10px;color:#86efac;text-transform:uppercase;letter-spacing:.8px;font-weight:700;margin-bottom:4px;font-family:'DM Mono',monospace}}
.solucion-recomendada .sr-title{{font-size:14px;color:#fff;font-weight:600;margin-bottom:4px}}
.solucion-recomendada .sr-why{{font-size:11px;color:#cce;line-height:1.5;margin-top:6px}}
.rec-content h4:first-child{{margin-top:0}}
.ta-table{{width:100%;border-collapse:collapse;margin:8px 0}}
.ta-table th,.ta-table td{{vertical-align:top;border:1px solid #1e1e1e;padding:8px 10px}}
.ta-table th{{background:#111;color:#888;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;text-align:left}}
.ta-th-turno{{background:#1a1a1a !important;color:#c8f060 !important;font-family:'DM Mono',monospace}}
.ta-col-left{{width:42%;background:#0e0e0e}}
.ta-col-right{{width:58%;background:#111}}
.ta-run-header{{display:inline-flex;align-items:center;gap:8px;font-size:12px;font-weight:600;padding:4px 10px 4px 8px;margin:10px 0 4px;background:#f0f0f0;border-radius:20px;font-family:'DM Mono',monospace;border:none}}
.run-num{{color:#111;letter-spacing:.3px}}
.run-badge{{font-size:10px;font-weight:700;padding:2px 9px;border-radius:10px;letter-spacing:.5px;text-transform:uppercase}}
.run-badge.ok{{background:#22c55e;color:#fff}}
.run-badge.fail{{background:#ef4444;color:#fff}}
.run-badge.inestable{{background:#f59e0b;color:#fff}}
.turn-badge{{font-size:9px;font-weight:700;padding:1px 7px;border-radius:8px;letter-spacing:.4px;vertical-align:middle;margin-left:6px;text-transform:uppercase}}
.turn-badge.ok{{background:#22c55e22;color:#22c55e;border:1px solid #22c55e55}}
.turn-badge.fail{{background:#ef444422;color:#ef4444;border:1px solid #ef444455}}
.regex-detail{{display:inline-block;margin:3px 0}}
.regex-detail summary{{list-style:none;cursor:pointer;padding:0}}
.regex-detail summary::-webkit-details-marker{{display:none}}
.regex-pill{{display:inline-flex;align-items:center;gap:3px;background:#1a2233;color:#64748b;border:1px solid #2a3a55;padding:2px 9px;border-radius:10px;font-size:10px;font-family:'DM Mono',monospace;letter-spacing:.3px}}
.regex-detail summary:hover .regex-pill{{color:#c8f060;border-color:#c8f06055}}
.regex-detail[open] .regex-pill{{color:#c8f060;border-color:#c8f06066}}
.regex-expanded{{display:block;margin-top:4px;padding:5px 8px;background:#080c12;border:1px solid #1e2a3a;border-radius:3px;color:#4a5568;font-size:10px;font-family:'DM Mono',monospace;word-break:break-all;white-space:pre-wrap}}
.wip-disclaimer{{margin-top:8px;padding:6px 10px;background:#1a1500;border:1px solid #f59e0b44;border-radius:4px;font-size:11px;color:#f59e0b}}
.wip-disclaimer-sm{{margin-top:10px;padding:5px 8px;background:#111;border:1px solid #2a2a2a;border-radius:4px;font-size:10px;color:#555}}
.ta-run-header + .ta-table{{border-radius:0;margin-top:0}}
.ta-run-header + .ta-table th{{border-top:none}}
.ta-run-block{{margin-bottom:8px;padding-bottom:8px;border-bottom:1px dashed #222}}
.ta-run-block:last-child{{border-bottom:none;margin-bottom:0;padding-bottom:0}}
.ta-run-tag{{display:inline-block;font-size:9px;padding:2px 6px;border-radius:3px;background:#222;color:#888;font-family:'DM Mono',monospace;margin-bottom:4px}}
.ta-run-tag.ok{{background:#22c55e22;color:#22c55e}}.ta-run-tag.fail{{background:#ef444422;color:#ef4444}}
/* Convención de colores en bloques User/Agent:
   - Texto conversacional (lo que dice cada uno): #ddd (igual para los dos)
   - Label USUARIO: violeta #8b8bf5
   - Label AGENTE: violeta #8b8bf5 + subrayado (distinguir sin saturar con colores)
   - El color verde-lima queda reservado para el header "TURNO" (estructural)
*/
.ta-user{{color:#ddd;font-size:13px;margin-bottom:6px;line-height:1.5}}
.ta-user .lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;color:#8b8bf5;display:block;margin-bottom:2px;font-style:normal}}
.ta-user .ta-text{{font-style:italic;color:#ddd}}
.ta-agent{{color:#ddd;font-size:13px;line-height:1.5;margin-bottom:6px}}
.ta-agent .lbl{{font-size:9px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;color:#8b8bf5;text-decoration:underline;text-underline-offset:3px;display:block;margin-bottom:2px;font-style:normal}}
.ta-agent .ta-text{{font-style:italic;color:#ddd}}
.ta-checks{{margin-top:4px}}
.ta-checks .turn-check{{margin-top:2px;font-size:10px}}
.log-btn{{display:inline-block;font-size:14px;padding:2px 6px;margin-right:8px;background:#1a1a1a;border:1px solid #333;border-radius:4px;text-decoration:none;cursor:pointer;transition:all .15s}}
.log-btn:hover{{background:#222;border-color:#c8f060}}
.ta-bullets{{margin:4px 0 4px 16px;padding:0;list-style:disc}}
.ta-bullets li{{font-size:11px;line-height:1.4;margin:1px 0;word-break:break-word;font-family:'DM Mono',monospace}}
.ta-bullets.ok{{color:#22c55e}}.ta-bullets.ok li{{color:#22c55e}}
.ta-bullets.fail{{color:#ef4444}}.ta-bullets.fail li{{color:#ef4444}}
.ta-detail{{margin:0 0 8px}}
.ta-detail summary{{padding:4px 0;cursor:pointer;color:#c8f060;font-size:10px;font-weight:600;font-family:'DM Mono',monospace;letter-spacing:.5px;text-transform:uppercase;list-style:none;user-select:none;display:flex;justify-content:space-between;align-items:center}}
.ta-detail summary::-webkit-details-marker{{display:none}}
.ta-detail summary:hover{{color:#fff}}
.ta-detail .ta-detail-icon{{display:inline-block;transition:transform .15s;color:#c8f060;font-size:11px;font-weight:700}}
.ta-detail[open] .ta-detail-icon{{transform:rotate(90deg)}}
.ta-detail .ta-flow-table{{margin:0;border-top:1px solid #1f1f1f}}
.ta-flow-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:12px}}
.ta-flow-table td{{padding:6px 8px;border-bottom:1px solid #1e1e1e;vertical-align:top}}
.ta-flow-table tr:last-child td{{border-bottom:none}}
.ta-flow-table .col-step{{width:62%;color:#ddd}}
.ta-flow-table .col-problem{{width:38%;color:#aaa;font-size:11px;border-left:1px solid #1e1e1e;padding-left:10px}}
.ta-flow-table code{{background:#1f2937;color:#cbd5e1;padding:1px 4px;border-radius:3px;font-size:10px;font-family:'DM Mono',monospace}}
.ta-flow-table em{{color:#ddd;font-style:italic}}
.trace-step{{margin:6px 0;padding:6px 10px;border-radius:4px;font-size:12px;line-height:1.5}}
.trace-user{{background:#1a1a2e;border-left:3px solid #8b8bf5;color:#ddd}}
.trace-agent{{background:#1a1a1a;border-left:3px solid #c8f060;color:#ddd}}
.trace-action{{background:transparent;color:#aaa;padding:4px 10px 4px 24px;font-style:italic}}
.trace-arrow{{color:#666;margin-right:4px}}
.trace-lbl{{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;color:#8b8bf5;margin-bottom:2px}}
.trace-agent .trace-lbl{{color:#8b8bf5;text-decoration:underline;text-underline-offset:3px}}
.trace-text{{color:#ddd;font-style:italic}}
/* Análisis técnico (columna derecha): texto en #ddd (coherente con user/agent), code en gris-azul */
.ta-right h2,.ta-right h3{{color:#c8f060;font-size:12px;font-weight:600;margin:10px 0 4px}}
.ta-right h2{{font-size:14px}}
.ta-right h4{{font-size:10px;color:#c8f060;font-weight:600;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.5px}}
.ta-right h4:first-child{{margin-top:0}}
.ta-right p{{font-size:13px;color:#ddd;line-height:1.6;margin:4px 0}}
.ta-right ul,.ta-right ol{{margin:6px 0 6px 18px}}
.ta-right li{{font-size:13px;color:#ddd;line-height:1.55;margin:2px 0}}
.ta-right .manual-analysis ol li{{margin:10px 0;line-height:1.6}}
.ta-right .manual-analysis ul li{{margin:6px 0}}
.diag-block{{margin-top:24px;padding-top:14px;border-top:1px solid #2a2a2a}}
.diag-header{{color:#c8f060 !important;font-size:12px !important;margin:0 0 10px !important;font-family:'DM Mono',monospace;letter-spacing:.5px}}
/* Capa blocks: renderizado estructurado de cada capa del análisis ('Causa raíz')
   NOTA: las capas internas NO tienen barra lateral coloreada (solo el bloque
   Diagnóstico exterior la tiene). El emoji 🔴🟢🟡⚪ es el indicador de marca. */
.capa-block{{margin:14px 0;padding:14px 16px;border-radius:6px;min-height:48px}}
.capa-block.capa-rojo{{background:rgba(255,80,80,0.07)}}
.capa-block.capa-verde{{background:rgba(80,200,80,0.05)}}
.capa-block.capa-amarillo{{background:rgba(220,180,50,0.06)}}
.capa-block.capa-na{{background:rgba(255,255,255,0.02)}}
.capa-header{{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}}
.capa-emoji{{font-size:18px;line-height:1;flex-shrink:0}}
.capa-titulo{{flex:1;font-size:14px;color:#fff}}
.capa-titulo strong{{color:#fff;font-weight:600}}
.capa-badge{{padding:3px 12px;border-radius:12px;font-size:11px;font-weight:600;white-space:nowrap;font-family:'DM Mono',monospace;letter-spacing:.3px}}
.capa-badge-verificada{{background:rgba(80,200,80,0.15);color:#5dc870;border:1px solid rgba(80,200,80,0.35)}}
.capa-badge-supuesta{{background:rgba(220,180,50,0.15);color:#d4b32f;border:1px solid rgba(220,180,50,0.35)}}
.capa-badge-na{{background:rgba(150,150,150,0.12);color:#aaa;border:1px solid rgba(150,150,150,0.3)}}
.capa-fuente{{font-size:12px;margin-top:8px;margin-left:30px}}
.capa-fuente code{{display:inline-block;max-width:100%;background:#2a2a2a;color:#ddd;padding:3px 10px;border-radius:4px;font-size:11px;font-family:'DM Mono',monospace;word-break:break-word;overflow-wrap:anywhere;white-space:normal;line-height:1.5;box-sizing:border-box}}
.capa-desc{{margin-top:8px;margin-left:30px}}
.capa-desc p,.capa-desc-p{{color:#ddd;font-size:13px;line-height:1.6;margin:6px 0}}
.capa-desc code{{background:#2a2a2a;color:#ddd;padding:1px 6px;border-radius:3px;font-size:11px;font-family:'DM Mono',monospace;word-break:break-word;overflow-wrap:anywhere}}
/* Cualquier tabla/pre/blockquote dentro de una capa hereda el sangrado del título */
.capa-block .md-table,.capa-block table,.capa-block pre,.capa-block blockquote,.capa-block ul,.capa-block ol{{margin-left:30px;margin-top:8px;margin-bottom:8px;max-width:calc(100% - 30px)}}
.capa-block .md-table{{width:calc(100% - 30px);border-collapse:collapse;font-size:11px}}
.capa-block .md-table th,.capa-block .md-table td{{border:1px solid #2a2a2a;padding:6px 8px;text-align:left;vertical-align:top;color:#ddd}}
.capa-block .md-table th{{background:#1a1a1a;color:#c8f060;font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.3px}}
.badge{{display:inline-block;font-size:9px;padding:2px 7px;border-radius:3px;margin-left:8px;font-family:'DM Mono',monospace;letter-spacing:.4px;vertical-align:middle;font-weight:600}}
.badge-auto{{background:#1a1a1a;color:#888;border:1px solid #2a2a2a}}
.badge-llm{{background:#1a2818;color:#c8f060;border:1px solid #2a4818}}
.panel-close{{color:#888 !important;font-size:14px;padding:4px 10px !important}}
.panel-close:hover{{color:#fff !important;background:#222}}
.ta-right code{{background:#1f2937;color:#cbd5e1;padding:2px 6px;border-radius:3px;font-size:12px;font-family:'DM Mono',monospace}}
.ta-right strong{{color:#fff;font-weight:600}}
.ta-right em{{color:#aaa;font-style:italic}}
.ta-right a{{color:#c8f060;text-decoration:none}}.ta-right a:hover{{text-decoration:underline}}
.ta-right .md-table{{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}}
.ta-right .md-table th,.ta-right .md-table td{{border:1px solid #1e1e1e;padding:5px 7px;text-align:left}}
.ta-right .md-table th{{background:#1a1a1a;color:#c8f060;font-weight:600}}
.ta-right .md-table tr:nth-child(even){{background:#0e0e0e}}
.diag-manual-block{{margin:12px 0 4px;padding:12px 14px;background:#0c0c0e;border:1px solid #1f1f2a;border-left:3px solid #c8f060;border-radius:6px}}
.diag-manual-block h2,.diag-manual-block h3{{color:#c8f060;font-size:12px;font-weight:600;margin:10px 0 4px;text-transform:uppercase;letter-spacing:.5px;font-family:'DM Mono',monospace}}
.diag-manual-block h4{{color:#aaa;font-size:11px;font-weight:600;margin:8px 0 4px;text-transform:uppercase;letter-spacing:.5px}}
.diag-manual-block p{{font-size:13px;color:#ddd;line-height:1.6;margin:4px 0}}
.diag-manual-block ul{{margin:6px 0 6px 20px}}
.diag-manual-block li{{font-size:13px;color:#ddd;line-height:1.55;margin:4px 0}}
.diag-manual-block code{{background:#1f2937;color:#cbd5e1;padding:2px 6px;border-radius:3px;font-size:12px;font-family:'DM Mono',monospace}}
.diag-manual-block strong{{color:#fff;font-weight:600}}
.diag-manual-block em{{color:#aaa;font-style:italic}}
.diag-manual-block .md-table{{width:100%;border-collapse:collapse;margin:8px 0;font-size:12px}}
.diag-manual-block .md-table th,.diag-manual-block .md-table td{{border:1px solid #1e1e1e;padding:6px 9px;text-align:left;vertical-align:top}}
.diag-manual-block .md-table th{{background:#1a1a1a;color:#c8f060;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.3px}}
.diag-manual-block .md-table tr:nth-child(even){{background:#0e0e0e}}
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
.modal-metodologia{{max-width:760px}}
.modal-sub{{color:#888;font-size:11px;font-family:'DM Mono',monospace;margin-bottom:18px;letter-spacing:.3px}}
.kpi-section{{margin:18px 0;padding:14px 16px;background:#0d0d0d;border:1px solid #1f1f1f;border-radius:6px;position:relative}}
.kpi-section h3[data-legend]{{cursor:help;position:relative;display:inline-block}}
.kpi-section h3[data-legend]:hover::after{{content:attr(data-legend);position:absolute;top:calc(100% + 6px);left:0;background:#1f1f1f;color:#ddd;padding:10px 14px;border-radius:5px;font-size:11px;line-height:1.5;border:1px solid #444;z-index:1000;width:340px;white-space:normal;font-family:'Inter',-apple-system,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.5);font-weight:normal;letter-spacing:normal;text-transform:none}}
.kpi-section h3[data-legend]:hover::before{{content:"";position:absolute;top:calc(100% - 1px);left:20px;border:6px solid transparent;border-bottom-color:#444;z-index:1000}}
.kpi-section h3{{color:#c8f060;font-size:13px;margin:0 0 10px;font-family:'DM Mono',monospace;letter-spacing:.3px}}
.kpi-section h4{{color:#aaa;font-size:11px;margin:12px 0 6px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.kpi-section p{{color:#ddd;font-size:12px;line-height:1.5;margin:4px 0}}
.kpi-section ul{{margin:4px 0 4px 18px;padding:0}}
.kpi-section li{{color:#ddd;font-size:12px;line-height:1.5;margin:2px 0}}
.kpi-section code{{background:#1f2937;color:#cbd5e1;padding:1px 5px;border-radius:3px;font-size:11px;font-family:'DM Mono',monospace}}
.kpi-sub{{color:#888 !important;font-size:11px !important;font-style:italic}}
.kpi-action{{color:#aaa !important;font-size:11px !important}}
.kpi-no-data{{color:#666 !important;font-size:11px !important;text-align:center;padding:10px 0}}
.kpi-flak h3{{color:#fbbf24}}
.kpi-component{{margin:10px 0 14px;padding-left:8px;border-left:2px solid #1f1f1f}}
.kpi-bar-row{{display:flex;align-items:center;gap:8px;margin:3px 0;position:relative;cursor:help}}
.kpi-bar-row[data-legend]:hover::after{{content:attr(data-legend);position:absolute;bottom:calc(100% + 8px);left:0;background:#1f1f1f;color:#ddd;padding:10px 14px;border-radius:5px;font-size:11px;line-height:1.5;border:1px solid #444;z-index:1000;width:340px;white-space:normal;font-family:'Inter',-apple-system,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.5)}}
.kpi-bar-row[data-legend]:hover::before{{content:"";position:absolute;bottom:calc(100% + 2px);left:30px;border:6px solid transparent;border-top-color:#444;z-index:1000}}
.kpi-label{{flex:0 0 180px;font-size:11px;color:#ccc}}
.kpi-bar{{flex:1;height:8px;background:#1a1a1a;border-radius:4px;overflow:hidden}}
.kpi-bar-fill{{height:100%;background:linear-gradient(90deg,#22c55e,#86efac);border-radius:4px;transition:width .3s}}
.kpi-value{{flex:0 0 50px;text-align:right;font-size:11px;color:#c8f060;font-family:'DM Mono',monospace;font-weight:600}}
.kpi-cobertura{{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0}}
.kpi-cobertura td{{padding:4px 8px;border-bottom:1px solid #1a1a1a;color:#ddd}}
.kpi-cobertura td:nth-child(2){{color:#aaa;width:30%}}
.kpi-cobertura td:nth-child(3){{color:#888;width:18%;text-align:right;font-size:10px}}
.kpi-regr{{width:100%;border-collapse:collapse;font-size:12px}}
.kpi-regr td{{padding:6px 10px;border-bottom:1px solid #1a1a1a;color:#ddd}}
.kpi-regr td:first-child{{color:#888;width:30%;font-size:11px}}
.delta-up{{color:#22c55e !important;font-weight:600}}
.delta-down{{color:#ef4444 !important;font-weight:600}}
.delta-neutral{{color:#888 !important;font-weight:600}}
/* fbtn-modal: usa estilo idéntico a fbtn normal (sin highlight) */
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
/* Botón "?" circular (info de capas / marcas) */
.info-btn{{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:#444;color:#ddd;border:1px solid #666;font-size:11px;cursor:pointer;margin-left:6px;padding:0;font-weight:bold;line-height:1;vertical-align:middle}}
.info-btn:hover{{background:#666;color:#fff}}
/* Modal info (capas / marcas) */
.info-modal-overlay{{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:1000;justify-content:center;align-items:center}}
.info-modal-overlay.visible{{display:flex}}
.info-modal{{background:#1a1a1a;border:1px solid #444;border-radius:8px;max-width:600px;width:90%;padding:24px;color:#ddd;font-size:14px;line-height:1.6;position:relative}}
.info-modal h3{{margin-top:0;color:#fff}}
.info-modal-close{{position:absolute;top:12px;right:12px;background:transparent;border:none;color:#888;font-size:20px;cursor:pointer;padding:0;line-height:1}}
.info-modal-close:hover{{color:#fff}}
.info-modal table{{width:100%;border-collapse:collapse;margin-top:8px}}
.info-modal td{{padding:6px 8px;border-bottom:1px solid #333}}
.info-modal code{{background:#1f2937;color:#cbd5e1;padding:1px 5px;border-radius:3px;font-size:12px;font-family:'DM Mono',monospace}}
/* Patrones cruzados — bloque colapsable (rojo = análisis de errores) */
.patterns-block{{background:#1a1a1a;border:1px solid #ef4444;border-left:4px solid #ef4444;border-radius:8px;margin-bottom:16px;overflow:hidden}}
.patterns-th{{display:flex;align-items:center;gap:10px;padding:11px 16px;cursor:pointer;user-select:none}}
.patterns-th:hover{{background:#222}}
.patterns-icon{{font-size:15px;flex:0 0 auto}}
.patterns-title{{color:#ef4444;font-size:13px;font-weight:700;flex:0 0 auto}}
.patterns-stats{{color:#999;font-size:11px;font-family:'DM Mono',monospace;flex:1}}
.patterns-arrow{{color:#ef4444;font-size:10px;transition:transform 0.2s;margin-left:auto;flex:0 0 auto}}
.patterns-arrow.open{{transform:rotate(90deg)}}
.patterns-body{{display:none;padding:4px 16px 16px;border-top:1px solid #2a2a2a}}
.patterns-body.open{{display:block}}
.patterns-block h2{{display:none}}
/* Patterns body — sketch layout (2-col cards) */
.pat-resumen{{background:#1a1a1a;border:1px solid #2d2d2d;border-radius:6px;padding:10px 14px;margin-bottom:14px}}
.pat-resumen-title{{font-size:10px;font-weight:700;letter-spacing:1px;color:#888;text-transform:uppercase;margin-bottom:6px;border-bottom:1px solid #2a2a2a;padding-bottom:3px}}
.pat-resumen-stat{{font-size:12px;color:#ccc;margin-bottom:2px;line-height:1.5}}
.pat-card{{background:#141414;border:1px solid #2d2d2d;border-radius:6px;margin-bottom:12px;overflow:hidden}}
.pat-card-hdr{{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #2a2a2a;gap:10px}}
.pat-card-title{{font-size:13px;font-weight:600;color:#e0e0e0;flex:1}}
.pat-roi-btn{{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:700;color:#c8f060;background:#0e1f05;border:1px solid #c8f06044;padding:3px 10px;border-radius:5px;margin-bottom:8px;user-select:none}}
.pat-roi-q{{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;background:#c8f06033;color:#c8f060;font-size:9px;font-weight:700;flex-shrink:0;cursor:pointer;transition:background .15s}}
.pat-roi-q:hover{{background:#c8f06066}}
.pat-wip{{font-size:12px;color:#666;font-style:italic;padding:6px 10px;border-left:2px solid #333;background:#161616;border-radius:0 4px 4px 0;line-height:1.5}}
.roi-modal-overlay{{display:none;position:fixed;inset:0;background:#000b;z-index:9999;align-items:center;justify-content:center}}
.roi-modal-overlay.open{{display:flex}}
.roi-modal{{background:#1a1a1a;border:1px solid #ef4444;border-radius:8px;width:380px;max-width:90vw;box-shadow:0 8px 32px #000c;overflow:hidden}}
.roi-modal-hdr{{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid #2a2a2a}}
.roi-modal-ttl{{font-size:13px;font-weight:700;color:#ef4444}}
.roi-modal-x{{font-size:20px;color:#666;cursor:pointer;line-height:1;padding:0 2px}}
.roi-modal-x:hover{{color:#ccc}}
.roi-modal-body{{padding:14px 16px}}
.rmi-def{{font-size:12px;color:#ccc;line-height:1.5;margin-bottom:12px}}
.rmi-section{{margin-bottom:12px}}
.rmi-lbl{{font-size:10px;font-weight:700;letter-spacing:.8px;color:#777;text-transform:uppercase;margin-bottom:5px;border-bottom:1px solid #2a2a2a;padding-bottom:3px}}
.rmi-formula{{font-size:12px;font-family:'DM Mono',monospace;color:#c8f060;background:#0e1f05;padding:6px 10px;border-radius:4px}}
.rmi-row{{display:flex;justify-content:space-between;font-size:12px;color:#ccc;padding:4px 0;border-bottom:1px solid #222}}
.rmi-result{{color:#c8f060;font-weight:700;border-bottom:none;margin-top:4px;padding-top:6px}}
.pat-card-body{{display:grid;grid-template-columns:1fr 2fr}}
.pat-card-left{{padding:12px 14px;border-right:1px solid #2a2a2a}}
.pat-card-right{{padding:12px 14px}}
.pat-col-lbl{{font-size:10px;font-weight:700;letter-spacing:.8px;color:#777;text-transform:uppercase;margin-bottom:7px;border-bottom:1px solid #2a2a2a;padding-bottom:3px}}
.pat-rec-lbl{{margin-top:12px}}
.pat-tc-item{{font-size:11px;font-family:'DM Mono',monospace;color:#c8f060;margin-bottom:4px}}
.pat-tc-nopattern{{color:#ef4444}}
.pat-causa-row{{font-size:12px;color:#ccc;margin-bottom:5px;line-height:1.4}}
.pat-causa-lbl{{color:#aaa;font-weight:600}}
.pat-rec-text{{font-size:12px;color:#b8c890;line-height:1.5}}
.pat-section{{margin-bottom:18px}}
.pat-sh{{font-size:10px;font-weight:700;letter-spacing:1px;color:#888;text-transform:uppercase;margin-bottom:8px;border-bottom:1px solid #2a2a2a;padding-bottom:4px;margin-top:16px}}
.pat-empty{{font-size:12px;color:#888;font-style:italic}}
.layer-format-note{{font-size:11px;color:#888;font-style:italic;margin:4px 0 16px;font-family:'DM Mono',monospace}}
</style></head><body>
<h1>QA Report \u2014 Florister\u00eda Petal</h1>
<p class="sub">{ts} · {RUNS} runs/TC · {'Cloud Shell' if IS_CLOUD_SHELL else platform.node()}</p>
{legacy_note}
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
{patterns_block}
<div class="actions-bar">
<a id="btn-delete" class="dl dl-disabled" onclick="openDeletePanel()" style="cursor:not-allowed">\U0001f5d1 Borrar an\u00e1lisis</a>
<a id="btn-optimize" class="dl dl-disabled" onclick="openOptimizePanel()" style="cursor:not-allowed">\u2699 Optimizar</a>
<a class="dl" onclick="openHistorial()" style="cursor:pointer">\U0001f4ca Hist\u00f3rico</a>
</div>
<div id="optimize-panel" class="optimize-panel hidden">
  <div class="optimize-panel-header">
    <span id="optimize-panel-title" class="optimize-panel-title">TCs en FAIL \u2014 selecciona los que quieras optimizar</span>
    <a id="btn-run" class="dl dl-disabled" onclick="runOptimize()" style="cursor:not-allowed">\u25b6 Run</a>
    <a class="dl panel-close" onclick="closePanel()" style="cursor:pointer" title="Cerrar panel">\u2715</a>
    <span id="btn-run-feedback" class="run-feedback"></span>
  </div>
  <table class="optimize-table">
    <thead><tr><th></th><th>ID</th><th>Nombre</th><th>Check fallido</th><th>Respuesta del agente</th></tr></thead>
    <tbody id="optimize-tbody"></tbody>
  </table>
</div>
<div class="filter-bar">
<div class="filter-row">
<span class="filter-label">Categor\u00eda</span>
<div class="fbtn" data-legend="Regresi\u00f3n: TCs que vigilan bugs ya corregidos para que no vuelvan" onclick="filterByType('REG')">Regresi\u00f3n</div>
<div class="fbtn" data-legend="Registro: TCs del flujo de alta de usuario (email, nombre, datos)" onclick="filterByType('NEW')">Registro</div>
<div class="fbtn fbtn-modal" data-legend="Ver KPIs de calidad QA: flakiness, salud de Orquestador y Compra, cobertura del suite, regresi\u00f3n vs run anterior" onclick="openMetodologia()">Metodolog\u00eda (KPIs)</div>"""
    for g in groups:
        legend = GROUP_LEGEND.get(g, "")
        legend_attr = f' data-legend="{esc(legend)}" title="{esc(legend)}"' if legend else ""
        h += f'\n<div class="fbtn"{legend_attr} onclick="filterByGroup(\'{g}\')">{g}</div>'
    h += "\n</div>\n</div>\n"

    for r in results:
        sb = {"PASS": "sb-pass", "FAIL": "sb-fail", "INESTABLE": "sb-inst", "QUOTA_ERROR": "sb-quota"}.get(r["status"], "sb-inst")
        bc = {"PASS": "b-p", "FAIL": "b-f", "INESTABLE": "b-i", "QUOTA_ERROR": "b-q"}.get(r["status"], "b-i")
        badge = f'<span class="b {bc}">{r["status"]}</span>'
        # Tag de tipo en el header (sustituye al veredicto)
        _analysis_peek = _load_tc_analysis(r["id"], run_ts=_ts_compact)
        tipo_tag_html = ""
        if _analysis_peek:
            _tipo = _analysis_peek["meta"].get("tipo", "")
            if _tipo:
                tipo_tag_html = f'<span class="tipo-tag">{esc(_tipo)}</span>'
        # Bot\u00f3n de log JSON (US-QA-09: an\u00e1lisis basado en log)
        log_btn_html = ""
        if logs_dir_name:
            log_url = f'{logs_dir_name}/{r["id"]}.json'
            log_btn_html = f'<a class="log-btn" href="{log_url}" target="_blank" title="Ver log JSON completo de este TC (conversacion, params, checks)" onclick="event.stopPropagation()">JSON</a>'
        h += f"""<div class="t {sb}" data-status="{r['status']}" data-group="{r['group']}" data-type="{r['type']}">
<div class="th" onclick="toggle(this)">
<div class="th-left">{log_btn_html}<span class="tid">{r['id']}</span><span class="tname">{esc(r['name'])}</span><span class="tgroup">{r['group']}</span><span class="truns">{r['pass_count']}/{r['total_runs']}</span>{tipo_tag_html}</div>
<div style="display:flex;gap:5px;align-items:center">{badge}<span class="arrow">\u25b6</span></div>
</div><div class="tbody">\n"""
        analysis = _analysis_peek
        # === RENDER UNIFICADO ===
        # Mismo template para todos los TCs (con o sin .md manual).
        # Izquierda: solo datos crudos (user + agent).
        # Derecha: flujo inline + evaluación + diagnóstico.
        # Si hay .md manual: se inserta como diagnóstico enriquecido + recomendación.
        _gi_map = {"G1": "Saludo/despedida", "G2": "Info negocio", "G3": "Consulta generica",
                   "G4": "Gestion pedido", "G5": "Compra directa", "G6": "Queja/incidencia",
                   "G7": "Fuera de scope", "COMPRA-INV": "Compra con inventario",
                   "COMPRA-ZG": "Compra zona geografica", "ESP": "Caso especial"}
        _gi_to_playbook = {
            "G1": "Orquestador (saludo)", "G2": "Orquestador (info)",
            "G3": "Orquestador (consulta)", "G4": "Checkout (gestion pedido)",
            "G5": "Compra (busqueda y venta)", "G6": "Orquestador (queja)",
            "G7": "Registro (alta usuario)", "COMPRA-INV": "Compra > tool buscar_inventario",
            "COMPRA-ZG": "Compra > tool zona_geografica", "ESP": "Orquestador (caso especial)",
        }
        _gi_to_file = {
            "G5": "definitions/playbooks/compra.yaml", "COMPRA-INV": "definitions/playbooks/compra.yaml",
            "COMPRA-ZG": "definitions/playbooks/compra.yaml", "G4": "definitions/playbooks/checkout.yaml",
            "G7": "definitions/playbooks/registro.yaml",
            "G1": "definitions/playbooks/petal_cx_orchestrator.yaml",
            "G2": "definitions/playbooks/petal_cx_orchestrator.yaml",
            "G3": "definitions/playbooks/petal_cx_orchestrator.yaml",
            "G6": "definitions/playbooks/petal_cx_orchestrator.yaml",
            "ESP": "definitions/playbooks/petal_cx_orchestrator.yaml",
        }
        fail_actions_all = []
        for ri, run in enumerate(r["runs"]):
            run_pass = run["pass"]
            run_cls = "ok" if run_pass else "fail"
            run_badge_label = "PASS" if run_pass else ("INESTABLE" if r["status"] == "INESTABLE" else "FAIL")
            run_badge_cls = "ok" if run_pass else ("inestable" if r["status"] == "INESTABLE" else "fail")
            h += f'<div class="ta-run-header"><span class="run-num">Run {ri+1}</span><span class="run-badge {run_badge_cls}">{run_badge_label}</span></div>\n'
            for tn_idx, t in enumerate(run["turns"]):
                tn = tn_idx + 1
                params = t.get("params") or {}
                gi = params.get("grupo_intent", "")
                # Trace real (dict desde la API de CX) y playbook real
                trace = t.get("trace") if isinstance(t.get("trace"), dict) else {}
                real_playbook = t.get("playbook", "") or trace.get("currentPlaybook", "")
                has_fail = any(d.startswith("FAIL") for d in t["checks"]["details"])
                # Slots reservados (no son grupo_intent ni internos) que muestran info útil
                slot_keys_to_show = [k for k in params.keys() if k not in ("grupo_intent", "intencion_inicial") and params.get(k)]
                # --- IZQUIERDA: solo datos crudos ---
                left_html = f'<div class="ta-user"><span class="lbl">Usuario (T{tn})</span><span class="ta-text">"{esc(t["user"])}"</span></div>'
                left_html += f'<div class="ta-agent {"has-fail" if has_fail else "has-ok"}"><span class="lbl">Agente</span><span class="ta-text">"{esc(t["agent"])}"</span></div>'
                # --- DERECHA: flujo inline + evaluacion + diagnostico ---
                # Si hay análisis manual con tabla Turnos vs Problemas → usar inline
                turno_md_for_flow = analysis["turnos"].get(tn, "") if analysis else ""
                manual_flow_rows = _extract_flow_table(turno_md_for_flow) if turno_md_for_flow else None
                # Pre-compute checks para EVALUACIÓN
                ok_msgs = []
                fail_msgs = []
                for d in t["checks"]["details"]:
                    st, msg = _split_check_detail(d)
                    if st == "OK":
                        ok_msgs.append(msg)
                    else:
                        fail_msgs.append(msg)
                # 1) EVALUACIÓN — siempre visible, primera en columna derecha
                rp = []
                rp.append(f'<h4>Evaluacion</h4>')
                if not has_fail:
                    # PASS: auto-desc de lo que mencionó el agente + pill regex colapsable
                    for c in ok_msgs:
                        _, toks, raw = _check_msg_to_tokens(c)
                        if toks:
                            auto_ok = "Agente mencionó: " + " / ".join(toks[:6])
                            rp.append(f'<p style="color:#aaa;font-size:12px;font-style:italic;margin:2px 0 4px 0">{esc(auto_ok)}</p>')
                        raw_display = f'[{raw}]' if raw else c
                        rp.append(f'<details class="regex-detail"><summary><span class="regex-pill">regex ▾</span></summary><code class="regex-expanded">{esc(raw_display)}</code></details>')
                else:
                    # FAIL: desc (manual o auto-generado) + pill regex colapsable
                    turn_desc = _tc_turn_desc.get((r["id"], tn), t.get("desc", ""))
                    if not turn_desc and fail_msgs:
                        auto_parts = []
                        for c in fail_msgs:
                            _, toks, _ = _check_msg_to_tokens(c)
                            if toks:
                                auto_parts.append("Debía incluir: " + " / ".join(toks[:6]))
                            elif c:
                                auto_parts.append(c[:80])
                        turn_desc = " · ".join(auto_parts)
                    if turn_desc:
                        rp.append(f'<p style="color:#aaa;font-size:12px;font-style:italic;margin:2px 0 6px 0">{esc(turn_desc)}</p>')
                    for c in fail_msgs:
                        _, _, raw = _check_msg_to_tokens(c)
                        raw_display = f'[{raw}]' if raw else c
                        rp.append(f'<details class="regex-detail"><summary><span class="regex-pill">regex ▾</span></summary><code class="regex-expanded">{esc(raw_display)}</code></details>')
                # 2) ANÁLISIS DETALLADO — colapsable, debajo de EVALUACIÓN
                rp.append(f'<details class="ta-detail">')
                rp.append(f'<summary>Análisis detallado <span class="ta-detail-icon">▶</span></summary>')
                rp.append(f'<div class="ta-detail-content">')
                if manual_flow_rows:
                    # CASO A: tabla manual del MD
                    rp.append(f'<table class="ta-flow-table">')
                    for row in manual_flow_rows:
                        rp.append(f'<tr>')
                        rp.append(f'<td class="col-step">{_md_inline_to_html(row["step"])}</td>')
                        rp.append(f'<td class="col-problem">{_md_inline_to_html(row["problem"])}</td>')
                        rp.append(f'</tr>')
                    rp.append(f'</table>')
                else:
                    # CASO B: auto trace desde grupo_intent + slots
                    has_useful_data = bool((real_playbook and real_playbook != "unknown") or params or gi)
                    # USUARIO box dentro del details
                    rp.append(f'<div class="trace-step trace-user">')
                    rp.append(f'<span class="trace-lbl">Usuario (T{tn})</span>')
                    rp.append(f'<div class="trace-text">"{esc(t["user"][:140])}"</div>')
                    rp.append(f'</div>')
                    if has_useful_data:
                        if real_playbook and real_playbook != "unknown":
                            rp.append(f'<div class="trace-step trace-action">')
                            rp.append(f'<span class="trace-arrow">v</span> Playbook activo: <strong>{esc(real_playbook)}</strong> <span style="color:#999;font-size:10px">(real)</span>')
                            rp.append(f'</div>')
                        if gi:
                            gi_desc = _gi_map.get(gi, "")
                            playbook_inferred = _gi_to_playbook.get(gi, "Orquestador")
                            gi_title = f' title="{esc(gi_desc)}"' if gi_desc else ""
                            rp.append(f'<div class="trace-step trace-action">')
                            rp.append(f'<span class="trace-arrow">v</span> Orquestador clasifica: <code{gi_title}>{esc(gi)}</code> · <em>{esc(gi_desc)}</em> <span style="color:#999;font-size:10px">(real)</span>')
                            rp.append(f'</div>')
                            if not (real_playbook and real_playbook != "unknown") and gi not in ("G1", "G2", "G3", "G6", "ESP"):
                                rp.append(f'<div class="trace-step trace-action">')
                                rp.append(f'<span class="trace-arrow">v</span> Handoff: <strong>{esc(playbook_inferred)}</strong> <span style="color:#999;font-size:10px">(inferido)</span>')
                                rp.append(f'</div>')
                        intent_match = trace.get("intent", "")
                        if intent_match:
                            rp.append(f'<div class="trace-step trace-action">')
                            rp.append(f'<span class="trace-arrow">v</span> Intent matched: <code>{esc(intent_match)}</code>')
                            rp.append(f'</div>')
                        if slot_keys_to_show:
                            slots_text = ", ".join(f'<code>{esc(k)}={esc(str(params[k])[:50])}</code>' for k in slot_keys_to_show[:5])
                            rp.append(f'<div class="trace-step trace-action">')
                            rp.append(f'<span class="trace-arrow">v</span> Slots completados: {slots_text} <span style="color:#999;font-size:10px">(real)</span>')
                            rp.append(f'</div>')
                    else:
                        rp.append(f'<div class="trace-step trace-action" style="color:#666"><span class="trace-arrow">v</span> <em>Sin trace ni grupo_intent capturado en este turno</em></div>')
                    # AGENTE box dentro del details
                    rp.append(f'<div class="trace-step trace-agent">')
                    rp.append(f'<span class="trace-lbl">Agente</span>')
                    agent_short = t["agent"][:240] + ("..." if len(t["agent"]) > 240 else "")
                    rp.append(f'<div class="trace-text">"{esc(agent_short)}"</div>')
                    rp.append(f'</div>')
                rp.append(f'</div>')  # cierre ta-detail-content
                rp.append(f'</div>')  # cierre ta-detail-content
                rp.append(f'</details>')
                # Diagnostico MANUAL: solo en el último run, en la columna derecha (no se duplica)
                turn_analysis_md = analysis["turnos"].get(tn, "") if analysis else ""
                is_last_run = (ri == len(r["runs"]) - 1)
                # 1) BLOQUE DETERMINÍSTICO: siempre que haya fail, mostrar datos reales del log
                if has_fail:
                    rp.append(f'<h4>Contexto <span class="badge badge-auto">⚙ AUTO</span></h4>')
                    playbook_inferred = _gi_to_playbook.get(gi, "Orquestador") if gi else "Orquestador"
                    grupo_expected = r.get("group", "")
                    grupo_match_ok = (gi == grupo_expected) or (grupo_expected and grupo_expected in (gi or ""))
                    rp.append(f'<ul class="ta-bullets" style="color:#aaa;font-size:12px">')
                    if gi:
                        match_icon = "✅" if grupo_match_ok else "⚠️"
                        rp.append(f'<li style="color:#aaa"><strong>Clasificación:</strong> {match_icon} grupo_intent observado <code>{esc(gi)}</code> (esperado: <code>{esc(grupo_expected) if grupo_expected else "—"}</code>) → playbook inferido <code>{esc(playbook_inferred)}</code></li>')
                    else:
                        rp.append(f'<li style="color:#aaa"><strong>Clasificación:</strong> ⚠️ grupo_intent NO capturado en este turno (esperado: <code>{esc(grupo_expected) if grupo_expected else "—"}</code>)</li>')
                    if slot_keys_to_show:
                        slots_str = ", ".join(f'<code>{esc(k)}={esc(str(params[k])[:40])}</code>' for k in slot_keys_to_show[:5])
                        rp.append(f'<li style="color:#aaa"><strong>Slots extraídos:</strong> {slots_str}</li>')
                    rp.append(f'</ul>')
                    if not turn_analysis_md:
                        # Solo añadir a la cola de Optimizar si NO hay análisis manual aún
                        fail_actions_all.append({"turno": tn, "msgs": fail_msgs, "user": t["user"][:100], "gi": gi})
                # Nota: el diagnóstico manual ahora se renderiza fuera del loop, al nivel del TC,
                # como banda full-width justo antes de "Recomendación / Acción".
                turn_analysis_html = "\n".join(rp)
                h += '<table class="ta-table"><tr>'
                turn_badge_cls = "fail" if has_fail else "ok"
                turn_badge_label = "No superado" if has_fail else "Superado"
                h += f'<th colspan="2" class="ta-th-turno">Turno {tn} <span class="turn-badge {turn_badge_cls}">{turn_badge_label}</span></th></tr><tr>'
                h += f'<td class="ta-col-left">{left_html}</td>'
                h += f'<td class="ta-col-right"><div class="ta-right">{turn_analysis_html}</div></td>'
                h += '</tr></table>\n'
        # ──────────────────────────────────────────────────────────────────
        # Diagnóstico al NIVEL del TC (no por run/turno): banda full-width
        # justo antes de la banda de Recomendación, con mismo ancho/letra.
        # ──────────────────────────────────────────────────────────────────
        diagnostico_md = ""
        if analysis:
            # Tomar el primer turno con MD (el análisis se asocia al T1 típicamente)
            for _tn_k, _md_v in analysis.get("turnos", {}).items():
                if _md_v and _md_v.strip():
                    diagnostico_md = _md_v
                    break
        if diagnostico_md:
            md_sin_tabla = re.sub(
                r"###?\s*Turnos\s+vs\s+Problemas[^\n]*\n(?:\s*\|[^\n]*\n)+",
                "", diagnostico_md, flags=re.IGNORECASE
            ).strip()
            # Extraer la sección "Dimensionamiento del bug" como banda aparte
            # Captura desde "### Dimensionamiento..." hasta el siguiente "## " o el fin del MD.
            dim_match = re.search(
                r"(####?\s*Dimensionamiento\s+del\s+bug[^\n]*\n.*?)(?=\n##\s|\n###\s|\Z)",
                md_sin_tabla, flags=re.IGNORECASE | re.DOTALL
            )
            dim_md = ""
            if dim_match:
                dim_md = dim_match.group(1).strip()
                # Quitarla del MD del diagnóstico
                md_sin_tabla = (md_sin_tabla[:dim_match.start()] + md_sin_tabla[dim_match.end():]).strip()
            if md_sin_tabla:
                diag_tipo = analysis["meta"].get("tipo", "")
                diag_tag_html = f'<span class="rec-tag diag-tag">{esc(diag_tipo)}</span>' if diag_tipo else ""
                h += f'<div class="diagnostico" data-tcid="{esc(r["id"])}">'
                h += f'<div class="rec-header"><span class="rec-icon">🔍</span><span class="rec-title diag-band-title">Diagnóstico</span>{diag_tag_html}<button class="info-btn" onclick="openInfoModal(\'capas\')" title="9 capas y sus estados">?</button></div>'
                h += f'<div class="rec-content diag-band-content"><div class="manual-analysis">{_postprocess_capa_blocks(_md_to_html(md_sin_tabla))}</div></div>'
                h += f'<div class="wip-disclaimer-sm">ℹ Análisis sin acceso a Backlog — puede no distinguir bug de feature pendiente. Ver épica <em>system_knowledge.md</em>.</div>'
                h += f'</div>\n'
            # Banda separada: Dimensionamiento del bug
            if dim_md:
                # Quitar el encabezado "### Dimensionamiento del bug" del MD (ya lo metemos en el header de la banda)
                dim_body_md = re.sub(r"^####?\s*Dimensionamiento\s+del\s+bug[^\n]*\n", "", dim_md, count=1, flags=re.IGNORECASE).strip()
                h += f'<div class="dimensionamiento" data-tcid="{esc(r["id"])}">'
                h += f'<div class="rec-header"><span class="rec-icon">📐</span><span class="rec-title diag-band-title">Dimensionamiento del bug</span></div>'
                h += f'<div class="rec-content diag-band-content">{_md_to_html(dim_body_md)}</div>'
                h += f'</div>\n'
        elif any(rr.get("status") == "FAIL" for rr in r.get("runs", [])):
            # Placeholder cuando hay FAIL pero aún sin análisis
            h += f'<div class="diagnostico pendiente" data-tcid="{esc(r["id"])}">'
            h += f'<div class="rec-header"><span class="rec-icon">🔍</span><span class="rec-title diag-band-title">Diagnóstico</span><span class="rec-tag diag-tag">Pendiente análisis</span><button class="info-btn" onclick="openInfoModal(\'capas\')" title="9 capas y sus estados">?</button></div>'
            h += f'<div class="rec-content diag-band-content"><p style="color:#888;font-style:italic">Pendiente análisis. Solicitar <em>"analiza {esc(r["id"])}"</em>. Se generará: diagnóstico (9 capas), soluciones evaluadas con score y plan de acción.</p></div>'
            h += f'</div>\n'

        # Banda de recomendacion: prefiere manual (.md), si no auto
        recomendacion_md = analysis.get("recomendacion", "") if analysis else ""
        if recomendacion_md:
            # Tag simplificado: solo el tipo (el coste y la solución recomendada ya están en la callout debajo)
            rec_tipo = analysis["meta"].get("tipo", "")
            rec_tag_html = f'<span class="rec-tag">{esc(rec_tipo)}</span>' if rec_tipo else ""
            h += f'<div class="recomendacion"><div class="rec-header"><span class="rec-icon">\U0001f4a1</span><span class="rec-title">Recomendacion / Accion</span>{rec_tag_html}</div>'
            h += f'<div class="rec-content">{_md_to_html(recomendacion_md)}</div></div>\n'
        elif r["status"] == "FAIL":
            # Plantilla vacía con estructura — se rellena cuando se hace análisis manual
            h += '<div class="recomendacion fail"><div class="rec-header"><span class="rec-icon">\U0001f4a1</span><span class="rec-title">Recomendación / Acción</span><span class="rec-tag">Pendiente análisis</span></div>'
            h += '<div class="rec-content">'
            h += '<div class="solucion-recomendada" style="background:#1a1a1a;border-color:#444;border-left-color:#777">'
            h += '<span class="sr-label" style="color:#888">Solución recomendada</span>'
            h += '<div class="sr-title" style="color:#aaa;font-style:italic">Pendiente análisis manual</div>'
            h += f'<div class="sr-why" style="color:#888;font-style:italic">Solicitar análisis: <em>"analiza {esc(r["id"])}"</em>. Se generará: diagnóstico (9 capas), soluciones evaluadas con score, plan de acción.</div>'
            h += '</div>'
            h += '<h4 style="color:#888">Soluciones evaluadas</h4>'
            h += '<p style="color:#888;font-style:italic">Pendiente. Aparecerán aquí 3-7 soluciones ordenadas por score (verde/amarillo/rojo) con dependencias y razonamiento.</p>'
            h += '<h4 style="color:#888">Plan de acción</h4>'
            h += '<p style="color:#888;font-style:italic">Pendiente. Aparecerá aquí el detalle de implementación de la solución recomendada.</p>'
            h += '</div></div>\n'
        elif r["status"] == "PASS":
            # Mismo template estructural que FAIL pero en verde, con contenido apropiado para test que pasa
            h += '<div class="recomendacion pass"><div class="rec-header"><span class="rec-icon">\u2713</span><span class="rec-title">Recomendaci\u00f3n / Acci\u00f3n</span><span class="rec-tag">Test correcto</span></div>'
            h += '<div class="rec-content">'
            h += '<div class="solucion-recomendada">'
            h += '<span class="sr-label">Soluci\u00f3n recomendada</span>'
            h += '<div class="sr-title" style="color:#86efac">No requiere acciones</div>'
            h += '<div class="sr-why">El test pasa todas las verificaciones esperadas en todos los runs. Comportamiento del agente correcto y consistente.</div>'
            h += '</div>'
            h += '<h4>Soluciones evaluadas</h4>'
            h += '<p>No aplica \u2014 el test pasa. Mantener vigilancia en pr\u00f3ximos QA runs para detectar regresiones.</p>'
            h += '<h4>Plan de acci\u00f3n</h4>'
            h += '<p>Ninguno. Si en alg\u00fan run futuro pasa a FAIL o INESTABLE, se generar\u00e1 an\u00e1lisis con causa ra\u00edz y soluciones.</p>'
            h += '</div></div>\n'
        h += "</div></div>\n"
    # Resumen agrupado por causa (carga qa/tc_analysis/_resumen.md si existe)
    resumen_md = _load_resumen()
    if resumen_md:
        h += f'<div class="resumen-section">{_md_to_html(resumen_md)}</div>\n'
        h += "</div></div>\n"
    # Modal METODOLOGÍA — KPIs de QA (flakiness, salud, cobertura, regresión)
    kpis = _compute_metodologia_kpis(results)
    prev_meta = _load_previous_meta()
    # Regresión vs run anterior
    regr_html = ""
    if prev_meta:
        curr_pct = int((n_pass / total) * 100) if total else 0
        prev_pct = prev_meta.get("pct", 0)
        prev_pass = prev_meta.get("pass", 0)
        prev_total = prev_meta.get("total", 0)
        delta = curr_pct - prev_pct
        delta_str = f"+{delta}" if delta >= 0 else str(delta)
        delta_cls = "delta-up" if delta > 0 else ("delta-down" if delta < 0 else "delta-neutral")
        regr_html = f"""
        <div class="kpi-section">
          <h3>📈 Regresión vs run anterior</h3>
          <table class="kpi-regr">
            <tr><td>Run actual</td><td>{esc(ts)}</td><td><strong>PASS {curr_pct}%</strong> ({n_pass}/{total})</td></tr>
            <tr><td>Run anterior</td><td>{esc(prev_meta.get("timestamp", "?"))}</td><td>PASS {prev_pct}% ({prev_pass}/{prev_total})</td></tr>
            <tr><td colspan="2"><strong>Δ Variación</strong></td><td class="{delta_cls}"><strong>{delta_str}%</strong></td></tr>
          </table>
        </div>"""
    else:
        regr_html = """
        <div class="kpi-section">
          <h3>📈 Regresión vs run anterior</h3>
          <p class="kpi-no-data"><em>Sin datos del run anterior (este es el primero o no se encontró meta.json previo).</em></p>
        </div>"""
    # Flakiness
    flak_tcs_str = ", ".join(kpis["flakiness"]["tcs"]) if kpis["flakiness"]["tcs"] else "—"
    flak_html = f"""
    <div class="kpi-section kpi-flak">
      <h3 data-legend="Un TC es INESTABLE cuando pasa en algunos runs pero falla en otros. Indica que el sistema no es determinístico — la misma entrada produce resultados distintos. Umbral aceptable: <10%. Si es alto, los tests no son fiables.">Flakiness: {kpis["flakiness"]["pct"]}% <span class="kpi-sub">({kpis["flakiness"]["count"]} TCs INESTABLE de {kpis["flakiness"]["total"]})</span></h3>
      <p>TCs flaky: <code>{esc(flak_tcs_str)}</code></p>
      <p class="kpi-action">Acción si alto: re-correr con <code>--runs 5</code> para confirmar.</p>
    </div>"""
    # Salud componentes
    orq_errors_html = ""
    if kpis["orquestador"]["errors"]:
        items = "".join(f'<li><code>{esc(e["tc"])}</code> — esperaba <code>{esc(e["expected"])}</code>, observó <code>{esc(e["observed"])}</code></li>' for e in kpis["orquestador"]["errors"])
        orq_errors_html = f'<p class="kpi-sub">Errores:</p><ul>{items}</ul>'
    salud_html = f"""
    <div class="kpi-section">
      <h3>🏥 Salud de componentes críticos</h3>
      <div class="kpi-component">
        <h4>Orquestador</h4>
        <div class="kpi-bar-row" data-legend="Cada TC declara su grupo_intent esperado (ej. G5, COMPRA-INV). El Orquestador clasifica el input del usuario en el primer turno. Este % indica cuántos TCs aciertan la clasificación esperada. Si baja: el Orquestador está fallando al clasificar inputs.">
          <span class="kpi-label">Clasificación correcta</span>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{kpis["orquestador"]["pct"]}%"></div></div>
          <span class="kpi-value">{kpis["orquestador"]["pct"]}%</span>
        </div>
        <p class="kpi-sub">{kpis["orquestador"]["ok"]}/{kpis["orquestador"]["total"]} TCs clasifican el grupo_intent esperado</p>
        {orq_errors_html}
      </div>
      <div class="kpi-component">
        <h4>Compra (slot-filling)</h4>
        <div class="kpi-bar-row" data-legend="% de turnos donde Compra extrajo el slot 'producto' del utterance del usuario (ej. 'rosas rojas', 'tulipanes'). Si baja: el Compra no está identificando qué producto pide el usuario.">
          <span class="kpi-label">Producto extraído</span>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{kpis["compra"]["producto"]}%"></div></div>
          <span class="kpi-value">{kpis["compra"]["producto"]}%</span>
        </div>
        <div class="kpi-bar-row" data-legend="% de turnos donde Compra detectó la ocasión (Regalo, Decoracion, Funebre, etc.) del input del usuario. Si baja: el playbook no infiere la intención de uso.">
          <span class="kpi-label">Ocasión detectada</span>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{kpis["compra"]["ocasion"]}%"></div></div>
          <span class="kpi-value">{kpis["compra"]["ocasion"]}%</span>
        </div>
        <div class="kpi-bar-row" data-legend="% de turnos donde se asignó modo_tono (estandar/solemne/corporativo). El Orquestador detecta esto en el primer utterance del usuario. Si baja: la detección de tono está fallando.">
          <span class="kpi-label">Modo_tono asignado</span>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width:{kpis["compra"]["modo_tono"]}%"></div></div>
          <span class="kpi-value">{kpis["compra"]["modo_tono"]}%</span>
        </div>
        <p class="kpi-sub">Sobre {kpis["compra"]["turnos"]} turnos totales</p>
      </div>
    </div>"""
    # Cobertura grupos
    grupos_rows = ""
    icon_map = {"ok": "✅", "low": "⚠️", "missing": "❌", "extra": "➕"}
    label_map = {"ok": "cubierto", "low": "baja cobertura", "missing": "FALTA cubrir", "extra": "extra"}
    for g in kpis["cobertura_grupos"]["items"]:
        grupos_rows += f'<tr><td><code>{esc(g["grupo"])}</code> {esc(g["nombre"])}</td><td>{icon_map.get(g["status"],"")} {label_map.get(g["status"],"")}</td><td>{g["count"]} TC{"s" if g["count"]!=1 else ""}</td></tr>'
    modos_rows = ""
    for m in kpis["cobertura_modos"]["items"]:
        modos_rows += f'<tr><td><code>{esc(m["modo"])}</code></td><td>{icon_map.get(m["status"],"")} {label_map.get(m["status"],"")}</td><td>{m["count"]} TC{"s" if m["count"]!=1 else ""}</td></tr>'
    cobertura_html = f"""
    <div class="kpi-section">
      <h3>🎯 Cobertura del test suite</h3>
      <div class="kpi-component">
        <h4>Grupos del Orquestador (clasificación del input) — {kpis["cobertura_grupos"]["ok"]}/{kpis["cobertura_grupos"]["total"]} cubiertos ({kpis["cobertura_grupos"]["pct"]}%)</h4>
        <table class="kpi-cobertura">{grupos_rows}</table>
      </div>
      <div class="kpi-component">
        <h4>Modos de tono (cómo modula el agente la respuesta) — {kpis["cobertura_modos"]["ok"]}/{kpis["cobertura_modos"]["total"]} cubiertos ({kpis["cobertura_modos"]["pct"]}%)</h4>
        <table class="kpi-cobertura">{modos_rows}</table>
      </div>
    </div>"""
    h += f"""
<div id="metodologia-modal" class="modal hidden">
  <div class="modal-overlay" onclick="closeMetodologia()"></div>
  <div class="modal-content modal-metodologia">
    <button class="modal-close" onclick="closeMetodologia()">&times;</button>
    <h2>📊 Metodología de evaluación QA</h2>
    <p class="modal-sub">{total} test cases · {n_pass} PASS · {n_inst} INESTABLE · {n_fail} FAIL · {ts}</p>
    {flak_html}
    {salud_html}
    {regr_html}
    {cobertura_html}
  </div>
</div>
"""
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
<!-- Modal: Las 9 capas + estados (unificado) -->
<div class="info-modal-overlay" id="modal-capas">
  <div class="info-modal">
    <button class="info-modal-close" onclick="closeInfoModal('capas')">&times;</button>
    <h3>Las 9 capas del análisis QA</h3>
    <p>Cada análisis evalúa estas 9 capas obligatoriamente para identificar la causa raíz del bug:</p>
    <table>
      <tr><td><strong>1. Comportamiento</strong></td><td>Playbooks, Examples, Generators</td></tr>
      <tr><td><strong>2. Routing</strong></td><td>Flows, Pages, Intents, Entity Types</td></tr>
      <tr><td><strong>3. Parámetros / Slots</strong></td><td>Paso de slots entre playbooks y tools</td></tr>
      <tr><td><strong>4. Integración</strong></td><td>Tools, Webhooks, llamadas al backend</td></tr>
      <tr><td><strong>5. Datos</strong></td><td>Google Sheet (inventario, agent_copy, negocio)</td></tr>
      <tr><td><strong>6. Infraestructura</strong></td><td>Environments, Versions, Agent Config</td></tr>
      <tr><td><strong>7. Modelo / LLM</strong></td><td>Comportamiento de Gemini (alucinaciones)</td></tr>
      <tr><td><strong>8. Histórico</strong></td><td>Regresiones — git log del playbook</td></tr>
      <tr><td><strong>9. Test</strong></td><td>Calibración del check regex del TC</td></tr>
    </table>
    <h3 style="margin-top:20px;">Estados posibles de cada capa</h3>
    <table>
      <tr><td style="width:130px;"><strong>🔴 problema</strong></td><td>Capa <em>comprobada con fuente</em>. ES causa del bug.</td></tr>
      <tr><td><strong>🟢 ok</strong></td><td>Capa <em>comprobada con fuente</em>. NO es causa del bug.</td></tr>
      <tr><td><strong>🟡 supuesta</strong></td><td>No se pudo comprobar (falta documentación o info externa).</td></tr>
      <tr><td><strong>⚪ N/A</strong></td><td>Esta capa no aplica al tipo de bug analizado.</td></tr>
    </table>
    <p style="margin-top:12px;">Las marcas <strong>🔴</strong> y <strong>🟢</strong> requieren citar la fuente (ej: <code>Read compra.yaml</code>, <code>git log</code>, <code>gh pr view</code>, <code>gcloud logging</code>, <code>curl URL</code>).</p>
  </div>
</div>
<script>
function toggle(el){el.nextElementSibling.classList.toggle('open');el.querySelector('.arrow').classList.toggle('open')}
function togglePatterns(){var b=document.querySelector('.patterns-body');var a=document.querySelector('.patterns-arrow');if(b){b.classList.toggle('open');a.classList.toggle('open');}}
function openRoiModal(btn){var val=btn.dataset.roiVal,tcs=btn.dataset.roiTcs,esf=btn.dataset.roiEsf;var b=document.getElementById('roi-modal-body');if(!b)return;b.innerHTML='<p class="rmi-def"><strong>Tasa de resolución</strong> — cuántos TCs puedes cerrar por hora de trabajo invertida en el fix.</p><div class="rmi-section"><div class="rmi-lbl">Fórmula</div><div class="rmi-formula">ROI = TCs resueltos ÷ esfuerzo (h)</div></div><div class="rmi-section"><div class="rmi-lbl">Este fix</div><div class="rmi-row"><span>TCs resueltos</span><span>'+(tcs||'—')+'</span></div><div class="rmi-row"><span>Esfuerzo estimado</span><span>'+(esf||'—')+'</span></div><div class="rmi-row rmi-result"><span>ROI resultante</span><span>'+(val||'—')+' TCs/h</span></div></div>';document.getElementById('roi-modal-overlay').classList.add('open');}
function closeRoiModal(){var o=document.getElementById('roi-modal-overlay');if(o)o.classList.remove('open');}
function toggleSelectAll(cb){document.querySelectorAll('.opt-check').forEach(function(c){c.checked=cb.checked});updateRunButton();}
function filterBy(s){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>{if(s==='all'){t.classList.remove('hidden')}else{t.classList.toggle('hidden',t.dataset.status!==s)}});if(s!=='all')document.querySelectorAll('.card[data-filter="'+s+'"]').forEach(c=>c.classList.add('active'))}
function filterByGroup(g){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',!t.dataset.group.includes(g)))}
function filterByType(tp){document.querySelectorAll('.fbtn,.card').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.t').forEach(t=>t.classList.toggle('hidden',t.dataset.type!==tp))}

// Histórico: fetch único a qa/history.json estático (publicado en gh-pages).
// Antes: ~25 llamadas a GitHub API → rate limit 60 req/h sin auth.
// Ahora: 1 fetch a ../history.json. Sin rate limit, sin latencia.
async function openHistorial(){
  const modal=document.getElementById('historial-modal');
  const loading=document.getElementById('hist-loading');
  const table=document.getElementById('hist-table');
  modal.classList.remove('hidden');
  loading.classList.remove('hidden');
  loading.textContent='Cargando histórico...';
  table.classList.add('hidden');
  try{
    const rows=await fetch('../history.json',{cache:'no-cache'}).then(r=>{
      if(!r.ok) throw new Error('history.json no disponible (HTTP '+r.status+')');
      return r.json();
    });
    if(!Array.isArray(rows)||rows.length===0){
      loading.textContent='No hay metadatos históricos disponibles.';
      return;
    }
    const currentTs=document.title.match(/\\d{4}-\\d{2}-\\d{2}\\s+\\d{2}:\\d{2}/);
    const tbody=table.querySelector('tbody');
    tbody.innerHTML='';
    rows.forEach(m=>{
      const tr=document.createElement('tr');
      if(currentTs && m.timestamp===currentTs[0]) tr.classList.add('current');
      const backfilled=m.backfilled?' <span class="backfilled-tag">retroactivo</span>':'';
      const url=`../${m.dir}/qa_latest.html`;
      tr.innerHTML=`<td>${m.timestamp||'?'}${backfilled}</td><td>${m.total??'?'}</td><td class="ok">${m.pass??'?'}</td><td class="inst">${m.inst??'?'}</td><td class="fail">${m.fail??'?'}</td><td>${m.pct??'?'}%</td><td><a href="${url}">Ver</a></td>`;
      tbody.appendChild(tr);
    });
    loading.classList.add('hidden');
    table.classList.remove('hidden');
  }catch(e){
    loading.textContent='Error cargando histórico: '+e.message;
  }
}
function closeHistorial(){document.getElementById('historial-modal').classList.add('hidden')}
function openMetodologia(){document.getElementById('metodologia-modal').classList.remove('hidden')}
function closeMetodologia(){document.getElementById('metodologia-modal').classList.add('hidden')}

// === Optimizar / Borrar análisis / Run ===
// Activar botón Optimizar si hay TCs en FAIL en el DOM
function initOptimizeButton(){
  var fails = document.querySelectorAll('.t[data-status="FAIL"]');
  var btn = document.getElementById('btn-optimize');
  if (!btn) return;
  if (fails.length > 0){
    btn.classList.remove('dl-disabled');
    btn.style.cursor = 'pointer';
  }
}
// Activar botón Borrar análisis si hay bloques LLM aplicados en el DOM
function initDeleteButton(){
  var analyses = document.querySelectorAll('.diag-block[data-tcid]');
  var btn = document.getElementById('btn-delete');
  if (!btn) return;
  if (analyses.length > 0){
    btn.classList.remove('dl-disabled');
    btn.style.cursor = 'pointer';
  }
}
// Set panel mode: 'optimize' (FAIL TCs, generate prompt) o 'delete' (TCs con .md, generate rm commands)
function setPanelMode(mode){
  var title = document.getElementById('optimize-panel-title');
  var run = document.getElementById('btn-run');
  var thead = document.querySelector('#optimize-panel thead tr');
  if (mode === 'optimize'){
    title.textContent = 'TCs en FAIL — selecciona los que quieras optimizar';
    run.textContent = '▶ Run';
    run.setAttribute('onclick', 'runOptimize()');
    thead.innerHTML = '<th><input type="checkbox" id="opt-select-all" title="Seleccionar todos" onchange="toggleSelectAll(this)"></th><th>ID</th><th>Nombre</th><th>Check fallido</th><th>Respuesta del agente</th>';
  } else {
    title.textContent = 'TCs con análisis LLM aplicado — selecciona los que quieras borrar';
    run.textContent = '\U0001f5d1 Borrar seleccionados';
    run.setAttribute('onclick', 'runDelete()');
    thead.innerHTML = '<th></th><th>ID</th><th>Análisis</th>';
  }
}
function openOptimizePanel(){
  var btn = document.getElementById('btn-optimize');
  if (btn.classList.contains('dl-disabled')) return;
  var panel = document.getElementById('optimize-panel');
  if (!panel) return;
  setPanelMode('optimize');
  // Construir tabla desde el DOM
  var tbody = document.getElementById('optimize-tbody');
  tbody.innerHTML = '';
  var fails = document.querySelectorAll('.t[data-status="FAIL"]');
  fails.forEach(function(tc){
    var tid = tc.querySelector('.tid') ? tc.querySelector('.tid').textContent.trim() : '?';
    var tname = tc.querySelector('.tname') ? tc.querySelector('.tname').textContent.trim() : '';
    // user utterance: primer ta-user > .ta-text (o .trace-text del primer trace-user)
    var userEl = tc.querySelector('.ta-user .ta-text') || tc.querySelector('.trace-user .trace-text') || tc.querySelector('.turn-user .text');
    var userTxt = userEl ? userEl.textContent.trim().replace(/^"|"$/g, '') : '';
    // agent response: primer ta-agent > .ta-text
    var agentEl = tc.querySelector('.ta-agent .ta-text') || tc.querySelector('.trace-agent .trace-text') || tc.querySelector('.turn-agent .text');
    var agentTxt = agentEl ? agentEl.textContent.trim().replace(/^"|"$/g, '').substring(0, 120) : '';
    // failed check: primer .turn-check.fail (render clásico) o primer .ta-bullets.fail li (render v3)
    var checkEl = tc.querySelector('.turn-check.fail') || tc.querySelector('.ta-bullets.fail li');
    var checkTxt = checkEl ? checkEl.textContent.trim() : '';
    // URL al log JSON completo (del botón JSON del TC)
    var logBtn = tc.querySelector('.log-btn');
    var jsonUrl = logBtn ? logBtn.getAttribute('href') : '';
    // group (extra metadato)
    var group = tc.getAttribute('data-group') || '';
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><input type="checkbox" class="opt-check" data-tid="' + tid + '" data-tname="' + tname.replace(/"/g, '&quot;') + '" data-group="' + group + '"></td>' +
                   '<td>' + tid + '</td>' +
                   '<td>' + tname + '</td>' +
                   '<td>' + checkTxt + '</td>' +
                   '<td>' + agentTxt + (agentTxt.length === 120 ? '…' : '') + '</td>';
    // attach data hidden for prompt
    tr.querySelector('input').dataset.user = userTxt;
    tr.querySelector('input').dataset.agent = agentTxt;
    tr.querySelector('input').dataset.check = checkTxt;
    tr.querySelector('input').dataset.jsonurl = jsonUrl;
    tbody.appendChild(tr);
  });
  panel.classList.remove('hidden');
  // attach listeners to checkboxes
  document.querySelectorAll('.opt-check').forEach(function(cb){
    cb.addEventListener('change', updateRunButton);
  });
  updateRunButton();
}
function openDeletePanel(){
  var btn = document.getElementById('btn-delete');
  if (btn.classList.contains('dl-disabled')) return;
  var panel = document.getElementById('optimize-panel');
  if (!panel) return;
  setPanelMode('delete');
  // Construir tabla con TCs que tienen análisis LLM aplicado
  var tbody = document.getElementById('optimize-tbody');
  tbody.innerHTML = '';
  var blocks = document.querySelectorAll('.diag-block[data-tcid]');
  var seen = {};
  blocks.forEach(function(b){
    var tid = b.getAttribute('data-tcid');
    if (seen[tid]) return;
    seen[tid] = true;
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><input type="checkbox" class="opt-check" data-tid="' + tid + '"></td>' +
                   '<td>' + tid + '</td>' +
                   '<td>Causa raíz LLM aplicada</td>';
    tbody.appendChild(tr);
  });
  panel.classList.remove('hidden');
  document.querySelectorAll('.opt-check').forEach(function(cb){
    cb.addEventListener('change', updateRunButton);
  });
  updateRunButton();
}
function updateRunButton(){
  var run = document.getElementById('btn-run');
  if (!run) return;
  var checked = document.querySelectorAll('.opt-check:checked');
  if (checked.length > 0){
    run.classList.remove('dl-disabled');
    run.style.cursor = 'pointer';
  } else {
    run.classList.add('dl-disabled');
    run.style.cursor = 'not-allowed';
  }
}
function runOptimize(){
  var run = document.getElementById('btn-run');
  if (run.classList.contains('dl-disabled')) return;
  var checked = document.querySelectorAll('.opt-check:checked');
  if (checked.length === 0) return;
  var ids = [];
  checked.forEach(function(cb){ ids.push(cb.dataset.tid); });
  var prompt = '/qa-tc-analyzer ' + ids.join(' ');
  navigator.clipboard.writeText(prompt).then(function(){
    var fb = document.getElementById('btn-run-feedback');
    fb.textContent = '✓ Copiado — pega en Claude';
    fb.classList.add('visible');
    setTimeout(function(){ fb.classList.remove('visible'); }, 3000);
  }).catch(function(err){
    var fb = document.getElementById('btn-run-feedback');
    fb.textContent = '✗ Error al copiar: ' + err.message;
    fb.classList.add('visible');
  });
}
function runDelete(){
  var run = document.getElementById('btn-run');
  if (run.classList.contains('dl-disabled')) return;
  var checked = document.querySelectorAll('.opt-check:checked');
  if (checked.length === 0) return;
  // Extraer TS de la URL (formato: /qa/<TS>/qa_latest.html)
  var m = window.location.pathname.match(/\\/qa\\/([0-9_]+)\\//);
  var ts = m ? m[1] : '<TS>';
  var P = '\\n';
  var cmd = '# Borrar análisis LLM seleccionados + regenerar + publicar' + P;
  checked.forEach(function(cb){
    cmd += 'rm qa/tc_analysis/' + cb.dataset.tid + '.md' + P;
  });
  cmd += 'python3 qap/regenerate_html.py --ts ' + ts + ' --out /tmp/qa.html' + P;
  cmd += './qap/publish_html.sh /tmp/qa.html ' + ts + P;
  navigator.clipboard.writeText(cmd).then(function(){
    var fb = document.getElementById('btn-run-feedback');
    fb.textContent = '✓ Copiado — pega en terminal';
    fb.classList.add('visible');
    setTimeout(function(){ fb.classList.remove('visible'); }, 3000);
  }).catch(function(err){
    var fb = document.getElementById('btn-run-feedback');
    fb.textContent = '✗ Error al copiar: ' + err.message;
    fb.classList.add('visible');
  });
}
function closePanel(){
  var panel = document.getElementById('optimize-panel');
  panel.classList.add('hidden');
  document.getElementById('optimize-tbody').innerHTML = '';
  // Resetear Run a desactivado
  var run = document.getElementById('btn-run');
  run.classList.add('dl-disabled');
  run.style.cursor = 'not-allowed';
  // Limpiar feedback
  var fb = document.getElementById('btn-run-feedback');
  fb.textContent = '';
  fb.classList.remove('visible');
}
// Init al cargar
function initButtons(){ initOptimizeButton(); initDeleteButton(); }
document.addEventListener('DOMContentLoaded', initButtons);
if (document.readyState !== 'loading') initButtons();

document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeHistorial();closeMetodologia();closePanel();}});

// Info modals (Capas / Marcas) — abiertas desde botones "?" en "Causa raíz"
function openInfoModal(id){document.getElementById('modal-'+id).classList.add('visible');}
function closeInfoModal(id){document.getElementById('modal-'+id).classList.remove('visible');}
// Cerrar al hacer clic fuera de la modal
document.addEventListener('click',function(e){if(e.target.classList&&e.target.classList.contains('info-modal-overlay')){e.target.classList.remove('visible');}});
// Cerrar con Escape
document.addEventListener('keydown',function(e){if(e.key==='Escape'){document.querySelectorAll('.info-modal-overlay.visible').forEach(function(m){m.classList.remove('visible');});}});
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
    logs_dir = out_dir / f"qa_{ts_file}_logs"
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
    # Guardar logs JSON por TC (US-QA-09: análisis basado en log) — para investigación profunda
    logs_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        log_data = {
            "tc_id": r["id"], "tc_name": r["name"],
            "group": r["group"], "type": r["type"],
            "status": r["status"], "pass_count": r["pass_count"], "total_runs": r["total_runs"],
            "ts": ts, "ts_file": ts_file,
            "runs": [{
                "run_id": ri + 1, "pass": run["pass"],
                "turns": [{
                    "turn": turn["turn"], "user": turn["user"], "agent": turn["agent"],
                    "playbook": turn.get("playbook", ""),  # US-QA-09: playbook activo
                    "params": turn["params"], "checks": turn["checks"],
                    "trace": turn.get("trace", {}),  # US-QA-09: trace del API
                } for turn in run["turns"]],
            } for ri, run in enumerate(r["runs"])],
            "metadata": meta["versions"],
        }
        log_path = logs_dir / f'{r["id"]}.json'
        with open(log_path, "w", encoding="utf-8") as f: json.dump(log_data, f, indent=2, ensure_ascii=False)
    with open(txt_path, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
    with open(html_path, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, txt_path.name, logs_dir_name=logs_dir.name))
    with open(meta_path, "w", encoding="utf-8") as f: json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"\n  TXT: {txt_path}\n  HTML: {html_path}\n  META: {meta_path}\n  LOGS: {logs_dir}/ ({len(results)} archivos)")
    if IS_CI:
        # Latest copies sin timestamp, para URL fija publicada en GitHub Pages.
        latest_txt = out_dir / "qa_latest.txt"
        latest_html = out_dir / "qa_latest.html"
        latest_meta = out_dir / "qa_latest.meta.json"
        latest_logs_dir = out_dir / "qa_latest_logs"
        with open(latest_txt, "w", encoding="utf-8") as f: f.write(generate_txt(results, ts))
        with open(latest_html, "w", encoding="utf-8") as f: f.write(generate_html(results, ts, latest_txt.name, logs_dir_name=latest_logs_dir.name))
        with open(latest_meta, "w", encoding="utf-8") as f: json.dump(meta, f, indent=2, ensure_ascii=False)
        # Copiar logs JSON a qa_latest_logs/ para URL fija
        latest_logs_dir.mkdir(parents=True, exist_ok=True)
        for r in results:
            src = logs_dir / f'{r["id"]}.json'
            dst = latest_logs_dir / f'{r["id"]}.json'
            if src.exists():
                shutil.copy2(src, dst)
        print(f"  TXT (latest): {latest_txt}\n  HTML (latest): {latest_html}\n  META (latest): {latest_meta}\n  LOGS (latest): {latest_logs_dir}/")
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
    parser.add_argument("--test", help="Ejecutar TC(s). Uno: TC-C29. Varios: TC-C29,TC-C30,TC-DECO-02")
    parser.add_argument("--type", help="Filtrar: REG, NEW, EDGE")
    parser.add_argument("--runs", type=int, default=3, help="Runs por TC (default 3)")
    parser.add_argument("--workers", type=int, default=1, help="TCs en paralelo (default 1). Seguro hasta 8 en europe-west1.")
    parser.add_argument("--list", action="store_true", help="Listar TCs")
    args = parser.parse_args()
    RUNS = max(1, min(args.runs, 5))
    if args.list:
        for t in TESTS:
            print(f"  {t['id']:12s} [{t['type']:4s}] [{t['group']:12s}] {t['name']}")
        return
    tests = TESTS
    if args.test:
        wanted = [tid.strip() for tid in args.test.split(",")]
        tests = [t for t in TESTS if t["id"] in wanted]
        missing = [tid for tid in wanted if tid not in {t["id"] for t in tests}]
        if missing: print(f"TCs no encontrados: {', '.join(missing)}"); return
        if not tests: print(f"TCs {args.test} no encontrados."); return
    elif args.type:
        tests = [t for t in TESTS if t["type"] == args.type]
        if not tests: print(f"Tipo {args.type} no encontrado."); return
    env = "Cloud Shell" if IS_CLOUD_SHELL else f"Local ({platform.system()})"
    print(f"QA Petal v23 \u2014 {env}")
    print(f"Orq {ORQ_VERSION} | Compra {COMPRA_VERSION} | Checkout {CHECKOUT_VERSION} | Registro {REGISTRO_VERSION}")
    print(f"Ejecutando {len(tests)} tests \u00d7 {RUNS} runs...\n")
    token = get_token()
    workers = max(1, min(args.workers, 10))
    _print_lock = threading.Lock()

    def _run_one(test):
        with _print_lock:
            print(f"  {test['id']} \u2014 {test['name']}...", end="", flush=True)
        r = run_test(token, test, RUNS)
        with _print_lock:
            print(f" {r['status']} ({r['pass_count']}/{r['total_runs']})")
        return r

    if workers > 1:
        print(f"[paralelo: {workers} workers]\n")
        with ThreadPoolExecutor(max_workers=workers) as executor:
            results = list(executor.map(_run_one, tests))
    else:
        results = [_run_one(test) for test in tests]

    for r in results: print_result(r)
    generate_reports(results)


if __name__ == "__main__":
    main()
