# Proceso de análisis QA — Documento maestro

> **Propósito:** documentar exactamente cómo se realiza el análisis de un TC en FAIL del QA de Petal, qué fuentes se consultan, qué se produce, y cómo evoluciona el proceso a lo largo del tiempo.
>
> **Fuente única de verdad** sobre el proceso. Cualquier cambio al skill `qa-analyze` queda reflejado primero aquí, validado contra un caso real, y luego propagado al `SKILL.md`.

---

## 📑 Índice

1. [Visión general](#vision-general)
2. [Versión actual — v1.0](#version-actual--v10)
3. [Versión propuesta — v1.1](#version-propuesta--v11)
4. [Tabla comparativa v1.0 vs v1.1](#tabla-comparativa-v10-vs-v11)
5. [Caso testigo: TC-URGENCIA-01](#caso-testigo-tc-urgencia-01)
6. [Métricas](#metricas)
7. [Changelog](#changelog)

---

## Visión general

El análisis QA arranca cuando un TC sale FAIL en un run de la suite. El usuario invoca el skill `qa-analyze` (o copia-pega un prompt desde el HTML) y se genera un análisis Markdown con:

- **Diagnóstico:** qué falla y en qué turno
- **Causa raíz** (multi-capa: playbook, catálogo, política, test)
- **7 soluciones** evaluadas con score 1-10 y trade-offs
- **Plan de acción** para la solución recomendada

El análisis se publica en `qa/tc_analysis/{TC-ID}.md` y se renderiza en el HTML de gh-pages.

---

## Versión actual — v1.0

### Fuentes de información

| # | Fuente | Acceso | Uso |
|---|---|---|---|
| 1 | JSON del TC (turnos, params, trace, checks) | `curl` desde gh-pages (URL en el copy-paste) | Reconstruir la conversación que falló |
| 2 | Texto truncado en el copy-paste del HTML | Embebido directamente | "Agente respondió (primeros 120 chars): ..." |
| 3 | `qa/test_QA_Playbooks_v23.py` | Read tool, opcional | Ver definición del check regex |
| 4 | Playbooks (`compra.yaml`, `checkout.yaml`...) | Read tool, no obligatorio | Confirmar qué hay en el código actual |

### Flujo (extraído del SKILL.md)

1. **Identificar modo** (individual o batch) y TS del run
2. **Descargar JSON** del TC con `curl` desde gh-pages
3. **Analizar** los turnos del JSON, identificar el turno que falla, extraer params y trace
4. **Generar MD** con la plantilla rica (Turnos vs Problemas + 7 soluciones + Plan)
5. **Regenerar HTML** con `regenerate_all_html.sh` y publicar en gh-pages
6. **Commit** del MD a main vía PR + merge

### Salida (formato del MD)

- `status`, `tipo`, `estimacion` en frontmatter
- Tabla "Turnos vs Problemas detectados"
- "Causa raíz" descompuesta en N capas (texto libre, sin marcado de fuente)
- Solución recomendada con score 🟢🟡🔴
- Tabla con 7 soluciones (siempre 7) DESC por score
- Plan de acción
- (Opcional) Tabla de slots si involucra transferencias entre playbooks

### Limitaciones conocidas v1.0

- ❌ No verifica el histórico de PRs antes de citarlos → riesgo de alucinación
- ❌ No lee la memoria del proyecto → puede inventar decisiones de producto
- ❌ No consulta Cloud Run logs cuando falla un tool call → causa raíz superficial
- ❌ Texto del agente truncado a 120 chars en el copy-paste → contexto perdido salvo que descargue JSON
- ❌ Siempre 7 soluciones aunque el caso sea trivial → contenido inflado innecesariamente
- ❌ No marca afirmaciones verificadas vs supuestas → usuario no sabe qué auditar
- ❌ Depende de gh-pages haya propagado (latencia 1-2 min) → puede leer datos antiguos

---

## Versión propuesta — v1.1

### Cambios principales

#### Cambio 1 — Fuentes verificables adicionales

| # | Fuente nueva | Acceso | Cuándo se usa |
|---|---|---|---|
| 5 | JSON local en `~/petal-qa/qa_<TS>_logs/<TC>.json` | Read tool | Siempre que exista (rerun_single_tc) → más rápido y fiable que gh-pages |
| 6 | `git log --since="14 days ago" --oneline -- definitions/playbooks/<archivo>.yaml` | Bash tool | Siempre, para detectar histórico relevante |
| 7 | `gh pr view <N>` (cuando se va a citar un PR) | Bash tool | Solo si el análisis va a citar un PR concreto |
| 8 | `gcloud logging read 'resource.labels.service_name="petal-sheet-api" AND httpRequest.status=400' --freshness=30m` | Bash tool | Solo si el agente respondió con error_generico (fallo de tool call) |
| 9 | Memoria del proyecto (`memory/MEMORY.md` + carpetas relevantes) | Read tool | Siempre, para conocer decisiones de producto y deuda técnica documentada |

#### Cambio 2 — Estrategia "local primero, gh-pages fallback"

Antes de descargar con `curl`:

```bash
# 1. Intentar local
ls -t ~/petal-qa/qa_*_logs/<TC-ID>.json | head -1
# Si existe → leer con Read tool (instantáneo, offline-safe)

# 2. Si no existe local → fallback a gh-pages
curl -sf https://jeronimosanchez.github.io/.../qa_latest_logs/<TC-ID>.json
```

**Razón:** las suites completas se ejecutan en GitHub Actions y solo viven en gh-pages. Los `rerun_single_tc.sh` se ejecutan en local y viven en ambos sitios. Esta estrategia funciona para ambos casos sin esfuerzo extra del usuario.

#### Cambio 3 — Marcado ✓ verificado vs ? supuesto en el output

En la sección "Causa raíz" del MD, cada capa lleva marca explícita:

```markdown
1. **Capa Playbook** ✓ verificada (`Read compra.yaml línea 487`): el bloque X no existe en el código actual.
2. **Capa Histórico** ✓ verificada (`git log`): el fix existió en `3f041df` (#83) y fue revertido en `aca187c` (#84).
3. **Capa Política** ? supuesta: Petal probablemente no soporta same-day delivery (no verificable sin variables de negocio expuestas).
```

#### Cambio 4 — Formato adaptativo de soluciones

Cambiar la regla "siempre 7 soluciones" por:

- **Bug trivial / Test mal calibrado:** 3 soluciones
- **Bug medio:** 5 soluciones
- **Bug arquitectónico:** 7 soluciones

Justificar el corte si se usan menos de 7.

#### Cambio 5 — Detección de patrones cruzados (en modo batch)

Antes de lanzar sub-agentes para analizar varios FAILs:

1. Agrupar TCs por keywords compartidas en `agent_text` (ej. todos los que dicen "Lo siento, algo no ha funcionado" → posible fallo común en checkout)
2. Reportar al usuario: *"⚠️ TC-X, TC-Y, TC-Z comparten patrón <descripción>. Posible causa raíz común."*

Esto conecta con la deuda técnica `automatizacion/deuda_analisis_dependencias_TC.md`.

### Limitaciones que persisten en v1.1

- ❌ Variables de negocio del Sheet aún no accesibles por endpoint dedicado → en v2.0
- ❌ No hay validación automática de si el análisis "funcionó" (la solución aplicada cierra el TC) → manual por ahora

---

## Tabla comparativa v1.0 vs v1.1

| Dimensión | v1.0 (actual) | v1.1 (propuesta) | Beneficio |
|---|---|---|---|
| **Fiabilidad de fuente JSON** | 99% (curl a gh-pages, depende de propagación) | 100% para reruns locales, 99% para suites | +1% sin dependencia de red |
| **Velocidad de descarga JSON** | 2-3 s | 0.002 s (local) o 2-3 s (fallback) | Instantáneo en mayoría de casos |
| **Riesgo de alucinación PRs** | Alto (yo cito sin verificar) | Bajo (verifico con `gh pr view`) | Más confianza del usuario |
| **Profundidad causa raíz tool call** | Superficial (solo texto del agente) | Profunda (Cloud Run logs con params del POST) | Detección exacta de campos vacíos |
| **Conocimiento de decisiones de producto** | Nulo (solo lo que infiero del playbook) | Documentado en memoria | Menos invenciones sobre "Petal no soporta X" |
| **Cantidad de soluciones** | Siempre 7 (algunas relleno) | 3-7 según complejidad | Output más realista |
| **Auditabilidad** | Difícil (todo afirmado sin fuente) | Fácil (✓/? con cita) | Usuario sabe qué revisar |
| **Detección de TCs con causa común** | Manual | Automática en modo batch | Priorización por ROI |

---

## Caso testigo: TC-URGENCIA-01

### Aplicación v1.0

**Análisis:** `qa/tc_analysis/TC-URGENCIA-01.md` (versión actual, generada el 21-may-2026 mañana).

**Solución recomendada:** #1 — Re-aplicar bloque DETECCION URGENCIA TEMPORAL.

**Resultado tras aplicar fix (cherry-pick `3e0b2d1`):** TC pasa de FAIL a PASS al primer rerun.

**Verificación post-mortem:** la solución funcionó, pero el análisis original (versión del skill, no la mejorada en chat) tenía afirmaciones sobre PR #83/#84 que en su momento se cuestionaron como posible alucinación. Tras verificar con `git log --grep`, **eran reales** — el skill citó algo correcto pero sin marcado verificable, lo que generó dudas innecesarias.

### Aplicación v1.1 — Pendiente

Plan:
1. Borrar `qa/tc_analysis/TC-URGENCIA-01.md` actual
2. Re-invocar el skill `qa-analyze` con las mejoras de v1.1 aplicadas al SKILL.md
3. Comparar el output nuevo con el anterior
4. Documentar diferencias

**Métricas a capturar:**
- Tiempo de generación (v1.0 vs v1.1)
- Número de afirmaciones marcadas ✓ vs ?
- Número de soluciones generadas (3-7 según complejidad)
- Si menciona patrones cruzados con TC-URGENCIA-02 y TC-URGENCIA-03

---

## Métricas

> Se rellenan tras aplicar v1.1 a los casos testigo.

| Métrica | v1.0 | v1.1 | Mejora |
|---|---|---|---|
| Tiempo medio de análisis | — | — | — |
| % afirmaciones verificadas | 0% (sin marcado) | ?% | ↑ |
| Soluciones aplicadas que cerraron TC | 1/1 (TC-URGENCIA-01) | — | — |
| Casos con detección de patrones cruzados | 0 | — | — |
| Alucinaciones detectadas post-hoc | 1 falsa (PRs #83/#84 → resultaron reales) | — | — |

---

## Changelog

### 21-may-2026 — Creación del documento (v1.0 documentado, v1.1 propuesto)

- Documentado el estado actual del proceso v1.0 a partir del `SKILL.md`.
- Detectado en sesión interactiva el riesgo de alucinaciones sobre PRs (caso TC-URGENCIA-01 con PRs #83/#84 — falsa alarma pero síntoma real de falta de marcado de fuentes).
- Confirmado que los JSONs locales viven en `~/petal-qa/qa_<TS>_logs/<TC-ID>.json` y persisten entre runs. Las suites completas viven solo en gh-pages.
- Propuesta v1.1 con 5 cambios: fuentes verificables, local primero, marcado ✓/?, formato adaptativo, detección de patrones cruzados.
- Pendiente: aplicar v1.1 al SKILL.md y validar contra TC-URGENCIA-01 + TC-URGENCIA-02 + TC-URGENCIA-03 (que comparten causa raíz).

### 21-may-2026 (tarde) — Aplicado Cambio 2 al SKILL.md

- **Cambio 2 (local primero, gh-pages fallback)** integrado en el `SKILL.md` (Paso 2).
- Antes: `curl` siempre a gh-pages (~2-3 seg por TC, depende de propagación).
- Después: lectura local instantánea (~0.002 seg) cuando existe; fallback a gh-pages cuando no.
- Beneficio esperado: análisis más rápido en reruns individuales (caso habitual de iteración).
- Pendiente de validar contra TC-URGENCIA-01 (caso testigo).

### 21-may-2026 (tarde) — Aplicado Cambio 3 al SKILL.md

- **Cambio 3 (marcado ✓ verificada / ? supuesta)** integrado en `SKILL.md` (sección "Causa raíz" + reglas clave).
- Cada capa de la causa raíz ahora obligatoriamente lleva marca:
  - **✓ verificada** con cita de fuente (`Read X`, `git log Y`, `gh pr view N`, `gcloud logging Z`, `curl URL`)
  - **? supuesta** con razón de por qué no se pudo verificar
- Reglas añadidas: nunca usar ✓ sin fuente; nunca citar un PR/commit/variable de negocio sin verificación previa.
- Habilita el KPI `pct_verificadas` del futuro benchmark (épica `epic_benchmark_skills_qa.md`).
- También habilita versionar `.claude/skills/` en git (hecho en commit anterior `08d6ab9`).
- Pendiente de validar contra TC-URGENCIA-01 (caso testigo).
