---
status: FAIL
tipo: Bug Playbook
estimacion: ~5 min (Solución #1 recomendada)
---

# TC-MULTI-PRODUCTO-01 — Pedido multi-item · Checkout recibe ambos productos como parametros formales

**Run:** 20260527_151044 · **Resultado:** 0/3 PASS · **Grupo:** COMPRA-ZG · **Tipo:** EDGE

## T1

Usuario inicia con dos productos en la misma frase (`"quiero un ramo de rosas y un centro de mesa para mi casa"`). El flujo esperado es: ramo (T1-T2) → centro (T2-T3) → **ECO RESUMEN con total combinado 65€** (T3) → confirmación + email (T4) → resumen final en Checkout (T5).

Los 3 runs muestran el **mismo fail estructural en T3**: el agente emite un resumen del pedido SIN total combinado. Posteriormente Checkout (T5) sí calcula y muestra `Total: 65€` correctamente — confirma que el bug está aislado al template del Paso 7 del Playbook `compra`, no a Checkout ni a la captura de slots.

### Turnos vs Problemas detectados

(Run 2, el más limpio — run 1 además tuvo flakiness en catálogo que no es la causa raíz)

| Turno | Usuario | Agente (resumen) | Check | Problema |
|---|---|---|---|---|
| T1 | "quiero un ramo de rosas y un centro de mesa para mi casa" | Pide elegir ramo, ofrece 3 opciones de rosas. | OK `[centro.{0,80}ramo]` | — |
| T2 | "el ramo de rosas morado de 37 euros" | Anota ramo, ofrece 3 centros de mesa (28€/28€/26€). | OK `[morado]` | — |
| T3 | "el centro de tulipanes de 28 euros" | "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0euros) y 1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros). ¿Lo confirmo?" | **FAIL `[65]`** | **Ausencia del total combinado en el ECO RESUMEN.** El agente lista los 2 productos pero no calcula 37+28=65. |
| T4 | "si" | Pide correo electrónico. | OK `[correo]` | — |
| T5 | "jerosan1@gmail.com" | Resumen final con `Total: 65€`. | OK `[65]` | — (Checkout funciona). |

El fail es **consistente en los 3 runs**: el T3 nunca incluye el total. Esto descarta flakiness del LLM como causa principal — es un problema de template.

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada]

`Read definitions/playbooks/compra.yaml` (líneas 601-606, Paso 7 del FLUJO MULTI-PRODUCTO):

```
7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
   Usa el template EXACTO segun modo, sin anadir productos extra:
   - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
   - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros). Lo confirmamos?'
   - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros). Confirmamos?'
```

El template del Paso 7 está **roto a propósito**: solo referencia `$producto` y `$precio_estimado`, omite `$producto_2`, `$precio_2` y el cálculo del total combinado. El LLM sigue el template al pie de la letra y emite un resumen incompleto. El instruction "sin anadir productos extra" refuerza activamente el bug.

El agente en T3 logra **mencionar el segundo producto** ("1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros)") porque tiene el contexto conversacional, pero **no incluye el total** — exactamente lo que el commit `c9ce667` indica que iba a pasar.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks puros, no Flows/Pages/Intents para este flujo.

🟢 3. **Capa Parámetros / Slots** [verificada]

`params` de T4-T5 (run 2) muestran los slots capturados correctamente:

```
producto: "Ramo de Rosas Morado — M"
cantidad: "1"
precio_estimado: "37"
producto_2: "Centro de Mesa Tulipanes Multicolor — S"
cantidad_2: "1"
precio_2: "28"
```

La captura del Paso 6b funciona — los 6 slots multi-producto llegan a Checkout. El bug no es de slot-filling.

🟢 4. **Capa Integración** [verificada] — No hay tool call sospechoso en este TC. `PetalDataTool` se llama en T1 y T2 para listar opciones y devuelve catálogo correcto. Checkout consume los slots y compone el total en T5, evidenciando que la integración con backend está OK.

🟢 5. **Capa Datos** [verificada] — Inventario del Sheet confirma `Ramo de Rosas Morado — M` (37€) y `Centro de Mesa Tulipanes Multicolor — S` (28€). Ambos productos existen, los precios son correctos y la suma 65€ es matemáticamente válida. No hay desajuste con el Sheet.

⚪ 6. **Capa Infraestructura** · N/A — No relacionado con Environments/Versions/Agent Config. El deploy del playbook actual está activo y reproducible en los 3 runs.

🟡 7. **Capa Modelo / LLM** [supuesta] — Hay una mínima señal de flakiness en run 1 (el agente afirmó "no tengo centros de tulipanes de 28 euros" cuando sí los hay). Sin embargo, esto NO es la causa del fail principal: el T3 falla de forma consistente en los 3 runs y el motivo es el template del Paso 7, no decisiones del LLM. Marcado 🟡 por trazabilidad de la anomalía de catálogo en run 1, no como causa raíz.

🔴 8. **Capa Histórico** [verificada]

`git log --oneline -- definitions/playbooks/compra.yaml` muestra el commit del break:

```
c9ce667 DEMO BREAK v2: rompe ECO RESUMEN multi-producto (Paso 7) — solo muestra primer producto
```

