---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

# TC-URGENCIA-01 — Entrega urgente — variante hora numerica ('hoy a las 6')

**Suite:** QA Playbooks v23 | **Fecha análisis:** 2026-05-25 | **Versiones:** orquestador v65 / compra v39

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente | Check | Estado |
|-------|---------|--------|-------|--------|
| T1 | "necesito un ramo de rosas para hoy a las 6" | "¿De qué color te gustaría el ramo de rosas?" | FAIL: Agente debía decir [hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano] | 🔴 FAIL |

**Turno crítico: T1** — El usuario especifica una entrega urgente ("hoy a las 6"). El agente debía detectar el indicador temporal y comunicar que no puede garantizar entrega en ese plazo (o derivar a equipo humano), pero en su lugar ignora la urgencia y avanza directamente al flujo de catálogo solicitando el color del ramo.

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Comportamiento 🔴 [verificada]
El agente no detecta el indicador de urgencia temporal "hoy a las 6" al inicio de la conversación. En lugar de ejecutar el bloque DETECCION URGENCIA TEMPORAL, entra directamente en el flujo de captura de catálogo (color del producto). El comportamiento esperado es reconocer la restricción temporal antes de avanzar en el flujo de compra.

### Capa 2 — Routing ⚪ N/A
No hay evidencia de problema de routing entre flujos o páginas. El agente llega al flujo de compra correctamente; el fallo ocurre dentro del playbook de compra, no en la transición entre flujos.

### Capa 3 — Parámetros / Slots ⚪ N/A
No aplica. El fallo ocurre antes de cualquier extracción de slots. El agente ni siquiera intenta capturar el parámetro de fecha/hora de entrega porque el bloque de detección no existe.

### Capa 4 — Integración ⚪ N/A
No aplica. La lógica de urgencia es puramente comportamental dentro del playbook; no requiere llamada a Tool ni webhook para este punto del flujo.

### Capa 5 — Datos 🟢 [verificada]
SHEET_OK. Los recursos business y agent_copy son objetos JSON válidos. La lógica de urgencia es puramente comportamental y no depende de datos del Sheet; no se detectan incoherencias de datos relacionadas con este TC.

### Capa 6 — Infraestructura ⚪ N/A
No aplica. No hay errores de deploy, timeout ni fallos de API reportados. El agente responde correctamente, solo con el comportamiento equivocado.

### Capa 7 — LLM 🟢 [verificada]
El LLM funciona correctamente: interpreta la petición del usuario y genera una respuesta coherente con el flujo de catálogo. El problema no es de comprensión lingüística sino de ausencia de instrucción en el playbook que dirija al LLM a verificar el plazo antes de continuar.

### Capa 8 — Histórico 🔴 [verificada]
Causa raíz confirmada por histórico de git. El bloque DETECCION URGENCIA TEMPORAL fue implementado en commit `3e0b2d1` y posteriormente en `a10ab02` (ambos con validación en producción: resolvía TC-URGENCIA-01, TC-URGENCIA-02 y TC-URGENCIA-03 simultáneamente). El commit `a10ab02` fue revertido en `1f95cae`, y `3e0b2d1` fue revertido en su correspondiente revert. El HEAD actual es `2126c52` (revert de `a10ab02`), dejando compra.yaml sin el bloque de detección de urgencia. El fix existe, está validado y solo necesita ser reaplicado.

### Capa 9 — Test 🟢 [verificada]
El test está bien calibrado. El patrón regex `[hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]` es correcto y cubre las respuestas esperadas del agente ante una urgencia temporal. El FAIL es un verdadero positivo: el agente realmente no da ninguna de esas respuestas.

### Resumen visual de capas

| Capa | Estado | Descripción |
|------|--------|-------------|
| 1 — Comportamiento | 🔴 | Agente ignora urgencia temporal y avanza al catálogo sin verificar plazo |
| 2 — Routing | ⚪ | N/A — el routing entre flujos es correcto |
| 3 — Parámetros / Slots | ⚪ | N/A — fallo ocurre antes de la captura de slots |
| 4 — Integración | ⚪ | N/A — no requiere Tool ni webhook en este punto |
| 5 — Datos | 🟢 | Sheet OK, lógica de urgencia es puramente comportamental |
| 6 — Infraestructura | ⚪ | N/A — el agente responde sin errores de infra |
| 7 — LLM | 🟢 | LLM funciona; el problema es la ausencia de instrucción, no comprensión |
| 8 — Histórico | 🔴 | Fix validado revertido en commit 2126c52; bloque ausente en HEAD actual |
| 9 — Test | 🟢 | Test bien calibrado; FAIL es verdadero positivo |

