# Auditoría — Contradicciones del refactor parcial `especie` en Compra

**Fecha:** 2026-07-05
**Alcance:** `definitions/playbooks/compra.yaml` + 5 examples modificados hoy (`exa_v9`, `exb_v15`, `exc_v9`, `exg_v15`, `exh_v16`).
**Modo:** solo lectura. No se editó ningún artefacto.

---

## Resumen ejecutivo

El refactor introdujo la lógica nueva `especie` (filtro exacto) en el **parseo** (PASO 1.1, DESAMBIGUACION ROSAS, FLUJO TURNO INICIAL, TOOLS) pero **NO tocó los dos guardarraíles que deciden si un input es "suficiente para mostrar"**:

1. **PASO 1 — `PRODUCTO EXACTO vs GENERICO`** (línea 240): sigue clasificando la flor sin tamaño como GENÉRICO → no atajo a mostrar.
2. **PASO 1.5 — TABLA DE SUFICIENCIA** (líneas 288-292): **no lista `especie`** como slot suficiente. Solo cuenta ocasión/tipo/color/precio.

Consecuencia directa: cuando el usuario dice "rosas" (solo `especie`), el playbook lo trata como "sin slot suficiente" y **pregunta** (ocasión/color) en vez de mostrar. Ese es el origen de los síntomas B y A.

Y lo más grave: **`exh_v16` (modificado hoy) enseña literalmente el anti-patrón**. Su input es "quiero rosas" y modela dos preguntas seguidas (ocasión → color) antes de mostrar. El LLM está siendo entrenado con el bug. El caso simétrico correcto ("unas rosas → muestra directo") solo existe como texto teórico en EJEMPLO 5 dentro del playbook, sin un example real que lo respalde.

---

## Tabla de hallazgos

