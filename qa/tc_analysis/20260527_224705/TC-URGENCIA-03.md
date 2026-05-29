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
| 2 | Orquestador | Clasifica G3 (exploración corporativa) | ✅ Correcto |
| 3 | Compra | Acknowledge "para este viernes" + pregunta tipo/presupuesto | 🔴 No menciona plazo ni viabilidad |
| 4 | Compra | Cierra con apertura exploratoria estándar | 🔴 Pierde oportunidad de informar política proactivamente |

### Causa raíz — evaluación de las 9 capas

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

Mismo bug que TC-URGENCIA-01. compra.yaml NO tiene sub-flujo URGENCIA. El agente reconoce el día ("De acuerdo, para este viernes") pero no informa proactivamente del plazo. La línea 254 del orquestador (ZG-5) solo activa cuando user PREGUNTA plazo.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente todos los slots)_

No existe slot `$fecha_entrega`; el día "viernes" se pierde tras el ACK inicial.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

Sin tool call problemática. Agente respondió texto válido, solo falta contenido requerido.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene `tiempo_entrega_estimado="24h en Madrid y Barcelona, 48h resto"` — EXACTAMENTE el contenido que el regex del test espera. La política existe, el playbook no la expone.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones idénticas — Capa 1 es la causa)_

Con Capa 1 como causa clara, regla binaria impide marcar 🔴 en LLM.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

HISTORIAL DE REGRESIÓN COMPARTIDA con TC-URGENCIA-01. Commits `e1984b5` + `cbf9eef` (refuerzo) cubrían AMBOS casos (hora explícita + día relativo "viernes"). Revertidos en `77828fa` y `56b5271`. Patrón demo break.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado para confirmación de plazo. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Cherry-pick `e1984b5` + refuerzo `cbf9eef` (COMPARTIDO con TC-URGENCIA-01)

🟢 **9/10** · ~0 min marginal · Sin dependencias externas

**Por qué**: el refuerzo `cbf9eef` cubre EXPLÍCITAMENTE días de semana en triggers (lunes-domingo, "este X"). Validado empíricamente sesión 2026-05-28: TC-URGENCIA-03 → 3/3 PASS con refuerzo.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ~8 líneas |
| Profundidad | Medio | Sub-flujo detección temporal + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | Fix histórico validado |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Cherry-pick `e1984b5` + `cbf9eef`** — cierra TC-01 + TC-03 simultáneamente | 🟢 9/10 | — | Fix histórico validado, ROI doble |
| 2 | **Solución #1 + slot `$fecha_entrega` propagado a Checkout** | 🟢 8/10 | — | Habilita validaciones futuras de viabilidad real |
| 3 | **Expandir ZG-5 del Orquestador para detectar mención (no solo pregunta) de plazo** | 🟡 6/10 | — | Acopla responsabilidad negocio al Orquestador |
| 4 | **Tool `validar_plazo_entrega`** en petal-sheet-api | 🟡 5/10 | Extender backend | Determinístico, requiere tocar Cloud Run |
| 5 | **Sub-playbook `Plazo_Task`** invocado por Compra | 🔴 3/10 | — | Sobre-ingeniería; añade latencia de hop |

### Plan de acción (Solución #1, COMPARTIDO con TC-URGENCIA-01)

1. **Cherry-pick**: `git cherry-pick e1984b5 cbf9eef`
2. **Verificar**: bloque DETECCION RESTRICCION TEMPORAL incluye triggers días de semana
3. **Push y deploy** (~3 min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01 + TC-URGENCIA-03

**Coste total**: ~11 min (compartido → coste marginal TC-03 = 0)

**Forma parte del patrón URGENCIA-IGNORADA.** Si el fix de `e1984b5+cbf9eef` resuelve la causa raíz común, este TC pasará a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.
