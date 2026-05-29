# cx-automation-template

Template reutilizable para automatizar agentes conversacionales en Dialogflow CX (REST v3beta1).

Provee:
- Definiciones declarativas YAML para los 11 recursos top-level de CX:
  - **Modernos (Sprint 2)**: Examples, Playbooks, Tools, Agent config.
  - **NLU clasico Flow-based (Sprint 3)**: Flows, Pages, Intents, Entity Types, Webhooks, Generators.
  - **Deploy / lifecycle (Sprint 4)**: Environments, Versions.
- Scripts agnosticos al agente con flujo idempotente `LIST -> diff -> PATCH/POST` (`GET -> diff -> PATCH` para el agente; `POST-only` para Versions inmutables).
- Suite de tests unitarios (`pytest`) sin red — 432 tests al cierre de Sprint 6.
- **QA con runner real (Sprint 6)**: `qap/test_qa_playbooks.py` ejecuta 29 TCs end-to-end contra el Default Environment de CX vía `detectIntent`, con publicación de reportes HTML + TXT en GitHub Pages.
- Validacion de capacidades de la API (`act/validate_api.py`) — usado para descubrir limites / comportamientos antes de codificarlos.
- **CI/CD GitHub Actions (Sprint 4)** con WIF: deploy automatico tras push a `main`, QA en `workflow_dispatch` + PRs (Sprint 6).

Pensado para varios agentes CX. Cambias `definitions/agent.yaml`, no tocas codigo.

**Limitacion validacion Sprint 3**: Petal (el agente de referencia) es Playbook-only. Los modulos NLU clasico (`push_flows`, `push_pages`, `push_intents`, `push_entity_types`, `push_webhooks`, `push_generators`) estan validados con tests unitarios + smoke tests `--dry-run` con fixtures sinteticos + LIST contra Petal real (sin errores). El camino completo `created/updated/unchanged` con cambios reales queda diferido hasta que aparezca un proyecto Flow-based real (ej. ECH).

---

## Estructura

```
.
├── definitions/                    # YAML declarativos — fuente de verdad
│   ├── agent.yaml                  #   contexto + agent_definition (config global)
│   ├── examples/                   #   un YAML por Playbook (registro_task.yaml, ...)
│   ├── playbooks/                  #   un YAML por Playbook (handoff.yaml, ...)
│   ├── tools/                      #   wrapper YAML + OpenAPI raw adyacente
│   ├── flows/                      #   un YAML por Flow (Sprint 3)
│   ├── pages/                      #   un YAML por Page (parent_flow_displayName, Sprint 3)
│   ├── intents/                    #   un YAML por Intent (Sprint 3)
│   ├── entity_types/               #   un YAML por Entity Type (Sprint 3)
│   ├── webhooks/                   #   un YAML por Webhook (Sprint 3)
│   ├── generators/                 #   un YAML por Generator (Sprint 3)
│   ├── environments/               #   un YAML por Environment (Sprint 4)
│   └── versions/                   #   un YAML por Version (immutable, Sprint 4)
├── act/                            # Scripts Python ejecutables
│   ├── diff.py                     #   funcion pura (recurso local vs remoto)
│   ├── push_examples.py            #   upsert Examples desde YAML
│   ├── push_playbooks.py           #   upsert Playbooks desde YAML
│   ├── push_tools.py               #   upsert Tools desde YAML
│   ├── push_agent_config.py        #   sync config global del agente (GET → diff → PATCH)
│   ├── push_flows.py               #   upsert Flows desde YAML (Sprint 3)
│   ├── push_pages.py               #   upsert Pages anidadas bajo Flow (Sprint 3)
│   ├── push_intents.py             #   upsert Intents desde YAML (Sprint 3)
│   ├── push_entity_types.py        #   upsert Entity Types desde YAML (Sprint 3)
│   ├── push_webhooks.py            #   upsert Webhooks desde YAML (Sprint 3)
│   ├── push_generators.py          #   upsert Generators desde YAML (Sprint 3)
│   ├── push_environments.py        #   upsert Environments desde YAML (Sprint 4)
│   ├── push_versions.py            #   --create / --list de Versions immutables (Sprint 4)
│   ├── validate_api.py             #   valida capacidades de la API CX (9 tests)
│   ├── audit_examples.py           #   auditoria de Examples legacy
│   └── tests/                      #   tests unitarios pytest (sin red)
│       ├── test_diff.py
│       ├── test_pull_*.py          #   un test por recurso (pull, x12)
│       └── test_push_*.py          #   un test por recurso (push, x12)
├── .github/workflows/              # CI/CD (Sprint 4 + 6)
│   ├── deploy.yml                  #   push a main → deploy + Version snapshot
│   └── qa.yml                      #   workflow_dispatch + push feature/** + PR → 29 TCs + GitHub Pages (Sprint 6)
├── qap/                            # Linea QAP — runner QA + reporting (Sprint 6)
│   ├── test_qa_playbooks.py        #   29 TCs end-to-end contra Default Environment de CX
│   ├── regenerate_html.py          #   regenera HTML del reporte sin llamar a CX
│   ├── rebuild_history.py          #   reconstruye history.json del dashboard
│   ├── list_fails.py               #   lista FAILs de un run y su estado de analisis
│   └── _archive/                   #   skeleton Promptfoo Sprint 1 archivado (EP-QA-04)
├── reports/                        # outputs HTML + TXT (gitignored, generados en CI o local)
├── docs/                           # documentacion ampliada
│   ├── setup-cicd.md               #   guia paso a paso Fase B Sprint 4 (WIF + Variables)
│   └── setup-qa.md                 #   guia paso a paso Fase B Sprint 6 (GitHub Pages + email)
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

Deps: `requests`, `google-auth`, `pyyaml` (runtime), `pytest` (tests). El runner QA del Sprint 6 (`qap/test_qa_playbooks.py`) solo necesita `requests`.

### 2. gcloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
```

