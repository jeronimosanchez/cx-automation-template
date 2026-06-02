---
status: FAIL
tipo: Bug Playbook
estimacion: ~20min
---

# TC-FRUSTRACION-01 — Multiples rechazos consecutivos — debe escalar o reformular

**Grupo:** COMPRA-ZG | **Tipo:** EDGE | **Runs:** 0/3 PASS | **Fecha:** 2026-06-02 13:59

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente (resumen) | Check | Problema |
|-------|---------|------------------|-------|----------|
| T1 | "quiero rosas" | Pregunta por ocasión especial | ✅ PASS (3/3) | Ninguno |
| T2 | "no me gustan" | Reconoce y reformula (alternativa / color / desambigua rosas-vs-ocasión) | ✅ PASS (3/3) | Ninguno — comportamiento variable pero siempre matchea el regex de T2 |
| T3 | "tampoco me convencen, dame otras" | Run1: "Ya te mostré lo más afín, ¿otra flor o color?" · Run2: "Te busco una alternativa, ¿flor en mente o presupuesto?" · Run3: muestra catálogo de 3 ramos | ❌ FAIL (0/3) | El regex exige `propongo\|alternativ.{0,30}tipo\|otra ocasion\|equipo\|persona\|humano`. En las 3 ejecuciones el agente reformula por dimensiones NO cubiertas (color, presupuesto, catálogo directo). Ninguna respuesta contiene token verificable |
| T4 | "ninguna me gusta" | Run1+Run2: escala al equipo (Alicia) ✅ · Run3: **respuesta vacía** ❌ | ⚠️ FAIL en Run3 (2/3) | En Run3 el agente NO emite texto: la escalación no se dispara. Regex `equipo\|persona\|humano\|hablar\|...` no matchea sobre cadena vacía |

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Instrucción de playbook 📄 [CAUSA RAÍZ]

**compra.yaml, línea 726**, sección `GESTION DE FRUSTRACION`:

```
1. RECHAZO ACUMULADO: rechazo 1 reformula. Rechazo 2 pregunta motivo. Rechazo 3 reformula y muestra una mas. Rechazo 4 ESCALAR.
```

Dos defectos en una sola línea:

1. **"Rechazo 2 pregunta motivo" es ambiguo.** "Motivo" no especifica dimensión (tipo de flor, ocasión, estilo) ni prohíbe mostrar catálogo. El LLM lo resuelve de forma distinta en cada run — color (Run1/Run3), presupuesto (Run2), catálogo directo (Run3 T3) — todas válidas conversacionalmente pero ninguna alineada con los tokens que verifica T3. El agente no falla; la instrucción ambigua falla.
2. **El conteo de rechazos deriva.** En Run3 el agente muestra catálogo en T3 (comportamiento de "Rechazo 3 reformula y muestra una mas") un turno antes de lo previsto. Esto desincroniza el contador: cuando llega T4 ("ninguna me gusta", que debería ser el Rechazo 4 → ESCALAR), el agente queda en estado indeterminado y devuelve respuesta vacía en lugar de escalar. La instrucción describe los escalones de rechazo en prosa sin anclar el incremento de `$contador_rechazos` por turno, dejando el conteo a la interpretación del modelo.

### Capa 2 — Lógica de flujo / condiciones 🔀 [CONTRIBUYENTE]

El mecanismo de escalación funciona cuando el contador llega a 4 (Run1 y Run2 escalan correctamente en T4). Pero el conteo en sí no es robusto: en Run3 la progresión Rechazo 1→2→3→4 se descalibra y la escalación nunca se activa (T4 vacío). El bug no está en la frase de escalación sino en el cómputo previo. La derivación nace de la instrucción de Capa 1, por eso aquí es contribuyente, no causa raíz independiente.

### Capa 3 — Datos / Sheet 📊 [NO APLICA]

SHEET_OK. La lógica de frustración es puramente comportamental. El catálogo mostrado en Run3 T3 (Peonías 35€, Girasoles 20€, Gerberas 18€) es coherente con `/tmp/sheet_business.json`; el problema no es el dato sino que mostrarlo en ese turno descalibra el conteo.

### Capa 4 — Regex / Verificación del test 🔍 [CONTRIBUYENTE SECUNDARIO]

**test_qa_playbooks.py, línea 410**, check T3: `propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano`

