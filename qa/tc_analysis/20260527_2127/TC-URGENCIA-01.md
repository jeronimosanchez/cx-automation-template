---
status: FAIL
tipo: Bug Playbook
estimacion: ~25 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas para hoy a las 18:00"* | — |
| 2 | Orquestador | Clasifica G5 (compra), deriva a Compra | ✅ Correcto |
| 3 | Compra | Llama PetalDataTool inventario y muestra 3 ramos de rosas | 🔴 Ignora restricción temporal "hoy a las 18:00" |
| 4 | Compra | Cierra con APERTURA estándar | 🔴 No menciona política mismo-día ni corte 14:00 |

### Causa raíz — evaluación de las 9 capas del sistema

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + petal_cx_orchestrator.yaml`

El playbook Compra no tiene sub-flujo de gestión de urgencia/plazo. La única mención de "hoy" en `compra.yaml` está en la línea 484 como ejemplo de pregunta del user ("se entrega hoy"), no como trigger del agente para gestionar la restricción temporal. En el Orquestador, la regla ZG-5 (`petal_cx_orchestrator.yaml` línea 254: "Pregunta plazo entrega - G1(business)") solo deriva a G1 cuando el user PREGUNTA explícitamente por el plazo, no cuando lo MENCIONA implícitamente dentro de una intención de compra (G5). Resultado: la frase "para hoy a las 18:00" se trata como ruido, el agente responde catálogo y nunca evalúa viabilidad temporal.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks, no Flows.

🟡 3. **Capa Parámetros/Slots** [supuesta] · _(no verificado: no se inspeccionaron exhaustivamente todos los slots de Compra)_

No existe slot `$fecha_entrega` / `$hora_entrega` capturado en `compra.yaml`; la información temporal que aporta el user en T1 se pierde inmediatamente tras el primer turno y no se propaga hacia Checkout. Aunque no es la causa principal (lo es Capa 1), la ausencia de slots temporales impide que cualquier fix futuro de viabilidad funcione end-to-end.

🟢 4. **Capa Integración** [verificada] · `JSON del log`

PetalDataTool responde correctamente con el catálogo de ramos de rosas (3 ítems con precio y nº de flores). No hay fallo de tool call ni de contrato de respuesta.

🟢 5. **Capa Datos** [verificada] · `curl GET /exec?recurso=business`

El Sheet `business` contiene los datos necesarios para resolver el TC: `horario_corte_mismo_dia=14:00` ("Hora limite para pedidos con entrega mismo dia (solo Madrid ciudad)"), `envio_madrid_ciudad=Mismo dia (pedidos antes 14:00) | 5.90eur (gratis >50eur)` y `tiempo_entrega_estimado=24h en Madrid y Barcelona, resto de ciudades 48 horas`. Los datos están completos y accesibles; el playbook simplemente no los consulta para este caso.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde, versión activa correcta.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 ejecuciones)_

Con un solo run no se puede afirmar reproducibilidad estable ni descartar variabilidad LLM. Aplica la regla binaria: 🔴 solo si todas las demás capas están 🟢 + N≥2 reproducciones. Aquí Capa 1 ES la causa estructural identificada → esta queda 🟡 por precaución metodológica.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

HISTORIAL DE REGRESIÓN DELIBERADA. Tres fixes aplicados y revertidos sobre exactamente este TC: `3f041df` (fix CASO ESPECIAL urgencia/plazo) → revertido por `aca187c`; `a10ab02` (bloque DETECCION URGENCIA TEMPORAL) → revertido por `2126c52`; `3e0b2d1` (mismo fix) → revertido por `1f95cae`. El fix existe históricamente, ha sido validado en QA y eliminado de main intencionalmente. Patrón típico de "break-for-demo": el bug está disponible para reproducir en presentaciones.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

El regex `[hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano]` está bien calibrado: cubre múltiples formas razonables de abordar la urgencia (negación explícita, mención de plazo, derivación a humano, simulación de entrega). Sin falsos negativos detectables.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL en compra.yaml

🟢 **9/10** · ~25 min · Sin dependencias externas

**Por qué**: el fix YA existe en el historial (commit `a10ab02`). Cherry-pick + ajustes menores → cierra el TC. Cero diseño nuevo, cero riesgo de regresión sobre flujos existentes.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Medio | 1 archivo (compra.yaml), bloque nuevo de ~10 líneas |
| Profundidad | Medio | Añade sub-flujo de detección + respuesta determinística desde Sheet |
| Riesgo de regresión | Trivial | No toca flujos existentes; el fix histórico ya fue validado |

**Nivel final:** Medio → 5 soluciones

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Cherry-pick commit a10ab02** (bloque DETECCION URGENCIA TEMPORAL) | 🟢 9/10 | — | Fix histórico validado, cero diseño nuevo |
| 2 | **Solución #1 + capturar $fecha_entrega / $hora_entrega como slots y propagar a Checkout** | 🟢 8/10 | — | Más completo, prepara terreno para validaciones futuras de viabilidad |
| 3 | **Mover gestión de urgencia al Orquestador (ZG-5 expandida)** | 🟡 6/10 | — | Más arquitectónico, pero acopla validación de negocio al Orquestador |
| 4 | **Crear tool validar_plazo_entrega en backend** | 🟡 6/10 | Extender petal-sheet-api | Determinístico al 100%, pero requiere tocar backend |
| 5 | **Sub-playbook Plazo_Task** | 🔴 4/10 | — | Sobre-ingeniería para algo que cabe en 10 líneas |

### Plan de acción (Solución #1)

1. **Cherry-pick**: `git cherry-pick a10ab02` (o restaurar manualmente el bloque desde ese commit)
2. **Verificar**: el bloque DETECCION URGENCIA TEMPORAL aparece tras el GOAL en compra.yaml, antes del FLUJO PRINCIPAL
3. **Push y deploy**: rama feature, esperar workflow Deploy to Petal CX (~3min)
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-URGENCIA-01

**Coste total**: ~5 min cherry-pick + 3 min deploy + 3 min QA = ~11 min reales.
