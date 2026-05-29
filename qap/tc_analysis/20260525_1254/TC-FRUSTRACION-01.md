---
status: FAIL
tipo: Bug Playbook
estimacion: ~20 min (Solución #1 recomendada)
---

# TC-FRUSTRACION-01 — Multiples rechazos consecutivos — debe escalar o reformular

**Suite:** QA Playbooks v23 | **Fecha análisis:** 2026-05-25 | **Versiones:** orquestador v65 / compra v39

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente | Check | Estado |
|-------|---------|--------|-------|--------|
| T1 | "quiero rosas" | "¿Es para alguna ocasión especial? Cumpleaños, boda, decoración..." | Agente dijo [ocasion] | 🟢 PASS |
| T2 | "no me gustan" | "Claro, te busco otras. ¿Tienes algún color en mente o lo dejo en mis manos?" | Agente dijo [otra] | 🟢 PASS |
| T3 | "tampoco me convencen, dame otras" | "Entiendo, disculpa la confusion. Te busco una alternativa. ¿Tienes algún color en mente o lo dejo en mis manos?" | Agente debía decir `[propongo\|alternativ.{0,30}tipo\|otra ocasion\|equipo\|persona\|humano]` | 🔴 FAIL |
| T4 | "ninguna me gusta" | "Creo que lo mejor es que hables con mi equipo - ellos te encontrarán exactamente lo que buscas. Hola, soy Alicia..." | Agente dijo [equipo] | 🟢 PASS |

**Turno crítico: T3** — segundo rechazo consecutivo. El fallo se reproduce en los 3 runs (0/3).

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Comportamiento 🔴 [verificada]

**Fallo:** La instrucción "Rechazo 2 pregunta motivo" en el bloque `GESTION DE FRUSTRACION` de `definitions/playbooks/compra.yaml` (líneas 722-743) es ambigua. El LLM interpretó "motivo" como preguntar por el color ("¿Tienes algún color en mente?") en lugar de preguntar por tipo de flor u ocasión concreta.

**Evidencia:**
- Instrucción en compra.yaml: `"Rechazo 2 pregunta motivo"`
- Respuesta del agente en T3: `"Te busco una alternativa. ¿Tienes algún color en mente o lo dejo en mis manos?"`
- Regex del check: `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]`
- "color" no está en el regex → FAIL

El TONO RECONOCIMIENTO se aplicó correctamente ("Entiendo, disculpa la confusion. Te busco una alternativa."), pero la pregunta de seguimiento no contenía ninguna de las palabras verificadas.

**Fuente:** `definitions/playbooks/compra.yaml` líneas 722-743 + respuesta del agente en T3.

---

### Capa 2 — Routing ⚪ N/A

No hay cambio de flow ni de playbook involucrado en este TC. El agente permanece en el playbook Compra durante toda la conversación.

---

### Capa 3 — Parámetros / Slots 🟢 [verificada]

Los parámetros funcionan correctamente. El contador de rechazos avanza como esperado: en T4 (rechazo 3 acumulado) el agente escala al equipo humano, lo que confirma que `$contador_rechazos` se está incrementando y que el mecanismo de escalación del Rechazo 4 está operativo. El bug está en la instrucción del Rechazo 2, no en el tracking de parámetros.

---

### Capa 4 — Integración 🟢 [verificada]

No hay tool calls relevantes en este TC. La lógica de frustración es puramente conversacional y no depende de ninguna herramienta externa.

---

### Capa 5 — Datos ⚪ N/A

La lógica de GESTION DE FRUSTRACION es puramente comportamental. No hay dependencia del Sheet ni de datos externos. El estado del Sheet (SHEET_OK) es irrelevante para este TC.

---

### Capa 6 — Infraestructura ⚪ N/A

No se detectan problemas de infraestructura. El agente responde en todos los turnos sin errores de conectividad ni timeouts.

---

### Capa 7 — LLM 🟢 [verificada]

El LLM está siguiendo las instrucciones correctamente. "Preguntar motivo" es una instrucción válida que el LLM interpreta preguntando por un atributo del producto (color). No hay alucinación: el LLM hace exactamente lo que la instrucción (ambigua) le permite hacer. El problema está en la especificidad de la instrucción, no en el comportamiento del modelo.

---

### Capa 8 — Histórico 🟢 [verificada]

Revisado `git log -- definitions/playbooks/compra.yaml` (últimos 20 commits). No se detecta ningún commit de DEMO BREAK ni revert específico para el bloque GESTION DE FRUSTRACION ni para la lógica de RECHAZO ACUMULADO. Los commits de DEMO BREAK recientes afectaron a ECO RESUMEN multi-producto y `$producto_2`, no a frustración. Este es un bug pre-existente de instrucción ambigua, no una regresión reciente.

```
2126c52 Revert "fix(compra): añade bloque DETECCION URGENCIA TEMPORAL..."
a10ab02 fix(compra): añade bloque DETECCION URGENCIA TEMPORAL...
c9ce667 DEMO BREAK v2: rompe ECO RESUMEN multi-producto      ← no afecta frustración
b8f9ee5 DEMO BREAK: quita captura de $producto_2             ← no afecta frustración
237955b fix(checkout+compra): FIX T17...
```

---

### Capa 9 — Test 🟢 [verificada]

El regex `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]` es correcto y captura las respuestas esperadas para un Rechazo 2 bien ejecutado. La solución no pasa por ampliar el test, sino por mejorar la instrucción del playbook para que el agente incluya "tipo" u "ocasion" en su respuesta.

---

### Resumen visual de capas

| Capa | Estado | Descripción |
|------|--------|-------------|
| 1 Comportamiento | 🔴 | Instrucción "Rechazo 2 pregunta motivo" ambigua |
| 2 Routing | ⚪ | N/A |
| 3 Parámetros/Slots | 🟢 | Contadores funcionan; escalación en T4 correcta |
| 4 Integración | 🟢 | Sin tool calls relevantes |
| 5 Datos | ⚪ | N/A — lógica puramente comportamental |
| 6 Infraestructura | ⚪ | N/A |
| 7 LLM | 🟢 | Sigue instrucciones; la instrucción es ambigua, no hay alucinación |
| 8 Histórico | 🟢 | Sin DEMO BREAK ni revert para este bloque |
| 9 Test | 🟢 | Regex correcto |

**1 🔴 · 3 🟢 · 0 🟡 · 5 ⚪**

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Alcance | Localizado — 1 archivo, 1 línea de instrucción |
| Profundidad | Superficial — cambio de texto en bloque existente |
| Riesgo de regresión | Bajo — la instrucción más específica no afecta otros disparadores de frustración |
| Severidad | Media — el TC falla siempre (0/3), pero el flujo general de escalación funciona (T4 escala correctamente) |
| Clasificación | **Trivial** |

---

## Recomendación

### Solución #1 — Especificar instrucción Rechazo 2 en compra.yaml ⭐ RECOMENDADA

**Puntuación: 9/10 | Esfuerzo: ~10 min**

**Cambio:** En `definitions/playbooks/compra.yaml`, línea ~726, modificar:

```
# ANTES
Rechazo 2 pregunta motivo.

# DESPUÉS
Rechazo 2 pregunta tipo de flor preferido u ocasion concreta para reformular la busqueda (no añadir catalogo).
```

**Por qué es la mejor opción:** Corrige la causa raíz (instrucción ambigua), mejora la experiencia real del usuario (preguntar por tipo/ocasión es más útil para reformular que preguntar por color), y el riesgo de regresión es mínimo — el resto del bloque FRUSTRACION no se toca.

**Verificación:** El agente debería responder en T3 algo como "Entiendo. ¿Qué tipo de flor tienes en mente, o hay alguna ocasión concreta para la que las buscas?", lo que activa `tipo` o `ocasion` en el regex.

---

### Solución #2 — Ampliar regex del test para incluir 'color'

**Puntuación: 6/10 | Esfuerzo: ~5 min**

Añadir `color` al regex del check T3: `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano|color]`.

**No recomendada:** Ajusta el test para que pase con el comportamiento actual, pero no mejora el playbook. Preguntar por "color" en Rechazo 2 es una respuesta subóptima para reformular la búsqueda — es mejor preguntar por tipo u ocasión. Esta solución enmascara el bug sin resolverlo.

---

### Solución #3 — Añadir Example de frustración Rechazo-2

**Puntuación: 5/10 | Esfuerzo: ~30 min**

Crear un Example que muestre el comportamiento correcto en Rechazo 2 (agente pregunta por tipo/ocasión), reforzando la instrucción del playbook.

**No recomendada como solución primaria:** Complementaria a la Solución #1, no alternativa. Un Example sin instrucción clara puede ser ignorado por el LLM bajo variabilidad. Abordar como refuerzo posterior si el fix de Solución #1 no es suficientemente estable.

---

### Plan de acción (Solución #1)

1. Editar `definitions/playbooks/compra.yaml` línea ~726
2. Cambiar: `Rechazo 2 pregunta motivo.`
3. Por: `Rechazo 2 pregunta tipo de flor preferido u ocasion concreta para reformular la busqueda (no añadir catalogo).`
4. Commit + PR + merge → deploy automático vía CI/CD
5. Re-ejecutar: `python qa/test_QA_Playbooks_v23.py --tc TC-FRUSTRACION-01 --runs 3`
6. Criterio de éxito: 3/3 PASS

**Comando QA post-fix:**
```bash
python qa/test_QA_Playbooks_v23.py --tc TC-FRUSTRACION-01 --runs 3
```

---

## Patrones cruzados

- **Instrucción ambigua → fallo reproducible:** patrón similar a otros TCs donde la vaguedad de la instrucción genera variabilidad en la respuesta del LLM. Revisar si otros disparadores del bloque FRUSTRACION tienen instrucciones igualmente ambiguas (ej. "Rechazo 3 reformula y muestra una mas" — ¿qué significa "una mas"?).
- **T4 escala correctamente:** confirma que el mecanismo de handoff a equipo humano funciona. El bug está acotado al comportamiento del Rechazo 2, no al sistema de escalación completo.
