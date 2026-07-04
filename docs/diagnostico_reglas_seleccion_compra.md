# Diagnóstico reglas de selección de producto — compra.yaml

> Alcance: reglas de `instruction.steps` relacionadas con selección / búsqueda / filtrado / recomendación de producto. Solo lectura. No se ha modificado ningún artefacto.
>
> Contexto de datos (verificado en vivo 2026-07-04): el backend `petal-sheet-api` YA filtra server-side por `color`, `precio_max`, `ocasion`, `tamano`, `categoria`, `tipo`, `producto` (fuzzy), `motivo` (legacy), `productos_excluidos`, `limit`. NO filtra por `flor` (no existe el param y la columna `Flor` está 100% vacía). NO hace proyección (devuelve las 16 columnas). `Ocasion` es CSV multi-valor con match "contains".

---

## Reglas encontradas (por bloque de instrucción)

| Regla (resumen) | Ubicación aprox | Clasificación | Hueco que compensa / motivo |
|---|---|---|---|
| PASO 1.1 — parseo de slots (separar producto/color/cantidad de la frase) | L250-256 | LEGÍTIMA | NLU de entrada. El backend no ve la frase cruda. |
| Listado hardcodeado de COLORES (14 valores) | L258 | COMPENSATORIA (parcial) | El backend no expone catálogo de colores válidos; el LLM debe adivinarlos para poblar el param `color`. |
| Listado hardcodeado de FLORES (~28 especies) | L259 | **COMPENSATORIA** | Hueco 1: no hay param `flor` + columna `Flor` vacía. El LLM mantiene la taxonomía de especies en el prompt porque el dato no existe en la capa de datos. |
| DESAMBIGUACION 'ROSAS' producto vs color (6 reglas + ejemplos) | L261-274 | **COMPENSATORIA** | Hueco 1 (derivado): al no haber campo `flor`, "rosas" solo puede resolverse contra el nombre compuesto vía `producto` fuzzy. La ambigüedad flor/color se resuelve 100% en el prompt. |
| PARSEO PRECIOS (máximo/mínimo/rango/aprox/"gastarme X") | L276-281 | LEGÍTIMA | NLU de entrada → deriva `precio_min`/`precio_max`/`pres_duro`. El backend solo recibe números. |
| TABLA DE SUFICIENCIA (cualquier slot basta, vacío total → 1 pregunta) | L287-292 | LEGÍTIMA | Política de UX / cuándo preguntar. |
| MAPEO DECORACION → `categoria` NO `ocasion` (v40, TC-DECO-01/02) | L304 | **COMPENSATORIA** | Hueco 3 + modelado: "Decoracion" vive en `Categoria_Uso`, no en `Ocasion`. El LLM debe recordar en qué columna cae cada concepto porque el backend no unifica ocasión/categoría. |
| TT-28 "si mencionó flor del listado, SIEMPRE pasar `producto`=flor" | L303 | **COMPENSATORIA** | Hueco 1: como no hay filtro `flor`, se fuerza el fuzzy `producto` para no perder el criterio de búsqueda del usuario. |
| CLASIFICACION DE INPUT tras mostrar (6 categorías) | L308-328 | LEGÍTIMA | Gestión de estado conversacional. No es filtrado de datos. |
| FLUJO TURNO DE ALTERNATIVAS (mantener filtros + productos_excluidos) | L330-334 | LEGÍTIMA (con matiz) | Orquesta re-consulta. El `productos_excluidos` SÍ lo aplica el backend; aquí solo se gestiona el acumulador. |
| LECTURA RESPONSE API (fallbacks color_relajado / producto_y_color / sin_filtros) | L339-344 | LEGÍTIMA | Interpreta señales que el backend YA emite. Correcto: reacciona a lo que el server decidió. |
| PRESENTACION VARIANTES S/M/L — "completa hasta 3 con MISMA OCASION+COLOR" | L346-350 | **REDUNDANTE / COMPENSATORIA** | El backend ya filtra por ocasión y color. "Completar hasta 3" replica lógica de selección que el WHERE + limit deberían cubrir; el LLM re-filtra en contexto. |
| DISAMBIGUACION TAMAÑO/PRECIO (TT-11): PASO 0 match unívoco + Caso A/B | L352-383 | LEGÍTIMA | Resuelve lenguaje coloquial ("la mediana", "la barata") contra las opciones ya mostradas. NLU sobre resultados, no filtrado. |
| Secuencia slot-filling: ocasion-tipo-flor-color-tamano-cantidad | L390 | LEGÍTIMA (con matiz) | Política de recogida. Incluye "flor" como slot que no tiene destino real en el backend. |
| "UN tool call por turno con TODOS los filtros" | L391 | LEGÍTIMA | Optimización de llamadas. Buena práctica. |
| REGLA CANTIDAD > STOCK (TT-25): 2ª llamada para leer `stock` | L396-405 | LEGÍTIMA (con matiz) | Lógica de negocio (no vender más que stock). Requiere 2ª llamada porque no hay endpoint de validación de cantidad. |
| RESULTADOS PARCIALES CON FILTRO NO CUMPLIDO (v39) | L514-525 | LEGÍTIMA | Grounding conversacional: informar de qué filtro no se cumplió. Reacciona a `count`/`fallback` del backend. |
| REGLA PLACEHOLDER [otros tipos disponibles] (no inventar tipos) | L527-534 | **COMPENSATORIA** | Hueco 2 (parcial) + anti-alucinación: el LLM no tiene forma barata de saber qué tipos existen para una ocasión sin haberlos consultado, así que se prohíbe inventar. |
| FALLBACK DE AGOTAMIENTO (`sin_mas_opciones=true` → agent_copy) | L538-540 | LEGÍTIMA | Reacciona a señal del backend. |
| R1 MEMORIA PRODUCTOS (`productos_mostrados` → `productos_excluidos`) | L569 | LEGÍTIMA | Alimenta el filtro server-side de exclusión. Correcto: el LLM acumula, el backend excluye. |
| R2 PERSISTENCIA DE FILTROS (`filtros_activos`) | L571-574 | **COMPENSATORIA** | El backend es stateless: no recuerda filtros entre llamadas. El LLM mantiene el estado de filtros en el prompt turno a turno. |
| R4 PRESUPUESTO DURO (nunca por encima de `precio_max` sin consentimiento) | L578 | **REDUNDANTE** | El backend ya filtra por `precio_max` (WHERE). Si `pres_duro`, el LLM re-vigila que no se cuele nada por encima — pero el server ya no lo devuelve. |
| FORMATO AL USUARIO + omitir Stock + concordancia género | L604 | **COMPENSATORIA** | Hueco 2 (proyección): el LLM recibe las 16 columnas y debe seleccionar/formatear las relevantes y suprimir Stock a mano, porque el backend no proyecta. |

