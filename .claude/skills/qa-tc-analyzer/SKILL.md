---
name: qa-tc-analyzer
version: 1.2
description: Analiza FAILs del QA con 9 capas de causa raíz. Arquitectura de dos fases — sub-agentes TC en paralelo (fase 1) + sub-agente de patrones con contexto limpio (fase 2). Checkpoint en git entre fases. Sin confirmaciones. Escalable a 50+ TCs + base de conocimiento. Coste 0€. Uso: '/qa-tc-analyzer TC-XYZ' o 'analiza todos los fails'.
---

# qa-tc-analyzer — Análisis profundo de TC(s) del QA

## Cuándo invocar esta skill

Cuando el usuario pida analizar uno o varios TCs del QA:

| Frase del usuario | Modo |
|---|---|
| `/qa-tc-analyzer TC-DECO-02` | **Individual**: un TC específico |
| `analiza TC-DECO-02` | **Individual** |
| `analiza y recomienda TC-XYZ` | **Individual** |
| `/qa-tc-analyzer --all` | **Batch**: todos los FAILs sin `.md` del último run |
| `analiza todos los fails` | **Batch** |
| `analiza todos los fails de 20260518_192907` | **Batch** sobre run histórico |
| `analiza el último run` | **Batch** sobre el último run |

## Argumentos

- `TC-ID` (opcional): identificador del TC a analizar
- `--all` (modo batch implícito): analizar todos los FAILs pendientes
- `--ts TIMESTAMP` (opcional): apuntar a un run histórico específico (default: el último de gh-pages)
- `--keep-existing` (opcional, default: false): si se activa, mantiene los MDs de análisis previos sin sobreescribir. Útil para preservar análisis hechos manualmente

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

**Modo BATCH**: ejecuta `qap/list_fails.py` para obtener los FAILs pendientes:
```bash
python qap/list_fails.py --ts $TS --only-pending --format ids
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

### Paso 2.5 — Auditoría del Sheet (variables de negocio) [v1.1 Paso nuevo]

El skill consulta el Sheet para obtener los valores reales de las variables de negocio y auditar su coherencia. Evita que el skill invente valores de horarios, precios, zonas o políticas.

**1. Cargar variables del Sheet (con timeout y verificación defensiva):**
```bash
curl -s --max-time 30 "https://petal-sheet-api-920225907399.europe-west1.run.app/exec?recurso=business" -o /tmp/sheet_business.json
curl -s --max-time 30 "https://petal-sheet-api-920225907399.europe-west1.run.app/exec?recurso=agent_copy" -o /tmp/sheet_agent_copy.json

# Verificación defensiva — exigir que ambos archivos sean objetos JSON
SHEET_OK=true
for f in /tmp/sheet_business.json /tmp/sheet_agent_copy.json; do
  if [ ! -s "$f" ] || ! jq -e 'type == "object"' "$f" > /dev/null 2>&1; then
    echo "SHEET_FAIL: $f no es un objeto JSON válido"
    SHEET_OK=false
  fi