| Síntoma | Bloque / línea exacta | Qué dice hoy (contradicción) | Fix propuesto |
|---|---|---|---|
| **B** (pregunta slot innecesario) | `compra.yaml` L288-292 **PASO 1.5 / TABLA DE SUFICIENCIA** | Lista como suficiente solo: `$ocasion_detectada`, `Tipo/color/precio_max/precio_min`. **NO incluye `especie`.** L292: "NINGUN slot - pregunta". Con la lógica nueva, "rosas" rellena `especie` pero la tabla no lo cuenta → cae en "NINGUN slot" → pregunta. | Añadir línea: `- especie mencionada - SUFICIENTE - PASO 2` (o a EXPLORAR / FLUJO TURNO INICIAL). Cualquier `especie` no vacía debe atajar a mostrar. |
| **B** (pregunta slot innecesario) | `compra.yaml` L240-243 **PASO 1 — PRODUCTO EXACTO vs GENERICO** | "Exacto solo si se especifica tamano". "rosas rojas" (especie+color, sin tamaño) = GENÉRICO → "continua" (no atajo). El criterio de exactitud sigue anclado a `producto`+tamaño de la lógica vieja; ignora que especie+color ya es suficiente para mostrar variantes. | Añadir rama: `Si $especie (con o sin color) Y sin tamaño - PASO EXPLORAR / FLUJO TURNO INICIAL (mostrar variantes)`, no seguir a la cascada de preguntas. |
| **B / A** (regresión de example) | `examples/compra/exh_v16` L6-23 | Input `quiero rosas` (solo especie). El example modela **DOS preguntas seguidas**: turno 1 "¿Es para alguna ocasión especial?" → turno 2 "¿Tienes preferencia de color?" → recién entonces tool call + muestra. Enseña exactamente "pregunta ocasión/color cuando ya hay slot suficiente (especie)". Es el patrón B, y el `executionSummary` (L81) lo canoniza como correcto ("PASO 1.5: agente pregunta ocasión... luego color"). | Rehacer el example para que "quiero rosas" (G5, solo especie) → **tool call directo** `especie=rosas` con ocasión inferida (Regalo) → muestra 3 variantes → APERTURA. Es el patrón de EJEMPLO 5 del playbook (L645-649), hoy sin example que lo respalde. |
| **A** (doble mensaje: pregunta + muestra) | `compra.yaml` L294 (PASO 1.5) ↔ L301-306 (FLUJO TURNO INICIAL) + L288-292 | Choque de dos rutas: PASO 1.5 dice "pregunta"; FLUJO TURNO INICIAL dice "llama inventario + muestra". Con especie presente pero no listada como suficiente, el LLM recibe señal ambigua (¿pregunto o muestro?) y **hace ambas en el mismo turno**: "¿Para qué ocasión? Claro, tenemos tulipanes blancos en S/M/L…". El opener emocional (L302) agrava: se formula como pregunta ("¿para quién es?") y luego el mismo turno se auto-responde mostrando. | (1) Resolver la suficiencia de `especie` (fixes de arriba) elimina la ambigüedad. (2) En FLUJO TURNO INICIAL L302, aclarar que el opener emocional es **eco afirmativo**, no pregunta, cuando ya hay especie/filtros suficientes: mostrar directo, no preguntar-y-mostrar. |
| **A** (doble mensaje) | `compra.yaml` L186-213 **ESTRUCTURA DE TURNO (ECO + CONTINUIDAD + APERTURA)** | La estructura permite CONTINUIDAD = "preguntar un slot" O "mostrar opciones" (L198), y siempre cierra con APERTURA = una pregunta (L200). No prohíbe que un turno "muestre" (continuidad) y a la vez incruste una pregunta de slot en la apertura. Combinado con la ambigüedad de suficiencia, produce "muestro productos + ¿para qué ocasión?". | Añadir regla explícita: si el turno MUESTRA productos, la APERTURA es invitación a iterar sobre lo mostrado ("¿alguna encaja?"), NUNCA una pregunta por un slot de contenido (ocasión/color) que ya no hace falta. Un turno pregunta-slot **o** muestra; no ambas. |
| **C** (duplica info / reconfirma) | `compra.yaml` L575-590 **REGLAS DE MEMORIA Y FILTROS** (R1 productos_mostrados, R2 persistencia, R5 acumulación) | Las reglas existen para NO repetir (`productos_excluidos=$productos_mostrados`). Pero dependen de que el flujo llegue a mostrar una sola vez. Como especie no es suficiente, el turno 1 pregunta y a veces también muestra parcial; el turno 2 vuelve a mostrar/reconfirmar lo mismo ("¿te refieres a lirios blancos?") porque el slot ya establecido (especie) no se consolidó como cerrado. La reconfirmación viene de que PASO 1.5 no reconoce especie como resuelta. | Mismo fix raíz: reconocer `especie` como slot cerrado en PASO 1.5. Reforzar en ESTRUCTURA DE TURNO L201-202 ("Si ya tienes el valor de un slot, úsalo sin pedirlo") extendiéndolo explícitamente a `especie`. No es un bug nuevo de memoria; es secuela de la no-suficiencia. |
| B (menor, coherencia) | `compra.yaml` L296 **PASO PRECIO** | "Extrae producto... Tiene tipo+**flor**+color... Solo **flor** - filtros reducidos". Usa vocabulario viejo ("flor", "producto") sin decir que la flor va a `especie`. No rompe por sí solo (el tool call sí usa especie vía L598-599), pero es andamiaje viejo que contradice terminológicamente el rewire y puede confundir al LLM sobre dónde colocar la flor en la consulta de precio. | Alinear con v41: "Solo especie → filtros reducidos con `especie=<flor>`". Coherencia terminológica con L303-304, L598-599, L612. |

---

## Análisis por punto de la auditoría

**1. TABLA DE SUFICIENCIA (PASO 1.5).** Confirmado el bug. L288-292 NO lista `especie`. "quiero rosas" cae en "NINGUN slot" → pregunta. Es la causa raíz de B. Es **contradicción directa del refactor parcial**: el parseo produce `especie` pero la tabla de decisión no la conoce.

**2. PASO PRECIO y demás pasos.** PASO PRECIO (L296) conserva "flor"/"producto" viejos — contradicción terminológica menor, no bloqueante. PASO 1 EXACTO/GENERICO (L240) sí es bloqueante: ancla exactitud a tamaño+producto, ignora especie+color.

**3. FLUJO TURNO INICIAL / opener emocional.** L301-306. El opener emocional (L302) "abre con muestra contexto emocional ANTES de mostrar" se presta a formularse como pregunta y auto-responderse en el mismo turno. Es el origen probable del doble-mensaje (A), agravado por la ambigüedad pregunta-vs-mostrar de la suficiencia.

**4. Lista FLORES + DESAMBIGUACION (C1).** Coherente con la salida `especie`. DESAMBIGUACION ROSAS (L261-275) fue reescrita a v41 y ya emite `especie=<flor>`. No quedan referencias a `producto` para flores en este bloque. **Aquí el refactor sí se completó.**

