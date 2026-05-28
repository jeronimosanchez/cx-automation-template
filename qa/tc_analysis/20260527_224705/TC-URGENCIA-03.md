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
| 2 | Orquestador | Clasifica G3 (exploración, modo corporativo) | ✅ Correcto |
| 3 | Compra | Acknowledge "para este viernes" pero pregunta tipo/presupuesto | 🔴 No menciona plazo ni viabilidad |
| 4 | Compra | Cierra con apertura estándar exploratoria | 🔴 Pierde oportunidad de informar política proactivamente |

### Causa raíz — evaluación de las 9 capas

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

Mismo bug que TC-URGENCIA-01. compra.yaml NO tiene sub-flujo URGENCIA. El agente reconoce el día ("De acuerdo, para este viernes") pero no informa proactivamente del plazo. La línea 254 del orquestador (ZG-5) solo activa cuando user PREGUNTA plazo, no cuando lo MENCIONA dentro de su intención.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente todos los slots)_

No existe slot `$fecha_entrega`; el día "viernes" se pierde tras el ACK inicial.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

Sin tool call problemática. Agente respondió texto válido, solo falta contenido requerido.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene `tiempo_entrega_estimado="24h en Madrid y Barcelona, resto de ciudades 48 horas"` — EXACTAMENTE el contenido que el regex del test espera. La política existe, solo falta exponerla.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones — Capa 1 es la causa)_

Con la Capa 1 como causa clara, no se puede marcar 🔴 LLM. Regla binaria: 🔴 solo si todas las demás 🟢. Aquí queda 🟡.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

HISTORIAL DE REGRESIÓN COMPARTIDA con TC-URGENCIA-01. Los commits `3f041df`/`a10ab02`/`3e0b2d1`/`e1984b5` cubrían AMBOS casos (hora explícita + día relativo). Revertidos en `aca187c`/`2126c52`/`1f95cae`/`77828fa`. Patrón demo break.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado para confirmación de plazo. Sin falsos negativos detectables.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Cherry-pick `e1984b5` (COMPARTIDO con TC-URGENCIA-01)

🟢 **9/10** · ~0 min marginal · Sin dependencias externas

**Por qué**: el commit `e1984b5` cubre AMBOS casos (hora explícita + día relativo). Un único fix cierra TC-01 y TC-03 simultáneamente. Validado empíricamente en sesión 2026-05-28 (TC-03 pasó 3/3 con refuerzo).

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
| 1 | **Cherry-pick `e1984b5`** — cierra TC-01 + TC-03 simultáneamente | 🟢 9/10 | — | Fix histórico validado, ROI doble |
| 2 | **Solución #1 + slot `$fecha_entrega` propagado a Checkout** | 🟢 8/10 | — | Habilita validaciones futuras de viabilidad |
| 3 | **Expandir ZG-5 del Orquestador para detectar mención (no solo pregunta) de plazo** | 🟡 6/10 | — | Acopla responsabilidad negocio al Orquestador |
| 4 | **Tool `validar_plazo_entrega`** en petal-sheet-api | 🟡 5/10 | Extender backend | Determinístico, requiere tocar Cloud Run |
| 5 | **Sub-playbook `Plazo_Task`** invocado por Compra | 🔴 3/10 | — | Sobre-ingeniería; añade latencia de hop |

### Plan de acción (Solución #1, COMPARTIDO con TC-URGENCIA-01)

1. **Cherry-pick**: `git cherry-pick e1984b5`
2. **Verificar formato**: bloque DETECCION RESTRICCION TEMPORAL incluye triggers para días de semana
3. **Push y deploy** (~3 min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01 + TC-URGENCIA-03

**Coste total**: ~11 min (compartido con TC-URGENCIA-01 → coste marginal de TC-03 = 0)

### Parámetros / slots requeridos

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$fecha_entrega` | Compra | Checkout | Condicional | Solo Sol #2 |
| `$urgencia_detectada` | Compra | Checkout | No | Flag telemetría |
