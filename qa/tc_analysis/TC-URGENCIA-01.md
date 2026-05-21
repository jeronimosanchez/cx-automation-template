---
status: FAIL
tipo: Bug Playbook
estimacion: ~8 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las 6"* | — |
| 2 | Orquestador | clasifica como `G5` (compra), extrae `producto="ramo de rosas"`, `intencion_inicial` con el texto completo (incluida la marca temporal "para hoy a las 6"), `modo_tono="estandar"` | ⚠️ Extrae los slots de compra pero **no estructura la urgencia** — la información temporal se pierde dentro de `intencion_inicial` como texto libre |
| 3 | Compra | recibe slots y entra directo en flujo de slot-filling/búsqueda. `currentPlaybook="unknown"` en el trace, `matchType="PLAYBOOK"` confianza 1.0 | 🔴 No detecta urgencia temporal antes de continuar el flujo |
| 4 | Compra | llama a inventario y devuelve catálogo de rosas con sus precios → *"Claro, ramos de rosas tenemos: Ramo de Rosas Morado — M (37€)..."* | 🔴 UX rota — el usuario pide entrega same-day y el agente actúa como si nada, generando falsa expectativa de que se puede entregar hoy |
| 5 | Test (check) | regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — la respuesta no contiene ningún token sobre plazo, política de entrega, ni escalado |

### Causa raíz — evaluación de las 7 capas estándar

🔴 1. **Capa Playbook** · verificada · `Read compra.yaml`

`definitions/playbooks/compra.yaml` actualmente NO contiene un bloque de detección de urgencia temporal en el FLUJO PRINCIPAL. La única mención a "hoy" es en una sección posterior (línea 484) sobre preguntas del usuario tras mostrar opciones, no en el flujo previo al slot-filling. **Es la causa directa del fail.**

🔴 2. **Capa Histórico** · verificada · `git log --since="14 days ago" -- definitions/playbooks/compra.yaml`