done
```

**2. Auditar coherencia del Sheet** (solo si SHEET_OK=true):
Para cada variable relevante al TC, comprobar:
- **Duplicados con valores distintos**: misma key en `business` y `agent_copy` con valores diferentes
- **Valores lógicamente imposibles**: ej. `horario_corte_mismo_dia` posterior al cierre de `horario_apertura`
- **Valores ausentes**: keys esperadas que no existen (ej. `envio_barcelona_metro`)
- **Formato inconsistente**: misma información en formatos distintos (ej. "14:00" vs "2pm")

**3. Reportar:**
Los hallazgos de coherencia del Sheet se reportan en la **Capa Datos** del análisis (capa 5 del nuevo esquema de 9 capas). Si la coherencia falla, esa capa puede ser 🔴 incluso si el playbook está correcto.

**Red de seguridad — Sheet no disponible o JSON inválido (SHEET_OK=false):**
- Continuar el análisis sin bloquear
- Marcar como 🟡 cualquier afirmación que dependa de datos del Sheet (con [supuesta] explícita en el MD)
- Añadir recomendación al final del análisis: *"Re-ejecutar el análisis cuando el Sheet esté disponible para verificar las afirmaciones marcadas como supuesta por falta de acceso a datos de configuración"*

### Paso 2.6 — Cargar fuentes contextuales adicionales [v1.1 Cambio 1]

Antes de analizar el TC, el skill carga fuentes contextuales que enriquecen el análisis y reducen alucinaciones.

**1. Historial del playbook (siempre):**
```bash
git log --oneline -n 20 -- definitions/playbooks/<archivo>.yaml
```
- Sin límite de tiempo. Últimos 20 commits sobre el playbook que toca ese TC.
- **Red de seguridad:** si el análisis apunta a una regresión pero los 20 commits no muestran nada relevante, marcar Capa Histórico como 🟡 con nota: *"no se encontró cambio relevante en los últimos 20 commits — revisar manualmente si el problema es anterior"*. No ampliar la búsqueda automáticamente.

**2. Memoria del proyecto (siempre, path relativo al repo):**
- Leer `memory/MEMORY.md` (path relativo desde la raíz del proyecto) como índice
- Decidir qué archivos abrir según el TC concreto:
  - TC de compra → `memory/petal/pendiente_refactor_compra.md` + `memory/current/estado_actual.md`
  - TC de proceso/QA → archivos relevantes en `memory/automatizacion/`
  - Siempre revisar `memory/current/` para conocer estado activo
- **Red de seguridad A — prioridad de fuentes:** si la memoria contradice el playbook actual, el playbook gana siempre. Si hay contradicción, marcarla explícitamente en el análisis.
- **Red de seguridad B — memoria sin resultado:** si tras leer memoria no encuentra nada relevante para ese TC, no forzar conexiones ni inventar relevancia. Continuar sin citar memoria.

**3. Verificación de PRs (condicional):**
Solo si el análisis va a citar un PR específico:
```bash
gh pr view <N>
```
**Nunca** citar un PR sin haberlo verificado primero con esta llamada.

**4. Logs del backend (condicional):**
Solo si el agente respondió con error de tool call ("Lo siento, algo no ha funcionado" o similar):
```bash
gcloud logging read 'resource.labels.service_name="petal-sheet-api" AND severity>=ERROR' --freshness=1h --limit=20
```
Para identificar parámetros vacíos, status codes y causa exacta del fallo del backend.

### Paso 3 — Analizar y escribir MDs

**Si hay 1 TC:** analizar inline y escribir el MD directamente. Si el MD ya existe, sobreescribirlo (salvo `--keep-existing`).

**Si hay ≥2 TCs:** lanzar un sub-agente por TC en PARALELO usando la herramienta Agent. Cada sub-agente recibe:
- El JSON completo del TC (embebido en el prompt)
- El formato exacto del MD (la plantilla completa de esta skill — sección Paso 3b)
- La ruta exacta donde escribir: `qap/tc_analysis/{TS}/{TC-ID}.md` en `~/cx-automation-template` (**run-scoped** — subcarpeta con el timestamp compacto del run, ej: `qap/tc_analysis/20260525_1254/TC-URGENCIA-01.md`)
- Instrucción de retorno explícita: **"Genera el análisis y escríbelo en la ruta indicada. Cuando termines, devuelve SOLO esta línea: `{TC-ID}: OK — {tipo} · fix ~{X}min`. NO incluyas el contenido del MD en tu respuesta."**

Esperar a que TODOS los sub-agentes devuelvan su línea de confirmación. El tool calling garantiza la sincronización — el agente principal no puede continuar hasta que todos respondan.

Tras recibir todas las confirmaciones, proceder inmediatamente al Paso 3-checkpoint sin mostrar análisis completos al usuario (los MDs ya están en disco).

### Paso 3-checkpoint — Commit de MDs como punto de recuperación

Ejecutar inmediatamente después de que todos los sub-agentes hayan confirmado, antes de cualquier otro paso.

```bash
cd ~/cx-automation-template
git add qap/tc_analysis/{TS}/
git commit -m "qa(analysis): checkpoint — {N} MDs del run {TS}"
git push -u origin qa/analyze-batch-{TS}
```

**Por qué es crítico:** si la sesión muere después de este commit, los MDs están seguros en git. Una sesión nueva puede retomar el flujo directamente desde el análisis de patrones sin repetir el trabajo ya hecho.

Tras el commit, proceder al Paso 3c (sub-agente de patrones).

---

### Paso 3b — Escribir el MD con formato rico

Crea `qap/tc_analysis/{TC-ID}.md` con esta estructura EXACTA:

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

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴/🟢/🟡/⚪ 1. **Capa Comportamiento** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: Playbooks + Examples + Generators (cómo guía la respuesta del agente). Verificar instrucciones del playbook, examples relevantes al turno, configuración de generadores LLM.

🔴/🟢/🟡/⚪ 2. **Capa Routing** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: Flows + Pages + Intents + Entity Types (cómo se enruta la conversación). En Petal suele ser ⚪ N/A porque usa Playbooks, no Flows.

🔴/🟢/🟡/⚪ 3. **Capa Parámetros / Slots** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: slots de entrada/salida entre playbooks y entre playbook y tools. Verificar que los parámetros pasan correctamente entre componentes.

🔴/🟢/🟡/⚪ 4. **Capa Integración** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: Tools + Webhooks + llamadas API al backend (PetalDataTool). Verificar tool calls, parámetros enviados, respuestas del backend.

🔴/🟢/🟡/⚪ 5. **Capa Datos** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: Sheet (`business` + `agent_copy` + `inventario` + `perfil` + `pedidos`) + coherencia entre recursos. Aquí se reportan los hallazgos del Paso 2.5 (auditoría del Sheet).

🔴/🟢/🟡/⚪ 6. **Capa Infraestructura** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: Environments + Versions + Agent Config. Verificar que el deploy es correcto, que la versión activa es la esperada, que la configuración del agente no introduce regresiones.

🔴/🟢/🟡/⚪ 7. **Capa Modelo / LLM** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: comportamiento de Gemini — alucinaciones, decisiones no deterministas. **Regla binaria de marcado 🔴:** se marca 🔴 [verificada] **solo si** las 8 capas restantes son todas 🟢 [verificada] **Y** el bug es reproducible en al menos 2 ejecuciones del mismo TC. En cualquier otro caso, 🟡 [supuesta]. Cuando se marque 🔴, incluir justificación explícita: *"Marcado 🔴 tras descartar las 8 capas restantes (todas 🟢) y confirmar reproducibilidad en N ejecuciones"*.

🔴/🟢/🟡/⚪ 8. **Capa Histórico** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: regresiones — git log del playbook involucrado (cargado en Paso 2.6).

🔴/🟢/🟡/⚪ 9. **Capa Test** [verificada/supuesta/N/A] · `<fuente o motivo>`

Cubre: calidad del propio test — regex mal calibrado, caso mal definido, expectativa incorrecta.

**Resumen visual:** <N> 🔴 problema · <N> 🟢 ok · <N> 🟡 supuesta · <N> ⚪ N/A

> **Importante:** para las capas marcadas ⚪ N/A, omitir el párrafo descripción y poner todo en una línea: `⚪ N. **Capa Nombre** · N/A — razón breve.`

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
| ... (3, 5 o 7 soluciones según dimensionamiento, DESC por score) |

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
- **3, 5 o 7 soluciones según dimensionamiento del bug (ver Cambio 4 abajo)** — rango score 1-10
- Ordena DESC por score
- Usa emojis 🟢 (8-10), 🟡 (5-7), 🔴 (1-4)
- "Dependencias" concreto o `—` (NO escribas "Sí, ya")
- Sé honesto sobre trade-offs en "Por qué este scoring"
- En el TIPO usa una de las categorías listadas, no inventes nuevas
- FORMATO VERTICAL JERÁRQUICO obligatorio: cada capa con emoji al inicio + título destacado + metadata en línea separada + descripción en párrafo aparte. Las capas N/A van en una sola línea compacta.

**[v1.1 Cambio 4] Soluciones adaptativas según dimensionamiento del bug:**

En lugar de generar siempre 7 soluciones, el skill evalúa 3 dimensiones del bug y genera 3, 5 o 7 soluciones según el resultado.

**Las 3 dimensiones:**

| Dimensión | Trivial | Medio | Arquitectónico |
|---|---|---|---|
| **Alcance** | 1 archivo, una línea/frase | 1-2 archivos, sección o condición | 3+ archivos, nuevo componente o restructura |
| **Profundidad** | Corregir texto, regex o calibración de test | Corregir lógica o paso de slots, añadir condición | Crear sub-playbook/Task, tocar Main flow, Agent config o fuente de datos |
| **Riesgo de regresión** | Sin dependencias externas | Afecta 1-2 TCs relacionados | Afecta múltiples TCs simultáneamente |

**Regla de clasificación:**
El nivel final es el **máximo** de las tres dimensiones. Escala siempre hacia arriba, nunca hacia abajo.
- 3 dimensiones en Trivial → 3 soluciones
- Al menos una en Medio → 5 soluciones
- Al menos una en Arquitectónico → 7 soluciones

**Documentar la clasificación en el MD del análisis.** Añadir antes de la sección "Soluciones evaluadas":

```markdown
### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | <Trivial/Medio/Arquitectónico> | <razón breve> |
| Profundidad | <Trivial/Medio/Arquitectónico> | <razón breve> |
| Riesgo de regresión | <Trivial/Medio/Arquitectónico> | <razón breve> |