**5. Reglas mostrar-hasta-3 / persistencia (C).** Las reglas de memoria (L575-590) son correctas en sí. La duplicación entre turnos es **secuela** de la no-suficiencia de especie (el slot no se consolida como cerrado), no un bug independiente.

**6. Los 5 examples.**
- `exa_v9`: **correcto**. Input ya trae ocasión (Regalo del Orquestador) + `especie=rosas`+color → tool call directo → muestra 3 tamaños. Modela bien el patrón nuevo.
- `exb_v15`: correcto. Funeral por categoría, luego `especie=gladiolos`. Coherente.
- `exc_v9`: correcto. Consulta precio con `especie=tulipanes`, muestra directo, sin preguntas espurias.
- `exg_v15`: **ambiguo/tolerable**. Es refinamiento progresivo legítimo (G3, arranca sin flor: "quiero un ramo"), pregunta flor→color de forma escalonada. No es el mismo caso que B porque el input inicial NO trae especie. No enseña el bug, pero refuerza el patrón "preguntar en cascada" que el LLM puede sobre-generalizar.
- `exh_v16`: **REGRESIÓN CLARA.** Input "quiero rosas" (especie presente) → pregunta ocasión → pregunta color → recién muestra. Enseña exactamente el síntoma B (y contribuye a A/C). Su `executionSummary` canoniza la doble pregunta como comportamiento correcto. Es el example que más daño hace hoy.

---

## Veredicto: origen de cada bug

| Origen | Peso | Detalle |
|---|---|---|
| **(a) Contradicción del refactor parcial** | **~60%** | El corazón del bug. PASO 1.5 (L288-292) y PASO 1 EXACTO/GENERICO (L240) no fueron actualizados para reconocer `especie` como slot suficiente. El parseo produce especie; la lógica de decisión la ignora. Causa B directamente y habilita A y C. |
| **(b) Regresión de los 5 examples de hoy** | **~30%** | Concentrada en **`exh_v16`**, que modela el doble-mensaje/pregunta-espuria para "quiero rosas". `exg_v15` refuerza secundariamente el patrón cascada. Los otros 3 (exa, exb, exc) son correctos. El LLM copia `exh_v16` porque es el vecino más cercano al input "quiero rosas". |
| **(c) Pre-existente sin relación con especie** | **~10%** | La ESTRUCTURA DE TURNO (L186-213) siempre permitió "mostrar + cerrar con pregunta". No prohíbe explícitamente pregunta-de-slot dentro de un turno que muestra. Pre-existe al refactor, pero solo se manifiesta como bug cuando la suficiencia de especie falla. El opener emocional (L302) también es pre-existente. |

---

## Lista priorizada de fixes

1. **[RAÍZ] PASO 1.5 — añadir `especie` a la TABLA DE SUFICIENCIA** (L288-292). Una línea: `especie mencionada → SUFICIENTE → mostrar`. Corta B de raíz y desactiva la ambigüedad que causa A. **Máximo impacto, mínimo cambio.**

2. **[RAÍZ] Rehacer `exh_v16`** para que "quiero rosas" → tool call directo `especie=rosas` (ocasión inferida) → muestra → APERTURA. Elimina el example que enseña el bug. Sin esto, el fix 1 lucha contra el example.

3. **PASO 1 — EXACTO/GENERICO (L240-243):** añadir rama para especie(+color) sin tamaño → mostrar variantes, no seguir a preguntas.

4. **ESTRUCTURA DE TURNO (L186-213):** regla explícita "un turno pregunta-slot O muestra, nunca ambas; si muestra, la APERTURA es iterativa sobre lo mostrado". Cierra el residual de A.

5. **FLUJO TURNO INICIAL (L302):** aclarar que el opener emocional es eco afirmativo, no pregunta, cuando ya hay slot suficiente.

6. **[COSMÉTICO] PASO PRECIO (L296):** alinear terminología "flor"→`especie`. No urgente.

**Nota sobre `exg_v15`:** revisar si conviene marcar que su cascada de preguntas es legítima SOLO porque el input arranca sin flor (G3), para que no se sobre-generalice al caso con especie presente. Prioridad baja.

---

*Auditoría de solo lectura. No se modificó `compra.yaml` ni ningún example.*
