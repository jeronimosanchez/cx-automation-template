---
name: qa-analyze
description: Analiza FAILs del QA y publica el análisis enriquecido en el HTML de gh-pages. Soporta análisis individual (un TC) o batch (todos los FAILs sin análisis de un run). Genera MDs con formato rico (Turnos vs Problemas + 7 soluciones con score 🟢🟡🔴 + plan de acción), regenera HTML sin llamar a CX y publica en gh-pages. Coste 0€. Uso típico: "/qa-analyze TC-XYZ" o "analiza todos los fails" tras un QA run.
---

# qa-analyze — Análisis profundo de TC(s) del QA

## Cuándo invocar esta skill

Cuando el usuario pida analizar uno o varios TCs del QA:

| Frase del usuario | Modo |
|---|---|
| `/qa-analyze TC-DECO-02` | **Individual**: un TC específico |
| `analiza TC-DECO-02` | **Individual** |
| `analiza y recomienda TC-XYZ` | **Individual** |
| `/qa-analyze --all` | **Batch**: todos los FAILs sin `.md` del último run |
| `analiza todos los fails` | **Batch** |
| `analiza todos los fails de 20260518_192907` | **Batch** sobre run histórico |
| `analiza el último run` | **Batch** sobre el último run |

## Argumentos

- `TC-ID` (opcional): identificador del TC a analizar
- `--all` (modo batch implícito): analizar todos los FAILs pendientes
- `--ts TIMESTAMP` (opcional): apuntar a un run histórico específico (default: el último de gh-pages)

## Pre-requisitos (verifica antes de empezar)

1. Estar en el worktree con la rama `main` actualizada:
   ```bash
   cd ~/cx-automation-template/.claude/worktrees/<worktree-actual>
   git fetch origin main
   git checkout -B qa/analyze-batch-<timestamp> origin/main
   ```

2. Tener venv activado: `source ../../../.venv/bin/activate`

## Flujo

### Paso 0 — Determinar modo y TS

**Detectar modo:**
- Si el usuario nombra un TC concreto → modo INDIVIDUAL
- Si dice "todos", "all", o no especifica TC → modo BATCH

**Determinar TS:**
- Si el usuario nombra TS explícito (`20260518_192907`) → úsalo
- Si no → el último de gh-pages: `curl -s https://jeronimosanchez.github.io/cx-automation-template/qa/ | grep -oE "20[0-9]{6}_[0-9]+" | sort -r | head -1`

### Paso 1 — Identificar TCs a analizar

**Modo INDIVIDUAL**: la lista es `[TC-ID]`.

**Modo BATCH**: ejecuta `qa/list_fails.py` para obtener los FAILs pendientes:
```bash
python qa/list_fails.py --ts $TS --only-pending --format ids
# Devuelve IDs separados por espacios: TC-XXX TC-YYY TC-ZZZ
```

Reporta al usuario qué TCs vas a analizar:
```
Voy a analizar N TCs:
- TC-XXX (descripción corta)
- TC-YYY (descripción corta)
```

Si modo BATCH y no hay FAILs pendientes, infórmalo y termina.

### Paso 2 — Obtener el JSON del TC (local primero, gh-pages fallback) [v1.1 Cambio 2]

**Estrategia v1.1:** local primero por velocidad y fiabilidad, gh-pages como fallback.

Para cada TC:

```bash
# 1. Intentar local (instantáneo, offline-safe, sin depender de propagación gh-pages)
LOCAL=$(ls -t ~/petal-qa/qa_*_logs/<TC-ID>.json 2>/dev/null | head -1)

# 2. Si existe → leer con Read tool directamente
if [ -n "$LOCAL" ]; then
  # usa $LOCAL como ruta de entrada
  cp "$LOCAL" /tmp/<TC-ID>.json   # o léelo directo con la tool Read
fi

# 3. Si no existe local → fallback a gh-pages
if [ -z "$LOCAL" ]; then
  curl -sf "https://jeronimosanchez.github.io/cx-automation-template/qa/$TS/qa_latest_logs/<TC-ID>.json" \
       -o /tmp/<TC-ID>.json
fi
```

**Para batch:** ejecutar los chequeos en paralelo con `&` + `wait`.

