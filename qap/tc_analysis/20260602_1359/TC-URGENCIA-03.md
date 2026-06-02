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

El historial muestra que el bloque DETECCION RESTRICCION TEMPORAL existe completo en el commit `c6f17bf` y cubre ambos casos (hora explícita + día relativo "viernes"). El fix está disponible en git para recuperarse.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado para confirmación de plazo. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Recuperar el bloque desde git `c6f17bf` (COMPARTIDO con TC-URGENCIA-01)

🟢 **9/10** · ~0 min marginal · Sin dependencias externas

**Por qué**: el bloque DETECCION RESTRICCION TEMPORAL que ya existe en el commit `c6f17bf` cubre explícitamente el caso de día relativo ("este viernes" → "Sin problema para el viernes, el plazo es 24h Madrid/Barcelona, 48h resto"). El mismo bloque que se recupera para TC-URGENCIA-01 resuelve este TC. Un único `git restore` cierra ambos.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ya existente en `c6f17bf` |
| Profundidad | Medio | El bloque maneja día relativo + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | Bloque ya validado; recuperación de git limpia |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Recuperar bloque de git `c6f17bf`** — cierra TC-01 + TC-03 | 🟢 9/10 | — | El fix ya existe completo y cubre día relativo. ROI doble, no se reinventa nada |
| 2 | **Recuperar `c6f17bf` + slot `$fecha_entrega` propagado** | 🟢 8/10 | — | Igual de fiable + habilita validaciones futuras |
| 3 | **Reescribir el bloque desde cero** | 🟡 6/10 | — | Funciona pero reinventa algo que ya está en git |
| 4 | **Expandir ZG-5 del Orquestador** para detectar mención de plazo | 🟡 5/10 | — | Acopla responsabilidad de negocio al Orquestador |
| 5 | **Sub-playbook Plazo_Task** | 🔴 3/10 | — | Sobre-ingeniería + latencia |

### Plan de acción (Solución #1, COMPARTIDO con TC-URGENCIA-01)

1. **Recuperar el bloque** de `c6f17bf` (mismo que para TC-URGENCIA-01) — cubre día relativo además de hora explícita
2. **Verificar** que el bloque incluye triggers de días de semana ("este viernes", "lunes"..."domingo")
3. **Re-ejecutar QA** con `--runs 3` filtrando ambos TCs

**Coste total**: ~5 min (compartido → coste marginal TC-03 = 0)

**Forma parte del patrón URGENCIA-IGNORADA.** El bloque de `c6f17bf` resuelve la causa raíz común — al recuperarlo, este TC pasará a PASS sin cambios adicionales.
