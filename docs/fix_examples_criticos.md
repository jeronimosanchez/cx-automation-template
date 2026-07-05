# Fix de 4 examples críticos — normalización de schema

Fecha: 2026-07-05 · Alcance: SOLO estos 4 archivos. `id` preservado en cada uno
(deploy idempotente actualiza el mismo example). Datos poblados con productos
REALES del backend `petal-sheet-api-v11` (`recurso=inventario`).

## Schema nuevo (plantilla: `exh_v16*.yaml` "ExH v17")

Campos válidos en resultados de inventario:
`Producto` (nombre BASE, sin color ni talla embebidos), `Especie`, `Color`,
`Tamano`, `Precio` (string), `Descripcion_Cantidad` (string "N flores"/"N tallos"),
`Ocasion` (multivaluada, coma).

Prohibidos (eliminados): `Flores_Tallos`, `Categoria_Uso`, `Nombre_Producto`,
`Tipo`, `Tamaño`, `Categoria`, `Tipo_Producto`, `Stock`.

Ocasion válidas (7): Funeral, Boda, Regalo, Decoracion, Romantico, Nacimiento,
Corporativo. "San Valentín" → mapeado a `Romantico`.

En `inputActionParameters`: la flor va en `especie` (no `producto`, no `categoria`).

## Cambios por archivo

### 1. `compra/exd_v13_exploracin_genrica_inventario.yaml` — RECONSTRUIDO
- displayName: `ExD v13` → `ExD v14`.
- El JSON de output estaba **sin cerrar** (YAML/JSON inválido) y con schema viejo
  (`Nombre_Producto`, `Tipo`, `Tamaño`, `Flores_Tallos`, `Stock`, `Categoria`).
- Reconstruido como bloque YAML nativo (no string JSON) con schema nuevo.
- Input: `categoria: regalo` → `ocasion: Regalo` (filtro correcto del backend).
- Datos reales (ocasion=Regalo): Ramo de Peonías Coral M (15 flores, 35€),
  Ramo de Girasoles Amarillo M (10 flores, 20€), Ramo de Gerberas Amarillo M
  (10 flores, 18€). Conversación conservadora: pregunta ocasión → muestra 3 →
  usuario declina → cierre. `executionSummary` reescrito (antes decía "consulta
  inventario" genérico).

### 2. `compra/exa_v9_ramo_rosas_rojas_elige_tamao_confirma.yaml` — NORMALIZADO
- displayName: `ExA v9` → `ExA v10`.
- Eliminados `Flores_Tallos`, `Categoria_Uso`, `Tipo_Producto`, `Stock`.
- `Ocasion: San Valentín` → `Regalo, Romantico` (valor válido).
- `Producto` con talla embebida ("Ramo de Rosas Rojas — M") → nombre BASE
  "Ramo de Rosas" + `Tamano` en su propio campo. XL: "Ramo San Valentín Rosas".
- Datos reales (especie=rosas, color=Rojo): S (8 flores, 22€), M (15 flores, 37€),
  XL San Valentín (36 flores, 132€). Usuario elige M.
- Input: `tipo: Ramo` retirado; se mantiene `especie: rosas`, `color: Rojo`.
- Output actionParameters ahora con `especie`, `color`, `tamano` separados
  (antes `producto: "Ramo de Rosas Rojas — M"`). Corregidas claves basura del
  input (`'"tipo_cliente"'` → `tipo_cliente`; `nombre_cliente: ana` → `Ana`).

### 3. `compra/exc_v9_consulta_precio_tulipanes_no_compra.yaml` — NORMALIZADO
- displayName: `ExC v9` → `ExC v10`.
- Eliminados `Flores_Tallos`, `Categoria_Uso`, `Tipo_Producto`, `Stock`.
- `Producto` con talla embebida ("— S/— M") → nombre BASE + `Tamano`.
- Datos reales (especie=tulipanes): Ramo de Tulipanes Multicolor M (10 flores, 20€),
  Ramo Primavera Tulipanes Mix M (12 flores, 28€), Ramo Gracias Tulipanes Mix M
  (15 flores, 30€). Rango de precios en el agentUtterance actualizado a 20–30€.
- Input: `producto: tulipanes` ya era `especie: tulipanes` (sin cambio). Estructura
  conversacional (consulta precio → declina) preservada.

### 4. `petal_cx_orchestrator/ex06_g2g5_..._lirios_blancos.yaml` — FIX INPUT
- Único cambio: `inputActionParameters.producto: lirios` → `especie: lirios`.
- El resto (output ya en schema nuevo con `Descripcion_Cantidad`, conversación de
  re-detección solemne, transición a Compra) se preserva intacto.
- Nota: el backend NO devuelve lirios de color Blanco (colores reales:
  Naranja/Rosa/Amarillo, todos "Ramo de Lirios" a 22€). El output de este example
  conserva sus "Lirios Blancos" originales por estar fuera del alcance pedido
  (solo se pidió corregir el field name del input). Si se quisiera fidelidad total
  de datos habría que revisar el escenario "blancos" contra el inventario real.

## Validación

Los 4 archivos pasan `python3 -c "import yaml; yaml.safe_load(open(...))"`.
Grep de campos prohibidos y valores de Ocasion inválidos: sin coincidencias.
`id`, `playbook` y estructura conversacional (userUtterance/agentUtterance/toolUse/
playbookTransition) preservados en todos.

## Dudas / notas para Jero

- **ex06 lirios "blancos" vs inventario real**: el backend no tiene lirios blancos.
  Fuera del alcance de este fix (solo input field). ¿Reescribir el escenario a un
  color real o dejarlo como está? [gate]