**Razón:** las suites completas de QA Petal se ejecutan en GitHub Actions y NO dejan JSONs locales — solo en gh-pages. Los `rerun_single_tc.sh` se ejecutan en local y dejan JSONs en `~/petal-qa/`. Esta estrategia funciona para ambos casos sin que el usuario haga nada distinto.

**Tiempos esperados:**
- Lectura local: ~0.002 segundos
- Fallback gh-pages: ~2-3 segundos (igual que antes)

Si el usuario proporciona los JSONs directamente (pegados o adjuntos), saltarse este paso.

### Paso 3 — Analizar y escribir MDs

**Si hay 1 TC:** analizar inline y escribir el MD directamente.

**Si hay ≥2 TCs:** lanzar un sub-agente por TC en paralelo usando la herramienta Agent. Cada sub-agente recibe:
- El JSON completo del TC (embebido en el prompt)
- El formato exacto del MD (la plantilla completa de esta skill)
- La ruta donde escribir: `qa/tc_analysis/{TC-ID}.md` en `~/cx-automation-template`
- Instrucción: "Genera el análisis, escribe el archivo y confirma. Nada más."

Esperar a que todos los sub-agentes terminen antes de continuar.

**Mostrar el análisis en pantalla** (resumen de cada TC: diagnóstico + solución recomendada) para que el usuario lo vea. Continuar automáticamente al Paso 4 sin esperar confirmación.

### Paso 3b — Escribir el MD con formato rico

Crea `qa/tc_analysis/{TC-ID}.md` con esta estructura EXACTA:

```markdown
---
status: FAIL
tipo: <Bug Playbook | Bug Catálogo | Test mal calibrado | Falso negativo | Flakiness | Bug Tool | Bug Orquestador>
estimacion: ~<X> min (Solución #<N> recomendada)
---

## T<N>

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"<texto user>"* | — |
| 2 | Orquestador | <acción> | ✅ Correcto / ⚠️ Observación / 🔴 Problema |
| 3 | Compra | <acción/slots extraídos> | <problema> |
| ... | ... | ... | ... |

### Causa raíz (descompuesta en <N> capas)

1. **<Capa 1>**: <descripción concreta>
2. **<Capa 2>**: <descripción concreta>
3. **<Capa 3>**: <descripción concreta>

## Recomendación

### Solución recomendada: #<N> — <título>

🟢 **<score>/10** · ~<tiempo> · <dependencias o "Sin dependencias externas">

**Por qué**: <razonamiento conciso>

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| <N> | **<solución>** | 🟢 <X>/10 | <dep o "—"> | <razonamiento> |
| <N> | **<solución>** | 🟡 <X>/10 | <dep> | <razonamiento> |
| <N> | **<solución>** | 🔴 <X>/10 | <dep> | <razonamiento> |
| ... (7 soluciones, DESC por score) |

### Plan de acción (Solución #<N>)

1. **<acción 1>**: <archivo o playbook a editar, qué cambiar>
2. **<acción 2>**: <archivo>
3. **Re-ejecutar QA** con `--runs 3`

**Coste total**: ~<tiempo> (desglose).

### Parámetros / slots requeridos entre playbooks

> Incluir esta sección solo si el TC involucra transferencia de slots entre playbooks (Compra→Checkout, Compra→Orquestador, etc.).

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$<slot>` | <Playbook> | <Playbook> | Sí / No / Condicional | <contexto o "—"> |
```

**Reglas clave:**
- SIEMPRE 7 soluciones (rango score 1-10)
- Ordena DESC por score
- Usa emojis 🟢 (8-10), 🟡 (5-7), 🔴 (1-4)
- "Dependencias" concreto o `—` (NO escribas "Sí, ya")
- Sé honesto sobre trade-offs en "Por qué este scoring"
- En el TIPO usa una de las categorías listadas, no inventes nuevas

### Paso 4 — Regenerar TODOS los HTMLs y publicar — AUTOMÁTICO

Tras escribir los MDs, ejecutar:

```bash
./qa/regenerate_all_html.sh
```

Este script clona gh-pages, regenera **todos** los HTMLs históricos con los MDs actuales (para que cualquier run viejo que tenga ese TC en FAIL muestre el análisis), reconstruye `history.json` y hace push en un solo commit.

Antes había `regenerate_html.py --ts X` + `publish_html.sh X` para un único run, pero eso dejaba los HTMLs viejos inconsistentes (mostraban "Pendiente análisis" para TCs que ya tenían MD). El nuevo script lo arregla.

### Paso 4b — (legado) Regenerar UN solo HTML

Después de escribir TODOS los MDs:

```bash
python qa/regenerate_html.py --ts $TS --out /tmp/qa_regen_$TS.html
```

Esto carga TODOS los MDs nuevos en el HTML.

### Paso 5 — Publicar en gh-pages

```bash
./qa/publish_html.sh /tmp/qa_regen_$TS.html $TS
```

### Paso 6 — Commit del MD(s) a main

```bash
git add qa/tc_analysis/TC-XXX.md  # (todos los MDs nuevos)
git commit -m "qa(analysis): <N> análisis estructurados del run $TS"
git push -u origin qa/analyze-batch-<timestamp>
gh pr create --title "qa(analysis): <N> análisis del run $TS" \
  --body "Análisis manual de los siguientes FAILs:\n- TC-XXX (...)\n- TC-YYY (...)\n..."
