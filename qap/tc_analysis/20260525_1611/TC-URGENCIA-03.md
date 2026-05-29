---
status: FAIL
tipo: EDGE
estimacion: fix ~15min
---

# TC-URGENCIA-03 — Entrega urgente — variante sin hora ('esta tarde')

**Grupo:** COMPRA-ZG | **Run:** 2026-05-25 16:11 | **Resultado:** 0/1 PASS

---

## Turnos

| # | Usuario | Agente (resumen) | Check |
|---|---------|-----------------|-------|
| 1 | "necesito un ramo de rosas para esta tarde" | Muestra catálogo de ramos directamente (Ramo Morado 37€, Amarillo 25€, Blanco 25€) | ❌ FAIL — debía indicar que la entrega para esta tarde no es posible |

**Regex esperado:** `hoy.{0,40}no|plazo|24h|24 horas|tarde.{0,30}no|entrega.{0,30}simulad|entrega.{0,30}disponible|equipo|humano`

---

## Causa raíz — 9 capas

| Capa | Estado | Detalle |
|------|--------|---------|
| 1. Sheet / datos | ✅ OK | SHEET_OK. Inventario correcto, no relevante para este flujo |
| 2. Tool / webhook | ✅ OK | No interviene en la detección de urgencia temporal |
| 3. Intent / NLU | ✅ OK | El mensaje "esta tarde" llega al playbook Compra sin problema |
| 4. Playbook Compra | ❌ BUG | Ausencia del bloque DETECCION URGENCIA TEMPORAL. El agente salta directamente a mostrar catálogo sin interceptar "esta tarde" como señal de urgencia |
| 5. Playbook Orquestador | ✅ OK | Enruta correctamente a Compra |
| 6. Playbook Checkout | ✅ OK | No relevante en turno 1 |
| 7. Task Registro | ✅ OK | No relevante en turno 1 |
| 8. Configuración agente | ✅ OK | Sin cambios |
| 9. Lógica de test / regex | ✅ OK | Regex correcto; incluye `tarde.{0,30}no` específicamente para esta variante sin hora |

**Causa raíz confirmada:** El commit `2126c52` revirtió el bloque `DETECCION URGENCIA TEMPORAL` que había sido introducido en `a10ab02`. En el HEAD actual (`2126c52`) ese bloque no existe en `compra.yaml`, por lo que el agente ignora cualquier señal de urgencia temporal (incluyendo "esta tarde") y muestra el catálogo directamente.

---

## Dimensionamiento del bug

- **Severidad:** Alta — el agente promete implícitamente una entrega que no puede cumplir (genera expectativa falsa al mostrar catálogo sin advertir la limitación)
- **Alcance:** Afecta a todas las variantes de urgencia temporal: "hoy", "esta tarde", "en X horas". Misma causa raíz que TC-URGENCIA-01 y TC-URGENCIA-02
- **Regresión:** Sí — el fix existió (commit `a10ab02`) y fue revertido dos veces (`1f95cae`, `2126c52`). El comportamiento correcto está validado
- **Complejidad del fix:** Baja — restaurar el bloque DETECCION URGENCIA TEMPORAL en compra.yaml

---

## Recomendación

### Solución #1 — Restaurar bloque DETECCION URGENCIA TEMPORAL en compra.yaml (recomendada)

Añadir al inicio del flujo principal de `compra.yaml` el bloque de detección de urgencia temporal, antes de la lógica de presentación de catálogo. El bloque debe interceptar expresiones como "esta tarde", "hoy", "en X horas" y responder indicando que la entrega no es posible en ese plazo (con variantes: "esta tarde no es posible", "el plazo mínimo es 24h", etc.).

El regex de validación incluye `tarde.{0,30}no` específicamente para esta variante, por lo que la respuesta del agente debe contener construcciones del tipo "esta tarde no podemos" / "para esta tarde no es posible".

**Ventaja:** fix directo, bajo riesgo, comportamiento ya validado en `a10ab02`.

### Solución #2 — Añadir Intent específico para urgencia temporal

Crear un intent `urgencia_entrega` que capture patrones como "esta tarde", "hoy mismo", "en X horas" y enrute a una página de respuesta de limitación de entrega antes de llegar a Compra.

**Ventaja:** separación de responsabilidades. **Desventaja:** mayor complejidad, requiere cambios en Flows/Pages además de Playbook.

### Solución #3 — Añadir condición en el Orquestador

Interceptar la señal de urgencia en el Orquestador antes de delegar a Compra, respondiendo directamente con el mensaje de limitación.

**Ventaja:** no toca compra.yaml. **Desventaja:** mezcla responsabilidades en el orquestador; peor mantenibilidad.

---

### Plan de acción (Solución #1)

1. Recuperar el bloque DETECCION URGENCIA TEMPORAL del commit `a10ab02` (`git show a10ab02 -- definitions/playbooks/compra.yaml`)
2. Añadir el bloque al inicio del flujo principal de `compra.yaml`, antes de la presentación de catálogo
3. Verificar que cubre las tres variantes: con hora específica (TC-URGENCIA-01), con "hoy" (TC-URGENCIA-02), con "esta tarde" (TC-URGENCIA-03)
4. Commit + PR + merge → deploy → rerun

**Comando QA post-fix:**
```
/qa-tc-analyzer TC-URGENCIA-01 TC-URGENCIA-02 TC-URGENCIA-03
```

---

## Patrones cruzados

**Patrón URGENCIA (3 TCs — misma causa raíz):**

| TC | Variante | Causa |
|----|----------|-------|
| TC-URGENCIA-01 | Con hora específica ("a las 5") | Ausencia DETECCION URGENCIA TEMPORAL |
| TC-URGENCIA-02 | Con "hoy" | Ausencia DETECCION URGENCIA TEMPORAL |
| TC-URGENCIA-03 | Con "esta tarde" (sin hora) | Ausencia DETECCION URGENCIA TEMPORAL |

Los tres TCs tienen **exactamente la misma causa raíz**: el revert `2126c52` eliminó el bloque `DETECCION URGENCIA TEMPORAL` de `compra.yaml`. Un único fix (Solución #1) resuelve los tres simultáneamente. Se recomienda hacer el fix una sola vez y validar los 3 TCs en el mismo rerun.
