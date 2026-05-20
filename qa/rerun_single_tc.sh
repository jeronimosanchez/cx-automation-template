#!/bin/bash
# qa/rerun_single_tc.sh — Re-ejecuta UN solo TC y publica un nuevo run en gh-pages
#
# Útil para demos: aplicas un fix → ejecutas solo el TC afectado → ves el
# resultado en el histórico sin esperar al QA completo de CI.
#
# Coste: 1 llamada al agente Petal CX (~0,01€).
# Tiempo: ~30 seg.
#
# Uso:
#     ./qa/rerun_single_tc.sh <TC-ID> [<BASE_TS>]
#
# Ejemplos:
#     ./qa/rerun_single_tc.sh TC-URGENCIA-01
#     ./qa/rerun_single_tc.sh TC-URGENCIA-01 20260519_115033
#
# Si <BASE_TS> no se indica, usa el último run publicado en gh-pages.
#
# Lo que hace:
#   1. Ejecuta el TC contra el agente real → genera 1 JSON nuevo
#   2. Descarga los otros 48 JSONs del BASE_TS desde gh-pages
#   3. Combina (reemplaza el JSON del TC re-ejecutado)
#   4. Regenera HTML completo (49 TCs)
#   5. Crea nuevo timestamp en gh-pages: HTML + JSONs + meta.json + entry en index

set -e

TC_ID="${1:-}"
BASE_TS="${2:-}"

if [ -z "$TC_ID" ]; then
  echo "Uso: $0 <TC-ID> [<BASE_TS>]"
  echo "Ej:  $0 TC-URGENCIA-01"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Auto-detectar BASE_TS = último run en gh-pages
if [ -z "$BASE_TS" ]; then
  echo "→ Buscando último run en gh-pages..."
  BASE_TS=$(curl -s "https://jeronimosanchez.github.io/cx-automation-template/qa/" \
    | grep -oE "20[0-9]{6}_[0-9]{6}" | sort -u | tail -1)
  if [ -z "$BASE_TS" ]; then
    echo "ERROR: no se pudo determinar BASE_TS"
    exit 1
  fi
  echo "  BASE_TS=$BASE_TS"
fi

NEW_TS=$(date -u +%Y%m%d_%H%M%S)
TMP_LOGS="/tmp/rerun_${NEW_TS}_logs"
TMP_HTML="/tmp/rerun_${NEW_TS}.html"
TMP_GHP="/tmp/rerun_${NEW_TS}_ghpages"

echo ""
echo "[1/6] Ejecutando $TC_ID contra el agente real..."
.venv/bin/python qa/test_QA_Playbooks_v23.py --test "$TC_ID" --runs 1 > /tmp/rerun_${NEW_TS}.log 2>&1
LOCAL_TS_FILE=$(grep -oE "qa_[0-9]+_[0-9]+_logs" /tmp/rerun_${NEW_TS}.log | head -1)
if [ -z "$LOCAL_TS_FILE" ]; then
  echo "ERROR: no se generó carpeta de logs local. Ver /tmp/rerun_${NEW_TS}.log"
  exit 1
fi
LOCAL_LOGS_DIR="$HOME/petal-qa/$LOCAL_TS_FILE"
echo "  → $LOCAL_LOGS_DIR/$TC_ID.json"

# Mostrar resultado del TC re-ejecutado
RESULT=$(grep -E "^  $TC_ID" /tmp/rerun_${NEW_TS}.log | head -1)
echo "  $RESULT"

