"""Pre-gate anti-fuga + degeneración → veredicto 3-estados (P1+P2, 12-jun).

POR QUÉ: el cribador reconstruye Petal a partir del prompt COMPILADO de CX. Ese prompt
contiene directivas EJECUTABLES de CX (${PLAYBOOK:..}, $var=, PASO N, sourceMapping...).
Un LLM pelado a veces las ESCUPE como texto en vez de ejecutarlas → la respuesta es
ANDAMIAJE, no comportamiento del agente. La rúbrica regex (check_turn) puede coincidir por
casualidad → un PASS/FAIL FALSO. Eso no es ni PASS ni FAIL: es INVALID — la medida no cuenta
(fallo del HARNESS, no del agente). Ver ADK-29 (kb_plat_adk) + handoff velocidad 12-jun.

ALTA PRECISIÓN obligatoria: el lexicón debe disparar ~0 sobre transcripts de CX reales
(Petal NUNCA dice "${PLAYBOOK:Handoff}"). Por eso solo usamos SINTAXIS de directiva CX-DSL,
que no aparece en habla natural — NO nombres "pelados" (p.ej. "compra"/"bienvenida" son
palabras naturales que Petal sí diría → flaggearlas serían falsos positivos).

API:
  build_lexicon(prompt) -> dict   # patrones + tokens cosechados del prompt (para el reporte)
  classify_turn(text, lex) -> (estado, motivo)   # estado in {"OK","INVALID"}
"""
import re
from collections import Counter

# Patrones ESTRUCTURALES de CX-DSL. Si aparecen en una respuesta = fuga de andamiaje → INVALID.
# Son sintaxis, no palabras → no aparecen en conversación natural → alta precisión.
STRUCTURAL = [
    (r"\$\{PLAYBOOK\b",                              "referencia a playbook ${PLAYBOOK:..}"),
    (r"\$\{[A-Za-z_][^}]*\}",                        "interpolacion ${var}"),
    (r"\$[A-Za-z_][\w.]*\s*=",                       "asignacion de variable $var="),
    (r"\$(session|flow|page|user|request)\.[A-Za-z_]", "scope de CX $session/$flow/.."),
    (r"\bPASO\s+\d+\b",                              "marcador de paso 'PASO N'"),
    (r"\b(sourceMapping|updateMask|displayName|webhookState)\b", "campo de la API de CX"),
    (r"\[\s*estado\s*\]",                            "marcador [estado]"),
    (r"^\s*```(tool|json|python|yaml)",              "bloque de codigo/tool-call"),
    (r"\bTOOL[_ ]?CALL\b|\bfunction_call\b",         "tool-call literal"),
]


def _degenerate(text):
    """Detecta no-respuesta o atasco del modelo (también INVALID). -> motivo | None."""
    t = (text or "").strip()
    if not t:
        return "respuesta vacia"
    if t.startswith("ERROR_"):
        return t.split(":")[0].replace("ERROR_", "error: ").lower()
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    for i in range(len(lines) - 2):                       # línea idéntica 3+ veces seguidas
        if lines[i] == lines[i + 1] == lines[i + 2]:
            return "repeticion de linea"
    words = t.split()
    if len(words) >= 30:                                  # loop de 4-grama dentro de texto largo
        grams = Counter(tuple(words[i:i + 4]) for i in range(len(words) - 3))
        if grams and grams.most_common(1)[0][1] > 3:
            return "loop de n-grama"
    return None


def build_lexicon(prompt):
    """Cosecha del prompt compilado los tokens de directiva (para transparencia/reporte) y
    devuelve los patrones estructurales activos. La detección usa los patrones (alta precisión);
    los tokens cosechados se listan para saber QUÉ andamiaje contiene este prompt concreto."""
    p = prompt or ""
    variables = sorted({m.group(1) for m in re.finditer(r"\$([A-Za-z_]\w{2,})", p)})
    playbooks = sorted({m.group(1).strip()
                        for m in re.finditer(r"PLAYBOOK[:\s]+([A-Za-z][\w ]{2,40})", p)})
    return {"structural": STRUCTURAL,
            "tokens": {"variables": variables, "playbooks": playbooks}}


def classify_turn(agent_text, lexicon):
    """-> ('OK'|'INVALID', motivo). OK = medida válida → pasa a la rúbrica PASS/FAIL.
    INVALID = degeneración o fuga de andamiaje → no cuenta como fidelidad."""
    deg = _degenerate(agent_text)
    if deg:
        return "INVALID", f"degeneracion: {deg}"
    text = agent_text or ""
    for pat, why in lexicon["structural"]:
        if re.search(pat, text, re.MULTILINE):
            return "INVALID", f"fuga: {why}"
    return "OK", ""


def _demo():
    lex = build_lexicon("### PLAYBOOK: Handoff\n$cliente_nombre = ...\nPASO 1: saluda")
    casos = [
        "¡Hola! Soy Petal 🌸 ¿En qué puedo ayudarte hoy?",            # OK (natural)
        "$cliente_nombre = Ana; ${PLAYBOOK:Handoff} PASO 3",          # INVALID (fuga)
        "Claro, te paso con un agente humano.",                       # OK
        "sí sí sí\nsí sí sí\nsí sí sí",                               # INVALID (repetición)
        "",                                                           # INVALID (vacío)
    ]
    print("tokens cosechados:", lex["tokens"])
    for c in casos:
        print(classify_turn(c, lex), "<-", repr(c[:48]))


if __name__ == "__main__":
    _demo()