gh pr merge --admin --squash
```

### Paso 7 — Reportar al usuario

Mensaje final adaptado al modo:

**Modo INDIVIDUAL:**
```
✅ Análisis de TC-XYZ publicado.

📊 Diagnóstico: <1 línea>
🎯 Solución recomendada: #<N> — <título corto>
   Score <X>/10 · ~<tiempo> · <deps>

🌐 Ver en dashboard:
   https://jeronimosanchez.github.io/cx-automation-template/qa/$TS/qa_latest.html
```

**Modo BATCH:**
```
✅ <N> análisis publicados.

| TC | Tipo | Solución recomendada | Score | Tiempo |
|---|---|---|---|---|
| TC-XXX | <tipo> | #<N> <título> | <X>/10 | ~<X> min |
| TC-YYY | <tipo> | #<N> <título> | <X>/10 | ~<X> min |

🌐 Ver dashboard actualizado:
   https://jeronimosanchez.github.io/cx-automation-template/qa/$TS/qa_latest.html
```

## Coste

- API CX: **0 €** (no se ejecuta QA)
- API Anthropic: **0 €** (uso tokens de conversación)
- Tiempo: **~3 min por TC** + 30 seg regenerate/publish

## Reglas importantes

- **NO ejecutes QA** salvo que el usuario lo pida explícitamente
- Si un MD ya existe, pregunta al usuario si quiere sobreescribir antes de hacerlo
- **NO pidas confirmación** entre análisis y guardar/publicar: mostrar análisis en pantalla + proceder automáticamente al Paso 4-6
- **Para ≥2 TCs: siempre lanzar sub-agentes en paralelo** — no analizar secuencialmente
- Para modo BATCH, si hay >5 FAILs, pregunta confirmación antes de empezar (puede ser largo)
- Si encuentras información en el JSON que requiere trace adicional (interno de CX), menciónalo como **limitación** en la causa raíz
- Usa SIEMPRE el último TS de gh-pages a menos que el usuario diga otro
- Después de publicar, recuerda al usuario: "El HTML puede tardar 1-2 min en propagarse en gh-pages"

## Ejemplos de uso real

**Ejemplo 1 — Individual:**
```
Usuario: /qa-analyze TC-FRUSTRACION-01
Claude:
  1. Detecta TS=20260518_192907 (último)
  2. Descarga TC-FRUSTRACION-01.json
  3. Escribe qa/tc_analysis/TC-FRUSTRACION-01.md
  4. python qa/regenerate_html.py --ts 20260518_192907
  5. ./qa/publish_html.sh /tmp/qa_regen_*.html 20260518_192907
  6. Commit + PR + merge
  7. Reporta URL
Total: ~3 min, 0€
```

**Ejemplo 2 — Batch:**
```
Usuario: analiza todos los fails
Claude:
  1. python qa/list_fails.py --only-pending → ["TC-A", "TC-B", "TC-C"]
  2. Confirma: "Voy a analizar 3 TCs. ¿Continúo?"
  3. Para cada TC: descarga JSON, escribe MD
  4. regenerate_html UNA vez al final
  5. publish_html UNA vez al final
  6. Commit + PR con los 3 MDs
  7. Reporta tabla resumen
Total: ~10 min, 0€
```
