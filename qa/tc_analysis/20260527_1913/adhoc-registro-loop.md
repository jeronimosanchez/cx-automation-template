---
status: ANALISIS_ADHOC
tipo: Bug Playbook (múltiple)
session: 2026-05-27
origen: conversación real de usuario (no TC formal)
---

# Adhoc — Compra ramo de rosas + usuario no registrado

**Escenario:** usuario busca ramo de rosas, refina por color y precio, intenta completar el pedido con un email no registrado.
**Runs ejecutados:** 2 (Run 1 = estado con bugs, Run 2 = tras aplicar fix + descubrimiento de bugs residuales)
**Resultado global:** 2 bugs corregidos y revertidos para demo · 2 bugs nuevos descubiertos pendientes de fix

---

## Comparativa de turnos (Run 1 vs Run 2)

| T | Usuario | Run 1 (con bugs) | Run 2 (con fix) | Delta |
|---|---------|-----------------|-----------------|-------|
| 1 | quiero un ramo de rosas | ¿Para qué ocasión o color? | ¿Tienes algún color en mente? | ✅ sin diferencia relevante |
| 2 | tienes mas barato | Amarillo M 25€, Blanco M 25€, Morado M 37€ | Amarillo M 25€, Blanco M 25€ | ⚠️ ninguno muestra opciones de 9€/15€ — bug compartido |
| 3 | la de 15 euros | No tengo ninguna de 15€ ¿Te refieres a alguna mostrada? | No tengo a 15€. Los más baratos son a 25€ | 🔴 ambos responden incorrectamente — Rosa M 15€ existe en catálogo |
| 4 | tienes rojas | Rojo S 22€, M 37€, L 59€ | Rojo S 22€, M 37€, L 59€ | ✅ igual, correcto |
| 5 | y mas barato | 🔴 Rosa S 9€, Rosa M 15€, Naranja S 22€ — perdió color rojo | ✅ "No tengo rosas rojas más baratas que 22€" | ✅ FIX VERIFICADO |
| 6 | pero de rosas rojas | El más barato en rojas es 22€ | El más barato en rojas es 22€ | ✅ correcto en ambos |
| 7 | dame ese | Perfecto, Rosas Rojo S 22€. ¿Cuántos? | Perfecto, Rosas Rojo S 22€. ¿Cuántos? | ✅ igual |
| 8 | 1 | Necesito tu correo electrónico | Necesito tu correo electrónico | ✅ igual (diseño correcto — resumen en Checkout PASO 2) |
| 9 | javi@gmail.com | No encuentro cuenta. ¿Otro correo o registrarte? | No encuentro cuenta. ¿Otro correo o registrarte? | ✅ igual |
| 10 | ese | 🔴 "Disculpa, no capté tu correo" — loop | ⚠️ "¿Cuál es tu nombre?" — entró a registro pero sin confirmar con qué email | ✅ FIX VERIFICADO (con matiz) |
| 11 | javi@gmail.com | 🔴 "No encuentro cuenta..." — loop infinito | ✅ "Eso es un correo, necesito tu nombre" — sigue en registro | ✅ FIX VERIFICADO |

---

## Bug #1 — Pérdida de filtro color en refinamiento de precio (T5)

**Playbook:** `compra.yaml` — FLUJO REFINAMIENTO
**Estado:** ✅ **CORREGIDO** en commit `74fd071` · revertido en `5b812e0` para demo

**Causa raíz:**
El FLUJO REFINAMIENTO tenía la instrucción "MANTIENE tipo + color + ocasion" pero sin anclaje explícito sobre qué hacer cuando el color no se re-menciona en el turno actual. El LLM olvidaba el color al recibir un refinamiento de precio.

**Fix aplicado:**
```yaml
⛔ REGLA CRITICA DE COLOR: si el usuario mencionó un color en cualquier turno anterior
de esta conversación ('tienes rojas', 'en rojo', 'pero rojas') y no lo ha cambiado
explícitamente, ese color SIGUE ACTIVO. Inclúyelo en PetalDataTool aunque el usuario
no lo repita en este turno.
```

**Para restaurar el fix post-demo:**
```bash
git revert 5b812e0 --no-edit && git push origin main
```

---

## Bug #2 — Loop infinito de registro (T10-T11)

**Playbook:** `checkout.yaml` — BUCLE EMAIL + EMAIL NO ENCONTRADO
**Estado:** ✅ **CORREGIDO** en commit `74fd071` · revertido en `5b812e0` para demo

**Causa raíz (doble):**

_Sub-bug A — referencia anafórica no reconocida:_
El BUCLE EMAIL filtra entradas sin '@' como intentos fallidos de email. "ese" no tiene '@' → el agente pedía el correo de nuevo en lugar de entender que el usuario quería registrarse con el email ya dado.

_Sub-bug B — mismo email repetido no activa registro:_
En EMAIL NO ENCONTRADO, la opción 1 decía "Otro email(@) → consulta perfil de nuevo" sin distinguir entre email nuevo vs. email idéntico. Repetir el mismo email no disparaba la opción 2 (Registrarse).

**Fix aplicado:**
```yaml
# En BUCLE EMAIL, antes del contador de intentos:
EXCEPCION REFERENCIA ANAFÓRICA: si el usuario dice 'ese', 'ese mismo', 'el mismo',
'ese correo', 'con ese', 'registrame con ese' → NO incrementes el contador. Interpreta
como intención de registrarse con $email → ejecuta directamente opción 2:
invoca ${PLAYBOOK:Registro_Task} pasando email=$email.

# En EMAIL NO ENCONTRADO, opción 1:
Otro email(@) diferente al anterior → $email=nuevo → consulta perfil de nuevo.
EXCEPCION: si el usuario repite exactamente el mismo email que ya está en $email
→ interpretar como intención de registrarse, tratar directamente como opción 2
sin nueva consulta de perfil.
```

