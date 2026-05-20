---
status: FAIL
tipo: Bug Catálogo
estimacion: ~2h (Solución #1 recomendada) / ~20 min si solo Solución #5
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"quiero un ramo de rosas para decorar mi salon"* | — |
| 2 | Orquestador | Clasifica como G5 (compra), extrae `producto=ramo de rosas`, `ocasion_detectada=Decoracion` | ✅ Clasificación y extracción correctas. |
| 3 | Compra | Llama al catálogo con `ocasion=Decoracion` + `producto=ramo de rosas`. Sin rosas en catálogo para Decoracion → fallback a productos genéricos de decoración | 🔴 El catálogo no devuelve ninguna Rosa para la ocasión Decoración. El playbook cae en fallback mostrando Tulipanes Mix y Hortensias sin mencionar el producto pedido. |
| 4 | Agente | *"Mira, para decorar tu salón tengo estas opciones que suelen gustar: Ramo Primavera Tulipanes Mix — Multicolor, Ramo de Hortensias — Blanco, Ramo de Hortensias — Azul"* | 🔴 Ninguna rosa en la respuesta. El usuario pedía rosas explícitamente. El agente no reconoce la petición concreta ni explica la limitación. |
| 5 | Test (check) | Regex: `Rosa.{0,40}--.{0,5}[SMLX]\|Rosa.{0,80}euros` | 🔴 FAIL — cero ocurrencias de "Rosa" en la respuesta. Check apropiado: TC-DECO-01 (margaritas) pasa con el mismo patrón → la ausencia de rosas es un gap real del catálogo. |

### Causa raíz (descompuesta en 3 capas)

1. **Catálogo (capa principal)**: no existe ningún producto de tipo "Rosa" asociado a la ocasión "Decoración" en el inventario de petal-sheet-api. TC-DECO-01 (margaritas para decorar) pasa → el pipeline funciona cuando el producto existe; aquí el catálogo devuelve vacío para rosas+decoracion.
2. **Playbook Compra (secundaria)**: el fallback ante "sin resultados para esta ocasión" muestra alternativas genéricas sin reconocer el producto pedido. Lo correcto sería: "No tengo rosas disponibles para decoración, pero te ofrezco estas opciones similares".
3. **Gestión de inventario (estructural)**: el catálogo es parcial por ocasión — hay flores bien cubiertas (margaritas, tulipanes, hortensias) y otras sin cobertura para ciertos contextos. Rosas + Decoracion es el gap más evidente dado que rosas sí aparecen en boda/compra genérica.

## Recomendación

### Solución recomendada: #1 — Catálogo: agregar productos Rosa para ocasión Decoración

🟢 **9/10** · ~2h (backend + verificación) · Aprobación de negocio + redeploy petal-sheet-api

**Por qué**: fix de raíz. El usuario pidió rosas y el catálogo no las tiene para decoración. Agregar SKUs Rosa para Decoracion resuelve el test y la UX real. TC-DECO-01 confirma que el pipeline es correcto cuando los datos existen — aquí es un gap de datos, no de lógica.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Catálogo: agregar productos Rosa — S/M/L para ocasión Decoración en petal-sheet-api** | 🟢 9/10 | Aprobación negocio + redeploy petal-sheet-api | Fix de raíz. Si los productos existen, el pipeline los muestra — TC-DECO-01 lo confirma. Única solución que resuelve test + UX real. |
| 6 | **Combinación #1 + #5** (catálogo + playbook fallback digno) | 🟢 8/10 | Aprobación negocio + redeploy | Solución completa: datos correctos + fallback explícito para gaps futuros de inventario. ~2.5h total. |
| 5 | **Playbook Compra: CASO ESPECIAL "producto pedido sin stock de ocasión"** → reconocer el producto explícito + explicar la limitación antes de sugerir alternativas | 🟢 8/10 | — | Mejora UX sin tocar backend. No resuelve el FAIL del test (regex pide "Rosa" en respuesta) pero elimina la respuesta engañosa actual. ~20 min. Combinable con #1. |
| 4 | **Examples: EX-DECO-ROSAS** anclando "quiero rosas para decorar" → respuesta con rosas reales | 🟡 6/10 | Requiere #1 previo | Solo tiene efecto si el catálogo ya tiene rosas para decoración. Multiplicador, no sustituto. ~10 min. |
| 2 | **Playbook Compra: eliminar rama especial de Decoración** y siempre respetar `producto` independientemente de la ocasión | 🟡 5/10 | — | Puede funcionar si el catálogo tiene rosas genéricas sin tag de ocasión. Riesgo: puede romper TC-DECO-01 y otros flujos de decoración. Requiere análisis de impacto previo. |
| 3 | **Test: recalibrar check** para probar que el agente reconoce la limitación ("no tengo rosas para decoración") en lugar de exigir mostrar rosas | 🟡 5/10 | Requiere #5 previo | Solo válido si se implementa CASO ESPECIAL (#5) primero. Ajusta el test a un comportamiento alcanzable mientras el catálogo tiene el gap. No aplicar solo. |
| 7 | **No hacer nada** (deuda técnica) | 🔴 2/10 | — | Test seguirá fallando permanentemente. UX real engañosa: usuario pide rosas, recibe tulipanes sin explicación. Solo aceptable si negocio decide que rosas-decoración no es caso de uso relevante. |

### Plan de acción (Solución #1)

1. **Aprobación de negocio**: confirmar que "Rosa para decoración" es un caso de uso válido y qué SKUs añadir (talla S/M/L, precio, color).
2. **Editar inventario en petal-sheet-api**: añadir filas con productos Rosa y `ocasion=Decoracion` en la hoja de cálculo.
3. **Redeploy petal-sheet-api** en Cloud Run `europe-west1`.
4. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable.

**Coste total**: ~2h (decisión de negocio ~1h + edición + redeploy ~30 min + verificación ~30 min). Si solo se implementa #5 (playbook fallback): ~20 min, pero el test seguirá en FAIL.
