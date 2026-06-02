---
status: FAIL
tipo: Bug Playbook
estimacion: ~0 min marginal (fix COMPARTIDO con TC-URGENCIA-01)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"lo necesito para este viernes"* | — |
| 2 | Orquestador | Clasifica G3 (exploración) | ✅ Correcto |
| 3 | Compra | Acknowledge "para este viernes" pero pregunta tipo/presupuesto | 🔴 No menciona plazo ni viabilidad |
| 4 | Compra | Cierra con apertura exploratoria | 🔴 Pierde oportunidad de informar política proactivamente |

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

Mismo bug que TC-URGENCIA-01. compra.yaml NO tiene sub-flujo URGENCIA. El agente reconoce el día pero no informa del plazo. La regla ZG-5 del orquestador solo activa cuando el user PREGUNTA plazo, no cuando lo MENCIONA.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente)_

No existe slot $fecha_entrega que capture "viernes" de forma estructurada para el playbook.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

Sin tool call problemática. Agente respondió texto válido.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene tiempo_entrega_estimado="24h Madrid/Barcelona, 48h resto" — exactamente lo que el regex del test espera. La política existe, el playbook no la expone.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 — Capa 1 es la causa)_

Con Capa 1 como causa clara, la regla binaria impide marcar 🔴 en LLM.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

El historial muestra que el bloque DETECCION RESTRICCION TEMPORAL existe en commits anteriores y cubría ambos casos (hora explícita + día relativo). El fix está disponible en el git para aplicarse.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado para confirmación de plazo. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Bloque DETECCION RESTRICCION TEMPORAL (COMPARTIDO con TC-URGENCIA-01)

🟢 **9/10** · ~0 min marginal · Sin dependencias externas

**Por qué**: el mismo bloque que arregla TC-URGENCIA-01 cubre también el caso de día relativo ("viernes"). Un único fix cierra ambos TCs.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ~8 líneas |
| Profundidad | Medio | Sub-flujo temporal + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | Fix histórico validado |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Bloque DETECCION RESTRICCION TEMPORAL** — cierra TC-01 + TC-03 | 🟢 9/10 | — | Fix compartido, ROI doble |
| 2 | **Solución #1 + slot $fecha_entrega propagado** | 🟢 8/10 | — | Habilita validaciones futuras |
| 3 | **Expandir ZG-5 del Orquestador** para detectar mención de plazo | 🟡 6/10 | — | Acopla responsabilidad de negocio al Orquestador |
| 4 | **Tool validar_plazo_entrega** en backend | 🟡 5/10 | Extender Cloud Run | Determinístico, requiere tocar backend |
| 5 | **Sub-playbook Plazo_Task** | 🔴 3/10 | — | Sobre-ingeniería + latencia |

### Plan de acción (Solución #1, COMPARTIDO con TC-URGENCIA-01)

1. **Editar compra.yaml**: el mismo bloque DETECCION RESTRICCION TEMPORAL cubre día relativo
2. **Verificar** triggers de días de semana
3. **Re-ejecutar QA** con `--runs 3` filtrando ambos TCs

**Coste total**: ~11 min (compartido → coste marginal TC-03 = 0)

**Forma parte del patrón URGENCIA-IGNORADA.** Si el fix de TC-URGENCIA-01 resuelve la causa raíz común, este TC pasará a PASS sin cambios adicionales.
