# Respaldo del sector (2026) — Sistema A

**Qué es:** anclaje del Sistema A a los métodos establecidos del sector (2025-2026). El diseño no es un invento propio — es una **aplicación** de prácticas reconocidas, escalada a un agente CX y optimizada en coste.

## DIAGNOSTICA se apoya en

| Nuestra pieza | Método del sector |
|---|---|
| Hipótesis guiada por marca + evidencia acotada | **LLM-as-judge guiado por taxonomía** — el método dominante en producción |
| Las familias / niveles de fallo | **Taxonomías de error conversacional**: Higashinaka (DBDC), **Möller (niveles)**, **RCOF**, **MAST** (NeurIPS 2025) |
| Diferencial ranqueado 2-4 (local→estructural) | **Diagnóstico diferencial** (medicina) + abducción (*inference to the best explanation*) |
| Trace → atribución por elemento | **Diagnóstico per-span con cadena causal** |
| Condición de falsación | **Falsacionismo** (Popper) — una hipótesis vale si es refutable |
| Agrupación a escala (espectro) | **Spectrum-based fault localization** |

**El dato que lo valida empíricamente:** un LLM adivinando la causa sola acierta el **8-13%**; **con taxonomía guía, 24-33%** (3× mejor). Dar al modelo evidencia acotada y marcada **no es eficiencia — es la condición para que acierte.**

## REPARA se apoya en

| Nuestra pieza | Método del sector |
|---|---|
| Generar parches → cribar → refinar | **APR conversacional/agéntico** (*generate-and-validate*) |
| Varios parches diversos (multinivel) | **Guided diversity** (razonamiento adversarial + multi-agente) |
| Edge cases en la criba (anti-overfit) | defensa contra **patch overfitting** (probar variaciones, no solo el TC) |
| Criba $0 en ADK antes de CX | **Cost-latency optimization con presupuesto adaptativo** |
| El bucle entero | **RepairAgent** / **AgentDebug** (+26% éxito) |

**Dato de anclaje:** los sistemas APR agénticos hacen **~11,8 iteraciones de feedback por fix** de media. El bucle generar→validar→refinar es lo normal, no la excepción.

## VALIDA + aprendizaje se apoyan en

| Nuestra pieza | Método del sector |
|---|---|
| Ranking dinámico (fix falla → sube estructural) | **Learning from failures** |
| Recetas de fix reutilizables (Sistema B) | **Memoria gobernada de fixes validados** (*Grove*): conocimiento validado por test, consciente de aplicabilidad |

## La idea en una frase

El Sistema A es **LLM-as-judge guiado por taxonomía** (diagnóstico) + **generate-and-validate APR** (reparación) + **memoria gobernada de fixes** (aprendizaje) — los tres paradigmas vigentes del sector en 2026, ensamblados en un ciclo agnóstico de cliente y plataforma.

## Fuentes

- [Why Do Multi-Agent LLM Systems Fail? (MAST)](https://openreview.net/pdf?id=wM521FqPvI)
- [Diagnosing Failure Root Causes — taxonomía sube RCA 10%→30%](https://arxiv.org/pdf/2509.23735)
- [Mind the Goal — evaluación goal-oriented (RCOF)](https://arxiv.org/pdf/2510.03696)
- [Integrated taxonomy of errors in chat-oriented dialogue systems (Higashinaka)](https://www.researchgate.net/publication/375931216_Integrated_taxonomy_of_errors_in_chat-oriented_dialogue_systems)
- [A Survey of LLM-based Automated Program Repair](https://arxiv.org/html/2506.23749v1)
- [Where LLM Agents Fail and How They Can Learn From Failures](https://arxiv.org/pdf/2509.25370)
