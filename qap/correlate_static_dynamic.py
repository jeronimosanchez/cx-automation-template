"""correlate_static_dynamic.py

Cruza los hallazgos del static_audit con los resultados dinámicos del QA suite.
Para cada criterio estático flaggeado, calcula cuántos TCs FAIL/INESTABLE
pasaron por un playbook con ese problema — sin tocar el runner ni CX.

Añade puntuación de plausibilidad causal (criterios Bradford Hill simplificados):
  1. Plausibilidad mecánica  (0-2): conocimiento del dominio, hardcoded por criterio
  2. Especificidad            (0-2): fail_rate_afectado / tasa_base_global
  3. Dosis-respuesta          (0-1): fail_rate(🔴) > fail_rate(🟡)?
Score 0-5 → BAJA (<2) / MEDIA (2-3) / ALTA (≥4). Solo ALTA+MEDIA pasan al loop ADK.

Uso:
  python qap/correlate_static_dynamic.py
  python qap/correlate_static_dynamic.py --logs ~/petal-qa/qa_20260615_0005_logs
  python qap/correlate_static_dynamic.py --root <repo_root>
"""
import os, sys, glob, json, argparse
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import static_audit

CRITERIA = [
    ("size",      "Token size"),
    ("dsl",       "DSL density"),
    ("exit",      "Exit paths"),
    ("params",    "Params declared"),
    ("ex_cnt",    "Examples (≥4)"),
    ("always",    "Always-select"),
    ("tool_fail", "Tool failure ex."),
    ("neg",       "Negation ex."),
    ("name_len",  "Name length"),
    ("snake",     "snake_case params"),
    ("steps",     "Step count"),
    ("cycle",     "Deleg. cycle"),
    ("single",    "Single resp."),
]

# Plausibilidad mecánica hardcoded (knowledge estable — no cambia entre runs)
# Tupla (strength: high/medium/low, explicación del mecanismo conocido)
MECHANISMS = {
    "size":      ("high",   "LLM pierde el hilo de instrucciones multi-paso con >10k tokens"),
    "snake":     ("high",   "Param incorrecto → slot vacío silencioso → condicional erróneo → respuesta equivocada"),
    "exit":      ("high",   "Sin exit definido → agente bucla o devuelve non-answer"),
    "cycle":     ("high",   "Bucle de delegación infinito → crash inevitable"),
    "name_len":  ("high",   "Límite duro de plataforma — si está en prod este issue no puede existir"),
    "neg":       ("medium", "Sin señal de entrenamiento → agente ignora cancelación o continúa el flujo"),
    "tool_fail": ("medium", "Sin señal de entrenamiento → agente alucina o se detiene ante error de backend"),
    "ex_cnt":    ("medium", "Pocos ejemplos → CX puede enrutar al playbook incorrecto"),
    "dsl":       ("medium", "DSL denso ($refs) dificulta el parsing de instrucciones por el LLM"),
    "always":    ("low",    "Depende de cobertura de ejemplos — efecto indirecto, difícil aislar"),
    "params":    ("low",    "Los params pueden cargarse vía tool en runtime — efecto indirecto"),
    "steps":     ("low",    "Indicador de mantenibilidad — efecto difuso sobre fiabilidad del LLM"),
    "single":    ("low",    "Indicador de complejidad — efecto difuso"),
}
MECH_PTS = {"high": 2, "medium": 1, "low": 0}


def _is_flagged(val):
    return isinstance(val, str) and ("🟡" in val or "🔴" in val)


def _sev(val):
    if not isinstance(val, str):
        return 0
    return 2 if "🔴" in val else (1 if "🟡" in val else 0)


def _sev_label(val):
    if not isinstance(val, str):
        return "—"
    return "🔴" if "🔴" in val else ("🟡" if "🟡" in val else "✅")


def _pbs_in_tc(tc):
    """Devuelve el set de displayNames de playbooks tocados en el TC (todos los runs)."""
    pbs = set()
    for run in tc.get("runs", []):
        for turn in run.get("turns", []):
            for action in turn.get("trace", {}).get("actions", []):
                for key in ("playbookInvocation", "playbookTransition"):
                    dn = action.get(key, {}).get("displayName")
                    if dn:
                        pbs.add(dn)
    return pbs


def _latest_logs_dir(petal_qa=None):
    base = petal_qa or os.path.expanduser("~/petal-qa")
    dirs = sorted(glob.glob(os.path.join(base, "*_logs")), reverse=True)
    return dirs[0] if dirs else None


