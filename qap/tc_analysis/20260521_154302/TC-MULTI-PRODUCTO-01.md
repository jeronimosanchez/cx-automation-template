---
status: FAIL
tipo: Bug Playbook
estimacion: ~10 min (Solución #1 recomendada)
---

## TC-MULTI-PRODUCTO-01 — Pedido multi-item: Checkout recibe ambos productos como parámetros formales

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"quiero un ramo de rosas y un centro de mesa para mi casa"* | — |
| 1 | Agente | *"Perfecto, te ayudo con los dos. Empiezo por el ramo de rosas… tenemos: Ramo de Rosas Morado — M (37€), Ramo de Rosas Amarillo — M (25€), Ramo de Rosas Blanco — M (25€). ¿Cuál te encaja?"* | ✅ Reconoce ambos productos y propone secuenciar correctamente |
| 2 | User | *"el ramo de rosas morado de 37 euros"* | — |
| 2 | Agente | *"Anotado, 1 x Ramo de Rosas Morado — M (37€). Ahora el centro de mesa: tenemos: Centro de Mesa Orquídeas Blanco — S (28€), Centro de Mesa Tulipanes Multicolor — S (28€), Centro de Mesa Rosas y Eucalipto Rosa y Verde — S (26€). ¿Cuál te gusta?"* | ✅ Captura primer producto y pasa al segundo correctamente |
| 3 | User | *"el centro de tulipanes de 28 euros"* | — |
| 3 | Agente | *"Tu pedido: 1 x Ramo de Rosas Morado — M (37€) y 1 x Centro de Mesa Tulipanes Multicolor — S (28€). ¿Lo confirmo?"* · params: `producto_2=null, cantidad_2=null, precio_2=null` | 🔴 El agente muestra ambos productos en el texto pero el check espera "65" (total combinado) y NO aparece. El Paso 7 (ECO RESUMEN) fue mutilado por el DEMO BREAK: el template solo suma un producto. Además los params muestran `producto_2=null` — el DEMO BREAK del Paso 6b también eliminó la captura de slots del segundo producto (aunque el LLM los recupera por contexto en T4) |
| 4 | User | *"si"* | — |
| 4 | Agente | *"Perfecto, para completar tu pedido necesito tu correo electrónico."* · params: `cantidad_2=1, producto_2=Centro de Mesa Tulipanes Multicolor — S, precio_2=28` | ✅ El LLM recupera los slots del segundo producto desde contexto conversacional |
| 5 | User | *"jerosan1@gmail.com"* | — |
| 5 | Agente | *"Perfecto Jero, te resumo tu pedido: 1 x Ramo de Rosas Morado — M (37€), 1 x Centro de Mesa Tulipanes Multicolor — S (28€). Total: 65€…"* | ✅ El total 65€ aparece en el resumen final de Checkout — pero el check de T3 ya marcó FAIL |

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

**Capa 1 — Playbook Compra (instrucciones LLM)** 🔴 [verificada]
Causa directa. Commit `c9ce667` (21-may-2026) introdujo un DEMO BREAK intencionado en el Paso 7 (ECO RESUMEN) de `compra.yaml`. El template fue mutilado de:
`'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) + $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros. Lo confirmo?'`
a:
`'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'`
Esto elimina el cálculo del total combinado y la mención del segundo producto en el resumen del Paso 7. El commit documenta explícitamente la intención: "bug visible en T3: el resumen mostrará 37€ solo del ramo, no 65€ del total."

**Capa 2 — Playbook Compra (slots y captura de parámetros)** 🟡 [supuesta — agravante]
El mismo commit `c9ce667` revierte el efecto de `b8f9ee5` (que eliminó la captura de `$producto_2` en el Paso 6b). Sin embargo, los params de T3 muestran `producto_2=null, cantidad_2=null, precio_2=null`, lo que indica que la captura del segundo slot también está incompleta en este punto del flujo. El LLM los recupera en T4 por contexto, pero en T3 —donde se evalúa el check— los parámetros están vacíos.

**Capa 3 — Test / Check** 🟢 [verificada]
El check de T3 busca "65" (total combinado). Es correcto: el comportamiento esperado es que el resumen de confirmación incluya el total de ambos productos. El FAIL refleja un bug real, no un check mal calibrado. Fuente: datos del run, T3 `checks.details: ["FAIL: Agente debía decir [65]"]`.

**Capa 4 — Herramienta / Tool** ⚪ N/A — el fallo es en el template del Playbook, no en ninguna llamada a Tool externa.

**Capa 5 — Sheet / Inventario** ⚪ N/A — el cálculo del total es lógica de plantilla del Playbook, no depende del Sheet. Los precios individuales (37€ y 28€) se capturan correctamente.

**Capa 6 — Orquestador** 🟢 [verificada]
El Orquestador clasifica correctamente como G5 (Compra) y pasa el flujo al Playbook Compra. T1 PASS confirma que el reconocimiento de multi-producto inicial funciona. Fuente: T1 `checks.pass: true`.

**Capa 7 — Dialogflow CX (configuración de agente / flows / pages)** ⚪ N/A — el bug está en las instrucciones LLM del Playbook, no en la configuración de Flows o Pages de CX.

**Capa 8 — Infraestructura / Deploy** ⚪ N/A — el DEMO BREAK fue desplegado intencionadamente. No hay fallo de pipeline.

**Capa 9 — Datos de entrenamiento / Examples** ⚪ N/A — no hay Examples específicos de multi-producto que contradigan el comportamiento. El fallo es de plantilla, no de few-shot.

**Resumen visual:** 1 🔴 · 1 🟢 verificado · 1 🟡 agravante · 6 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|-----------|-------|---------------|
| Alcance | Trivial | 1 archivo afectado: `definitions/playbooks/compra.yaml`, Paso 7 (ECO RESUMEN). El fix es restaurar el template original con el cálculo del total |
| Profundidad | Trivial | Cambio de 1 línea de plantilla de texto. No afecta lógica condicional, slots ni flujos |
| Riesgo de regresión | Trivial | El template original fue validado en PR #94 (`4f7adea`) y pasó la suite completa. Restaurar es revertir a un estado conocido-bueno |

**Nivel final:** Trivial → 3 soluciones evaluadas

---

### Solución recomendada: #1 — Restaurar template ECO RESUMEN multi-producto en Paso 7 de compra.yaml

🟢 **10/10** · ~10 min · Sin dependencias externas

**Por qué**: El DEMO BREAK es explícito y documentado. El fix es restaurar exactamente el template que existía antes del commit `c9ce667`, que fue validado en PR #94. Es una reversión de 1 línea en `compra.yaml` Paso 7. Bajo coste, cero riesgo de regresión (el estado destino es un estado validado). Cubre directamente el check de T3 (total "65" en el ECO RESUMEN).

---

### Soluciones evaluadas (ordenadas DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar template Paso 7**: reescribir la línea del ECO RESUMEN en `compra.yaml` Paso 7 con el template completo multi-producto que incluye `$cantidad_2 x $producto_2 ($precio_2euros)` y el cálculo del total | 🟢 10/10 | — | Reversión a estado conocido-bueno (PR #94). 1 línea, 0 riesgo, cubre el check de T3 directamente |
| 2 | **`git revert c9ce667`**: revertir el commit del DEMO BREAK completo | 🟢 9/10 | Verificar que el revert no pise cambios posteriores (`2126c52`, `a10ab02`) | Más completo que #1 (restaura también el Paso 6b). Riesgo de conflicto con commits intermedios sobre `compra.yaml` — requiere inspección previa del diff |
| 3 | **Recalibrar el check de T3**: eliminar el check que busca "65" en T3 | 🔴 2/10 | — | Esconde el bug. El comportamiento correcto es mostrar el total en el ECO RESUMEN. Esta solución invalida la cobertura del TC |

---

### Plan de acción (Solución #1)

1. **Editar** `definitions/playbooks/compra.yaml`, Paso 7 (ECO RESUMEN) → restaurar el template multi-producto:
   - Modo estándar: `'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) + $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros. Lo confirmo?'`
   - Calcular `total = $precio_estimado + $precio_2` (entero sin decimales)
   - Verificar que el Paso 6b también tiene activa la captura de `$producto_2`, `$cantidad_2`, `$precio_2` (puede estar afectado por el DEMO BREAK `b8f9ee5` si `c9ce667` no lo restauró completamente)
2. **Commit + push** → CI corre `Deploy to Petal CX` + `QA Petal` automáticamente
3. **Verificar** que TC-MULTI-PRODUCTO-01 pasa en T3 (check "65" presente en ECO RESUMEN) y que los params `producto_2`, `cantidad_2`, `precio_2` están poblados en T3

**Coste total**: ~10 min (5 min edición + revisión del Paso 6b + ~2 min deploy CX + validación)
