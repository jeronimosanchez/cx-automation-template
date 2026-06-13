# Catálogo de scripts — cx-automation-template

Versión: v1.0 | Fecha: 2026-06-13

Inventario de todos los scripts `.py` del proyecto. Excluye tests unitarios (`act/tests/`),
dependencias de terceros (`node_modules/`, `.venv*/`) y el archivo archivado (`qap/_archive/`).

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

## QAP — Suite QA (1 script)

| Script | Cuándo usarlo | Qué hace |
|---|---|---|
| `qap/test_qa_playbooks.py` | CI/CD automático (`qa.yml`) o manual con permiso | Suite principal: 51 TCs contra el agente CX en vivo. Genera reports HTML + JSON en `reports/` y publica en GitHub Pages. No modificar sin actualizar `qa.yml`. |

---

## QAP — Linting estático L0 (2 scripts — sin integrar en CI/CD)

Estos scripts analizan el YAML de los playbooks **sin ejecutar el agente**. Son independientes
entre sí y actualmente ninguno está en el pipeline de `deploy.yml`.

| Script | Cuándo usarlo | Reglas implementadas |
|---|---|---|
| `qap/lint_playbook.py` | Manual sobre un archivo `.txt` de playbook | **R1** — acentos diacríticos en el texto · **R2** — referencias a playbooks con backticks en lugar de `${PLAYBOOK:Name}` · **R3** — uso de `$session_id` |
| `qap/pb_audit.py` | Manual sobre el conjunto de playbooks | 9 criterios de consistencia inter-playbook: parámetros declarados vs. referenciados, naming, solapamiento de responsabilidades, etc. Baseline actual: 0✅ / 27⚠️ / 3❌. |

> **Deuda técnica:** `qap/adk_fidelity/leak_gate.py` también implementa reglas L0 (fuga de
> directivas CX en texto libre) pero vive dentro del harness ADK. Los tres forman la base
> de un linter unificado pendiente (`lint_all.py`).

---

## QAP — Utilidades QA (4 scripts)

| Script | Cuándo usarlo | Qué hace |
|---|---|---|
| `qap/surgical_run.py` | Cuando quieres re-correr 1-N TCs específicos sin pagar los 51 | **Paso 1** — corre los TCs indicados contra CX en paralelo y guarda JSONs en local. **Paso 2** (`--publish`) — mergea los resultados con el último run completo de gh-pages y publica como run nuevo. El resultado en gh-pages es indistinguible de un run completo. |
| `qap/list_fails.py` | Para saber qué FAILs necesitan análisis manual | Lista los FAILs del último run (local o gh-pages) con su estado: si ya existe `.md` de análisis en `qap/tc_analysis/` o está pendiente. |
| `qap/regenerate_html.py` | Para iterar análisis sin gastar API calls | Regenera el HTML del dashboard desde JSONs locales o de gh-pages, incorporando los MDs de `qap/tc_analysis/`. Flujo: editar MD → `regenerate_html.py` → ver resultado en `/tmp/`. |
| `qap/rebuild_history.py` | CI/CD (`qa.yml`) — raramente manual | Genera `qa/history.json` para la vista Histórico del dashboard. Sustituye ~25 llamadas a la GitHub API por 1 fetch a un JSON estático. |

---

## QAP/ADK — Harness de fidelidad (7 scripts)

Sistema de validación local del agente: reconstruye Petal con LLMs locales (Qwen via Ollama)
y mide cuántos de los 51 TCs coinciden con los veredictos de CX en vivo.

| Script | Cuándo usarlo | Qué hace |
|---|---|---|
| `qap/adk_fidelity/petal_agent.py` | Lo carga `run_fidelity.py` | Reconstrucción plana de Petal: un único `LlmAgent` con todos los playbooks en el prompt. Usa `LiteLlm(model=ADK_MODEL, temperature=0.0, seed=42)`. |
| `qap/adk_fidelity/petal_agent_multi.py` | Lo carga `run_fidelity.py` con `ADK_RECON=multi` | Reconstrucción multi-agente: orquestador + 5 sub-agentes, cada uno con un único playbook. |
| `qap/adk_fidelity/run_fidelity.py` | Arrancar un run de fidelidad | Runner principal: corre los 51 TCs contra la reconstrucción ADK y compara veredictos con `FAILS_ACTUALES` (ground truth CX). Genera `fidelity_result.json`. |
| `qap/adk_fidelity/leak_gate.py` | Lo usa `run_fidelity.py` automáticamente | Pre-gate anti-fuga: detecta directivas CX ejecutables (`$var=`, `PASO N`, `${PLAYBOOK:X}`, `sourceMapping`) en los outputs del LLM. Un output con fuga → veredicto `INVALID`, no cuenta en la métrica de acuerdo. |
| `qap/adk_fidelity/judge.py` | Pendiente de integrar en `run_fidelity.py` | Skeleton del juez suave: usa Gemma-27B vía Ollama para evaluar 6 dimensiones no-deterministas (tono, palabras clave, confirmación, etc.). No está conectado al runner aún. |
| `qap/adk_fidelity/smoke_test.py` | Antes de un run completo si algo falla en arranque | Smoke test end-to-end: 1 turno con ADK + webhook de inventario + Gemini. Verifica que la cadena completa funciona antes de invertir tiempo en los 51 TCs. |
| `qap/adk_fidelity/kaggle/_gen_notebook.py` | Al actualizar el harness para re-empaquetarlo | Genera `kaggle_fidelity.ipynb` a partir de las celdas definidas en el propio script. Correr después de cualquier cambio al harness que vaya a Kaggle. |

---

## Scripts sin integrar en CI/CD (deuda técnica)

| Script | Estado | Acción pendiente |
|---|---|---|
| `qap/lint_playbook.py` | Activo — huérfano | Integrar en `deploy.yml` como paso pre-deploy |
| `qap/pb_audit.py` | Activo — manual | Integrar en `deploy.yml` como paso pre-deploy |
| `qap/adk_fidelity/judge.py` | Skeleton — incompleto | Conectar a `run_fidelity.py` cuando Gemma-27B esté disponible localmente |
| `act/audit_examples.py` | Activo — uso puntual | Archivar o convertir en test si la migración está completa |
| `act/validate_api_v2.py` | Activo — solapado con v1 | Valorar unificar con `validate_api.py` o eliminar |
