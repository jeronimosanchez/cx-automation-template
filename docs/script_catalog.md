# Catálogo de scripts — cx-automation-template

Versión: v1.0 | Fecha: 2026-06-13

Inventario de los scripts `.py` de **ACT** (este repo, despliegue a Dialogflow CX).
Excluye tests unitarios (`act/tests/`) y dependencias de terceros (`node_modules/`, `.venv*/`).
Los scripts de QAP (validación / QA) viven en [`agent-validation-engine`](https://github.com/jeronimosanchez/agent-validation-engine) — ver sección final.

**Cómo mantenerlo:** actualizar esta tabla al crear o eliminar un script. Si añades una
regla nueva a un linter, actualiza la columna "Qué hace".

---

## ACT — Deploy y Pull (24 scripts)

Patrón común: todos los `push_*.py` siguen `LIST → diff → PATCH/POST solo lo que cambió`
(idempotencia). Todos los `pull_*.py` llaman a la API y guardan en `definitions/`.

| Script | Operación | Recurso CX | Notas |
|---|---|---|---|
| `act/push_playbooks.py` | Push | Playbooks | Full Update obligatorio (bug `europe-west1` con `updateMask`) |
| `act/push_examples.py` | Push | Examples | Acepta `--all` |
| `act/push_tools.py` | Push | Tools | |
| `act/push_intents.py` | Push | Intents | |
| `act/push_entity_types.py` | Push | Entity Types | |
| `act/push_flows.py` | Push | Flows | |
| `act/push_pages.py` | Push | Pages | |
| `act/push_generators.py` | Push | Generators | |
| `act/push_agent_config.py` | Push | Agent Config | |
| `act/push_environments.py` | Push | Environments | |
| `act/push_versions.py` | Push | Versions | LRO polling obligatorio (`GET /operations/{id}` hasta `done=true`) |
| `act/push_webhooks.py` | Push | Webhooks | |
| `act/pull_playbooks.py` | Pull | Playbooks | |
| `act/pull_examples.py` | Pull | Examples | |
| `act/pull_tools.py` | Pull | Tools | |
| `act/pull_intents.py` | Pull | Intents | |
| `act/pull_entity_types.py` | Pull | Entity Types | |
| `act/pull_flows.py` | Pull | Flows | |
| `act/pull_pages.py` | Pull | Pages | |
| `act/pull_generators.py` | Pull | Generators | |
| `act/pull_agent_config.py` | Pull | Agent Config | |
| `act/pull_environments.py` | Pull | Environments | |
| `act/pull_versions.py` | Pull | Versions | |
| `act/pull_webhooks.py` | Pull | Webhooks | |

---

## ACT — Utilidades (4 scripts)

| Script | Cuándo usarlo | Qué hace |
|---|---|---|
| `act/diff.py` | Librería — no se ejecuta directamente | Función pura `diff_resource(local, remote)` sin efectos secundarios. Compara dos dicts y devuelve `DiffResult` con `needs_update`, `update_mask` y `patch_payload` listos para PATCH. La usan todos los `push_*.py`. |
| `act/audit_examples.py` | Migración puntual | Detecta examples que usan el `operationId` legacy `petaldatatool` en lugar del actual `consultarDatos`. Solo lectura — no modifica nada. |
| `act/validate_api.py` | Antes de un sprint o tras cambios de IAM | 9 tests de conectividad y auth contra la API CX: verifica token, headers, LIST, GET, PATCH, etc. |
| `act/validate_api_v2.py` | Diagnóstico avanzado | 4 tests adicionales: PATCH con `updateMask`, `displayName` duplicado, tamaño máximo de Example, paginación profunda. Complementa `validate_api.py`. |

---

## ACT — Tests unitarios (26 archivos)

Ubicación: `act/tests/`. Nomenclatura: `test_push_<recurso>.py` / `test_pull_<recurso>.py`.

Cómo correrlos: `python -m pytest act/tests/ -q` (ver CLAUDE.md §5).

---

## Scripts QAP — viven en otro repo

Los scripts de QA, linting estático, harness de fidelidad ADK y publicación de
reportes **no viven en este repo**. Tienen su propio catálogo y README en
[`agent-validation-engine`](https://github.com/jeronimosanchez/agent-validation-engine)
(carpeta `qap/`).

ACT (este repo) solo se ocupa del **despliegue de artefactos a Dialogflow CX**.
La validación / QA es responsabilidad de la línea QAP.

