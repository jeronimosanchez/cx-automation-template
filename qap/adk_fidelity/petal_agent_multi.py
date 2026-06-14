"""Reconstrucción MULTI-AGENTE de Petal — renderer v2 (AgentTool, call-and-return).

v2 (14-jun): la delegación usa AgentTool, NO sub_agents (transfer_to_agent).
El orquestador invoca cada sub-playbook como una TOOL: pasa el control, el
sub-playbook responde, y el control VUELVE al orquestador — igual que CX hace
"${PLAYBOOK:X} → cuando vuelve, sigo". Mata el ping-pong orquestador↔sub que en
v1 (sub_agents) grindaba ~140 llamadas/TC. Ver kb_plat_adk ADK-30 + ADK-26.

Uso: ADK_RECON=multi python run_fidelity.py
"""
import os, re
import yaml
from petal_agent import consultar_datos, _playbook_text, ADK_MODEL, PB_DIR  # reusa la plana

# Sub-playbooks que cuelgan del orquestador (el orquestador va aparte)
# Local (ollama/openai) sufre el tool-calling frágil de litellated → necesita el callback
# secuencial. Gemini lo maneja nativo → no se le aplica (no contaminar su baseline).
_IS_LOCAL = ADK_MODEL.startswith("ollama") or ADK_MODEL.startswith("openai")

SUB_PLAYBOOKS = ["compra", "checkout", "registro_task", "gestion_deuda", "handoff"]

# Descripción de cada sub-agente → el orquestador la usa para decidir a quién derivar.
# CRÍTICO (12.2 del RES): el `description` ES el prompt de routing — vago = mal routing.
SUB_DESC = {
    "compra": "Búsqueda de productos e inventario, recomendaciones, armar el pedido.",
    "checkout": "Confirmar pedido, dirección de entrega, pago y finalizar la compra.",
    "registro_task": "Alta de cliente nuevo (nombre, email, dirección).",
    "gestion_deuda": "Cliente con deuda o moroso; gestión de pago pendiente.",
    "handoff": "Derivar a un agente humano (lo pide el cliente o hay frustración).",
}


def _route_to_tool(text):
    """Traduce la directiva CX ${PLAYBOOK:Xxx} → instrucción de llamar a la tool
    `petal_xxx` (el nombre del AgentTool). Necesario para que el orquestador sepa
    QUÉ herramienta es cada flujo. Es la traducción MÍNIMA de ADK-29 para que
    AgentTool funcione; NO es el anti-fuga completo (eso es el paso 2, after_model_callback)."""
    return re.sub(
        r"\$\{PLAYBOOK:\s*([^}]+?)\s*\}",
        lambda m: f"la herramienta `petal_{m.group(1).strip().lower()}`",
        text,
    )


def _model():
    # openai/<modelo> → endpoint OpenAI-compatible de Ollama (/v1). SALTA el handler
    # ollama_chat.py de litellm, que está roto para tool-calls (serializa mal assistant
    # tool_calls + content array → "Missing tool results" → loop). Fix #1 del research
    # (confirmado en litellm #11273 / adk #677). Preserva la arquitectura: solo cambia el
    # transporte. ollama_chat/<modelo> queda como fallback.
    if ADK_MODEL.startswith("openai"):
        os.environ.setdefault("OPENAI_API_BASE", "http://localhost:11434/v1")
        os.environ.setdefault("OPENAI_API_KEY", "ollama")
    if ADK_MODEL.startswith("ollama") or ADK_MODEL.startswith("openai"):
        from google.adk.models.lite_llm import LiteLlm
        import litellm
        litellm.drop_params = True   # traga params no soportados (parallel_tool_calls)
        # temp=0 + seed: banco de medición determinista (igual que la plana).
        return LiteLlm(model=ADK_MODEL, temperature=0.0, seed=42)
    return ADK_MODEL


# Cap MANUAL de llamadas por TC. El max_llm_calls de ADK NO bordea con AgentTool (cada
# sub-agente corre en Runner HIJO con contador propio → resetea). Y el state del callback
# NO persiste entre llamadas en 1.21 (el delta no se commitea hasta cerrar el evento).
# → Contador GLOBAL de módulo (in-process, inmediato), reseteado por el harness por TC.
# Cuenta TODAS las llamadas (orquestador + sub-agentes, mismo módulo) → bordea el churn total.
LOCAL_CALL_CAP = int(os.environ.get("ADK_CALL_CAP", "6"))
_CALL_COUNTER = {"n": 0}


def reset_call_counter():
    """El harness lo llama al inicio de cada TC."""
    _CALL_COUNTER["n"] = 0


def _diag_before_model(callback_context, llm_request):
    """before_model_callback: (1) CAP global anti-churn (corta a N llamadas/TC),
    (2) DIAGNÓSTICO gated ADK_DIAG=1 (registra roles/partes/args)."""
    # --- CAP global (in-process, fiable; el state del callback no persiste en 1.21) ---
    _CALL_COUNTER["n"] += 1
    if _CALL_COUNTER["n"] > LOCAL_CALL_CAP:
        from google.adk.models.llm_response import LlmResponse
        from google.genai import types
        return LlmResponse(content=types.Content(
            role="model",
            parts=[types.Part(text=f"ERROR_CAP_CHURN: {_CALL_COUNTER['n']} llamadas > cap {LOCAL_CALL_CAP}")]))
    if os.environ.get("ADK_DIAG") != "1":
        return None
    try:
        lines = []
        for c in (getattr(llm_request, "contents", None) or []):
            role = getattr(c, "role", "?")
            tags = []
            for p in (getattr(c, "parts", None) or []):
                if getattr(p, "function_call", None):
                    tags.append(f"CALL:{p.function_call.name}(args={dict(p.function_call.args or {})})")
                elif getattr(p, "function_response", None):
                    tags.append(f"RESP:{p.function_response.name}={str(p.function_response.response)[:60]}")
                elif getattr(p, "text", None):
                    tags.append(f"text[{p.text[:60]!r}]")
            lines.append(f"  {role}: {', '.join(tags) or '-'}")
        agent_name = getattr(callback_context, "agent_name", "?")
        with open("/tmp/adk_diag.log", "a") as f:
            f.write(f"=== REQUEST por [{agent_name}] ({len(lines)} msgs) ===\n" + "\n".join(lines) + "\n")
    except Exception as e:
        with open("/tmp/adk_diag.log", "a") as f:
            f.write(f"[diag error: {e}]\n")
    return None


