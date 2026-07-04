# Diagnóstico BBDD Petal — 2026-07-04

> Análisis estático de la base de datos de inventario de Petal contra 10 principios de calidad para bases de datos que alimentan agentes LLM. Solo lectura — sin modificaciones.

---

## Fuentes consultadas

| Fuente | Detalle |
|---|---|
| API endpoint | `GET /exec?recurso=inventario&limit=100` (base: `petal-sheet-api-v11-920225907399.europe-west1.run.app`) |
| Registros obtenidos | 10 (top-10 por `Ventas_Anuales`) |
| Examples Compra | ExA, ExB, ExC, ExD, ExF, ExG, ExH (7 archivos) |
| Playbook Compra | `definitions/playbooks/compra.yaml` (inputParams, outputParams, primeras líneas) |
| Tool definition | `definitions/tools/petaldatatool_openapi.yaml` v3.9.0 |

---

## Muestra de datos — 5 registros representativos

| Producto | Tipo_Producto | Color | Tamano | Precio | Categoria_Uso | Ocasion | Descripcion_Cantidad | Duracion | Flor | Es_Temporada | Entrega_Mismo_Dia | Tipo_Flor | Stock | Ventas_Anuales | Descripcion_Corta |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ramo de Peonías | Ramo | Coral | M | 35 | Regalo | Regalo | 15 flores | 5-7 días | *(vacío)* | No | Sí | Fresca | 48 | 138 | "Ramo mediano de 15 flores. Envuelto en papel craft con lazo. Duración: 5-7 días." |
| Ramo de Girasoles | Ramo | Amarillo | M | 20 | Regalo | Regalo | 10 flores | 5-7 días | *(vacío)* | No | Sí | Fresca | 64 | 136 | "Ramo mediano de 10 flores. Envuelto en papel craft con lazo. Duración: 5-7 días." |
| Ramo de Gladiolos | Ramo | Rosa | M | 19 | Funeral | Funeral, Regalo | 3 tallos | 5-7 días | *(vacío)* | No | Sí | Fresca | 63 | 135 | "Ramo mediano de 3 tallos. Envuelto en papel craft con lazo. Duración: 5-7 días." |
| Ramo de Claveles | Ramo | Multicolor | M | 15 | Funeral, Regalo | Funeral, Regalo, Decoracion | 6 flores | 10-14 días | *(vacío)* | No | Sí | Fresca | 49 | 134 | "Ramo mediano de 6 flores. Envuelto en papel craft con lazo. Duración: 10-14 días." |
| Ramo Primavera Tulipanes Mix | Ramo | Multicolor | M | 28 | Regalo, Decoración | Decoracion, Regalo | 12 flores | 5-7 días | *(vacío)* | Sí | Sí | Fresca | 52 | 134 | "Ramo mediano de 12 flores. Envuelto en papel craft con lazo. Duración: 5-7 días." |

**Campos del schema (16 total):**
`Categoria_Uso` · `Color` · `Descripcion_Cantidad` · `Descripcion_Corta` · `Duracion` · `Entrega_Mismo_Dia` · `Es_Temporada` · `Flor` · `Ocasion` · `Precio` · `Producto` · `Stock` · `Tamano` · `Tipo_Flor` · `Tipo_Producto` · `Ventas_Anuales`

---

## Diagnóstico por principio

