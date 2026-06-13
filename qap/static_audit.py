"""static_audit (static): LINTER ESTÁTICO de playbooks CX.

$0, instantáneo, SIN emulador ni LLM. Audita el DISEÑO de los playbooks antes del deploy.
Checks implementados:
  · TAMAÑO      (CX-25): tokens → ✅<5k · 🟡>5k refactor · 🔴>10k urgente.
  · DSL DENSITY (CX-34): % líneas con $ en instrucción → ✅<15% · 🟡15-30% · 🔴>30%.
  · EXIT PATHS  (CX-27): keywords de cierre en instrucción.
  · PARAMS      (CX-31): $refs en instrucción vs params declarados en schema.
  · EXAMPLES    (CX-13): nº de examples → 🟡 si <4 (Google recomienda ≥4).
  · ALWAYS_SEL  (CX-36): ≥1 example con selectionStrategy ALWAYS.
  · TOOL FAIL   (CX-26): ≥1 example con keywords de fallo de tool.
  · NEGACIÓN    (CX-36): ≥1 example con userUtterance de cancelación.
Dogfooding sobre Petal; agnóstico vía --root (otro cliente = otro repo de definitions/).

Uso: python qap/static_audit.py [--root <repo_root>]

Scope actual: solo playbooks. Roadmap de expansión:
  · Flows/Pages  — checks NLU: intents sin utterances, pages sin exit routes.
  · Entity Types — naming, cobertura mínima de valores.
  · Generators   — tamaño y referencias huérfanas.
  · Tools        — schemas incompletos, operationId con caracteres inválidos.
Cada componente se añade cuando el proyecto lo requiere — no antes.
"""
import os, sys, glob, argparse, re
import yaml

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    _tok = lambda t: len(_enc.encode(t))
    _MET = "tiktoken/cl100k"
except Exception:
    _tok = lambda t: len(t) // 4
    _MET = "aprox chars/4"

SIZE_PROPOSE, SIZE_URGENT = 5000, 10000
MIN_EXAMPLES              = 4
DSL_WARN, DSL_FAIL        = 0.15, 0.30

EXIT_KW = ["handoff", "escalar", "agente humano", "no puedo", "transferir", "escalación"]
FAIL_KW = ["error", "fallo", "no disponible", "no encontrado", "herramienta"]
NEG_KW  = ["no quiero", "cancelar", "ya no", "no gracias", "lo cancelo"]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _instr_text(pb):
    steps = pb.get("instruction", {}).get("steps", [])
    return "\n".join(s.get("text", "") for s in steps if isinstance(s, dict))


def _check_size(tokens):
    if tokens > SIZE_URGENT:  return "🔴 URGENTE"
    if tokens > SIZE_PROPOSE: return "🟡 refactor"
    return "✅"


def _check_dsl(text):
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0, "✅"
    pct = sum(1 for l in lines if "$" in l) / len(lines)
    return pct, ("🔴" if pct > DSL_FAIL else "🟡" if pct > DSL_WARN else "✅")


def _check_exit(text):
    return "✅" if any(kw in text.lower() for kw in EXIT_KW) else "🔴 sin exit path"


def _check_params(pb, text):
    declared = {p["name"] for section in ("inputParameterDefinitions", "outputParameterDefinitions")
                for p in pb.get(section, [])}
    # $param_name — the regex matches $word but NOT ${...} (brace after $ is not a letter)
    refs = set(re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)', text))
    orphan = refs - declared
    if not orphan:
        return "✅"
    return f"🔴 sin declarar: {', '.join(sorted(orphan))}"


