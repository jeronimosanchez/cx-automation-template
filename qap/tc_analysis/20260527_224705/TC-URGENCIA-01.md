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
| 2 | Orquestador | Clasifica G5, deriva a Compra | ✅ Correcto |
| 3 | Compra | Llama PetalDataTool, muestra catálogo | 🔴 Ignora restricción temporal "hoy 18:00" |
| 4 | Compra | Cierra con APERTURA estándar | 🔴 No menciona política mismo-día ni corte 14:00 |

### Causa raíz — evaluación de las 9 capas

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

compra.yaml NO tiene sub-flujo DETECCION URGENCIA TEMPORAL. La única mención de "hoy" (línea 484) es ejemplo de pregunta del user. Orquestador ZG-5 (línea 254) solo activa cuando user PREGUNTA plazo, no cuando lo MENCIONA dentro de G5.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente: no existe slot $fecha_entrega ni $hora_entrega documentado)_

No existe slot temporal en compra.yaml. Información temporal del user se pierde tras T1.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

PetalDataTool responde catálogo correctamente. Sin fallo de tool call.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene `horario_corte_mismo_dia: 14:00`, `envio_madrid_ciudad: Mismo dia <14:00`, `tiempo_entrega_estimado: 24h Madrid/Barcelona, 48h resto`. Datos completos. El playbook no los consulta.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones idénticas — Capa 1 es la causa identificada)_

Con Capa 1 como causa clara, regla binaria impide marcar 🔴 en LLM.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

HISTORIAL DE REGRESIÓN REPETIDA. 5+ ciclos fix→revert: `e1984b5`→`77828fa`, `cbf9eef`→`56b5271`, `3f041df`→`aca187c`, `a10ab02`→`2126c52`, `3e0b2d1`→`1f95cae`. Patrón demo break confirmado. El fix existe históricamente y funciona empíricamente.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado, captura cualquier respuesta razonable sobre urgencia/plazo.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Cherry-pick `e1984b5` + refuerzo `cbf9eef`

🟢 **9/10** · ~11 min · Sin dependencias externas

**Por qué**: ambos commits ya existen en el historial. Validados empíricamente en sesión 2026-05-28 con 5/5 PASS en TC-URGENCIA-01. Cero diseño nuevo.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ~8 líneas |
| Profundidad | Medio | Sub-flujo de detección + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | Fix histórico validado |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Cherry-pick `e1984b5` + refuerzo `cbf9eef`** (bloque DETECCION RESTRICCION TEMPORAL unificada + ejemplo inline) | 🟢 9/10 | — | Fix histórico validado 5/5 PASS empírico, cero diseño nuevo |
| 2 | **Solución #1 + capturar `$fecha_entrega`/`$hora_entrega` como slots** y propagar a Checkout | 🟢 8/10 | — | Más completo, prepara validaciones futuras de viabilidad |
| 3 | **Expandir ZG-5 del Orquestador para detectar mención (no solo pregunta) de plazo** | 🟡 6/10 | — | Acopla responsabilidad de negocio al Orquestador |
| 4 | **Tool `validar_plazo_entrega`** en petal-sheet-api | 🟡 6/10 | Extender backend | Determinístico 100%, requiere tocar Cloud Run |
| 5 | **Sub-playbook `Plazo_Task`** invocado por Compra | 🔴 4/10 | — | Sobre-ingeniería para algo que cabe en 8 líneas |

### Plan de acción (Solución #1)

1. **Cherry-pick**: `git cherry-pick e1984b5 cbf9eef` desde rama feature
2. **Verificar**: bloque DETECCION RESTRICCION TEMPORAL aparece tras MODO DE OPERACION, antes del PASO 0
3. **Push y deploy** (~3 min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01

**Coste total**: ~5 min cherry-pick + 3 min deploy + 3 min QA = ~11 min.

**Forma parte del patrón URGENCIA-IGNORADA.** Si el fix de `e1984b5+cbf9eef` resuelve la causa raíz común, TC-URGENCIA-03 pasará a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.
