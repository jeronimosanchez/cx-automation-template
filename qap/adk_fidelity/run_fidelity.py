"""Experimento de fidelidad ADK vs CX.

Corre los TCs por el Petal reconstruido en ADK, aplica la MISMA rúbrica que CX
(check_turn de test_qa_playbooks), y compara contra el ground truth de CX guardado
en ~/petal-qa. Mide acuerdo en AMBAS clases (PASS reproducidos + FAIL reproducidos).

Uso:
  python run_fidelity.py                 # los 51 TCs
  python run_fidelity.py --limit 8       # primeros 8
  python run_fidelity.py --only TC-URGENCIA-01,TC-R01
"""
import os, re, sys, json, time, glob, asyncio, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- key ---
for line in open(os.path.join(ROOT, ".env")):
    m = re.match(r'GEMINI_API_KEY=(\S+)', line.strip())
    if m:
        os.environ["GOOGLE_API_KEY"] = m.group(1)
        os.environ["GEMINI_API_KEY"] = m.group(1)
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"

sys.path.insert(0, os.path.join(ROOT, "qap"))
import test_qa_playbooks as q          # TESTS + check_turn (la rúbrica de CX)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# ADK_RECON=multi → reconstrucción multi-agente (orquestador + sub-agentes);
# por defecto, la plana. Permite comparar antes/después sin tocar el resto.
if os.environ.get("ADK_RECON") == "multi":
    import petal_agent_multi as petal_agent
else:
    import petal_agent
import static_leak_gate                       # P1+P2: pre-gate anti-fuga → veredicto 3-estados (OK/INVALID)

from google.adk.runners import InMemoryRunner
from google.adk.agents.run_config import RunConfig
from google.genai import types

# Cap de llamadas LLM POR TURNO. Default de ADK = 500 → un loop de delegación
# (${PLAYBOOK:Orchestrator} interpretado como transfer_to_agent → ping-pong) grinda ~140/TC.
# Un turno limpio usa ~3-10 (route + respuesta + tool). 25 mata el loop sin cortar turnos legítimos;
# el turno que lo excede cae como INVALID (la reconstrucción SE ROMPE ahí — honesto). Fix profundo = P3.
MAX_LLM_CALLS = 25

# Ground truth MEDIDO (12-jun, run 3/TC qa_20260612_1646 contra CX, Petal post-#116) — NO asumido.
#   FAILs robustos (0/3): FRUSTRACION-01, STOCK-EXCESO-01, URGENCIA-03, MULTI-PRODUCTO-01.
#   FLAKY/INESTABLE (2/3): C40, CAMBIO-OP-01 → CX no-determinista → NO es ground truth fiable → se EXCLUYEN.
# OJO: URGENCIA-03 falla 0/3 → el fix 4bc33b2 NO la arregló (era para URGENCIA-01 + -03). URGENCIA-02 pasa 3/3
# (el FAIL del run único del 2-jun era ruido). El hardcode viejo de 2 FAILs estaba mal.
FAILS_ACTUALES = {"TC-FRUSTRACION-01", "TC-STOCK-EXCESO-01", "TC-URGENCIA-03", "TC-MULTI-PRODUCTO-01"}
FLAKY_CX = {"TC-C40", "TC-CAMBIO-OP-01"}   # INESTABLE 2/3 → fuera del ground truth determinista


def load_cx_truth():
    # PASS/FAIL determinista del Petal actual; las flaky se excluyen (no son ground truth fiable).
    return {t["id"]: ("FAIL" if t["id"] in FAILS_ACTUALES else "PASS")
            for t in q.TESTS if t["id"] not in FLAKY_CX}