Mensaje del commit (verbatim): _"modifico el template del ECO RESUMEN (Paso 7) para que solo muestre $cantidad x $producto, sin la parte de $producto_2 ni el cálculo del total combinado. […] Fix mañana: restaurar el template original con + $cantidad_2 x $producto_2 y total."_

El commit fue introducido el 21-may-2026 como rotura intencional para una demo. **No ha sido revertido**. El fix prometido ("mañana") no se aplicó.

🟢 9. **Capa Test** [verificada] — El check `[65]` en T3 es razonable y bien diseñado: exige que el agente calcule explícitamente el total combinado de un pedido multi-producto, lo cual es comportamiento esperado de un asistente de comercio. El test ha detectado correctamente la regresión introducida por `c9ce667`. Los checks de T4 y T5 también son válidos.

**Resumen visual:** 2 🔴 problema · 5 🟢 ok · 1 🟡 supuesta · 2 ⚪ N/A

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| **Alcance** | Trivial | Un único archivo (`compra.yaml`), una única sección (Paso 7 del FLUJO MULTI-PRODUCTO, 6 líneas). |
| **Profundidad** | Medio | Lógica del Paso 7 — requiere restaurar 3 templates (estandar/solemne/corporativo) + cálculo del total + instrucción explícita. |
| **Riesgo** | Trivial | Afecta solo a TCs de multi-producto. El resto de la suite (compra simple, urgencia, etc.) no se ve afectado. Checkout sigue funcionando — el cliente nunca llega a confirmar un total erróneo en producción porque el resumen final lo corrige. |

**Nivel final: Medio → proponemos 5 soluciones.**

## Recomendación

### Solución recomendada: #1 — Revertir el commit `c9ce667` y restaurar el template original

Es la solución más rápida (~5 min), con el menor riesgo de regresión (el template revertido ya estuvo en producción y funcionaba) y deja el repo limpio del marcador "DEMO BREAK". El propio mensaje del commit lo anuncia: _"Fix mañana: restaurar el template original"_.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Tiempo | Riesgo | Trade-off |
|---|---|---|---|---|---|
| **1** | **Revertir `c9ce667`** (restaurar template con `+ $cantidad_2 x $producto_2 = [total]euros`) | ⭐⭐⭐⭐⭐ | ~5 min | Muy bajo — código previamente validado | Ninguno relevante. Deuda saldada. |
| 2 | Editar manualmente el Paso 7 sin revertir (añadir `+ $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros` a los 3 templates y quitar "sin anadir productos extra") | ⭐⭐⭐⭐ | ~8 min | Bajo — cambio quirúrgico | Más trabajoso que el revert, mismo resultado funcional. Útil si hubiese habido otros cambios sobre `compra.yaml` entre `c9ce667` y HEAD que no quisieras perder. |
| 3 | Mover el cálculo del total exclusivamente a Checkout y eliminar el ECO RESUMEN del Paso 7 de Compra | ⭐⭐ | ~15 min | Medio — afecta a la UX y al contrato del TC | El usuario perdería la validación intermedia del total antes de pasar a Checkout. Hay que actualizar el TC para mover el check `[65]` a T4/T5. Solo justificable si se decide rediseñar el flujo. |
| 4 | Añadir un Example multi-producto con resumen + total esperado | ⭐⭐ | ~10 min | Bajo, pero **no resuelve el bug** | Refuerza el comportamiento mediante few-shot, pero mientras la instrucción del Paso 7 diga "sin anadir productos extra" el LLM seguirá ignorando el Example. Útil como complemento a #1, no como sustituto. |
| 5 | Relajar el check del test (quitar `[65]` del T3) | ⭐ | ~2 min | Alto — anti-patrón | Esconde la regresión en lugar de arreglarla. El total combinado es comportamiento esperado de cualquier asistente de comercio. Documentar la decisión sería obligatorio, pero la decisión correcta es no tomarla. |

### Plan de acción (Solución #1)

1. **Revertir el commit del break:**
   ```bash
   git revert c9ce667 --no-edit
   # O alternativamente, cherry-pick inverso solo del bloque del Paso 7
   ```
2. **Verificar el diff** — solo deben cambiar las líneas 600-606 de `definitions/playbooks/compra.yaml`, restaurando:
   ```
   7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
      Calcula total = $precio_estimado + $precio_2 (entero sin decimales).
      - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) + $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros. Lo confirmo?'
      - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros) + $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros. Lo confirmamos?'
      - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros) + $cantidad_2 x $producto_2 ($precio_2euros) = [total]euros. Confirmamos?'
   ```
3. **PR + merge** → dispara `deploy.yml` que publica el playbook actualizado al agente Petal.
4. **Esperar deploy** (~2 min) y **relanzar TC-MULTI-PRODUCTO-01** con 3 runs. Validar que T3 contiene `= 65euros` (o equivalente).
5. **Anti-regresión:** correr suite completa (29 TCs) para confirmar que no se ha roto ningún otro flujo.

### Parámetros / slots requeridos entre playbooks

El fix no introduce nuevos slots. Los existentes (`$producto`, `$cantidad`, `$precio_estimado`, `$producto_2`, `$cantidad_2`, `$precio_2`) ya se capturan correctamente en el Paso 6 y ya se transfieren a Checkout en el Paso 8. La restauración del template solo cambia el **render** en el turno de eco, no el contrato de datos.
