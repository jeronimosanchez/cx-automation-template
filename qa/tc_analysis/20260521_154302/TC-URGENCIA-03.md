---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## TC-URGENCIA-03 — Entrega urgente — variante sin hora ("esta tarde")

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para esta tarde"* | — |
| 2 | Orquestador | Clasifica G5 (compra), extrae `producto="rosas"`, `intencion_inicial` completa con la marca temporal, `modo_tono="estandar"` | ⚠️ Slots extraídos correctamente. "Esta tarde" queda como texto libre en `$intencion_inicial` sin captura explícita de urgencia. A diferencia de URGENCIA-01 ("hoy a las 6"), no hay hora numérica que ancle el momento del pedido |
| 3 | Compra | Entra directo al flujo de slot-filling y consulta catálogo: *"Claro, ramos de rosas tenemos: Ramo de Rosas Morado — M (37€), Amarillo — M (25€), Blanco — M (25€). ¿Alguno te convence?"* | 🔴 No detecta urgencia temporal antes de continuar. Muestra productos generando falsa expectativa de entrega en la misma tarde, sin verificar si el corte de 14:00 aplica |
| 4 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|tarde.{0,30}no\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado. El patrón `tarde.{0,30}no` (ausente en URGENCIA-01/02) es adicional para cubrir respuestas del tipo "para esta tarde no podemos" |

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 **1. Capa Comportamiento** [verificada] · `git diff 2126c52^..2126c52 -- definitions/playbooks/compra.yaml` + `grep URGENCIA|urgencia|plazo.minimo|DETECCION compra.yaml`

Causa principal. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional, preparación demo 21-may). Sin él, el playbook salta directamente al PASO 0 (mostrar catálogo) sin inspeccionar `$intencion_inicial`. El bloque listaba explícitamente `'esta tarde'` como trigger de urgencia. Su ausencia es suficiente y necesaria para explicar el FAIL.

⚪ **2. Capa Routing** · N/A — El enrutamiento hacia Compra es correcto (G5 detectado, `matchType=PLAYBOOK`, confianza 1.0). El Orquestador no es parte del problema.

🟢 **3. Capa Parámetros / Slots** [verificada] · Logs del run (JSON del TC)

`$intencion_inicial = "necesito un ramo de rosas para esta tarde"` llega íntegro a Compra. El slot se pasa correctamente; el problema es que las instrucciones del playbook no inspeccionan ese valor para detectar urgencia antes de avanzar al slot-filling.

🟢 **4. Capa Integración** [verificada] · Logs del run (JSON del TC)

El agente muestra precios reales del catálogo (37€, 25€, 25€), confirmando que PetalDataTool respondió correctamente. No hay error de tool call. El bug ocurre upstream: el agente debió aclarar el plazo antes de consultar inventario.

🟡 **5. Capa Datos** [supuesta] · `curl /exec?recurso=business` — Sheet accesible, matiz de ambigüedad elevado vs URGENCIA-01/02

Sheet disponible. Auditoría de coherencia:

| Variable | Valor Sheet | Impacto en este TC |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta de fallback si no se conoce la zona |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) \| 5.90eur (gratis >50eur)" | **Único caso donde "esta tarde" podría ser viable** |
| `horario_apertura` | "Lunes-Sabado 9:00-20:00" | Ventana dentro de la cual "esta tarde" es ambigua |

**Hallazgo (matiz adicional vs URGENCIA-01/02):** "Esta tarde" sin hora específica es semánticamente ambigua respecto al corte de 14:00. Si el pedido se realiza a las 11:00 desde Madrid ciudad, "esta tarde" podría ser atendible (mismo día antes de 14:00). Si se realiza a las 16:00, el corte ya ha pasado. El bloque revertido respondería "para hoy no podemos" en todos los casos, lo que es técnicamente incorrecto para el primer escenario. Esto es deuda técnica de diseño conversacional: la Solución #1 restaura el fix conocido-bueno pero arrastra esta inexactitud. La Solución #2 la resuelve. Marcado 🟡 porque la Capa Datos no es causa del FAIL; sí eleva la complejidad del fix óptimo por encima de URGENCIA-01/02.