---

## Lógica COMPENSATORIA (parchea datos)

### C1 — Listado hardcodeado de FLORES + toda la desambiguación "rosas" (L259, L261-274, L303)
**Qué hace:** mantiene en el prompt ~28 nombres de especie y 6 reglas ordenadas para decidir si "rosa/rosas" es flor o color, más el mandato TT-28 de forzar `producto=<flor>`.
**Hueco que compensa:** Hueco 1. No existe param `flor` y la columna `Flor` está vacía en los 10 registros. La única vía para "quiero rosas" es el fuzzy `producto` contra el nombre compuesto ("Ramo de Rosas"). Toda la inteligencia de "qué es una flor y cómo distinguirla de un color" vive en el prompt porque el dato no la aporta.
**Cómo se simplificaría si se arregla el hueco:** si el backend tuviera un campo `Flor` poblado y un param `flor` de filtrado:
- El listado de FLORES se reduce o desaparece (el backend valida la especie).
- La desambiguación "rosas producto/color" sigue siendo necesaria como NLU (es ambigüedad del español, no del dato) PERO deja de necesitar el rodeo "fuerza `producto` fuzzy" — pasaría `flor=Rosas` limpio.
- TT-28 desaparece: ya no hay riesgo de "perder el criterio" porque hay un filtro dedicado.

### C2 — MAPEO DECORACION → categoria (L304)
**Qué hace:** obliga a recordar que "Decoracion" se pasa como `categoria`, NO como `ocasion`, o el tool devuelve vacío.
**Hueco que compensa:** modelado de datos (relacionado con Hueco 3). Los conceptos que el usuario expresa como "ocasión/uso" están repartidos entre dos columnas (`Ocasion` y `Categoria_Uso`) sin una capa que los unifique. El LLM carga el mapa concepto→columna.
**Cómo se simplificaría:** si el backend aceptara un param semántico único (ej. `uso`/`contexto`) que internamente busque en ambas columnas, esta regla y su par de TCs (TC-DECO-01/02) desaparecen.

### C3 — R2 Persistencia de filtros / filtros_activos (L571-574)
**Qué hace:** el LLM mantiene turno a turno el set de filtros activos (ocasion, tipo, color, precio, tamaño), decide cuáles se mantienen al refinar y cuáles se resetean al cambiar ocasión.
**Hueco que compensa:** el backend es stateless. No hay sesión de búsqueda server-side. Todo el estado de la consulta vive en el prompt.
**Cómo se simplificaría:** un backend con sesión/carrito de búsqueda (search state con ID) descargaría la contabilidad de filtros; el LLM solo enviaría deltas. Es la compensatoria más "arquitectónica" — no se arregla con proyección/columna, sino con estado server-side. Menor prioridad.

