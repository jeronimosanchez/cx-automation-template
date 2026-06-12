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

from google.adk.runners import InMemoryRunner
from google.genai import types

# Ground truth CORREGIDO (11-jun, según Jero): CX actual pasa TODOS los TCs menos 2.
# Los 2 FAILs reales actuales son multiturno (urgencia ya arreglada el 2-jun).
FAILS_ACTUALES = {"TC-FRUSTRACION-01", "TC-MULTI-PRODUCTO-01"}


def load_cx_truth():
    # Todos PASS excepto los 2 FAILs actuales. Basado en la lista real de TCs.
    return {t["id"]: ("FAIL" if t["id"] in FAILS_ACTUALES else "PASS") for t in q.TESTS}


async def run_tc_adk(runner, test):
    """Corre un TC (todos sus turnos en una sesión) por ADK. Devuelve PASS/FAIL + turnos."""
    sess = await runner.session_service.create_session(app_name="petal", user_id="u")
    all_pass = True
    any_error = False
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
                kwargs = dict(user_id="u", session_id=sess.id, new_message=msg)
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
                is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)
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
        turns_out.append({"user": user_text, "agent": final_text[:300], "pass": tc["pass"],
                          "details": tc["details"]})
    return {"pass": all_pass, "errored": any_error, "turns": turns_out}


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

    rows = []
    for n, test in enumerate(tests, 1):
        cx_status = cx[test["id"]]
        res = await run_tc_adk(runner, test)
        adk_status = "ERROR" if res["errored"] else ("PASS" if res["pass"] else "FAIL")
        match = "✅" if (cx_status == adk_status) else ("⚡" if adk_status == "ERROR" else "❌")
        print(f"[{n:>2}/{len(tests)}] {test['id']:<22} CX={cx_status:<5} ADK={adk_status:<5} {match}")
        rows.append({"id": test["id"], "cx": cx_status, "adk": adk_status, "detail": res})
        time.sleep(1)  # respiro para el rate limit

    # --- Matriz de confusión (solo PASS/FAIL de CX) ---
    cm = {"pp": 0, "pf": 0, "fp": 0, "ff": 0}
    for r in rows:
        if r["cx"] == "PASS" and r["adk"] == "PASS": cm["pp"] += 1
        elif r["cx"] == "PASS" and r["adk"] == "FAIL": cm["pf"] += 1
        elif r["cx"] == "FAIL" and r["adk"] == "PASS": cm["fp"] += 1
        elif r["cx"] == "FAIL" and r["adk"] == "FAIL": cm["ff"] += 1

    errors = sum(1 for r in rows if r["adk"] == "ERROR")
    n = len(rows) - errors   # el acuerdo se mide sobre los TCs sin error
    agree = cm["pp"] + cm["ff"]
    print("\n" + "=" * 56)
    print("MATRIZ DE CONFUSIÓN  (filas = CX real, cols = ADK)")
    print("=" * 56)
    print(f"                 ADK PASS    ADK FAIL")
    print(f"  CX PASS          {cm['pp']:>3}         {cm['pf']:>3}    (falsas alarmas)")
    print(f"  CX FAIL          {cm['fp']:>3}         {cm['ff']:>3}    (fallos cazados)")
    print("=" * 56)
    if errors:
        print(f"  ⚡ TCs con error (excluidos): {errors}")
    print(f"  Acuerdo total:        {agree}/{n}  ({100*agree//max(n,1)}%)")
    cx_pass = cm["pp"] + cm["pf"]
    cx_fail = cm["fp"] + cm["ff"]
    if cx_pass: print(f"  PASS reproducidos:    {cm['pp']}/{cx_pass}  (detecta lo que funciona)")
    if cx_fail: print(f"  FAIL reproducidos:    {cm['ff']}/{cx_fail}  (detecta lo que NO funciona)")
    print("=" * 56)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fidelity_result.json")
    json.dump({"matrix": cm, "rows": rows}, open(out, "w"), ensure_ascii=False, indent=2)
    print(f"\nDetalle guardado en: {out}")


if __name__ == "__main__":
    asyncio.run(main())
