# cx-automation-template

Template reutilizable para automatizar agentes conversacionales en Dialogflow CX (REST v3beta1).

Provee:
- Definiciones declarativas de Examples / Playbooks / Tools / Agent config en YAML.
- Scripts agnosticos al agente con flujo idempotente `LIST -> diff -> PATCH/POST` (`GET -> diff -> PATCH` para el agente).
- Suite de tests unitarios (`pytest`) sin red.
- QA con Promptfoo + custom provider Python que llama a `detectIntent`.
- Validacion de capacidades de la API (`src/validate_api.py`) — usado para descubrir limites / comportamientos antes de codificarlos.

Pensado para varios agentes CX. Cambias `definitions/agent.yaml`, no tocas codigo.

---

## Estructura

```
.
├── definitions/                    # YAML declarativos — fuente de verdad
│   ├── agent.yaml                  #   contexto + agent_definition (config global)
│   ├── examples/                   #   un YAML por Playbook (registro_task.yaml, ...)
│   ├── playbooks/                  #   un YAML por Playbook (handoff.yaml, ...)
│   └── tools/                      #   wrapper YAML + OpenAPI raw adyacente
├── src/                            # Scripts Python ejecutables
│   ├── diff.py                     #   funcion pura (recurso local vs remoto)
│   ├── push_examples.py            #   upsert Examples desde YAML
│   ├── push_playbooks.py           #   upsert Playbooks desde YAML
│   ├── push_tools.py               #   upsert Tools desde YAML
│   ├── push_agent_config.py        #   sync config global del agente (GET → diff → PATCH)
│   └── validate_api.py             #   valida capacidades de la API CX (9 tests)
├── tests/                          # Tests unitarios pytest (sin red)
│   ├── test_diff.py
│   ├── test_push_examples.py
│   ├── test_push_playbooks.py
│   ├── test_push_tools.py
│   └── test_push_agent_config.py
├── qa/                             # Promptfoo + custom provider
│   ├── promptfoo_provider.py
│   ├── promptfooconfig.yaml
│   └── README.md
├── reports/                        # outputs timestamped (gitignored)
├── docs/                           # documentacion ampliada
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

Deps: `requests`, `google-auth`, `pyyaml` (runtime), `pytest` (tests). Promptfoo NO esta aqui — se instala via npm en `qa/`.

### 2. gcloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
```

El `<PROJECT_ID>` debe coincidir con `project:` en `definitions/agent.yaml`.

### 3. Promptfoo (opcional, solo QA)

```bash
cd qa/
npm install
```

Ver `qa/README.md`.

---

## Comandos

Patron unificado en los 4 push_*.py: **`LIST -> diff -> PATCH/POST`** con idempotencia real (PATCH parcial con `updateMask`). Para el agente: `GET -> diff -> PATCH` (no hay LIST: solo hay un agente).

Todos los scripts soportan `--dry-run`. **Recomendado antes de tocar producción.**

### Listar Playbooks del agente

```bash
python src/push_examples.py --list-playbooks
```

### Examples — upsert desde YAML

```bash
# Dry-run
python src/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml \
    --dry-run

# Real
python src/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml

# Solo uno (filtra por campo `id` del YAML)
python src/push_examples.py \
    --playbook=Registro_Task \
    --file=definitions/examples/registro_task.yaml \
    --only EX_REG_01
```

El campo `tool` (full path) se inyecta automaticamente en cada `toolUse` desde `definitions/agent.yaml` — los YAMLs de Examples son agnosticos.

### Playbooks — upsert desde YAML

```bash
# Un fichero
python src/push_playbooks.py --file=definitions/playbooks/handoff.yaml --dry-run

# Todos los YAMLs de definitions/playbooks/
python src/push_playbooks.py --all --dry-run

# Filtro por displayName
python src/push_playbooks.py --all --only Handoff --dry-run
```

### Tools — upsert desde YAML

```bash
python src/push_tools.py --file=definitions/tools/petaldatatool.yaml --dry-run
python src/push_tools.py --all --dry-run
python src/push_tools.py --all --only PetalDataTool --dry-run
```

El YAML de Tool puede traer la spec OpenAPI inline en `openApiSpec.textSchema`, o referenciar un fichero adyacente con `openapi_spec_file: petaldatatool_openapi.yaml`. La opcion del fichero adyacente se lee como **texto crudo** — preserva formatting byte-a-byte y evita falsos diffs por re-serializacion.

### Agent config — sincroniza config global

```bash
python src/push_agent_config.py --dry-run
```

Lee el bloque `agent_definition:` de `definitions/agent.yaml`, hace GET del agente, diffea, y PATCH-ea solo los campos cambiados. Sin LIST.

### Validar capacidades de la API

```bash
python src/validate_api.py
python src/validate_api.py --skip-concurrency
python src/validate_api.py --quick
```

Crea un Example dummy (`__VALIDATION_DUMMY_<ts>__`), ejecuta 9 tests (PATCH, DELETE, paginacion, rate limit, retry, diff, concurrencia), y limpia con `atexit`.

### Tests unitarios

```bash
pytest tests/
pytest tests/ -v          # verbose
pytest tests/ -q          # quiet (objetivo: <10s)
```

Sin red. Sin auth. Mock de `requests` con `unittest.mock`.

### QA con Promptfoo

```bash
cd qa/
PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval
```

---

## Decisiones arquitectonicas

**No negociables** — definidas en briefs Sprint 1 / Sprint 2 tras descubrir comportamientos de la API CX:

- **CI/CD**: GitHub Actions (no Cloud Build). Sprint 4.
- **Auth API CX**: `gcloud auth print-access-token` para todos los scripts. No `google.auth.default()`.
- **Header obligatorio**: `x-goog-user-project: <project>` en todas las llamadas. Se carga desde `definitions/agent.yaml.api.required_headers`.
- **Idempotencia**: PATCH parcial con `updateMask`. Sin full-update salvo que un recurso no admita parcial documentado. (Capacidad confirmada en S60 Test 10 PASS.)
- **Workflow `LIST -> diff -> PATCH/POST` unificado** para los 4 push_*.py de recursos colectivos. Para el agente (recurso unico): `GET -> diff -> PATCH`.
- **`src/diff.py` es funcion pura**: dict local + dict remoto -> `(needs_update, update_mask, patch_payload)`. Sin red, sin side effects. Cubierto por `tests/test_diff.py`.
- **Agnosticismo**: constantes especificas del agente (project, location, IDs, etc.) en `definitions/agent.yaml` o env vars. Nada hardcoded en Python. Los push_*.py reciben Playbook ID / Tool ID por argumento o YAML.
- **Tests sin red**: mock de `requests`. Si un test necesita red, no va en `tests/` — va en `qa/` o se descarta.
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

## Roadmap

- **Sprint 1** ✅ — Estructura base, `push_examples` agnostico, Promptfoo skeleton, `validate_api` re-ubicado.
- **Sprint 2** ✅ — `diff.py` puro + tests, idempotencia en `push_examples`, modulos nuevos `push_playbooks` / `push_tools` / `push_agent_config`, suite pytest sin red.
- **Sprint 3+** — Migracion legacy de Examples (`petaldatatool` → `consultarDatos`), CI/CD GitHub Actions con `concurrency: 1`, mas agentes.

---

*Estado al 8-may-2026: Sprint 2 entregado. Ver `📋 Claude Code Reports` en Notion para logs de ejecucion autonoma.*