---

## Bug #3 — Error factual en precio mínimo (T3) ← PENDIENTE

**Playbook:** `compra.yaml` — clasificación de input "la de 15 euros" tras REFINAMIENTO
**Estado:** 🔴 **SIN FIX** — descubierto en Run 2

**Qué ocurre:**
Cuando el usuario dice "la de 15 euros" (T3) tras recibir un catálogo que no incluía opciones de 15€, el agente responde "No tengo ramos de rosas por 15 euros. Los más baratos son los de 25 euros." — afirmación factualmente incorrecta. El catálogo tiene Ramo de Rosas Rosa — M (6 flores, 15€) y Ramo de Rosas Rosa — S (3 flores, 9€).

**Causa raíz:**
En T2, la query con "mas barato" devolvió un subset que no incluía las opciones Rosa (probablemente porque el LLM aplicó algún filtro implícito excluyendo flores de color rosa). Cuando el usuario pidió "la de 15 euros", el agente:
1. Buscó entre los productos YA MOSTRADOS si alguno era de 15€ → ninguno → "no tengo"
2. NO relanzó PetalDataTool con `precio_max=15` o `precio_exacto=15`

La clasificación de input correcta para "la de 15 euros" en este contexto debería ser **REFINAMIENTO** (precio exacto), lo que dispara una nueva query con filtro de precio. El agente lo clasificó como selección fallida de catálogo mostrado.

**Fix propuesto:**
En la `⛔ CLASIFICACION DE INPUT TRAS MOSTRAR OPCIONES ⛔` de `compra.yaml`, reforzar que "la de X euros" cuando X no corresponde a ningún producto mostrado se clasifica como **REFINAMIENTO** (no como intento de selección fallida):

```yaml
2. SELECCION: el usuario elige uno de los mostrados. Si menciona un precio que NO
   corresponde a ningún producto del catálogo actual → NO es selección, es REFINAMIENTO.
   Clasifica como categoría 4 y llama PetalDataTool con precio_max=$X.
```

**Impacto:** media-alta. El usuario recibe información incorrecta sobre el catálogo. Puede perder confianza en el agente.

---

## Bug #4 — Transición a registro sin confirmar email (T10) ← PENDIENTE

**Playbook:** `checkout.yaml` — rama de referencia anafórica → Registro_Task
**Estado:** ⚠️ **PARCIALMENTE CORREGIDO** — el fix del Bug #2 funciona pero la UX es abrupta

**Qué ocurre:**
El agente detecta "ese" como intención de registro (✅ correcto) e invoca Registro_Task directamente. El resultado es que el agente pasa de "¿Quieres probar con otro correo o registrarte?" → "ese" → "¿Cuál es tu nombre?" sin confirmar con qué email se está registrando al usuario.

El usuario no tiene visibilidad de que:
- Se está iniciando el flujo de registro
- El email que se va a usar es javi@gmail.com

**Fix propuesto:**
En la excepción anafórica añadida al BUCLE EMAIL de checkout.yaml, antes de invocar Registro_Task, añadir un mensaje de confirmación:

```yaml
EXCEPCION REFERENCIA ANAFÓRICA: [...] → di según modo:
- Estándar: 'Perfecto, te registro con $email. ¿Cuál es tu nombre?'
- Solemne: 'De acuerdo, procedemos a registrarle con $email. ¿Su nombre, por favor?'
- Corporativo: 'Entendido, registramos $email. ¿Cuál es su nombre?'
Y a continuación invoca ${PLAYBOOK:Registro_Task} pasando email=$email.
```

**Impacto:** medio. El flujo funciona pero el usuario puede quedar confundido por la transición abrupta.

---

## Bugs compartidos con TC-MULTI-PRODUCTO-01

| Bug | TC-MULTI-PRODUCTO-01 | Adhoc registro |
|-----|---------------------|----------------|
| Catálogo no-determinista | Run 3 (subset diferente en T2) | T2 no incluye opciones baratas Rosa S/M |
| Causa raíz | LLM selecciona subset aleatorio del catálogo | LLM no incluye todas las opciones al precio más bajo |

Ambos apuntan al mismo patrón: la query a PetalDataTool con filtros blandos ("mas barato", sin precio_max explícito) devuelve resultados inconsistentes entre runs. Considerar añadir un parámetro `orden=precio_asc` a la tool para anclar el orden de resultados.

---

## Historial git relevante

```
5b812e0  Revert "fix(checkout+compra): ..."         ← HEAD actual (bugs presentes para demo)
74fd071  fix(checkout+compra): loop registro + color ← fix verificado (revertir para restaurar)
dea385d  qa(analysis): TC-MULTI-PRODUCTO-01 run 20260527_1913
```

---

## Próximos pasos

| Acción | Cuándo | Comando |
|--------|--------|---------|
| Restaurar fix (Bug #1 + #2) post-demo | Después de la demo | `git revert 5b812e0 --no-edit && git push origin main` |
| Fix Bug #3 (precio mínimo factual) | Sprint siguiente | Editar clasificación de input en compra.yaml |
| Fix Bug #4 (confirmación email en registro) | Sprint siguiente | Editar excepción anafórica en checkout.yaml |
| Investigar `orden=precio_asc` en PetalDataTool | Backlog | Evaluar si la API lo soporta |
