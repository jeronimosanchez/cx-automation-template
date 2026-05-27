---
status: FAIL
tipo: Bug Playbook
estimacion: ~25 min (Solución #1 recomendada, COMPARTIDA con TC-URGENCIA-01)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"lo necesito para este viernes"* | — |
| 2 | Orquestador | Clasifica G3 (exploración, modo corporativo) | ✅ Correcto |
| 3 | Compra | Acknowledge "para este viernes" pero pregunta tipo/presupuesto | 🔴 No menciona plazo de entrega ni viabilidad para viernes |
| 4 | Compra | Cierra con apertura estándar exploratoria | 🔴 Pierde oportunidad de informar política proactivamente |

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

Mismo bug que TC-URGENCIA-01. compra.yaml NO tiene sub-flujo "PLAZO/URGENCIA". El playbook reconoce el día ("De acuerdo, para este viernes") pero no informa proactivamente del plazo. La línea 254 del orquestador (ZG-5) solo activa cuando el user PREGUNTA plazo explícitamente, no cuando lo MENCIONA dentro de su intención.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente)_

No existe slot $fecha_entrega; el día "viernes" se pierde después del ACK inicial.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

Sin tool call problemática. El agente respondió texto válido, solo falta el contenido requerido.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene tiempo_entrega_estimado="24h en Madrid y Barcelona, resto de ciudades 48 horas" — EXACTAMENTE el contenido que el regex del test espera. La política existe, solo falta exponerla.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones)_

Con 1 sola ejecución no se puede afirmar reproducibilidad. Capa 1 es la causa → esta queda 🟡.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

HISTORIAL DE REGRESIÓN COMPARTIDA con TC-URGENCIA-01. Los commits 3f041df / a10ab02 / 3e0b2d1 implementaban el bloque DETECCION URGENCIA TEMPORAL que cubría TANTO la hora explícita (TC-01) como la fecha relativa (TC-03). Revertidos en aca187c / 2126c52 / 1f95cae. Patrón demo break.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado para confirmación de plazo. Captura "24h", "24 horas", "plazo", "días", "llega", "tiempo entrega", etc. Sin falsos negativos detectables.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL (compartida con TC-URGENCIA-01)

🟢 **9/10** · ~25 min · Sin dependencias externas

**Por qué**: el bloque histórico ya cubría AMBOS casos (hora explícita + día relativo). Un solo fix cierra los dos TCs.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque nuevo de ~10 líneas |
| Profundidad | Medio | Sub-flujo de detección temporal + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | No toca flujos existentes; fix histórico ya validado en su día |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Cherry-pick a10ab02 (bloque DETECCION URGENCIA TEMPORAL)** — cierra TC-01 + TC-03 simultáneamente | 🟢 9/10 | — | Fix histórico validado, ROI doble (2 TCs / 1 fix) |
| 2 | **Solución #1 + slot $fecha_entrega propagado a Checkout** | 🟢 8/10 | — | Más completo, habilita validaciones futuras de viabilidad real |
| 3 | **Expandir ZG-5 del Orquestador para detectar mención (no solo pregunta) de plazo** | 🟡 6/10 | — | Acopla responsabilidad de negocio al Orquestador; menos cohesivo |
| 4 | **Tool validar_plazo_entrega en backend** | 🟡 5/10 | Extender petal-sheet-api | Determinístico, pero requiere tocar Cloud Run y tabla nueva |
| 5 | **Sub-playbook Plazo_Task invocado por Compra al detectar trigger temporal** | 🔴 3/10 | — | Sobre-ingeniería para algo que cabe en 10 líneas; añade latencia de hop |

### Plan de acción (Solución #1, COMPARTIDA con TC-URGENCIA-01)

1. **Cherry-pick**: `git cherry-pick a10ab02` desde rama feature
2. **Verificar formato**: el bloque DETECCION URGENCIA TEMPORAL debe estar tras el GOAL, antes del FLUJO PRINCIPAL
3. **Push y deploy** (~3 min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01 + TC-URGENCIA-03

**Coste total**: ~11 min (compartido con TC-URGENCIA-01 → coste marginal de TC-03 es 0)
