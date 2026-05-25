---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## TC-URGENCIA-01 — Entrega urgente, variante hora numérica ("hoy a las 6")

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las 6"* | — |
| 2 | Orquestador | Clasifica G5 (compra), extrae `producto="rosas"`, `intencion_inicial` completa con la marca temporal, `modo_tono="estandar"` | ⚠️ Slots extraídos correctamente, pero la urgencia temporal queda como texto libre en `$intencion_inicial` sin captura explícita |
| 3 | Compra | Entra directo al flujo de slot-filling y consulta catálogo: *"Claro, ramos de rosas tenemos: Ramo de Rosas Morado — M (37€), Amarillo — M (25€), Blanco — M (25€). ¿Cuál te gusta más o miramo..."* | 🔴 No detecta urgencia antes de continuar. Muestra productos generando falsa expectativa de entrega esa misma tarde |
| 4 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado |

**Estabilidad:** 0/3 runs pasan. Los 3 runs presentan síntoma idéntico. No hay flakiness.

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 **1. Capa Comportamiento** [verificada] · Fuente: `git log -- definitions/playbooks/compra.yaml` + `grep "URGENCIA\|urgente\|urgencia\|DETECCION" compra.yaml`

Causa principal. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional para demo 21-may). Sin él, el playbook salta directamente al PASO 0 (mostrar catálogo) sin verificar si `$intencion_inicial` contiene urgencia temporal. El `grep` actual sobre `compra.yaml` solo encuentra una mención de "hoy" en un ejemplo de usuario (línea ~484), confirmando la ausencia total del bloque de detección.

⚪ **2. Capa Routing** · N/A — Petal usa arquitectura de Playbooks. El enrutamiento hacia Compra es responsabilidad del Orquestador y funcionó correctamente (`grupo_intent="G5"` detectado, confianza implícita por llegada a Compra).

🟢 **3. Capa Parámetros / Slots** [verificada] · Fuente: campo `params` del JSON del run (`intencion_inicial: "necesito un ramo de rosas para hoy a las 6"`)

`$intencion_inicial` llega íntegro a Compra con la marca temporal incluida. El slot se transfiere correctamente; el problema es que las instrucciones del playbook no lo inspeccionan para detectar urgencia temporal antes de avanzar al slot-filling del catálogo.

🟢 **4. Capa Integración** [verificada] · Fuente: campo `agent` del JSON del run (turno 1)

El agente muestra precios reales del catálogo (37€, 25€, 25€), confirmando que PetalDataTool respondió correctamente. No hay error de tool call. El bug ocurre upstream: el playbook debió clarificar el plazo antes de invocar inventario.

🟡 **5. Capa Datos** [supuesta] · Fuente: Sheet (`recurso=business`) — Sheet accesible; matiz relevante detectado

| Variable | Valor Sheet | Impacto en CX |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta genérica para consultas sin zona declarada |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) · 5.90€ (gratis >50€)" | Única zona con envío same-day. Corte: 14:00 |
| `horario_corte_mismo_dia` | "14:00" | — |

**Hallazgo:** el bloque revertido afirmaba "el plazo mínimo de entrega es 24h" — impreciso para Madrid ciudad antes de las 14:00, donde el envío mismo día sí está disponible. Para "hoy a las 6" (18:00h), el corte de 14:00 ya ha pasado, por lo que en este caso concreto la respuesta de 24h es correcta. Marcado 🟡 porque la Capa Datos no es causa del FAIL, pero revela que la Solución #1 arrastra una inexactitud de negocio para pedidos desde Madrid ciudad antes de las 14:00.

⚪ **6. Capa Infraestructura** · N/A — versiones `orquestador v65 / compra v39 / checkout v33` en el JSON corresponden al estado post-revert (`2126c52`). El problema está en el contenido del playbook, no en el entorno desplegado.

🟢 **7. Capa Modelo / LLM** [verificada] · Fuente: campo `agent` del JSON del run (turno 1)

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de detección de urgencia → muestra catálogo. Comportamiento determinista dado el prompt. La causa está en las instrucciones, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · Fuente: `git log --oneline -- definitions/playbooks/compra.yaml`

Patrón de regresión intencional doble:

| Commit | Acción | Contexto |
|---|---|---|
| `3f041df` | Fix (CASO ESPECIAL urgencia/plazo, PR #83) | Fix real, TC pasó a PASS |
| `aca187c` | Revert (PR #84) | Preparación demo |
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | Fix mejorado |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | TC pasó a PASS en rerun |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El TC lleva 2 ciclos completos fix → revert. Ambos reverts fueron intencionales para demo, no por regressions. El fix es conocido-bueno.

🟢 **9. Capa Test** [verificada] · Fuente: campo `checks` del JSON del run

Regex bien calibrado: `hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano`. El bloque revertido producía respuestas con "el plazo minimo de entrega es 24h" → matches "plazo" y "24h". El caso "hoy a las 6" es representativo de toda la familia URGENCIA. TC válido, no hay falso positivo.

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

### Solución recomendada: #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: fix conocido-bueno (probado en `3e0b2d1` y `a10ab02`, TC pasó a PASS en primer rerun en ambas ocasiones). Cherry-pick o edición directa de 14 líneas en 1 archivo. Sin riesgo de regresión documentado. La inexactitud del "24h siempre" vs. Madrid ciudad antes de 14:00 (detectada en Capa Datos) es deuda técnica de diseño conversacional para un sprint posterior, no un bloqueante.

**Bloque a insertar** antes de `-- PASO 0 - MODO SEGUN GRUPO --` (~línea 388 de `compra.yaml`):

```
⛔ DETECCION URGENCIA TEMPORAL ⛔
Si $intencion_inicial o el input actual del usuario contiene palabras que implican entrega urgente:
- 'hoy', 'ahora', 'ya', 'esta tarde', 'esta noche', 'en X minutos', 'en X horas'
- una hora concreta del mismo dia ('a las 6', 'a las 18:00', 'para las 7', 'antes de las X')
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

### Soluciones evaluadas (3 soluciones, DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, 1 archivo, sin riesgo conocido. Único gap: no menciona excepción Madrid mismo día |
| 2 | **Solución #1 + consultar zona antes de dar plazo** (añadir paso de zona en slot-filling inicial) | 🟡 6/10 | Refactor slot-filling Compra | Más preciso con la política real del Sheet (`envio_madrid_ciudad`), pero añade un turno extra y puede impactar otros TCs |
| 3 | **Añadir Example de urgencia** (few-shot turno-a-turno en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 sola muestra flakiness en variantes |

### Plan de acción (Solución #1)

1. **Editar `definitions/playbooks/compra.yaml`**: insertar el bloque antes de `-- PASO 0 - MODO SEGUN GRUPO --` (~línea 388).
2. **Commit + PR + merge** siguiendo el flujo estándar del repo.
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable en los 3 TCs del patrón URGENCIA.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

> **TC raíz del patrón URGENCIA.** El mismo fix resuelve TC-URGENCIA-02 y TC-URGENCIA-03. Re-ejecutar los 3 tras aplicar.

> **Deuda técnica (Capa Datos):** la respuesta "plazo mínimo 24h" es inexacta para `envio_madrid_ciudad` (mismo día antes de 14:00). Registrar como historia en `epic_backlog_conversational_design.md` para la Solución #2 en sprint posterior.
