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
| 2 | Orquestador | Clasifica G5 (compra), extrae `producto="ramo de rosas"`, `intencion_inicial` completa con la marca temporal, `modo_tono="estandar"` | ⚠️ Slots extraídos correctamente, pero la urgencia temporal queda como texto libre en `$intencion_inicial` sin captura explícita |
| 3 | Compra | Entra directo al flujo de slot-filling y consulta catálogo: *"Claro, ramos de rosas tenemos: Ramo de Rosas Morado — M (37€), Amarillo — M (25€), Blanco — M (25€). ¿Alguna te convence?"* | 🔴 No detecta urgencia antes de continuar. Muestra productos generando falsa expectativa de entrega misma tarde |
| 4 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado |

---

### Causa raíz — evaluación de las 9 capas del sistema

🔴 **1. Capa Comportamiento** [verificada] · `git diff 2126c52^..2126c52 -- definitions/playbooks/compra.yaml` + `grep URGENCIA|urgencia|plazo.minimo|DETECCION compra.yaml`

Causa principal. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` (14 líneas) fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional, preparación demo 21-may). Sin él, el playbook salta directamente al PASO 0 (mostrar catálogo) sin verificar si la `$intencion_inicial` contiene urgencia temporal. El `grep` actual sobre `compra.yaml` solo encuentra una mención de "hoy" en la línea 484 (como ejemplo de pregunta del usuario, no como instrucción de detección), confirmando la ausencia total del bloque.

⚪ **2. Capa Routing** · N/A — Petal usa arquitectura de Playbooks. El enrutamiento hacia Compra es responsabilidad del Orquestador y funcionó correctamente (grupo G5 detectado, `matchType=PLAYBOOK`, confianza 1.0).

🟢 **3. Capa Parámetros / Slots** [verificada] · `Read /Users/jeronimosanchezmorote/petal-qa/qa_20260521_1706_logs/TC-URGENCIA-01.json`

`$intencion_inicial = "necesito un ramo de rosas para hoy a las 6"` llega íntegro a Compra. El slot pasa correctamente; el problema es que las instrucciones del playbook no lo inspeccionan para detectar urgencia antes de avanzar al slot-filling.

🟢 **4. Capa Integración** [verificada] · `Read TC-URGENCIA-01.json`

El agente muestra precios reales del catálogo (37€, 25€, 25€), lo que confirma que PetalDataTool respondió correctamente. No hay error de tool call. El bug ocurre upstream: el agente debió clarificar el plazo antes de llamar a inventario.

🟡 **5. Capa Datos** [supuesta] · `curl /exec?recurso=business` — Sheet accesible, matiz relevante detectado

Sheet disponible (SHEET_OK=true). Auditoría de coherencia:

| Variable | Valor Sheet | Impacto CX declarado |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta rápida para consultas sin zona |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) \| 5.90eur (gratis >50eur)" | **Única zona con envío mismo día. Corte 14:00** |
| `horario_apertura` | "Lunes-Sabado 9:00-20:00" | — |

**Hallazgo:** el fix revertido (`a10ab02`) afirmaba "el plazo mínimo de entrega es 24h" — impreciso para clientes de Madrid ciudad antes de las 14:00, donde el envío mismo día sí está disponible. Para "hoy a las 6" (18:00h), el corte de 14:00 ya ha pasado, por lo que en este caso concreto la respuesta de 24h es correcta. Aun así, la instrucción debería mencionar esta excepción o preguntar la zona antes de dar el plazo. Marcado 🟡 porque la Capa Datos no es causa del FAIL, pero sí revela que la Solución #1 arrastra una inexactitud de negocio para pedidos antes de las 14:00 desde Madrid ciudad. _(verificada: Sheet accesible y coherente internamente; la imprecisión es de diseño, no inconsistencia entre claves)_

⚪ **6. Capa Infraestructura** · N/A — versiones `orquestador v65 / compra v39` en el JSON son las correctas post-revert. El problema está en el contenido del playbook, no en el entorno desplegado.

🟢 **7. Capa Modelo / LLM** [verificada] · `Read TC-URGENCIA-01.json`

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de urgencia → muestra catálogo. Comportamiento determinista dado el prompt. La causa está en las instrucciones, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · `git log --oneline -n 10 -- definitions/playbooks/compra.yaml`

Patrón de regresión intencional doble:

| Commit | Acción | Contexto |
|---|---|---|
| `3f041df` | Fix (CASO ESPECIAL urgencia/plazo) | PR #83 — fix real |
| `aca187c` | Revert | PR #84 — preparación demo |
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL) | Fix mejorado, pasó en rerun |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | Fix re-aplicado |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El TC lleva 2 ciclos completos fix→revert. Ambos reverts fueron intencionales para demo, no por regressions. El fix es conocido-bueno.

🟢 **9. Capa Test** [verificada] · `Read TC-URGENCIA-01.json`

Regex bien calibrado: `[hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]`. El fix revertido producía "el plazo minimo de entrega es 24h" → matches "plazo" y "24h". El caso "hoy a las 6" es representativo. TC válido.

**Resumen visual:** 2 🔴 problema · 3 🟢 ok · 1 🟡 supuesta · 3 ⚪ N/A

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), restaurar 14 líneas ya escritas |
| Profundidad | Trivial | Restaurar instrucción condicional existente, sin nueva lógica |
| Riesgo de regresión | Trivial | Fix aplicado 2 veces sin regressions; reverts fueron intencionales para demo |

**Nivel final:** Trivial → 3 soluciones

### Solución recomendada: #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: fix conocido-bueno (probado en `3e0b2d1` y `a10ab02`, TC pasó a PASS en primer rerun en ambas ocasiones). Cherry-pick o edición directa de 14 líneas en 1 archivo. Sin riesgo de regresión documentado. La inexactitud del "24h siempre" vs. Madrid ciudad antes de 14:00 (detectada en Capa Datos) es deuda técnica de diseño conversacional para un sprint posterior, no un bloqueante.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, 1 archivo, sin riesgo conocido. Único gap: no menciona excepción Madrid mismo día |
| 2 | **Solución #1 + consulta de zona antes de dar plazo** (añadir paso de zona en slot-filling inicial) | 🟡 6/10 | Refactor slot-filling Compra | Más preciso con la política real del Sheet (`envio_madrid_ciudad`), pero añade un turno extra y puede impactar otros TCs |
| 3 | **Añadir Example de urgencia** (few-shot turno-a-turno en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 sola muestra flakiness en variantes |

### Plan de acción (Solución #1)

1. **Editar `definitions/playbooks/compra.yaml`**: insertar el bloque antes de `-- PASO 0 - MODO SEGUN GRUPO --` (~línea 388):

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
      - Si insiste en hoy o rechaza - $razon_handoff='cliente_solicita_humano' - transfiere a Handoff pasando $razon_handoff, $nombre_cliente, $id_cliente, $modo_tono. (Un humano puede gestionar excepciones de logistica).
      ⛔ FIN DETECCION URGENCIA ⛔
```

2. **Commit + PR + merge** con `--admin --squash`.
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

> **Deuda técnica (Capa Datos):** la respuesta "plazo mínimo 24h" es inexacta para `envio_madrid_ciudad` (mismo día antes de 14:00). Registrar como historia en `epic_backlog_conversational_design.md` para la Solución #2 en sprint posterior.