**Nivel final:** <Trivial/Medio/Arquitectónico> → <3/5/7> soluciones
```

**[v1.1 Cambio 3 actualizado] Las 9 capas obligatorias con marca explícita:**

Cada análisis evalúa OBLIGATORIAMENTE las 9 capas estándar (Comportamiento, Routing, Parámetros/Slots, Integración, Datos, Infraestructura, Modelo/LLM, Histórico, Test). Cada capa lleva una combinación de emoji + corchete:

- 🔴 [verificada] — capa comprobada con fuente, ES causa del bug
- 🟢 [verificada] — capa comprobada con fuente, NO es causa del bug
- 🟡 [supuesta] — no se pudo comprobar con fuente directa
- ⚪ [N/A] — esta capa no aplica al tipo de bug

Reglas:
- 🔴 y 🟢 REQUIEREN cita de fuente entre paréntesis tras la marca:
  * `Read <ruta>` — leíste el archivo
  * `git log -n 20 -- <ruta>` — viste el commit relevante
  * `gh pr view <N>` — verificaste el PR antes de citarlo
  * `gcloud logging read '<filtro>'` — viste el log del backend
  * `curl <URL>` — consultaste el endpoint del backend
- 🟡 REQUIERE razón explicando por qué no se pudo comprobar (`_(no verificado: <razón>)_`)
- ⚪ REQUIERE breve justificación de por qué la capa no aplica
- NUNCA cites un PR (#N), commit (sha), o variable de negocio sin haberlo verificado con la herramienta correspondiente
- SIEMPRE incluye el "Resumen visual" al final de la sección "Causa raíz" con el conteo de cada marca

### Paso 3c — Sub-agente de patrones + HTML + publicación (solo modo BATCH)

Solo en modo BATCH, tras el Paso 3-checkpoint. En modo INDIVIDUAL se omite.

Lanzar **UN único sub-agente** con contexto limpio usando la herramienta Agent. Este sub-agente asume toda la segunda fase: patrones, HTML, publicación y commit final.

**Por qué sub-agente y no inline:** el agente principal lleva el contexto acumulado de todos los TC sub-agentes. El sub-agente de patrones empieza con 200K tokens limpios y puede cargar la base de conocimiento del sistema sin restricciones de contexto.

#### Prompt del sub-agente de patrones

Sustituir `{TS}`, `{N}` y `{LISTA_TC_IDS}` con los valores reales del run antes de lanzar.

---
**CONTEXTO:**
- Run TS: `{TS}`
- TCs analizados: `{LISTA_TC_IDS}` (uno por línea, ej: TC-URGENCIA-01, TC-URGENCIA-02, TC-FRUSTRACION-01)
- Repo: `~/cx-automation-template`
- Rama activa: `qa/analyze-batch-{TS}` (ya existe en remote — el checkpoint ya fue commiteado)
- N TCs: `{N}`

**Tu tarea es completa y autónoma. No pidas confirmación en ningún paso.**

---

**PASO A — Leer MDs del disco:**

```bash
ls ~/cx-automation-template/qap/tc_analysis/{TS}/TC-*.md
```

Leer cada MD con la herramienta Read. Extraer de cada uno:
- `tipo` del frontmatter (`Bug Playbook`, `Bug Catálogo`, etc.)
- Capas con 🔴 y su descripción (causa raíz)
- Playbook involucrado
- Solución recomendada + tiempo estimado del frontmatter `estimacion`

---

**PASO B — Identificar patrones:**

Agrupar TCs por similitud en:
- Misma capa 🔴
- Mismo playbook involucrado
- Mismo síntoma en `agent_text`
- Mismo fix

Un grupo es patrón si **≥2 TCs** comparten al menos un atributo. Evaluar cada grupo con 3 razones independientes:

| Razón | Cómo evaluar | Estados |
|---|---|---|
| **Síntoma compartido** | ¿Respuesta del agente idéntica o muy similar? | ✅ / ⚠️ / ❌ |
| **Capa compartida** | ¿Misma capa 🔴? | ✅ / ⚠️ / ❌ |
| **Fix compartido** | ¿Mismo fix cierra varios TCs? | ✅ / ⚠️ / ❌ |

Calcular ROI: `(TCs resueltos / minutos_fix) × 60 = TCs/h`

---

**PASO C — Escribir `_patterns_{TS}.md`:**

Ruta: `~/cx-automation-template/qap/tc_analysis/{TS}/_patterns_{TS}.md`

**FORMATO OBLIGATORIO — NO INFERIR. Copiar esta estructura exacta:**

```markdown
---
run_ts: {TS}
generado: {FECHA_HOY}
---