def _check_examples(ex_dir):
    if not os.path.isdir(ex_dir):
        return 0, "🔴 sin carpeta", "🔴 sin carpeta", "🔴 sin carpeta", "🔴 sin carpeta"

    files = [f for f in glob.glob(os.path.join(ex_dir, "*.yaml")) if os.path.isfile(f)]
    n = len(files)

    has_always = has_fail = has_neg = False
    for f in files:
        d = _load(f)
        strategy = str(d.get("selectionStrategy", "")).upper()
        if "ALWAYS" in strategy:
            has_always = True

        desc = str(d.get("description", "")).lower()
        has_fail = has_fail or any(kw in desc for kw in FAIL_KW)

        for act in d.get("actions", []):
            ag  = str(act.get("agentUtterance",  {}).get("text", "")).lower()
            usr = str(act.get("userUtterance",   {}).get("text", "")).lower()
            has_fail = has_fail or any(kw in ag  for kw in FAIL_KW)
            has_neg  = has_neg  or any(kw in usr for kw in NEG_KW)

    ex_cnt  = "✅" if n >= MIN_EXAMPLES else f"🟡 {n}<{MIN_EXAMPLES}"
    always  = "✅" if has_always else "🟡 sin always_select"
    tool_f  = "✅" if has_fail   else "🟡 sin ejemplo de fallo"
    neg     = "✅" if has_neg    else "🟡 sin negación"
    return n, ex_cnt, always, tool_f, neg


def audit(root):
    pb_dir = os.path.join(root, "definitions", "playbooks")
    ex_dir = os.path.join(root, "definitions", "examples")
    sys.path.insert(0, os.path.join(root, "qap", "adk_fidelity"))
    import petal_agent

    rows = []
    for f in sorted(glob.glob(os.path.join(pb_dir, "*.yaml"))):
        name = os.path.splitext(os.path.basename(f))[0]
        pb   = _load(f)
        text = _instr_text(pb)
        tokens   = _tok(petal_agent._playbook_text(name))
        dsl_pct, dsl_f = _check_dsl(text)
        n_ex, ex_cnt, always_f, fail_f, neg_f = _check_examples(os.path.join(ex_dir, name))
        rows.append({
            "name":      name,
            "tokens":    tokens,
            "size":      _check_size(tokens),
            "dsl_pct":   dsl_pct,
            "dsl":       dsl_f,
            "exit":      _check_exit(text),
            "params":    _check_params(pb, text),
            "n_ex":      n_ex,
            "ex_cnt":    ex_cnt,
            "always":    always_f,
            "tool_fail": fail_f,
            "neg":       neg_f,
        })
    return rows


def report(rows):
    print(f"\nstatic_audit (static)  ·  {_MET}")
    print("=" * 80)
    for r in rows:
        flags = [v for k, v in r.items() if isinstance(v, str) and ("🟡" in v or "🔴" in v)]
        status = "🔴" if any("🔴" in f for f in flags) else ("🟡" if flags else "✅")
        print(f"\n{status} {r['name']}  ({r['tokens']} tokens)")
        print(f"   tamaño      (CX-25):  {r['size']}")
        print(f"   DSL density (CX-34):  {r['dsl']}  ({r['dsl_pct']:.0%})")
        print(f"   exit paths  (CX-27):  {r['exit']}")
        print(f"   params      (CX-31):  {r['params']}")
        print(f"   examples    (CX-13):  {r['ex_cnt']}  (total: {r['n_ex']})")
        print(f"   always_sel  (CX-36):  {r['always']}")
        print(f"   fallo tool  (CX-26):  {r['tool_fail']}")
        print(f"   negación    (CX-36):  {r['neg']}")

    print("\n" + "=" * 80)
    urgent = [r["name"] for r in rows if "URGENTE" in r["size"]]
    warn   = [r["name"] for r in rows if "refactor" in r["size"]]
    issues = [r["name"] for r in rows
              if any("🟡" in str(v) or "🔴" in str(v)
                     for k, v in r.items() if k != "size" and isinstance(v, str))]
    print(f"TAMAÑO:  🔴 {len(urgent)} urgente(s): {urgent or '—'}  ·  🟡 {len(warn)} refactor: {warn or '—'}")
    print(f"CHECKS:  {len(issues)}/{len(rows)} playbooks con algún check fallido")
    print("=" * 80)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="raíz del repo con definitions/")
    report(audit(ap.parse_args().root))