El `<PROJECT_ID>` debe coincidir con `project:` en `definitions/agent.yaml`.

### 3. QA local (opcional)

```bash
# Listar los 29 TCs sin ejecutar
python qap/test_qa_playbooks.py --list

# Ejecutar todos (3 runs por TC por default, output en ~/petal-qa/)
python qap/test_qa_playbooks.py

# Subset
python qap/test_qa_playbooks.py --type REG
python qap/test_qa_playbooks.py --test TC-C29 --runs 1
```

Reportes públicos del último run en CI: ver `docs/setup-qa.md`.

---

## Comandos

Patron unificado en los 9 push_*.py de recursos colectivos: **`LIST -> diff -> PATCH/POST`** con idempotencia real (PATCH parcial con `updateMask`). Para el agente (recurso unico): `GET -> diff -> PATCH`.

Todos los scripts soportan `--dry-run`. **Recomendado antes de tocar producción.**

### Listar Playbooks del agente

```bash
python act/push_examples.py --list-playbooks
```

### Examples — upsert desde YAML

```bash
# Dry-run
python act/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml \
    --dry-run

# Real
python act/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml

# Solo uno (filtra por campo `id` del YAML)
python act/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml \
    --only EX_REG_01
```

El campo `tool` (full path) se inyecta automaticamente en cada `toolUse` desde `definitions/agent.yaml` — los YAMLs de Examples son agnosticos.

### Playbooks — upsert desde YAML

```bash
# Un fichero
python act/push_playbooks.py --file=definitions/playbooks/handoff.yaml --dry-run

# Todos los YAMLs de definitions/playbooks/
python act/push_playbooks.py --all --dry-run

# Filtro por displayName
python act/push_playbooks.py --all --only Handoff --dry-run
```

### Tools — upsert desde YAML

```bash
python act/push_tools.py --file=definitions/tools/petaldatatool.yaml --dry-run
python act/push_tools.py --all --dry-run
python act/push_tools.py --all --only PetalDataTool --dry-run
```

El YAML de Tool puede traer la spec OpenAPI inline en `openApiSpec.textSchema`, o referenciar un fichero adyacente con `openapi_spec_file: petaldatatool_openapi.yaml`. La opcion del fichero adyacente se lee como **texto crudo** — preserva formatting byte-a-byte y evita falsos diffs por re-serializacion.

### Agent config — sincroniza config global

```bash
python act/push_agent_config.py --dry-run
```

Lee el bloque `agent_definition:` de `definitions/agent.yaml`, hace GET del agente, diffea, y PATCH-ea solo los campos cambiados. Sin LIST.

### Environments / Versions — Sprint 4

```bash
# Environments (LIST → diff → PATCH/POST, igual que el resto)
python act/push_environments.py --all --dry-run

# Versions (immutables: solo --create o --list)
python act/push_versions.py --list                                  # lista versiones de todos los flows
python act/push_versions.py --list --flow "Default Start Flow"      # filtra por flow

python act/push_versions.py --create --description "v1.0.0" --dry-run
python act/push_versions.py --create --file definitions/versions/v1.yaml --dry-run
python act/push_versions.py --create --all --dry-run                # todos los YAMLs en definitions/versions/
```

`push_versions.py` es el unico modulo del template que NO sigue el patron LIST → diff → PATCH/POST: las Versions son snapshots inmutables, solo POST crea recursos nuevos.

