# Auditoría de terminología — Examples de Petal (Dialogflow CX)

> **Solo lectura + análisis.** Ningún `.yaml` fue modificado. Esta lista es para que un humano decida qué cambiar.
> Fecha: 2026-07-05 · Alcance: los 29 examples en `definitions/examples/` (recursivo).

## Terminología correcta (post-refactor) — recordatorio

| Dimensión | Correcto (nuevo) | Viejo / prohibido |
|---|---|---|
| Flor como filtro exacto | param `especie` | `producto=<flor>` |
| Cantidad de flores (output) | `Descripcion_Cantidad` (string "N flores") | `Flores_Tallos` (campo muerto) |
| Ocasión (columna/campo) | `Ocasion` | `Categoria_Uso` (columna eliminada) |
| Ocasión (param de entrada) | `ocasion` | `categoria` (legacy, aún funciona) |
| Nombre de producto (output) | nombre base ("Ramo de Rosas") | nombre con color/talla ("Ramo de Rosas Rojas — S") |
| Valores de ocasión válidos | Funeral, Boda, Regalo, Decoracion, Romantico, Nacimiento, Corporativo | cualquier otro |

Severidad: 🔴 campo muerto / schema fantasma · 🟡 legacy que funciona pero inconsistente · 🟢 cosmético.

---

## Tabla de hallazgos

| Archivo (basename) | Línea/campo aprox | Terminología vieja encontrada | Cambio propuesto | Severidad |
|---|---|---|---|---|
| exa_v9_ramo_rosas_rojas_elige_tamao_confirma | L23,32,43 `outputActionParameters` | `Categoria_Uso: Regalo` (x3) en resultados | Eliminar el campo (columna eliminada); la ocasión ya está en `Ocasion` | 🔴 |
| exa_v9_ramo_rosas_rojas_elige_tamao_confirma | L24,31,42 `outputActionParameters` | `Flores_Tallos: '36'/'8'/'15'` (x3) | Cambiar a `Descripcion_Cantidad: "36 flores"` etc. | 🔴 |
| exa_v9_ramo_rosas_rojas_elige_tamao_confirma | L19 `outputActionParameters` | `Ocasion: San Valentín` (fuera de los 7 válidos) | Usar valor válido, p.ej. `Regalo` (San Valentín no es ocasión válida) | 🟡 |
| exa_v9_ramo_rosas_rojas_elige_tamao_confirma | L26,36 `Producto` + L66 `playbookOutput.producto` | `Ramo de Rosas Rojas — S` / `— M` (color+talla embebidos) | Nombre base `Ramo de Rosas`; color/talla en sus campos | 🟡 |
| exb_v15_funeral_tipoproducto_con_filtros | L10 `inputActionParameters` | `categoria: funeral` (param legacy) | Considerar `ocasion: Funeral` | 🟡 |
| exb_v15_funeral_tipoproducto_con_filtros | L49 `playbookOutput.producto` | `Ramo de Gladiolos Blancos — S` (color+talla embebidos) | Nombre base `Ramo de Gladiolos` | 🟡 |
| exc_v9_consulta_precio_tulipanes_no_compra | L23,31,35 `outputActionParameters` | `Flores_Tallos: '5'/'10'/'3'` (x3) | Cambiar a `Descripcion_Cantidad: "5 flores"` etc. | 🔴 |
| exc_v9_consulta_precio_tulipanes_no_compra | L24,30,36 `outputActionParameters` | `Categoria_Uso: Regalo` (x3) | Eliminar (columna eliminada) | 🔴 |
| exc_v9_consulta_precio_tulipanes_no_compra | L17,27,41 `Producto` | `Ramo de Tulipanes Mixtos — S/M`, `Morados — S` (color+talla embebidos) | Nombre base `Ramo de Tulipanes` | 🟡 |
| exc_v9_consulta_precio_tulipanes_no_compra | L54,63 `executionSummary` | `producto=tulipanes` (describe filtro como producto, no especie) | Redactar `especie=tulipanes` | 🟢 |
| exd_v13_exploracin_genrica_inventario | L10-16 `inputActionParameters` | `categoria: regalo` (param legacy) | Considerar `ocasion: Regalo` | 🟡 |
| exd_v13_exploracin_genrica_inventario | L28,38,48 JSON output | `Flores_Tallos: 8/10/4` | Cambiar a `Descripcion_Cantidad: "8 flores"` etc. | 🔴 |
| exd_v13_exploracin_genrica_inventario | L24,34,44 JSON output | `Nombre_Producto` en vez de `Producto`; L26 `Tipo` en vez de `Tipo_Producto`; L27 `Tamaño` en vez de `Tamano`; L31 `Categoria` en vez de `Ocasion` | Alinear nombres de campo al schema nuevo (`Producto`, `Ocasion`, `Tamano`) | 🔴 |
| exd_v13_exploracin_genrica_inventario | L17-53 output | Bloque JSON está sin cerrar (falta `]}` y comilla de bloque) — schema roto además de terminología | Revisar/reconstruir el output; hoy es JSON inválido | 🔴 |
| exf_v15_g3_boda_pregunta_abierta_rechaza_alternativas | L13 `inputActionParameters` | `categoria: boda` (param legacy) | Considerar `ocasion: Boda` | 🟡 |
| exg_v15_refinamiento_progresivo_filtros_acumulados | L14,27 `inputActionParameters` | `categoria: regalo` (param legacy, x2 tool calls) | Considerar `ocasion: Regalo` | 🟡 |
| exg_v15_refinamiento_progresivo_filtros_acumulados | L57 `playbookOutput.producto` | `Ramo de Rosas Rojas — M` (color+talla embebidos) | Nombre base `Ramo de Rosas` | 🟡 |
| ex06_g2g5_con_re-deteccion_de_solemne_lirios_blancos | L13 `inputActionParameters` | `producto: lirios` (flor en `producto` en vez de `especie`) | Cambiar a `especie: lirios` | 🔴 |
| ex_checkout_email_recovery_input_no_email_f1_calidez | L38,55,71 varios | `Ramo de Rosas Rojas — M` (color+talla en línea de pedido y resumen) | Cosmético en checkout (no es filtro inventario, es item de pedido); homogeneizar si se desea nombre base | 🟢 |
| nombre_checkout_ex01_..._validar_pedido | L54,66,99 varios | `Ramo de Rosas Rojas — M` en validar_pedido/resumen/input; ojo: L83 usa `Ramo de Rosas Rojas` (inconsistente dentro del mismo file) | Homogeneizar nombre de producto; decidir base vs con-talla y ser consistente | 🟢 |

