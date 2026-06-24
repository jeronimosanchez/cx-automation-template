# ADK Multi-Agente — Benchmarks 1.0 vs 1.1

Versión: v1.0 | Fecha: 2026-06-23

> Cómo ejecutar ADK (fidelidad local con Qwen 14B) contra agentes 1.0 y 1.1 en paralelo y comparar benchmarks.

---

## Arquitectura

**ADK (Agent Development Kit) localmente:**
- Levanta Qwen 14B localmente (MLX o Ollama)
- Corre TCs contra agentes CX reales (no simulados)
- Genera benchmarks (% acuerdo, gaps, patrones)
- Soporta **dos agentes en paralelo**: 1.0 y 1.1

| Aspecto | 1.0 | 1.1 |
|---|---|---|
| Agent ID | `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` | `cea66b60-192d-4b5a-af10-28f8661032e0` |
| TCs | `qap/tc_1_0.yaml` (51 TCs) | `qap/tc_1_1.yaml` (51 TCs, por ahora) |
| Benchmark salida | `fidelity_1.0_<timestamp>.json` | `fidelity_1.1_<timestamp>.json` |
| Backend | `petal-sheet-api` (Sheet 1.0) | `petal-sheet-api-v11` (Sheet 1.1) |

---

## Requisitos previos

```bash
# 1. Qwen 14B ejecutándose localmente (MLX o Ollama)
ollama pull qwen2.5:14b
ollama serve  # en otra terminal, port 11434

# 2. ADK disponible
cd ~/agent-validation-engine

# 3. Credenciales GCP (para llamar a CX)
gcloud auth application-default login
```

---

## Uso — CLI

### Contra 1.0 (baseline)
```bash
python qap/petal_agent/run_fidelity.py --agent 1.0 --runs 3
```
Salida: `reports/fidelity_1.0_20260623_143022.json`

### Contra 1.1 (propuesta)
```bash
python qap/petal_agent/run_fidelity.py --agent 1.1 --runs 3
```
Salida: `reports/fidelity_1.1_20260623_143022.json`

### Benchmark comparativo
```bash
python qap/petal_agent/run_fidelity.py --agent 1.0 --runs 3 && \
python qap/petal_agent/run_fidelity.py --agent 1.1 --runs 3 && \
python qap/petal_agent/compare_fidelity.py \
  --file1 reports/fidelity_1.0_latest.json \
  --file2 reports/fidelity_1.1_latest.json
```

---

## Resultados esperados

### Formato del reporte `fidelity_1.X_<ts>.json`

```json
{
  "agent": "1.0",
  "model": "qwen2.5:14b",
  "timestamp": "2026-06-23T14:30:22",
  "total_tcs": 51,
  "runs_per_tc": 3,
  "summary": {
    "pass_rate": "88%",
    "agreement_with_judge": "82%",
    "major_gaps": ["TC-C31", "TC-FRUSTRACION-01"],
    "confidence": "high"
  },
  "tcs": [
    {
      "id": "TC-C29",
      "runs": 3,
      "pass": 3,
      "verdict": "PASS",
      "confidence": "high"
    },
    ...
  ]
}
```

### Comparativa
```
┌─────────────────────┬──────────┬──────────┬─────────┐
│ Métrica             │ 1.0      │ 1.1      │ Mejora  │
├─────────────────────┼──────────┼──────────┼─────────┤
│ Pass rate           │ 88%      │ 92%      │ +4pp    │
│ Agreement w/ judge  │ 82%      │ 86%      │ +4pp    │
│ OOM incidents       │ 2/51     │ 0/51     │ -100%   │
│ Avg latency         │ 4.2s     │ 3.8s     │ -9.5%   │
└─────────────────────┴──────────┴──────────┴─────────┘
```

---

## Integración en el workflow de refactorización

**Fase 4 — Validación final:**

```
1. QA contra 1.0 y 1.1 (46 TCs cada uno)
   └─ Verificar 0 regressions

2. ADK benchmark 1.0 vs 1.1
   ├─ `run_fidelity.py --agent 1.0 --runs 3`
   ├─ `run_fidelity.py --agent 1.1 --runs 3`
   └─ `compare_fidelity.py` → reporte comparativo

3. Decisión
   ├─ Si 1.1 >= 1.0 en métricas → PROMOTE a 1.0
   └─ Si 1.1 < 1.0 → ROLLBACK refactor
```

---

## Notas de implementación

### Actualización pendiente a `run_fidelity.py`:

```python
# Línea ~30: agregar argument parser
parser.add_argument('--agent', default='1.0', choices=['1.0', '1.1'])
args = parser.parse_args()

# Línea ~50: resolver AGENT_ID
AGENTS = {
    "1.0": "745375ba-ac7e-4eb8-b8a0-d742891f2aa4",
    "1.1": "cea66b60-192d-4b5a-af10-28f8661032e0",
}
AGENT_ID = AGENTS[args.agent]

# Línea ~200 (en generate_report): incluir sufijo agent
report_file = f"reports/fidelity_{args.agent}_{timestamp}.json"

# TCs: cargar según agent
tc_file = f"qap/tc_{args.agent}.yaml"  # tc_1_0.yaml o tc_1_1.yaml
```

### Script nuevo: `compare_fidelity.py`

Leer dos reportes `fidelity_1.0_*.json` y `fidelity_1.1_*.json`, generar tabla comparativa.

---

## Estado

- [ ] `run_fidelity.py` actualizado para aceptar `--agent`
- [ ] Reportes guardan con sufijo `_1.0_` y `_1.1_`
- [ ] `compare_fidelity.py` creado
- [ ] Test: 3 TCs contra 1.0, 3 contra 1.1, verificar archivos separados
- [ ] Integración en Fase 4 del workflow

---

## Troubleshooting

| Problema | Causa | Solución |
|---|---|---|
| "AGENT_ID not found" | `--agent` pasado con valor inválido | Usar `1.0` o `1.1` |
| "tc_1_X.yaml not found" | Archivos no creados | Ver checklist Fase 0.2 |
| "OOM en Qwen" | Playbooks aún > 8k tokens | Esperar Fase 2 (refactor) |
| "Reportes no separados" | Suffix no implementado | Verificar línea 200 de run_fidelity.py |