### NLU clasico Flow-based — Sprint 3

Mismo patron `LIST -> diff -> PATCH/POST` con flags `--file`, `--all`, `--only`, `--dry-run`. Estos modulos cubren los recursos del Dialogflow CX clasico (no Playbook-based).

```bash
# Flows (top-level)
python act/push_flows.py --all --dry-run

# Pages (anidadas bajo Flow — el YAML declara parent_flow_displayName)
python act/push_pages.py --all --dry-run
python act/push_pages.py --all --flow Test_Flow --dry-run   # filtro por flow padre

# Intents
python act/push_intents.py --all --dry-run

# Entity Types (KIND_MAP / KIND_LIST / KIND_REGEXP)
python act/push_entity_types.py --all --dry-run

# Webhooks (genericWebService)
python act/push_webhooks.py --all --dry-run

# Generators (Gemini, con placeholders en promptText)
python act/push_generators.py --all --dry-run
```

Cada modulo tiene un fixture sintetico bajo `definitions/<recurso>/example_*.yaml` que sirve para probar el flujo en seco. Los nombres de los displayName empiezan por `Test_*` para no colisionar con recursos reales.

### Validar capacidades de la API

```bash
python act/validate_api.py
python act/validate_api.py --skip-concurrency
python act/validate_api.py --quick
```

Crea un Example dummy (`__VALIDATION_DUMMY_<ts>__`), ejecuta 9 tests (PATCH, DELETE, paginacion, rate limit, retry, diff, concurrencia), y limpia con `atexit`.

### Tests unitarios

```bash
pytest act/tests/
pytest act/tests/ -v          # verbose
pytest act/tests/ -q          # quiet (objetivo: <10s)
```

Sin red. Sin auth. Mock de `requests` con `unittest.mock`.

### QA — runner real (Sprint 6)

```bash
# Listar los 29 TCs
python qap/test_qa_playbooks.py --list

# Ejecutar todos (por default 3 runs/TC, output a ~/petal-qa/)
python qap/test_qa_playbooks.py

# Subset por tipo o por TC
python qap/test_qa_playbooks.py --type REG          # solo regresión
python qap/test_qa_playbooks.py --type EDGE         # solo metodología
python qap/test_qa_playbooks.py --test TC-C29 --runs 1
```

En CI el script detecta `GITHUB_ACTIONS=true` y escribe a `./reports/`. Los reportes se publican en
`https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.{html,txt}` tras cada run a `main`. Ver `docs/setup-qa.md`.

---

## Decisiones arquitectonicas

**No negociables** — definidas en briefs Sprint 1 / Sprint 2 tras descubrir comportamientos de la API CX:

- **CI/CD**: GitHub Actions (no Cloud Build). Sprint 4.
- **Auth API CX**: `gcloud auth print-access-token` para todos los scripts. No `google.auth.default()`.
- **Header obligatorio**: `x-goog-user-project: <project>` en todas las llamadas. Se carga desde `definitions/agent.yaml.api.required_headers`.
- **Idempotencia**: PATCH parcial con `updateMask`. Sin full-update salvo que un recurso no admita parcial documentado. (Capacidad confirmada en S60 Test 10 PASS.)
- **Workflow `LIST -> diff -> PATCH/POST` unificado** para los 4 push_*.py de recursos colectivos. Para el agente (recurso unico): `GET -> diff -> PATCH`.
- **`act/diff.py` es funcion pura**: dict local + dict remoto -> `(needs_update, update_mask, patch_payload)`. Sin red, sin side effects. Cubierto por `act/tests/test_diff.py`.
- **Agnosticismo**: constantes especificas del agente (project, location, IDs, etc.) en `definitions/agent.yaml` o env vars. Nada hardcoded en Python. Los push_*.py reciben Playbook ID / Tool ID por argumento o YAML.
- **Tests sin red**: mock de `requests`. Si un test necesita red, no va en `act/tests/` — va en `qap/` o se descarta.
- **Concurrencia**: la API CX no tiene optimistic locking (last-write-wins). En CI usar `concurrency: 1` para evitar race conditions (Sprint 4).
- **Secretos**: en GitHub Actions usar Workload Identity Federation con un Service Account, NO Service Account Key files. Localmente: `gcloud auth login` + ADC.

---

## Schema de Examples (descubierto en S60)

```yaml
displayName: str
actions:
  - userUtterance: { text: str }
  - agentUtterance: { text: str }
  - toolUse:
      action: consultarDatos       # operationId del Tool
      inputActionParameters:
        # campos sueltos top-level (recurso, accion, ...)
      outputActionParameters:
        '200':                     # CRITICO: un solo top-level key
          # JSON entero anidado aqui
playbookOutput:
  actionParameters:
    # parametros de salida del Playbook
```

