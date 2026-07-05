# Cambios playbook Compra — rewire flor→especie + poda DECORACION + tono fallback (v41)

Fecha: 2026-07-04 · Alcance: solo edición local, sin push/deploy. Etiqueta de versión nueva en comentarios: **v41**.

## Contexto (backend en producción, verificado)
- Nuevo param `especie=<flor>`: filtro EXACTO por especie botánica. Es el último en relajarse en la escalera de fallback (tras color y producto), emitiendo `fallback=especie_relajada`.
- Columna `Categoria_Uso` ELIMINADA. `categoria`/`motivo` ahora filtran contra `Ocasion`. "Decoracion" vive en `Ocasion` como una ocasión normal.
- Fallbacks del backend: `color_relajado`, `producto_y_color_relajados`, `sin_filtros_opcionales`, `especie_relajada`.

---

## CAMBIO 1 — Rewire flor: `producto=<flor>` → `especie=<flor>`

La flor deja de rutearse al param fuzzy `producto` y pasa al param exacto `especie`. `producto` se conserva para nombres de producto reales (ej "ramo de novia", "corona"). La lista `FLORES` se mantiene (vocabulario de reconocimiento). La lógica NLU flor-vs-color se conserva intacta.

Bloques tocados en `definitions/playbooks/compra.yaml`:

