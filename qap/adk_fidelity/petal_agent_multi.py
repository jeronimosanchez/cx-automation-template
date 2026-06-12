"""Reconstrucción MULTI-AGENTE de Petal: un orquestador enruta a sub-agentes,
y cada sub-agente carga SOLO su playbook (no los 6 juntos como la plana).

POR QUÉ (3 razones, independientes del hardware):
  1. FIDELIDAD: reproduce el enrutado de CX (donde viven los bugs). La plana da
     los 6 playbooks de golpe — algo que CX nunca hace.
  2. ESCALA: 60 playbooks en un prompt es inviable; uno a la vez escala.
  3. CONTEXTO/VELOCIDAD: prompt activo ~7-15k por turno (no ~36k) → cabe con
     holgura, sin context-shift, caching consistente → más rápido.

BORRADOR: la mecánica de delegación de ADK (sub_agents → transfer_to_agent) hay
que VALIDARLA en test — un 14B local puede no derivar de forma fiable. Probar
DESPUÉS del baseline plano, para comparar antes/después con TCs discriminantes.

Uso: ADK_RECON=multi python run_fidelity.py
"""
import os, re
from petal_agent import consultar_datos, _playbook_text, ADK_MODEL  # reusa la plana

# P3 (experimento, flag ADK_P3=1): neutraliza SOLO las directivas ${PLAYBOOK:X} y ${...} — la sintaxis
# EJECUTABLE de transferencia/interpolación de CX que el LLM fuga (C29/C31/C35) y que dispara el loop de
# delegación (orquestador↔sub). Los $var (594, estado/slots) y PASO (99, referencias de flujo) se DEJAN:
# son lógica load-bearing; borrarlos rompería el comportamiento. Objetivo: ¿baja calls/TC + INVALID sin tirar el acuerdo?
P3 = os.environ.get("ADK_P3") == "1"


def _sanitize(text):
    if not P3:
        return text
    t = re.sub(r"\$\{PLAYBOOK:\s*([^}]+?)\s*\}", r"el flujo \1", text)  # ${PLAYBOOK:Handoff} -> "el flujo Handoff"
    t = re.sub(r"\$\{\s*([^}]+?)\s*\}", r"\1", t)                       # ${x} -> x
    return t

# Sub-playbooks que cuelgan del orquestador (el orquestador va aparte)
SUB_PLAYBOOKS = ["compra", "checkout", "registro_task", "gestion_deuda", "handoff"]

# Descripción de cada sub-agente → el orquestador la usa para decidir a quién derivar.
# (En CX esto lo hace el clasificador NLU por grupo_intent; aquí lo guía el LLM.)
SUB_DESC = {
    "compra": "Búsqueda de productos e inventario, recomendaciones, armar el pedido.",
    "checkout": "Confirmar pedido, dirección de entrega, pago y finalizar la compra.",
    "registro_task": "Alta de cliente nuevo (nombre, email, dirección).",
    "gestion_deuda": "Cliente con deuda o moroso; gestión de pago pendiente.",
    "handoff": "Derivar a un agente humano (lo pide el cliente o hay frustración).",
}


def _model():
    if ADK_MODEL.startswith("ollama"):
        from google.adk.models.lite_llm import LiteLlm
        # temp=0 + seed: igual que la plana, banco de medición determinista.
        return LiteLlm(model=ADK_MODEL, temperature=0.0, seed=42)
    return ADK_MODEL


def _sub_agent(name):
    from google.adk.agents import LlmAgent
    instr = _sanitize(_playbook_text(name))  # SOLO este playbook (literal) + sus examples; P3 neutraliza ${PLAYBOOK:}
    # t=instr en el lambda: captura la instrucción correcta por sub-agente (evita el
    # bug clásico de closure en bucle).
    return LlmAgent(
        name=f"petal_{name}",
        model=_model(),
        description=SUB_DESC.get(name, name),
        instruction=lambda ctx, t=instr: t,
        tools=[consultar_datos],
    )


def build_agent():
    """Orquestador con los sub-agentes colgando. ADK auto-genera transfer_to_agent
    para la delegación; el orquestador (su playbook) guía cuándo derivar."""
    from google.adk.agents import LlmAgent
    orch_instr = _sanitize(_playbook_text("petal_cx_orchestrator"))
    return LlmAgent(
        name="petal_orchestrator",
        model=_model(),
        instruction=lambda ctx: orch_instr,
        sub_agents=[_sub_agent(n) for n in SUB_PLAYBOOKS],
        tools=[consultar_datos],  # el orquestador también puede consultar datos
    )
