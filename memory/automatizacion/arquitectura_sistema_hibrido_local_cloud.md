# Arquitectura del sistema híbrido — Divergencia local + Convergencia cloud

> **Fecha**: 2026-05-22
> **Estado**: propuesta validada, pendiente de construcción
> **Pre-requisitos**: bottom-up Petal + benchmark engine + adversarial framework
> **Cuándo arrancar**: Sprint S10-S11 (post-cierre de QA y bottom-up)

---

## Qué es

Modelo de servicio **AI-native** para diseñar, evaluar, desplegar y optimizar agentes
conversacionales (Petal y futuros clientes). Combina:

- **Divergencia local** (M4 24GB) con multi-agente para generar 500-1000 alternativas
  arquitectónicas a coste marginal cero
- **Convergencia cloud** (Claude Sonnet) para filtrar, evaluar y rankear
- **Pipeline ACT existente** para desplegar
- **QAP + adversarial** para validar
- **RES** para auto-corrección continua

Es la implementación profesional de las 4 líneas (ACT + GEN + QAP + RES) como un
único producto consultivo escalable.

---

## Por qué tiene sentido

### 1. Moat económico — divergencia a coste cero

| Modelo | Coste por ciclo de divergencia | 100 ciclos |
|---|---|---|
| Consultor senior | 8-16h × 80€/h = 640-1.280€ | 64.000-128.000€ |
| Cloud LLM (Claude/GPT) | 5-20€ tokens | 500-2.000€ |
| **M4 local 24h** | **~0,30€ luz** | **30€** |

Permite mostrar 3-5 alternativas donde competidor muestra 1, e iterar 10 veces antes
de presentar al cliente.

### 2. Calidad reproducible por diseño

Cada cliente recibe el mismo rigor metodológico:
- 3 propuestas arquitectónicas con evidencia
- Benchmark contra datos reales del cliente
- KPIs medibles, no opinión

### 3. Escalabilidad 1:N

Una persona puede servir N clientes simultáneamente porque el grueso del trabajo
(divergencia + validación) corre en infra automatizada.

### 4. Diferenciación vs competidores

| Competidor | Lo que entrega |
|---|---|
| Dev con Claude | 1 arquitectura propuesta |
| Consultor tradicional | 1-2 arquitecturas con horas humanas |
| **Tu sistema** | **3+ arquitecturas evaluadas con métricas + plan de migración** |

---

## Arquitectura — 8 capas

```
┌─────────────────────────────────────────────────────────────┐
│  CAPA 1 — INPUTS                                            │
│  • Brief del cliente (o brief de evolución interna)         │
│  • RAG indexado: playbooks existentes + best practices CX   │
│  • Constraints duros: idempotencia, full update, KPIs       │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 2 — DIVERGENCIA LOCAL (M4, coste ~0)                  │
│  Stack: Ollama + Llama 3.1 8B / Qwen 14B + CrewAI/AutoGen   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Agente Generator → propone arquitecturas             │   │
│  │ Agente Critic    → estresa con conversaciones duras  │   │
│  │ Agente Validator → check constraints (descarta inv.) │   │
│  └──────────────────────────────────────────────────────┘   │
│  Loop 1-2h → 500-1000 candidatos en queue local             │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 3 — FILTRO TÉCNICO CLOUD (Claude Sonnet, ~5-10€)      │
│  • Lee candidatos                                           │
│  • Descarta: inválidos, duplicados, broken, constraints     │
│    violados                                                 │
│  • NO filtra por "calidad subjetiva" — solo viabilidad      │
│  • Output: 30-50 candidatos técnicamente viables            │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 4 — EJECUCIÓN MASIVA (ACT, ya operativo)              │
│  Despliega los 30-50 a environments paralelos en CX         │
│  (reutilización secuencial si hay límite de environments)   │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 5 — VALIDACIÓN MASIVA (QAP + Adversarial)             │
│  • 50 TCs × 30-50 candidatos                                │
│  • 500 ataques adversariales × 30-50                        │
│  • Métricas: % PASS, tokens, latencia, robustez             │
│  • Coste extra vs solo 3: +20-35€ (insignificante vs riesgo │
│    de descartar el ganador real)                            │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 6 — RANKING AUTOMÁTICO                                │
│  • Ranking ponderado por KPIs sobre los 30-50               │
│  • Top 3 con KPIs detallados emergen automáticamente        │
│  • Ganador si supera baseline +5% en KPIs clave             │
│  • Detección de optimizaciones cruzadas entre candidatos    │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 7 — VALIDACIÓN ESTRATÉGICA HUMANA (15 min)            │
│  • Revisa ganador con KPIs completos                        │
│  • Valida: ¿KPIs cumplen? ¿estratégicamente sensato?        │
│    ¿encaja con roadmap cliente?                             │
│  • Decisión basada en datos, no en filtrado intuitivo       │
└─────────────────────────────────────────────────────────────┘
              ↓
┌─────────────────────────────────────────────────────────────┐
│  CAPA 8 — PRODUCCIÓN + RES                                  │
│  • Ganador a producción                                     │
│  • RES monitoriza y auto-corrige                            │
│  • Si degradación → vuelta a Capa 2 con problema concreto   │
└─────────────────────────────────────────────────────────────┘
```