No cubre las dimensiones de reformulación que el agente elige espontáneamente (color, presupuesto, catálogo). Es síntoma de la ambigüedad de Capa 1: si la instrucción se precisa hacia tipo/ocasión, el regex queda cubierto. El check T4 (línea 413) es correcto pero no puede matchear sobre la respuesta vacía de Run3 — ahí el fallo es real, no de calibración.

### Capa 5 — Prompt del orquestador 🧠 [LIMPIA]

Orquestador v65. La gestión de frustración es responsabilidad del playbook Compra (v39). No hay evidencia de interferencia del orquestador.

### Capa 6 — Contexto conversacional / slots 🗂️ [CONTRIBUYENTE]

`$contador_rechazos` (declarado en compra.yaml líneas 75-76 y 141-142, "Incrementa en cada rechazo") no se observa en el JSON de params en ninguno de los turnos — el log expone `modo_tono`, `grupo_intent`, `producto`, `intencion_inicial` pero nunca el contador. Esto sugiere que el contador no se está materializando como slot persistente entre turnos y que el escalado se rige por la lectura que el LLM hace del histórico, lo que explica la derivación de Run3.

### Capa 7 — Herramientas / Tools 🔧 [NO APLICA]

No se invocan tools verificables en este flujo. El catálogo de Run3 T3 proviene del LLM/contexto, no de una tool call trazada en el TC.

### Capa 8 — NLU / Clasificación de intent 🎯 [LIMPIA]

Inputs claros y cortos. `grupo_intent=G5` correcto en todos los turnos. El agente entiende cada turno como un rechazo; el problema es qué hace con él, no cómo lo clasifica.

### Capa 9 — Modelo / Temperatura 🌡️ [CONTRIBUYENTE]

A diferencia del análisis previo (1 run), las 3 ejecuciones muestran respuestas distintas en T2 y T3, y un fallo intermitente de escalación en T4 (vacío solo en Run3). Hay un componente estocástico real: la instrucción ambigua deja margen suficiente para que la variación del modelo descalibre el conteo en algunas ejecuciones. Bajar temperatura mitigaría el síntoma pero no corrige la causa — la instrucción debe ser determinista por sí misma.

---

### Resumen visual de capas

| Capa | Nombre | Estado |
|------|--------|--------|
| 1 | Instrucción de playbook | 🔴 CAUSA RAÍZ |
| 2 | Lógica de flujo / condiciones | 🟡 CONTRIBUYENTE |
| 3 | Datos / Sheet | ⚪ NO APLICA |
| 4 | Regex / Verificación del test | 🟡 CONTRIBUYENTE SECUNDARIO |
| 5 | Prompt del orquestador | 🟢 LIMPIA |
| 6 | Contexto conversacional / slots | 🟡 CONTRIBUYENTE |
| 7 | Herramientas / Tools | ⚪ NO APLICA |
| 8 | NLU / Clasificación de intent | 🟢 LIMPIA |
| 9 | Modelo / Temperatura | 🟡 CONTRIBUYENTE |

**Resumen:** 1 🔴 · 2 🟢 · 4 🟡 · 2 ⚪

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Severidad | Media — el paso de reformulación (T3) falla en 3/3, y la escalación (T4) falla intermitentemente en 1/3. El peor caso (Run3) deja al usuario frustrado sin respuesta ni handoff |
| Alcance | Acotado al bloque GESTION DE FRUSTRACION (compra.yaml líneas 722-743), específicamente al Rechazo 2 y al cómputo de `$contador_rechazos` |
| Regresión | No — el bloque GESTION DE FRUSTRACION no se ha tocado en los últimos 20 commits (todos son URGENCIA/temporal/multi-producto). Bug preexistente, no introducido por el trabajo de urgencia |
| Complejidad del fix | Baja — precisar 1 línea (726) y, opcionalmente, anclar el incremento del contador por turno |
| Impacto en usuario real | Medio — la reformulación degradada es tolerable, pero la respuesta vacía de Run3 es una ruptura visible (el agente "se queda mudo" ante un cliente frustrado) |
| TCs potencialmente afectados | Solo TC-FRUSTRACION-01; ningún otro TC de COMPRA-ZG verifica este bloque |
| Clasificación | **Menor** (peor caso intermitente eleva sobre Trivial) |

---

## Recomendación

### Solución #1 — Precisar Rechazo 2 + anclar conteo en playbook ⭐ RECOMENDADA · score 9/10

**Archivo:** `definitions/playbooks/compra.yaml`, línea 726