| # | Principio | Estado | Evidencia | Impacto en agente |
|---|---|---|---|---|
| 1 | Atomicidad | 🔴 | `Descripcion_Cantidad` mezcla número y unidad en texto libre: "15 flores", "3 tallos". Sustituye al antiguo campo numérico `Flores_Tallos` (aún presente en examples ExA, ExC, ExH). `Categoria_Uso` y `Ocasion` son listas CSV embebidas en un string: "Funeral, Regalo, Decoracion". | El modelo no puede extraer el número de tallos sin parseo de texto. Las listas CSV en un campo string impiden filtrado limpio por valor individual. |
| 2 | Univocidad | 🔴 | ExD usa `Nombre_Producto`, `Tipo`, `Tamaño`, `Categoria` para los mismos conceptos que la API actual llama `Producto`, `Tipo_Producto`, `Tamano`, `Categoria_Uso`. El campo `Flores_Tallos` de los examples (ExA, ExC, ExH) no existe en la API actual (reemplazado por `Descripcion_Cantidad`). Los params de filtro de la tool usan nombres distintos a los campos de respuesta: filtro `categoria` → campo `Categoria_Uso`. | El modelo aprende de examples con field names distintos al schema real. En inferencia, puede enviar o esperar campos que no existen, generando fallos silenciosos. |
| 3 | Consistencia interna | 🔴 | `Categoria_Uso` = "Decoración" (con tilde) vs `Ocasion` = "Decoracion" (sin tilde) para el mismo concepto. `Precio`, `Stock` y `Ventas_Anuales` se devuelven como STRING, no como NUMBER (el param `precio_max` de la tool es `type: number`). `Tamano` en API sin acento vs `Tamaño` con acento en ExD. Los valores de `Ocasion` no tienen orden consistente: "Funeral, Regalo" vs "Decoracion, Regalo". | Inconsistencia de acentos fuerza normalización implícita. Tipo incorrecto en campos numéricos puede romper la comparación `precio_max ≤ Precio` si la API no normaliza internamente. |
| 4 | Completitud | 🔴 | El campo `Flor` está vacío en los **10/10 registros** del top-10. `Tamano` tiene un único valor (M) en todos los registros mostrados, lo que oculta que el catálogo real tiene S, M, L, XL (evidenciado por los examples). El endpoint sin `limit` solo devuelve 3 registros por defecto; el máximo es 10. | El campo `Flor` existe en el schema pero no aporta información. El agente que confíe en el top-10 para inferir qué valores de `Tamano` existen obtendrá una imagen distorsionada del catálogo. |
| 5 | Valores discretos | 🟡 | Los campos de filtrado `Color`, `Tipo_Producto`, `Tamano` tienen valores discretos bien definidos en los datos reales. Sin embargo, `Categoria_Uso` y `Ocasion` son listas CSV variables (no un enum), lo que rompe la discreción. `Descripcion_Cantidad` es texto libre ("15 flores", "3 tallos"). | El modelo puede predecir "Rojo" o "Ramo" con fiabilidad, pero no puede enumerar con certeza los valores válidos de ocasión/categoría porque se presentan como listas concatenadas. |
| 6 | Normalización | 🔴 | El mismo concepto "Decoración" aparece como: "Decoración" en `Categoria_Uso` (Record 6), "Decoracion" en `Ocasion` (Records 6, 7, 8). El campo `Categoria_Uso` tiene "Funeral, Regalo" y "Regalo, Decoración" con acento distinto. Los examples usan "Multicolor" y "Mixto" para el mismo concepto (ExD: "Mixto" vs API: "Multicolor"). | Cada variante ortográfica que el modelo aprende como distinta genera fragmentación semántica. El filtro `categoria=decoracion` puede no devolver el registro con "Decoración" si el backend es sensible a tildes. |
| 7 | Sin redundancia conflictiva | 🔴 | `Categoria_Uso` y `Ocasion` solapan casi completamente: ambos codifican la categoría de uso (funeral, regalo, decoración). No hay documentación de cuál usar para filtrar. `Descripcion_Corta` es una concatenación mecánica de `Tipo_Producto` + `Tamano` + `Descripcion_Cantidad` + `Duracion` + texto fijo. `Descripcion_Cantidad` y `Flores_Tallos` (en examples) representan el mismo dato con nombres y tipos distintos. | El modelo recibe información duplicada y debe inferir cuál fuente usar. El riesgo de citar `Descripcion_Corta` como base para razonar en vez de los campos atómicos es real (el texto incluye "mediano" como descripción de tamaño, redundante con `Tamano`). |
| 8 | Granularidad adecuada | 🟡 | `Descripcion_Corta` es demasiado granular para razonar (texto de marketing); el agente necesita los datos atómicos. `Ventas_Anuales` es un campo operacional interno demasiado específico para la decisión del agente (no le ayuda a recomendar). `Duracion` tiene una granularidad adecuada (rango de días). `Entrega_Mismo_Dia` está a la granularidad correcta pero aporta cero información al ser siempre "Sí". | El agente recibe campos de granularidad muy variable: algunos útiles (Color, Tamano), otros inutilizables sin parseo (Descripcion_Cantidad), otros irrelevantes (Ventas_Anuales). |
| 9 | Separación de dimensiones | 🟡 | Color, Tamano, Tipo_Producto, Ocasion/Categoria están en campos separados. Correcto en principio. Pero `Descripcion_Cantidad` mezcla cantidad + unidad ("3 tallos" vs "15 flores"), colapsando dos dimensiones. `Ocasion` lista múltiples valores en un string, colapsando varias ocasiones posibles en un campo no descomponible sin parseo. | Las dimensiones principales están razonablemente separadas. El problema está en los casos borde: cantidad vs unidad, y listas de ocasiones multi-valor. |
| 10 | Orientación al agente | 🔴 | `Ventas_Anuales` es un artifact operacional (se usa para el ranking interno de paginación) que no tiene valor para el razonamiento del agente. `Descripcion_Corta` es texto de marketing sin estructura. `Entrega_Mismo_Dia` y `Tipo_Flor` no tienen varianza en el dataset actual (siempre "Sí" y "Fresca"), por lo que consumen tokens sin aportar información discriminante. El campo `Flor` está siempre vacío pero ocupa espacio en cada registro devuelto. | El agente recibe aproximadamente 5 de 16 campos sin valor discriminante en el contexto actual. Cada registro devuelto tiene tokens innecesarios que acumulan coste de contexto y potencialmente diluyen la señal útil. |

---

## Hallazgos críticos (🔴)

### C-01: Campo `Flor` siempre vacío
El campo `Flor` existe en el schema y se incluye en cada respuesta, pero tiene valor vacío (`""`) en los 10/10 registros analizados. El agente recibe el campo, puede intentar usarlo en reasoning, y siempre encontrará valor vacío. Esto es ruido puro en el contexto.

