"""Reconstrucción de Petal en ADK para el experimento de fidelidad ADK vs CX.

NO es Petal exacto: CX envuelve los playbooks en su harness propietario y enruta
entre sub-playbooks con su NLU. Aquí inlineamos todos los playbooks en una sola
instrucción y exponemos el webhook como tool. El GAP entre esto y CX es justo lo
que el experimento mide.
"""
import os
import glob
import yaml
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PB_DIR = os.path.join(ROOT, "definitions", "playbooks")
EX_DIR = os.path.join(ROOT, "definitions", "examples")
# URL del backend: del entorno o de .env (privado, fuera del repo público). Vacío si falta.
PETAL_API = os.environ.get("PETAL_API_URL", "")
if not PETAL_API and os.path.exists(os.path.join(ROOT, ".env")):
    for _l in open(os.path.join(ROOT, ".env")):
        if _l.startswith("PETAL_API_URL="):
            PETAL_API = _l.split("=", 1)[1].strip()

# Orden: orquestador primero, luego sub-playbooks (como los referencia CX)
PLAYBOOK_ORDER = [
    "petal_cx_orchestrator", "compra", "checkout",
    "registro_task", "gestion_deuda", "handoff",
]


def _format_example(ex: dict) -> str:
    """Convierte un example de CX (actions: userUtterance/toolUse/agentUtterance)
    en una demostración few-shot legible para el modelo."""
    lines = [f"# Ejemplo: {ex.get('displayName', '')}"]
    if ex.get("description"):
        lines.append(f"# ({ex['description']})")
    for act in ex.get("actions", []):
        if "userUtterance" in act:
            lines.append(f"Usuario: {act['userUtterance'].get('text', '')}")
        elif "agentUtterance" in act:
            lines.append(f"Petal: {act['agentUtterance'].get('text', '')}")
        elif "toolUse" in act:
            tu = act["toolUse"]
            inp = tu.get("inputActionParameters", {})
            out = tu.get("outputActionParameters", {})
            out_summary = ""
            for _code, payload in (out or {}).items():
                if isinstance(payload, dict):
                    res = payload.get("resultados")
                    out_summary = str(res)[:220] if res is not None else str(payload)[:220]
            lines.append(f"[Llama consultar_datos({inp}) → {out_summary}]")
        elif "playbookInvocation" in act:
            pi = act["playbookInvocation"]
            pb = pi.get("playbook", "")
            pb = pb.split("/")[-1] if isinstance(pb, str) else pi.get("displayName", "")
            lines.append(f"[Deriva al flujo: {pb}]")
    return "\n".join(lines)


def _load_examples(name: str) -> str:
    ex_dir = os.path.join(EX_DIR, name)
    if not os.path.isdir(ex_dir):
        return ""
    blocks = []
    for f in sorted(glob.glob(os.path.join(ex_dir, "*.yaml"))):
        ex = yaml.safe_load(open(f))
        if ex and ex.get("actions"):
            blocks.append(_format_example(ex))
    if not blocks:
        return ""
    return ("\n\nEJEMPLOS DE CONVERSACIÓN (few-shot — imita estos patrones de cuándo "
            "llamar a la herramienta y cómo responder):\n\n" + "\n\n".join(blocks))


def _params_text(d: dict) -> str:
    """Nivel 1 — el modelo CONOCE los parámetros (entrada/salida) del playbook.
    Incluye las definiciones de inputParameterDefinitions / outputParameterDefinitions
    (grupo_intent, estado_pago, contadores, flags...). NO cablea valores (eso es Nivel 2,
    state + callbacks). Sin esto, el modelo lee instrucciones que referencian parámetros
    que no sabe que existen."""
    blocks = []
    for key, label in [
        ("inputParameterDefinitions", "PARÁMETROS DE ENTRADA (recibes estos del orquestador/sesión)"),
        ("outputParameterDefinitions", "PARÁMETROS DE SALIDA (debes producir/actualizar estos)"),
    ]:
        defs = d.get(key) or []
        if defs:
            lines = [f"  - {p.get('name')}: {(p.get('description') or '').strip()}" for p in defs]
            blocks.append(f"{label}:\n" + "\n".join(lines))
    return ("\n\n" + "\n\n".join(blocks)) if blocks else ""