---

## Resumen

- **Total examples auditados:** 29
- **Limpios (100% correctos, no tocar):** 15
- **Necesitan cambio:** 14
- **Hallazgos 🔴 (campo muerto / schema roto):** 6 examples afectados
- **Hallazgos 🟡 (legacy funcional):** 6 examples
- **Hallazgos 🟢 (cosmético):** 3 examples

### Los más graves (🔴, abordar primero)

1. **`exd_v13`** — el peor: JSON de output roto (sin cerrar) + campos con nombres viejos (`Nombre_Producto`, `Tipo`, `Tamaño`, `Categoria`) + `Flores_Tallos` + `categoria` legacy. Reconstruir.
2. **`exa_v9`** y **`exc_v9`** — ambos con `Flores_Tallos` + `Categoria_Uso` en cada resultado del array (campos muertos). Son los outputs de inventario más "sucios".
3. **`ex06` (orquestador)** — `producto: lirios` debería ser `especie: lirios`. Es un filtro de flor mal ubicado.

### Nota sobre `ExH v17` — patrón de referencia LIMPIO

`exh_v16_g5_genrico_paso_1.5_contexto_refinamiento.yaml` (displayName "ExH v17") es el **único example de compra que usa el schema nuevo completo y correcto**: `especie` como filtro, `Descripcion_Cantidad: "15 flores"`, `Ocasion` con valores válidos multivaluados ("Regalo, Romantico, Decoracion"), y `Producto: Ramo de Rosas` como nombre base (color/talla en campos separados). **Usar como plantilla al normalizar los demás.**

---

## Examples 100% correctos (NO tocar)

Sin terminología vieja de inventario (o no consultan inventario):

**Compra:**
- `exh_v16_g5_genrico_paso_1.5_contexto_refinamiento.yaml` (patrón de referencia)
- `exi_v1_fallback_rosas_azules_tono_calido.yaml` — usa `especie`, `Ocasion` válida y NO tiene `Flores_Tallos`/`Categoria_Uso`. (Único punto blando: `Producto` con color+talla embebido "Ramo de Rosas Rojas — M", pero criterio cosmético; no listado arriba por ser fallback de tono. Ver nota.)

**Orquestador (tono / clasificación, sin inventario):**
- `ex07_g3_corporativo_sin_producto_oficina.yaml`
- `ex08_g3_recomendacin_compra.yaml`
- `ex08b_g3_sin_ocasion_transfiere_compra.yaml`
- `ex09_solicitud_agente.yaml`
- `ex10_g6_historial_pide_email.yaml` (usa `recurso: perfil`, sin inventario)
- `ex2_email_no_encontrado_registro_task.yaml`
- `ex5_ubicacin_tienda_pre-email_g1.yaml` (recurso `business`)
- `ex5b_g1_horario_apertura_business.yaml` (recurso `business`)
- `orq_cambio_frustracion.yaml`
- `orq_cambio_urgencia.yaml`
- `orq_celebracion.yaml` — `ocasion_detectada: Boda` (válida)
- `orq_duelo_solemne.yaml` — `ocasion_detectada: Funeral` (válida)
- `orq_frustracion_solemne.yaml`
- `orq_urgente_estandar.yaml`

**Registro_Task (registro de cliente, sin inventario):**
- `ex_reg_01_particular_con_bajo_captura_planta_slot_filling_letra.yaml`
- `ex_reg_02_datos_multiples_en_un_turno.yaml`
- `ex_reg_03_empresa_con_cif.yaml`
- `registro_completo.yaml`

> **Aclaración sobre `producto` en Checkout / validar_pedido / pedidos:** ahí `producto` se refiere al nombre del producto de un ítem de pedido, NO a un filtro de especie. Su uso es correcto por definición; los hallazgos en checkout son solo cosméticos (nombre con talla embebida).

---

## Observación transversal (para el humano)

El param de entrada **`categoria`** (legacy pero funcional) aparece en 4 examples de compra: `exb`, `exd`, `exf`, `exg`. Si se decide migrar a `ocasion`, hacerlo en bloque y verificar que el Playbook Compra + Tool aceptan el nuevo nombre antes de cambiar los examples (los examples describen el comportamiento esperado; cambiarlos sin cambiar el playbook rompería la coherencia).
