#!/bin/bash
# qap/publish_html.sh — Sube un HTML regenerado a gh-pages
#
# Útil tras editar MDs de análisis y regenerar HTML sin tocar CX.
# Coste: 0 € (solo git operations, no API calls a Anthropic ni a CX).
#
# Uso:
#     ./qap/publish_html.sh <ruta-html> <timestamp-destino> [<logs-dir>]
#
# Si se pasa <logs-dir>, también sincroniza los JSONs de ese directorio
# a qa/<timestamp>/qa_latest_logs/ en gh-pages. Esto evita desincronización
# entre el HTML y los JSONs descargables desde el dashboard.
#
# Ejemplos:
#     ./qap/publish_html.sh /tmp/qa_regen_20260518_1929.html 20260518_192907
#     ./qap/publish_html.sh /tmp/qa_regen.html 20260527_224705 ~/petal-qa/qa_20260527_1733_logs
#
# Resultado:
#   - Clona gh-pages en /tmp/gh-pages-publish/
#   - Sustituye qa/{TIMESTAMP}/qa_latest.html con el nuevo HTML
#   - Si se pasa logs-dir, sincroniza qa/{TIMESTAMP}/qa_latest_logs/*.json
#   - Commit + push (atómico)
#   - Limpia /tmp/gh-pages-publish/

set -e

HTML_PATH="${1:-}"
TARGET_TS="${2:-}"
LOGS_DIR="${3:-}"

if [ -z "$HTML_PATH" ] || [ -z "$TARGET_TS" ]; then
  echo "Uso: $0 <html-path> <timestamp> [<logs-dir>]"
  echo "Ej:  $0 /tmp/qa_regen_20260518_1929.html 20260518_192907"
  echo "Ej:  $0 /tmp/qa_regen.html 20260527_224705 ~/petal-qa/qa_20260527_1733_logs"
  exit 1
fi

if [ ! -f "$HTML_PATH" ]; then
  echo "ERROR: $HTML_PATH no existe"
  exit 1
fi

if [ -n "$LOGS_DIR" ] && [ ! -d "$LOGS_DIR" ]; then
  echo "ERROR: $LOGS_DIR no existe"
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

# Sincronizar JSONs si se pasó logs-dir
JSONS_SYNCED=0
if [ -n "$LOGS_DIR" ]; then
  DEST_LOGS="qa/${TARGET_TS}/qa_latest_logs"
  mkdir -p "$DEST_LOGS"
  for f in "$LOGS_DIR"/TC-*.json; do
    [ -f "$f" ] && cp "$f" "$DEST_LOGS/$(basename $f)" && JSONS_SYNCED=$((JSONS_SYNCED+1))
  done
  echo "    Sincronizados $JSONS_SYNCED JSONs desde $LOGS_DIR"
fi

echo "[3/4] Commit + push..."
git -c user.email="claude@anthropic.com" -c user.name="Claude (publish_html)" add "$DEST"
if [ "$JSONS_SYNCED" -gt 0 ]; then
  git -c user.email="claude@anthropic.com" -c user.name="Claude (publish_html)" add "qa/${TARGET_TS}/qa_latest_logs/"
fi

MSG="qa(regen): actualiza HTML ${TARGET_TS}"
if [ "$JSONS_SYNCED" -gt 0 ]; then
  MSG="${MSG} + ${JSONS_SYNCED} JSONs sincronizados (atómico)"
fi

git -c user.email="claude@anthropic.com" -c user.name="Claude (publish_html)" commit -m "$MSG" 2>&1 | tail -3
git push origin gh-pages 2>&1 | tail -3

echo "[4/4] Limpieza..."
cd /tmp
rm -rf "$TMP_DIR"

echo ""
echo "✓ Publicado. URL:"
echo "  https://jeronimosanchez.github.io/cx-automation-template/qa/${TARGET_TS}/qa_latest.html"
if [ "$JSONS_SYNCED" -gt 0 ]; then
  echo "  Con ${JSONS_SYNCED} JSONs sincronizados atómicamente."
fi
echo ""
echo "Puede tardar 1-2 min en propagarse en gh-pages."