TCs analizados en este batch: {TC-X, TC-Y, TC-Z}

## Patrón {NOMBRE} — {descripción corta}

**TCs:** {TC-X, TC-Y, TC-Z}

| Razón | Evaluación | Detalle |
|---|---|---|
| **Síntoma compartido** | ✅/⚠️/❌ | descripción concreta |
| **Capa compartida** | ✅/⚠️/❌ | descripción concreta |
| **Fix compartido** | ✅/⚠️/❌ | descripción concreta |

### ROI del patrón

| Fix | TCs resueltos | Esfuerzo | ROI |
|---|---|---|---|
| descripción del fix | **N TCs** | ~X min | Y TCs/h |

**Recomendación de secuencia:** texto corto — qué TC fijar primero y por qué.

## TCs sin patrón

| TC | Por qué no forma patrón |
|---|---|
| TC-X | razón concreta |

## Resumen ejecutivo

Texto libre: N patrones detectados, orden de ejecución recomendado, deuda técnica detectada.
```

**Reglas de parseo críticas** (son las que consume `_render_patterns_html` en `test_qa_playbooks.py`):
- `TCs analizados en este batch:` — texto literal exacto, línea sola tras el frontmatter
- `## Patrón` — exactamente 2 hashes, no 3
- `**TCs:**` — en negrita, dos puntos, sin variantes
- Tabla con cabeceras `| Razón | Evaluación | Detalle |` — exactas
- `### ROI del patrón` — exactamente 3 hashes
- ROI en formato `N TCs/h` (número entero, no decimal)
- `**Recomendación de secuencia:**` — en negrita, dos puntos
- `## TCs sin patrón` — obligatoria aunque esté vacía (tabla con 0 filas)
- `## Resumen ejecutivo` — siempre al final

