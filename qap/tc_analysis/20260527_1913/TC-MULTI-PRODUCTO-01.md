---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

# TC-MULTI-PRODUCTO-01 — Pedido multi-item — ECO RESUMEN muestra total antes de confirmar

**Grupo:** COMPRA-INV | **Run:** 2026-05-27 19:13 | **Resultado:** FAIL (0/3)
**Versiones:** orquestador v65 · compra v39 · checkout v33 · registro v7

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente (resumen) | Check | Veredicto |
|-------|---------|-----------------|-------|-----------|
| T1 | "quiero un ramo de rosas y un centro de mesa para mi casa" | Ofrece catálogo de ramos de rosas; anuncia que luego ven el centro de mesa | OK: Agente dijo [centro.{0,80}ramo] | PASS |
| T2 | "el ramo de rosas morado de 37 euros" | "Anotado, 1 x Ramo de Rosas Morado — M (37.0€). Ahora el centro de mesa:" + catálogo (varía entre runs) | OK: Agente dijo [morado] | PASS |
| T3 | "el centro de tulipanes de 28 euros" | **Runs 1&2:** "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0€) y 1 x Centro de Mesa Tulipanes Multicolor — S (28.0€). ¿Lo confirmo?" — muestra ambos productos pero **omite el total 65€** · **Run 3:** "No tengo un centro de tulipanes de 28 euros" — el agente mostró Rosas y Eucalipto en T2, por lo que tulipanes no estaban en la conversación | FAIL: Agente debía decir [65] | **FAIL** |

**Dos modos de fallo distintos:**
- **Runs 1 & 2 (causa principal):** El agente llega al ECO RESUMEN del Paso 7 con ambos productos en contexto, pero el template mono-producto del DEMO BREAK no incluye `$producto_2`, `$precio_2` ni el cálculo del total. El LLM improvisa el listado de ambos ítems pero no suma.
- **Run 3 (causa secundaria):** El LLM seleccionó un subset distinto de centros de mesa en T2 (Rosas y Eucalipto en lugar de Tulipanes). El usuario pidió tulipanes — producto no ofrecido en esa conversación — y el agente respondió correctamente que no lo tiene. El test falla porque el check `[65]` tampoco se cumple.

---

## Causa raíz — evaluación de las 9 capas del sistema [v1.1]

🔴 1. **Capa Comportamiento** [verificada] · `Read definitions/playbooks/compra.yaml líneas 601-607`

La instrucción del Paso 7 ECO RESUMEN define:
```
Usa el template EXACTO segun modo, sin anadir productos extra:
- Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
```
El template es **mono-producto**: solo referencia `$producto` y `$precio_estimado`. No hay variante multi-producto con `$producto_2`, `$precio_2` ni total calculado. La frase "sin anadir productos extra" es el DEMO BREAK activo (`c9ce667`). En runs 1&2, el LLM viola parcialmente esta instrucción (añade el segundo producto al texto) pero no calcula el total al no tener la variable en el template. El resultado es un ECO RESUMEN incompleto — ambos productos visibles, total ausente.

La misma capa explica el fallo secundario de run 3: la instrucción del Paso 5d dice "muestra hasta 3 opciones", sin anclaje a qué subset mostrar, lo que genera selección no-determinista del catálogo. El LLM eligió Rosas y Eucalipto en T2, haciendo imposible que el usuario pida tulipanes consistentemente.

⚪ 2. **Capa Routing** · N/A — Petal utiliza Playbooks exclusivamente; no hay Flows ni Pages ni Intents involucrados en este flujo.

🟡 3. **Capa Parámetros / Slots** [supuesta] · _(no verificado: los parámetros del JSON reflejan el estado de sesión, no se puede confirmar si $producto_2/$precio_2 se capturan formalmente como session params en T3)_

El Paso 6b contiene la instrucción "CAPTURA OBLIGATORIA: $producto_2 = nombre_exacto_elegido" (verificado en el archivo actual — la instrucción está presente, no fue eliminada por el DEMO BREAK activo). Sin embargo, los parámetros registrados en T3 del JSON (`producto`, `intencion_inicial`, `grupo_intent`, `modo_tono`, `ocasion_detectada`) no incluyen `$producto_2` ni `$precio_2`. Es incierto si esto refleja el estado pre-respuesta del turno o un fallo de captura formal del slot. El texto del agente incluye ambos productos, lo que indica que el LLM accede a la información de contexto, pero la captura como session parameter no es verificable desde el JSON actual.

