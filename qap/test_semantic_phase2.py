#!/usr/bin/env python3
"""
test_semantic_phase2.py — Evaluación semántica (fase 2) sobre logs del runner QA.

Lee los JSONs per-TC que el runner ya guarda en ~/petal-qa/qa_*_logs/ y evalúa
semánticamente si la respuesta del agente cumplió el objetivo, independientemente
de si coincide con los keywords del check determinístico.

Lógica de dos fases:
  Fase 1 — not_expected (determinístico): si dispara → FAIL definitivo, sin LLM.
  Fase 2 — checks (LLM semántico, dos mensajes):
    Mensaje 1 → el LLM lee la definición del TC (objetivo + criterios por turno).
    Mensaje 2 → el LLM analiza la ejecución real y emite veredicto.

Discrepancias que reporta:
  ⚠ FALSO POS — Runner=FAIL pero LLM=PASS: el agente estaba bien, el check es demasiado literal.
  🔴 FALSO NEG — Runner=PASS pero LLM=FAIL: el agente estaba mal, el runner no lo vio.

Uso:
  python qap/test_semantic_phase2.py                         # último run (Ollama)
  python qap/test_semantic_phase2.py --mlx                   # usar MLX (Apple Silicon)
  python qap/test_semantic_phase2.py --run 20260616_084859   # run concreto
  python qap/test_semantic_phase2.py --tc TC-R04,TC-BODA-01  # filtrar TCs
  python qap/test_semantic_phase2.py --only-disc             # solo discrepancias
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests
import yaml

PETAL_QA_DIR  = Path.home() / "petal-qa"
TC_YAML       = Path(__file__).parent / "tc_1_1.yaml"

# Ollama (por defecto)
OLLAMA_URL    = "http://localhost:11434/api/chat"
OLLAMA_MODEL  = "qwen2.5:14b"

# MLX — OpenAI-compatible
MLX_URL       = "http://localhost:8081/v1/chat/completions"
MLX_MODEL     = "mlx-community/Qwen3-14B-4bit"

MAX_AGENT_CHARS = 400  # truncar respuestas largas para no saturar el contexto del LLM


# ── helpers ──────────────────────────────────────────────────────────────────

def find_latest_logs_dir():
    dirs = sorted(d for d in PETAL_QA_DIR.iterdir() if d.is_dir() and "_logs" in d.name)
    if not dirs:
        sys.exit(f"No se encontró ningún directorio de logs en {PETAL_QA_DIR}")
    return dirs[-1]


def load_tc_meta(path):
    with open(path, encoding="utf-8") as f:
        tcs = yaml.safe_load(f)
    return {tc["id"]: tc for tc in tcs}


def _truncar(text):
    t = text[:MAX_AGENT_CHARS]
    return t + " [...]" if len(text) > MAX_AGENT_CHARS else t


def _bloque_definicion(tc_id, tc_meta):
    """Construye el bloque de texto con la definición del TC (objetivo + criterios)."""
    name     = tc_meta.get("name", tc_id)
    objetivo = tc_meta.get("objetivo", "")
    turns    = tc_meta.get("turns", [])

    lines = [f"TC: {tc_id} — {name}"]
    if objetivo:
        lines.append(f"Objetivo: {objetivo}")
    lines.append("")
    lines.append("Turnos y criterios orientativos:")
    for i, t in enumerate(turns, 1):
        checks = t.get("checks", [])
        c_desc = " / ".join(checks) if checks else "(sin criterios)"
        lines.append(f"  Turno {i}: el usuario dice \"{t.get('user', '')}\"")
        lines.append(f"           criterios: {c_desc}")
    return "\n".join(lines)


def _bloque_ejecucion(log_turns):
    """Construye el bloque de texto con la ejecución real del TC."""
    lines = ["Ejecución real del agente:"]
    for turn in log_turns:
        agent_text = _truncar(turn.get("agent", ""))
        lines.append(f"  Turno {turn['turn']}:")
        lines.append(f"    Usuario: \"{turn['user']}\"")
        lines.append(f"    Agente:  \"{agent_text}\"")
    return "\n".join(lines)


def _chat_mlx(messages, max_tokens):
    r = requests.post(MLX_URL, json={
        "model": MLX_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }, timeout=120)
    return r.json()["choices"][0]["message"]["content"].strip()


def _chat_ollama(messages, num_predict):
    r = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "messages": messages,
        "options": {"temperature": 0, "num_predict": num_predict},
        "stream": False,
    }, timeout=120)
    return r.json()["message"]["content"].strip()


def evaluar_tc_llm(tc_id, tc_meta, log_turns, use_mlx=False):
    """Fase 2: el LLM lee el TC en YAML (mensaje 1) y luego juzga la ejecución (mensaje 2)."""
    # Si ningún turno tiene checks, no hay nada que el LLM pueda juzgar
    has_checks = any(t.get("checks") for t in tc_meta.get("turns", []))
    if not has_checks:
        return "—", "(sin checks)"

    tc_def  = _bloque_definicion(tc_id, tc_meta)
    exec_log = _bloque_ejecucion(log_turns)

    sys_msg = "Eres un juez de calidad de un agente conversacional de una floristería en español."
    # /no_think desactiva el thinking mode de Qwen3 — necesario para multi-turno estable
    msg1    = f"/no_think Lee y entiende este test case:\n\n{tc_def}\n\nConfirma el objetivo en una línea."
    msg2    = (
        f"Ahora analiza la ejecución real:\n\n{exec_log}\n\n"
        "¿El agente cumplió el objetivo del TC? "
        "Juzga el SENTIDO, no las palabras exactas — los criterios son orientativos.\n\n"
        "Responde EXACTAMENTE en este formato:\n"
        "VEREDICTO: PASS o FAIL\n"
        "RAZÓN: una línea (máx 20 palabras)"
    )

    try:
        if use_mlx:
            messages = [
                {"role": "system", "content": sys_msg},
                {"role": "user",   "content": msg1},
            ]
            confirmation = _chat_mlx(messages, max_tokens=80)
            messages += [
                {"role": "assistant", "content": confirmation},
                {"role": "user",      "content": msg2},
            ]
            content = _chat_mlx(messages, max_tokens=80)
        else:
            messages = [
                {"role": "user", "content": f"{sys_msg}\n\n{msg1}"},
            ]
            confirmation = _chat_ollama(messages, num_predict=80)
            messages += [
                {"role": "assistant", "content": confirmation},
                {"role": "user",      "content": msg2},
            ]
            content = _chat_ollama(messages, num_predict=80)

        v_match = re.search(r"VEREDICTO:\s*(PASS|FAIL)", content, re.IGNORECASE)
        r_match = re.search(r"RAZÓN:\s*(.+)",            content, re.IGNORECASE)
        verdict = v_match.group(1).upper() if v_match else "UNKNOWN"
        reason  = r_match.group(1).strip() if r_match else content[:100]
        return verdict, reason

    except Exception as e:
        return "ERROR", str(e)[:80]


def fase1_not_expected(agent_response, not_expected_patterns):
    """Fase 1 determinística: comprueba not_expected. Devuelve (FAIL, pattern) o (PASS, None)."""
    text = agent_response.lower()
    for pat in not_expected_patterns:
        if re.search(pat.lower(), text):
            return "FAIL", pat
    return "PASS", None


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fase 2 semántica sobre logs del runner QA")
    parser.add_argument("--run",       help="Timestamp del run (ej: 20260616_084859)")
    parser.add_argument("--tc",        help="TCs a analizar separados por coma (ej: TC-R04,TC-BODA-01)")
    parser.add_argument("--only-disc", action="store_true", help="Solo mostrar discrepancias")
    parser.add_argument("--mlx",       action="store_true", help="Usar MLX (Apple Silicon) en vez de Ollama")
    args = parser.parse_args()

    # Localizar directorio de logs
    if args.run:
        candidates = [d for d in PETAL_QA_DIR.iterdir()
                      if d.is_dir() and args.run in d.name and "_logs" in d.name]
        if not candidates:
            sys.exit(f"No se encontró logs dir para run '{args.run}'")
        logs_dir = candidates[0]
    else:
        logs_dir = find_latest_logs_dir()

    motor = f"MLX  ({MLX_MODEL})" if args.mlx else f"Ollama ({OLLAMA_MODEL})"
    print(f"\n▶ Logs:  {logs_dir.name}")
    print(f"▶ Motor: {motor}\n")

    tc_meta   = load_tc_meta(TC_YAML)
    tc_filter = set(args.tc.split(",")) if args.tc else None
    tc_files  = sorted(logs_dir.glob("TC-*.json"))
    if tc_filter:
        tc_files = [f for f in tc_files if f.stem in tc_filter]
    if not tc_files:
        sys.exit("No se encontraron archivos TC-*.json")

    print(f"{'TC':<22} {'Runner':>7} {'F1':>5} {'F2 (LLM)':>9}  {'Discrepancia':<16} Razón LLM")
    print("─" * 90)

    stats = {"total": 0, "acuerdo": 0, "fp_runner": 0, "fn_runner": 0, "error_llm": 0}

    for tc_file in tc_files:
        with open(tc_file, encoding="utf-8") as f:
            log = json.load(f)

        tc_id         = log["tc_id"]
        runner_status = log["status"]
        meta          = tc_meta.get(tc_id, {})
        tc_name       = meta.get("name", log.get("tc_name", ""))
        tc_not_exp    = meta.get("not_expected", [])

        if not log.get("runs"):
            continue
        run0 = log["runs"][0]

        # ── Fase 1: not_expected (determinístico, por turno) ──────────────────
        f1_result    = "PASS"
        f1_triggered = None

        for turn in run0["turns"]:
            idx          = turn["turn"] - 1
            agent        = turn["agent"]
            turns_meta   = meta.get("turns", [])
            turn_meta    = turns_meta[idx] if idx < len(turns_meta) else {}
            turn_not_exp = turn_meta.get("not_expected", [])
            all_not_exp  = list(tc_not_exp) + list(turn_not_exp) if idx == 0 else list(turn_not_exp)

            f1, triggered = fase1_not_expected(agent, all_not_exp)
            if f1 == "FAIL":
                f1_result    = "FAIL"
                f1_triggered = triggered

        # ── Fase 2: LLM semántico (una llamada por TC, dos mensajes) ─────────
        f2_verdict = "—"
        f2_reason  = ""

        if f1_result == "PASS":
            f2_verdict, f2_reason = evaluar_tc_llm(tc_id, meta, run0["turns"], use_mlx=args.mlx)

        # ── Veredicto global ──────────────────────────────────────────────────
        if f2_verdict == "ERROR":
            f2_global = "ERROR"
            stats["error_llm"] += 1
        elif f1_result == "FAIL":
            f2_global = "FAIL (F1)"
        elif f2_verdict == "FAIL":
            f2_global = "FAIL"
        elif f2_verdict == "PASS":
            f2_global = "PASS"
        else:
            f2_global = "—"

        # ── Discrepancia runner vs (F1+F2) ────────────────────────────────────
        runner_bin = "PASS" if runner_status == "PASS" else "FAIL"
        f2_bin     = "PASS" if f2_global in ("PASS", "—") else "FAIL"

        if runner_bin == f2_bin:
            disc = "—"
            stats["acuerdo"] += 1
        elif runner_bin == "FAIL" and f2_bin == "PASS":
            disc = "⚠ FALSO POS"
            stats["fp_runner"] += 1
        else:
            disc = "🔴 FALSO NEG"
            stats["fn_runner"] += 1

        stats["total"] += 1

        if args.only_disc and disc == "—":
            continue

        r_icon  = "✅" if runner_status == "PASS" else "❌"
        f1_icon = "✅" if f1_result == "PASS" else "❌"
        f2_icon = "✅" if f2_global in ("PASS", "—") else ("❌" if "FAIL" in f2_global else "⚠")
        reason_short = (f2_reason[:48] if f2_reason else
                        (f"F1 disparó: '{f1_triggered}'" if f1_triggered else ""))
        print(f"{tc_id:<22} {r_icon}{runner_status:>6} {f1_icon}{f1_result:>4} {f2_icon}{f2_global:>8}  {disc:<16} {reason_short}")

    print("─" * 90)
    print(f"\nTotal: {stats['total']} TCs | Acuerdo: {stats['acuerdo']} | "
          f"⚠ Falsos positivos runner: {stats['fp_runner']} | "
          f"🔴 Falsos negativos runner: {stats['fn_runner']} | "
          f"Errores LLM: {stats['error_llm']}\n")


if __name__ == "__main__":
    main()
