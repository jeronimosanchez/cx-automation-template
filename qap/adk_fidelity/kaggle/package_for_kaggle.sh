#!/usr/bin/env bash
# Empaqueta el MÍNIMO necesario para correr el harness de fidelidad en Kaggle.
# Preserva la estructura del repo (definitions/ + qap/) para que el ROOT que
# run_fidelity.py calcula con __file__ resuelva igual que en local.
#
# Salida: qap/adk_fidelity/kaggle/build/petal-fidelity.zip  → subir como Kaggle Dataset.
# Coste: €0. No incluye secretos (el path Ollama no usa GEMINI key; va un .env dummy).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # ruta ABSOLUTA al dir del script
cd "$SCRIPT_DIR/../../.."                      # raíz del repo
OUT="qap/adk_fidelity/kaggle/build/petal-fidelity"
rm -rf "$OUT"; mkdir -p "$OUT"

# --- definiciones (playbooks + examples) ---
mkdir -p "$OUT/definitions"
cp -R definitions/playbooks "$OUT/definitions/playbooks"
cp -R definitions/examples  "$OUT/definitions/examples"

# --- harness ---
mkdir -p "$OUT/qap/adk_fidelity"
cp qap/test_qa_playbooks.py "$OUT/qap/test_qa_playbooks.py"
cp qap/adk_fidelity/petal_agent.py        "$OUT/qap/adk_fidelity/"
cp qap/adk_fidelity/petal_agent_multi.py  "$OUT/qap/adk_fidelity/"
cp qap/adk_fidelity/static_leak_gate.py          "$OUT/qap/adk_fidelity/"   # pre-gate anti-fuga (run_fidelity lo importa)
cp qap/adk_fidelity/run_fidelity.py       "$OUT/qap/adk_fidelity/"
cp qap/adk_fidelity/smoke_test.py         "$OUT/qap/adk_fidelity/" 2>/dev/null || true

# --- .env dummy (run_fidelity.py:17 abre .env; Ollama NO usa la key) ---
echo "GEMINI_API_KEY=unused-on-kaggle" > "$OUT/.env"

# --- zip ---
cd "$SCRIPT_DIR/build"
rm -f petal-fidelity.zip
zip -qr petal-fidelity.zip petal-fidelity
echo "✅ Bundle listo: qap/adk_fidelity/kaggle/build/petal-fidelity.zip"
echo "   $(find petal-fidelity -name '*.yaml' | wc -l | tr -d ' ') yaml + harness, $(du -sh petal-fidelity.zip | cut -f1)"
echo "   → Súbelo a Kaggle como Dataset (New Dataset → upload zip)."
