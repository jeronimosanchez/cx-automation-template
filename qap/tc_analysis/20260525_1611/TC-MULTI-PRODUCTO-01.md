---
status: FAIL
tipo: Bug Playbook
estimacion: ~10 min (Solución #1 recomendada)
---

# TC-MULTI-PRODUCTO-01 — Pedido multi-item — Checkout recibe ambos productos como parámetros formales

**Grupo:** COMPRA-ZG | **Run:** 2026-05-25 16:11 | **Resultado:** FAIL (0/1)
**Versiones:** orquestador v65 · compra v39 · checkout v33 · registro v7

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente (resumen) | Check | Veredicto |
|-------|---------|-----------------|-------|-----------|
| T1 | "quiero un ramo de rosas y un centro de mesa para mi casa" | Ofrece catálogo de ramos de rosas; menciona que luego verán el centro de mesa | OK: Agente dijo [centro.{0,80}ramo] | PASS |
| T2 | "el ramo de rosas morado de 37 euros" | Anota Ramo de Rosas Morado — M (37€) y ofrece catálogo de centros de mesa | OK: Agente dijo [morado] | PASS |
| T3 | "el centro de tulipanes de 28 euros" | "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0euros) y 1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros). ¿Lo confirmo?" — **NO incluye el total 65€** | FAIL: Agente debía decir [65] | **FAIL** |
| T4 | "si" | Solicita correo electrónico para completar el pedido | OK: Agente dijo [correo] | PASS |
| T5 | "jerosan1@gmail.com" | Resumen final con ambos productos y "Total: 65€" | OK: Agente dijo [65] | PASS |

**Fallo único en T3:** el ECO RESUMEN del Paso 7 de compra.yaml no calcula ni muestra el total cuando hay dos productos. El checkout (T5) sí lo muestra correctamente.

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Síntoma observable 🔴 [CONFIRMADO]

En T3, el agente presenta el resumen multi-producto con ambos ítems y precios individuales pero omite el total (65€). El check espera la cadena "65" y no la encuentra. En T5 (checkout), el total sí aparece correctamente.

### Capa 2 — Turno y parámetros implicados 🔴 [CONFIRMADO]

- **Turno fallido:** T3
- **Params disponibles en T3:** `producto` = "ramo de rosas y centro de mesa", `precio_estimado` implícito 37€, `precio_2` implícito 28€ — aún no capturados formalmente como slots independientes
- **Params en T4 (post-confirmación):** `precio_2=28`, `precio_estimado=37`, `producto_2=Centro de Mesa Tulipanes Multicolor — S`, `producto=Ramo de Rosas Morado — M`, `cantidad=1`, `cantidad_2=1`
- El agente construye el resumen correcto en texto libre pero no calcula la suma

### Capa 3 — Lógica del playbook 🔴 [CONFIRMADO]

El Paso 7 ECO RESUMEN de `compra.yaml` define el template como:

```
Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
```

Este template es **mono-producto**. No existe variante multi-producto que incluya `$producto_2`, `$precio_2` ni el cálculo del total. El commit `c9ce667` ("DEMO BREAK v2: rompe ECO RESUMEN multi-producto") eliminó intencionalmente esta variante para una demo. El agente improvisa el listado de ambos productos pero, sin instrucción explícita de calcular el total, no lo hace.

### Capa 4 — Flujo de slots Compra → Checkout 🟡 [RELEVANTE]

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| $producto | Compra | Checkout | Sí | Primer producto |
| $precio_estimado | Compra | Checkout | Sí | Precio primer producto |
| $producto_2 | Compra | Checkout | Condicional | Solo en multi-producto |
| $precio_2 | Compra | Checkout | Condicional | Solo en multi-producto |
| $cantidad | Compra | Checkout | Sí | |
| $cantidad_2 | Compra | Checkout | Condicional | Solo en multi-producto |

Los slots `$producto_2`, `$precio_2` y `$cantidad_2` se capturan correctamente (confirmado en T4), por lo que el flujo de parámetros hacia Checkout funciona. El problema es exclusivamente la instrucción del ECO RESUMEN antes de la confirmación.

### Capa 5 — Historial de commits 🔴 [CONFIRMADO]

```
c9ce667  DEMO BREAK v2: rompe ECO RESUMEN multi-producto (Paso 7) — solo muestra primer producto
b8f9ee5  DEMO BREAK: quita captura de $producto_2 en compra.yaml Paso 6b
4f7adea  fix(multi-producto): slots explícitos + ECO resumen + Checkout condicional (#94)
```

La secuencia es clara:
1. El commit `4f7adea` introdujo la solución completa multi-producto (slots + ECO resumen + Checkout condicional).
2. El commit `b8f9ee5` rompió la captura de `$producto_2` para una demo.
3. El commit `c9ce667` rompió adicionalmente el ECO RESUMEN multi-producto para la misma demo.
4. El commit `2126c52` (revert de detección urgencia) no guarda relación con este bug.

El estado actual es resultado de dos DEMO BREAKs deliberados que no han sido revertidos.

### Capa 6 — Estado del inventario / Sheet ✅ [OK]

SHEET_OK. Los precios (37€, 28€, total 65€) y los nombres de producto son coherentes con el catálogo. No hay incoherencia de datos que contribuya al fallo.

### Capa 7 — Coherencia entre turnos 🟡 [PARCIAL]

El agente muestra en T3 ambos productos con precios individuales (comportamiento correcto a nivel de listado) pero no suma. En T5 el checkout sí calcula y muestra el total. Hay coherencia de datos entre turnos pero incoherencia de presentación en T3 vs T5 — el usuario ve el precio total solo después de confirmar, no antes.

### Capa 8 — Impacto en experiencia de usuario 🟡 [MEDIO]

El usuario confirma ("sí") sin haber visto el precio total explícito. Aunque el total correcto aparece en T5, el patrón óptimo de UX requiere que el cliente vea el total antes de confirmar. El checkout corrige el dato pero el ECO RESUMEN de confirmación previa es el momento estándar de transparencia de precio.

### Capa 9 — Clasificación y deuda técnica ✅ [DOCUMENTADO]

Bug introducido intencionalmente (DEMO BREAK). No es regresión accidental ni alucinación del LLM — es una instrucción del playbook incompleta por diseño temporal. La solución es restaurar el template multi-producto del Paso 7, operación de bajo riesgo y alcance único.

---

### Resumen visual de capas

| Capa | Nombre | Estado | Veredicto |
|------|--------|--------|-----------|
| 1 | Síntoma observable | 🔴 | Confirmado — T3 sin total |
| 2 | Turno y parámetros | 🔴 | Confirmado — slots capturados pero no usados en suma |
| 3 | Lógica del playbook | 🔴 | **Causa raíz** — template mono-producto en Paso 7 |
| 4 | Flujo de slots Compra→Checkout | 🟡 | Relevante — slots OK, problema en instrucción ECO |
| 5 | Historial de commits | 🔴 | Confirmado — DEMO BREAK `c9ce667` |
| 6 | Estado Sheet | ✅ | OK — sin incoherencias de datos |
| 7 | Coherencia entre turnos | 🟡 | Parcial — T3 sin total, T5 con total |
| 8 | Impacto UX | 🟡 | Medio — confirmación sin precio total visible |
| 9 | Deuda técnica | ✅ | Documentado — fix deliberado pendiente de revertir |

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Archivo afectado | `definitions/playbooks/compra.yaml` (Paso 7 ECO RESUMEN) |
| Alcance | 1 archivo |
| Profundidad | Cambio de texto en template de instrucción |
| Riesgo del fix | Medio — afecta experiencia de compra multi-producto |
| Causa | DEMO BREAK deliberado (`c9ce667`) no revertido |
| TCs probablemente afectados | Todos los TCs de flujo multi-producto con check de total en ECO RESUMEN |
| Coste de no arreglar | Usuario confirma pedido sin ver el precio total → riesgo de disputas |

---

## Recomendación

### Solución #1 — Restaurar template multi-producto en Paso 7 ECO RESUMEN ⭐ RECOMENDADA

Añadir en el Paso 7 de `compra.yaml` una rama condicional que, cuando existen `$producto_2` y `$precio_2`, use un template con ambos productos y el total calculado:

```yaml
# Paso 7 ECO RESUMEN — variante multi-producto (cuando $producto_2 existe)
- Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [$precio_estimado + $precio_2]€. ¿Lo confirmo?'
- Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [$precio_estimado + $precio_2]€. ¿Lo confirmamos?'
- Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [$precio_estimado + $precio_2]€. ¿Confirmamos?'
```

El template mono-producto existente se mantiene inalterado para pedidos de un solo ítem.

**Ventajas:** mínimo impacto, restaura comportamiento pre-DEMO BREAK, revierte exactamente lo que `c9ce667` eliminó.

**Riesgo:** bajo — solo cambia texto de instrucción en un paso de compra.yaml.

---

### Solución #2 — Revertir commit `c9ce667` directamente

Ejecutar `git revert c9ce667` para restaurar el estado del Paso 7 al commit anterior. Si `b8f9ee5` (captura de `$producto_2`) también sigue roto, revertir ambos en orden inverso.

**Ventajas:** reversión limpia y trazable mediante git.

**Riesgo:** medio — si otros cambios del mismo commit son deseables, el revert los deshace también. Verificar el diff completo del commit antes de revertir.

---

### Solución #3 — Delegar el cálculo del total al LLM sin template fijo

Reemplazar el template con instrucción abierta: "Si hay $producto_2, muestra ambos productos y calcula el total sumando $precio_estimado + $precio_2 antes de pedir confirmación."

**Ventajas:** más flexible para futuras extensiones (3+ productos).

**Riesgo:** mayor variabilidad en el output del LLM; los checks de texto fijo ("65") pueden ser frágiles si el LLM formatea el número de forma distinta (65,00 vs 65 vs 65.0).

---

### Solución #4 — Añadir instrucción de suma explícita como regla global del playbook

Añadir al encabezado de `compra.yaml` una regla global: "Cuando el pedido tenga más de un producto, SIEMPRE calcula y muestra el total antes de pedir confirmación."

**Ventajas:** cubre casos futuros de multi-producto sin tocar cada paso individualmente.

**Riesgo:** medio — las reglas globales interactúan con todos los pasos; posible interferencia con otros flujos si el LLM aplica la regla en contextos no deseados.

---

### Solución #5 — Añadir un Paso 7b específico para multi-producto

Crear un paso intermedio entre la selección del segundo producto y el ECO RESUMEN que calcule y confirme el total antes de pasar al Paso 7.

**Ventajas:** separación clara de responsabilidades; el Paso 7 existente no se toca.

**Riesgo:** complejidad añadida al flujo; más pasos = más posibilidades de salto incorrecto entre pasos.

---

### Plan de acción (Solución #1)

1. Abrir `definitions/playbooks/compra.yaml`
2. Localizar el Paso 7 ECO RESUMEN (actualmente líneas ~601-606)
3. Añadir condicional multi-producto: si `$producto_2` existe, usar template con ambos ítems y total calculado
4. Mantener el template mono-producto existente sin cambios
5. Commit: `fix(compra): restaura ECO RESUMEN multi-producto en Paso 7 (revierte DEMO BREAK c9ce667)`
6. PR + merge → pipeline CI/CD → rerun TC-MULTI-PRODUCTO-01
7. Verificar que T3 ahora incluye "65" en el resumen

**Tiempo estimado:** ~10 min (edición de texto + ciclo PR/merge/deploy)

---

## Patrones cruzados

- **DEMO BREAK no revertido:** patrón recurrente cuando las demos deliberadamente rompen features para mostrar el estado previo. El riesgo es que los commits de restauración se olvidan o se posponen. Considerar política: todo DEMO BREAK debe tener un ticket de revert asociado.
- **ECO RESUMEN vs Checkout:** el total aparece correctamente en Checkout (T5) pero no en el ECO RESUMEN previo (T3). Indica que la lógica de cálculo existe en el sistema pero no está replicada en el paso de confirmación intermedio. Patrón de diseño a revisar: ¿el ECO RESUMEN debería delegar en la misma lógica que Checkout para calcular totales?
- **Slots condicionales multi-producto:** `$producto_2`, `$precio_2`, `$cantidad_2` funcionan correctamente en la captura y transferencia a Checkout. El bug está únicamente en la instrucción de presentación. Este patrón es saludable — los datos fluyen bien, solo falta la vista.
