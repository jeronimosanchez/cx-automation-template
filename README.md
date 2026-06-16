# cx-automation-template

Template reutilizable para automatizar el despliegue y validación de agentes conversacionales en Dialogflow CX (REST v3beta1).

**Qué hace:** convierte las definiciones de un agente CX (playbooks, intents, tools, ejemplos…) en ficheros YAML versionados en Git, y automatiza su despliegue idempotente a CX mediante CI/CD. Incluye una suite de QA end-to-end con reportes públicos y un harness de validación local con LLMs.

**Agente de referencia:** [Petal 1.1](https://dialogflow.cloud.google.com/cx/projects/floristeria-petal-digital/locations/europe-west1/agents/cea66b60-192d-4b5a-af10-28f8661032e0) — floristería online en español, construida como simulación de un proyecto de producción real. (1.0 congelado: `745375ba-ac7e-4eb8-b8a0-d742891f2aa4`)

---

## Qué incluye

| Componente | Descripción |
|---|---|
| **12 recursos CX cubiertos** | Playbooks, Examples, Tools, Agent Config, Flows, Pages, Intents, Entity Types, Webhooks, Generators, Environments, Versions |
| **Patrón idempotente** | `LIST → diff → PATCH/POST` en todos los recursos colectivos. Solo se envía lo que cambió |
| **432 tests unitarios** | Sin red, sin auth. Mock de `requests`. Cubren todos los módulos de `act/` |
| **51 TCs end-to-end** | Runner QA real contra el agente CX vía `detectIntent`. Reportes HTML publicados en GitHub Pages |
| **CI/CD con WIF** | GitHub Actions + Workload Identity Federation. Deploy automático al hacer push a `main` |
| **Harness de validación local** | Reconstrucción del agente con LLMs locales (Qwen/Ollama via ADK) para validar playbooks sin coste de API |
| **Linting estático** | Reglas estáticas sobre los YAMLs de playbooks (sintaxis, consistencia, cobertura de examples) |

> Adaptarlo a otro agente CX: cambia `definitions/agent.yaml`, no tocas código Python.

---

## Estructura

```
.
├── definitions/                    # YAML declarativos — fuente de verdad del agente
│   ├── agent.yaml                  #   config global + identificadores del agente
│   ├── playbooks/                  #   un YAML por Playbook
│   ├── examples/                   #   un YAML de examples por Playbook
│   ├── tools/                      #   wrapper YAML + spec OpenAPI adyacente
│   ├── flows/                      #   un YAML por Flow (NLU clásico)
│   ├── pages/                      #   un YAML por Page
│   ├── intents/                    #   un YAML por Intent
│   ├── entity_types/               #   un YAML por Entity Type
│   ├── webhooks/                   #   un YAML por Webhook
│   ├── generators/                 #   un YAML por Generator
│   ├── environments/               #   un YAML por Environment
│   └── versions/                   #   un YAML por Version (inmutables)
│
├── act/                            # Deploy: scripts de push/pull + utilidades
│   ├── push_*.py                   #   12 scripts — uno por recurso CX
│   ├── pull_*.py                   #   12 scripts — exporta CX → definitions/
│   ├── diff.py                     #   función pura: dict local vs remoto → patch payload
│   ├── validate_api.py             #   9 tests de conectividad y auth contra la API CX
│   └── tests/                      #   432 tests unitarios (pytest, sin red)
│
├── qap/                            # QA & validación
│   ├── petal_qa.py        #   51 TCs end-to-end contra CX — runner principal
│   ├── static_audit.py             #   linter estático: consistencia entre playbooks (9 criterios)
│   ├── surgical_run.py             #   corre TCs específicos y publica en GitHub Pages sin relanzar los 51
│   ├── regenerate_html.py          #   regenera el dashboard HTML desde JSONs sin llamar a CX
│   ├── rebuild_history.py          #   genera history.json para el histórico del dashboard
│   ├── list_fails.py               #   lista FAILs del último run con estado de análisis
│   └── adk_fidelity/               #   harness de validación local con LLMs
│       ├── petal_agent.py          #     reconstrucción plana del agente (Qwen via Ollama)
│       ├── petal_agent_multi.py    #     reconstrucción multi-agente (orquestador + sub-agentes)
│       ├── run_fidelity.py         #     runner: compara veredictos LLM local vs CX en vivo
│       ├── static_leak_gate.py            #     detecta directivas CX filtradas en outputs del LLM
│       └── judge.py                #     juez suave (Gemma) para dimensiones no deterministas
│
├── .github/workflows/
│   ├── deploy.yml                  #   push a main → deploy smart (solo recursos cambiados)
│   └── qa.yml                      #   QA end-to-end + publicación en GitHub Pages
│
├── docs/
│   ├── script_catalog.md           #   inventario de todos los scripts con función y cuándo usarlos
│   ├── setup-cicd.md               #   guía de configuración WIF + GitHub Variables
│   ├── setup-qa.md                 #   guía de configuración GitHub Pages
│   └── qa_analysis_process.md      #   proceso de análisis de FAILs
│
├── requirements.txt
└── .gitignore
```

---

## Setup local

### 1. Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dependencias runtime: `requests`, `google-auth`, `pyyaml`. El runner QA solo necesita `requests`.

### 2. gcloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
```

`<PROJECT_ID>` debe coincidir con `project:` en `definitions/agent.yaml`.

### 3. QA local (opcional)

```bash
# Listar los 51 TCs sin ejecutar
python qap/petal_qa.py --list

# Ejecutar todos (3 runs por TC, output en ~/petal-qa/)
python qap/petal_qa.py

# Subset
python qap/petal_qa.py --difficulty core
python qap/petal_qa.py --test TC-URGENCIA-01 --runs 1
```

Reportes del último run: [GitHub Pages](https://jeronimosanchez.github.io/cx-automation-template/qa/)

---

## Comandos

Todos los scripts de deploy soportan `--dry-run`. Recomendado antes de cualquier cambio real.

### Deploy — Playbooks

```bash
python act/push_playbooks.py --file=definitions/playbooks/handoff.yaml --dry-run
python act/push_playbooks.py --all --dry-run
python act/push_playbooks.py --all
```

### Deploy — Examples

```bash
python act/push_examples.py --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml --dry-run
python act/push_examples.py --all --dry-run
```

### Deploy — Tools

```bash
python act/push_tools.py --all --dry-run
python act/push_tools.py --all --only PetalDataTool --dry-run
```

### Deploy — Agent config

```bash
python act/push_agent_config.py --dry-run
```

### Deploy — Environments y Versions

```bash
python act/push_environments.py --all --dry-run

# Versions son inmutables — solo --create o --list
python act/push_versions.py --list
python act/push_versions.py --create --description "v1.0.0" --dry-run
```

### Deploy — NLU clásico (Flow-based)

```bash
python act/push_flows.py --all --dry-run
python act/push_pages.py --all --dry-run
python act/push_intents.py --all --dry-run
python act/push_entity_types.py --all --dry-run
python act/push_webhooks.py --all --dry-run
python act/push_generators.py --all --dry-run
```

> Los módulos NLU clásico están validados con tests unitarios y `--dry-run` contra Petal.
> El flujo completo `created/updated/unchanged` con cambios reales requiere un agente Flow-based.

### Tests unitarios

```bash
pytest act/tests/ -q          # objetivo: <10s
pytest act/tests/ -v          # verbose
```

### QA — runner end-to-end

```bash
python qap/petal_qa.py --list
python qap/petal_qa.py
python qap/petal_qa.py --difficulty core     # solo regresión
python qap/petal_qa.py --test TC-URGENCIA-01 --runs 1
```

### QA — run quirúrgico (TCs específicos sin relanzar los 51)

```bash
# Paso 1 — correr solo los TCs que necesitas
python qap/surgical_run.py --test TC-URGENCIA-01,TC-URGENCIA-03 --runs 2

# Paso 2 — publicar resultado en GitHub Pages (merge con el último run completo)
python qap/surgical_run.py --publish
python qap/surgical_run.py --publish --dry-run   # previsualiza sin hacer push
```

### Validar conectividad y auth

```bash
python act/validate_api.py
python act/validate_api.py --quick
```

---

## Dependencias externas

El agente Petal llama a **`petal-sheet-api`** (Cloud Run, `europe-west1`) para consultar inventario, perfiles y pedidos desde Google Sheets. Es un servicio separado — su código vive en [`jeronimosanchez/petal-sheet-api`](https://github.com/jeronimosanchez/petal-sheet-api) (privado).

**Estado y deuda conocida:**
- **Sin autenticación** — el endpoint es público. Aceptable para un PoC de demo; en producción real requeriría IAM o API key. Pendiente de cerrar.
- **Regla de relajación de inventario (deuda de arquitectura)** — la lógica de fallback cuando no hay stock (`color_relajado` → `producto_y_color_relajados` → `sin_filtros_opcionales`) vive en el backend en lugar de en el playbook. Consecuencia: no es testeable por la suite QA ni versionada con el agente. Previsto moverla al playbook en Petal 1.1.

---

## Decisiones de diseño

Decisiones tomadas tras validación directa contra la API CX. No cambiar sin verificar en producción.

- **Auth:** `gcloud auth print-access-token` en todos los scripts. `google.auth.default()` no se usa.
- **Header obligatorio:** `x-goog-user-project: <project>` en todas las llamadas a la API.
- **Idempotencia:** PATCH parcial con `updateMask`. La función `act/diff.py` es pura (sin efectos secundarios) y calcula exactamente qué campos cambiaron.
- **Playbooks — Full Update:** `PATCH` con `updateMask` falla en `europe-west1` para Playbooks (bug conocido del backend). Workaround validado: `GET` completo → modificar → `PATCH` sin `updateMask`.
- **Versions — LRO polling:** `POST /versions` devuelve una Operation, no la Version. Hay que polear `GET /operations/{id}` hasta `done=true`.
- **Tests sin red:** todos los tests de `act/tests/` usan mock de `requests`. Si un test necesita red, va en `qap/`.
- **WIF en CI:** Workload Identity Federation, sin Service Account key files.
- **Concurrencia:** `concurrency: 1` en los workflows de GitHub Actions. La API CX no tiene optimistic locking.
- **Agnosticismo:** todas las constantes del agente (project, location, IDs) viven en `definitions/agent.yaml`. Nada hardcodeado en Python.

---

## Schemas YAML

### Playbook

```yaml
displayName: str
goal: str
instruction:
  steps:
    - text: str
inputParameterDefinitions: [...]
outputParameterDefinitions: [...]
referencedTools: [...]
playbookType: PLAYBOOK_TYPE_TASK | ROUTINE
```

### Example

```yaml
displayName: str
actions:
  - userUtterance: { text: str }
  - agentUtterance: { text: str }
  - toolUse:
      action: consultarDatos       # operationId del Tool
      inputActionParameters:
        recurso: inventario
      outputActionParameters:
        '200':                     # un solo top-level key — la API rechaza con 400 si hay más
          productos: [...]
playbookOutput:
  actionParameters: {}
```

### Tool

```yaml
displayName: PetalDataTool
description: ...
toolType: CUSTOMIZED_TOOL
openapi_spec_file: petaldatatool_openapi.yaml   # se lee como texto crudo — evita falsos diffs
```

---

## CI/CD

Dos workflows GitHub Actions con autenticación via Workload Identity Federation:

| Workflow | Trigger | Qué hace |
|---|---|---|
| `deploy.yml` | push a `main` | Detecta qué carpetas de `definitions/` cambiaron y corre solo los `push_*.py` afectados, en orden topológico. Crea Version snapshot al final. |
| `qa.yml` | `workflow_dispatch` + PR a `main` | 51 TCs end-to-end contra Default Environment. Publica HTML + TXT en GitHub Pages. No bloquea merge. |

Configuración inicial: ver [`docs/setup-cicd.md`](docs/setup-cicd.md) (~30-45 min).

---

## Referencia

- [Inventario de scripts](docs/script_catalog.md) — todos los `.py` y `.sh` con función y cuándo usarlos
- [Proceso de análisis QA](docs/qa_analysis_process.md) — cómo interpretar y analizar FAILs
- [Configuración CI/CD](docs/setup-cicd.md) — WIF + GitHub Variables
- [Configuración QA](docs/setup-qa.md) — GitHub Pages + notificaciones
- [Reportes QA en vivo](https://jeronimosanchez.github.io/cx-automation-template/qa/)
