#!/bin/bash
# qa/regenerate_all_html.sh — Regenera TODOS los HTMLs en gh-pages con los MDs actuales.
#
# Usar tras añadir/editar `qa/tc_analysis/*.md` para que los HTMLs históricos no muestren
# "Pendiente análisis" cuando ya existe el MD. Los resultados QA de cada run (pass/fail)
# son inmutables; lo que se actualiza es la parte de análisis enriquecido.
#
# Optimización: clona gh-pages una vez, lee logs LOCALES (no curl por TC) → ~5-10x más
# rápido que llamar a regenerate_html.py con --ts por cada run.
#
# Tras regenerar todos los HTMLs, también reconstruye qa/history.json y publica todo en
# un único commit a gh-pages.
#
# Uso:
#     ./qa/regenerate_all_html.sh           # regenera TODOS los runs
#     ./qa/regenerate_all_html.sh --last 5  # solo los 5 más recientes (más rápido)

set -e

LAST_N=""
if [ "$1" = "--last" ] && [ -n "$2" ]; then
  LAST_N="$2"
fi

REPO_URL="https://github.com/jeronimosanchez/cx-automation-template.git"
TMP_DIR="/tmp/gh-pages-regenall"
REPO_LOCAL=$(git rev-parse --show-toplevel)

echo "[1/5] Clonando gh-pages..."
rm -rf "$TMP_DIR"
git clone --branch gh-pages --single-branch --depth 1 "$REPO_URL" "$TMP_DIR" 2>&1 | tail -2

if [ -n "$LAST_N" ]; then
  DIRS=$(ls "$TMP_DIR/qa" | grep -E "^[0-9]{8}_[0-9]{6}$" | sort -r | head -n "$LAST_N")
else
  DIRS=$(ls "$TMP_DIR/qa" | grep -E "^[0-9]{8}_[0-9]{6}$" | sort)
fi
TOTAL=$(echo "$DIRS" | wc -l | tr -d ' ')
echo "[2/5] Encontrados $TOTAL directorios a regenerar"

cd "$REPO_LOCAL"
source .venv/bin/activate 2>/dev/null || true

REGEN_OK=0
REGEN_FAIL=0
for TS in $DIRS; do
  # Preferir logs timestamped (no qa_latest_logs) — extrae el TS bien para display
  LOGS_DIR=$(find "$TMP_DIR/qa/$TS" -maxdepth 1 -type d -name "qa_*_logs" -not -name "qa_latest_logs" 2>/dev/null | head -1)
  if [ -z "$LOGS_DIR" ] || [ ! -d "$LOGS_DIR" ]; then
    LOGS_DIR="$TMP_DIR/qa/$TS/qa_latest_logs"
  fi
  if [ ! -d "$LOGS_DIR" ]; then
    REGEN_FAIL=$((REGEN_FAIL + 1))
    echo "  ⚠️ $TS — sin logs"
    continue
  fi
  TMP_HTML="/tmp/regen_${TS}.html"
  if python qa/regenerate_html.py --logs-dir "$LOGS_DIR" --out "$TMP_HTML" >/dev/null 2>&1; then
    cp "$TMP_HTML" "$TMP_DIR/qa/$TS/qa_latest.html"
    REGEN_OK=$((REGEN_OK + 1))
    rm -f "$TMP_HTML"
  else
    REGEN_FAIL=$((REGEN_FAIL + 1))
    echo "  ⚠️ $TS — fallo al regenerar"
  fi
done

echo "[3/5] Regenerados $REGEN_OK / fallaron $REGEN_FAIL"

echo "[4/5] Reconstruyendo history.json..."
python3 qa/rebuild_history.py --out "$TMP_DIR/qa/history.json" 2>&1 | tail -2

cd "$TMP_DIR"
git -c user.email="claude@anthropic.com" -c user.name="Claude (regenerate_all)" add -A
if git diff --staged --quiet; then
  echo "[5/5] No hay cambios para publicar"
else
  git -c user.email="claude@anthropic.com" -c user.name="Claude (regenerate_all)" commit -m "qa: regenera HTMLs con análisis actuales ($REGEN_OK runs)" 2>&1 | tail -3
  git push origin gh-pages 2>&1 | tail -3
fi

cd "$REPO_LOCAL"
rm -rf "$TMP_DIR"
echo ""
echo "✓ Listo. $REGEN_OK HTMLs regenerados + history.json actualizado."