**Hallazgo critico**: la API rechaza con 400 si `outputActionParameters` tiene mas de un top-level key. Convencion: envolver bajo `"200"`.

---

## Schema de Playbooks (Sprint 2)

```yaml
displayName: str
goal: str
instruction:
  steps:
    - text: str
inputParameterDefinitions: [...]
outputParameterDefinitions: [...]
referencedTools: [...]
playbookType: PLAYBOOK_TYPE_TASK | ROUTINE | ...   # default: el del agente
```

`tokenCount`, `name`, `createTime`, `updateTime` son read-only y se ignoran en el diff.

---

## Schema de Tools (Sprint 2)

Wrapper YAML (`definitions/tools/<name>.yaml`):

```yaml
displayName: PetalDataTool
description: ...
toolType: CUSTOMIZED_TOOL
openapi_spec_file: petaldatatool_openapi.yaml   # ruta adyacente, se lee como texto crudo
# o bien:
openApiSpec:
  textSchema: |
    openapi: 3.0.0
    ...
```

---

## Schema de Agent config (Sprint 2)

Bloque `agent_definition:` dentro de `definitions/agent.yaml`:

```yaml
agent_definition:
  displayName: ...
  defaultLanguageCode: es
  timeZone: ...
  speechToTextSettings: { ... }
  advancedSettings: { ... }
  start_playbook_id: <uuid>            # se resuelve a startPlaybook (full path) en runtime
  enableMultiLanguageTraining: true
```

---

## CI/CD

Sprint 4 introduce dos workflows GitHub Actions con autenticacion via **Workload Identity Federation** (NO Service Account Keys):

| Workflow | Trigger | Que hace |
|---|---|---|
| `.github/workflows/qa.yml` | `workflow_dispatch` + push `feature/**` + PR a `main` (Sprint 6) | Ejecuta los 29 TCs de `qap/test_qa_playbooks.py` contra Default Environment, sube artifact con reportes y publica HTML + TXT a GitHub Pages (rama `gh-pages`, ruta `/qa/`). `continue-on-error: true` en fase 1 (no bloquea merge). `cancel-in-progress: true`. |
| `.github/workflows/deploy.yml` | push a `main` (post-merge) | Deploy de Examples / Playbooks / Tools / Agent Config + creacion de Version snapshot. `concurrency: 1` con `cancel-in-progress: false` (no cortar deploys). |

Los workflows referencian dos GitHub Variables (NO secrets): `GCP_WIF_PROVIDER` y `GCP_SERVICE_ACCOUNT`. Hasta que esten configuradas, los workflows fallan limpio en `google-github-actions/auth@v2` — no tocan Petal.

**Fase B humana (configuracion GCP IAM + GitHub Variables)**: ver guia paso a paso en [`docs/setup-cicd.md`](docs/setup-cicd.md). Tiempo estimado 30-45 min.

---

## Roadmap

- **Sprint 1** ✅ — Estructura base, `push_examples` agnostico, Promptfoo skeleton, `validate_api` re-ubicado.
- **Sprint 2** ✅ — `diff.py` puro + tests, idempotencia en `push_examples`, modulos nuevos `push_playbooks` / `push_tools` / `push_agent_config`, suite pytest sin red.
- **Sprint 3** ✅ — Cobertura NLU clasico Flow-based: `push_flows`, `push_pages`, `push_intents`, `push_entity_types`, `push_webhooks`, `push_generators`. Validacion completa diferida a un proyecto Flow-based real (Petal es Playbook-only).
- **Sprint 4** ✅ — CI/CD GitHub Actions con WIF, modulos `push_environments` y `push_versions` (immutable), workflows `deploy.yml` + `qa.yml`, guia humana `docs/setup-cicd.md`.
- **Sprint 5** ✅ — Migracion real de Petal: 11 pull scripts + refactor `push_examples`, los 12 recursos exportados (round-trip-clean validado contra CX).
- **Sprint 6** ✅ — Integracion del runner QA real (`test_qa_playbooks.py`, 29 TCs) en el pipeline ACT contra Default Environment + publicacion de reportes en GitHub Pages. Promptfoo skeleton archivado en `qap/_archive/` (reactivacion: EP-QA-04).

---

*Estado al 14-may-2026: Sprint 6 SHIPPED — template cubre 12/12 recursos top-level CX + CI/CD + QA real con reportes públicos. Pendiente: Fáse B humana del Sprint 6 (`docs/setup-qa.md`). Ver `📋 Claude Code Reports` en Notion para logs de ejecucion autonoma.*

