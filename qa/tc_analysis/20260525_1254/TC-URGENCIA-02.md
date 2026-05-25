---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada — mismo fix que TC-URGENCIA-01)
---

# TC-URGENCIA-02 — Entrega urgente: variante hora textual ("hoy a las seis de la tarde")

**Run:** 20260525_1254 | **Resultado:** FAIL (0/3 en los 3 runs)

---

## T1

**Usuario:** "necesito un ramo de rosas para hoy a las seis de la tarde"
**Agente:** muestra catálogo de rosas directamente, sin detectar urgencia ni clarificar plazo de entrega.

### Turnos vs Problemas detectados

| Turno | Actor | Contenido | Problema |
|-------|-------|-----------|----------|
| T1 | Usuario | "necesito un ramo de rosas para hoy a las seis de la tarde" | — |
| T1 | Agente | Muestra catálogo de rosas | No detecta la señal temporal "hoy a las seis de la tarde". Pasa directamente a slot-filling/catálogo sin verificar viabilidad de entrega. |

**Check T1:** FAIL — regex `hoy.{0,40}no|plazo|24h|24 horas|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano` no encontrado en respuesta del agente.

---

### Causa raíz — evaluación de las 9 capas [v1.1]

| Capa | Estado | Evaluación |
|------|--------|------------|
| 1. Comportamiento del Playbook | 🔴 Verificada | El bloque `⛔ DETECCION URGENCIA TEMPORAL ⛔` está ausente en `compra.yaml`. Fue eliminado mediante el revert `2126c52`. Fuente: `git log -- definitions/playbooks/compra.yaml` |
| 2. Routing / Intent | ⚪ N/A | El TC no involucra problemas de enrutamiento. El agente llega al playbook de Compra correctamente. |
| 3. Parámetros / Slots | 🟢 Verificada | `intencion_inicial` = "necesito un ramo de rosas para hoy a las seis de la tarde" — capturado completo con la señal temporal incluida. El problema no es de captura de parámetros. Fuente: `params` del JSON del run. |
| 4. Integración / Herramientas | 🟢 Verificada | El agente muestra catálogo real (integración con Sheet funciona). El fallo ocurre upstream, antes de llegar a la búsqueda de catálogo. |
| 5. Datos / Sheet | 🟡 Supuesta | Sheet: `tiempo_entrega_estimado = "24h en Madrid y Barcelona"`, `horario_corte_mismo_dia = "14:00"`. El Sheet es técnicamente correcto: "a las seis de la tarde" = 18:00h > corte de 14:00h, por lo que 24h es la respuesta correcta para este caso. El dato "24h siempre" podría ser inexacto para Madrid antes de las 14:00 (donde aplica "mismo día"), pero no afecta a este TC concreto. |
| 6. Infraestructura | ⚪ N/A | No hay evidencia de problemas de infra. CI/CD funcional, versiones activas correctas (orquestador v65 / compra v39). |
| 7. Comportamiento del LLM | 🟢 Verificada | El LLM sigue fielmente las instrucciones del playbook. Sin el bloque de detección de urgencia, actúa conforme a lo que está escrito: avanza a catálogo. No hay alucinación ni comportamiento inesperado. |
| 8. Histórico / Patrón | 🔴 Verificada | Mismo patrón que TC-URGENCIA-01: el bloque fue añadido (`3e0b2d1`), revertido (`1f95cae`), re-añadido (`a10ab02`) y vuelto a revertir (`2126c52`) dos veces de forma intencionada para demos. Estado actual: bloque eliminado. Fuente: `git log -- definitions/playbooks/compra.yaml`. |
| 9. Test / Cobertura | 🟢 Verificada | El regex del check T1 está bien calibrado: `hoy.{0,40}no\|plazo\|24h\|24 horas\|entrega.{0,30}simulad\|entrega.{0,30}disponible\|equipo\|humano` cubre la variante textual de hora ("seis de la tarde") porque el agente debería mencionar el plazo de 24h o la inviabilidad, no la hora exacta. El test detecta correctamente el FAIL. |

**Resumen visual:**

```
Capa 1 🔴  Capa 2 ⚪  Capa 3 🟢  Capa 4 🟢  Capa 5 🟡
Capa 6 ⚪  Capa 7 🟢  Capa 8 🔴  Capa 9 🟢
```

