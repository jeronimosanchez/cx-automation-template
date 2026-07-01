# TC-TONO-CAMBIO-SOLEMNE-01 — Análisis de causa raíz

**Fecha:** 2026-07-01
**Batch:** 20260701_170805
**Estado:** FAIL (0/1 runs PASS)
**Tipo:** EDGE · Grupo: TONO
**Descripción:** Cambio a solemne mid-conversación — revela funeral en turno 2

---

## Resumen ejecutivo

El TC falla por **tres problemas independientes** de distinta gravedad:

1. **Bug Playbook — instrucción interna expuesta** al usuario en turno 2 (crítico, P0).
2. **Bug Test — check mal calibrado** en turno 2: el agente usa "lamento" (sinónimo válido de "siento") pero el patrón `siento|pesame|acompan|...` no lo incluye (incorrecto, P1).
3. **Doble respuesta en turno 1** — posible artefacto de arquitectura multi-playbook, no causa del FAIL pero señal de problema de orquestación (medio, P2).

El FAIL real es consecuencia de los problemas 1 y 2 **combinados**: incluso si el bug de instrucción expuesta se corrige, el check actual seguiría fallando si el agente dice "lamento" en lugar de "siento". Son dos fixes necesarios.

---

## 9 capas de causa raíz

### Capa 1 — Reproducibilidad

- **Status:** FAIL determinista (0/1 passes).
- **Patrón:** El problema de instrucción expuesta es estructural (texto de playbook filtrado al usuario). No es flakiness.

### Capa 2 — Localización del fallo

**Turno 1** (falla el check `not_expected`):
- Check: `FAIL: Agente NO debía decir [mira,|genial|fenomenal|perfecto!|que te parece|🌸]`
- La respuesta real del agente en turno 1 contiene `🌸` en la primera parte de la doble respuesta.
- El not_expected está justificado: el agente está en registro estándar en turno 1 pero la doble respuesta incluye el emoji prohibido.

**Turno 2** (falla el check `expected`):
- Check: `FAIL: Agente debía decir [siento|pesame|acompan|corona|funebr|ceremonia|opciones|sobri]`
- La respuesta real del agente en turno 2: `"De acuerdo, lamento mucho tu pérdida. En este caso, el registro cambia a solemne. Entendido. Para funerales..."`
- **Verificación del check:** `lamento` NO matchea ninguno de los patrones del check (`siento`, `pesame`, `acompan`, `corona`, `funebr`, `ceremonia`, `opciones`, `sobri`). El fallo del check es correcto en la lógica del runner, pero el patrón está incompleto — "lamento mucho tu pérdida" es semánticamente equivalente a "lo siento mucho".

### Capa 3 — Análisis del turno 1 (Doble respuesta + 🌸)

La respuesta del turno 1 es:
```
"¡Claro! 🌸 ¿Tienes alguna flor o color en mente?\n Claro, para un regalo tengo cosas que suelen gustar. ¿Tienes alguna flor o color en mente?"
```

Dos respuestas concatenadas con `\n ` como separador. Hipótesis:

**H1 — Orquestador + Compra responden ambos:** El Orquestador clasifica la intención (`G3`, `$grupo_intent='G3'`) y **emite un primer turno propio** ("¡Claro! 🌸 ¿Tienes alguna flor o color en mente?") antes de transferir a Compra. Compra recibe el control y genera su propio turno. Ambas respuestas llegan concatenadas al usuario.

Evidencia a favor:
- El Orquestador tiene la regla `⛔ NUNCA hagas slot filling multi-turno. Si necesitas más de 1 turno para recoger datos de producto, transfiere a Compra` — pero puede emitir un primer ECO antes de transferir.
- La primera mitad ("¡Claro! 🌸") tiene el estilo del Orquestador en G3 (abre con entusiasmo + emoji).
- La segunda mitad ("Claro, para un regalo tengo cosas que suelen gustar") tiene el estilo de Compra en modo G3/estandar.
- `$grupo_intent='G3'` confirmado en los `params` del turno 1 del run.

**H2 — Dos steps del mismo playbook ejecutando en secuencia:** Menos probable, Compra tiene un solo `steps` (instrucción monolítica).

**Conclusión provisional:** La doble respuesta es un artefacto de arquitectura — el Orquestador emite respuesta antes de transferir a Compra. Es un problema de diseño del playbook del Orquestador para el caso G3 (debería transferir sin responder, o al menos sin emoji en ese contexto). No causa directa del FAIL del TC pero sí causa del fallo del not_expected en turno 1.

