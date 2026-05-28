---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #2 recomendada)
---

## T3 (turno crítico)

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero un ramo de rosas y un centro de mesa para mi casa"* | — |
| 1 | Compra | Catálogo ramos rosas (3 opciones) | ✅ Correcto |
| 2 | User | *"el ramo de rosas morado de 37 euros"* | — |
| 2 | Compra | ECO "Anotado, 1x Ramo Morado" + catálogo centros | ✅ Correcto |
| 3 | User | *"el centro de tulipanes de 28 euros"* | — |
| 3 | Compra | ECO RESUMEN "1x Ramo (37€) y 1x Centro (28€). ¿Lo confirmo?" — **SIN total** | 🔴 Falta total (test espera 65) |

### Causa raíz — evaluación de las 9 capas

🔴 1. **Capa Comportamiento** [verificada] · `Read compra.yaml:601-605`

Template del ECO RESUMEN del FLUJO MULTI-PRODUCTO está MAL: solo referencia UN producto y NO calcula total. Contradicción interna: línea 600 captura `$producto_2`, `$cantidad_2`, `$precio_2`; línea 607 los pasa a Checkout; pero líneas 603-605 no los usan en el ECO. El LLM en run 2 generó template extendido por su cuenta pero sin total porque el playbook no lo pide.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟢 3. **Capa Parámetros/Slots** [verificada] · `Read compra.yaml:595-600`

Los slots `$producto_2`, `$cantidad_2`, `$precio_2` SE capturan correctamente y SE pasan a Checkout. El problema no es el contrato de slots, es que el template ECO no los usa.

🟢 4. **Capa Integración** [verificada] · `runs 1/2/3 logs`

Backend devuelve precios correctos en T2. Sin error de tool call.

🟡 5. **Capa Datos** [supuesta] · _(no verificado: requiere consultar logs Cloud Run para confirmar scoring inventario)_

Variabilidad de catálogo en T2 (runs 1/3 no incluyen tulipanes, run 2 sí). NO es causa del FAIL del test (test pide "65", no tulipanes específicos), pero ensucia los logs. Cubierto por épica `pendiente_refactor_compra`.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde.

🟡 7. **Capa Modelo/LLM** [supuesta] · _(no verificado con N≥2 — Capa 1 es la causa)_

En run 2 el LLM extendió el template por su cuenta para listar 2 productos pero no calculó total. Con prompt mejor probablemente sí calcularía. No se puede marcar 🔴 sin descartar capa 1.

🔴 8. **Capa Histórico** [verificada] · `git log -n 20 -- definitions/playbooks/compra.yaml`

Commit `eb928a2` (TEMP fix ECO RESUMEN multi-producto incluye 2 productos + total) revertido en `a957a04`. Patrón demo break.

🟢 9. **Capa Test** [verificada] · `Read JSON tc_id`

Test bien calibrado: pide "65" (suma exacta 37+28). Mide directamente el comportamiento que debería tener un ECO RESUMEN multi-item.

**Resumen visual:** 2 🔴 · 3 🟢 · 2 🟡 · 2 ⚪

## Recomendación

### Solución recomendada: #2 — Cherry-pick `eb928a2` + instrucción explícita "muestra siempre suma total"

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: el fix `eb928a2` ya existe en historial. Validado empíricamente en sesión 2026-05-28 (5/5 PASS POST-FIX). Cero diseño nuevo.

### Dimensionamiento del bug

| Dimensión | Nivel | Justificación |
|---|---|---|
| Alcance | Trivial | 1 archivo (compra.yaml), 3 líneas (templates ECO) |
| Profundidad | Trivial | Editar texto del template, añadir cálculo de suma |
| Riesgo de regresión | Trivial | Solo afecta FLUJO MULTI-PRODUCTO |

**Nivel final:** Trivial → 3 soluciones

### Soluciones evaluadas

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Extender template ECO con 2 productos + total explícito** (líneas 603-605) | 🟢 9/10 | — | Fix directo en la capa del bug |
| 2 | **Solución #1 + nota explícita "muestra siempre suma total"** | 🟢 8/10 | — | Más defensivo, sin coste extra |
| 3 | **Refactor: extraer ECO RESUMEN como sub-bloque parametrizado iterando productos** | 🟡 5/10 | — | Sobre-ingeniería para fix trivial |

### Plan de acción (Solución #2)

1. **Cherry-pick `eb928a2`** o restaurar manualmente bloque desde ese commit
2. **Editar líneas 603-605 de `compra.yaml`** con templates que incluyan ambos productos + total calculado
3. **Añadir instrucción** "⛔ OBLIGATORIO: calcula y muestra suma total cuando haya 2 productos"
4. **Re-ejecutar QA** con `--runs 3` filtrando TC-MULTI-PRODUCTO-01

**Coste total**: ~12 min edición + 3 min QA = ~15 min.

### Parámetros / slots requeridos

| Slot | Playbook origen | Playbook destino | Obligatorio | Notas |
|------|----------------|-----------------|-------------|-------|
| `$producto_2` | Compra | Checkout | Sí (en multi-producto) | Captura en paso 6b |
| `$cantidad_2` | Compra | Checkout | Sí | Idem |
| `$precio_2` | Compra | Checkout | Sí | precio_unitario × cantidad_2 |
| `$total` | Compra | Checkout | Calculado on-the-fly | precio_estimado + precio_2 |

### Nota secundaria

La variabilidad de catálogo en T2 (runs 1/3 sin tulipanes) NO es lo que falla este test, pero es ruido. Cubierto por épica `pendiente_refactor_compra` (Consulta_Inventario como Task). No tocar ahora.