def _strip_leak(text):
    """Quita líneas de andamiaje CX-DSL fugado (sourceMapping, $var=, ${PLAYBOOK}, PASO N)
    del texto. Replica la capa de interpretación de CX: el motor EJECUTA esas directivas y
    el cliente NUNCA las ve. Paso 2 / ADK-32 / ADK-29. Reusa los patrones de static_leak_gate.
    Limpia en ORIGEN ≠ medir: static_leak_gate sigue dando el veredicto para registrar
    cuánto se fugaba (salud del harness)."""
    import static_leak_gate as lk
    out = [ln for ln in (text or "").splitlines()
           if not any(re.search(pat, ln) for pat, _ in lk.STRUCTURAL)]
    return "\n".join(out).strip()


def _clean_output(callback_context, llm_response):
    """after_model_callback (todos los modelos): (1) limpia el andamiaje CX-DSL fugado del
    texto (paso 2, ADK-32), (2) se queda con la 1ª function_call (ollama_chat no soporta
    paralelas → evita 'Missing tool results'; en Gemini es inocuo, stepwise = fiel a CX)."""
    resp = llm_response
    if not resp or not getattr(resp, "content", None) or not resp.content.parts:
        return None
    seen_fc, changed, new_parts = False, False, []
    for p in resp.content.parts:
        if getattr(p, "function_call", None):
            if seen_fc:
                changed = True
                continue
            seen_fc = True
            new_parts.append(p)
        elif getattr(p, "text", None):
            cleaned = _strip_leak(p.text)
            if cleaned != p.text:
                p.text = cleaned
                changed = True
            new_parts.append(p)
        else:
            new_parts.append(p)
    if changed:
        resp.content.parts = new_parts
        return resp
    return None


def _input_schema(name):
    """Pydantic schema desde los inputParameterDefinitions del playbook. AgentTool sin
    input_schema espera UN arg 'request'; pero el orquestador pasa el DICT de params de CX
    (modo_tono, grupo_intent, producto...) → mismatch → el sub-agente no recibe la query →
    loop. Con input_schema, AgentTool valida el dict y se lo pasa estructurado al sub-agente
    (= como CX pasa inputParameterDefinitions entre playbooks). Fiel a CX. Ver ADK-38."""
    from pydantic import create_model, ConfigDict
    from typing import Optional, Any
    d = yaml.safe_load(open(os.path.join(PB_DIR, f"{name}.yaml")))
    defs = d.get("inputParameterDefinitions") or []
    fields = {p["name"]: (Optional[Any], None) for p in defs if p.get("name")}
    if not fields:
        return None
    # extra="allow": el orquestador a veces pasa params no declarados → no romper por eso.
    return create_model(f"{name}_input", __config__=ConfigDict(extra="allow"), **fields)


def _sub_agent(name):
    from google.adk.agents import LlmAgent
    instr = _playbook_text(name)  # SOLO este playbook (literal) + sus examples
    # t=instr en el lambda: captura la instrucción correcta por sub-agente (evita
    # el bug clásico de closure en bucle); el callable activa bypass_state_injection.
    return LlmAgent(
        name=f"petal_{name}",
        model=_model(),
        description=SUB_DESC.get(name, name),
        instruction=lambda ctx, t=instr: t,
        input_schema=_input_schema(name),   # acepta los params de CX que pasa el orquestador
        tools=[consultar_datos],
        before_model_callback=_diag_before_model,
        after_model_callback=_clean_output,
    )


def build_agent():
    """Orquestador con los sub-playbooks como AgentTool (call-and-return, ADK-30).
    El orquestador invoca el sub-playbook como tool → respuesta → sigue. No hay
    transfer_to_agent → no hay ping-pong."""
    from google.adk.agents import LlmAgent
    from google.adk.tools.agent_tool import AgentTool
    orch_instr = _route_to_tool(_playbook_text("petal_cx_orchestrator"))
    # skip_summarization=False (default): tras volver el sub-agente, el orquestador SÍ hace
    # el paso de summarization → relaya/sintetiza la respuesta final al cliente. Con True,
    # el padre NO sintetiza → respuesta vacía. El loop NO lo causaba la summarization sino el
    # contrato de args (resuelto con input_schema en el sub-agente). Ver ADK-38.
    sub_tools = [AgentTool(agent=_sub_agent(n)) for n in SUB_PLAYBOOKS]
    return LlmAgent(
        name="petal_orchestrator",
        model=_model(),
        instruction=lambda ctx: orch_instr,
        tools=[consultar_datos] + sub_tools,  # datos + delegación-como-tool
        before_model_callback=_diag_before_model,
        after_model_callback=_clean_output,
    )