async def run_tc_adk(runner, test, lexicon):
    """Corre un TC (todos sus turnos en una sesión) por ADK. Devuelve veredicto 3-estados + turnos."""
    sess = await runner.session_service.create_session(app_name="petal", user_id="u")
    all_pass = True
    any_error = False
    invalid = False
    invalid_reason = ""
    turns_out = []
    for i, turn in enumerate(test["turns"]):
        user_text = turn["user"].replace("{RUN}", "adk_1")
        # session_params de CX → los inyectamos como state inicial (aproximación)
        state_delta = turn.get("session_params") if i == 0 else None
        msg = types.Content(role="user", parts=[types.Part(text=user_text)])
        final_text = ""
        errored = False
        for attempt in range(5):  # reintento ante 429 (rate limit) y transitorios
            try:
                final_text = ""
                kwargs = dict(user_id="u", session_id=sess.id, new_message=msg,
                              run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS))
                if state_delta:
                    kwargs["state_delta"] = state_delta
                async for event in runner.run_async(**kwargs):
                    if event.is_final_response() and event.content:
                        final_text = "".join(
                            p.text or "" for p in event.content.parts if getattr(p, "text", None))
                errored = False
                break
            except Exception as e:
                errored = True
                emsg = str(e)
                # Cap de llamadas excedido = loop de delegación. NO reintentar (es determinista,
                # cada reintento volvería a gastar el cap) → cortar ya como INVALID.
                if "max_llm_calls" in emsg.lower() or "llm calls" in emsg.lower() \
                        or "LlmCallsLimit" in type(e).__name__:
                    final_text = f"ERROR_LOOP_DELEGACION: cap {MAX_LLM_CALLS} llamadas excedido"
                    break
                is_quota = "429" in emsg or "RESOURCE_EXHAUSTED" in emsg
                wait = (8 * (attempt + 1)) if is_quota else (2 * (attempt + 1))
                if attempt < 4:
                    time.sleep(wait)
                    continue
                final_text = f"ERROR_TRAS_REINTENTOS: {str(e)[:120]}"
        if errored:
            any_error = True
        checks = turn.get("checks", [])
        not_exp = test.get("not_expected", []) if i == 0 else []
        tc = q.check_turn(final_text, checks, not_exp)
        if not tc["pass"]:
            all_pass = False
        lstate, lwhy = static_leak_gate.classify_turn(final_text, lexicon)   # P1+P2: ¿medida válida o andamiaje?
        if lstate == "INVALID":
            invalid = True
            if not invalid_reason:
                invalid_reason = lwhy
        turns_out.append({"user": user_text, "agent": final_text[:300], "pass": tc["pass"],
                          "valid": lstate == "OK", "invalid_reason": lwhy, "details": tc["details"]})
    # Veredicto 3-estados: INVALID (fuga/degeneración/error) > FAIL > PASS. INVALID NO cuenta como fidelidad.
    verdict = "INVALID" if (any_error or invalid) else ("PASS" if all_pass else "FAIL")
    return {"pass": all_pass, "errored": any_error, "invalid": invalid,
            "invalid_reason": invalid_reason, "verdict": verdict, "turns": turns_out}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")
    args = ap.parse_args()

    cx = load_cx_truth()
    tests = [t for t in q.TESTS if t["id"] in cx]   # solo los que tienen ground truth CX
    # ORDER-BY-CLASS (P0, 12-jun): agrupa TCs por clase (prefijo alfa del id) consecutivos → el prefijo del
    # sub-agente se queda CALIENTE en caché (no re-prefilea entre TCs de su clase). Orden FIJO → va al fingerprint.
    # Ver handoff velocidad 12-jun en memoria de proyecto.
    tests.sort(key=lambda t: ((re.match(r"TC-([A-Za-z]+)", t["id"]) or re.match(r"(.+)", t["id"])).group(1), t["id"]))
    if args.only:
        wanted = set(args.only.split(","))
        tests = [t for t in tests if t["id"] in wanted]
    if args.limit:
        tests = tests[:args.limit]

    print(f"Ground truth CX: {len(cx)} TCs | a correr en ADK: {len(tests)}")
    print(f"Modelo ADK: {petal_agent.ADK_MODEL} | webhook: petal-sheet-api\n")

    agent = petal_agent.build_agent()
    runner = InMemoryRunner(agent=agent, app_name="petal")
    import petal_agent as _flat                                          # módulo PLANO: tiene load_instruction()
    lexicon = static_leak_gate.build_lexicon(_flat.load_instruction())          # P2: lexicón autogenerado del prompt compilado (vale para flat y multi)
    print(f"Lexicón anti-fuga: {len(lexicon['structural'])} patrones | "
          f"{len(lexicon['tokens']['variables'])} vars + {len(lexicon['tokens']['playbooks'])} playbooks cosechados\n")

    rows = []
    for n, test in enumerate(tests, 1):
        cx_status = cx[test["id"]]
        res = await run_tc_adk(runner, test, lexicon)
        adk_status = res["verdict"]   # PASS / FAIL / INVALID
        if adk_status == "INVALID":
            match = "⚠️"
        else:
            match = "✅" if (cx_status == adk_status) else "❌"
        extra = f"  ⚠️ {res['invalid_reason']}" if adk_status == "INVALID" else ""
        print(f"[{n:>2}/{len(tests)}] {test['id']:<22} CX={cx_status:<5} ADK={adk_status:<7} {match}{extra}")
        rows.append({"id": test["id"], "cx": cx_status, "adk": adk_status, "detail": res})
        time.sleep(1)  # respiro para el rate limit

    # --- Matriz de confusión: SOLO medidas VÁLIDAS (los INVALID no son fidelidad, van aparte) ---
    cm = {"pp": 0, "pf": 0, "fp": 0, "ff": 0}
    for r in rows:
        if r["adk"] == "INVALID": continue
        if r["cx"] == "PASS" and r["adk"] == "PASS": cm["pp"] += 1
        elif r["cx"] == "PASS" and r["adk"] == "FAIL": cm["pf"] += 1
        elif r["cx"] == "FAIL" and r["adk"] == "PASS": cm["fp"] += 1
        elif r["cx"] == "FAIL" and r["adk"] == "FAIL": cm["ff"] += 1

    invalids = sum(1 for r in rows if r["adk"] == "INVALID")
    n = len(rows) - invalids   # el acuerdo se mide solo sobre medidas válidas
    agree = cm["pp"] + cm["ff"]
    health = 100 * invalids // max(len(rows), 1)
    print("\n" + "=" * 56)
    print("MATRIZ DE CONFUSIÓN  (filas = CX real, cols = ADK) — solo VÁLIDAS")
    print("=" * 56)
    print(f"                 ADK PASS    ADK FAIL")
    print(f"  CX PASS          {cm['pp']:>3}         {cm['pf']:>3}    (falsas alarmas)")
    print(f"  CX FAIL          {cm['fp']:>3}         {cm['ff']:>3}    (fallos cazados)")
    print("=" * 56)
    print(f"  ⚠️  INVALID (fuga/degeneración):  {invalids}/{len(rows)}  → salud del harness: {100-health}% válidas")
    print(f"  Acuerdo (solo válidas):  {agree}/{n}  ({100*agree//max(n,1)}%)")
    cx_pass = cm["pp"] + cm["pf"]
    cx_fail = cm["fp"] + cm["ff"]
    if cx_pass: print(f"  PASS reproducidos:    {cm['pp']}/{cx_pass}  (detecta lo que funciona)")
    if cx_fail: print(f"  FAIL reproducidos:    {cm['ff']}/{cx_fail}  (detecta lo que NO funciona)")
    print("=" * 56)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fidelity_result.json")
    json.dump({"matrix": cm, "invalids": invalids, "rows": rows}, open(out, "w"),
              ensure_ascii=False, indent=2)
    print(f"\nDetalle guardado en: {out}")


if __name__ == "__main__":
    asyncio.run(main())