def _playbook_text(name: str) -> str:
    d = yaml.safe_load(open(os.path.join(PB_DIR, f"{name}.yaml")))
    goal = d.get("goal", "")
    steps = d.get("instruction", {}).get("steps", []) or []
    body = "\n".join(
        (s.get("text", "") if isinstance(s, dict) else str(s)) for s in steps
    )
    params = _params_text(d)
    examples = _load_examples(name)
    return f"### PLAYBOOK: {d.get('displayName', name)}\nOBJETIVO: {goal}{params}\n\n{body}{examples}"


def load_instruction() -> str:
    parts = [_playbook_text(n) for n in PLAYBOOK_ORDER]
    header = (
        "Eres el agente conversacional Petal. A continuación tienes TODOS tus playbooks. "
        "El primero (orquestador) decide a qué flujo derivar; los siguientes son los flujos. "
        "Compórtate como un único agente que sigue estas instrucciones. Cuando necesites datos "
        "(inventario, perfil de cliente, validar pedido, crear pedido), USA la herramienta "
        "consultar_datos. NUNCA inventes inventario, precios ni stock.\n\n"
    )
    return header + "\n\n".join(parts)


def consultar_datos(
    recurso: str,
    accion: str = "leer",
    producto: str = "", color: str = "", categoria: str = "", ocasion: str = "",
    tamano: str = "", precio_max: float = 0, productos_excluidos: str = "",
    limit: int = 5, tipo: str = "",
    email: str = "", id: str = "",
    nombre: str = "", apellidos: str = "", calle: str = "", codigo_postal: str = "",
    ciudad: str = "", telefono: str = "", cif: str = "",
    clave: str = "",
    cantidad: int = 0, precio_estimado: float = 0, estado_pago: str = "",
    id_cliente: str = "",
) -> dict:
    """Consulta o escribe datos de la floristeria Petal (Google Sheets).

    recurso: uno de [inventario, perfil, registro, business, agent_copy, validar_pedido, pedidos].
      - inventario: buscar flores. Usa producto, color, ocasion, tamano, precio_max, limit, productos_excluidos.
      - perfil: buscar cliente por email o id.
      - registro: alta de cliente (nombre, apellidos, calle, codigo_postal, ciudad, telefono, tipo, cif).
      - validar_pedido: comprobar si un cliente puede pedir (id, cantidad, precio_estimado, estado_pago).
      - business / agent_copy: variables del negocio por clave.
    accion: 'leer' (default), 'crear' o 'actualizar'.
    Devuelve un JSON con los resultados reales del backend. No inventes datos: usa lo que devuelve.
    """
    params = {"recurso": recurso, "accion": accion}
    optional = {
        "producto": producto, "color": color, "categoria": categoria, "ocasion": ocasion,
        "tamano": tamano, "productos_excluidos": productos_excluidos, "tipo": tipo,
        "email": email, "id": id, "nombre": nombre, "apellidos": apellidos, "calle": calle,
        "codigo_postal": codigo_postal, "ciudad": ciudad, "telefono": telefono, "cif": cif,
        "clave": clave, "estado_pago": estado_pago, "id_cliente": id_cliente,
    }
    for k, v in optional.items():
        if v:
            params[k] = v
    for k, v in [("precio_max", precio_max), ("precio_estimado", precio_estimado),
                 ("limit", limit), ("cantidad", cantidad)]:
        if v:
            params[k] = v
    try:
        r = requests.get(PETAL_API, params=params, timeout=30)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# Modelo configurable por env. Local $0: ollama_chat/qwen2.5:14b (¡ollama_chat, NO ollama!).
# Cloud: gemini-2.5-flash (modelo real de CX, free tier 20/día).
ADK_MODEL = os.environ.get("ADK_MODEL", "ollama_chat/qwen2.5:14b")
os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")


def build_agent():
    from google.adk.agents import LlmAgent
    if ADK_MODEL.startswith("ollama"):
        from google.adk.models.lite_llm import LiteLlm
        # temp=0 + seed: banco de MEDICIÓN → determinista/reproducible (sin ruido de sampling).
        # Default de Ollama es temp~0.8 (variabilidad) → ensuciaba el baseline.
        model = LiteLlm(model=ADK_MODEL, temperature=0.0, seed=42)
    else:
        model = ADK_MODEL
    # Instrucción como callable: ADK pone bypass_state_injection=True y NO interpola
    # las llaves {..} literales de los playbooks (ejemplos JSON, etc.)
    instruction_text = load_instruction()
    return LlmAgent(
        name="petal_adk",
        model=model,
        instruction=lambda ctx: instruction_text,
        tools=[consultar_datos],
    )