---

## Coste por ciclo completo (1 cliente o 1 evolución de Petal)

| Capa | Coste | Tiempo |
|---|---|---|
| 1 — Inputs | 0€ | manual, ~1h |
| 2 — Divergencia local | 0,30€ luz | 1-2h |
| 3 — Filtro técnico cloud | 5-10€ tokens | 10-20 min |
| 4 — Ejecución ACT masiva (30-50 environments) | 0€ | 30-60 min |
| 5 — Validación QAP masiva (30-50 candidatos) | 30-50€ | 3-5h |
| 6 — Ranking automático | 0€ | 5 min |
| 7 — Validación estratégica humana | 0€ | 15 min |
| 8 — RES continuo | 1-3€/mes | recurrente |
| **Total por ciclo** | **~40-65€** | **~5-8h** |

**Trade-off coste vs riesgo**: el incremento de 20-35€ por benchmarkear 30-50 en vez de 3 candidatos es **trivial frente al riesgo** de descartar el ganador real por filtrado humano subjetivo. En un proyecto de 50-150K€, es seguro barato.

---

## Cambio clave en el rol humano (decisión 22-may)

El rol humano se ELEVA: deja de ser filtro mid-funnel (donde el sesgo cognitivo limita) y pasa a ser decisor estratégico final (donde el contexto de negocio sí aporta).

| Rol humano (modelo anterior) | Rol humano (modelo actual) |
|---|---|
| Filtra top 10 → top 3 (40% del tiempo) | Valida ganador con datos (15% del tiempo) |
| Acepta/rechaza propuestas individualmente | Valida que ganador encaja con contexto cliente |
| Sesgo cognitivo afecta filtrado | Solo entra cuando datos están claros |
| Riesgo de descartar buen candidato | Riesgo cero — todas las viables se prueban |

**Implicación comercial defendible**:
> "Probamos las 30 arquitecturas técnicamente viables, no las 3 que un consultor humano tuvo tiempo de revisar."

Competidor humano no puede igualar volumen + objetividad simultáneamente.

---

## Stack técnico

| Componente | Tecnología |
|---|---|
| Modelos locales | Ollama + Llama 3.1 8B + Qwen 2.5 14B |
| RAG local | AnythingLLM o LangChain con ChromaDB |
| Multi-agente | CrewAI (más simple) o AutoGen (más potente) |
| Filtro cloud | Claude Sonnet via Anthropic API |
| Pipeline despliegue | ACT existente (GitHub Actions + WIF) |
| Benchmark | QAP existente + extensión A/B/C |
| Monitoreo continuo | Rutinas Claude Code |
| Sistema fuente verdad | Google Sheets (catálogo + business + agent_copy) |

---

## Cuándo usar este sistema vs el approach actual

### Usar este sistema (divergencia + convergencia)

- Cliente nuevo entra con brief → 3 arquitecturas candidatas evaluadas
- Refactor mayor de Petal → 3 reorganizaciones evaluadas
- Diseño de un nuevo flujo complejo → 3 estructuras alternativas
- Cuando se busca explorar arquitecturas fuera del sesgo actual

### NO usar este sistema (mantener approach Claude-directo)

- Fix puntual de un TC fallando
- Ajuste de prompt específico
- Cambio menor en un playbook
- Tareas operativas/ejecutivas concretas

