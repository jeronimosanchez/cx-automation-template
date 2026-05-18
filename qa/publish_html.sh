#!/bin/bash
# qa/publish_html.sh — Sube un HTML regenerado a gh-pages
#
# Útil tras editar MDs de análisis y regenerar HTML sin tocar CX.
# Coste: 0 € (solo git operations, no API calls a Anthropic ni a CX).
#
# Uso:
#     ./qa/publish_html.sh <ruta-html> <timestamp-destino>
#
# Ejemplo:
#     ./qa/publish_html.sh /tmp/qa_regen_20260518_1929.html 20260518_192907
#
# Resultado:
#   - Clona gh-pages en /tmp/gh-pages-publish/
#   - Sustituye qa/{TIMESTAMP}/qa_latest.html con el nuevo
#   - Commit + push
#   - Limpia /tmp/gh-pages-publish/

set -e

HTML_PATH="${1:-}"
TARGET_TS="${2:-}"

if [ -z "$HTML_PATH" ] || [ -z "$TARGET_TS" ]; then
  echo "Uso: $0 <html-path> <timestamp>"
  echo "Ej:  $0 /tmp/qa_regen_20260518_1929.html 20260518_192907"
  exit 1
fi

if [ ! -f "$HTML_PATH" ]; then
  echo "ERROR: $HTML_PATH no existe"
  exit 1
fi

REPO_URL="https://github.com/jeronimosanchez/cx-automation-template.git"
TMP_DIR="/tmp/gh-pages-publish"

echo "[1/4] Clonando gh-pages..."
rm -rf "$TMP_DIR"
git clone --branch gh-pages --single-branch --depth 1 "$REPO_URL" "$TMP_DIR" 2>&1 | tail -2

cd "$TMP_DIR"

DEST="qa/${TARGET_TS}/qa_latest.html"
if [ ! -d "qa/${TARGET_TS}" ]; then
  echo "ERROR: qa/${TARGET_TS}/ no existe en gh-pages. Solo se puede actualizar un run que ya esté publicado."
  exit 1
fi

echo "[2/4] Copiando HTML a ${DEST}..."
cp "$HTML_PATH" "$DEST"

echo "[3/4] Commit + push..."
git -c user.email="claude@anthropic.com" -c user.name="Claude (regenerate_html)" add "$DEST"
git -c user.email="claude@anthropic.com" -c user.name="Claude (regenerate_html)" commit -m "qa(regen): actualiza HTML ${TARGET_TS} con análisis manual" 2>&1 | tail -3
git push origin gh-pages 2>&1 | tail -3

echo "[4/4] Limpieza..."
rm -rf "$TMP_DIR"

echo ""
echo "✓ Publicado. URL:"
echo "  https://jeronimosanchez.github.io/cx-automation-template/qa/${TARGET_TS}/qa_latest.html"
echo ""
echo "Puede tardar 1-2 min en propagarse en gh-pages."
