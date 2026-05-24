---
name: qa-tc-analyzer
version: 1.1
description: Analiza FAILs del QA con 9 capas de causa raíz, dimensionamiento del bug (alcance/profundidad/riesgo), consulta del Sheet, lectura de memoria del proyecto y detección de patrones cruzados. Publica en HTML de gh-pages. Soporta individual o batch. Coste 0€. Uso: '/qa-tc-analyzer TC-XYZ' o 'analiza todos los fails'.
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

### Paso 3c — Análisis de patrones cruzados (solo modo BATCH) [v1.1 Cambio 5]

Solo se ejecuta en modo BATCH **después** de completar el análisis individual de todos los TCs. En modo INDIVIDUAL este paso se omite.

**1. Identificar grupos candidatos:**
Para los TCs en FAIL ya analizados, agrupar por similitud comparando:
- `tipo` (del frontmatter del MD)
- Capa(s) 🔴 (qué capa(s) están fallando)
- Playbook involucrado
- `agent_text` (texto del agente al fallar)
- Solución recomendada

Un grupo se considera candidato a patrón si **2 o más TCs** comparten al menos uno de estos atributos.

**2. Evaluar cada grupo candidato con 3 razones independientes:**

| Razón | Cómo se evalúa | Estados |
|---|---|---|
| **Síntoma compartido** | ¿`agent_text` idéntico o muy similar? | ✅ existe / ⚠️ parcial / ❌ no existe |
| **Capa compartida** | ¿Misma capa 🔴 o capas relacionadas? | ✅ existe / ⚠️ parcial / ❌ no existe |
| **Fix compartido** | ¿La misma solución cierra varios TCs? | ✅ existe / ⚠️ parcial / ❌ no existe |

Las tres razones son independientes. No son excluyentes. Un patrón puede tener síntoma sin capa compartida, fix sin síntoma, etc.

**3. Calcular ROI por patrón:**

| TC a fixear | Alcance (TCs potencialmente resueltos) | Esfuerzo (tiempo del fix) | ROI (TCs/h) |
|---|---|---|---|
| TC-XXX | <N> TCs | <X> min | <N/X> |

**4. Generar bloque dedicado en el reporte:**
Crear un archivo adicional `qa/tc_analysis/_patterns_<TS>.md` con todos los patrones detectados, sus razones, y la tabla ROI.

Si no se detecta ningún patrón, el archivo contiene únicamente:
```markdown
## Patrones cruzados detectados

✅ Sin patrones cruzados detectados en este batch.
```

Este archivo es renderizado por `qa/regenerate_html.py` como sección destacada al inicio del reporte batch del dashboard (ver Cambio F).

**5. Anotar en cada TC del patrón:**
En la sección "Recomendación" del MD individual de cada TC afectado, añadir una nota:

> **Forma parte del patrón <nombre>.** Previsión de alcance: si el fix de TC-YYY resuelve la causa raíz común, es probable que TC-ZZZ y TC-WWW pasen a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.

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
- Si un MD ya existe, sobreescríbelo sin preguntar (a menos que se use el flag `--keep-existing`). Los MDs viejos quedan en git, recuperables con `git show <commit>:qa/tc_analysis/TC-X.md`
- **Política de confirmación unificada:**
  - **BATCH con >5 FAILs:** pide confirmación UNA vez al inicio (antes de lanzar los sub-agentes), porque puede ser largo
  - **BATCH con ≤5 FAILs:** sin confirmación, arranca directo
  - **INDIVIDUAL (1 TC):** sin confirmación, arranca directo
  - **Durante el análisis:** NUNCA pidas confirmación. Mostrar el análisis en pantalla y proceder automáticamente al Paso 4-6
- **Para ≥2 TCs: siempre lanzar sub-agentes en paralelo** — no analizar secuencialmente
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
  3. Escribe qa/tc_analysis/TC-FRUSTRACION-01.md
  4. python qa/regenerate_html.py --ts 20260518_192907
  5. ./qa/publish_html.sh /tmp/qa_regen_*.html 20260518_192907
  6. Commit + PR + merge
  7. Reporta URL
Total: ~3 min, 0€
```

**Ejemplo 2 — Batch (≤5 FAILs, sin confirmación):**
```
Usuario: analiza todos los fails
Claude:
  1. python qa/list_fails.py --only-pending → ["TC-A", "TC-B", "TC-C"]
  2. Arranca directo (≤5 FAILs, no requiere confirmación)
  3. Lanza sub-agentes en paralelo: uno por TC. Cada uno descarga JSON y escribe MD
  4. regenerate_html UNA vez al final
  5. publish_html UNA vez al final
  6. Commit + PR con los 3 MDs
  7. Reporta tabla resumen
Total: ~10 min, 0€

**Ejemplo 3 — Batch (>5 FAILs, confirmación una vez):**
```
Usuario: analiza todos los fails
Claude:
  1. python qa/list_fails.py --only-pending → ["TC-A", ..., "TC-H"] (8 TCs)
  2. Confirma una vez al inicio: "Voy a analizar 8 TCs (~25 min). ¿Continúo?"
  3. Tras OK del usuario, lanza sub-agentes en paralelo
  4. regenerate_html + publish_html + Commit + PR
Total: ~25 min, 0€
```
