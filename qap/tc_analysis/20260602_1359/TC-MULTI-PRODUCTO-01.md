---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

# TC-MULTI-PRODUCTO-01 — Pedido multi-item — ECO RESUMEN muestra total antes de confirmar

**Grupo:** COMPRA-INV | **Tipo:** EDGE | **Run:** 2026-05-27 19:13 | **Resultado:** FAIL (0/3)
**Versiones:** orquestador v65 · compra v39 · checkout v33 · registro v7 (Task) · script v23

---

## T3

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas y un centro de mesa para mi casa"* | — |
| 2 | Compra | Reconoce ambos productos, ofrece catálogo de ramos de rosas y anuncia que luego ven el centro de mesa | ✅ Correcto — Paso 5 del CASO multi-producto funciona; captura `producto = "ramo de rosas, centro de mesa"`. Check `[centro.{0,80}ramo]` PASS |
| 3 | User | *"el ramo de rosas morado de 37 euros"* | — |
| 4 | Compra | "Anotado, 1 x Ramo de Rosas Morado — M (37.0euros). Ahora el centro de mesa:" + catálogo de centros (subset varía entre runs) | ✅ Correcto — ECO de confirmación del Paso 5c + salto al [tipo_2]. Check `[morado]` PASS |
| 5 | User | *"el centro de tulipanes de 28 euros"* | — |
| 6 | Compra | **Runs 1&2:** "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0euros) **y** 1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros). ¿Lo confirmo?" — lista ambos productos pero **omite el total 65€** · **Run 3:** "No tengo un centro de tulipanes de 28 euros" — el subset de T2 fue Rosas y Eucalipto, no Tulipanes | 🔴 ECO RESUMEN sin total. Check `FAIL: Agente debía decir [65]` |

**Dos modos de fallo distintos:**
- **Runs 1 & 2 (causa principal — determinista):** El agente llega al ECO RESUMEN del Paso 7 con ambos productos en contexto. El template del Paso 7 es mono-producto (`compra.yaml:603`) y la instrucción "sin anadir productos extra" (`compra.yaml:602`) prohíbe explícitamente incluir el segundo ítem. El LLM viola parcialmente la prohibición (improvisa el listado de ambos productos) pero, al no existir `$precio_2` ni cálculo de total en el template, no suma 37 + 28 = 65. El ECO queda incompleto: ambos productos visibles, total ausente.
- **Run 3 (causa secundaria — coyuntural):** En T2 el LLM mostró un subset distinto de centros de mesa (Rosas y Eucalipto S/M) en lugar de incluir Tulipanes. El usuario pidió "tulipanes de 28 euros" — producto no ofrecido en esa conversación — y el agente respondió correctamente que no lo tiene. El check `[65]` falla por arrastre, no por el bug del ECO. Cubierto por la épica `pendiente_refactor_compra` (variabilidad de catálogo), no es lo que mide este test.

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1]

🔴 1. **Capa Comportamiento** [verificada] · `Read definitions/playbooks/compra.yaml líneas 601-607`

El Paso 7 ECO RESUMEN OBLIGATORIO define:
```
7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
   Usa el template EXACTO segun modo, sin anadir productos extra:
   - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
   - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros). Lo confirmamos?'
   - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros). Confirmamos?'
```
El template es **mono-producto en los tres modos**: solo referencia `$producto` y `$precio_estimado`. No existe variante multi-producto con `$producto_2`, `$precio_2` ni el cálculo del total. Además, la coletilla "sin anadir productos extra" instruye activamente al LLM a NO incluir el segundo ítem. Esto es una **contradicción interna del propio playbook**: el Paso 6b (`compra.yaml:600`) captura `$producto_2` y `$precio_2`, y el Paso 8 (`compra.yaml:607`) los transfiere a Checkout — pero el Paso 7 los ignora y prohíbe mostrarlos. El usuario, por tanto, nunca ve el total antes de confirmar. Causa directa del FAIL determinista en runs 1&2.

La misma capa explica el fallo secundario de run 3: el Paso 5d (`compra.yaml:597`) dice "Muestra hasta 3 opciones" sin anclaje a qué subset mostrar, generando selección no-determinista del catálogo de centros de mesa.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks exclusivamente; no hay Flows, Pages ni Intents en este flujo. `matchType=PLAYBOOK` en los 3 runs.

🟢 3. **Capa Parámetros / Slots** [verificada] · `Read definitions/playbooks/compra.yaml líneas 158-171, 600, 607`

