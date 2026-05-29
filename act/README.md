# ACT — Despliegue de artefactos a Dialogflow CX

Línea **ACT** del sistema de Automatización CD. Despliega los artefactos de
`definitions/` al agente conversacional Petal en Dialogflow CX.

## Contenido

| Grupo | Qué hace |
|---|---|
| `push_*.py` (×12) | Upsert idempotente de cada recurso a CX (`LIST → diff → PATCH/POST`) |
| `pull_*.py` (×12) | Export de cada recurso desde CX a YAML |
| `diff.py` | Función pura de diff (recurso local vs remoto). Sin red, sin side effects |
| `validate_api.py` | Valida capacidades de la API CX |
| `audit_examples.py` | Auditoría de Examples legacy |
| `tests/` | Tests unitarios pytest (sin red, mock de `requests`) |

## Uso

```bash
# Tests
python -m pytest act/tests/ -q

# Dry-run (previsualizar, NO despliega)
python act/push_playbooks.py --all --dry-run
```

El despliegue real lo ejecuta `deploy.yml` tras push a `main`. Los scripts no se
corren directamente contra producción fuera del CI/CD.

## Reglas no negociables

Ver `CLAUDE.md` §3 (auth vía `gcloud`, headers obligatorios, idempotencia, LRO
polling en versions, Full Update en `europe-west1`).