### C4 — FORMATO AL USUARIO + supresión de Stock + concordancia (L604)
**Qué hace:** define el formato de presentación, ordena omitir `Stock`, y gestiona la concordancia de género del color. Implícitamente el LLM ignora `Ventas_Anuales`, `Descripcion_Corta`, `Flor` (vacío), `Tipo_Flor` ("Fresca"), `Entrega_Mismo_Dia` ("Sí").
**Hueco que compensa:** Hueco 2 (no proyección). El LLM recibe 16 columnas por fila y hace la proyección mentalmente cada turno: elige las 4-5 relevantes y descarta 5-6 campos ruido. Ese descarte no está escrito como regla pero es coste cognitivo real en cada respuesta y consume tokens de entrada.
**Cómo se simplificaría:** si el backend proyectara (devolviera solo `Producto, Color, Tamano, Descripcion_Cantidad, Precio, Stock`), la regla de formato se mantiene (es presentación legítima) pero desaparece el ruido de entrada y la carga de "qué ignorar". Ahorro principalmente en tokens de *response*, no de prompt.

### C5 — Listado hardcodeado de COLORES (L258) y REGLA PLACEHOLDER (L527-534)
**Qué hacen:** COLORES fija los 14 valores válidos que puede tomar `color`. PLACEHOLDER prohíbe nombrar tipos de producto no vistos en respuestas previas.
**Hueco que compensan:** el backend no expone su vocabulario controlado (qué colores / qué tipos existen). El LLM lo lleva en el prompt (colores) o lo reconstruye a base de acumular lo visto (tipos), con una anti-regla para no alucinar.
**Cómo se simplificaría:** un endpoint de metadatos (`GET /facets` → colores, tipos, categorías válidas) eliminaría el listado de COLORES y buena parte de la ansiedad anti-alucinación de PLACEHOLDER.

---

## Lógica REDUNDANTE (el backend ya lo hace)

### R-a — R4 Presupuesto duro (L578)
"Si `pres_duro=true`, NUNCA ofrezcas productos por encima de `precio_max`." El backend ya aplica `precio_max` en el WHERE, así que no puede devolver nada por encima. La regla re-vigila en contexto algo que el server ya garantiza. *Matiz:* solo aportaría valor si en algún fallback el backend relaja `precio_max` y devuelve caros; en ese caso la vigilancia sí sirve. Como está escrita ("NUNCA ofrezcas"), duplica el WHERE.

### R-b — "Completar hasta 3 con MISMA OCASION + MISMO COLOR" (L349)
Cuando `count` 1-2, el LLM completa el trío re-seleccionando por ocasión+color. Pero esos son exactamente los filtros que el backend ya aplicó. Si el server devolvió 1-2 con esos filtros, es que no hay más que cumplan; pedir al LLM que "complete" con los mismos criterios es redundante (y arriesga que invente o repita). Lo correcto sería subir `limit` o leer el fallback, no re-filtrar en prompt.

### R-c (parcial) — TT-28 forzar producto (L303)
No es redundante hoy (es la única vía sin param `flor`), pero se vuelve redundante en cuanto exista filtro `flor`. Anotado como compensatoria que migra a redundante tras el arreglo.

---

## Lógica LEGÍTIMA (debe quedarse)

- Parseo de slots de entrada: PASO 1.1, PARSEO PRECIOS, CANTIDAD IMPLICITA (NLU, el backend no ve la frase).
- TABLA DE SUFICIENCIA y política de cuándo preguntar (UX).
- CLASIFICACION DE INPUT tras mostrar (6 categorías) y los flujos de estado: ALTERNATIVAS, EXPANSION, REFINAMIENTO, CAMBIO DE TIPO, DELEGACION, MULTI-PRODUCTO.
- TT-11 disambiguación tamaño/precio sobre opciones ya mostradas (NLU coloquial).
- LECTURA RESPONSE API / fallbacks y RESULTADOS PARCIALES: reaccionan a señales que el backend YA emite (buen diseño).
- REGLA CANTIDAD > STOCK (TT-25): regla de negocio; la 2ª llamada es razonable a falta de endpoint de validación.
- R1 MEMORIA PRODUCTOS → `productos_excluidos`: el LLM acumula, el backend excluye. Reparto correcto.
- FALLBACK DE AGOTAMIENTO, TRANSVERSALES (queja/humano/despedida), FORMATO de presentación (el "cómo se muestra" es legítimo; el "qué ignorar" es la parte compensatoria).
- La desambiguación "rosas flor vs color" como NLU pura (ambigüedad del idioma) es legítima; solo su acoplamiento al fuzzy `producto` es compensatorio.

