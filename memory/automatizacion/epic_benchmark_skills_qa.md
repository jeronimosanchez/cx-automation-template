---
name: epic-benchmark-skills-qa-tc-analyzer
description: "Épica: construir estructura comparativa entre versiones del skill qa-tc-analyzer (v1.0 vs v1.1 vs v1.2...) con KPIs cuantitativos y cualitativos. Permite decisiones basadas en datos sobre qué versión usar."
metadata: 
  node_type: memory
  type: project
  originSessionId: aba78269-83d9-450d-9b27-639b9a2827f7
---

# Épica — Benchmark comparativo de skills de análisis QA

**Origen:** 21-may-2026, sesión de mejora del proceso de análisis QA. Jero detecta que la capacidad de tener múltiples versiones del skill `qa-tc-analyzer` permite hacer A/B testing real con KPIs concretos, en lugar de iterar a ciegas.

**Hipótesis:** sin métricas objetivas, las mejoras al skill se evalúan por intuición. Con benchmark estructurado, se decide qué versión usar basado en datos.

**Valor para el proyecto:**
- 🎯 Decisiones basadas en datos, no en sensaciones
- 🔍 Detección automática de regresiones entre versiones
- 📊 Diferenciador comercial para consultoría ("tengo métricas, no opiniones")
- 🧪 Permite probar versiones experimentales sin miedo a romper la estable
- 📁 Construye un activo de portfolio profesional (proceso medible, no artesanal)

---

## Arquitectura propuesta

### Skills versionados como variantes

```
.claude/skills/
├── qa-tc-analyzer/              ← alias del activo (versión recomendada)
├── qa-tc-analyzer-v1.0/         ← snapshot v1.0 congelado
├── qa-tc-analyzer-v1.1/         ← snapshot v1.1 (con Cambio 2 ya aplicado)
├── qa-tc-analyzer-v1.2-exp/     ← experimental, no para producción
```

Invocación: `/qa-tc-analyzer-v1.1 TC-XYZ` vs `/qa-tc-analyzer-v1.0 TC-XYZ`.

### Suite de TCs testigos

Conjunto representativo, congelado, comparable:

| TC testigo | Tipo | Por qué representativo |
|---|---|---|
| TC-URGENCIA-01 | Bug Playbook con histórico | Mide capacidad anti-alucinación sobre PRs |
| TC-MULTI-PRODUCTO-01 | Bug con cascada multi-turno | Mide profundidad multi-turno |
| TC-FRUSTRACION-01 | Frontera playbook-catálogo | Mide capacidad de cruzar capas |
| TC-DECO-02 | Bug en datos (Sheet) | Mide detección de bug fuera del código |
| (TBD) | Test mal calibrado | Mide capacidad de proponer fix conservador |

---

## KPIs

### Cuantitativos (medibles automáticamente)

| KPI | Definición | Cómo medirlo | Mejor cuando... |
|---|---|---|---|
| **t_analisis** | Tiempo total desde invocación hasta MD generado | Cronómetro automático | menor |
| **tokens_in** | Tokens del prompt enviado al modelo | Conteo de prompt | menor (eficiencia) |
| **tokens_out** | Tokens del output generado | Conteo de respuesta | menor a igualdad de calidad |
| **coste_€** | tokens × precio modelo | Cálculo directo | menor |
| **pct_fix_acierta** | % de soluciones #1 propuestas que cerraron el TC al primer rerun | (TCs cerrados / TCs analizados) × 100 | mayor |
| **n_soluciones** | Número de soluciones propuestas en el MD | Conteo en el MD | adaptado a complejidad |
| **pct_verificadas** | % de afirmaciones marcadas con ✓ vs ? (cuando aplique Cambio 3) | Conteo en el MD | mayor |
| **n_patrones_cruzados** | Detecciones correctas de causa raíz común entre TCs | Auditoría manual | mayor |

### Cualitativos (requieren revisión humana, escala 1-5)

