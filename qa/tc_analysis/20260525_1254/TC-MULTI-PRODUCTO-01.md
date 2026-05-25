---
status: FAIL
tipo: Bug Playbook (DEMO BREAK activo)
estimacion: ~10 min (Solución #1 recomendada)
---

# TC-MULTI-PRODUCTO-01 — Pedido multi-item — Checkout recibe ambos productos como parametros formales

**Suite:** QA Playbooks v23 | **Fecha análisis:** 2026-05-25 | **Versiones:** orquestador v65 / compra v39

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente | Check | Estado |
|-------|---------|--------|-------|--------|
| T1 | "quiero un ramo de rosas y un centro de mesa para mi casa" | Ofrece catálogo de ramos de rosas + indica que luego verá centro de mesa | Agente dijo [catalo\|opciones\|ramo] | 🟢 PASS |
| T2 | "el ramo de rosas morado de 37 euros" | "Anotado, 1 x Ramo de Rosas Morado — M (37.0euros). Ahora el centro de mesa: Para centro de mesa tengo estas opciones: [...]" | Agente dijo [anotado\|centro de mesa\|ahora] | 🟢 PASS |
| T3 | "el centro de tulipanes de 28 euros" | "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0euros) y 1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros). ¿Lo confirmo?" | Agente debía decir `[Tu pedido.*ramo.*centro\|resumen.*ramo.*centro\|37.*28\|65\|ambos productos]` | 🔴 FAIL |
| T4 | "si" | "Perfecto, para completar tu pedido necesito tu correo electronico." | Agente dijo [correo\|email] | 🟢 PASS |
| T5 | "jerosan1@gmail.com" | "Perfecto Jero, te resumo tu pedido: 1 x Ramo de Rosas Morado — M (37€) / 1 x Centro de Mesa Tulipanes Multicolor — S (25€) / Total: 62€ / [dirección...]" | Agente debía decir `[65\|37.*28\|28.*37]` (precio total esperado: 37+28=65€, agente dice 62€ con $precio_2=25€) | 🔴 FAIL |

**Turnos críticos: T3 y T5.** El fallo se reproduce en los 3 runs (0/3).

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Comportamiento 🔴 [verificada]

**Fallo:** El DEMO BREAK `c9ce667` modificó el template del ECO RESUMEN (Paso 7) en `definitions/playbooks/compra.yaml` para que solo muestre `$producto`, eliminando `$producto_2`, `$precio_2` y el total combinado. El template activo (líneas 601-606) es:

```
7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
   Usa el template EXACTO segun modo, sin anadir productos extra:
   - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
   - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros). Lo confirmamos?'
   - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros). Confirmamos?'
   ESPERA confirmacion explicita del usuario.
```

La instrucción `sin anadir productos extra` es la restricción del DEMO BREAK — instruye explícitamente al LLM a omitir el segundo producto del resumen.

**Consecuencia en T3:** El LLM ignoró la restricción del template y generó el ECO RESUMEN con ambos productos desde el contexto conversacional, mostrando: "Tu pedido: 1 x Ramo de Rosas Morado — M (37.0euros) y 1 x Centro de Mesa Tulipanes Multicolor — S (28.0euros)." Sin embargo, el check falla (ver Capa 9).

**Consecuencia en T5:** El Checkout muestra `$precio_2 = 25€` en lugar de 28€ (total 62€ en lugar de 65€). El DEMO BREAK en el template del Paso 7 hace que el LLM no tenga el valor canónico de `$precio_2` claramente especificado en el ECO RESUMEN confirmado, lo que introduce una divergencia en el valor del slot cuando se transfiere a Checkout.

**Fuente:** `git show c9ce667 -- definitions/playbooks/compra.yaml`; template actual en líneas 601-606 de `definitions/playbooks/compra.yaml`.

---

### Capa 2 — Routing ⚪ N/A

No hay cambio de flow ni de playbook problemático. El agente transita correctamente al flujo multi-producto y llama a Checkout en T4-T5. El routing no es la causa del fallo.

---

### Capa 3 — Parámetros / Slots 🔴 [verificada]

**Fallo:** `$precio_2` llega a Checkout con valor 25€ en lugar de 28€ (visible en T5: "Centro de Mesa Tulipanes Multicolor — S (25€)").

El Paso 6b (línea 600) define: `$precio_2 = precio_unitario x $cantidad_2`. En T3 el agente mostró correctamente "(28.0euros)" en su respuesta, pero el slot `$precio_2` no se ancló al valor confirmado porque el ECO RESUMEN del Paso 7 — que es el punto de consolidación canónica de los parámetros antes de Checkout — no incluye `$precio_2` en el template del DEMO BREAK. El LLM, al transferir a Checkout, recalcula o usa un valor diferente (posiblemente el precio de catálogo del producto "S" = 25€) en lugar del precio declarado por el usuario (28€).

**Evidencia:** T5 agent response: "1 x Centro de Mesa Tulipanes Multicolor — S (25€) / Total: 62€" vs. esperado 28€ y 65€.

**Fuente:** T5 agent response en JSON del run; líneas 600-607 de `definitions/playbooks/compra.yaml`.

---

### Capa 4 — Integración 🟢 [verificada]

Los tool calls a PetalDataTool funcionan correctamente. En T1 el catálogo de ramos de rosas se devuelve con precios reales. En T2 el catálogo de centros de mesa se devuelve correctamente. No hay errores de tool call ni timeouts. El fallo no está en la integración con herramientas externas.

---

### Capa 5 — Datos 🟡 [supuesta]

El precio del "Centro de Mesa Tulipanes Multicolor — S" en el catálogo podría ser 25€ (precio real del Sheet), mientras el usuario en T3 lo mencionó como "de 28 euros" (precio leído de la pantalla tras la muestra del agente en T2). Si el catálogo tiene el precio a 25€ y el agente en T2 mostró el producto a 28€, hay una discrepancia entre el precio del Sheet y el precio mostrado — pero esto es secundario al DEMO BREAK de Capa 1. No hay variables del Sheet relevantes para la lógica multi-producto. Estado del Sheet: no evaluado como causa primaria.

---

### Capa 6 — Infraestructura ⚪ N/A

No se detectan problemas de infraestructura. El agente responde en todos los turnos sin errores de conectividad ni timeouts.

---

### Capa 7 — LLM 🟢 [verificada]

El LLM compensó el template roto del Paso 7: en T3 generó el ECO RESUMEN con ambos productos desde el contexto conversacional, ignorando la restricción `sin anadir productos extra`. Este comportamiento demuestra que el LLM tiene la información correcta en contexto y la capacidad de generar el resumen completo. El problema no está en el modelo sino en el template roto que introduce ambigüedad en la consolidación de `$precio_2` antes del traspaso a Checkout.

---

### Capa 8 — Histórico 🔴 [verificada]

DEMO BREAK activo identificado en el git log:

```
c9ce667 DEMO BREAK v2: rompe ECO RESUMEN multi-producto (Paso 7) — solo muestra primer producto
  → Template del Paso 7 modificado para excluir $producto_2 y total combinado

b8f9ee5 DEMO BREAK: quita captura de $producto_2 en compra.yaml Paso 6b
  → Parcialmente revertido en c9ce667 (captura de $producto_2 restaurada, pero ECO RESUMEN permanece roto)

4f7adea fix(multi-producto): slots explícitos + ECO resumen + Checkout condicional (#94)
  → Fix original con el template correcto del Paso 7 (incluía ambos productos y total)
```

El fix correcto existía en `4f7adea`. El DEMO BREAK `c9ce667` fue aplicado intencionalmente sobre ese fix para propósitos de demostración.

**Fuente:** `git log --oneline -- definitions/playbooks/compra.yaml`.

---

### Capa 9 — Test 🟡 [supuesta]

**T3 — posible problema de calibración por case-sensitivity:**

El regex del check es `[Tu pedido.*ramo.*centro|resumen.*ramo.*centro|37.*28|65|ambos productos]`. La respuesta del agente contiene "Tu pedido", "37" y "28" — la alternativa `37.*28` debería matchear. Sin embargo, si el regex es case-sensitive, las alternativas `Tu pedido.*ramo.*centro` y `resumen.*ramo.*centro` fallarían porque el agente usó "Ramo" y "Centro" (mayúsculas). Si ninguna alternativa matchea (por un bug en el motor de regex o en cómo se evalúan las alternativas), el check podría fallar aunque el texto contenga `37.*28`.

Hipótesis más probable: el check evalúa cada alternativa de la lista `[A|B|C|D|E]` con flags de compilación específicos, y hay un problema con el operador `.*` que requiere que los tokens sean exactos sin saltos de línea. Si la respuesta del agente usa `\n` u otro separador entre "37.0euros" y "28.0euros", la alternativa `37.*28` podría no matchear en modo no-DOTALL.

**T5 — check correcto:** El check `[65|37.*28|28.*37]` es correcto. El agente devuelve 62€ (37+25) en lugar de 65€ (37+28), por lo que ninguna alternativa matchea. El bug del T5 es real y está en Capa 3.

---

### Resumen visual de capas

| Capa | Estado | Descripción |
|------|--------|-------------|
| 1 Comportamiento | 🔴 | DEMO BREAK `c9ce667` — template Paso 7 excluye $producto_2 y total |
| 2 Routing | ⚪ | N/A |
| 3 Parámetros/Slots | 🔴 | $precio_2 llega a Checkout como 25€ en lugar de 28€ |
| 4 Integración | 🟢 | PetalDataTool devuelve catálogos correctamente |
| 5 Datos | 🟡 | Posible discrepancia precio catálogo (25€) vs precio mostrado (28€) — secundario |
| 6 Infraestructura | ⚪ | N/A |
| 7 LLM | 🟢 | LLM compensó el template roto; tiene el contexto correcto |
| 8 Histórico | 🔴 | DEMO BREAK `c9ce667` sobre fix `4f7adea` — rotura intencionada |
| 9 Test | 🟡 | T3: posible case-sensitivity en regex; T5: check correcto |

**3 🔴 · 2 🟢 · 2 🟡 · 2 ⚪**

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Alcance | Localizado — 1 archivo (`compra.yaml`), 3-5 líneas del Paso 7 |
| Profundidad | Superficial — restaurar template a la versión de `4f7adea` |
| Riesgo de regresión | Bajo — el bloque FLUJO MULTI-PRODUCTO es autocontenido; el resto del playbook no se toca |
| Severidad | Alta para el flujo multi-producto — el Checkout recibe precio incorrecto (25€ vs 28€), lo que genera un total erróneo en el resumen de confirmación al cliente |
| Clasificación | **Trivial** |

---

## Soluciones propuestas

### Solución #1 — Restaurar template ECO RESUMEN Paso 7 con ambos productos y total ⭐ RECOMENDADA

**Puntuación: 9/10 | Esfuerzo: ~10 min**

**Cambio:** En `definitions/playbooks/compra.yaml`, líneas 601-606, restaurar el template del Paso 7 para incluir `$producto_2`, `$precio_2` y el total combinado. Referencia: commit `4f7adea`.

```yaml
# ANTES (DEMO BREAK activo — c9ce667)
7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
   Usa el template EXACTO segun modo, sin anadir productos extra:
   - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros). Lo confirmo?'
   - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros). Lo confirmamos?'
   - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros). Confirmamos?'
   ESPERA confirmacion explicita del usuario.

# DESPUÉS (restaurado)
7. ECO RESUMEN OBLIGATORIO (NO saltarse, NO ir directo a Checkout):
   Usa el template EXACTO segun modo:
   - Estandar: 'Tu pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [suma]euros. Lo confirmo?'
   - Solemne: 'El pedido queda: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [suma]euros. Lo confirmamos?'
   - Corporativo: 'Resumen del pedido: $cantidad x $producto ($precio_estimadoeuros) y $cantidad_2 x $producto_2 ($precio_2euros). Total: [suma]euros. Confirmamos?'
   ESPERA confirmacion explicita del usuario.
```

**Por qué es la mejor opción:** Corrige la causa raíz de ambos fallos (T3 y T5). El ECO RESUMEN con `$precio_2` explícito fuerza al LLM a anclar el valor del slot antes de transferir a Checkout, eliminando la divergencia de precio. El riesgo de regresión es mínimo — el fix ya existía en `4f7adea` y fue validado en su momento.

**Verificación:** El agente debería mostrar en T3 el resumen con ambos productos y total 65€, y en T5 el Checkout debería reflejar 37€ + 28€ = 65€.

---

### Solución #2 — Solución #1 + revisar regex T3 para case-insensitive

**Puntuación: 8/10 | Esfuerzo: ~15 min**

Aplicar Solución #1 y adicionalmente revisar el check de T3 para confirmar si el fallo era de calibración de regex (case-sensitivity) o de comportamiento. Si tras el fix de Solución #1 el T3 sigue fallando, ajustar el regex añadiendo flag case-insensitive o cambiando `ramo.*centro` por `[Rr]amo.*[Cc]entro`.

**Cuándo usar:** Si tras aplicar Solución #1 el T3 continúa fallando en los 3 runs (lo que indicaría que el problema del T3 no era solo el template roto sino también el regex).

---

### Solución #3 — Añadir Example multi-producto para consolidar el ECO RESUMEN

**Puntuación: 5/10 | Esfuerzo: ~30 min**

Crear un Example que muestre el flujo completo multi-producto con el ECO RESUMEN correcto (ambos productos + total), reforzando el template del Paso 7.

**No recomendada como solución primaria:** Complementaria a Solución #1, no alternativa. Sin el template correcto, un Example puede ser insuficiente bajo variabilidad del LLM. Abordar como refuerzo si Solución #1 muestra inestabilidad en runs posteriores.

---

## Plan de acción — Solución #1

1. Editar `definitions/playbooks/compra.yaml` líneas 601-606
2. Restaurar el template del Paso 7 con `$producto_2`, `$precio_2` y total combinado (referencia: `git show 4f7adea -- definitions/playbooks/compra.yaml`)
3. Commit + PR + merge → deploy automático vía CI/CD
4. Re-ejecutar: `python qa/test_QA_Playbooks_v23.py --tc TC-MULTI-PRODUCTO-01 --runs 3`
5. Criterio de éxito: 3/3 PASS (T3 y T5 correctos, total 65€)

**Comando QA post-fix:**
```bash
python qa/test_QA_Playbooks_v23.py --tc TC-MULTI-PRODUCTO-01 --runs 3
```

---

## Patrones cruzados

- **DEMO BREAK como causa raíz:** este es el segundo TC en el batch 20260525_1254 donde un commit DEMO BREAK (`c9ce667`) es la causa directa del fallo. El mismo commit afecta la suite multi-producto de forma transversal.
- **Divergencia slot → Checkout:** patrón donde el valor de un slot (`$precio_2`) capturado en el flujo conversacional no se consolida correctamente antes del traspaso a Checkout. Si el ECO RESUMEN no incluye `$precio_2` explícitamente, el LLM puede recalcular desde el catálogo (precio "real" = 25€) en lugar de usar el precio declarado por el usuario (28€). Este patrón es un riesgo en cualquier TC que pase parámetros de precio a Checkout sin confirmación canónica.
- **LLM compensando templates rotos:** el LLM generó el resumen correcto en T3 ignorando el template, pero no pudo mantener el precio correcto en el traspaso a Checkout. Esto ilustra el límite de la compensación del LLM: puede generar texto adecuado, pero no puede garantizar la integridad de los slots cuando el template no los especifica explícitamente.