### Capa 4 — Análisis del turno 2 (Instrucción interna expuesta)

La respuesta del turno 2 incluye literalmente:
```
"De acuerdo, lamento mucho tu pérdida. En este caso, el registro cambia a solemne."
```

La frase `"En este caso, el registro cambia a solemne."` es texto de instrucción interna filtrado al usuario. La instrucción de Compra dice explícitamente:

> `Actualiza silenciosamente. Propaga $registro, $es_urgente, $usuario_frustrado a Checkout y Handoff. No anuncies el cambio al usuario.`

El agente está violando la regla `No anuncies el cambio al usuario`. El LLM está confundiendo la instrucción meta (cómo debe comportarse) con el contenido de la respuesta. Esto es un **Bug Playbook de tipo Instrucción Expuesta** — el LLM mezcla la capa de razonamiento con la capa de respuesta.

**Causa probable:** La instrucción `$registro=solemne` en la sección VIGILANCIA DE CAMBIO está estructurada como un bloque de acción interna (`-> $registro=solemne`) pero el LLM la interpreta como algo que debe comunicar. La instrucción no tiene suficiente énfasis en el silencio del cambio en ese contexto específico.

### Capa 5 — Análisis del check del turno 2 (Calibración)

El check espera: `siento|pesame|acompan|corona|funebr|ceremonia|opciones|sobri`

Lo que el agente dijo: `"lamento mucho tu pérdida"` + `"Para funerales, en ramos tenemos"`

- `lamento` ≠ ningún patrón del check → el runner marca FAIL correctamente.
- Pero `lamento mucho tu pérdida` es semánticamente equivalente a `lo siento mucho` o `le acompaño en el sentimiento`.
- El patrón `funebr` debería haber matcheado `"Para funerales"` (la raíz `funebr` vs `funeral` — `funeral` contiene `funebr`? No: `funebr` como regex matchea `funebre`, `funebres`, pero NO `funeral` porque `funeral` no contiene `funebr`).

**Verificación:** `funebr` vs `funeral` — la cadena `funeral` contiene `f-u-n-e-r-a-l`, no `f-u-n-e-b-r`. Son raíces distintas en español: `fúnebre` (adjetivo) vs `funeral` (sustantivo). El check usa `funebr` para capturar `fúnebre/funebres` pero NO captura `funeral`.

Además `opciones` debería haber matcheado en `"Para funerales, en ramos tenemos: [opciones]"` — la palabra `opciones` NO aparece literalmente en la respuesta real. El agente no usó la palabra `opciones`; mostró las opciones directamente sin encabezarlas con esa palabra.

**Conclusión:** El check tiene dos problemas acumulados:
1. `funebr` no captura `funeral` (falso negativo de patrón).
2. `lamento` no está incluido como alternativa de `siento` (patrón incompleto).
3. `opciones` no aparece en la respuesta (el agente muestra el catálogo sin usar esa palabra introductoria).

### Capa 6 — Estado de $registro y $ocasion_detectada

Los `params` del turno 2 muestran:
```json
{"ocasion_detectada": "Regalo", "grupo_intent": "G3", "intencion_inicial": "quiero un ramo bonito para regalar"}
```

- `$ocasion_detectada` sigue siendo `"Regalo"` en turno 2 → **no se actualizó a "Funeral/Sepelio"**.
- `$registro` no aparece en los params del run (el runner de QA no lo captura directamente).

La actualización de `$registro` a `solemne` es interna al playbook (no siempre visible en los parámetros de sesión registrados). Sin embargo, la respuesta del agente contiene la frase expuesta `"el registro cambia a solemne"`, lo que confirma que el modelo SÍ detectó el duelo y activó el cambio — pero lo verbalizó.

**Respecto a `$ocasion_detectada`:** El input del turno 2 ("es para el tanatorio de mi padre, ha fallecido esta mañana") debería haber actualizado `$ocasion_detectada` a `"Funeral"`. Que siga en `"Regalo"` puede ser:
- Un artefacto del runner (captura el valor inicial, no el actualizado).
- O que el playbook de Compra no actualiza `$ocasion_detectada` en su VIGILANCIA DE CAMBIO — esa variable la establece el Orquestador en el enrutado inicial, y Compra solo gestiona `$registro`.

La instrucción de Compra dice en VIGILANCIA DE CAMBIO:
```
DUELO ('funeral','fallecimiento','entierro','velatorio','ha muerto','difunto','luto')
-> $registro=solemne
```

