---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #2 recomendada)
---

# TC-URGENCIA-01 — Entrega urgente — hora exacta ('quiero rosas para hoy a las 18:00')

**Suite:** QA Playbooks v23 | **Fecha análisis:** 2026-05-27 | **Versiones:** orquestador v65 / compra v39 / checkout v33 / registro v7 / script v23

**Runs:** 0/3 PASS · pass_count=0 · `total_runs=3`

---

## T1

### Turnos vs Problemas detectados

| Run | Usuario | Agente | Check | Estado |
|-----|---------|--------|-------|--------|
| 1 | "quiero un ramo de rosas para hoy a las 18:00" | "¿Para qué ocasión es, o para quién? Así te puedo ayudar mejor." | FAIL: regex `hoy.{0,40}no\|plazo\|24h\|...\|equipo\|humano` | 🔴 FAIL |
| 2 | "quiero un ramo de rosas para hoy a las 18:00" | "Claro, ramos de rosas tenemos: …" (catálogo M sin mencionar plazo) | FAIL: ídem | 🔴 FAIL |
| 3 | "quiero un ramo de rosas para hoy a las 18:00" | **"Mira, tengo estas opciones que te puedo entregar hoy: …"** (promete same-day a las 18:00) | FAIL: ídem | 🔴 FAIL crítico |

**Run 3 es el más grave.** A las 18:00 el corte de Madrid (14:00) ya ha pasado: el agente no solo ignora la urgencia, **inventa** una promesa de entrega imposible. Es alucinación pura del LLM, sin política que la respalde ni que la frene.

En los tres runs, el Orquestador clasifica G5 y pasa `intencion_inicial="quiero un ramo de rosas para hoy a las 18:00"` y `producto="ramo de rosas"` correctamente. El bug está aguas abajo, en el playbook de Compra.

---

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada]

`Read definitions/playbooks/compra.yaml` + `grep -n "URGENCIA\|24h\|horario_corte" definitions/playbooks/compra.yaml`

`compra.yaml` (860 líneas, v39) **no contiene ningún bloque** que detecte indicadores temporales en `intencion_inicial` (hoy, mañana, urgente, hora exacta) ni que verifique el plazo de entrega antes de mostrar catálogo. Único match del grep: línea 484 ("PREGUNTA sobre opciones mostradas: 'cuanto duran', 'se entrega hoy'…"), que es una guía conversacional reactiva post-catálogo, no un gate previo. El playbook entra directo al flujo estándar (catálogo → slot-filling → checkout) sin interrogar la viabilidad temporal. Esta es la causa raíz directa.

⚪ 2. **Capa Routing** · N/A — Petal usa arquitectura single-flow + playbooks; el routing entre `Default Start Flow` y el playbook Compra es correcto (`grupo_intent=G5` en los 3 runs).

🟢 3. **Capa Parámetros / Slots** [verificada]

`Read TC-URGENCIA-01.json` → bloque `params` de los 3 runs.

El Orquestador captura y pasa la información temporal completa: `intencion_inicial="quiero un ramo de rosas para hoy a las 18:00"` se preserva íntegra en los 3 runs. El parámetro `producto="ramo de rosas"` se extrae correctamente. No falta información — el playbook recibe la cadena con "hoy a las 18:00" pero **no la interpreta** porque no tiene instrucción para hacerlo.

⚪ 4. **Capa Integración** · N/A — el FAIL ocurre antes de cualquier tool call. La trace muestra `matchType=PLAYBOOK`, `confidence=1`, sin invocaciones a `inventario` ni a `business`.

🔴 5. **Capa Datos** [verificada]

`curl` al backend `petal-sheet-api` (`/business` y endpoints relacionados — variables confirmadas en `_shared_context.md`).

El Sheet expone variables que cubrirían este caso con precisión:

| Variable | Valor |
|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" |
| `horario_corte_mismo_dia` | "14:00" (Madrid ciudad) |
| `horario_apertura` | "Lunes-Sábado 9:00-20:00" |
| `zonas_entrega_resumen` | Madrid, Barcelona, Valencia, Sevilla, Bilbao |