### C-02: `Flores_Tallos` eliminado — examples obsoletos
Los examples ExA, ExC y ExH usan el campo `Flores_Tallos` (numérico, entero) como output de la herramienta. El campo ya no existe en la API: fue reemplazado por `Descripcion_Cantidad` (string con formato "N flores" o "N tallos"). Los examples que el modelo usa como ground truth de comportamiento muestran un schema que ya no es real. El modelo aprenderá a esperar un campo que nunca llegará.

### C-03: Inconsistencia de nomenclatura entre examples y API
ExD usa `Nombre_Producto`, `Tipo`, `Tamaño`, `Categoria` — cuatro nombres distintos a los de la API actual (`Producto`, `Tipo_Producto`, `Tamano`, `Categoria_Uso`). Hay un segundo schema fantasma en los examples que contradice el schema real.

### C-04: `Categoria_Uso` y `Ocasion` solapan — cuál usar no está documentado
Ambos campos codifican el mismo concepto semántico con ligeras diferencias en valores y sin documentación de cuál tiene preferencia para filtrar. Además tienen inconsistencia de acentos entre sí ("Decoración" vs "Decoracion").

### C-05: `Precio` y `Stock` devueltos como STRING
El param `precio_max` de la tool es `type: number`. Los valores `Precio` devueltos son strings ("15", "20"...). Si el backend no normaliza la comparación internamente, los filtros por precio pueden fallar silenciosamente o dar resultados incorrectos.

### C-06: `Descripcion_Cantidad` pierde atomicidad respecto a `Flores_Tallos`
La migración de un campo numérico (`Flores_Tallos: 8`) a texto libre (`Descripcion_Cantidad: "8 flores"`) introduce una pérdida de atomicidad. Además, el campo mezcla unidades heterogéneas: la mayoría de registros usan "flores", pero los gladiolos usan "tallos". El LLM debe inferir la unidad contextualmente para presentar la información al usuario.

---

## Hallazgos de atención (🟡)

### A-01: `Entrega_Mismo_Dia` y `Tipo_Flor` sin varianza
En los 10 registros, ambos campos tienen un único valor ("Sí" y "Fresca" respectivamente). No tienen poder discriminante. Si el catálogo completo tampoco tiene varianza, son candidatos a eliminar o convertir en metadata de configuración del agente, no en campo por registro.

### A-02: `Ventas_Anuales` expone métrica operacional
Este campo actúa como cursor de paginación interna (el endpoint devuelve los N registros con más ventas). El agente lo recibe en contexto pero no debería usarlo para razonar sobre qué recomendar. Su presencia puede inducir al modelo a mencionar popularidad cuando no fue preguntado.

### A-03: `Descripcion_Corta` redundante
El campo es una concatenación mecánica de `Tipo_Producto` + tamaño + `Descripcion_Cantidad` + texto fijo + `Duracion`. No aporta información que no esté ya en campos atómicos. Consume tokens en cada resultado.

### A-04: `Es_Temporada` potencialmente útil pero no verificable con 10 registros
Solo 1 de 10 registros tiene `Es_Temporada: Sí`. Es un campo con varianza real, pero sin acceso al catálogo completo no se puede validar si la cobertura es correcta o si el flag se mantiene actualizado.

### A-05: `Ocasion` usa listas CSV en un string
Los valores multi-ocasión ("Funeral, Regalo, Decoracion") son listas embebidas en un string. Para filtrar por ocasión el backend debe hacer contains/split internamente, lo que introduce ambigüedad de matching (¿"Boda" devuelve un registro con "Boda, Regalo"?). No hay enum documentado de valores posibles de `Ocasion`.

---

## Resumen ejecutivo

El inventario de Petal tiene un schema de 16 campos con problemas en tres capas. La capa más crítica es la **desincronización entre el schema actual de la API y los examples de entrenamiento del agente**: al menos 4 campos difieren entre lo que la API devuelve hoy y lo que los examples enseñan al modelo a esperar (`Flores_Tallos`, `Nombre_Producto`, `Tipo`, `Tamaño`/`Tamano`). Esto no degrada gradualmente el agente — lo enseña con datos incorrectos.

La segunda capa es la **redundancia conflictiva**: `Categoria_Uso` y `Ocasion` transportan el mismo concepto semántico con inconsistencias ortográficas entre sí, sin documentar cuál tiene preferencia como filtro. `Descripcion_Corta` repite en texto lo que ya está en campos atómicos.

La tercera capa son los **campos sin valor discriminante**: `Flor` siempre vacío, `Entrega_Mismo_Dia` y `Tipo_Flor` siempre con el mismo valor, `Ventas_Anuales` como artifact operacional — aproximadamente 5 de 16 campos no aportan información al razonamiento del agente pero consumen tokens en cada resultado devuelto.

La acción de mayor impacto inmediato es actualizar los examples para que reflejen el schema real de la API (especialmente reemplazar `Flores_Tallos` por `Descripcion_Cantidad` y unificar los nombres de campo de ExD).