Si no hay ningún patrón, el archivo contiene solo:
```markdown
---
run_ts: {TS}
generado: {FECHA_HOY}
---

TCs analizados en este batch: {TC-X, TC-Y, TC-Z}

## TCs sin patrón

| TC | Por qué no forma patrón |
|---|---|
| TC-X | razón |

## Resumen ejecutivo

Sin patrones cruzados detectados en este batch.
```

Anotar en la sección `## Recomendación` de cada TC que forme parte de un patrón:
> **Forma parte del patrón {nombre}.** Si el fix de TC-YYY resuelve la causa raíz común, TC-ZZZ pasará a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.

---

**PASO D — Regenerar HTML:**

```bash
cd ~/cx-automation-template && source .venv/bin/activate

# Intentar con logs locales primero
if [ -d ~/petal-qa/qa_{TS}_logs ]; then
  python qap/regenerate_html.py --logs-dir ~/petal-qa/qa_{TS}_logs --out /tmp/qa_regen_{TS}.html
else
  python qap/regenerate_html.py --ts {TS} --out /tmp/qa_regen_{TS}.html
fi
```

---

**PASO E — Publicar en gh-pages:**

```bash
bash ~/cx-automation-template/qap/publish_html.sh /tmp/qa_regen_{TS}.html {TS}
```

---

**PASO F — Commit final + PR + merge:**

```bash
cd ~/cx-automation-template
git add qap/tc_analysis/{TS}/_patterns_{TS}.md
git commit -m "qa(analysis): patrones cruzados + HTML publicado — run {TS}"
git push
gh pr create \
  --title "qa(analysis): {N} análisis + patrones del run {TS}" \
  --body "$(cat <<'EOF'
## Análisis batch run {TS}

- {N} TCs analizados
- Patrones detectados: ver _patterns_{TS}.md
- Dashboard: https://jeronimosanchez.github.io/cx-automation-template/qa/{TS}/qa_latest.html

🤖 Generated with Claude Code
EOF
)"
gh pr merge --admin --squash
```

