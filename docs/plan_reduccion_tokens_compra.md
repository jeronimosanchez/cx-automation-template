# Plan de reducción de tokens — compra.yaml

**Fecha:** 2026-07-02
**Estado actual:** 13,700 tk
**Objetivo:** ~6,000-8,000 tk (rango seguro Qwen 14B)

## Lista ordenada por coste de ejecución y dependencias

| Orden | # orig | Acción | Ahorro | Riesgo | Por qué aquí |
|---|---|---|---|---|---|
| 1 | 9 | Eliminar `# VARIABLES` (redundante con inputParameterDefinitions) | ~200 tk | Cero | Cero esfuerzo. Limpia ruido inmediato |
| 2 | 10 | Fusionar `⛔ REGLA CRITICA INVENTARIO ⛔` en PASO 2 (aparece 3 veces) | ~350 tk | Cero | Cero esfuerzo. Deja visible la lógica real de inventario |
| 3 | 11 | Eliminar duplicados tono/urgencia (dicho 2 veces a 9 líneas) | ~70 tk | Cero | Cero esfuerzo. Completa limpieza pura |
| 4 | 12 | IDENTIDAD abreviada en Compra (Orquestador ya estableció persona) | ~250 tk | Bajo | Aclara qué es Compra vs persona compartida |
| 5 | 1 | Cerrar prohibiciones → reglas positivas (completar `aa05036`) | ~300 tk | Bajo | Positivo es más compacto y facilita paso 7 |
| 6 | 2 | Reducir descripciones params input/output | ~200 tk | Bajo | Params limpios = más fácil diseñar interfaces de Tasks |
| 7 | 3+13 | Comprimir prosa + lenguaje verboso (un solo paso) | ~1,410 tk | Bajo | Mayor reducción de bajo riesgo. Bloques a extraer quedan claramente visibles |
| 8 | 4 | Eliminar 7 ejemplos inline → mover a CX Examples | ~1,100 tk | Medio | Quita ~1k tk de golpe. Deja el núcleo funcional expuesto para extracciones |
| 9 | 7 | Extraer Parseo de Slots + Desambiguación como Task | ~350 tk | Medio-alto | El parseo alimenta a ConsultaInventario — sale primero |
| 10 | 5 | Extraer Flujo Multi-Producto como Task | ~400 tk | Medio | Flujo discreto, bordes ya visibles tras pasos anteriores |
| 11 | 8 | Refactorizar ConsultaInventario como Task (reutilizable por Orquestador) | ~2,000-3,000 tk | Medio-alto | Mayor impacto, mayor riesgo — se hace con el playbook ya saneado |

**Eliminado:** #6 Frustración como Task — la detección debe estar en Compra de todas formas (estado transversal, no flujo discreto). Mismo motivo por el que urgencia tampoco se extrae.

## Acumulado por bloque

| Bloque | Pasos | Ahorro acumulado | Compra resultante |
|---|---|---|---|
| Limpieza pura | 1-3 | ~620 tk | ~13,080 tk |
| Bajo riesgo | 4-7 | ~2,780 tk | ~10,920 tk |
| Ejemplos | 8 | ~3,880 tk | ~9,820 tk |
| Extracciones | 9-11 | ~6,630-7,630 tk | **~6,070-7,070 tk** |

## Refactor transversal — renombrado de params (todos los playbooks)

**Alcance:** 6 playbooks + definitions/examples/ (no afecta a CX runtime directamente, solo a los YAMLs)
**Ahorro:** ~650 tk en YAMLs estáticos. Se multiplica en runtime (cada turno serializa el estado) y en QA (Qwen procesa menos tokens por run).
**Complejidad:** Media — es solo nomenclatura, pero cross-cutting. Un param renombrado debe actualizarse en todos los playbooks que lo usan simultáneamente.

| Param actual | Propuesta | Ahorro total | Playbooks afectados |
|---|---|---|---|
| `es_urgente` | `urgente` | −52 tk | compra, checkout, orchestrator, handoff |
| `usuario_frustrado` | `frustrado` | −64 tk | compra, checkout, orchestrator, gestion_deuda, handoff |
| `ocasion_detectada` | `ocasion` | −54 tk | compra, checkout, orchestrator |
| `intencion_inicial` | `intencion` | −34 tk | compra, orchestrator |
| `recien_registrado` | `recien_reg` | −30 tk | checkout, orchestrator, registro_task |
| `sesion_cerrada` | `cerrada` | −22 tk | checkout, orchestrator, registro_task |
| `precio_estimado` | `precio_est` | −40 tk | compra, checkout, orchestrator, gestion_deuda |
| `frustracion_detectada` | `frust_det` | −8 tk | compra |
| `presupuesto_duro` | `pres_duro` | −8 tk | compra |

**Descartados por riesgo de ambigüedad:** `precio_estimado→precio` (colisiona con `precio_max`/`precio_2`), `id_cliente→id`, `nombre_cliente→nombre`, `razon_handoff→razon`.

**Prerequisito:** verificar divergencia `modo_tono` vs `registro` en parameter_audit.md antes de ejecutar.
**Orden recomendado:** después del paso 6 del plan de compra (params ya limpios) y antes de los Tasks (#9-11).

## Notas de arquitectura

- Los Tasks (#9-11) cargan sus tokens **solo cuando se invocan** — confirmado en código ADK (`petal_agent_multi.py`) y docs CX.
- ConsultaInventario (#11) es reutilizable por Orquestador (~800 tk adicionales de ahorro en ORQ).
- El lenguaje compacto (paso 7) debe mantenerse natural para Qwen — notación telegráfica (`Si X → Y`) no recomendada para modelos <14B.
- Gemini (target producción) aguanta lenguaje compacto sin degradación.
- Hacer los pasos en orden: cada bloque limpia el playbook y hace más visibles los bordes del siguiente.