---

## Veredicto

### ¿Las reglas están "mal" o están "en la capa equivocada"?
**Mayoritariamente en la capa equivocada, no mal.** Las reglas compensatorias funcionan (los TCs lo prueban), pero implementan en el prompt del LLM responsabilidades que pertenecen a la capa de datos: taxonomía de especies (C1), unificación ocasión/categoría (C2), vocabulario controlado (C5), proyección (C4) y estado de búsqueda (C3). El síntoma clásico: reglas que existen por un TC concreto (TT-28, TC-DECO-01/02) — cada una es un parche a un hueco de datos que se manifestó como fallo. Genuinamente redundante (no solo mal ubicada) es poco: R4 y el "completar hasta 3".

### Estimación de tokens recuperables si se arregla la capa de datos
Estimación aproximada por bloque (tokens de prompt, ~1 token ≈ 0,75 palabras en español):

| Bloque | Líneas | Tokens aprox | Recuperable si… |
|---|---|---|---|
| Listado FLORES (L259) | 1 densa | ~120 | existe param/columna `flor` |
| DESAMBIGUACION ROSAS completa (L261-274) | 14 | ~350 | campo `flor` (queda ~⅓ como NLU pura → recuperable ~230) |
| TT-28 crítico (L303) | 2 | ~90 | filtro `flor` |
| MAPEO DECORACION (L304) | 1 densa | ~150 | param semántico `uso` |
| Listado COLORES (L258) | 1 | ~40 | endpoint de facets |
| REGLA PLACEHOLDER (L527-534) | 8 | ~200 | endpoint de facets (queda ~½ → recuperable ~100) |
| R2 persistencia filtros (L571-574) | 4 | ~110 | estado server-side (arquitectónico, baja prioridad) |
| R4 presupuesto duro (L578) | 1 | ~40 | ya redundante hoy |
| "completar hasta 3" (L349) | 1 | ~40 | ya redundante hoy |
| Formato "qué ignorar" (implícito, C4) | — | ~0 prompt / ahorro en response | proyección backend |

**Total recuperable de prompt: ~950-1.050 tokens** de los ~3.900-4.200 tokens del bloque `instruction` de compra.yaml. Es decir, **~24-27% del prompt de selección** es lógica compensatoria/redundante que migraría a la capa de datos. A esto se suma un ahorro NO contabilizable aquí en tokens de *response* (la proyección reduce cada fila de 16 a ~6 columnas → reduce el input que el LLM recibe del tool en cada llamada, típicamente el mayor consumidor real).

Nota: el arreglo de mayor impacto en tokens *totales* (prompt + tool response) es probablemente la **proyección (Hueco 2)**, aunque libere pocos tokens de prompt: recorta el payload de cada tool call, que se repite muchas veces por conversación.

### Mapa causa → efecto (arreglo de datos → regla que se simplifica)

| Arreglo en la capa de datos | Regla(s) que simplifica o elimina | Impacto |
|---|---|---|
| **Poblar columna `Flor` + añadir param `flor`** (Hueco 1) | Listado FLORES ↓, DESAMBIGUACION ROSAS ↓ (parte fuzzy), TT-28 ✗ | Alto — elimina la familia de parches "flor" |
| **Param semántico `uso`/`contexto` que busque en `Ocasion` + `Categoria_Uso`** (Hueco 3/modelado) | MAPEO DECORACION ✗ (y TC-DECO-01/02) | Medio — cierra una clase de bug |
| **Proyección server-side** (devolver ~6 columnas) (Hueco 2) | Formato "qué ignorar" ✗, ruido de entrada ↓ | Alto en tokens de response; bajo en prompt |
| **Endpoint de metadatos / facets** (colores, tipos, categorías válidas) | Listado COLORES ✗, REGLA PLACEHOLDER ↓ | Medio — reduce anti-alucinación |
| **Estado de búsqueda server-side** (sesión/carrito) | R2 persistencia filtros ↓ | Bajo/arquitectónico — no prioritario |
| **Ninguno (ya redundante)** | R4 presupuesto duro, "completar hasta 3" | Limpieza directa hoy, sin depender de datos |

**Prioridad recomendada de arreglo de datos (por ratio impacto/coste):** (1) Poblar `Flor` + param `flor` — elimina la mayor masa de reglas y la más frágil; (2) Proyección — mayor ahorro de tokens reales por conversación; (3) Param `uso` unificado — cierra bugs de categoría; (4) Facets; (5) estado server-side.