🟢 4. **Capa Integración** [verificada] · JSON T1-T2 runs 1&2

PetalDataTool devuelve resultados de inventario válidos en T1 (ramos de rosas) y T2 (centros de mesa). El tool call funciona y los productos mostrados existen en catálogo (Ramo de Rosas Morado 37€, Centro de Mesa Tulipanes Multicolor 28€ confirmados en runs 1&2). No hay errores de backend ni respuestas "Lo siento, algo no ha funcionado". Esta capa no es causa del fallo.

🟢 5. **Capa Datos** [verificada] · `curl .../exec?recurso=business`

Sheet business cargado correctamente (43 variables de negocio, SHEET_OK). No se detectan duplicados con valores distintos ni inconsistencias de formato en las variables auditadas. El producto "Centro de Mesa Tulipanes Multicolor — S (28€)" existe en catálogo (aparece en T2 de runs 1&2). Run 3 muestra selección diferente (Rosas y Eucalipto — S/M) — coherente con un catálogo que tiene más de 3 centros de mesa disponibles y un LLM que selecciona el subset a mostrar de forma no-determinista.

🟢 6. **Capa Infraestructura** [verificada] · `metadata` del JSON (orquestador v65, compra v39, checkout v33, registro v7)

Las versiones del agente son coherentes con el estado actual del repo (post-PR #107). El deploy es correcto y la versión activa es la esperada.

🟡 7. **Capa Modelo / LLM** [supuesta] · _(no verificado: requeriría múltiples runs con debug de tool calls para aislar el comportamiento del LLM)_

Run 3 muestra comportamiento no-determinista: el LLM seleccionó un subset de centros de mesa diferente al de runs 1&2, aunque la query de usuario fue idéntica ("quiero un centro de mesa"). Este es un comportamiento conocido cuando el catálogo tiene más productos disponibles que el límite de "hasta 3" — el LLM elige qué mostrar sin instrucción de prioridad. No se puede marcar 🔴 porque la Capa Comportamiento (instrucción del playbook) no está en 🟢 y run 3 es solo 1 de 3 ejecuciones. Candidato a investigar si persiste post-fix del DEMO BREAK.

🔴 8. **Capa Histórico** [verificada] · `git log --oneline -n 20 -- definitions/playbooks/compra.yaml`

```
c9ce667  DEMO BREAK v2: rompe ECO RESUMEN multi-producto (Paso 7) — solo muestra primer producto
b8f9ee5  DEMO BREAK: quita captura de $producto_2 en compra.yaml Paso 6b
4f7adea  fix(multi-producto): slots explícitos + ECO resumen + Checkout condicional (#94)
```

El commit `c9ce667` es la causa directa del FAIL en runs 1&2. El commit `b8f9ee5` aparece en el historial pero la instrucción de captura de `$producto_2` en Paso 6b está presente en el archivo actual — posiblemente `4f7adea` o `237955b` la restauró parcialmente. Ambos DEMO BREAKs son intencionados y no han sido revertidos.

🟢 9. **Capa Test** [verificada] · JSON T3

El check `["65"]` es correcto: verifica que el total (37€ + 28€ = 65€) aparezca en el ECO RESUMEN antes de la confirmación. Es una condición de negocio válida — el usuario debe ver el precio total antes de confirmar el pedido. El fallo en 3/3 runs es determinista para runs 1&2 (template DEMO BREAK) y coyuntural para run 3 (subset de catálogo no-determinista). La calibración del test es correcta.

**Resumen visual:** 2 🔴 problema · 3 🟢 ok · 2 🟡 supuesta · 1 ⚪ N/A

---

## Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), una sección (Paso 7 template) |
| Profundidad | Medio | Cambiar template de instrucción + comportamiento no-determinista del catálogo en Paso 5d; afecta lógica de presentación y slot-filling |
| Riesgo de regresión | Medio | Afecta todos los flujos multi-producto; puede impactar TC-MULTI-PRODUCTO y TCs de compra con múltiples ítems |

**Nivel final:** Medio → 5 soluciones

---

## Recomendación

### Solución recomendada: #1 — Restaurar template multi-producto en Paso 7

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: Revierte exactamente lo que `c9ce667` eliminó, con el mínimo alcance posible. Añadir la variante multi-producto (con `$producto_2`, `$precio_2` y total calculado) al Paso 7, manteniendo la variante mono-producto para pedidos de un ítem. Eliminar la instrucción "sin anadir productos extra" que confunde al LLM. Fix quirúrgico, bajo riesgo.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar template multi-producto en Paso 7** | 🟢 9/10 | — | Cirugía precisa: solo modifica el template del ECO RESUMEN. Revierte exactamente el DEMO BREAK. Bajo riesgo de regresión en TCs mono-producto. |
| 2 | **`git revert c9ce667`** | 🟡 7/10 | — | Más rápido (5 min) pero menos control: revierte TODO el commit, incluidas posibles instrucciones de estilo o reglas de contexto que también modificó. Requiere revisar el diff completo primero. |
| 3 | **Añadir regla global de cálculo de total** | 🟡 6/10 | — | Más resiliente a futuros cambios de template, pero las reglas globales tienen riesgo de interferir con otros flujos. No aborda el problema de subset de catálogo no-determinista del run 3. |
| 4 | **Anclar el subset de catálogo en Paso 5d** | 🔴 4/10 | — | Aborda el run 3 secundario pero añade rigidez al playbook. Forzar siempre tulipanes/un producto específico no es la solución correcta — el catálogo debe ser dinámico. ROI bajo. |
| 5 | **Hacer el test resiliente al subset de catálogo** | 🔴 3/10 | — | Solución lado test, no arregla el bug del agente. Puede enmascarar fallos reales del ECO RESUMEN. Solo útil si el run 3 pattern persiste post-fix y se decide aceptar la no-determinisidad del catálogo. |

### Plan de acción (Solución #1)

1. **Abrir `definitions/playbooks/compra.yaml`**: localizar Paso 7 ECO RESUMEN (línea ~601)
2. **Modificar la instrucción**: eliminar "sin anadir productos extra"; añadir variante multi-producto condicional:
   ```
   - Si $producto_2 existe:
     Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [$precio_estimado + $precio_2]€. ¿Lo confirmo?'
   - Si no:
     Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). ¿Lo confirmo?'
   ```
3. **Commit**: `fix(compra): restaura ECO RESUMEN multi-producto en Paso 7 (revierte DEMO BREAK c9ce667)`
4. **PR + merge** → pipeline CI/CD → rerun `--runs 3`
5. **Verificar**: T3 runs 1&2 ahora muestran "65" en el ECO RESUMEN

**Coste total**: ~15 min (edición 5 min + ciclo PR/merge/deploy ~10 min)

### Parámetros / slots requeridos entre playbooks

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$producto` | Compra | Checkout | Sí | Primer producto — siempre capturado |
| `$precio_estimado` | Compra | Checkout | Sí | Precio primer producto |
| `$cantidad` | Compra | Checkout | Sí | Cantidad primer producto |
| `$producto_2` | Compra | Checkout | Condicional | Solo en multi-producto — captura instrucción presente en Paso 6b actual |
| `$precio_2` | Compra | Checkout | Condicional | Precio segundo producto — ausente en template Paso 7 (DEMO BREAK) |
| `$cantidad_2` | Compra | Checkout | Condicional | Solo en multi-producto |

---

## Notas adicionales

**Sobre el DEMO BREAK**: la causa raíz de esta sesión es el DEMO BREAK `c9ce667`, dejado intencionadamente para una demo. No se recomienda revertir hasta confirmar que la demo ha concluido o que no se necesita para futuras demostraciones.

**Sobre run 3**: incluso después de corregir el DEMO BREAK, el comportamiento no-determinista del catálogo en T2 puede ocasionar runs donde el agente muestre un subset diferente de centros de mesa. Si persiste, considerar anclar el orden del catálogo o ampliar el check de T2 para aceptar cualquier producto a 28€.
