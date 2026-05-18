---
status: FAIL
tipo: Bug Playbook + Bug Catálogo
estimacion: ~1h (Solución #7 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas para decorar mi salon"* | — |
| 2 | Orquestador | Clasifica `G5` (Compra directa) → handoff a Compra | ✅ Correcto |
| 3 | Compra | Extrae slots: `producto=ramo de rosas`, `ocasion_detectada=Decoracion`, `modo_tono=estandar` | ⚠️ El mapeo "decorar" → `ocasion=Decoracion` es el origen del problema |
| 4 | Compra → tool | `buscar_inventario(producto=rosas, tipo=Ramo, categoria=Decoracion)` → **0 resultados** | 🔴 Filtros incompatibles con el catálogo |
| 5a | Compra (Run 1) | Fallback directo: muestra Tulipanes Mix + Hortensias Blanco + Hortensias Azul **sin explicar** que no hay rosas | 🔴 Cambio silencioso del producto pedido |
| 5b | Compra (Run 2) | Responde *"No tengo ramos de rosas específicamente para decoración, pero..."* + alternativas Tulipanes/Hortensias | 🟡 Mejor UX (informa) pero **viola check `NO debía decir [no tengo.{0,40}rosa]`** |

El LLM es inestable extrayendo `producto` y respondiendo al fallback (en Run 1 extrae *"ramo de rosas"* y hace fallback silencioso; en Run 2 extrae *"rosas"* y responde explícitamente). Es **flakiness estructural** del playbook Compra cuando el filtro devuelve 0 resultados.

### Causa raíz (descompuesta en 3 capas)

1. **Catálogo** (`Inventario` sheet): no hay ramos de rosas con `Categoria_Uso=Decoracion`. Todos los ramos de rosas tienen `Categoria_Uso=Regalo`. **SÍ existen** rosas para decoración pero como **Centros de Mesa** (2 productos: `Centro de Mesa Rosas y Eucalipto` S/M).
2. **Playbook Compra**: mapea "decorar" → `ocasion=Decoracion` (filtro RÍGIDO). Cuando el tool devuelve 0, salta directo al fallback genérico — pierde los matches reales (Centros de Mesa).
3. **Tool `buscar_inventario`**: filtra por combinación exacta `producto + tipo + categoria`. Sin lógica de "si vacío, relajar 1 filtro". El backend filtra `producto=X` en columna `Producto` (nombre comercial completo), no en `Flor`.

## Recomendación

### Solución recomendada: #7 — Combinar Fallback escalonado + Example ancla

🟢 **9.5/10** · ~1h total · Sin dependencias externas

**Por qué**: fix estructural en playbook + ancla determinística en Example. Reduce flakiness entre runs. Resuelve TC-DECO-02 + TC-DECO-01 (similar). Sin tocar catálogo ni tool. Riesgo bajo. Es el patrón que ya funciona en Compra y Checkout.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 3 | **Fix Catálogo: añadir `Ramo Rosas Decoración` S/M/L** con `Categoria_Uso=Decoracion` | 🟢 10/10 técnico | Aprobación de negocio | Pasa el check al 100% sin tocar código. Pero: ¿Petal realmente vende rosas para decoración? Si no es producto real, inflamos catálogo solo para pasar test. ~5 min técnico, 0-N días de aprobación negocio. |
| 7 | **Combinar #1 + #5** (Fallback escalonado + Example ancla) | 🟢 9.5/10 | — | **RECOMENDADO**. Fix estructural en playbook + ancla determinística en Example reduce flakiness. Resuelve TC-DECO-02 + TC-DECO-01. Sin tocar catálogo ni tool. Riesgo bajo. ~1h total. |
| 1 | **Fix Playbook Compra: añadir `FALLBACK ESCALONADO` en `CASOS ESPECIALES`**. Al devolver 0 resultados: informar del filtro no cumplido + relajar 1 filtro a la vez (orden: `tipo` → `categoría` → `producto`) + mostrar 3 opciones combinadas | 🟢 9/10 | — | Resuelve estructuralmente. Permite mostrar los Centros de Mesa Rosas Eucalipto (que existen). Mantiene la lógica de "decorar = filtrar por uso". UX clara. Patrón reutilizable. ~45 min. |
| 5 | **Fix Examples: añadir `EX-DECO-ROSAS`** mostrando comportamiento esperado para input "rosas + decoración" | 🟢 8/10 complementario | — | Reduce flakiness entre runs (silencioso vs explícito). NO resuelve el bug del filtro por sí solo. **Multiplicador** de #1 y #2, no sustituto. ~20 min. |
| 4 | **Fix Tool: añadir param `producto_alternativo`** que busque productos relacionados (mismo `Flor` aunque distinto `Producto`) cuando match exacto está vacío | 🟡 7/10 | Redeploy `petal-sheet-api` | Capa correcta (datos). Centro de Mesa Rosas tiene `Flor=Rosas` → aparecería. ~1-2h + redeploy backend. Toca otra capa fuera del repo. |
| 2 | **Fix Playbook Compra: NO mapear "decorar" → `ocasion=Decoracion`**. Pasa solo `producto + tipo`, deja al catálogo responder con todo | 🟡 6/10 | Revisar 5-6 TCs relacionados | Resuelve este TC + TC-DECO-01 juntos. Pero **pierde filtro por intención** — riesgo de regresión silenciosa en TC-FUNERAL-01 y otros donde la ocasión SÍ es relevante. ~30 min + revisar TCs. |
| 6 | **Fix Test: relajar regex** — quitar check "Rosa -- talla", aceptar "no tengo rosas..." | 🔴 3/10 | Decisión negocio + renombrar TC | Renuncia al objetivo del test. Enmascara el bug en vez de resolverlo. Solo aceptable si combinado con decisión de negocio de "no vendemos rosas para decoración". ~5 min. |

### Plan de acción (Solución #7)

1. **Editar `definitions/playbooks/compra.yaml`** → sección `# CASOS ESPECIALES`. Añadir bloque `FALLBACK ESCALONADO`:
   - Si tool devuelve 0 resultados → NO saltar al fallback genérico.
   - Informar explícitamente: *"No tengo ramos de rosas específicamente para decoración."*
   - Relajar UN filtro a la vez en orden: `tipo` → `categoría` → `producto`.
   - Mostrar hasta 3 opciones combinadas escalonadas.

2. **Crear Example `EX-DECO-ROSAS-FALLBACK`** en `definitions/examples/`:
   - Input: *"ramo de rosas para decorar"*
   - Output esperado: 2 Centros de Mesa Rosas Eucalipto + 1 Ramo de Rosas (Regalo) + 1 alternativa decoración + explicación clara.

3. **Re-ejecutar QA** con `--runs 3`:
   - TC-DECO-02 debe pasar mostrando los Centros de Mesa Rosas Eucalipto.
   - Ambas runs deben responder con el mismo patrón (sin flakiness).

**Coste total**: ~1h (playbook 30 min + example 20 min + QA 10 min).