**Regla**: divergencia → local. Convergencia y ejecución → cloud/Claude.

---

## Pre-requisitos antes de construir

| Pre-requisito | Por qué | Estado | Sprint |
|---|---|---|---|
| Bottom-up de Petal | Sin stories y criterios, no hay constraints inyectables | Pendiente | S7 |
| Benchmark engine A/B funcional | Sin esto, "ganador" es subjetivo | Pendiente | S9 |
| Adversarial framework | Sin esto, robustez no medible | Pendiente | S8 |
| Constraints escritos (idempotencia, full update, patrones Petal) | Para inyectar a Validator local | Parcial (CLAUDE.md) | S7 |

Saltarse cualquier prerrequisito hace este sistema costoso sin retorno medible.

---

## Tiempo de construcción del sistema

| Pieza | Duración estimada |
|---|---|
| Setup local Ollama + RAG | 2-3 días |
| Multi-agente CrewAI/AutoGen | 4-5 días |
| Filtro cloud (script de evaluación con Claude API) | 2 días |
| Integración con ACT existente (deploy a environments paralelos) | 2 días |
| Adaptación QAP a comparativa A/B/C | 3 días |
| Dashboard de ranking + decisión | 2 días |
| **Total** | **~2.5-3 semanas** |

Con factor de buffer 2x: **5-6 semanas reales**.

---

## Riesgos identificados

| Riesgo | Mitigación |
|---|---|
| Modelos locales (8B/14B) generan JSON sintácticamente válido pero conversacionalmente pobre | Filtro cloud filtra agresivamente; constraints duros como entrada |
| Groupthink local (agentes convergen en mala idea consistente) | Validator independiente con criterios duros + tercer agente externo |
| 24GB justos para 14B + RAG + 2-3 agentes simultáneos | Monitor swap; alternativa Llama 8B si memoria se llena |
| Sin GPU dedicada, latencia M4 puede ser ~50 tok/s | Compensa con tiempo (1-2h continuos producen suficiente volumen) |
| Constraints en CLAUDE.md no se inyectan automáticamente | Construir loader que extraiga reglas y las pase al Validator |

---

## Implicación comercial — Service Model AI-native

Lo que estás construyendo NO es una herramienta interna, es un **producto de servicio**:

- **Consultoría tradicional**: humanos venden horas, escala 1:1, márgenes bajos
- **Tu modelo**: AI genera/evalúa/despliega/valida, tú curas y vendes. Escala 1:N, márgenes altos, calidad reproducible por diseño

**Pricing defendible**: 15-150K€ por proyecto siendo una sola persona, porque no estás vendiendo tu tiempo — estás vendiendo el output de una máquina que opera 24/7 sin marginal cost.

**Moat real**: 100 ciclos de divergencia te cuestan 30€. Competidor con cloud-only paga 500-2.000€. Competidor con consultor tradicional paga 64-128K€. Esa asimetría económica es lo que defiende el negocio.

---

## Conexión con épicas existentes

| Épica relacionada | Cómo conecta |
|---|---|
| `epic_backlog_conversational_design` | Aporta stories y criterios que se inyectan como constraints al Validator local |
| `epic_optimizar_analisis_QA` | El filtro cloud (Capa 3) usa los aprendizajes de anti-alucinación del skill QA |
| `epic_benchmark_skills_qa` | El benchmark engine usado en Capa 6 es el mismo que evalúa versiones del skill |
| `mercado_renovacion_legacy` | Este sistema ES el producto que se vende a clientes de renovación |
| `estrategia_comercial_consultoria` | El moat económico de divergencia local hace viable independent-declared sin partner credits |
| `proximo_sprint_ingenieria_inversa` (current/) | Sprint S7 es prerrequisito directo |

---

## Próximo paso concreto

Cuando llegue Sprint S10-S11:

1. Pruebas de concepto rápidas (2-3 días): Ollama + Llama 8B en M4, primer test de generación de 1 playbook simple
2. Si los resultados son aceptables → construir el sistema completo según el roadmap arriba
3. Si los resultados son pobres → reevaluar: ¿Qwen 14B? ¿modelo distinto? ¿cloud para esta fase también?

**No comprometerse a construir el sistema completo sin la prueba de concepto inicial**. 2-3 días de validación pueden ahorrar 5 semanas de inversión sobre arquitectura inadecuada.
