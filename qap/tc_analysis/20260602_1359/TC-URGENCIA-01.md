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

El historial muestra que el bloque DETECCION RESTRICCION TEMPORAL existe completo en el commit `c6f17bf` (playbook que consume `$hora_actual`). Además, `b32f773` añadió la inyección de los session_params en el test. El fix de playbook está disponible en git para recuperarse.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado: captura cualquier respuesta que mencione plazo/urgencia/no-disponible. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 4 🟢 · 1 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Recuperar el bloque DETECCION RESTRICCION TEMPORAL desde git (`c6f17bf`)

🟢 **9/10** · ~5 min · Sin dependencias externas

**Por qué**: el bloque que resuelve este bug **ya existe completo y validado en el historial de git** (commit `c6f17bf` — "DETECCION RESTRICCION TEMPORAL con $hora_actual inyectada"). No hay que construir nada nuevo: el bloque lee `$hora_actual` (que ya se inyecta como session_param), calcula el corte de las 14:00, y responde la política de entrega. Cubre tanto la hora explícita ("hoy a las 18:00") como el día relativo ("este viernes"). Recuperarlo de git es más rápido y seguro que reescribirlo. **El humano valida que esta es la mejor opción frente a construir desde cero.**

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ya existente en `c6f17bf` |
| Profundidad | Medio | El bloque consume `$hora_actual` + responde política determinística |
| Riesgo de regresión | Trivial | Bloque ya validado en su momento; recuperación de git limpia |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Recuperar bloque de git `c6f17bf`** (`git show c6f17bf:definitions/playbooks/compra.yaml` → restaurar el bloque) | 🟢 9/10 | — | El fix ya existe completo y validado. Usa `$hora_actual` inyectado. Cubre hoy + día futuro. La opción más rápida y segura: no se reinventa nada |
| 2 | **Recuperar `c6f17bf` + propagar flag de urgencia a Checkout** | 🟢 8/10 | — | Igual de fiable + prepara validaciones de viabilidad futuras |
| 3 | **Reescribir el bloque desde cero** consumiendo session_params | 🟡 6/10 | — | Funciona pero reinventa algo que ya está en git. Más tiempo, más riesgo de introducir variaciones |
| 4 | **Tool validar_plazo en backend** | 🟡 5/10 | Extender Cloud Run | Determinístico al 100% pero toca el backend, sobredimensionado |
| 5 | **Sub-playbook Plazo_Task** | 🔴 3/10 | — | Sobre-ingeniería + latencia de hop adicional |

### Plan de acción (Solución #1)

1. **Recuperar el bloque** de `c6f17bf`: `git show c6f17bf:definitions/playbooks/compra.yaml` → copiar el bloque DETECCION RESTRICCION TEMPORAL y aplicarlo a `compra.yaml` actual (tras el GOAL, antes del PASO 0)
2. **Verificar** que el bloque consume `$hora_actual` (ya inyectado como session_param)
3. **Re-ejecutar QA** con `--runs 3`

**Coste total**: ~3 min recuperación + 3 min QA = ~5 min (más rápido que reescribir).

**Forma parte del patrón URGENCIA-IGNORADA.** Si el bloque recuperado resuelve la causa raíz, TC-URGENCIA-03 pasará a PASS sin cambios adicionales (el mismo bloque cubre día relativo).
