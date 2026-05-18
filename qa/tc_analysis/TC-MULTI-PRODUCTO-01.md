---
status: FAIL
tipo: Bug Playbook (multi-producto ignorado)
estimacion: ~25 min (Solución #2 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas **y un centro de mesa** para una boda"* (DOS productos) | — |
| 2 | Orquestador | Clasifica `G5` (Compra directa) → handoff a Compra. Detecta modo_tono=boda | ✅ Correcto |
| 3 | Compra | Extrae solo `producto=ramo de rosas`, **ignora el centro de mesa** | 🔴 Slot-filling parcial: pierde el segundo producto del pedido |
| 4 | Compra | Responde *"Claro, para boda tengo el Ramo de Novia Rosas — L (12 flores, 45€)..."* | 🔴 **Cambio silencioso del pedido.** Solo muestra 1 producto cuando el usuario pidió 2. No menciona el centro de mesa ni explica limitación |

Bug crítico de UX: el cliente piensa que su pedido está siendo procesado completo, pero el agente se ha "comido" el centro de mesa. Es **failure silencioso**, el peor tipo.

### Causa raíz (descompuesta en 3 capas)

1. **Compra (playbook)**: el slot `$producto` es escalar (singular). El playbook no tiene lógica para procesar lista de productos en un solo input.
2. **Orquestador**: tampoco contempla pedidos multi-item — `intencion_inicial` se pasa entera pero Compra solo extrae el primer producto que detecta.
3. **Examples**: no hay ningún Example que muestre cómo manejar pedidos con 2+ productos. El LLM cae al patrón más común (1 producto) por defecto.

## Recomendación

### Solución recomendada: #2 — Compra detecta multi-producto + procesa uno por uno

🟢 **9/10** · ~25 min · Sin dependencias externas

**Por qué**: añadir regla en `CASOS ESPECIALES` para detectar conectores (`y`, `,`, `también`, `además`) entre productos en T1, listar los detectados, y procesar uno por uno preguntando *"Empezamos por el ramo. ¿Qué tamaño?"*. Mantiene UX clara y honesta.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 2 | **Compra: detección de multi-producto + proceso secuencial** | 🟢 9/10 | — | **RECOMENDADO**. Patrón: detectar `y\|,\|también\|además` separando ≥2 productos. Listar los detectados, procesar uno por uno. Patrón validado en otros agentes conversacionales. ~25 min. |
| 4 | **Backend: carrito multi-item** que acepta lista de productos | 🟢 9.5/10 técnico | `petal-sheet-api` + Compra rediseño | Solución arquitectónica correcta a largo plazo. Pero requiere refactor del flujo Compra→Checkout completo. ~6-8h. **Diferir a sprint mayor.** |
| 1 | **Slot `$productos[]`** (array) en Orquestador + Compra | 🟢 8.5/10 | Examples del Orquestador + refactor Compra | Captura todos los productos como info estructurada. Es **prerequisito** de #4 pero por sí solo no resuelve UX. ~1-2h. |
| 5 | **Examples: añadir EX-MULTI-PRODUCTO-01** mostrando comportamiento esperado | 🟢 8/10 complementario | — | Ancla determinística. NO resuelve el bug por sí solo. **Multiplicador** de #2. ~15 min. |
| 3 | **Compra: detectar multi-producto y derivar a humano** | 🟡 6/10 | — | Honesto pero pierde la venta. El cliente espera que el agente sepa hacer pedidos de bodas (uso común). Mejor #2. ~10 min. |
| 6 | **Compra: ignorar segundo producto y avisar** ("Solo puedo procesar uno por conversación") | 🟡 5/10 | — | Es la opción más barata pero pone la limitación encima del cliente. Mala UX. ~10 min. |
| 7 | **Test: relajar regex para aceptar respuesta actual** | 🔴 1/10 | — | Enmascara un bug crítico de UX. NO recomendado bajo ningún concepto. ~5 min. |

### Plan de acción (Solución #2)

1. **Editar `definitions/playbooks/compra.yaml`** → sección `# CASOS ESPECIALES`. Añadir bloque `MULTI-PRODUCTO`:
   - Detectar en T1 conectores entre productos: `y|,|también|además|junto con|más un`.
   - Si match: extraer lista de productos (ej. `["ramo de rosas", "centro de mesa"]`).
   - Responder: *"Perfecto, vamos paso a paso. Empecemos con el ramo de rosas. ¿Qué tamaño prefieres: S, M o L?"*
   - Tras completar el primer producto, ofrecer continuar con el segundo: *"Listo. ¿Seguimos con el centro de mesa?"*

2. **Crear Example `EX-MULTI-PRODUCTO-01`** en `definitions/examples/`:
   - Input: *"quiero un ramo de rosas y un centro de mesa"*
   - Output esperado: reconocimiento de ambos + propuesta de procesar secuencial.

3. **Re-ejecutar QA** con `--runs 3`:
   - TC-MULTI-PRODUCTO-01 debe pasar mencionando `centro` Y `ramo`, o `empezar por`, o `uno`.

**Coste total**: ~25 min (playbook 15 min + example 10 min + QA 5 min).
