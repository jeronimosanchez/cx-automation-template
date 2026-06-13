# Benchmark de fidelidad — cribador ADK local

Registro de versiones de la reconstrucción + su fidelidad vs CX. Cada fila = un config
(fingerprint) + su número de acuerdo. **Fingerprint incluye HARDWARE/backend** — Mac y Kaggle
son instrumentos DISTINTOS (la reproducibilidad cross-hardware es físicamente imposible).

⚠️ **Los números 88%/82% están CONTAMINADOS por fuga de scaffolding** (ver bitácora) — no son
fidelidad limpia hasta aplicar el veredicto de 3 estados (PASS/FAIL/INVALID). Baseline v3 limpio = pendiente.

| Ver | Fecha | Cambios vs anterior | Fingerprint (config) | Acuerdo | Estado |
|---|---|---|---|---|---|
| **v0** | 11-jun | plano, los 6 playbooks inline | Qwen14b-q4 · ctx 4096 · temp~0.8 · Mac/Metal | 54% | ❌ DESCARTADO — confound: ctx 4096 < prompt ~32k → truncación |
| **v1** | 12-jun | + ctx 32k + temp=0 + flash + params N1 | Qwen14b-q4 · ctx 32768 · temp0 seed42 · flash · Mac/Metal | — | bundle de config (no aislado) |
| **v2-Mac** | 12-jun | + multi-agente | Qwen14b-q4 · multi · ctx32k · temp0 · flash · **Mac/Metal** · ollama 0.30.7 · digest 2049f5674b1e | **88%** | ⚠️ pp43/pf6/fp0/ff2 · sesgo pesimista (6 FA/0 FN) · FAIL-recall 2/2 · CONTAMINADO por fuga |
| **v2-Kaggle** | 12-jun | misma config, otro hardware | idem · **Kaggle P100/CUDA (cuda_v12 fallback)** · digest IDÉNTICO | **82%** | ⚠️ pp40/pf9/fp0/ff2 · NO reproduce Mac (9 TCs voltean) · instrumento DISTINTO |
| v3 | — | + veredicto 3-estados + sanear prompts + routing tool-call | Mac (canónico) | — | 🔜 el 1er número LIMPIO (sin fuga) |

## Estado óptimo actual
**v2-Mac**, pero contaminado. El siguiente paso es **v3 (descontaminado)** SOLO en Mac. Para correr:
```
./start_ollama.sh                                   # flash + ctx 32k + keep_alive
ADK_RECON=multi python run_fidelity.py              # multi-agente (v2)
```

## Cómo se lee el impacto
El DELTA de "Acuerdo" entre versiones del MISMO entorno (Mac) = el impacto del cambio. NUNCA comparar
Mac vs Kaggle (instrumentos distintos). Cada fila lleva su fingerprint completo, **incluido hardware/backend**.

## Bitácora de cambios

- **11-jun** — Reconstrucción plana (6 playbooks + webhook real). Primer run → 54%.
- **12-jun — CONFOUND 1 (truncación)** — el 54% estaba envenenado: ctx 4096 < prompt ~32k → playbooks truncados. v0 descartado.
- **12-jun — v1/v2** — config arreglada (ctx32k+temp0+flash+params) + multi-agente → 88% en Mac.
- **12-jun — engine check en Kaggle** — réplica en P100/CUDA dio **82%**, NO reproduce el Mac. Digest del modelo IDÉNTICO (2049f5674b1e) → **drift descartado**; la divergencia es **backend** (Metal vs CUDA, coma flotante no asociativa). 9 TCs voltean en ambas direcciones. **CONCLUSIÓN: reproducibilidad cross-hardware imposible → pinear Mac como canónico.**
- **12-jun — CONFOUND 2 (fuga de scaffolding)** — ambas reconstrucciones vomitan andamiaje interno (`$var`, `${PLAYBOOK}`, `sourceMapping`, `PASO N`, JSON routing) al output; el regex lo PREMIA por coincidencia → el 88%/82% mide ruido en las dos direcciones. Causa raíz CONFIRMADA: los artefactos están literalmente en los prompts (88 `$var=`, 92 `PASO N`). Fix: veredicto 3-estados (fuga=INVALID, no FAIL) + lexicón anti-fuga autogenerado + sanear prompts (ADK-29) + routing como tool-call.
- **12-jun — P1+P2 IMPLEMENTADO (`static_leak_gate.py`)** — veredicto 3-estados (OK/INVALID, vía pre-gate de patrones CX-DSL + degeneración) + lexicón autogenerado del prompt (`build_lexicon`). **RETRO sobre los transcripts Kaggle-82 (gratis):** 11/51 = **22% de los runs FUGABAN** (cota INFERIOR — el agente está truncado a 300 chars). De las 9 falsas alarmas, **3 eran fuga** (no desacuerdo real); de los "aciertos" PASS/PASS, **8 eran falsos aciertos** (regex coincidió pese a la fuga). Acuerdo sobre VÁLIDAS = 34/40 = **85%**. **Precisión del lexicón verificada: 0 falsos positivos** sobre los 11 (cada uno = fuga genuina: `sourceMapping:`, `$grupo_intent='G5'`, `${PLAYBOOK:Orchestrator}`, instrucciones de andamiaje). El `22% INVALID` = "salud del harness", la métrica que P3 (sanear, ADK-29) tiene que subir.

### Nota metodológica
3 envenenamientos del instrumento ya cazados (ground truth caduco → truncación → fuga+regex). El patrón ES la tesis del método: **el harness se audita ANTES de creerle un número.** Fingerprint + preflight + veredicto 3-estados = piezas de producto, no parches.
