# QAP Hypothesis Loop — Diseño del sistema de análisis y mejora automática

**Fecha:** 2026-06-15  
**Estado:** Propuesta de diseño — parcialmente implementada, sin validar empíricamente  
**Contexto:** Petal (agente conversacional Dialogflow CX, floristería online)  
**Artefactos implementados:** `qap/static_audit.py`, `qap/correlate_static_dynamic.py`

---

## 1. El problema

El agente Petal tiene una suite de 51 TCs que corre contra CX real. El resultado es un listado de PASS/FAIL/INESTABLE. El problema es: **cuando un TC falla, no sabemos automáticamente por qué ni qué arreglar.**

Las opciones actuales son:
- Leer el log manualmente y diagnosticar (lento, no escala)
- Darle todo el contexto a un LLM y pedirle que diagnose y arregle (~60-80k tokens, alucinaciones al escalar)

El sistema descrito en este documento busca una tercera vía.

---

## 2. El pipeline estático-dinámico

### 2.1 Capa estática — `static_audit.py`

Analiza los playbooks YAML **sin ejecutar el agente**. Audita 13 criterios de diseño:

| Campo | Criterio | Mecanismo de fallo conocido |
|---|---|---|
| `size` | Token size | LLM pierde el hilo con >10k tokens |
| `snake` | snake_case params | Param incorrecto → slot vacío silencioso → condicional erróneo |
| `exit` | Exit paths | Sin exit → agente bucla o da non-answer |
| `cycle` | Deleg. cycle | Bucle de delegación → crash inevitable |
| `neg` | Negation ex. | Sin señal de entrenamiento → ignora cancelación |
| `tool_fail` | Tool failure ex. | Sin señal → alucina ante error de backend |
| `ex_cnt` | Examples (≥4) | Pocos ejemplos → CX enruta al playbook incorrecto |
| `dsl` | DSL density | DSL denso ($refs) dificulta el parsing del LLM |
| `always` | Always-select | Depende de cobertura de ejemplos — efecto indirecto |
| `params` | Params declared | Pueden cargarse vía tool en runtime |
| `steps` | Step count | Indicador de mantenibilidad — efecto difuso |
| `name_len` | Name length | Límite duro de plataforma |
| `single` | Single resp. | Indicador de complejidad — efecto difuso |

Output: matriz de 🔴/🟡/✅ por playbook × criterio.

### 2.2 Capa dinámica — suite QA

51 TCs que corren contra CX real. Cada TC genera un JSON con:
- `status`: PASS / FAIL / INESTABLE
- `trace.actions[*].playbookInvocation.displayName`: qué playbooks tocó en cada turno

### 2.3 Correlación — `correlate_static_dynamic.py`

Cruza las dos capas: para cada criterio estático flaggeado, calcula cuántos TCs FAIL/INESTABLE pasaron por un playbook con ese problema.

```
Para cada criterio:
  flagged_pbs = playbooks con ese criterio en 🔴 o 🟡
  fail_hits   = TCs FAIL que tocaron algún flagged_pb
  pass_hits   = TCs PASS que tocaron algún flagged_pb
  pct         = fail_hits / (fail_hits + pass_hits)
```

---

## 3. Scoring de plausibilidad causal (Bradford Hill simplificado)

La correlación no implica causalidad. Para saber **cuánto confiar** en que la correlación es causal, se puntúan tres criterios inspirados en Bradford Hill (0-5):

### Criterio 1 — Plausibilidad mecánica (0-2, hardcoded)

¿Existe un mecanismo conocido por el que este criterio puede causar un FAIL?

- `high` (+2): mecanismo directo y conocido (snake_case → slot vacío → condicional erróneo)
- `medium` (+1): mecanismo plausible pero indirecto (pocos ejemplos → CX enruta mal)
- `low` (+0): indicador de calidad sin mecanismo causal claro

### Criterio 2 — Especificidad (0-2, computable)

¿El criterio aparece más en FAILs que en el baseline global?

```
baseline  = total_fails / total_tcs          # tasa base del run (9.8% con 51 TCs)
fail_rate = fail_hits / (fail_hits + pass_hits)
ratio     = fail_rate / baseline

ratio ≥ 3x  → +2  (alta especificidad)
ratio ≥ 1.5x → +1  (moderada)
ratio < 1.5x → +0  (ruido estadístico)
```