**Cambio:**
```
# ANTES
1. RECHAZO ACUMULADO: rechazo 1 reformula. Rechazo 2 pregunta motivo. Rechazo 3 reformula y muestra una mas. Rechazo 4 ESCALAR.

# DESPUÉS
1. RECHAZO ACUMULADO (incrementa $contador_rechazos en CADA turno de rechazo): rechazo 1 reformula. Rechazo 2 pregunta tipo de flor preferido u ocasion concreta (NO mostrar catalogo aun). Rechazo 3 reformula y muestra una mas. Rechazo 4 (o mas) ESCALAR SIEMPRE con la FRASE ESCALACION del tono.
```

**Razonamiento:** Resuelve los dos defectos a la vez. (a) "pregunta tipo de flor preferido u ocasion concreta" fuerza tokens que el regex de T3 ya cubre (`tipo`, `ocasion`) y prohíbe explícitamente el catálogo, eliminando la derivación de Run3. (b) "incrementa $contador_rechazos en CADA turno" + "Rechazo 4 (o mas) ESCALAR SIEMPRE" ancla el conteo y garantiza que T4 nunca quede en respuesta vacía.

**Riesgo:** Muy bajo. Solo afecta al bloque de frustración; Rechazo 1, 3 y los disparadores 2-5 mantienen su comportamiento.

---

### Solución #2 — Ampliar regex T3 para aceptar dimensiones válidas · score 5/10

**Archivo:** `qap/test_qa_playbooks.py`, línea 410

**Cambio:** `propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano|color|presupuesto`

**Razonamiento:** Si preguntar por color o presupuesto es reformulación válida al Rechazo 2, el test debería aceptarla. Soluciona el FAIL de T3 sin tocar el playbook.

**Riesgo:** Medio-alto. Vuelve el test más permisivo y, sobre todo, **no corrige la respuesta vacía de T4 en Run3** — el fallo de escalación seguiría intermitente. No recomendable como solución única.

---

### Solución #3 — Combinar fix playbook + ampliar regex · score 7/10

**Archivos:** `definitions/playbooks/compra.yaml` (línea 726) + `qap/test_qa_playbooks.py` (línea 410)

**Cambio:** Aplicar Solución #1 y además añadir `color|presupuesto` al regex de T3 como tokens alternativos aceptables.

**Razonamiento:** Máxima robustez: la instrucción precisa guía hacia tipo/ocasión y ancla el conteo, mientras el regex ampliado absorbe el caso borde si el agente combina tipo con color/presupuesto. Blinda el TC contra variabilidad residual del LLM (Capa 9).

**Riesgo:** Bajo. Dos ediciones triviales; cobertura óptima.

---

### Plan de acción (Solución #1)

1. Abrir `definitions/playbooks/compra.yaml`
2. Localizar línea 726, sección `GESTION DE FRUSTRACION`
3. Reemplazar la línea de RECHAZO ACUMULADO por la versión precisa (ver arriba)
4. Commit: `fix(compra): precisa Rechazo 2 y ancla conteo en GESTION DE FRUSTRACION`
5. PR → merge → esperar deploy
6. Rerun TC-FRUSTRACION-01 (3 runs) — verificar PASS en T3 y escalación no vacía en T4

**Tiempo estimado:** ~20 min (5 min edición + 12-15 min deploy + 3 min rerun ×3)

---

## Patrones cruzados

- **NO comparte causa con TC-URGENCIA.** URGENCIA falla por anclaje de plazo temporal (`$hora_actual` inyectada, Example G1) en el FLUJO PRINCIPAL; este TC falla en el bloque GESTION DE FRUSTRACION por instrucción de rechazo ambigua y conteo no anclado. Sin solape de archivo (líneas distintas), de mecanismo ni de fix. **Anotar como TC sin patrón compartido con URGENCIA.**

- **Instrucciones de un solo término sin dimensión explícita** — "pregunta motivo", "reformula", "ofrece alternativa" se prestan a interpretación libre del LLM. El patrón `[verbo] [objeto vago]` es propenso a comportamientos válidos-pero-no-verificables. Revisar bloques análogos (GESTION_CLIENTE, SLOT_FILLING) y añadir dimensión explícita.

- **Contadores descritos en prosa sin anclaje de incremento** — `$contador_rechazos`, `$contador_repeticion_slot`, `$contador_sugerencias` se describen en lenguaje natural (líneas 723-728) pero su incremento no está anclado por turno y no aparecen en los params del log. Cualquier disparador que dependa de un umbral de conteo (Rechazo 4, Repetición 3, Sugerencia 3) hereda el mismo riesgo de derivación visto en Run3. Considerar materializar los contadores como slots con incremento explícito.
