# Plan de reducción de tokens — compra.yaml

**Fecha:** 2026-07-02
**Estado actual:** 13,700 tk
**Objetivo:** ~6,000-8,000 tk (rango seguro Qwen 14B)

## Lista de optimizaciones

| # | Acción | Ahorro est. | Riesgo |
|---|---|---|---|
| 1 | Cerrar prohibiciones → reglas positivas (completar `aa05036`) | ~300 tk | Bajo |
| 2 | Reducir descripciones params input/output (verbosas en ambos lados) | ~200 tk | Bajo |
| 3 | Comprimir prosa — 4 secciones (TURNO NATURAL, RESTRICCIÓN TEMPORAL, DESAMBIGUACIÓN ROSAS, CLASIFICACIÓN INPUT) | ~410 tk | Bajo |
| 4 | Eliminar 7 ejemplos inline → mover a CX Examples | ~1,100 tk | Medio |
| 5 | Extraer Flujo Multi-Producto como Task | ~400 tk | Medio |
| 6 | Extraer Gestión de Frustración como Task | ~300 tk | Medio |
| 7 | Extraer Parseo de Slots + Desambiguación como Task | ~350 tk | Medio-alto |
| 8 | Refactorizar ConsultaInventario como Task (reutilizable por Orquestador) | ~2,000-3,000 tk | Medio-alto |
| 9 | Eliminar `# VARIABLES` (redundante con inputParameterDefinitions) | ~200 tk | Cero |
| 10 | Fusionar `⛔ REGLA CRITICA INVENTARIO ⛔` en PASO 2 (aparece 3 veces) | ~350 tk | Cero |
| 11 | Eliminar duplicados tono/urgencia (dicho 2 veces a 9 líneas de distancia) | ~70 tk | Cero |
| 12 | IDENTIDAD abreviada en Compra (versión mínima, el Orquestador ya estableció persona) | ~250 tk | Bajo |
| 13 | Compactar lenguaje verboso — lenguaje natural pero conciso, sin telegráfico (para Qwen) | ~1,000 tk | Bajo |

**Total acumulado:** ~7,000-8,000 tk → Compra: 13,700 → **~5,700-6,700 tk**

## Notas de arquitectura

- Los Tasks (#5-8) cargan sus tokens **solo cuando se invocan** — confirmado en código ADK (`petal_agent_multi.py`) y en docs CX (la transición resume contexto previo, no lo carga completo).
- ConsultaInventario (#8) es reutilizable por Orquestador (~800 tk adicionales de ahorro en ORQ).
- El lenguaje compacto (#13) debe mantenerse natural para Qwen — notación telegráfica (`Si X → Y`) no recomendada para modelos <14B.
- Gemini (target producción) aguanta lenguaje compacto sin degradación.

## Orden de ejecución recomendado

1. Primero cero-riesgo: #9, #10, #11 (~620 tk)
2. Luego bajo riesgo: #1, #2, #3, #12, #13 (~2,160 tk)
3. Ejemplos inline: #4 (~1,100 tk, verificar cobertura en `definitions/examples/compra/`)
4. Tasks estructurales: #5, #6, #7 (~1,050 tk)
5. ConsultaInventario Task: #8 (~2,000-3,000 tk, mayor impacto)