⚪ **6. Capa Infraestructura** · N/A — versiones `orquestador v65 / compra v39` son las correctas post-revert. El problema está en el contenido del playbook, no en el entorno desplegado.

🟢 **7. Capa Modelo / LLM** [verificada] · Logs del run (JSON del TC)

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de urgencia → muestra catálogo. Comportamiento determinista dado el prompt. La causa está en las instrucciones, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · `git log --oneline -- definitions/playbooks/compra.yaml`

Patrón de regresión intencional doble (mismo que URGENCIA-01/02):

| Commit | Acción | Contexto |
|---|---|---|
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL) | Fix aplicado, TC pasó a PASS |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | Fix re-aplicado, TC pasó a PASS |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El fix es conocido-bueno: aplicado 2 veces, TC PASS en ambas ocasiones, revertido 2 veces de forma intencional para demo.

🟢 **9. Capa Test** [verificada] · Regex del JSON del TC

Regex bien calibrado: `[hoy.{0,40}no|plazo|24h|24 horas|tarde.{0,30}no|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]`. El patrón `tarde.{0,30}no` (no presente en URGENCIA-01/02) anticipa que el agente podría responder "para esta tarde no podemos" — variante más natural para esta expresión. El resto de patrones cubren la respuesta genérica de plazo. TC válido y representativo de la variante más ambigua del grupo URGENCIA.

**Resumen visual:** 2 🔴 · 3 🟢 · 1 🟡 · 3 ⚪

---

## Recomendación

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (`compra.yaml`), restaurar bloque ya escrito |
| Profundidad | Trivial | Restaurar instrucción condicional existente, sin nueva lógica |
| Riesgo de regresión | Trivial | Fix aplicado 2 veces sin regressions; reverts fueron intencionales para demo |

**Nivel final:** Trivial → 3 soluciones

### Solución recomendada: #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: fix conocido-bueno (probado en `3e0b2d1` y `a10ab02`, TC pasó a PASS en primer rerun en ambas ocasiones). Edición de 14 líneas en 1 archivo. Sin riesgo de regresión documentado. La ambigüedad de "esta tarde" vs. el corte de 14:00 de Madrid ciudad es deuda técnica de diseño conversacional, no un bloqueante para este fix. La respuesta de plazo genérica ("para hoy no podemos") es conservadora-segura: puede sobreestimar el corte en un escenario de madrugada, pero nunca crea una falsa expectativa de entrega imposible.

### Soluciones evaluadas (ordenadas DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, 1 archivo, sin riesgo conocido. Gap: no menciona excepción Madrid mismo día ni pide hora cuando "esta tarde" es ambigua |
| 2 | **Solución #1 + preguntar hora cuando la expresión es ambigua** (añadir rama condicional: si urgencia detectada sin hora explícita → preguntar "¿a partir de qué hora lo necesitas?") | 🟡 7/10 | Modificación mayor del bloque de urgencia | Elimina la ambigüedad de "esta tarde" y permite aplicar correctamente la excepción de Madrid. Añade un turno extra; puede introducir complejidad en el flujo. Recomendable en sprint posterior |
| 3 | **Añadir Example de urgencia con variante "esta tarde"** (few-shot en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 sola muestra flakiness en variantes sin hora numérica |

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
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable en TC-URGENCIA-01, TC-URGENCIA-02 y TC-URGENCIA-03 simultáneamente.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

> **Deuda técnica (Capa Datos):** "esta tarde" sin hora explícita es ambigua respecto al corte de 14:00 de `envio_madrid_ciudad`. La respuesta de "plazo mínimo 24h" es conservadora-segura pero puede ser incorrecta para clientes de Madrid ciudad que pidan antes de las 14:00. Registrar como historia en `epic_backlog_conversational_design.md` para la Solución #2 en sprint posterior.

> **Forma parte del patrón URGENCIA.** Si el fix de TC-URGENCIA-01 restaura el bloque, TC-URGENCIA-02 y TC-URGENCIA-03 pasarán a PASS sin cambios adicionales. Re-ejecutar los tres antes de planificar fix individual.
