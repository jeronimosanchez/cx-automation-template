---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## TC-URGENCIA-02 — Entrega urgente, variante hora textual ("hoy a las seis de la tarde")

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"necesito un ramo de rosas para hoy a las seis de la tarde"* | — |
| 2 | Orquestador | Clasifica G5 (compra), extrae `producto="Ramo de Rosas"`, `intencion_inicial` completa con la marca temporal textual, `modo_tono="estandar"` | ⚠️ Slots extraídos correctamente; la urgencia temporal ("seis de la tarde") queda como texto libre en `$intencion_inicial` sin captura explícita |
| 3 | Compra | Entra directo al flujo de slot-filling y consulta catálogo: *"Claro, ramos de rosas tenemos. Mira: Ramo de Rosas Morado — M (37€), Amarillo — M (25€), Blanco — M (25€). ¿Alguna te convence?"* | 🔴 No detecta urgencia antes de continuar. Muestra productos generando falsa expectativa de entrega para las 18:00h del mismo día |
| 4 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado |

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 **1. Capa Comportamiento** [verificada] · `git log --oneline -- definitions/playbooks/compra.yaml` + `grep -n "URGENCIA\|urgencia\|plazo.minimo\|DETECCION" definitions/playbooks/compra.yaml`

Causa principal. Idéntica a TC-URGENCIA-01. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional, preparación demo 21-may). El bloque cubría explícitamente las horas textuales del mismo día: `'esta tarde', 'esta noche'` y `'a las 6', 'a las 18:00', 'para las 7', 'antes de las X'`. La expresión "seis de la tarde" (variante textual de "18:00") queda fuera de cualquier instrucción de detección en el playbook vigente. Sin el bloque, el modelo avanza al PASO 0 mostrando catálogo sin clarificar disponibilidad.

⚪ **2. Capa Routing** · N/A — enrutamiento a Compra correcto (G5, `matchType=PLAYBOOK`, confianza 1.0 según params del JSON). La variante textual de la hora no afecta a la clasificación de intent.

🟢 **3. Capa Parámetros / Slots** [verificada] · JSON del TC (campo `params`, turno 1)

`$intencion_inicial = "necesito un ramo de rosas para hoy a las seis de la tarde"` llega íntegro a Compra, incluyendo la expresión temporal textual. La extracción es correcta. El problema es que las instrucciones del playbook no inspeccionan ese campo para detectar urgencia antes de avanzar.

🟢 **4. Capa Integración** [verificada] · JSON del TC (campo `agent`, turno 1)

El agente muestra precios reales del catálogo (37€, 25€, 25€), confirmando que PetalDataTool respondió correctamente y sin errores. El bug ocurre upstream: el playbook debió clarificar el plazo antes de llamar a inventario.

🟡 **5. Capa Datos** [supuesta] · Valores del Sheet referenciados en el contexto verificado

Sheet disponible (SHEET_OK=true referenciado en análisis del patrón). Auditoría de coherencia:

| Variable | Valor Sheet | Impacto en este TC |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta base para consultas sin zona |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) \| 5.90eur" | Única zona con envío mismo día; corte 14:00 |
| `horario_apertura` | "Lunes-Sabado 9:00-20:00" | — |

**Hallazgo:** "hoy a las seis de la tarde" = 18:00h, claramente posterior al corte de 14:00 de `envio_madrid_ciudad`. En este caso concreto, "no podemos hoy" es la respuesta correcta incluso para Madrid ciudad. La imprecisión del bloque (dice "24h siempre" sin mencionar la excepción Madrid antes de 14:00) es deuda técnica de diseño conversacional, no un error en este TC. No es causa del FAIL.

⚪ **6. Capa Infraestructura** · N/A — versiones `orquestador v65 / compra v39 / checkout v33` en el JSON son las correctas post-revert. El problema está en el contenido del playbook, no en el entorno.

🟢 **7. Capa Modelo / LLM** [verificada] · JSON del TC (respuesta del agente en turno 1)

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de urgencia → muestra catálogo. El modelo interpretó correctamente "seis de la tarde" como marca temporal (el slot `intencion_inicial` lo captura íntegro), pero las instrucciones no le piden actuar sobre ella. La causa está en el prompt, no en la capacidad del modelo.

🔴 **8. Capa Histórico** [verificada] · `git log --oneline -- definitions/playbooks/compra.yaml` (contexto verificado)

Patrón de regresión intencional doble, idéntico al documentado en TC-URGENCIA-01:

| Commit | Acción | Contexto |
|---|---|---|
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL) | Fix mejorado con hora textual explícita |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | Re-aplicado, TC-URGENCIA-01 pasó a PASS en rerun |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El bloque revertido contenía cobertura explícita para horas textuales (`'esta tarde', 'esta noche'`, y variantes de `'a las X'`). El fix es conocido-bueno para la variante textual también.

🟢 **9. Capa Test** [verificada] · JSON del TC (campo `checks`, turno 1)

Regex correctamente calibrado: `[hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]`. La variante textual "seis de la tarde" no afecta al check, que valida la respuesta del agente (no el input del usuario). TC válido y representativo.

**Resumen visual:** 2 🔴 · 3 🟢 · 1 🟡 · 3 ⚪

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

**Por qué**: fix conocido-bueno (probado en `3e0b2d1` y `a10ab02`). El bloque cubre explícitamente la variante textual de hora (`'esta tarde'`, `'esta noche'`, `'a las X'`), por lo que "seis de la tarde" queda cubierta sin cambios adicionales respecto al fix de TC-URGENCIA-01. Cherry-pick o edición directa de 14 líneas en 1 archivo. Sin riesgo de regresión documentado. La inexactitud del "24h siempre" vs. Madrid ciudad antes de 14:00 no aplica a este caso (18:00h > corte 14:00) y es deuda técnica de diseño, no un bloqueante.

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, cubre horas textuales, 1 archivo, sin riesgo conocido |
| 2 | **Solución #1 + consulta de zona antes de dar plazo** (añadir paso de zona en slot-filling inicial) | 🟡 6/10 | Refactor slot-filling Compra | Más preciso con `envio_madrid_ciudad` (mismo día antes de 14:00), pero añade un turno extra y puede impactar otros TCs |
| 3 | **Añadir Example de urgencia con hora textual** (few-shot en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 muestra flakiness en variantes textuales poco frecuentes |

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
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable en TC-URGENCIA-01, TC-URGENCIA-02 y TC-URGENCIA-03.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

> **Forma parte del patrón URGENCIA.** Si el fix de TC-URGENCIA-01 restaura el bloque, TC-URGENCIA-02 y TC-URGENCIA-03 pasarán a PASS sin cambios adicionales. Re-ejecutar antes de planificar fix individual.
