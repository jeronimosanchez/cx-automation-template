---
status: INESTABLE
tipo: Bug Playbook
estimacion: ~25 min (Solución #1 recomendada)
---

## TC-URGENCIA-03 — Entrega urgente: plazo viernes, agente confirma viabilidad y política de envío

### Turnos vs Problemas detectados

| # | Run | Quién | Acción / Texto | Problema detectado |
|---|-----|-------|---------------|--------------------|
| 1 | 1,3 | User | *"lo necesito para este viernes"* | — |
| 2 | 1,3 | Orquestador | "Perfecto, lo tendré en cuenta. ¿Es para alguna ocasión especial o tienes algún tipo de flor en mente?" | 🔴 Orquestador responde directamente en lugar de transferir a Compra. No menciona plazo de 24h. |
| 1 | 2 | User | *"lo necesito para este viernes"* | — |
| 2 | 2 | Orquestador | Transfiere a Compra con `grupo_intent=G3`, `ocasion_detectada=Corporativo`, `modo_tono=corporativo` | ✅ Correcto |
| 3 | 2 | Compra | "Sin problema para el viernes, el plazo es 24h en Madrid y Barcelona, 48h resto de ciudades. ¿Para qué ocasión lo necesitas?" | ✅ Bloque DETECCION RESTRICCION TEMPORAL ejecutado correctamente |

**Patrón observado:** En runs 1 y 3, el trace muestra solo el playbook Orquestador (`00000000-...`) sin `playbookTransition` a Compra. El Orquestador genera la pregunta de orientación genérica del bloque AMBIGUO. En el run 2 (PASS), el Orquestador clasificó como G3 y transfirió a Compra, donde el bloque DETECCION RESTRICCION TEMPORAL respondió correctamente.

---

### Causa raíz — evaluación de las 9 capas del sistema

🔴 **1. Capa Comportamiento** [verificada] · `Read definitions/playbooks/petal_cx_orchestrator.yaml`

El bloque CASO AMBIGUO del Orquestador (línea 190) lista `'necesito flores para manana'` y `'urgente'` como casos ambiguos con respuesta de orientación directa en el Orquestador. El utterance `"lo necesito para este viernes"` matchea ese patrón estructuralmente (marcador temporal sin producto concreto), por lo que el LLM lo trata como AMBIGUO en 2/3 runs y genera:

> *"¿Es para alguna ocasión especial o tienes algún tipo de flor en mente?"*

Sin embargo, este utterance debería clasificarse como G3 (recomendación sin producto) y transferirse a Compra, donde el bloque `⛔ DETECCION RESTRICCION TEMPORAL ⛔` (compra.yaml línea 391-405) tiene el ejemplo exacto: `"lo necesito para este viernes"` → `"Sin problema para el viernes, el plazo es 24h en Madrid y Barcelona..."`.

La raíz está en el Orquestador: la frontera entre AMBIGUO y G3 no está suficientemente definida para utterances con SOLO restricción temporal y sin producto.

⚪ **2. Capa Routing** · N/A — Petal usa playbooks, no Flows/Pages.

🟢 **3. Capa Parámetros / Slots** [verificada] · `Read definitions/playbooks/petal_cx_orchestrator.yaml`

En el run 2 (PASS), la transferencia a Compra pasó correctamente `intencion_inicial`, `grupo_intent=G3`, `ocasion_detectada`, `modo_tono`. El slot passing no es la causa del FAIL — el problema es anterior (no se llega a la transferencia en 2/3 runs).

🟢 **4. Capa Integración** [verificada] · trace TC JSON run 2

En el run 2, el trace no muestra tool calls ni errores de backend. No hay invocación de PetalDataTool en ningún run. La integración no es causa.

🟡 **5. Capa Datos** [supuesta] · _(no verificado: endpoint /exec?recurso=business devolvió error 403 al ejecutar jq. Los plazos `24h Madrid/Barcelona, 48h resto` que aparecen en la respuesta del run 2 son coherentes con la instrucción de compra.yaml. Asumo valores correctos en el Sheet, pero sin confirmación directa.)_

🟢 **6. Capa Infraestructura** [verificada] · `git log --oneline -n 20 -- definitions/playbooks/petal_cx_orchestrator.yaml definitions/playbooks/compra.yaml`

El commit `76cbe39 fix(compra): recupera bloque DETECCION RESTRICCION TEMPORAL de 3bec490 (TC-URGENCIA-01 + TC-URGENCIA-03)` (PR #116) está en producción. El deploy es correcto — el run 2 confirma que el bloque de Compra está activo. No hay regresión de infraestructura.

🟡 **7. Capa Modelo / LLM** [supuesta] · _(el no-determinismo es evidente: mismo utterance, 3 resultados distintos, 2 FAIL / 1 PASS. Sin embargo, la causa principal está en la Capa Comportamiento — la ambigüedad de la instrucción del Orquestador crea las condiciones para la variabilidad. No es LLM puro sin causa playbook: es LLM explotando una instrucción ambigua. Marcado 🟡 porque la Capa Comportamiento es 🔴 y no se puede separar.)_

🟢 **8. Capa Histórico** [verificada] · `git log --oneline -n 20 -- definitions/playbooks/compra.yaml`

El historial muestra un ciclo extenso de fixes/reverts alrededor de DETECCION RESTRICCION TEMPORAL. El commit activo `76cbe39` es el que restauró el bloque correcto tras varios reverts. La fix de Compra está bien. La raíz actual es en el Orquestador, que no tiene el equivalente refinamiento post-PR #116.

🟢 **9. Capa Test** [verificada] · trace TC JSON

El check `[24h|24 horas|plazo|días|dias|llega|tiempo.{0,20}entrega|entrega.{0,20}tiempo]` es correcto y preciso. En el run 2 matcheó `"24h"`. El test está bien calibrado.

**Resumen visual:** 1 🔴 problema · 4 🟢 ok · 2 🟡 supuesta · 1 ⚪ N/A

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (`petal_cx_orchestrator.yaml`), sección de clasificación G3/AMBIGUO |
| Profundidad | Medio | Añadir regla de clasificación + ejemplo explícito. Afecta lógica de routing del Orquestador |
| Riesgo de regresión | Medio | El Orquestador clasifica múltiples TCs. Cambio en AMBIGUO puede impactar TC-URGENCIA-01 y otros |

**Nivel final: Medio → 5 soluciones**

---

### Solución recomendada: #1 — Añadir regla G3 explícita para restricción temporal sin producto

🟢 **9/10** · ~25 min · Sin dependencias externas

**Por qué**: Ataca la raíz directa. La instrucción del Orquestador no distingue entre utterance ambiguo genuino (sin temporal, sin acción) y utterance de restricción temporal sin producto (con temporal + acción implícita de compra). El bloque DETECCION RESTRICCION TEMPORAL de Compra ya tiene el caso cubierto — solo necesita recibir el utterance.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Añadir regla G3 explícita: marcador temporal sin producto → siempre G3, nunca AMBIGUO** | 🟢 9/10 | — | Ataca la raíz. Sin riesgo de romper TC-URGENCIA-01 (que ya transfiere correctamente). Coherente con bloque DETECCION de Compra. |
| 2 | **Quitar `necesito flores para manana` del bloque AMBIGUO** | 🟡 6/10 | — | Reduce el espacio de confusión. Pero `necesito flores para manana` SÍ tiene `flores` (producto) → ya debería ser G3. Quitar este ejemplo del AMBIGUO es correcto como limpieza adicional pero no es suficiente por sí solo. |
| 3 | **Modificar respuesta AMBIGUO: si hay marcador temporal, incluir plazo antes de preguntar orientación** | 🟡 6/10 | — | Pasaría el check sin cambiar el routing. Pero el Orquestador respondería el plazo desde su propia instrucción, duplicando responsabilidad con Compra. Solución de parche, no de raíz. |
| 4 | **Añadir al check del TC la respuesta de orientación del Orquestador** | 🔴 3/10 | — | Falsea el test. El comportamiento esperado ES que Compra responda con el plazo. Relajar el check oculta el bug. |
| 5 | **Añadir anti-regresión en Compra: si $intencion_inicial llega vacía, preguntar al usuario** | 🔴 2/10 | — | No resuelve el problema. El bug ocurre antes de que Compra sea invocada. |

### Plan de acción (Solución #1)

1. **Añadir regla en G3 del Orquestador** (`definitions/playbooks/petal_cx_orchestrator.yaml`, bloque G3 ~línea 279):

   Añadir justo antes de la línea `⛔ APLICA AQUI cuando...`:
   ```
   ⛔ RESTRICCION TEMPORAL SIN PRODUCTO: si el utterance tiene SOLO marcador temporal ('para hoy', 'para este viernes', 'para mañana', 'necesito algo para el lunes', etc.) sin producto concreto ni tipo — es G3, NO AMBIGUO. Transferir directamente a Compra con $intencion_inicial. Compra maneja la política de envío.
   Ejemplos G3 con temporal:
   - 'lo necesito para este viernes' → G3 (sin producto, sin tipo)
   - 'necesito algo para mañana' → G3 (sin producto, sin tipo)
   - 'quiero algo para hoy' → G3 (sin producto, sin tipo)
   ```

2. **Limpiar el bloque AMBIGUO** (`definitions/playbooks/petal_cx_orchestrator.yaml`, ~línea 190):

   Quitar `'necesito flores para manana'` de la lista de ejemplos AMBIGUOS — este utterance tiene `flores` (palabra de producto de la lista REGLA ANTI-SALUDO) y debería clasificarse como G3 directamente.

3. **Re-ejecutar QA** con `--runs 3` sobre TC-URGENCIA-03 (y TC-URGENCIA-01 como anti-regresión).
