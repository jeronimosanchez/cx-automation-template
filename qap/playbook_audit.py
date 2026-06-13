"""playbook_audit (Capa 0 / L0): LINTER ESTÁTICO de playbooks CX.

$0, instantáneo, SIN emulador ni LLM. Audita el DISEÑO de los playbooks antes del deploy.
Checks (MVP):
  · TAMAÑO  (CX-25): tokens por playbook → ✅<5k · 🟡>5k propone refactor · 🔴>10k urgente.
  · EXAMPLES (CX-13/Google "examples > instructions"): nº de examples → 🟡<4 (Google recomienda ≥4).
Dogfooding sobre Petal; agnóstico vía --root (otro cliente = otro repo de definitions/).

Uso: python qap/playbook_audit.py [--root <repo_root>]

Scope actual: solo playbooks. Roadmap de expansión L0:
  · Flows/Pages  — checks NLU: intents sin utterances, pages sin exit routes.
  · Entity Types — naming, cobertura mínima de valores.
  · Generators   — tamaño y referencias huérfanas.
  · Tools        — schemas incompletos, operationId con caracteres inválidos.
Cada componente se añade cuando el proyecto lo requiere — no antes.
"""
import os, sys, glob, argparse

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")
    _tok = lambda t: len(_enc.encode(t))
    _MET = "tiktoken/cl100k"
except Exception:
    _tok = lambda t: len(t) // 4
    _MET = "aprox chars/4"

SIZE_PROPOSE, SIZE_URGENT, MIN_EXAMPLES = 5000, 10000, 4


def audit(root):
    """Devuelve filas [(name, tokens, size_flag, n_examples, ex_flag)] por playbook."""
    pb_dir = os.path.join(root, "definitions", "playbooks")
    ex_dir = os.path.join(root, "definitions", "examples")
    # Reusa _playbook_text del cribador (compila instruction+params+examples como lo ve el agente).
    sys.path.insert(0, os.path.join(root, "qap", "adk_fidelity"))
    import petal_agent
    rows = []
    for f in sorted(glob.glob(os.path.join(pb_dir, "*.yaml"))):
        name = os.path.splitext(os.path.basename(f))[0]
        t = _tok(petal_agent._playbook_text(name))
        exd = os.path.join(ex_dir, name)
        n_ex = len([x for x in glob.glob(os.path.join(exd, "*")) if os.path.isfile(x)]) if os.path.isdir(exd) else 0
        size_flag = "🔴 refactor URGENTE" if t > SIZE_URGENT else ("🟡 propone refactor" if t > SIZE_PROPOSE else "✅ ok")
        ex_flag = f"🟡 <{MIN_EXAMPLES} examples" if n_ex < MIN_EXAMPLES else "✅ ok"
        rows.append((name, t, size_flag, n_ex, ex_flag))
    return rows


def report(rows):
    print(f"\npb-audit (L0) — linter estático de playbooks  ·  medición: {_MET}")
    print("=" * 78)
    print(f"{'playbook':<26}{'tokens':>8}  {'tamaño (CX-25)':<22}{'ej.':>4}  examples (CX-13)")
    print("-" * 78)
    for name, t, sf, n, ef in rows:
        print(f"{name:<26}{t:>8}  {sf:<22}{n:>4}  {ef}")
    print("=" * 78)
    refac = [r[0] for r in rows if "refactor" in r[2]]
    pocos = [r[0] for r in rows if "<" in r[4]]
    print(f"VEREDICTO: {len(refac)} playbook(s) a refactorizar por tamaño: {refac or '—'}")
    print(f"           {len(pocos)} playbook(s) con pocos examples (<{MIN_EXAMPLES}): {pocos or '—'}")
    print("=" * 78)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="raíz del repo con definitions/ (default: repo de este script)")
    report(audit(ap.parse_args().root))
