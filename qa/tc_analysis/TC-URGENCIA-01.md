---
status: FAIL
tipo: Bug Playbook (urgencia ignorada)
estimacion: ~30 min (Solución #5 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"necesito un ramo de rosas **para hoy a las 6**"* | — |
| 2 | Orquestador | Clasifica `G5` (Compra directa) → handoff a Compra | ✅ Correcto |
| 3 | Compra | Extrae slots: `producto=ramo de rosas`, `modo_tono=estandar` | ⚠️ **NO extrae** la urgencia ("hoy a las 6") como slot — no existe `slot=urgencia` o `slot=plazo` |
| 4 | Compra | Responde *"¿De qué color te gustaría el ramo de rosas?"* | 🔴 **Ignora completamente la urgencia.** Pasa directo a slot-filling de producto sin reconocer plazo ni clarificar disponibilidad |

El agente actúa como si el input fuera *"necesito un ramo de rosas"* sin el `"para hoy a las 6"`. El usuario percibe que no le escuchan — riesgo de pedido sin entrega válida + frustración.

### Causa raíz (descompuesta en 3 capas)

1. **Compra (playbook)**: no tiene regla para detectar urgencia temporal. Su PASO 1 (slot-filling) salta directo a preguntar color/tamaño sin considerar si el plazo es viable.
2. **Sin slot de plazo**: no existe `$plazo_solicitado` ni equivalente en `petal_cx_orchestrator.yaml`. La info temporal se pierde en la clasificación.
3. **Catálogo / Backend**: no hay forma de consultar si los productos pueden entregarse "hoy" (no hay endpoint de disponibilidad horaria). La pregunta del usuario tiene una dependencia de infra no resuelta.

## Recomendación

### Solución recomendada: #5 — Detectar urgencia en Compra + handoff humano

🟢 **8.5/10** · ~30 min · Sin dependencias externas

**Por qué**: añade regla en `CASOS ESPECIALES` del playbook Compra para detectar urgencia ("hoy", "ahora", "ya", hora explícita) y derivar al equipo humano antes de slot-filling. Es la respuesta correcta dado que no tenemos endpoint de disponibilidad horaria. Honesto con el usuario.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Backend: endpoint `disponibilidad_horaria`** que dado un producto + hora devuelva si es entregable | 🟢 10/10 técnico | `petal-sheet-api` redeploy + datos reales de logística | Resolución ideal. El agente respondería *"Para hoy a las 6 tenemos disponibles X productos"*. Pero requiere datos de logística que probablemente no tenemos. ~2-3h. |
| 5 | **Compra: añadir `CASO ESPECIAL` para urgencia + handoff a humano** | 🟢 8.5/10 | — | **RECOMENDADO**. Detectar palabras clave (`hoy`, `ahora`, `ya`, hora explícita `\d+`) en T1 → derivar a equipo humano. Honesto con limitación actual. ~30 min implementación. |
| 2 | **Slot `$plazo_solicitado`** en Orquestador + traspasar a Compra | 🟢 7.5/10 | Examples del Orquestador | Captura la urgencia como info estructurada. Luego Compra puede usarla. Pero por sí solo no resuelve el bug — Compra sigue sin saber qué hacer con el plazo. Es **prerequisito** de #1 o #5. ~45 min. |
| 4 | **Compra: añadir mensaje genérico de plazo** ("nuestros pedidos se entregan en 24h") | 🟡 6/10 | Validar tiempos reales | Patch rápido. Pero si el cliente pide "para hoy a las 6", responder "24h" puede ser ambiguo. Mejora la experiencia pero no resuelve el caso edge. ~10 min. |
| 6 | **Examples: añadir EX-URGENCIA-01** mostrando comportamiento esperado | 🟢 7/10 complementario | — | Ancla determinística. NO resuelve por sí solo el bug — necesita #5 o #2 detrás. **Multiplicador**, no sustituto. ~15 min. |
| 3 | **Compra: detectar urgencia y responder con disclaimer** ("no puedo confirmar disponibilidad para hoy") | 🟡 6.5/10 | — | Honesto pero pierde la venta. El usuario se va. Peor UX que derivar a humano. ~15 min. |
| 7 | **Test: relajar regex y aceptar respuesta actual** | 🔴 2/10 | — | Renunciar al objetivo del test. Enmascara un bug real (el agente sigue ignorando urgencia). NO recomendado. ~5 min. |

### Plan de acción (Solución #5)

1. **Editar `definitions/playbooks/compra.yaml`** → sección `# CASOS ESPECIALES`. Añadir bloque `URGENCIA`:
   - Detectar en T1 palabras: `hoy|ahora|ya|urgente|inmediato` o patrón hora `\d+\s*h|para las \d+`.
   - Si match: NO ejecutar slot-filling. Responder: *"Para confirmar disponibilidad inmediata necesito pasarte con un humano del equipo. ¿Te paso ahora con un agente?"*
   - Transition a `Handoff` con `razon_handoff=urgencia_horaria`.

2. **Crear Example `EX-URGENCIA-01`** en `definitions/examples/`:
   - Input: *"necesito un ramo para hoy a las 6"*
   - Output esperado: reconocimiento de urgencia + propuesta de handoff humano.

3. **Re-ejecutar QA** con `--runs 3`:
   - TC-URGENCIA-01 debe pasar mencionando "equipo" o "humano".

**Coste total**: ~30 min (playbook 15 min + example 10 min + QA 5 min).