echo ""
echo "[2/6] Descargando 48 JSONs del histórico $BASE_TS..."
mkdir -p "$TMP_LOGS"
TC_IDS=$(.venv/bin/python -c "
import sys
sys.path.insert(0, 'qa')
from test_QA_Playbooks_v23 import TESTS
print('\n'.join(t['id'] for t in TESTS if t['id'] != '$TC_ID'))
" 2>/dev/null)
COUNT=0
for tc in $TC_IDS; do
  if curl -sfL "https://jeronimosanchez.github.io/cx-automation-template/qa/$BASE_TS/qa_latest_logs/$tc.json" \
       -o "$TMP_LOGS/$tc.json" 2>/dev/null; then
    COUNT=$((COUNT+1))
  fi
done
echo "  Descargados: $COUNT/48"

echo ""
echo "[3/6] Reemplazando $TC_ID con el nuevo (re-ejecutado)..."
cp "$LOCAL_LOGS_DIR/$TC_ID.json" "$TMP_LOGS/$TC_ID.json"

echo ""
echo "[4/6] Regenerando HTML..."
.venv/bin/python qa/regenerate_html.py --logs-dir "$TMP_LOGS" --out "$TMP_HTML" 2>&1 | grep -E "Cargados|Generando|OK" | head -3

# Extraer stats del HTML generado (mismo formato que regenerate_html imprime)
STATS=$(.venv/bin/python qa/regenerate_html.py --logs-dir "$TMP_LOGS" --out "$TMP_HTML" 2>&1 | grep -oE "Cargados: [0-9]+ TCs \([0-9]+ PASS, [0-9]+ INESTABLE, [0-9]+ FAIL\)" | head -1)
TOTAL=$(echo "$STATS" | grep -oE "Cargados: [0-9]+" | grep -oE "[0-9]+")
PASS_N=$(echo "$STATS" | grep -oE "[0-9]+ PASS" | grep -oE "[0-9]+")
INST_N=$(echo "$STATS" | grep -oE "[0-9]+ INESTABLE" | grep -oE "[0-9]+")
FAIL_N=$(echo "$STATS" | grep -oE "[0-9]+ FAIL" | grep -oE "[0-9]+")
PCT=$(( PASS_N * 100 / TOTAL ))

echo ""
echo "[5/6] Publicando a gh-pages como nuevo run $NEW_TS..."
SHORT_SHA=$(git rev-parse --short=7 main 2>/dev/null || git rev-parse --short=7 HEAD)
TS_DISPLAY="${NEW_TS:0:4}-${NEW_TS:4:2}-${NEW_TS:6:2} ${NEW_TS:9:2}:${NEW_TS:11:2}"

git clone --branch gh-pages --single-branch --depth 1 \
  https://github.com/jeronimosanchez/cx-automation-template.git "$TMP_GHP" 2>&1 | tail -1

mkdir -p "$TMP_GHP/qa/$NEW_TS/qa_latest_logs"
cp "$TMP_HTML" "$TMP_GHP/qa/$NEW_TS/qa_latest.html"
cp "$TMP_LOGS"/*.json "$TMP_GHP/qa/$NEW_TS/qa_latest_logs/"

# Generar qa_latest.meta.json (necesario para que aparezca en el modal Histórico)
cat > "$TMP_GHP/qa/$NEW_TS/qa_latest.meta.json" <<EOF
{
  "timestamp": "$TS_DISPLAY",
  "ts_file": "$NEW_TS",
  "total": $TOTAL,
  "pass": $PASS_N,
  "inst": $INST_N,
  "fail": $FAIL_N,
  "pct": $PCT,
  "runs_per_tc": 1,
  "rerun_single_tc": "$TC_ID",
  "base_ts": "$BASE_TS"
}
EOF

# Insertar entry en index.html (antes de la primera fila de timestamp existente)
NEW_ROW="<tr><td>${NEW_TS}</td><td><code>${SHORT_SHA}</code></td><td>Total: ${TOTAL} | PASS: ${PASS_N} | INESTABLE: ${INST_N} | FAIL: ${FAIL_N}</td><td><a href=\"${NEW_TS}/qa_latest.html\">Ver</a></td></tr>"
export NEW_ROW
python3 - "$TMP_GHP/qa/index.html" <<'PYEOF'
import os, re, sys
path = sys.argv[1]
new_row = os.environ["NEW_ROW"]
with open(path, encoding="utf-8") as f:
    content = f.read()
pattern = r"(<tr><td>20\d{6}_\d{6}</td>)"
new_content = re.sub(pattern, new_row + "\n" + r"\1", content, count=1)
if new_content == content:
    new_content = content.replace("</tbody>", new_row + "\n</tbody>", 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)
PYEOF

cd "$TMP_GHP"
git -c user.email="claude@anthropic.com" -c user.name="Claude (rerun)" add -A
git -c user.email="claude@anthropic.com" -c user.name="Claude (rerun)" \
  commit -m "qa(rerun): $TC_ID re-ejecutado como nuevo run $NEW_TS" 2>&1 | tail -1
git push origin gh-pages 2>&1 | tail -1

cd "$REPO_ROOT"
rm -rf "$TMP_GHP"

echo ""
echo "[6/6] ✓ Listo"
echo ""
echo "  Total: $TOTAL | PASS: $PASS_N | INESTABLE: $INST_N | FAIL: $FAIL_N | Tasa: ${PCT}%"
echo ""
echo "  HTML:      https://jeronimosanchez.github.io/cx-automation-template/qa/$NEW_TS/qa_latest.html"
echo "  Histórico: https://jeronimosanchez.github.io/cx-automation-template/qa/"
echo ""
echo "  Puede tardar 1-2 min en propagarse en gh-pages."