Nota que la lista de palabras DUELO en Compra incluye `'ha muerto'` pero NO incluye `'tanatorio'` ni `'ha fallecido'`. Sin embargo, el Orquestador SÍ incluye `"tanatorio"` y `"ha fallecido"` en su lista DUELO. El input del usuario contiene `"tanatorio"` y `"ha fallecido"` — ambas reconocidas por el Orquestador pero NO por la lista de Compra.

**En este flujo, el Orquestador ya transfirió a Compra en turno 1.** En turno 2, quien procesa es Compra. La lista DUELO de Compra no incluye `tanatorio` ni `ha fallecido`. Sin embargo, el agente claramente activó el cambio (dice "el registro cambia a solemne"), lo que sugiere que el LLM es capaz de inferir el contexto aunque la lista exacta no incluya todas las palabras. El LLM no está siendo estricto con la lista — está usando comprensión semántica.

### Capa 7 — Severidad por problema

| # | Problema | Tipo | Severidad | Causa |
|---|---|---|---|---|
| P0 | Instrucción interna expuesta al usuario ("el registro cambia a solemne") | Bug Playbook | CRÍTICA | Instrucción de silencio insuficientemente reforzada en VIGILANCIA DE CAMBIO |
| P1 | Check turno 2 incompleto (`lamento` no está, `funebr` no captura `funeral`) | Bug Test | ALTA | Patrón regex insuficiente |
| P2 | Doble respuesta turno 1 (Orquestador + Compra concatenados) | Bug Arquitectura / Playbook | MEDIA | Orquestador emite respuesta antes de transferir silenciosamente a Compra en G3 |
| P3 | Lista DUELO en Compra no incluye `tanatorio` / `ha fallecido` | Bug Playbook (latente) | BAJA | El LLM compensa semánticamente pero la cobertura es inconsistente con el Orquestador |

### Capa 8 — Causa raíz unificada

El TC falla por la **combinación de P0 (Bug Playbook) + P1 (Bug Test)**:

- Si solo se corrige P0 (se elimina la instrucción expuesta), el check seguirá fallando porque `lamento` no está en el patrón.
- Si solo se corrige P1 (se añade `lamento` al check), el TC podría pasar en el runner, pero el agente seguiría exponiendo instrucciones internas (UX rota).
- La corrección completa requiere **ambos fixes en paralelo**.

P2 (doble respuesta) no causa el FAIL del TC directamente (el not_expected detecta el emoji 🌸 en turno 1) pero sí causa el fallo del not_expected. Su fix es independiente y más complejo (arquitectura de orquestación).

### Capa 9 — Patrón con otros TCs

TC-TONO-PRECEDENCIA-01 (PASS) usa `"necesito flores para el funeral de mi jefe"` en turno 1 (no hay cambio mid-conversación) y no expone instrucciones internas. El problema de exposición es específico del **cambio mid-conversación**: cuando el LLM detecta el cambio, lo anuncia como si fuera parte del razonamiento visible.

Esto sugiere que el patrón `No anuncies el cambio al usuario` necesita refuerzo con un ⛔ y un example explícito de lo que NO decir.

---

## Soluciones propuestas (orden DESC por score)

### Solución 1 — Fix Test: ampliar patrón check turno 2 [SCORE: 95]

**Tipo:** Bug Test
**Archivo:** `qap/tc_1_0.yaml`
**Tiempo estimado:** 5 min
**Riesgo:** Mínimo

**Cambio concreto:**
```yaml
# Antes (línea ~748 en tc_1_0.yaml):
- siento|pesame|acompan|corona|funebr|ceremonia|opciones|sobri

# Después:
- siento|lament|pesame|acompan|corona|funebr|funeral|ceremonia|sobri
```

Razonamiento:
- Añadir `lament` para capturar `lamento`, `lamentamos`, `lamentablemente`.
- Añadir `funeral` (la palabra que el agente usó realmente: "Para funerales").
- Eliminar `opciones` del check (el agente nunca la usa — muestra las opciones sin esa palabra introductoria).
- Eliminar `sobri` (ninguna respuesta real usa esta raíz, es un falso positivo de expectativa).

**Nota:** Este fix hace que el TC pueda pasar en el runner incluso con el bug P0 activo (si el LLM no expone la instrucción en ese run). Debe ir acompañado del fix P0.

---

### Solución 2 — Fix Playbook: reforzar silencio en VIGILANCIA DE CAMBIO [SCORE: 90]