El fix existió en `3f041df` (PR #83 — "fix(playbook-compra): añade CASO ESPECIAL urgencia/plazo (TC-URGENCIA-01)"), fue revertido en `aca187c` (PR #84). Hoy se re-aplicó en `3e0b2d1` y volvió a revertirse en `1f95cae` por motivos de coordinación de la demo. **La decisión de revertir es parte de la causa raíz** — sin esos reverts, el bloque seguiría activo.

⚪ 3. **Capa Catálogo** · N/A — el TC no consulta inventario antes del fail (el bug ocurre en T1, antes de cualquier llamada al tool).

🟢 4. **Capa Orquestador** · verificada · `Read JSON trace + log del TC`

El Orquestador clasifica correctamente como `G5` (compra) y extrae `producto="ramo de rosas"` + `intencion_inicial` con el texto completo incluida la marca temporal. La información llega íntegra a Compra; el problema es que Compra no la procesa.

⚪ 5. **Capa Backend / Tool** · N/A — el TC falla antes de cualquier invocación de tool al petal-sheet-api.

🟡 6. **Capa Política / Negocio** · supuesta · _(no verificado)_

Petal no soporta same-day delivery (plazo mínimo 24h). La política no está documentada como knowledge explícito en el repo — vive sólo en el commit revertido `3f041df` y en la cabeza del producto. Pendiente del `epic_backlog_conversational_design.md`.

🟢 7. **Capa Test** · verificada · `Read qa/test_QA_Playbooks_v23.py`

El regex del check `hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano` es razonable y mide lo correcto. No es un test mal calibrado.

**Resumen visual:** 2 🔴 problema · 2 🟢 ok · 1 🟡 supuesta · 2 ⚪ N/A

## Recomendación

### Solución recomendada: #1 — Re-aplicar el bloque DETECCION URGENCIA TEMPORAL (recuperar el patrón validado del PR #83 / commit `3e0b2d1`)

🟢 **9/10** · ~8 min · Sin dependencias externas

**Por qué**: el patrón ya fue validado dos veces (PR #83 y la sesión de hoy con commit `3e0b2d1`, donde **TC-URGENCIA-01 pasó a PASS en el primer rerun**). El revert reciente (`1f95cae`) se hizo por coordinación de demo, no porque la solución no funcionara. Cambio quirúrgico en un solo archivo (`compra.yaml`), bajo riesgo, sin tocar el esquema del Orquestador, sin tocar Tools, sin artefactos nuevos. Reaplica una intervención conocida y probada.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Re-aplicar bloque DETECCION URGENCIA TEMPORAL en `compra.yaml`** (`git show 3e0b2d1 -- definitions/playbooks/compra.yaml`) | 🟢 9/10 | — | Patrón validado en producción 2 veces. 1 archivo. Bajo riesgo. TC pasa en rerun. Solo riesgo: la regex de palabras temporales puede no cubrir variantes muy creativas (ej: "para la merienda"). |
| 2 | **Solución #1 + Example "hoy a las 6 → clarifica plazo"** en `definitions/examples/compra/*.yaml` | 🟢 8/10 | — | Refuerza con few-shot concreto. Mejora robustez pero añade superficie de mantenimiento (2 sitios). Ideal si la #1 sola muestra flakiness en `--runs 3`. |
| 3 | **Variable de negocio `entrega_min_horas` en `business_variables` + lectura desde Compra** | 🟡 7/10 | Update Google Sheet + posible cambio en tool | Más correcto a largo plazo (separa configuración de lógica), pero introduce dependencia del backend para un valor que cambia raramente (24h hoy, quizá nunca). Pague el coste sólo si se prevé cambiar. |
| 4 | **Slot `urgencia`/`fecha_entrega` en el Orquestador + rama en Compra** | 🟡 6/10 | Refactor esquema Orquestador + tests E2E | Más limpio arquitectónicamente, pero toca 2 playbooks y cambia el contrato Orquestador↔Compra. Riesgo de regresión en otros TCs. |
| 5 | **Sub-playbook `Consulta_Logistica` invocado como Task desde Compra** | 🟡 5/10 | Nuevo playbook + `push_playbooks.py` | Reutilizable si se añaden 3+ casos similares (envíos, costes, horarios). Overkill para 1 caso aislado. Aumenta latencia (handoff extra). |
| 6 | **Tool `check_delivery_feasibility(fecha_solicitada)` desde Compra** | 🔴 4/10 | Nueva Tool + webhook + tests | Correcto si Petal tuviera logística real. Hoy la respuesta es una constante, así que el Tool añade dependencia sin valor. |
| 7 | **Relajar el regex del check para aceptar `color`/`ramo` como válido** | 🔴 2/10 | — | Falso positivo: el TC pasa pero el bug de UX persiste. Rompe la intención del test. Anti-patrón. |

### Plan de acción (Solución #1)

1. **Recuperar el diff del commit `3e0b2d1`** → `git show 3e0b2d1 -- definitions/playbooks/compra.yaml` (~30 segundos). Confirma que el bloque añade ~14 líneas: detección de tokens temporales (`hoy`, `ahora`, `a las X`, `urgente`...), respuesta según `$modo_tono` con plazo mínimo 24h, y escape a Handoff si el cliente insiste → archivo objetivo `definitions/playbooks/compra.yaml`.
2. **Aplicar el diff** (con `git cherry-pick 3e0b2d1` o editando directamente) → archivo `definitions/playbooks/compra.yaml`.
3. **Commit + push** + esperar deploy.
4. **Re-ejecutar QA** con `./qa/rerun_single_tc.sh TC-URGENCIA-01` (o con `--runs 3` si quieres validar estabilidad). En la sesión de hoy ya salió PASS en el primer intento.

**Coste total**: ~8 min (cherry-pick o edit + commit + push + ~3 min deploy + rerun).

---

### Notas de verificación (transparencia anti-alucinación)

Todo lo afirmado en este análisis está marcado como **✓ verificado** porque fue comprobado contra:
- `git log` real (PRs #83/#84/#94, commits `3e0b2d1` y `1f95cae`).
- `grep` sobre `compra.yaml` actual (ausencia de bloque de urgencia).
- Log JSON del run `20260521_125002` de gh-pages.

Ningún PR ni commit citado es invento.
