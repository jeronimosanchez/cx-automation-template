---
status: FAIL
tipo: Bug Playbook
estimacion: ~11 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas para hoy a las 18:00"* | — |
| 2 | Sistema | Inyecta session_params: hora_actual=11:21, entrega_hoy_posible=no, dia_semana=domingo | ✅ El dato de urgencia SÍ llega al contexto |
| 3 | Compra | Muestra catálogo de rosas ignorando los session_params | 🔴 No consume entrega_hoy_posible=no |
| 4 | Compra | Cierra con apertura estándar | 🔴 No avisa de plazo ni de que hoy no es posible |

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml`

El playbook NO tiene instrucción que consuma los session_params de urgencia (hora_actual, entrega_hoy_posible, dia_semana). El dato llega al contexto pero el playbook no lo lee ni lo usa para avisar al usuario.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks, no Flows.

🟢 3. **Capa Parámetros/Slots** [verificada] · `JSON del log (params.fields)`

Los session_params SÍ se inyectan correctamente: hora_actual=11:21, entrega_hoy_posible=no, dia_semana=domingo. El contrato de slots funciona — el problema no es la inyección, es que el playbook no los consume (eso es Capa 1).

🟢 4. **Capa Integración** [verificada] · `JSON del log`

Sin tool call problemática. El catálogo se muestra correctamente.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene horario_corte_mismo_dia=14:00 y tiempo_entrega_estimado. Datos completos y coherentes.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones idénticas — Capa 1 es la causa identificada)_

Con Capa 1 como causa clara (falta instrucción), la regla binaria impide marcar 🔴 en LLM.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

El historial muestra que el bloque DETECCION RESTRICCION TEMPORAL existe en commits anteriores (b32f773 session_params dinámicos). El fix está disponible en el git para aplicarse.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado: captura cualquier respuesta que mencione plazo/urgencia/no-disponible. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 4 🟢 · 1 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Bloque DETECCION RESTRICCION TEMPORAL que consuma session_params

🟢 **9/10** · ~11 min · Sin dependencias externas

**Por qué**: los session_params (entrega_hoy_posible) ya llegan al contexto. Solo falta el bloque de instrucción en compra.yaml que los lea y avise al usuario. El fix existe en el historial.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ~8 líneas |
| Profundidad | Medio | Sub-flujo que consume session_params + respuesta determinística |
| Riesgo de regresión | Trivial | Fix histórico validado |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Bloque DETECCION RESTRICCION TEMPORAL** que lee entrega_hoy_posible y avisa | 🟢 9/10 | — | Los datos ya llegan, solo falta consumirlos. Fix histórico validado |
| 2 | **Solución #1 + propagar a Checkout** el flag de urgencia | 🟢 8/10 | — | Más completo para validaciones futuras |
| 3 | **Generator dedicado** para respuestas de urgencia | 🟡 6/10 | — | Añade componente, más mantenimiento |
| 4 | **Tool validar_plazo en backend** | 🟡 5/10 | Extender Cloud Run | Determinístico pero toca backend |
| 5 | **Sub-playbook Plazo_Task** | 🔴 3/10 | — | Sobre-ingeniería + latencia de hop |

### Plan de acción (Solución #1)

1. **Editar compra.yaml**: añadir bloque que lee `entrega_hoy_posible`; si es "no", avisar del plazo antes de mostrar catálogo
2. **Verificar** que consume los session_params inyectados
3. **Re-ejecutar QA** con `--runs 3`

**Coste total**: ~8 min edición + 3 min QA = ~11 min.

**Forma parte del patrón URGENCIA-IGNORADA.** Si el fix resuelve la causa raíz, TC-URGENCIA-03 pasará a PASS sin cambios adicionales.
