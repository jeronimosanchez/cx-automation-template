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
| 2 | Orquestador | Clasifica G5 (compra), extrae `producto="ramo de rosas"`, `intencion_inicial` completa con la marca temporal, `modo_tono="estandar"` | ⚠️ Slots extraídos correctamente, pero la urgencia temporal queda como texto libre en `$intencion_inicial` sin captura explícita |
| 3 | Compra | Entra directo al flujo de slot-filling y consulta catálogo sin verificar la urgencia implícita en "esta tarde" | 🔴 No detecta urgencia antes de continuar. Muestra catálogo generando falsa expectativa de entrega esa misma tarde |
| 4 | Test (check) | Regex: `hoy.{0,40}no\|plazo\|24h\|24 horas\|tarde.{0,30}no\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` | 🔴 FAIL — respuesta no contiene ningún token de plazo, política ni escalado |

---

### Causa raíz — evaluación de las 9 capas del sistema [v1.1 Capas rediseñadas]

🔴 **1. Capa Comportamiento** [verificada] · Fuente: `git diff 2126c52^..2126c52 -- definitions/playbooks/compra.yaml` + `grep URGENCIA compra.yaml`

Causa principal. El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` (14 líneas) fue eliminado de `compra.yaml` en el commit `2126c52` (revert intencional, preparación demo 21-may). Sin él, el playbook salta directamente al PASO 0 (mostrar catálogo) sin verificar si `$intencion_inicial` contiene urgencia temporal. El trigger "esta tarde" está explícitamente incluido en la lista de señales de urgencia del bloque eliminado. El `grep` actual sobre `compra.yaml` confirma la ausencia total del bloque de detección.

⚪ **2. Capa Routing** · N/A — Petal usa arquitectura de Playbooks. El enrutamiento hacia Compra es responsabilidad del Orquestador y funcionó correctamente (grupo G5 detectado, `matchType=PLAYBOOK`, confianza 1.0).

🟢 **3. Capa Parámetros / Slots** [verificada] · Fuente: campo `params` del TC (turno 1)

`$intencion_inicial = "necesito un ramo de rosas para esta tarde"` llega íntegro a Compra. El slot se transfiere correctamente; el problema es que las instrucciones del playbook no lo inspeccionan para detectar urgencia temporal antes de avanzar al slot-filling del catálogo.

🟢 **4. Capa Integración** [verificada] · Fuente: campo `agent` del TC (turno 1)

El agente muestra contenido real del catálogo, confirmando que PetalDataTool respondió correctamente. No hay error de tool call. El bug ocurre upstream: el playbook debió clarificar el plazo antes de invocar inventario.

🟡 **5. Capa Datos** [supuesta] · Fuente: `curl /exec?recurso=business` — Sheet accesible; ambigüedad semántica detectada

Sheet disponible (SHEET_OK=true). Auditoría de coherencia:

| Variable | Valor Sheet | Impacto en CX |
|---|---|---|
| `tiempo_entrega_estimado` | "24h en Madrid y Barcelona, resto de ciudades 48 horas" | Respuesta genérica para consultas sin zona declarada |
| `envio_madrid_ciudad` | "Mismo dia (pedidos antes 14:00) · 5.90€ (gratis >50€)" | **Única zona con envío same-day. Corte: 14:00** |
| `horario_corte_mismo_dia` | "14:00" | Corte explícito para pedidos same-day |
| `horario_apertura` | "Lunes-Sábado 9:00-20:00" | — |

**Hallazgo — ambigüedad específica de esta variante:** a diferencia de "hoy a las 6" (hora concreta que permite saber si el corte de 14:00 ya pasó), "esta tarde" es semánticamente ambiguo respecto al corte de las 14:00. Si el cliente escribe a las 11:00 y está en Madrid ciudad, "esta tarde" puede ser antes de las 14:00, lo que haría viable el envío mismo día según `envio_madrid_ciudad`. El bloque restaurado responde "24h siempre" — correcto para la mayoría de casos pero puede ser incorrecto para Madrid ciudad antes de 14:00. Marcado 🟡 porque la Capa Datos no es causa del FAIL, pero revela que la Solución #1 arrastra una inexactitud de negocio más pronunciada que en URGENCIA-01 (donde la hora concreta permitía desambiguar). Documentado como deuda técnica.

⚪ **6. Capa Infraestructura** · N/A — las versiones desplegadas corresponden al estado post-revert. El problema está en el contenido del playbook, no en el entorno desplegado.

🟢 **7. Capa Modelo / LLM** [verificada] · Fuente: campo `agent`, turno 1

El modelo sigue las instrucciones de `compra.yaml` con fidelidad: sin instrucción de detección de urgencia → muestra catálogo. Comportamiento determinista dado el prompt. La causa está en las instrucciones, no en el modelo.

🔴 **8. Capa Histórico** [verificada] · Fuente: `git log --oneline -n 10 -- definitions/playbooks/compra.yaml`

Patrón de regresión intencional doble (idéntico a URGENCIA-01/02):

| Commit | Acción | Contexto |
|---|---|---|
| `3e0b2d1` | Fix (DETECCION URGENCIA TEMPORAL) | Fix inicial, TC pasó a PASS en rerun |
| `1f95cae` | Revert | — |
| `a10ab02` | Fix (DETECCION URGENCIA TEMPORAL, re-aplicado) | Fix re-aplicado, TC pasó a PASS |
| `2126c52` | **Revert (estado actual)** | Preparación demo 21-may |

El TC lleva 2 ciclos completos fix → revert. Ambos reverts fueron intencionales para demo, no por regressions. El fix es conocido-bueno.

🟢 **9. Capa Test** [verificada] · Fuente: campo `checks` del TC

Regex bien calibrado: `[hoy.{0,40}no|plazo|24h|24 horas|tarde.{0,30}no|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]`. Esta variante añade `tarde.{0,30}no` respecto al regex de URGENCIA-01, cubriendo específicamente respuestas del tipo "para esta tarde no podemos" o "esta tarde no es posible". El bloque revertido producía respuestas con "el plazo minimo de entrega es 24h" → matches "plazo" y "24h". El patrón `tarde.{0,30}no` es un bonus de precisión para esta variante. TC válido.

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

**Por qué**: fix conocido-bueno (probado en `3e0b2d1` y `a10ab02`, TC pasó a PASS en primer rerun en ambas ocasiones). Cherry-pick o edición directa de 14 líneas en 1 archivo. Sin riesgo de regresión documentado. La inexactitud del "24h siempre" vs. Madrid ciudad antes de 14:00 (más relevante en esta variante por la ambigüedad de "esta tarde") es deuda técnica de diseño conversacional para un sprint posterior, no un bloqueante.

### Soluciones evaluadas (3 soluciones, DESC por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Restaurar bloque DETECCION URGENCIA TEMPORAL** en `compra.yaml` (cherry-pick `a10ab02` o edición manual) | 🟢 9/10 | — | Fix probado 2 veces, 1 archivo, sin riesgo conocido. Único gap: no desambigua "esta tarde" vs. corte 14:00 Madrid ciudad |
| 2 | **Solución #1 + preguntar zona antes de dar plazo** (añadir paso de zona en slot-filling inicial) | 🟡 6/10 | Refactor slot-filling Compra | Más preciso con la política real del Sheet (`envio_madrid_ciudad`) y especialmente relevante para la ambigüedad de "esta tarde", pero añade un turno extra y puede impactar otros TCs |
| 3 | **Añadir Example de urgencia variante "esta tarde"** (few-shot turno-a-turno en `definitions/examples/`) | 🟡 5/10 | — | Complementario a #1, no elimina el gap de instrucciones. Útil como refuerzo si #1 sola muestra flakiness en esta variante semántica |

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
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable en los 3 TCs del patrón.

**Coste total**: ~15 min (2 min edición + 3 min deploy + 10 min rerun × 3).

> **Forma parte del patrón URGENCIA.** El fix de TC-URGENCIA-01 resuelve este TC. Re-ejecutar los 3 TCs del patrón tras aplicar.

> **Deuda técnica (Capa Datos):** la respuesta "plazo mínimo 24h siempre" es inexacta para `envio_madrid_ciudad` (mismo día antes de 14:00). La ambigüedad de "esta tarde" hace este gap más pronunciado que en URGENCIA-01 (hora concreta) o URGENCIA-02 (expresión nocturna fuera de horario). Registrar como historia en `epic_backlog_conversational_design.md` para la Solución #2 en sprint posterior.
