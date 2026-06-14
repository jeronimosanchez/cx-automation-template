"""static_audit (static): LINTER ESTÁTICO de playbooks CX.

$0, instantáneo, SIN emulador ni LLM. Audita el DISEÑO de los playbooks antes del deploy.
Checks implementados:
  · TAMAÑO      (CX-25): tokens → ✅<5k · 🟡>5k refactor · 🔴>10k urgente.
  · DSL DENSITY (CX-34): % líneas con $ en instrucción → ✅<15% · 🟡15-30% · 🔴>30%.
  · EXIT PATHS  (CX-27): keywords de cierre en instrucción.
  · PARAMS      (CX-31): $refs no declaradas (excluye locales `$x=` y glue a texto `$totaleuros`).
  · EXAMPLES    (CX-13): nº de examples → 🟡 si <4 (Google recomienda ≥4).
  · ALWAYS_SEL  (CX-36): ≥1 example con selectionStrategy ALWAYS (➖ n/d: no viaja en export REST).
  · TOOL FAIL   (CX-26): ≥1 example con keywords de fallo de tool.
  · NEGACIÓN    (CX-36): ≥1 example con userUtterance de cancelación.
  · NAME LEN    (CX-29): len(displayName) ≤64 (hard limit Google).
  · SNAKE_CASE  (CX-33): params en snake_case (^[a-z][a-z0-9_]*$).
  · STEPS       (CX-35): nº de pasos en instrucción → ✅≤15 · 🟡16-25 · 🔴>25.
  · CICLO DELEG (CX-28): bucle prohibido en el grafo ${PLAYBOOK:X} (hard limit CX).
  · 1 RESPONS   (CX-32): >1 delegación distinta + >3 tools distintos → candidato a dividir.
  · MAX PB      (CX-30): ≤50 playbooks por agente (hard limit Google) — nivel agente.
Dogfooding sobre Petal; agnóstico vía --root (otro cliente = otro repo de definitions/).

Uso: python qap/static_audit.py [--root <repo_root>]

Scope actual: solo playbooks. Roadmap de expansión:
  · Flows/Pages  — checks NLU: intents sin utterances, pages sin exit routes.
  · Entity Types — naming, cobertura mínima de valores.
  · Generators   — tamaño y referencias huérfanas.
  · Tools        — schemas incompletos, operationId con caracteres inválidos.
Cada componente se añade cuando el proyecto lo requiere — no antes.

Umbrales: hardcoded por defecto; si existe qap/static_audit_config.yaml (generado por
sync_static_config.py desde los bloques `static:` del KB), se usan esos valores en su lugar.
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

# ── Defaults (overridden by static_audit_config.yaml when present) ───────────
SIZE_PROPOSE, SIZE_URGENT = 5000, 10000
MIN_EXAMPLES              = 4
DSL_WARN, DSL_FAIL        = 0.15, 0.30
EXIT_KW = ["handoff", "escalar", "agente humano", "no puedo", "transferir", "escalación"]
FAIL_KW = ["error", "fallo", "no disponible", "no encontrado", "herramienta",
           "sin stock", "agotado", "no hay", "no queda", "fuera de stock"]
NEG_KW  = ["no quiero", "cancelar", "ya no", "no gracias", "lo cancelo",
           "mejor no", "déjalo", "olvíd", "no me interesa", "para nada"]

def _load_config(script_path):
    cfg_path = os.path.join(os.path.dirname(script_path), "static_audit_config.yaml")
    if not os.path.isfile(cfg_path):
        return
    global SIZE_PROPOSE, SIZE_URGENT, MIN_EXAMPLES, DSL_WARN, DSL_FAIL
    global EXIT_KW, FAIL_KW, NEG_KW
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if "size" in cfg:
        SIZE_PROPOSE = cfg["size"].get("propose", SIZE_PROPOSE)
        SIZE_URGENT  = cfg["size"].get("urgent",  SIZE_URGENT)
    if "min_examples" in cfg:
        MIN_EXAMPLES = cfg["min_examples"].get("min", MIN_EXAMPLES)
    if "dsl_density" in cfg:
        DSL_WARN = cfg["dsl_density"].get("warn", DSL_WARN)
        DSL_FAIL = cfg["dsl_density"].get("fail", DSL_FAIL)
    if "exit_paths" in cfg:
        EXIT_KW = cfg["exit_paths"].get("keywords", EXIT_KW)
    if "tool_fail_examples" in cfg:
        FAIL_KW = cfg["tool_fail_examples"].get("keywords", FAIL_KW)
    if "negation_examples" in cfg:
        NEG_KW = cfg["negation_examples"].get("keywords", NEG_KW)

_load_config(os.path.abspath(__file__))


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


ASSIGN_RE = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)\s*=')

def _check_params(pb, text):
    declared = {p["name"] for section in ("inputParameterDefinitions", "outputParameterDefinitions")
                for p in pb.get(section, [])}
    # $param_name — the regex matches $word but NOT ${...} (brace after $ is not a letter)
    refs   = set(re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)', text))
    locals_= set(ASSIGN_RE.findall(text))         # $x = ... → computado en la instrucción, no es param de schema
    orphan = refs - declared - locals_
    # refs pegadas a texto sin delimitador ($totaleuros = $total + "euros"): artefacto del regex,
    # no un param distinto. Un prefijo que ES otra ref + sufijo puramente alfabético → glue.
    glued  = {o for o in orphan
              if any(o != r and o.startswith(r) and o[len(r):].isalpha() for r in refs)}
    real = orphan - glued
    if not real:
        return "✅"
    # 🟡 (no 🔴): el linter no distingue 'cargado de tool/runtime' de 'falta de verdad' → señal, no error.
    return f"🟡 sin declarar (revisar tool/locales): {', '.join(sorted(real))}"


def _check_examples(ex_dir):
    if not os.path.isdir(ex_dir):
        return 0, "🔴 sin carpeta", "🔴 sin carpeta", "🔴 sin carpeta", "🔴 sin carpeta"

    files = [f for f in glob.glob(os.path.join(ex_dir, "*.yaml")) if os.path.isfile(f)]
    n = len(files)

    has_always = has_fail = has_neg = saw_strategy = False
    for f in files:
        d = _load(f)
        if "selectionStrategy" in d or "selection_strategy" in d:
            saw_strategy = True
        strategy = str(d.get("selectionStrategy", d.get("selection_strategy", ""))).upper()
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
    # selectionStrategy NO viaja en el export REST de CX → si nunca aparece, es inmedible, no un fallo.
    always  = "✅" if has_always else ("🟡 sin always_select" if saw_strategy else "➖ n/d (no en export)")
    tool_f  = "✅" if has_fail   else "🟡 sin ejemplo de fallo"
    neg     = "✅" if has_neg    else "🟡 sin negación"
    return n, ex_cnt, always, tool_f, neg


# ── Defaults adicionales (CX-35) ─────────────────────────────────────────────
STEPS_WARN, STEPS_FAIL = 15, 25
MAX_PLAYBOOKS          = 50
SNAKE_RE = re.compile(r'^[a-z][a-z0-9_]*$')
PB_REF_RE = re.compile(r'\$\{PLAYBOOK:([^}]+)\}')


def _check_name_len(pb, name):
    dn = pb.get("displayName")
    if not dn:  # sin displayName → usa el fichero como fallback, no es el foco
        return "✅"
    return "✅" if len(dn) <= 64 else f"🔴 displayName {len(dn)}>64"


def _check_snake(pb):
    bad = {p["name"] for section in ("inputParameterDefinitions", "outputParameterDefinitions")
           for p in pb.get(section, []) if not SNAKE_RE.match(p.get("name", ""))}
    if not bad:
        return "✅"
    return f"🔴 no snake_case: {', '.join(sorted(bad))}"


def _check_steps(pb):
    n = len(pb.get("instruction", {}).get("steps", []))
    u = "paso" if n == 1 else "pasos"
    if n > STEPS_FAIL:  return f"🔴 {n} {u}"
    if n > STEPS_WARN:  return f"🟡 {n} {u}"
    return f"✅ {n} {u}"


def _pb_refs(pb):
    # OJO: solo capta la sintaxis DSL ${PLAYBOOK:X}. Petal mezcla estilos: hay delegaciones
    # en prosa ("transfiere a Gestion_Deuda") que NO se ven aquí → CX-28 puede dar falso
    # negativo si un ciclo pasa por una delegación en prosa. Limitación conocida.
    return set(PB_REF_RE.findall(_instr_text(pb)))


def _tools_count(pb):
    rt = pb.get("referencedTools") or pb.get("referencedTool") or []
    if isinstance(rt, str):
        rt = [rt]
    return len(set(rt))


def _check_single_resp(pb):
    delegs = len(_pb_refs(pb))
    tools  = _tools_count(pb)
    if delegs > 1 and tools > 3:
        return f"🟡 candidato a dividir ({delegs} delegaciones, {tools} tools)"
    return "✅"


def _build_cycles(pbs):
    # pbs: {displayName: set(refs)}. Grafo dirigido por displayName; refs a
    # playbooks inexistentes se ignoran (no son ciclos). DFS con back-edge.
    nodes = set(pbs)
    graph = {n: {r for r in refs if r in nodes} for n, refs in pbs.items()}
    in_cycle = set()
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}

    def dfs(n, stack):
        color[n] = GRAY
        stack.append(n)
        for m in graph[n]:
            if color[m] == GRAY:           # back-edge → ciclo
                i = stack.index(m)
                for x in stack[i:]:
                    in_cycle.add(x)
            elif color[m] == WHITE:
                dfs(m, stack)
        stack.pop()
        color[n] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            dfs(n, [])
    return in_cycle


def _check_max_playbooks(n):
    if n > MAX_PLAYBOOKS:    return f"🔴 {n}>{MAX_PLAYBOOKS} playbooks"
    if n > MAX_PLAYBOOKS - 10: return f"🟡 {n} playbooks (cerca del límite {MAX_PLAYBOOKS})"
    return f"✅ {n} playbooks"


def audit(root):
    pb_dir = os.path.join(root, "definitions", "playbooks")
    ex_dir = os.path.join(root, "definitions", "examples")
    sys.path.insert(0, os.path.join(root, "qap", "adk_fidelity"))
    import petal_agent

    files = sorted(glob.glob(os.path.join(pb_dir, "*.yaml")))
    # carga previa para el grafo de delegación (CX-28) — mapea por displayName
    pbs   = {os.path.splitext(os.path.basename(f))[0]: _load(f) for f in files}
    graph = {pb.get("displayName", name): _pb_refs(pb) for name, pb in pbs.items()}
    in_cycle = _build_cycles(graph)

    rows = []
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        pb   = pbs[name]
        text = _instr_text(pb)
        tokens   = _tok(petal_agent._playbook_text(name))
        dsl_pct, dsl_f = _check_dsl(text)
        n_ex, ex_cnt, always_f, fail_f, neg_f = _check_examples(os.path.join(ex_dir, name))
        dn = pb.get("displayName", name)
        cycle_f = f"🔴 ciclo de delegación ({dn})" if dn in in_cycle else "✅"
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
            "name_len":  _check_name_len(pb, name),
            "snake":     _check_snake(pb),
            "steps":     _check_steps(pb),
            "cycle":     cycle_f,
            "single":    _check_single_resp(pb),
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
        print(f"   name len    (CX-29):  {r['name_len']}")
        print(f"   snake_case  (CX-33):  {r['snake']}")
        print(f"   nº pasos    (CX-35):  {r['steps']}")
        print(f"   ciclo deleg (CX-28):  {r['cycle']}")
        print(f"   1 respons   (CX-32):  {r['single']}")

    print("\n" + "=" * 80)
    urgent = [r["name"] for r in rows if "URGENTE" in r["size"]]
    warn   = [r["name"] for r in rows if "refactor" in r["size"]]
    issues = [r["name"] for r in rows
              if any("🟡" in str(v) or "🔴" in str(v)
                     for k, v in r.items() if k != "size" and isinstance(v, str))]
    print(f"TAMAÑO:  🔴 {len(urgent)} urgente(s): {urgent or '—'}  ·  🟡 {len(warn)} refactor: {warn or '—'}")
    print(f"MAX PB   (CX-30):  {_check_max_playbooks(len(rows))}")
    print(f"CHECKS:  {len(issues)}/{len(rows)} playbooks con algún check fallido")
    print("=" * 80)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="raíz del repo con definitions/")
    report(audit(ap.parse_args().root))