### Criterio 3 — Gradiente de severidad (0-1, computable)

¿Los playbooks con 🔴 producen más FAILs que los con 🟡 para el mismo criterio?

```
red_rate = FAILs en TCs que tocan playbooks 🔴 / total TCs que tocan 🔴
yel_rate = FAILs en TCs que tocan playbooks 🟡 / total TCs que tocan 🟡
red_rate > yel_rate → +1 (gradiente confirmado)
```

### Resultado

```
score 0-5 → ALTA (≥4) / MEDIA (2-3) / BAJA (<2)

Solo ALTA + MEDIA pasan como hipótesis candidatas para el loop de fix.
BAJA = ruido estadístico o mecanismo demasiado débil para actuar.
```

**Output del run actual (51 TCs, 5 FAIL/INESTABLE, baseline 9.8%):**

| Criterio | BH | Especificidad | Gradiente | Candidata |
|---|---|---|---|---|
| Examples (≥4) | 3/5 | 2.3x ✓ | 🔴 25% > 🟡 20% ✓ | MEDIA ✓ |
| Token size | 3/5 | 1.1x ✗ | 🔴 12% > 🟡 11% ✓ | MEDIA ✓ |
| DSL density | 2/5 | 1.0x ✗ | 🔴 10% > 🟡 0% ✓ | MEDIA ✓ |
| snake_case | 2/5 | 1.0x ✗ | n/a (solo 🔴) | MEDIA ✓ |
| Always-select | 1/5 | 2.5x ✓ | n/a | BAJA ✗ |
| Params declared | 0/5 | 1.0x ✗ | n/a | BAJA ✗ |

**Limitación actual:** con solo 5 TCs FAIL, la potencia estadística es baja. La especificidad de la mayoría de criterios es ruido porque los playbooks afectados (Compra, Orchestrator) aparecen en casi todos los TCs. El BH score ayuda a filtrar, pero no suple una suite mayor.

---

## 4. Estructura de hipótesis

La correlación produce **hipótesis de problema (H)**. Para cada H hay múltiples **hipótesis de solución (HS)**. No es una cruz completa — cada H tiene sus propias HS independientes.

```
H1: Examples (≥4) en Handoff → causa TC-FRUSTRACION-01
  H1-HS1: añadir 4 ejemplos canónicos de frustración a Handoff
  H1-HS2: reescribir la instrucción de transición (más explícita)
  H1-HS3: añadir always-select que capture frustración antes del routing

H2: Token size en Compra → causa TC-FRUSTRACION-01
  H2-HS1: extraer ConsultaInventario como sub-playbook (reduce ~6k tokens)
  H2-HS2: comprimir instrucciones redundantes
  H2-HS3: podar ejemplos obsoletos del flujo de pago

H3: snake_case en Registro_Task → causa TC-MULTI-PRODUCTO-01
  H3-HS1: renombrar param (fix determinista — una sola opción)
```

**Total tests ADK = Σ(HS por H)**, no una cruz completa. Fixes deterministas tienen 1 HS. Fixes generativos tienen 2-4 HS propuestas por el LLM.

---

## 5. El loop REACTIVO — fix de lo conocido

Trigger: un TC falla en CX (ya se sabe que hay un problema).

```
┌─────────────────────────────────────────────────────┐
│  Python (0 tokens)                                  │
│  static_audit + correlación → BH score              │
│  → lista de hipótesis H-HSn rankeadas por urgencia  │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  LLM barato (Haiku / Gemini Flash, ~3-5k tokens)    │
│  Input: criterio fallido + sección YAML afectada    │
│  Output: YAML del parche para H-HS1, HS2, HS3       │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  ADK runner (local, 0 tokens)                       │
│  Aplica el parche en memoria → rerun TC             │
│  PASS → PR a CX / FAIL → siguiente H-HSn           │
└─────────────────────────────────────────────────────┘
```

### Por qué el LLM es barato aquí

El pipeline hace el trabajo analítico (0 tokens) y entrega al LLM **un contexto reducido y dirigido**. El modelo no razona sobre 60k tokens — recibe la hipótesis ya formada.

| Enfoque | Tokens por fix | Riesgo de alucinación |
|---|---|---|
| LLM directo (todos los playbooks) | ~60-80k | Alto a escala |
| Nuestro pipeline | ~3-5k | Bajo (espacio acotado) |

