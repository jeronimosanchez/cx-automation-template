---
status: FAIL
tipo: Bug Playbook
estimacion: ~10 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las 6"* | — |
| 2 | Orquestador | clasifica como G5 (Compra) → handoff a Compra, extrae `producto=ramo de rosas` | ✅ Clasificación correcta, pero ⚠️ no marca la urgencia ("hoy a las 6") como señal a propagar |
| 3 | Compra | ignora el marcador temporal "hoy a las 6" y entra directo a slot-filling (color) | 🔴 No hay CASO ESPECIAL urgencia/plazo en el Playbook Compra |
| 4 | Agente | *"¿De qué color te gustaría el ramo de rosas?"* | 🔴 Respuesta funcional pero falsa expectativa: el usuario asume que su plazo "hoy a las 6" es viable, cuando Petal solo entrega en 24-48h |
| 5 | Test (check) | Regex `[hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano]` | 🔴 FAIL — el agente no menciona plazo, no clarifica imposibilidad de same-day, ni ofrece humano |

### Causa raíz (descompuesta en 3 capas)

1. **Capa 1 (Playbook Compra)**: no existe un CASO ESPECIAL que detecte palabras de urgencia/plazo ("hoy", "ahora", "en X horas", "esta tarde", "urgente") y responda con el plazo real (24-48h) + opción de escalado a humano. El PR #83 añadía exactamente este CASO pero fue revertido en el PR #84, dejando el bug activo.
2. **Capa 2 (Orquestador)**: clasifica G5 correctamente pero no tiene una señal/slot `urgencia_temporal` que pueda propagar a Compra para activar el camino especial. Aunque añadir esto sería deseable, no es bloqueante: Compra puede detectarlo en su propio texto de entrada.
3. **Capa 3 (estructural/negocio)**: Petal opera con simulación de entrega 24-48h. No existe pipeline real same-day. El agente debe ser explícito sobre el plazo en lugar de dejar que el usuario asuma viabilidad de su petición temporal.

## Recomendación

### Solución recomendada: #1 — Playbook Compra: añadir CASOS ESPECIALES urgencia/plazo

🟢 **9/10** · ~10 min · Sin dependencias externas

**Por qué**: es exactamente el fix del PR #83 (revertido), validado conceptualmente. Localizado en un solo archivo (`definitions/playbooks/Compra.yaml`), no toca orquestador ni catálogo, coste mínimo, cubre el regex del test y mejora UX real (gestiona expectativas del cliente). El revert de #84 sugiere que hubo regresión colateral — esta vez se mete con regex de detección más estricto y se valida con `--runs 3` antes del merge.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Playbook Compra: añadir CASOS ESPECIALES urgencia/plazo (detectar "hoy/ahora/urgente/en X horas" → responder con 24-48h + ofrecer humano)** | 🟢 9/10 | — | Fix localizado, ya validado conceptualmente en PR #83. Riesgo bajo si se acota el trigger con regex estricto y se valida con runs múltiples. |
| 2 | **Orquestador: nuevo slot `urgencia_temporal` + propagación a Compra que activa rama especial** | 🟢 8/10 | Cambio en Orquestador + Compra | Más limpio arquitectónicamente (separación clasificación/ejecución), pero toca 2 playbooks y requiere coordinar slots. Más coste, mismo resultado funcional. |
| 3 | **Añadir un sub-playbook `GestionUrgencia` invocado como Task desde Compra cuando detecta urgencia** | 🟡 7/10 | Nuevo playbook + push | Buena separación de responsabilidades y reutilizable (Decoración, Suscripción también podrían usarlo), pero overkill para el bug puntual y aumenta superficie de fallos. |
| 4 | **Tool `check_delivery_availability(fecha, hora)` que devuelve "no disponible same-day, próximo slot: mañana"** | 🟡 6/10 | Nuevo Tool + Webhook | Más "real" como simulación, pero introduce dependencia de Tool para un caso que se resuelve con texto estático. Sobrediseño. |
| 5 | **Añadir Intent específico `urgencia_entrega` y Page dedicada con respuesta canned** | 🟡 5/10 | Intents + Pages + Flows | Romper el patrón Playbook-centric del agente por un caso edge. Aumenta complejidad NLU sin ganancia clara. |
| 6 | **Generator dedicado que enriquezca el prompt de Compra con "considera plazo de entrega" cuando hay marcadores temporales** | 🟡 5/10 | Nuevo Generator | Posible pero opaco: depende de que el LLM "interprete" la instrucción, menos determinístico que un CASO ESPECIAL explícito. |
| 7 | **Relajar el regex del test para que pase cualquier respuesta de Compra (aceptar slot-filling como válido)** | 🔴 2/10 | — | Ocultar el bug. El TC existe precisamente porque la respuesta actual es UX-incorrecta (genera falsa expectativa). Anti-patrón. |

### Plan de acción (Solución #1)

1. **Editar `definitions/playbooks/Compra.yaml`** → añadir bloque CASO ESPECIAL: "Si el usuario menciona urgencia temporal (hoy, ahora, urgente, esta tarde, en X horas, antes de las HH), responder: 'Para hoy mismo no podemos garantizar la entrega; nuestros pedidos se entregan en 24-48h. ¿Quieres que confirmemos para mañana o prefieres que un humano del equipo te ayude con una opción más rápida?'". Trigger con regex estricto para evitar falsos positivos en "para mañana", "para el lunes" etc.
2. **Revisar el diff con el PR #83 revertido** → identificar qué causó el revert en #84 y blindar el nuevo CASO (regex más acotado, no interferir con otros TCs de Compra).
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable y verificar que no hay regresión en los otros TCs de COMPRA-ZG (especialmente los que mencionan fechas/plazos legítimos).

**Coste total**: ~10 min (edit + PR + merge + deploy + rerun)