Causa raíz única: **ausencia del bloque `DETECCION URGENCIA TEMPORAL` en `compra.yaml`** (capa 1), documentada en el histórico de commits (capa 8). El estado actual es fruto de un revert intencional para demo.

---

## Recomendación

### Dimensionamiento del bug

| Eje | Valoración | Justificación |
|-----|-----------|---------------|
| Alcance | Trivial | Afecta únicamente al playbook `compra.yaml`. Sin impacto en otros recursos, flujos o playbooks. |
| Profundidad | Trivial | Fix conocido y ya probado: restaurar bloque existente. Sin cambios de arquitectura ni de integración. |
| Riesgo | Trivial | El bloque fue validado en producción en `a10ab02` y `3e0b2d1`. Anti-regresión cubierta por la suite existente (TC-URGENCIA-01 y TC-URGENCIA-02). |

### Solución recomendada: #1

**Restaurar el bloque `DETECCION URGENCIA TEMPORAL` en `compra.yaml`.**

El bloque ya existe en el historial de git (`a10ab02`) y ha sido probado en producción. El fix consiste en añadirlo de nuevo al FLUJO PRINCIPAL del playbook, antes de los pasos de slot-filling y búsqueda de catálogo:

```
⛔ DETECCION URGENCIA TEMPORAL ⛔
Si $intencion_inicial o el input actual del usuario contiene palabras que implican entrega urgente:
- 'hoy', 'ahora', 'ya', 'esta tarde', 'esta noche', 'en X minutos', 'en X horas'
- una hora concreta del mismo dia ('a las 6', 'a las 18:00', 'para las 7', 'antes de las X')
- 'urgente', 'rapido', 'cuanto antes'
ANTES de continuar con slot-filling o busqueda de catalogo, clarifica el plazo segun $modo_tono:
- Estandar: 'Mira, el plazo minimo de entrega es 24h, asi que para hoy no podemos...'
...
⛔ FIN DETECCION URGENCIA ⛔
```

Este fix resuelve simultáneamente TC-URGENCIA-01 y TC-URGENCIA-02 porque el bloque cubre tanto horas numéricas ("a las 6") como textuales ("a las seis de la tarde") mediante la regla genérica "hora concreta del mismo día".

### Soluciones evaluadas (3)

| # | Solución | Estimación | Ventajas | Inconvenientes |
|---|----------|-----------|----------|----------------|
| **1** | **Restaurar bloque `DETECCION URGENCIA TEMPORAL` en `compra.yaml`** | **~15 min** | Fix probado, cubre toda la familia URGENCIA (01 + 02), sin cambios de arquitectura. | Requiere hacer el fix en el mismo commit que TC-URGENCIA-01 (o después, si ya se aplicó). |
| 2 | Ampliar regex del check T1 para aceptar catálogo como respuesta válida | ~5 min | No toca el playbook. | Solución incorrecta: el comportamiento del agente es el bug, no el test. Degradaría la cobertura QA. |
| 3 | Crear regla específica para variante textual de hora en `compra.yaml` | ~20 min | Más granular. | Duplicación de lógica respecto a la regla genérica ya existente. Mayor mantenimiento futuro. |

### Plan de acción

1. Verificar si el fix de TC-URGENCIA-01 ya fue aplicado (`git log -- definitions/playbooks/compra.yaml`).
2. Si no se ha aplicado: ejecutar `/qa-fix TC-URGENCIA-01 1` — resuelve ambos TCs en un único cambio.
3. Si ya se aplicó a TC-URGENCIA-01: el bloque ya estará presente y este TC debería pasar en el siguiente run. Verificar con rerun.
4. Validar que ambos TCs (01 y 02) pasan con 3/3 runs antes de cerrar.

---

> **Nota clave:** TC-URGENCIA-02 forma parte del patrón URGENCIA junto con TC-URGENCIA-01. El fix de TC-URGENCIA-01 (restaurar el bloque `DETECCION URGENCIA TEMPORAL`) resuelve este TC sin cambios adicionales. No son bugs independientes: comparten causa raíz única (ausencia del mismo bloque) y la misma solución. Aplicar el fix una sola vez cubre ambos casos.