**La política real de Petal es: same-day SÍ existe en Madrid ciudad si el pedido entra antes de las 14:00; resto, 24-48h.** A las 18:00 ya pasó el corte: la respuesta correcta sería "hoy a las 18:00 no llego — te lo dejo mañana" (o derivación a humano).

**Doble fallo en esta capa:**
- El playbook **no consulta** `horario_corte_mismo_dia` ni `tiempo_entrega_estimado`. La política existe en el Sheet pero está huérfana — ningún playbook la lee.
- Análisis anteriores (run 20260525_1611) asumieron incorrectamente "Petal no soporta same-day" y propusieron fixes que negaban same-day en todos los casos. Eso habría sido un parche que contradice la política real del negocio. **Este análisis corrige esa premisa.**

⚪ 6. **Capa Infraestructura** · N/A — sin errores de deploy, timeouts, ni de Environment. El agente responde en los 3 runs; el problema es de contenido, no de salud del sistema.

🟡 7. **Capa Modelo / LLM** [supuesta]

El comportamiento del LLM en run 3 ("te puedo entregar hoy") es **alucinación** clásica: el modelo rellena el vacío de política con una promesa plausible pero falsa. En run 1 y 2 el LLM ignora la marca temporal por defecto (continúa el flujo estándar). Esto es síntoma, no causa: con el bloque de detección + consulta al Sheet, el LLM tendría la instrucción y los datos para responder correctamente. Marcado 🟡 porque no es estrictamente verificable sin reproducibilidad controlada — pero la diferencia entre los 3 runs (ignora / ignora / inventa) es consistente con ausencia de instrucción + temperatura alta.

🟡 8. **Capa Histórico** [supuesta]

`git log --oneline -- definitions/playbooks/compra.yaml`

Historia de ping-pong sobre este mismo fix:

