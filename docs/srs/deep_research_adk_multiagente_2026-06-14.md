# Deep Research — Fiabilidad de Google ADK multi-agente con tool-calling en local

**Fecha:** 2026-06-14 · **Estado:** ⚠️ PARCIAL (chocó con límite de sesión en síntesis + verificación de alternativas; reanudación pendiente)

---

## Objetivo

Hacer correr de forma **fiable** el cribador local ($0): ADK 1.35.0 multi-agente (orquestador→sub-playbooks, call-and-return vía AgentTool, webhooks como tools) reconstruyendo Petal de CX, sin aplanar a un router de un nivel.

**Problema:** el resultado de AgentTool se enhebra como user-text en vez de `function_response` emparejado al `tool_call_id` → tool_call "sin responder" → placeholder "missing tool result" → re-llamada → loop. No-determinista pese a `temp=0+seed=42` (pasa aislado, se atasca en run completo).

**Stack:** ADK 1.35.0 (no 2.x: 2.2 rompe AgentTool con `KeyError:'request'`) · LiteLLM 1.88.1 · Ollama 0.30.8 + qwen2.5:14b. Prompt completo en el script del workflow (ver abajo).

---

## Hallazgos CONFIRMADOS (verificación adversarial, 2-3 votos)

### 1. La causa raíz diagnosticada es CORRECTA — bug de ADK, no del modelo
El fallo exacto es `_rearrange_events_for_latest_function_response` no emparejando `function_call` con `function_response` cuando un sub-agente envuelto en AgentTool hace una tool-call.
- Fuente: https://github.com/google/adk-python/issues/4159 (primary, voto 3-0)
- Cita: *"ValueError: No function call event found for function responses ids: {'adk-xxxx-...'} occurring in the `_rearrange_events_for_latest_function_response` function"*

### 2. Es una REGRESIÓN de versión — roto en 1.22.1, funciona en 1.21.0
Apunta a la lógica de event-filtering introducida en 1.22.1, no al modelo.
- Fuente: https://github.com/google/adk-python/issues/4159 (voto 2-1)
- Cita: *"Broken in version 1.22.1; works in 1.21.0."*
- **Acción a explorar:** bajar a ADK **1.21.0** (1.21 < 1.35 actual; verificar que AgentTool va y que no choca con el "no 2.x").

### 3. `skip_summarization=True` NO arregla el problema — VÍA MUERTA (3 claims independientes)
Era la prueba #5 en curso. Confirmado que descarta el output en vez de arreglarlo:
- Devuelve **string vacío `''`** con parent + `output_key`: https://github.com/google/adk-python/issues/561 (3-0) — *"the output is `''`"*
- **El stream termina sin emitir** el output de la tool: https://github.com/google/adk-python/issues/3427 (3-0) — *"no final response being returned... The stream ends without yielding the tool's output."*
- Suprime la summarization pero el output crudo nunca se emite como evento de respuesta (3-0).

---

## REFUTADO de verdad (0-3)

- **La teoría role='tool' vs 'tool_responses' de Gemma es FALSA.** No es la causa del loop.
  - Fuente: https://github.com/google/adk-python/issues/5650 (0-3). Era hipótesis lateral (Gemma, no qwen).

---

## INCONCLUSO — no verificado por límite de sesión (≠ refutado)

Todo el **BLOQUE CLAVE de alternativas** quedó sin verificar ni sintetizar. Las 18 "abstenciones" (0-0) NO son refutaciones; los verificadores no llegaron a correr. Fuentes recogidas (21 total) pendientes de verificar:

- Provider `ollama_chat` vs `ollama` vs `openai/` → https://github.com/google/adk-python/issues/81
- Bug content-array (Ollama espera string, litellm manda array) → litellm #11273, #11433
- vLLM tool-calling (`--enable-auto-tool-choice --tool-call-parser hermes`) → https://docs.vllm.ai/en/stable/features/tool_calling/ · https://google.github.io/adk-docs/agents/models/vllm/
- Modelfile template Qwen3 (`{{ .Function }}` sin serializar) → https://github.com/ollama/ollama/issues/14601
- Repo ejemplo ADK+ollama+tool → https://github.com/jageenshukla/adk-ollama-tool
- Blog tool-calling local 2026 → https://www.jdhodges.com/blog/local-llms-on-tool-calling-2026-pt1-local-lm/
- Qwen2.5-14B fine-tune para function calling (xLAM) → https://huggingface.co/ermiaazarkhalili/Qwen2.5-14B-Instruct_Function_Calling_xLAM
- Otros issues del loop: adk #1103, #152, #1968, #3727

---

## Stats del run

6 ángulos · 21 fuentes · 84 claims extraídos · 25 verificados → **5 confirmados / 2 refutados / 18 inconclusos** · síntesis NO ejecutada.

## Para REANUDAR (cache de lo ya hecho; same-session only)

- runId: `wf_4221565c-5de`
- scriptPath: `…/560872ce-…/workflows/scripts/deep-research-wf_4221565c-5de.js`
- El límite de sesión resetea **15:30 (Europe/Madrid)**. Reanudar después completa alternativas + síntesis.