**Reducir el espacio de búsqueda antes del LLM es la aportación central del sistema.** La contextualización es el pipeline.

---

## 6. El loop PROACTIVO — descubrimiento de lo desconocido

Trigger: cron / on-demand. No hay TC fallido previo.

```
┌─────────────────────────────────────────────────────┐
│  LLM adversarial local (Qwen 7b, ~$0)               │
│  Lee los playbooks → genera N edge cases            │
│  "20 formas ambiguas de pedir un ramo"              │
│  "usuarios que cambian de intent a mitad"           │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  ADK runner (local, 0 tokens)                       │
│  Testa cada edge case contra los playbooks          │
└──────────────────────┬──────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│  Tabla de auditoría                                 │
│  PASS / FAIL por caso generado                      │
│  FAILs sobre umbral → nuevos TCs + PR potencial     │
└─────────────────────────────────────────────────────┘
```

**Diferencia con el reactivo:** el proactivo descubre vulnerabilidades *antes* de que fallen en CX. El adversarial inventa el problema; el reactivo lo analiza una vez conocido.

**Coste:** ~$0 (LLM local + ADK local). El único coste es CPU y tiempo.

---

## 7. Ponderación de TCs — la tercera dimensión

### 7.1 Taxonomía estándar en Diseño Conversacional

La clasificación más común en DC es por tipo de camino:

| Tipo | Qué cubre |
|---|---|
| **Happy path** | Flujo ideal: usuario cooperativo, intención clara, backend OK |
| **Alternate paths** | Variaciones válidas: sinónimos, orden distinto, interrupciones |
| **Error paths** | Fallos esperados: NLU no entiende, backend cae, usuario cancela |
| **Edge cases** | Límites: inputs ambiguos, multi-intent, cambio de intent a mitad |

Y por componente que testa: NLU coverage, slot filling, flow completion, fallback/escalation.

### 7.2 Lo que falta: impacto de negocio

La taxonomía estándar no lleva peso de negocio. Un happy path de "consultar horario" y uno de "completar pago" son la misma categoría, aunque uno valga €0 y el otro valga €50.

La capa de impacto de negocio requiere **definición humana explícita previa**:

| Nivel | Criterio de clasificación | Umbral de calidad |
|---|---|---|
| **P0** | Flujos que generan dinero o son críticos para el usuario | 100% PASS — bloquea deploy |
| **P1** | Flujos frecuentes pero no transaccionales | ≥90% PASS — se trackea |
| **P2** | Edge cases, casos exóticos, graceful degradation | ≥70% PASS — informativo |

**Importante:** el adversarial genera P1/P2 por defecto. No puede saber si un edge case inventado es crítico para el negocio. Los P0 los define el diseñador.

### 7.3 El peso propaga hacia arriba en el pipeline

La aportación que no está en QA estándar: el peso del TC no solo afecta al umbral de deploy — **retroalimenta el ranking de hipótesis**.

```
urgencia_hipótesis = BH_score × peso_severity(P0=3, P1=2, P2=1)
```

Un criterio con BH 3/5 que correlaciona con un P0 FAIL es más urgente que uno con BH 4/5 que solo aparece en P2 FAILs.

Esto está propuesto pero **no implementado** en el script actual (que trata todos los FAILs igual).

---

## 8. Lo que está implementado vs lo que es propuesta

| Componente | Estado | Artefacto |
|---|---|---|
| Static audit (13 criterios) | ✅ Implementado | `qap/static_audit.py` |
| Correlación estático-dinámica | ✅ Implementado | `qap/correlate_static_dynamic.py` |
| BH scoring (mecanismo + especificidad + gradiente) | ✅ Implementado | `qap/correlate_static_dynamic.py` |
| ADK runner (simulación CX local) | ✅ Implementado | `qap/adk_fidelity/` (problema de memoria en Mac con 14b) |
| LLM generador de fixes (H-HS) | ❌ No implementado | — |
| Loop reactivo completo | ❌ No implementado | — |
| LLM adversarial proactivo | ❌ No implementado | — |
| Ponderación P0/P1/P2 en el pipeline | ❌ No implementado | — |

---

## 9. Supuestos sin validar

El sistema descrito es un diseño razonado, no un sistema validado. Los supuestos clave que hay que comprobar empíricamente:

1. **¿El BH score predice qué fixes funcionan?** — Un criterio con ALTA plausibilidad, ¿produce fixes que hacen pasar el TC con más frecuencia que uno BAJA? No lo sabemos.

2. **¿La correlación apunta al playbook correcto?** — Los playbooks más grandes (Compra, Orchestrator) aparecen en casi todos los TCs. La correlación puede estar señalando ubiquidad, no causalidad.

3. **¿El adversarial genera casos útiles?** — Un Qwen 7b inventando variaciones de usuario puede producir casos que CX ya maneja bien, sin añadir cobertura real.

4. **¿El ADK simula CX fielmente?** — El baseline actual es 54-64% de acuerdo entre ADK y CX. Un fix que pasa en ADK puede seguir fallando en CX.

---

## 10. Alternativas al enfoque propuesto

| Enfoque | Ventaja | Desventaja |
|---|---|---|
| **LLM directo** (Claude lee todo y arregla) | Simple, sin infraestructura | ~80k tokens, alucinación a escala, no auditable |
| **Mutation testing** (mutar playbooks, ver qué rompe) | Encuentra fragilidades sin TCs previos | Requiere definir qué mutaciones son válidas |
| **LLM judge sin ejecutar** | Barato, rápido | No detecta fallos de routing o webhook |
| **A/B entre versiones de playbook** | Evidencia directa de mejora | Requiere staging operativo |

El enfoque de este documento no invalida los otros — pueden ser complementarios o superiores según el contexto.

---

## 11. Prerequisitos para el loop completo

Para que el loop reactivo funcione de extremo a extremo:

1. **Suite QA con P0/P1/P2 definidos** — alguien tiene que etiquetar los 51 TCs actuales con su impacto de negocio. Trabajo manual, ~1h.
2. **ADK fidelidad suficiente** — actualmente 54-64%. El fix puede pasar en ADK pero fallar en CX. Mitigación: usar CX real como validación final antes del PR.
3. **Resolver el problema de memoria del Mac** — Qwen 14b OOM con contextos >18k. Opciones: Petal 1.1 reduce playbooks a <5k tokens (viable con 7b), o cloud para el runner.
4. **`fix_recipes.py`** — mapeo criterio → tipo de fix → prompt template para el LLM generador. Sin esto el LLM no sabe qué generar.

---

## 12. El sistema como framework A/B

La observación unificadora: **todo el sistema es un framework de comparación de versiones.**

```
Versión A (actual)  ←→  Versión B (fix del loop reactivo)
         comparadas contra
         51 TCs base + edge cases del adversarial (proactivo)
```

Los edge cases generados por el loop proactivo no son solo para encontrar bugs nuevos — son para hacer la comparación más discriminante. Un fix que resuelve TC-FRUSTRACION-01 pero rompe un edge case de cancelación a mitad de compra necesita saberlo antes de ir a CX.

### Gate de promoción

Para que Versión B promueva a CX:

| Condición | Resultado |
|---|---|
| B mejora todas las métricas sin regresiones | PR a CX ✅ |
| B mejora P1 pero regresiona algún edge case | Revisar el fix ⚠️ |
| B no mejora nada respecto a A | Hipótesis rechazada ✗ |

### Métrica de comparación

```
métrica_versión = Σ(pass_i × peso_severity_i) / Σ(peso_severity_i)

P0 (peso=3): si cualquier P0 falla → B nunca promueve independientemente de la métrica
P1 (peso=2): objetivo ≥ A  
P2 (peso=1): informativo — no bloquea pero se reporta
```

### Cómo conectan los tres loops

- **Reactivo** → genera la Versión B (el fix candidato)
- **Proactivo** → enriquece la suite con edge cases que hacen la comparación más discriminante
- **LLM judge** → etiqueta cada FAIL (routing / quality / slot) antes de entrar al pipeline, haciendo la correlación más precisa
- **A/B** → decide con criterio objetivo si B es mejor que A

Sin el proactivo, el A/B compara contra 51 TCs que pueden no cubrir los casos que el fix rompe. Con el proactivo, la comparación es robusta.

---

## 13. Principio central

> El sistema usa datos (correlación + BH score) para reducir el espacio de búsqueda antes de invocar al LLM. El modelo recibe una hipótesis ya formada y genera el contenido del parche — no razona sobre 60k tokens en bruto.
>
> La contextualización *es* el pipeline. La inteligencia está en el análisis previo, no en el modelo.
