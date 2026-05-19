---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las 6"* | — |
| 2 | Orquestador | Clasifica como `G5` (compra) y extrae `producto=rosas` | ✅ Clasificación correcta. ⚠️ NO extrae slot de urgencia/fecha (`fecha_entrega`, `hora_entrega`, `urgencia` — ninguno presente) |
| 3 | Playbook Compra | Procede directamente a mostrar catálogo de rosas (3 opciones: Morado/Amarillo/Blanco M) | 🔴 Ignora la información temporal del usuario ("hoy a las 6"). No clarifica plazo de entrega ni redirige al equipo |
| 4 | Agente | *"Claro, tenemos ramos de rosas en varios colores y tamaños. Por ejemplo: \[lista\] ¿Alguno te convence?"* | 🔴 Respuesta inadecuada: el usuario tiene una restricción dura (entrega hoy) y el agente la ignora completamente. Si compra y la entrega no es posible, se genera frustración / posible cancelación |
| 5 | Test (check) | Regex pide: `hoy.{0,40}no \| plazo \| 24h \| 24 horas \| entrega.{0,30}simulad \| entrega.{0,30}disponible \| equipo \| humano` | 🔴 Check FAIL — el regex es generoso (7 patterns válidos) y el agente no produce NINGUNO. Señal real de regresión |

### Causa raíz (descompuesta en 3 capas)

1. **Playbook Compra (capa principal)**: no tiene CASOS ESPECIALES para "petición con restricción temporal". El playbook entra directo en modo "buscar producto → mostrar catálogo" sin chequear primero si la petición tiene urgencia/plazo que el negocio no puede cumplir.
2. **Orquestador**: clasifica bien como G5 (compra) y extrae `producto`, pero NO extrae slot de urgencia/fecha. Sin slot, el playbook ni siquiera puede saber que hay una restricción temporal.
3. **Política de negocio**: no hay regla explícita sobre qué hacer ante peticiones urgentes. Asumiendo que actualmente Petal no soporta same-day delivery, la respuesta correcta es informar plazo real (24-48h) y/o redirigir al equipo si el cliente insiste.

## Recomendación

### Solución recomendada: #1 — Playbook Compra: añadir CASOS ESPECIALES "petición con urgencia/plazo"

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: bug real del agente, no del test. El check ya es generoso (7 patterns). La solución más conservadora y de mayor impacto es añadir una regla en el Playbook Compra para detectar palabras temporales (hoy, mañana, urgente, a las X, ahora, ya) y responder ANTES de mostrar catálogo con: "Actualmente las entregas se gestionan en 24-48h. Si necesitas algo urgente, te paso con mi equipo". Encaja con el patrón ya usado en otros CASOS ESPECIALES del playbook.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Playbook Compra: CASOS ESPECIALES "urgencia/plazo"** — detectar palabras temporales y clarificar plazo o redirigir antes de catálogo | 🟢 9/10 | — | **RECOMENDADO**. Fix de raíz, sin dependencias, en el lugar correcto (Playbook). Patrón ya usado en otros casos especiales. ~15 min. |
| 3 | **Combinar #1 + #2** (Playbook + Orquestador slot) | 🟢 8.5/10 | Tests Orquestador | Solución más robusta: orquestador extrae `urgencia` como slot, playbook lo lee. Más limpio arquitectónicamente pero ~40 min y toca 2 capas. |
| 2 | **Orquestador: extraer slot `urgencia` o `fecha_entrega`** | 🟢 8/10 | Tests Orquestador | Captura la info temporal en params. Necesita complemento en playbook para reaccionar. Solo no resuelve el bug. ~30 min. |
| 4 | **Examples: añadir `EX-URGENCIA-01`** anclando *"necesito hoy"* → *"actualmente entrega es 24h"* | 🟢 7/10 complementario | — | Refuerza determinismo del LLM. Multiplicador de #1, no sustituto. ~10 min. |
| 6 | **Backend: implementar same-day delivery real** | 🟡 5/10 | Negocio + backend + logística | Sobre-ingeniería para un MVP. Solo válido si negocio decide ofrecer same-day como producto. Días/semanas. |
| 5 | **Test: relajar regex** para aceptar respuestas que solo muestren catálogo | 🔴 3/10 | — | Falso fix. El agente está mal: ignora restricción dura del usuario. Relajar el test pierde señal de regresión real. NO recomendado. |
| 7 | **No hacer nada** (aceptar FAIL como deuda técnica permanente) | 🔴 2/10 | — | Test seguirá fallando, pierde señal. Riesgo de frustración real con clientes. NO recomendado. |

### Plan de acción (Solución #1)

1. **Editar Playbook Compra** (`definitions/playbooks/Compra/instruction.md` o equivalente) → añadir bloque:
   ```
   ### CASOS ESPECIALES

   - **Petición con urgencia/plazo concreto** (palabras clave: "hoy", "mañana", "ahora", "urgente", "ya", "a las HH", "antes de HH"):
     ANTES de mostrar catálogo, responde:
     "Actualmente las entregas se gestionan en 24-48h. Si necesitas algo urgente,
     puedo pasarte con mi equipo para que vean qué pueden hacer."
     Si el usuario insiste → handoff al equipo (razón: `urgencia_no_cubierta`).
   ```
2. **Commit + push** → CI auto-corre `Deploy to Petal CX` + `QA Petal`.
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable y descartar flakiness.

**Coste total**: ~15 min (edit + commit + verificación post-merge).