| Bloque | Antes → Después |
|---|---|
| PASO 1.1 PARSEO DE SLOTS (~L251-254) | `producto=rosas` → `especie=rosas` en los 3 ejemplos de separación de slots. Añadido `tipo=Ramo` al ejemplo "un ramo de rosas rojas". |
| DESAMBIGUACION ROSAS (~L261-274) | Título "PRODUCTO vs COLOR" → "ESPECIE vs COLOR". Reglas 2, 4, 5 y ejemplos: salida flor `producto=…` → `especie=…`. Añadida nota: la lógica NLU se mantiene, solo cambia el param de salida cuando es flor; el color sigue en `color`. |
| FLUJO TURNO INICIAL paso 2 (~L302) | Lista de slots al tool: `producto (si flor)` → `especie (si flor)`. |
| CRITICO TT-28 (~L303, era v39/v40) | Reescrito a v41: flor del listado FLORES → SIEMPRE `especie=<flor>`. Aclara que `producto` se reserva para nombres de producto reales. |
| REGLA CRITICA - INVENTARIO (# TOOLS, ~L596-599) | Ahora lista `especie: <flor pedida>` (exacto) + `producto: <nombre de producto real, solo si aplica>`. |
| HERRAMIENTAS (~L611) | Lista de filtros del tool: añadido `especie`; nota "la flor va en especie; producto para nombres reales". |
| EJEMPLO 5 (~L646-648) | `producto=Rosas` → `especie=Rosas` (incluye la variante "sin producto" → "sin especie"). |
| EJEMPLO 6 caso B (~L655-656) | `producto=tulipanes` → `especie=tulipanes`. |

**Conservado sin cambios:** lista `FLORES`, PASO PRECIO, lógica tipo/color/precio, TT-25 (`Llama PetalDataTool producto=$producto` = nombre exacto confirmado, sigue siendo `producto`), modo variedad, TCs.

---

## CAMBIO 2 — Poda C2 (MAPEO DECORACION)

Eliminada la regla "CRITICO v40 (TC-DECO-01/02) MAPEO DECORACION" que obligaba a pasar `categoria='Decoracion'` en vez de `ocasion='Decoracion'`. Ya no aplica: Decoracion vive en `Ocasion`, el agente la pasa como cualquier ocasión normal. La excepción TT-28 que contenía (flor→producto+categoria=Decoracion) desaparece junto con la regla; el rewire flor→especie del CAMBIO 1 la cubre.

- Antes: bloque completo `⛔ CRITICO v40 (TC-DECO-01/02) MAPEO DECORACION: … pasa categoria='Decoracion' … NO ocasion='Decoracion' …`
- Después: eliminado. El paso 2 del FLUJO TURNO INICIAL ahora sólo lista los slots normales (con `especie` para flor).

---

## CAMBIO 3 — Comunicar el fallback con tono cálido (intención, no literal)

En "LECTURA RESPONSE API" (~L339-347):
- Añadida línea para `fallback='especie_relajada'`: la especie exacta pedida no está disponible; informar con naturalidad y proponer alternativas, aplicando `$registro`.
- Añadido bloque **⛔ TONO ANTE CUALQUIER fallback (v41)**: ante cualquier campo `fallback` (color_relajado, producto_y_color_relajados, especie_relajada, sin_filtros_opcionales), la intención del turno es cálida e invitacional:
  (a) reconoce con naturalidad que no tenemos lo exacto,
  (b) menciona que sí hay alternativas,
  (c) INVITA a mostrarlas ("¿te enseño algunas?"),
  (d) NO vuelca la lista de golpe; muestra "los más habituales" (ya ordenados por ventas).
- **No** se escribe el mensaje literal: sólo la intención. El tono concreto se enseña con el nuevo example.

---

## Examples

### Modificados (routing `producto`→`especie` en `inputActionParameters`, sólo cuando el valor es una flor)
- `exa_v9_ramo_rosas_rojas_elige_tamao_confirma.yaml` — `producto: rosas` → `especie: rosas`.
- `exb_v15_funeral_tipoproducto_con_filtros.yaml` — `producto: gladiolos` → `especie: gladiolos`.
- `exc_v9_consulta_precio_tulipanes_no_compra.yaml` — `producto: tulipanes` → `especie: tulipanes`.
- `exg_v15_refinamiento_progresivo_filtros_acumulados.yaml` — `producto: rosas` → `especie: rosas`.
- `exh_v16_g5_genrico_paso_1.5_contexto_refinamiento.yaml` — `producto: rosas` → `especie: rosas`.

Los `producto: <nombre de producto real>` en `outputActionParameters` (ej "Ramo de Rosas Rojas — M") se conservan. Los `categoria: regalo/funeral/boda` de exd/exb/exf son ocasión-categoría, no flor, y quedan intactos (fuera de alcance).

### Añadido
- `exi_v1_fallback_rosas_azules_tono_calido.yaml` — NUEVO. Usuario pide "rosas azules"; el backend relaja el color (`fallback=color_relajado`) y devuelve rosas en otros colores ordenadas por ventas. Petal reconoce ("Rosas azules justo no tenemos… pero sí en otros colores preciosos. ¿Te enseño las más pedidas?"), invita, y sólo tras el "sí" vuelca las opciones con APERTURA. Misma estructura de campos que los examples existentes.

---

## Validación
`python3 -c "import yaml; yaml.safe_load(...)"` — OK en `compra.yaml` y en los 9 examples de `definitions/examples/compra/`.

## Dudas / puntos no del todo seguros
1. **Example de tono, elección de `fallback`:** el prompt sugiere "rosas azules". Usé `fallback=color_relajado` (rosas existen, azul no) por ser el encaje más natural para ese input, en vez de `especie_relajada` (que aplicaría si no existiera la especie). El bloque de tono v41 cubre ambos casos por igual, así que el aprendizaje de tono es transferible. Si se prefiere un example que ejercite específicamente `especie_relajada`, se puede ajustar el input a una flor inexistente.
2. **`categoria` en examples exd/exb/exf/exg/exh:** los dejé como `categoria: <ocasion>` (regalo/funeral/boda). Con la eliminación de `Categoria_Uso`, el backend filtra `categoria` contra `Ocasion`, así que siguen siendo válidos. No los toqué porque no son routing de flor y quedan fuera del alcance declarado.
3. **`producto_2` (multi-producto):** el flujo multi-producto usa `producto`/`producto_2` como nombres de producto elegidos (salida), no como flores de entrada — no requieren cambio. No toqué el modo variedad según instrucción.