`producto_2` (línea 161) y `precio_2` (línea 171) están declarados como parámetros del playbook. El Paso 6b los captura ("CAPTURA OBLIGATORIA: $producto_2 = nombre_exacto_elegido ... $precio_2 = precio_unitario x $cantidad_2") y el Paso 8 los transfiere a Checkout. El paso de slots NO es el problema: el agente dispone de ambos productos (lo demuestra el texto de runs 1&2, que sí los lista). El fallo es que el template del Paso 7 no los usa para calcular el total. La capa de slots funciona; la de comportamiento no la aprovecha.

🟢 4. **Capa Integración** [verificada] · `JSON T1-T2 runs 1&2`

PetalDataTool devuelve inventario válido en T1 (ramos de rosas) y T2 (centros de mesa). Los productos mostrados existen en catálogo (Ramo de Rosas Morado 37€, Centro de Mesa Tulipanes Multicolor 28€ confirmados en runs 1&2). Sin errores de backend ni respuestas "Lo siento, algo no ha funcionado". No es causa del fallo.

🟢 5. **Capa Datos** [verificada] · `JSON T1-T2 runs 1&2`

El producto "Centro de Mesa Tulipanes Multicolor — S (28€)" existe en catálogo (aparece en T2 de runs 1&2). La suma esperada por el test (37 + 28 = 65) es aritméticamente correcta sobre datos reales del Sheet. Run 3 muestra un subset diferente (Rosas y Eucalipto S/M) — coherente con un catálogo de centros de mesa con más de 3 SKUs y un LLM que elige el subset sin instrucción de prioridad. Los datos son correctos; la presentación no.

🟢 6. **Capa Infraestructura** [verificada] · `metadata del JSON (orquestador v65, compra v39, checkout v33, registro v7)`

Las versiones del agente son coherentes con el estado del repo. El deploy es correcto y la versión activa es la esperada. No introduce regresión.

🟡 7. **Capa Modelo / LLM** [supuesta] · _(no verificado: requeriría múltiples runs con debug de tool calls para aislar el comportamiento del LLM frente al de la instrucción)_

Run 3 muestra comportamiento no-determinista: el LLM seleccionó un subset de centros de mesa distinto al de runs 1&2 ante una query de usuario equivalente. Es un síntoma conocido cuando el catálogo tiene más productos que el límite "hasta 3" sin instrucción de prioridad. No se marca 🔴 porque la Capa Comportamiento no está en 🟢 y run 3 es solo 1 de 3 ejecuciones. La regla binaria del skill exige las 8 capas restantes en 🟢 [verificada] para marcar 🔴 — no se cumple.

🔴 8. **Capa Histórico** [verificada] · `git log --oneline -n 25 -- definitions/playbooks/compra.yaml`

```
a957a04  Revert "feat(compra): DETECCION RESTRICCION TEMPORAL..."  (revierte eb928a2)
eb928a2  TEMP fix(compra): ECO RESUMEN multi-producto incluye 2 productos + total
...
c9ce667  DEMO BREAK v2: rompe ECO RESUMEN multi-producto (Paso 7) — solo muestra primer producto
b8f9ee5  DEMO BREAK: quita captura de $producto_2 en compra.yaml Paso 6b
4f7adea  fix(multi-producto): slots explícitos + ECO resumen + Checkout condicional (#94)
5b05396  fix(playbook-compra): CASO ESPECIAL multi-producto (TC-MULTI-PRODUCTO-01) (#93)
```
El fix correcto **ya existió**: `eb928a2` ("ECO RESUMEN multi-producto incluye 2 productos + total") resolvía exactamente este TC. Fue **revertido por `a957a04`** — patrón "demo break": el ECO de 2 productos + total se quita intencionadamente para reproducir el bug en demos. El estado actual del archivo (template mono-producto, línea 603) es el resultado de ese revert sumado al DEMO BREAK previo `c9ce667`. La regresión es intencionada y reversible; el fix de referencia es recuperable con `git show eb928a2:definitions/playbooks/compra.yaml`.

🟢 9. **Capa Test** [verificada] · `JSON T3 (check "65")`

El check `[65]` es correcto: verifica que el total (37 + 28 = 65€) aparezca en el ECO RESUMEN antes de la confirmación. Es una condición de negocio válida — el usuario debe ver el precio total antes de confirmar. El FAIL es determinista en runs 1&2 (template mono-producto) y coyuntural en run 3 (subset de catálogo). La calibración del test es correcta; no es un falso negativo.

**Resumen visual:** 2 🔴 problema · 5 🟢 ok · 1 🟡 supuesta · 1 ⚪ N/A

---

## Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), una sección (Paso 7, líneas 601-605) |
| Profundidad | Medio | Cambiar el template del ECO RESUMEN a variante condicional multi-producto + cálculo de total; toca lógica de presentación, no solo texto |
| Riesgo de regresión | Medio | Afecta todos los flujos multi-producto; debe preservar el comportamiento mono-producto para no romper TCs de compra de un solo ítem |