def causal_plausibility(field, fail_hits, pass_hits, total_fails, total_tcs, flagged):
    """
    Score Bradford Hill simplificado (0-5) para la correlación de un criterio.

    Criterios:
      1. Plausibilidad mecánica  (0-2): hardcoded en MECHANISMS
      2. Especificidad            (0-2): fail_rate_afectado vs tasa base global
      3. Dosis-respuesta          (0-1): fail_rate(🔴 pbs) > fail_rate(🟡 pbs)?

    Umbral: ≥4 → ALTA · 2-3 → MEDIA · <2 → BAJA.
    Solo ALTA+MEDIA tienen evidencia suficiente para enviar al loop ADK.

    Devuelve (score int, label str, detail dict)
    """
    score = 0
    details = {}

    # 1. Mecanismo
    mech_str, mech_why = MECHANISMS.get(field, ("low", "mecanismo no documentado"))
    mech_pts = MECH_PTS[mech_str]
    score += mech_pts
    details["mechanism"] = (mech_str, mech_pts, mech_why)

    # 2. Especificidad — compara la tasa de FAIL entre los TCs que tocan playbooks
    #    afectados vs la tasa base global del run
    touching = len(fail_hits) + len(pass_hits)
    baseline = total_fails / total_tcs if total_tcs else 0
    if touching > 0 and baseline > 0:
        fail_rate = len(fail_hits) / touching
        ratio = fail_rate / baseline
    else:
        ratio = 0.0
    if ratio >= 3.0:
        spec_pts, spec_lbl = 2, f"{ratio:.1f}x (alta)"
    elif ratio >= 1.5:
        spec_pts, spec_lbl = 1, f"{ratio:.1f}x (moderada)"
    else:
        spec_pts, spec_lbl = 0, f"{ratio:.1f}x (ruido)"
    score += spec_pts
    details["specificity"] = (spec_pts, spec_lbl)

    # 3. Dosis-respuesta — solo cuando hay playbooks en ambos niveles (🔴 y 🟡)
    red_pbs = {dn for dn, row in flagged.items() if _sev(row.get(field, "")) == 2}
    yel_pbs = {dn for dn, row in flagged.items() if _sev(row.get(field, "")) == 1}
    if red_pbs and yel_pbs:
        all_hits = fail_hits + pass_hits
        red_f = sum(1 for t in fail_hits if t["_pbs"] & red_pbs)
        red_t = sum(1 for t in all_hits  if t["_pbs"] & red_pbs)
        yel_f = sum(1 for t in fail_hits if t["_pbs"] & yel_pbs)
        yel_t = sum(1 for t in all_hits  if t["_pbs"] & yel_pbs)
        red_rate = red_f / red_t if red_t else 0.0
        yel_rate = yel_f / yel_t if yel_t else 0.0
        if red_rate > yel_rate:
            dose_pts = 1
            dose_lbl = f"✓ 🔴 {red_rate:.0%} > 🟡 {yel_rate:.0%}"
        else:
            dose_pts = 0
            dose_lbl = f"✗ 🔴 {red_rate:.0%} ≤ 🟡 {yel_rate:.0%}"
    else:
        dose_pts, dose_lbl = 0, "n/a (un solo nivel de severidad)"
    score += dose_pts
    details["dose_response"] = (dose_pts, dose_lbl)

    label = "ALTA" if score >= 4 else ("MEDIA" if score >= 2 else "BAJA")
    return score, label, details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", help="Directorio con TC-*.json del run a analizar")
    ap.add_argument("--root", default=os.path.dirname(HERE),
                    help="Raíz del repo (contiene definitions/)")
    args = ap.parse_args()

    logs_dir = args.logs or _latest_logs_dir()
    if not logs_dir or not os.path.isdir(logs_dir):
        print("ERROR: no se encontró directorio de logs. Pasa --logs <dir>")
        sys.exit(1)

    print(f"Run:  {os.path.basename(logs_dir)}")
    print(f"Repo: {args.root}\n")

    # ── 1. Static audit ──────────────────────────────────────────────────────
    audit_rows = static_audit.audit(args.root)

    pb_dir = os.path.join(args.root, "definitions", "playbooks")
    name_to_dn = {}
    for f in glob.glob(os.path.join(pb_dir, "*.yaml")):
        fname = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8") as yf:
            pb = yaml.safe_load(yf) or {}
        name_to_dn[fname] = pb.get("displayName", fname)

    dn_to_audit = {name_to_dn.get(r["name"], r["name"]): r for r in audit_rows}

    # ── 2. Dynamic results ───────────────────────────────────────────────────
    tc_files = sorted(glob.glob(os.path.join(logs_dir, "TC-*.json")))
    tcs = []
    for f in tc_files:
        with open(f, encoding="utf-8") as jf:
            tc = json.load(jf)
        tc["_pbs"] = _pbs_in_tc(tc)
        tcs.append(tc)

    fail_tcs    = [t for t in tcs if t["status"] in ("FAIL", "INESTABLE")]
    pass_tcs    = [t for t in tcs if t["status"] == "PASS"]
    total_fails = len(fail_tcs)
    total_tcs   = len(tcs)

    print(f"TCs totales:       {total_tcs}")
    print(f"FAIL + INESTABLE:  {total_fails}")
    print(f"PASS:              {len(pass_tcs)}")
    print(f"Tasa base FAIL:    {total_fails / total_tcs * 100:.1f}%\n")

    # ── 3. Correlación + plausibilidad causal ────────────────────────────────
    results = []
    for field, label in CRITERIA:
        flagged = {dn: row for dn, row in dn_to_audit.items()
                   if _is_flagged(row.get(field, ""))}
        if not flagged:
            continue

        flagged_set = set(flagged)
        fail_hits = [t for t in fail_tcs if t["_pbs"] & flagged_set]
        pass_hits = [t for t in pass_tcs if t["_pbs"] & flagged_set]
        touching  = len(fail_hits) + len(pass_hits)
        pct       = len(fail_hits) / touching * 100 if touching else 0.0
        max_sev   = max((_sev(row.get(field, "")) for row in flagged.values()), default=0)
        sev_lbl   = "🔴" if max_sev == 2 else "🟡"

        bh_score, bh_label, bh_detail = causal_plausibility(
            field, fail_hits, pass_hits, total_fails, total_tcs, flagged
        )

        results.append({
            "field":      field,
            "criterion":  label,
            "sev":        max_sev,
            "sev_lbl":    sev_lbl,
            "pbs":        sorted(flagged),
            "fail":       len(fail_hits),
            "fail_ids":   [t["tc_id"] for t in fail_hits],
            "pass":       len(pass_hits),
            "touching":   touching,
            "pct":        pct,
            "bh_score":   bh_score,
            "bh_label":   bh_label,
            "bh_detail":  bh_detail,
            "_fail_hits": fail_hits,
        })

    # Orden primario: plausibilidad causal desc → % FAIL desc → severidad desc
    results.sort(key=lambda x: (-x["bh_score"], -x["pct"], -x["sev"], x["criterion"]))

    # ── 4. Tabla resumen ─────────────────────────────────────────────────────
    W_CRIT = 22
    W_PB   = 34
    print(f"{'Criterio':<{W_CRIT}} {'Sev':<4} {'Playbooks con issue':<{W_PB}} "
          f"{'F+I':>4} {'PASS':>5} {'Tot':>4} {'%F+I':>5}  {'BH':>12}")
    print("─" * (W_CRIT + 4 + W_PB + 4 + 5 + 5 + 6 + 14))
    for r in results:
        pbs_str = ", ".join(r["pbs"])
        if len(pbs_str) > W_PB - 1:
            pbs_str = pbs_str[:W_PB - 4] + "..."
        bar = "█" * int(r["pct"] / 10)
        bh_col = f"{r['bh_label']} ({r['bh_score']}/5)"
        print(f"{r['criterion']:<{W_CRIT}} {r['sev_lbl']:<4} {pbs_str:<{W_PB}} "
              f"{r['fail']:>4} {r['pass']:>5} {r['touching']:>4} {r['pct']:>4.0f}%  "
              f"{bh_col:>12}  {bar}")

    # ── 5. Hipótesis prioritarias (solo ALTA + MEDIA → candidatas para ADK) ──
    priority = [r for r in results if r["bh_label"] in ("ALTA", "MEDIA")]
    discarded = [r for r in results if r["bh_label"] == "BAJA"]
    print(f"\n{'═' * 70}")
    print(f"Hipótesis para ADK: {len(priority)} candidatas · {len(discarded)} descartadas (BAJA)\n")
    for r in priority:
        d = r["bh_detail"]
        mech_str, mech_pts, mech_why = d["mechanism"]
        spec_pts, spec_lbl           = d["specificity"]
        dose_pts, dose_lbl           = d["dose_response"]
        print(f"  ▶ [{r['bh_label']} {r['bh_score']}/5]  {r['criterion']}  {r['sev_lbl']}")
        print(f"    Playbooks: {', '.join(r['pbs'])}")
        print(f"    Mecanismo ({mech_str}, +{mech_pts}pt): {mech_why}")
        print(f"    Especificidad (+{spec_pts}pt): {spec_lbl}")
        print(f"    Dosis-respuesta (+{dose_pts}pt): {dose_lbl}")
        print(f"    TCs correlacionados: {', '.join(r['fail_ids']) or '—'}")
        print()
    if discarded:
        print(f"  Descartadas (BAJA — ruido estadístico o mecanismo débil):")
        for r in discarded:
            print(f"    · {r['criterion']} ({r['bh_score']}/5)  — {r['pbs']}")
        print()

    # ── 6. Detalle por TC FAIL/INESTABLE ─────────────────────────────────────
    print(f"{'─' * 70}")
    print("Detalle TCs FAIL/INESTABLE — playbooks tocados e issues estáticos:\n")
    for tc in sorted(fail_tcs, key=lambda t: t["tc_id"]):
        pbs = tc["_pbs"]
        issues = []
        for dn in sorted(pbs):
            row = dn_to_audit.get(dn)
            if not row:
                continue
            flags = [(label, row[field]) for field, label in CRITERIA
                     if _is_flagged(row.get(field, ""))]
            if flags:
                issues.append(f"  {dn}: " + " · ".join(f"{l}={_sev_label(v)}" for l, v in flags))
        pb_str = ", ".join(sorted(pbs))
        print(f"{tc['tc_id']} [{tc['status']}]  →  {pb_str}")
        if issues:
            for line in issues:
                print(line)
        else:
            print("  (ningún issue estático en los playbooks tocados)")
        print()


if __name__ == "__main__":
    main()
