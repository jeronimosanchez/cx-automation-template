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
| 2 | Orquestador | clasifica como G5 (compra), extrae `producto=ramo de rosas`, `intencion_inicial` completa, `modo_tono=estandar`. **NO extrae slot de urgencia/fecha** | ⚠️ Pierde la señal "hoy a las 6" — no hay slot `urgencia` ni `fecha_entrega` en el esquema |
| 3 | Compra | recibe slots y entra directo en slot-filling de color, ignorando la dimensión temporal del mensaje | 🔴 No hay rama CASO ESPECIAL para urgencia/plazo (PR #83 lo añadía, PR #84 lo revirtió) |
| 4 | Agente | *"¿De qué color te gustaría el ramo de rosas?"* | 🔴 UX rota — el user pide algo imposible (same-day) y el agente continúa como si nada, generando falsa expectativa |
| 5 | Test (check) | regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — la respuesta del agente no contiene ninguno de los tokens esperados (ni clarifica plazo, ni redirige a humano, ni informa de simulación) |

### Causa raíz (descompuesta en 3 capas)

1. **Capa 1 (Playbook Compra)**: tras el revert del PR #84, el Playbook Compra no tiene rama CASO ESPECIAL que detecte expresiones de urgencia ("hoy", "para esta tarde", "ya", "ahora", "en X horas", "urgente") y responda con la política real de Petal (entrega 24-48h, no same-day). El bug está activo de forma intencionada para la demo.
2. **Capa 2 (Orquestador)**: el esquema de slots del Orquestador no contempla `urgencia` ni `fecha_entrega_solicitada` como dimensiones extraíbles del primer turno. La información temporal del mensaje se pierde antes de llegar a Compra, así que aunque Compra tuviera la rama, no recibiría la señal estructurada (Compra tendría que detectarla en `intencion_inicial`).
3. **Capa 3 (política de producto)**: Petal no soporta same-day delivery pero esa restricción no está codificada como knowledge explícito en ningún artefacto — vive sólo en la cabeza de Jero. El agente no tiene forma de "saber" que hoy a las 6 es imposible sin una regla explícita en algún playbook o knowledge base.

## Recomendación

### Solución recomendada: #1 — Playbook Compra: CASOS ESPECIALES urgencia/plazo

🟢 **9/10** · ~8 min · Sin dependencias externas

**Por qué**: es el mismo patrón que ya validamos en PR #83 (revertido sólo para la demo). Cambio quirúrgico en un solo archivo, sin tocar el esquema del Orquestador, sin tocar Tools, sin nuevos artefactos. Reaplica una intervención conocida y probada. El TC vuelve a PASS en el primer rerun y mejora la UX real (gestiona expectativas del cliente en lugar de dejarlas implícitas).

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | Playbook Compra: añadir CASO ESPECIAL urgencia/plazo (re-aplicar PR #83) | 🟢 9/10 | — | Patrón validado, 1 archivo, bajo riesgo, TC pasa en rerun. Trigger con regex estricto para no pisar fechas legítimas ("para mañana", "el lunes") |
| 2 | Playbook Compra: CASO ESPECIAL urgencia + Example "hoy a las 6 → clarifica plazo" | 🟢 8/10 | — | Refuerza con ejemplo concreto few-shot, pero añade superficie de mantenimiento (2 sitios sincronizados) |
| 3 | Orquestador: añadir slot `urgencia`/`fecha_entrega` + rama en Compra que lo consume | 🟡 7/10 | Refactor esquema Orquestador + tests E2E | Solución arquitectónicamente más limpia, pero toca 2 playbooks y cambia el contrato Orquestador↔Compra. Riesgo de regresión en otros TCs |
| 4 | Sub-playbook `GestionUrgencia` invocado como Task desde Compra (y reutilizable por Decoración/Suscripción) | 🟡 6/10 | Nuevo playbook + push_playbooks | Buena separación, reutilizable, pero overkill para un único caso hoy. Aumenta superficie de fallos y latencia (handoff extra) |
| 5 | Tool `check_delivery_feasibility(fecha_solicitada)` que Compra llama si detecta urgencia | 🟡 5/10 | Nueva Tool + webhook + tests | Correcto a largo plazo (cuando haya logística real) pero overkill hoy — la respuesta es siempre la misma constante. Introduce dependencia de webhook |
| 6 | Generator que inyecta "considera plazo de entrega" en el prompt de Compra cuando hay marcadores temporales | 🟡 5/10 | Nuevo Generator | Opaco y poco determinístico: depende de que el LLM "interprete" la instrucción. Menos predecible que un CASO ESPECIAL explícito |
| 7 | Relajar el regex del check para aceptar "color"/"ramo" como válido | 🔴 2/10 | — | Falso positivo: el TC pasaría pero el bug de UX seguiría ahí. Rompe la intención del test. Anti-patrón |

### Plan de acción (Solución #1)

1. **Recuperar el diff del PR #83** (`gh pr view 83 --json files` o `git show <sha de #83>`) y extraer la sección CASO ESPECIAL urgencia/plazo → archivo objetivo `definitions/playbooks/Compra.yaml`
2. **Añadir la rama** detectando tokens estrictos: `hoy`, `esta tarde`, `esta noche`, `ya`, `ahora mismo`, `en X horas`, `para hoy`, `urgente` → respuesta tipo: *"Para hoy mismo no podemos garantizar la entrega; nuestros pedidos se entregan en 24-48h. ¿Quieres que confirmemos para mañana o prefieres que un humano del equipo te ayude con una opción más rápida?"* → archivo `definitions/playbooks/Compra.yaml`. Acotar regex para no disparar en "para mañana" / "el lunes"
3. **Re-ejecutar QA** con `--runs 3` sobre TC-URGENCIA-01 (mitiga flakiness ±2-3 TCs documentada en `shared/feedback_qa_runs1_flakiness.md`) y verificar que ningún otro TC del grupo COMPRA-ZG regresa

**Coste total**: ~8 min (1 min recuperar diff + 2 min edit + 2 min PR/merge + ~3 min deploy + rerun)