**Tipo:** Bug Playbook
**Archivo:** `definitions/playbooks/compra.yaml`
**Tiempo estimado:** 10 min
**Riesgo:** Bajo

**Cambio concreto** en la sección VIGILANCIA DE CAMBIO de `compra.yaml`:

```yaml
# Antes:
VIGILANCIA DE CAMBIO (por turno):
Si el usuario menciona:
- DUELO ('funeral','fallecimiento','entierro','velatorio','ha muerto','difunto','luto')
  -> $registro=solemne
...
Actualiza silenciosamente. Propaga $registro, $es_urgente, $usuario_frustrado a Checkout y Handoff.
No anuncies el cambio al usuario.

# Después:
VIGILANCIA DE CAMBIO (por turno):
Si el usuario menciona:
- DUELO ('funeral','fallecimiento','tanatorio','entierro','velatorio','ha muerto','ha fallecido','difunto','luto')
  -> $registro=solemne
...
⛔ ACTUALIZA SILENCIOSAMENTE. NUNCA digas al usuario 'el registro cambia a solemne' ni ninguna variante.
⛔ El cambio de registro es INTERNO. Lo que el usuario recibe es directamente la respuesta en tono solemne.
Propaga $registro, $es_urgente, $usuario_frustrado a Checkout y Handoff.
```

Dos mejoras en un mismo cambio:
1. Refuerzo del silencio con ⛔ y prohibición explícita.
2. Ampliación de lista DUELO en Compra para incluir `tanatorio` y `ha fallecido` (alineación con el Orquestador).

---

### Solución 3 — Fix Playbook: eliminar respuesta del Orquestador antes de transferir en G3 [SCORE: 60]

**Tipo:** Bug Arquitectura / Playbook
**Archivo:** `definitions/playbooks/petal_cx_orchestrator.yaml`
**Tiempo estimado:** 15-20 min + validación con suite completa
**Riesgo:** MEDIO — afecta comportamiento de G3 global, puede impactar otros TCs

**Problema:** En G3, el Orquestador emite un turno propio ("¡Claro! 🌸 ¿Tienes alguna flor o color en mente?") antes de transferir a Compra. Compra genera su propio turno. El resultado es una doble respuesta concatenada.

**Cambio concreto** en la instrucción G3 del Orquestador:

```yaml
# Antes (en bloque G3 del Orquestador):
G3 RECOMENDACION (...)
⛔ NO explores en el Orquestador. Captura y transfiere.
...
- ${PLAYBOOK:Compra} con $intencion_inicial, $ocasion_detectada, $grupo_intent, $precio_max.

# Después:
G3 RECOMENDACION (...)
⛔ NO explores en el Orquestador. Captura y transfiere.
⛔ NO emitas ninguna respuesta al usuario antes de la transferencia. La transferencia es SILENCIOSA.
- ${PLAYBOOK:Compra} con $intencion_inicial, $ocasion_detectada, $grupo_intent, $precio_max.
```

**Precaución:** Este cambio puede afectar a TC-N01 ("Recomendación — transfiere a Compra") y otros TCs de G3 que esperan una cierta fluidez. Requiere rerun de suite tras el cambio.

**Alternativa menos arriesgada:** No eliminar la respuesta del Orquestador pero añadir la anti-regla `⛔ en G3 sin emoji` al bloque de identidad del Orquestador para que el not_expected del turno 1 no falle. Esto es un parche, no una solución estructural.

---

## Recomendación

1. **Solución 1** (Fix Test, 5 min) — aplica primero para que el runner refleje la realidad.
2. **Solución 2** (Fix Playbook Compra, 10 min) — aplica segundo, cierra el bug crítico P0.
3. Rerun del TC para verificar ambos fixes.
4. **Solución 3** (Fix Orquestador, 15-20 min) — aborda la doble respuesta, tratar como tarea separada con gate de validación de suite completa.

---

## Metadatos

| Campo | Valor |
|---|---|
| Bugs encontrados | 3 (P0 Playbook crítico · P1 Test · P2 Arquitectura) |
| Archivos afectados | `qap/tc_1_0.yaml` · `definitions/playbooks/compra.yaml` · `definitions/playbooks/petal_cx_orchestrator.yaml` |
| TCs relacionados | TC-TONO-PRECEDENCIA-01 (PASS, patrón similar sin cambio mid-conv) · TC-FUNERAL-01 (PASS) |
| Fix mínimo para PASS | Sol. 1 + Sol. 2 |
| Riesgo de regresión | BAJO (Sol. 1+2) / MEDIO (Sol. 3) |
