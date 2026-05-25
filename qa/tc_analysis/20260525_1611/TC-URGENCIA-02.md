---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

# TC-URGENCIA-02 — Entrega urgente — variante hora textual ("hoy a las seis de la tarde")

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las seis de la tarde"* | — |
| 2 | Compra | Entra directo al flujo de slot-filling y consulta catálogo: *"Claro, ramos de rosas tenemos. Mira: Ramo de Rosas Morado — M (15 flores, 37€), Ramo de Rosas Amarillo — M (12 flores, 25€), Ramo de Rosas Blanco — M (12 flores, 25€). ¿Alguna te convence?"* | 🔴 No detecta urgencia temporal antes de continuar. Muestra catálogo generando falsa expectativa de entrega esa misma tarde |
| 3 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado |

**Estabilidad:** 0/1 runs pasan. Síntoma idéntico a TC-URGENCIA-01 y TC-URGENCIA-03. No hay flakiness (causa determinista).

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 **1. Capa Comportamiento** [verificada] · Fuente: `git log -- definitions/playbooks/compra.yaml` + estado HEAD `2126c52`

Causa principal. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional para demo 21-may). Sin él, el playbook salta directamente al PASO 0 (mostrar catálogo) sin verificar si `$intencion_inicial` contiene urgencia temporal. La variante "seis de la tarde" (hora textual en español) está cubierta por el patrón de detección del bloque revertido (`'a las 6', 'a las 18:00', 'para las X'`), pero el bloque no existe en la versión actual.

⚪ **2. Capa Routing** · N/A — Petal usa arquitectura de Playbooks. El enrutamiento hacia Compra es responsabilidad del Orquestador y funcionó correctamente (llegada confirmada al playbook Compra, catálogo mostrado).

🟢 **3. Capa Parámetros / Slots** [verificada] · Fuente: campo `user` del JSON del run (turno 1)

La expresión "hoy a las seis de la tarde" llega al playbook Compra como parte del mensaje del usuario. El slot `$intencion_inicial` incluye la marca temporal. El problema es que las instrucciones del playbook no la inspeccionan para detectar urgencia antes de avanzar al slot-filling del catálogo.

🟢 **4. Capa Integración** [verificada] · Fuente: campo `agent` del JSON del run (turno 1)

El agente muestra precios reales del catálogo (37€, 25€, 25€), confirmando que PetalDataTool respondió correctamente. No hay error de tool call. El bug ocurre upstream: el playbook debió clarificar el plazo antes de invocar inventario.

🟡 **5. Capa Datos** [supuesta] · Fuente: Sheet (`recurso=business`) — SHEET_OK; matiz relevante heredado de TC-URGENCIA-01

| Variable | Valor Sheet | Impacto en CX |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta genérica para consultas sin zona declarada |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) · 5.90€ (gratis >50€)" | Única zona con envío same-day. Corte: 14:00 |
| `horario_corte_mismo_dia` | "14:00" | — |

**Hallazgo:** para "hoy a las seis de la tarde" (18:00h), el corte de 14:00 ya ha pasado, por lo que la respuesta "24h mínimo" es correcta en este caso concreto. La Capa Datos no es causa del FAIL. Marcado 🟡 por coherencia con el análisis de patrón (la inexactitud aparece en pedidos desde Madrid ciudad antes de las 14:00, no en este escenario).

⚪ **6. Capa Infraestructura** · N/A — versiones `orquestador v65 / compra v39 / checkout v33` en el JSON corresponden al estado post-revert (`2126c52`). El problema está en el contenido del playbook, no en el entorno desplegado.

🟢 **7. Capa Modelo / LLM** [verificada] · Fuente: campo `agent` del JSON del run (turno 1)

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de detección de urgencia → muestra catálogo. Comportamiento determinista dado el prompt. La causa está en las instrucciones, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · Fuente: `git log --oneline -- definitions/playbooks/compra.yaml`

Mismo patrón de regresión intencional que TC-URGENCIA-01:

| Commit | Acción | Contexto |
|---|---|---|
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL) | TC-URGENCIA-01/02/03 pasaron a PASS |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | TC pasó a PASS en rerun; fix validado en producción para los 3 TCs del patrón |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El commit `a10ab02` está documentado como cherry-pick validado en producción que resolvió TC-URGENCIA-01, TC-URGENCIA-02 y TC-URGENCIA-03 simultáneamente. El fix es conocido-bueno.

🟢 **9. Capa Test** [verificada] · Fuente: campo `checks` del JSON del run

Regex bien calibrado: `hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano`. La variante textual "seis de la tarde" no afecta la validez del check — el check no valida cómo el usuario expresa la hora, sino si el agente responde con política de plazo. TC válido, no hay falso positivo.

**Resumen visual:** 2 🔴 · 3 🟢 · 1 🟡 · 3 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), restaurar 14 líneas ya escritas y probadas |
| Profundidad | Trivial | Restaurar instrucción condicional existente, sin nueva lógica |
| Riesgo de regresión | Trivial | Fix aplicado 2 veces sin regressions; reverts fueron intencionales para demo |

**Nivel final:** Trivial → 3 soluciones

### Soluciones evaluadas (3 soluciones, DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, 1 archivo, sin riesgo conocido. Resuelve TC-URGENCIA-01/02/03 en un solo cambio |
| 2 | **Solución #1 + consultar zona antes de dar plazo** (añadir paso de zona en slot-filling inicial) | 🟡 6/10 | Refactor slot-filling Compra | Más preciso con la política real del Sheet (`envio_madrid_ciudad`), pero añade un turno extra y puede impactar otros TCs |
| 3 | **Añadir Example de urgencia con hora textual** (few-shot turno-a-turno en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 sola muestra flakiness en variantes de hora textual |

### Plan de acción (Solución #1)

1. **Editar `definitions/playbooks/compra.yaml`**: insertar el bloque antes de `-- PASO 0 - MODO SEGUN GRUPO --` (~línea 388).

**Bloque a insertar:**

```
⛔ DETECCION URGENCIA TEMPORAL ⛔
Si $intencion_inicial o el input actual del usuario contiene palabras que implican entrega urgente:
- 'hoy', 'ahora', 'ya', 'esta tarde', 'esta noche', 'en X minutos', 'en X horas'
- una hora concreta del mismo dia ('a las 6', 'a las 18:00', 'para las 7', 'antes de las X', 'a las seis de la tarde')
- 'urgente', 'rapido', 'cuanto antes'
ANTES de continuar con slot-filling o busqueda de catalogo, clarifica el plazo segun $modo_tono:
- Estandar: 'Mira, el plazo minimo de entrega es 24h, asi que para hoy no podemos. Te valdria para mañana o un dia despues?'
- Solemne: 'Lamentablemente el plazo minimo de entrega disponible es de 24h. Le valdria para mañana?'
- Corporativo: 'El plazo minimo de entrega es 24h. Para mañana o posterior?'
ESPERA respuesta del usuario.
- Si acepta plazo (mañana o posterior) - continua el flujo normal (PASO 0).
- Si insiste en hoy o rechaza - $razon_handoff='cliente_solicita_humano' - transfiere a Handoff pasando $razon_handoff, $nombre_cliente, $id_cliente, $modo_tono.
⛔ FIN DETECCION URGENCIA ⛔
```

2. **Commit + PR + merge** siguiendo el flujo estándar del repo.
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable en los 3 TCs del patrón URGENCIA.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

---

### Patrones cruzados

**TC-URGENCIA-01, TC-URGENCIA-02 y TC-URGENCIA-03 comparten causa raíz idéntica:** ausencia del bloque `DETECCION URGENCIA TEMPORAL` en `compra.yaml` tras revert `2126c52`. Las tres variantes (hora numérica, hora textual, sin hora explícita) son distintas expresiones del mismo escenario de negocio. El commit `a10ab02` resolvió los 3 simultáneamente. Aplicar Solución #1 sobre cualquiera de los 3 resuelve el patrón completo.

> **Deuda técnica (Capa Datos):** la respuesta "plazo mínimo 24h" es inexacta para `envio_madrid_ciudad` (mismo día antes de 14:00). Registrar como historia en `epic_backlog_conversational_design.md` para la Solución #2 en sprint posterior.
