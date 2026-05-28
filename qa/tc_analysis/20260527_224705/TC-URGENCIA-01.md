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
| 3 | Compra | Llama PetalDataTool, muestra catálogo ramos rosas | 🔴 Ignora restricción temporal "hoy 18:00" |
| 4 | Compra | Cierra con APERTURA estándar | 🔴 No menciona política mismo-día ni corte 14:00 |

### Causa raíz — evaluación de las 9 capas

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

compra.yaml NO tiene sub-flujo de detección de urgencia temporal. La única mención de "hoy" (línea 484) es ejemplo de pregunta del user, no trigger del agente. Orquestador ZG-5 (línea 254) solo activa cuando user PREGUNTA plazo, no cuando lo MENCIONA dentro de G5.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado exhaustivamente todos los slots de Compra)_

No existe slot `$fecha_entrega` ni `$hora_entrega` en compra.yaml. Información temporal del user se pierde tras T1.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

PetalDataTool responde catálogo correctamente. No es fallo de tool call.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

Sheet contiene toda la información necesaria: `horario_corte_mismo_dia: 14:00`, `envio_madrid_ciudad: Mismo dia (pedidos antes 14:00)`, `tiempo_entrega_estimado: 24h en Madrid y Barcelona, resto de ciudades 48 horas`. El playbook simplemente no las consulta.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones — Capa 1 es la causa identificada)_

Con la Capa 1 como causa clara, no se puede afirmar 🔴 en LLM. Regla binaria: 🔴 solo si todas las demás 🟢. Aquí Capa 1 ES la causa → esta queda 🟡.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

**HISTORIAL DE REGRESIÓN REPETIDA**. 4 ciclos fix→revert detectados: `3f041df`/`a10ab02`/`3e0b2d1`/`e1984b5` revertidos por `aca187c`/`2126c52`/`1f95cae`/`77828fa`. El fix existe y funciona; ha sido revertido intencionalmente (patrón demo break).

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Regex bien calibrado: captura cualquier respuesta razonable que aborde urgencia/plazo. Sin falsos negativos.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Cherry-pick `e1984b5` (bloque DETECCION RESTRICCION TEMPORAL unificada)

🟢 **9/10** · ~11 min · Sin dependencias externas

**Por qué**: el fix YA existe en el historial. Validado empíricamente en sesión 2026-05-28 con 5/5 PASS. Cero diseño nuevo.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque ~8 líneas |
| Profundidad | Medio | Sub-flujo de detección + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | Fix histórico validado, sin afectar otros flujos |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Cherry-pick `e1984b5`** (bloque DETECCION RESTRICCION TEMPORAL unificada) | 🟢 9/10 | — | Fix histórico validado (5/5 PASS empírico), cero diseño nuevo |
| 2 | **Solución #1 + capturar `$fecha_entrega` / `$hora_entrega` como slots y propagar a Checkout** | 🟢 8/10 | — | Más completo, prepara validaciones futuras |
| 3 | **Expandir ZG-5 del Orquestador para detectar mención (no solo pregunta) de plazo** | 🟡 6/10 | — | Acopla responsabilidad de negocio al Orquestador |
| 4 | **Crear tool `validar_plazo_entrega`** en backend petal-sheet-api | 🟡 6/10 | Extender backend | Determinístico al 100%, requiere tocar Cloud Run |
| 5 | **Sub-playbook `Plazo_Task`** invocado por Compra | 🔴 4/10 | — | Sobre-ingeniería para algo que cabe en 8 líneas |

### Plan de acción (Solución #1)

1. **Cherry-pick**: `git cherry-pick e1984b5` desde rama feature
2. **Verificar**: bloque DETECCION RESTRICCION TEMPORAL aparece tras MODO DE OPERACION, antes del PASO 0
3. **Push y deploy** (~3 min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01

**Coste total**: ~5 min cherry-pick + 3 min deploy + 3 min QA = ~11 min reales.

### Parámetros / slots requeridos entre playbooks

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$fecha_entrega` | Compra | Checkout | Condicional | Solo si Solución #2 |
| `$hora_entrega` | Compra | Checkout | Condicional | Idem |
| `$urgencia_detectada` | Compra | Checkout | No | Flag telemetría |