**Nivel final:** Medio → 5 soluciones

---

## Recomendación

### Solución recomendada: #1 — Restaurar template multi-producto + total en Paso 7

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: El fix correcto ya existió y está versionado (`eb928a2`). Reintroducir la variante condicional multi-producto en el Paso 7 (con `$producto_2`, `$precio_2` y total) y eliminar la coletilla "sin anadir productos extra" cierra la contradicción interna del playbook con el mínimo alcance. Conserva la variante mono-producto intacta. Bajo riesgo, base recuperable de `git show eb928a2`.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar template multi-producto + total en Paso 7** (base: `eb928a2`) | 🟢 9/10 | — | Cirugía precisa: solo el template del ECO RESUMEN. Reintroduce un fix ya validado, revertido por demo break. Resuelve la contradicción Paso 6b/8 vs Paso 7. Bajo riesgo en mono-producto. |
| 2 | **`git revert a957a04`** (re-aplica `eb928a2`) | 🟡 7/10 | — | Más rápido (~5 min) pero revierte el commit completo; conviene revisar el diff de `eb928a2` por si arrastra cambios temporales (RESTRICCION TEMPORAL) no deseados antes de aplicarlo. |
| 3 | **Añadir regla global de cálculo de total al cierre de Compra** | 🟡 6/10 | — | Más resiliente a futuros cambios de template, pero las reglas globales pueden interferir con otros flujos (mono-producto, Checkout). No aborda el subset de catálogo del run 3. |
| 4 | **Anclar el subset de catálogo en Paso 5d** | 🔴 4/10 | — | Aborda el run 3 secundario pero añade rigidez al playbook. Forzar siempre Tulipanes contradice el catálogo dinámico. ROI bajo — no es lo que mide el test. |
| 5 | **Hacer el test resiliente al subset de catálogo (T2)** | 🔴 3/10 | — | Solución lado test, no arregla el bug del agente. Puede enmascarar fallos reales del ECO RESUMEN. Solo útil si el run 3 pattern persiste tras el fix principal. |

### Plan de acción (Solución #1)

1. **Abrir `definitions/playbooks/compra.yaml`**: localizar Paso 7 ECO RESUMEN (líneas 601-605).
2. **Sustituir el template mono-producto** por una variante condicional. Referencia recuperable: `git show eb928a2:definitions/playbooks/compra.yaml`. Eliminar "sin anadir productos extra". Forma orientativa:
   ```
   7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
      - Si $producto_2 existe:
        Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [$precio_estimado + $precio_2]euros. Lo confirmo?'
      - Si no:
        Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
   ```
   (replicar las variantes Solemne y Corporativo con el mismo patrón condicional).
3. **Commit**: `fix(compra): restaura ECO RESUMEN multi-producto + total en Paso 7 (reaplica eb928a2)`
4. **PR + merge** → pipeline CI/CD → rerun QA `--runs 3`.
5. **Verificar**: T3 runs 1&2 muestran "65" en el ECO RESUMEN. Si run 3 sigue fallando por subset de catálogo, evaluar Solución #4/#5 por separado (deuda `pendiente_refactor_compra`).

**Coste total**: ~15 min (edición ~5 min + ciclo PR/merge/deploy ~10 min).

### Parámetros / slots requeridos entre playbooks

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$producto` | Compra | Checkout | Sí | Primer producto — siempre capturado (Paso 5b) |
| `$precio_estimado` | Compra | Checkout | Sí | Precio primer producto |
| `$cantidad` | Compra | Checkout | Sí | Cantidad primer producto |
| `$producto_2` | Compra | Checkout | Condicional | Solo multi-producto — capturado en Paso 6b, declarado línea 161 |
| `$precio_2` | Compra | Checkout | Condicional | Precio segundo producto — capturado en Paso 6b, **no usado en template Paso 7** (causa del bug) |
| `$cantidad_2` | Compra | Checkout | Condicional | Solo multi-producto |

---

## Notas adicionales

**Patrón demo break**: el fix correcto (`eb928a2`) fue revertido intencionadamente (`a957a04`) para reproducir el bug en demos. No reaplicar hasta confirmar que la demo concluyó o que no se necesita el estado roto. La reversibilidad está garantizada vía git.

**Sobre run 3**: incluso tras el fix del ECO, la selección no-determinista del catálogo en T2 (Paso 5d "hasta 3 opciones" sin anclaje) puede producir runs donde no aparezcan Tulipanes. Es un síntoma distinto, cubierto por la épica `pendiente_refactor_compra`. No es lo que mide TC-MULTI-PRODUCTO-01 — no escalar el fix para resolverlo aquí.