**2 🔴 · 3 🟢 · 0 🟡 · 4 ⚪**

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Alcance | 3 TCs afectados simultáneamente (TC-URGENCIA-01, TC-URGENCIA-02, TC-URGENCIA-03) |
| Profundidad | Bloque completo ausente en compra.yaml — no es un ajuste de texto sino una sección de lógica |
| Riesgo de regresión | Bajo — el fix fue validado en producción en `a10ab02`; reaplicarlo es predecible |
| Severidad | Alta — afecta a un caso de negocio crítico (urgencia de entrega) que puede generar promesas incumplibles al cliente |
| Clasificación | **Medio** |

---

## Recomendación

### Solución #1 — Reaplicar bloque DETECCION URGENCIA TEMPORAL desde commit a10ab02 ⭐ RECOMENDADA

**Puntuación: 10/10 | Esfuerzo: ~15 min**

Recuperar el bloque DETECCION URGENCIA TEMPORAL tal como existía en el commit `a10ab02` y añadirlo al FLUJO PRINCIPAL de `compra.yaml` en la posición correcta (antes del inicio del flujo de catálogo). El bloque debe incluir: detección de indicadores temporales urgentes ("hoy", "ahora", "en X horas", hora numérica del mismo día), respuesta informando del plazo mínimo de entrega, y opción de continuar si el plazo es aceptable o derivar a equipo humano si no lo es.

**Por qué es la mejor opción:** El fix está validado en producción. El commit `a10ab02` resolvió los 3 TCs de urgencia simultáneamente sin efectos secundarios conocidos. Reaplicarlo es la ruta de menor riesgo y mayor confianza. No requiere diseño nuevo ni experimentación.

**Verificación:** Ejecutar suite con los 3 TCs de urgencia con `--runs 3`. Los 3 deben pasar. Revisar también que TC del flujo de compra normal (sin urgencia) no se ve afectado.

---

### Solución #2 — Implementar detección de urgencia desde cero con diseño actualizado

**Puntuación: 6/10 | Esfuerzo: ~45 min**

Diseñar e implementar un nuevo bloque de detección de urgencia temporal en compra.yaml, revisando el diseño conversacional para incorporar aprendizajes desde `a10ab02`. Incluiría: patrones de detección más amplios, respuestas más naturales, y posiblemente integración con la lógica de slots de fecha/hora. Útil si se detectan limitaciones en el diseño original, pero requiere más tiempo de diseño y validación.

---

### Solución #3 — Revert del revert (git revert 2126c52)

**Puntuación: 5/10 | Esfuerzo: ~5 min**

Ejecutar `git revert 2126c52` para deshacer el revert y recuperar el estado de `a10ab02`. Técnicamente correcto y el más rápido, pero arriesgado si el motivo del revert original tenía justificación (el git log muestra un ciclo fix→revert→fix→revert que sugiere posibles efectos secundarios no documentados). Requiere investigar por qué se hizo el revert antes de aplicarlo ciegamente.

---

### Plan de acción (Solución #1)

1. Inspeccionar el bloque DETECCION URGENCIA TEMPORAL tal como estaba en `a10ab02`: `git show a10ab02 -- definitions/playbooks/compra.yaml`
2. Añadir el bloque recuperado al FLUJO PRINCIPAL de `definitions/playbooks/compra.yaml` en la posición correcta (antes del bloque de inicio de catálogo), usando Edit.
3. Re-ejecutar: `python qa/test_QA_Playbooks_v23.py --test TC-URGENCIA-01,TC-URGENCIA-02,TC-URGENCIA-03 --runs 3`
4. Criterio de éxito: 3/3 PASS en los 3 TCs

**Comando QA post-fix:**
```bash
python qa/test_QA_Playbooks_v23.py --test TC-URGENCIA-01,TC-URGENCIA-02,TC-URGENCIA-03 --runs 3
```

---

## Patrones cruzados

- **Patrón revert-sin-documentación:** El ciclo `fix → revert → fix → revert` sobre el mismo bloque (4 commits) sin mensaje explicativo del motivo del revert indica un proceso de integración frágil. Riesgo: el mismo bloque puede volver a revertirse sin causa registrada. Recomendación: añadir nota en el commit de fix reaplicado explicando el historial y por qué se mantiene esta vez.
- **Patrón alcance N:1:** Un único bloque ausente en compra.yaml provoca 3 FAILs simultáneos (TC-URGENCIA-01, -02, -03). Indica alta cohesión del bloque de urgencia: un solo fix resuelve múltiples TCs. Prioridad de fix elevada por ratio impacto/esfuerzo.
- **Patrón pre-slot detection:** La detección de restricciones de negocio (plazo de entrega, zonas, stock) debe ocurrir antes de la captura de slots de catálogo. Si el agente captura producto antes de validar viabilidad operativa, genera expectativas incorrectas al usuario. Este patrón se repite potencialmente en otros flujos (TC-DECO, TC-IMPOSIBLE).