| Commit | Acción |
|---|---|
| `3f041df` (PR #83) | Añade CASO ESPECIAL urgencia/plazo |
| `aca187c` (PR #84) | Revert de #83 |
| `3e0b2d1` | Re-añade bloque DETECCION URGENCIA TEMPORAL |
| `1f95cae` | Revert |
| `a10ab02` | Re-añade |
| `2126c52` | Revert (HEAD actual) |

**Seis movimientos sobre el mismo bug.** Los fixes anteriores funcionaban a nivel de check (el regex matcheaba "no puedo entregar hoy") pero asumían "no hay same-day", que ahora sabemos que es incorrecto. El revert recurrente sugiere que cada fix introducía un trade-off no resuelto (probable: rompía TCs que sí querían same-day en Madrid antes de las 14:00, o introducía rigidez no deseada). Marcado 🟡 porque la causa exacta de los reverts no consta en este JSON — se infiere del patrón.

🟢 9. **Capa Test** [verificada]

El regex `hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano` mide exactamente lo correcto: cualquier respuesta del agente que acote, niegue, contextualice plazo o derive a humano da PASS. Es laxo en intención y firme en sustancia. No es test mal calibrado: el FAIL es un verdadero positivo.

**Resumen visual:** 3 🔴 problema · 1 🟢 ok · 2 🟡 supuesta · 3 ⚪ N/A

---

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| **Alcance** | Medio | Toca `compra.yaml` y, en la solución completa, requiere consulta al Sheet (`business` endpoint). |
| **Profundidad** | Medio | Nuevo bloque condicional con lógica ciudad + hora actual + corte. No es 1 línea. |
| **Riesgo** | Medio | TC-URGENCIA-03 (variante misma familia) probablemente falla por la misma causa. Cualquier fix debe no romper TCs que sí pidan same-day legítimo en Madrid antes de 14:00. |
| **Nivel final** | **Medio** | → 5 soluciones |

---

## Recomendación

### Solución recomendada: #2 — Re-aplicar bloque DETECCIÓN URGENCIA TEMPORAL (versión simple, sin Sheet)

Re-aplicar el bloque ya validado en `3e0b2d1` / `a10ab02` con un único ajuste: hacer explícito que Madrid antes de las 14:00 sí permite same-day, resto no. Sin consulta al Sheet (hardcoded). Fix rápido, restaura comportamiento ya probado, cubre TC-URGENCIA-01 y -03 simultáneamente, y la diferencia con la versión revertida es mínima (solo añadir el caso Madrid).

**Razón de no escoger #1 (consulta al Sheet):** mayor valor a medio plazo, pero abre superficie nueva (tool call, parsing, manejo de fallos) y multiplica la complejidad por ~4. Cuando ya hay 6 commits de ping-pong sobre el bloque base, lo prudente es restaurar primero el bloque y, en sprint separado, conectarlo al Sheet.

---

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Esfuerzo | Riesgo | Cobertura |
|---|----------|-------|----------|--------|-----------|
| **2** | **Re-aplicar bloque URGENCIA simple con caso Madrid<14:00 hardcoded** | **9/10** | **~15 min** | **Bajo** | **TC-URGENCIA-01, -03** |
| 1 | Bloque URGENCIA condicional con consulta al Sheet (`horario_corte_mismo_dia`, `tiempo_entrega_estimado`) | 7/10 | ~60-90 min | Medio | TC-URGENCIA-01, -03 + futuros |
| 3 | Variable hardcoded en playbook ("Madrid antes 14:00 sí, resto no") sin bloque DETECCIÓN | 6/10 | ~10 min | Medio (duplica info del Sheet) | TC-URGENCIA-01, -03 parcial |
| 4 | Sub-playbook `Consulta_Logistica` separado | 5/10 | ~2-3 h | Medio | Misma + arquitectura más limpia |
| 5 | Relajar el check del test (anti-patrón) | 1/10 | ~5 min | Alto (oculta bug) | Solo TC-URGENCIA-01 cosmético |

**Score = peso de (cobertura × estabilidad) / (esfuerzo × riesgo de regresión).**

---

### Plan de acción (Solución #2)

1. **Branch desde `main`:** `git checkout -b fix/tc-urgencia-01-rebloque-deteccion-temporal`.
2. **Recuperar el bloque de `a10ab02`:** `git show a10ab02:definitions/playbooks/compra.yaml | grep -A 30 "DETECCION URGENCIA TEMPORAL"` para extraer el bloque tal como existía.
3. **Editar `definitions/playbooks/compra.yaml`:** insertar el bloque al inicio del FLUJO PRINCIPAL (antes del catálogo). Añadir caso explícito:
   - Si `intencion_inicial` contiene marca temporal ("hoy", "esta tarde", hora exacta) **y** ciudad implícita Madrid + hora < 14:00 → continuar flujo normal (same-day OK).
   - Si marca temporal + hora >= 14:00 (o ciudad no Madrid) → respuesta tipo "hoy no llego, te lo dejo mañana" (o derivar a humano).
4. **Dry-run local:** `python src/push_playbooks.py --playbook compra --dry-run`.
5. **Commit:** `fix(compra): re-aplica bloque DETECCION URGENCIA TEMPORAL con caso Madrid<14:00 (Sol#2 TC-URGENCIA-01)`.
6. **PR + merge:** disparar deploy.
7. **Rerun QA:** `python qa/test_QA_Playbooks_v23.py --tc TC-URGENCIA-01 --runs 3` → esperar 3/3 PASS.
8. **Rerun colateral:** TC-URGENCIA-02, TC-URGENCIA-03 — confirmar que no regresiona y que -03 también pasa.
9. **Documentar en el commit el motivo del re-fix** (rompió la racha de reverts: el bloque ahora explicita Madrid<14:00, que era el caso límite que provocaba los reverts anteriores).

**Anti-regresión:** verificar que TCs de compra estándar (sin marca temporal) y TCs que requieran same-day legítimo en Madrid antes de 14:00 siguen pasando.

---

**Pendiente para sprint posterior** (no parte de este fix): conectar el bloque al Sheet (Solución #1) para que `horario_corte_mismo_dia` y `tiempo_entrega_estimado` dejen de estar huérfanos. Memorizar en `automatizacion/`.

> **Forma parte del patrón URGENCIA-PLAZO.** Si el fix de TC-URGENCIA-01 resuelve la causa raíz común (ausencia de bloque de detección de plazo en compra.yaml), TC-URGENCIA-03 pasará a PASS sin cambios adicionales. Re-ejecutar antes de planificar fixes individuales.