| KPI | Definición | Quién evalúa |
|---|---|---|
| **calidad_diagnostico** | ¿El análisis identifica correctamente qué falla? | Jero o reviewer |
| **realismo_soluciones** | ¿Las soluciones propuestas son aplicables en la práctica? | Jero |
| **claridad_plan_accion** | ¿El plan de acción es ejecutable sin reinterpretación? | Jero |
| **alucinaciones_post_hoc** | ¿Cuántas afirmaciones del análisis resultaron falsas tras verificar? | Auditoría con git log/gh pr |

### KPI consolidado

**`score_global`** = combinación ponderada de los anteriores:

```
score = 0.30 × pct_fix_acierta           (¿la solución funciona?)
      + 0.20 × calidad_diagnostico/5     (¿entiende el problema?)
      + 0.15 × realismo_soluciones/5     (¿las soluciones valen?)
      + 0.15 × (1 - alucinaciones_norm)  (¿es fiable?)
      + 0.10 × pct_verificadas/100       (¿es auditable?)
      + 0.10 × (1 - t_analisis_norm)     (¿es rápido?)
```

Pesos provisionales — se ajustan tras varios benchmarks reales.

---

## Output del benchmark

Estructura del archivo generado tras cada comparativa:

```
docs/benchmarks/
├── qa-tc-analyzer_v1.0_vs_v1.1_2026-05-21.md
│   ├── Suite ejecutada (lista de TCs)
│   ├── Métricas agregadas por versión (tabla)
│   ├── Detalle por TC (outputs lado a lado)
│   ├── Ganador por KPI
│   └── Recomendación consolidada
├── qa-tc-analyzer_v1.1_vs_v1.2_2026-06-15.md
└── ...
```

---

## Plan de implementación

### Fase 1 — Preparación (~4h)

1. Crear estructura `.claude/skills/qa-tc-analyzer-v1.0/` (snapshot del actual sin Cambio 2)
2. Mover el v1.1 a `qa-tc-analyzer-v1.1/` y dejar `qa-tc-analyzer/` como alias del activo
3. Crear script `qa/benchmark_skills.sh` que:
   - Recibe lista de skills a comparar + lista de TCs
   - Para cada combinación skill × TC: invoca el skill, mide tiempos, conteos
   - Calcula métricas agregadas
   - Genera el MD comparativo

### Fase 2 — Primer benchmark v1.0 vs v1.1 (~2h)

- Ejecutar sobre los 5 TCs testigos
- Documentar resultados en `docs/benchmarks/qa-tc-analyzer_v1.0_vs_v1.1_<fecha>.md`
- Validar que las métricas tienen sentido
- Ajustar pesos del score_global si hace falta

### Fase 3 — Iteración (~ongoing)

- Cada nueva versión propuesta del skill se benchmarka antes de declararla "activa"
- El doc maestro `docs/qa_analysis_process.md` actualiza la tabla de métricas con el resultado

---

## Cuándo abordar

- **NO ahora** (mientras estemos aplicando v1.1 cambios 3, 4, 5). Sería prematuro: necesitamos primero tener v1.1 completa para que tenga sentido comparar.
- **Sí cuando** v1.1 esté completa y haya propuesta de v1.2 → entonces el benchmark sirve para decidir si v1.2 sustituye a v1.1.
- **Estimación realista**: ~1 día de construcción + 0.5 días por benchmark posterior.

---

## Dependencias con otras épicas

- **Pre-requisito:** v1.1 completa (`docs/qa_analysis_process.md` con los 5 cambios aplicados al SKILL.md).
- **Habilita:** decisiones objetivas sobre futuros cambios al proceso, sin sesgo intuitivo.
- **Conexión con `epic_optimizar_analisis_QA.md`:** US-4 (marcado ✓/?) habilita el KPI `pct_verificadas`. Sin Cambio 3, ese KPI no es medible.

---

## Anti-patrones a evitar

- Construir benchmark antes de tener versiones realmente distintas → no aporta señal
- Definir pesos de `score_global` de forma rígida sin haber visto varios benchmarks → mejor pesos provisionales y ajustar
- Hacer benchmark sobre la suite completa (49 TCs) cada vez → coste prohibitivo. Mejor 5-10 TCs testigos representativos.
- Confundir "más métricas" con "mejor benchmark" → 8 KPIs bien definidos baten a 30 mal definidos.