---

**Devuelve al agente principal SOLO:**
`PATRONES: OK — {N_PATRONES} patrón(es) · {N_TCS_CON_PATRON} TCs afectados · HTML publicado`

---

**Pasos 4, 5 y 6 están absorbidos por este sub-agente. El agente principal no los ejecuta.**

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

Confirmaciones de sub-agentes TC:
  TC-XXX: OK — Bug Playbook · fix ~15min
  TC-YYY: OK — Bug Catálogo · fix ~10min

Confirmación sub-agente patrones:
  PATRONES: OK — 1 patrón · 3 TCs afectados · HTML publicado

🌐 Ver dashboard:
   https://jeronimosanchez.github.io/cx-automation-template/qa/$TS/qa_latest.html
```

## Coste

- API CX: **0 €** (no se ejecuta QA)
- API Anthropic: **0 €** (uso tokens de conversación)
- Tiempo: **~3 min por TC** + 30 seg regenerate/publish

## Reglas importantes

- **NO ejecutes QA** salvo que el usuario lo pida explícitamente
- Si un MD ya existe, sobreescríbelo sin preguntar (a menos que se use el flag `--keep-existing`). Los MDs viejos quedan en git, recuperables con `git show <commit>:qap/tc_analysis/{TS}/TC-X.md`
- **Sin confirmaciones en ningún caso.** Arranca siempre directo, independientemente del número de TCs.
- **Para ≥2 TCs: siempre lanzar sub-agentes en paralelo** — no analizar secuencialmente
- **Los sub-agentes devuelven una sola línea** — no el MD completo. El contexto del agente principal no crece con el contenido de los análisis
- **Ruta siempre run-scoped:** `qap/tc_analysis/{TS}/{TC-ID}.md` — nunca el path plano sin subcarpeta de timestamp
- Si encuentras información en el JSON que requiere trace adicional (interno de CX), menciónalo como **limitación** en la causa raíz
- Usa SIEMPRE el último TS de gh-pages a menos que el usuario diga otro
- Después de publicar, recuerda al usuario: "El HTML puede tardar 1-2 min en propagarse en gh-pages"

## Ejemplos de uso real

**Ejemplo 1 — Individual:**
```
Usuario: /qa-tc-analyzer TC-FRUSTRACION-01
Claude:
  1. Detecta TS=20260518_192907 (último)
  2. Descarga TC-FRUSTRACION-01.json
  3. Escribe qap/tc_analysis/TC-FRUSTRACION-01.md
  4. python qap/regenerate_html.py --ts 20260518_192907
  5. ./qap/publish_html.sh /tmp/qa_regen_*.html 20260518_192907
  6. Commit + PR + merge
  7. Reporta URL
Total: ~3 min, 0€
```

**Ejemplo 2 — Batch:**
```
Usuario: analiza todos los fails
Claude:
  1. python qap/list_fails.py --only-pending → ["TC-A", "TC-B", "TC-C"]
  2. Arranca directo sin confirmar (sin excepciones de número de TCs)
  3. Paso 3: lanza sub-agentes TC en paralelo
     Cada sub-agente escribe MD en qap/tc_analysis/{TS}/ y devuelve UNA LÍNEA
  4. Paso 3-checkpoint: git commit de los MDs (punto de recuperación)
  5. Paso 3c: lanza sub-agente de patrones con contexto limpio
     → Analiza patrones, escribe _patterns_{TS}.md, regenera HTML, publica, hace PR+merge
  6. Reporta confirmaciones
Total: ~12 min, 0€

**Ejemplo 3 — Batch grande (20 TCs):**
```
Usuario: analiza todos los fails
Claude:
  1. python qap/list_fails.py --only-pending → 20 TCs
  2. Arranca directo sin confirmar
  3. Paso 3: 20 sub-agentes en paralelo. Cada uno carga su JSON + system_knowledge.md
     Devuelven solo una línea cada uno → contexto principal no se satura
  4. Paso 3-checkpoint: git commit (20 MDs seguros)
  5. Paso 3c: sub-agente patrones — contexto limpio, carga todos los MDs del disco
  6. Reporta tabla resumen
Total: ~20 min, 0€
```
