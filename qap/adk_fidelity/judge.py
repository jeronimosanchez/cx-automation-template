"""Juez Gemma — capa de evaluación NO determinista del cribador.

Las dos capas:
  · check_turn (regex, en test_qa_playbooks)  → lo DURO (precio, tool, email, callejones)
  · judge.py  (este, Gemma)                   → lo BLANDO que el regex no puede medir

Las dimensiones NO se inventan: son los principios de diseño del KB (kb_ag_global)
que requieren juicio, no coincidencia de patrones. El regex no puede medir "¿suena
humano?" — Gemma sí.

ARQUITECTURA (independiente del hardware — igual en Mac y en Kaggle):
  1. Qwen simula Petal → transcripts        (fase A, NO toca a Gemma)
  2. Gemma juzga esos transcripts           (fase B, este módulo)
  Secuencial: el juez necesita la respuesta YA generada. Solo un modelo en VRAM a la vez.

INDEPENDENCIA: el juez (Gemma) es de OTRA familia que el simulador (Qwen) → no se juzga
a sí mismo (rompe la circularidad). Gemma es la familia de Gemini = criterio cercano a CX.

USO (NO ejecutar mientras hay un run de Qwen vivo — compiten por memoria):
    ollama pull gemma2:27b           # Kaggle/GPU. En Mac 24GB: gemma2:9b o gemma3:12b
    python judge.py --demo           # juzga unos turnos de fidelity_result.json
"""
import os
import json
import argparse
import requests

# Modelo del juez. Kaggle (32GB): gemma2:27b. Mac (24GB, junto a otras apps): gemma2:9b/gemma3:12b.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gemma2:27b")
OLLAMA = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")

# --- Dimensiones blandas = principios del KB que el regex NO puede verificar ---
# (key, principio, qué pregunta el juez). Ajustable: añadir/quitar según calibración.
DIMENSIONS = [
    ("tono",          "P5",  "¿El tono encaja con lo que el agente sabe del usuario en ese momento (situación, perfil, necesidad)?"),
    ("palabras",      "P9",  "¿Reutiliza el vocabulario EXACTO del usuario, en vez de traducirlo a su propia jerga?"),
    ("invisible",     "P11", "¿Mantiene invisible la fontanería interna (no menciona módulos, flujos, parámetros, herramientas)?"),
    ("confirmacion",  "P12", "¿Confirma lo entendido en lenguaje natural, no como un volcado de datos técnicos?"),
    ("engancha",      "P8",  "¿Reconoce lo que el usuario dijo, aporta valor y deja la puerta abierta a seguir (no cierra en seco)?"),
    ("alternativa",   "P13", "Si hay una negativa, ¿va acompañada de una alternativa concreta? (N/A si no hay 'no')"),
]

VERDICTS = ("PASS", "PARTIAL", "FAIL", "NA")


def build_judge_prompt(user_text: str, agent_text: str, prior: str = "") -> str:
    dims = "\n".join(f'  - "{k}" ({p}): {q}' for k, p, q in DIMENSIONS)
    ctx = f"\nCONTEXTO PREVIO (turnos anteriores):\n{prior}\n" if prior else ""
    keys = ", ".join(f'"{k}"' for k, _, _ in DIMENSIONS)
    return (
        "Eres un evaluador EXPERTO de calidad conversacional de un agente de atención al "
        "cliente (floristería). Juzgas SOLO la calidad BLANDA de la respuesta del agente, "
        "no si los datos son correctos (eso se valida por separado).\n"
        f"{ctx}\n"
        f"USUARIO dijo: {user_text}\n\n"
        f"AGENTE respondió: {agent_text}\n\n"
        "Evalúa CADA dimensión con un veredicto y una razón de UNA línea:\n"
        f"{dims}\n\n"
        f'Veredictos posibles: PASS (cumple), PARTIAL (a medias), FAIL (no cumple), NA (no aplica).\n'
        f"Responde SOLO JSON válido con esta forma exacta (claves: {keys}):\n"
        '{"tono": {"verdict": "PASS", "reason": "..."}, ...}'
    )


def judge_turn(user_text: str, agent_text: str, prior: str = "", model: str = None) -> dict:
    """Llama a Gemma (Ollama) y devuelve el veredicto por dimensión. format=json fuerza JSON."""
    prompt = build_judge_prompt(user_text, agent_text, prior)
    try:
        r = requests.post(
            f"{OLLAMA}/api/chat",
            json={
                "model": model or JUDGE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",          # Ollama fuerza salida JSON parseable
                "stream": False,
                "options": {"temperature": 0.0, "seed": 42},  # juicio reproducible
            },
            timeout=120,
        )
        content = r.json()["message"]["content"]
        verdicts = json.loads(content)
    except Exception as e:
        return {"_error": str(e)[:160]}
    # Normaliza: solo dimensiones conocidas, veredictos válidos
    out = {}
    for k, _, _ in DIMENSIONS:
        v = verdicts.get(k) or {}
        verdict = str(v.get("verdict", "")).upper()
        out[k] = {
            "verdict": verdict if verdict in VERDICTS else "FAIL",
            "reason": str(v.get("reason", ""))[:200],
        }
    return out


def score(verdicts: dict) -> dict:
    """Resume un dict de veredictos: cuántas PASS / PARTIAL / FAIL (ignora NA y _error)."""
    c = {"PASS": 0, "PARTIAL": 0, "FAIL": 0, "NA": 0}
    for k, v in verdicts.items():
        if k.startswith("_"):
            continue
        c[v["verdict"]] = c.get(v["verdict"], 0) + 1
    applicable = c["PASS"] + c["PARTIAL"] + c["FAIL"]
    c["soft_pass_rate"] = round(c["PASS"] / applicable, 2) if applicable else None
    return c


def _demo():
    """Juzga unos turnos de un run de fidelidad ya existente (fidelity_result.json)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fidelity_result.json")
    if not os.path.exists(path):
        print("No hay fidelity_result.json — corre antes run_fidelity.py.")
        return
    data = json.load(open(path))
    print(f"Juez: {JUDGE_MODEL} | dimensiones: {[k for k,_,_ in DIMENSIONS]}\n")
    shown = 0
    for row in data.get("rows", []):
        for t in row["detail"]["turns"]:
            if not t.get("agent"):
                continue
            v = judge_turn(t["user"], t["agent"])
            if "_error" in v:
                print(f"[{row['id']}] ERROR juez: {v['_error']}")
                return
            s = score(v)
            print(f"[{row['id']}] soft_pass={s['soft_pass_rate']} "
                  f"(P{s['PASS']}/PA{s['PARTIAL']}/F{s['FAIL']}/NA{s['NA']})")
            for k, vv in v.items():
                if not k.startswith("_") and vv["verdict"] in ("FAIL", "PARTIAL"):
                    print(f"     ⚠ {k}: {vv['verdict']} — {vv['reason']}")
            shown += 1
            if shown >= 5:
                return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="juzga 5 turnos de fidelity_result.json")
    args = ap.parse_args()
    if args.demo:
        _demo()
    else:
        print("Uso: python judge.py --demo  (requiere Gemma en Ollama y NINGÚN run de Qwen vivo)")
