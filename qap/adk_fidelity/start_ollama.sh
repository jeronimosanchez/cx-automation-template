#!/usr/bin/env bash
# Config del cribador ADK local — arranca Ollama con la config de MEDICIÓN validada.
# Config-as-code: esto es la fuente de verdad de cómo debe correr el simulador.
# NO ejecutar mientras hay un run en curso (reinicia Ollama y lo mataría).
#
# Perfil: Qwen2.5-14B-q4 @ M4 Air 24GB. Ver kb_plat_adk (ADK-22/23/24 + perfil).
set -e

# --- Config de medición (los confounds que hay que fijar) ---
export OLLAMA_FLASH_ATTENTION=1       # ADK: acelera el prefill, output idéntico (sin pérdida de fidelidad)
export OLLAMA_NUM_PARALLEL=1          # P0 12-jun (config limpia): 1 slot = contexto entero, sin trocear → +60 tok/s vs auto=4
export OLLAMA_CONTEXT_LENGTH=24576    # P0 12-jun right-size: prompt real max ~22k → 24k cabe + libera ~2GB → caché de 3 prefijos. Preflight guarda overflow. (era 32k: ADK-22)
export OLLAMA_KEEP_ALIVE=-1           # modelo NO se descarga entre TCs/iteraciones → la KV-cache del prefijo persiste (ADK-24)
export OLLAMA_HOST=127.0.0.1:11434
# NOTA: temp=0 + seed=42 NO van aquí — van en petal_agent.py (LiteLlm), por petición.
# NOTA: OLLAMA_KV_CACHE_TYPE se deja sin setear (fp16) — q8 degrada recall en contexto largo (regla "0 calidad").

# --- Persistir para la app de Ollama (sesión GUI) ---
launchctl setenv OLLAMA_FLASH_ATTENTION 1
launchctl setenv OLLAMA_NUM_PARALLEL 1
launchctl setenv OLLAMA_CONTEXT_LENGTH 24576
launchctl setenv OLLAMA_KEEP_ALIVE -1

# --- Arrancar limpio ---
osascript -e 'tell application "Ollama" to quit' 2>/dev/null || true
pkill -f "ollama serve" 2>/dev/null || true
sleep 1
nohup ollama serve > /tmp/ollama_adk.log 2>&1 &

echo "Ollama arrancado: flash ON + num_parallel=1 + contexto 24k (right-sized) + keep_alive (log: /tmp/ollama_adk.log)"
echo "Verifica: grep -oE 'OLLAMA_FLASH_ATTENTION:[a-z]+|OLLAMA_CONTEXT_LENGTH:[0-9]+' /tmp/ollama_adk.log"
echo "Modelo del cribador: qwen2.5:14b (ollama_chat) — ver petal_agent.py ADK_MODEL"
