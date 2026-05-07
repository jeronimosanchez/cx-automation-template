# cx-automation-template

Template reutilizable para automatizar agentes conversacionales en Dialogflow CX (REST v3beta1).

Provee:
- Definiciones declarativas de Examples / Playbooks / Tools en YAML.
- Scripts agnosticos al agente: leen `definitions/agent.yaml` (la unica fuente de verdad de project / location / agent_id / tool).
- Suite QA con Promptfoo + custom provider Python que llama a `detectIntent`.
- Validacion de capacidades de la API (`src/validate_api.py`) — usado para descubrir limites / comportamientos antes de codificarlos.

Pensado para varios agentes CX. Cambias `definitions/agent.yaml`, no tocas codigo.

---

## Estructura

```
.
├── definitions/                  # YAML declarativos — fuente de verdad
│   ├── agent.yaml                #   contexto del agente (project, location, agent_id, tool, playbooks)
│   ├── examples/                 #   un YAML por Playbook (registro_task.yaml, ...)
│   ├── playbooks/                #   reservado: definicion de playbooks
│   └── tools/                    #   reservado: definicion de tools (OpenAPI specs)
├── src/                          # Scripts Python ejecutables
│   ├── push_examples.py          #   crea / upsert Examples desde YAML
│   └── validate_api.py           #   valida capacidades de la API CX
├── qa/                           # Promptfoo + custom provider
│   ├── promptfoo_provider.py
│   ├── promptfooconfig.yaml
│   ├── package.json
│   └── README.md
├── tests/                        # reservado: tests Python
├── reports/                      # outputs timestamped (gitignored)
├── docs/                         # reservado: documentacion ampliada
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

Deps minimas: `requests`, `google-auth`, `pyyaml`. (Promptfoo NO esta aqui — se instala via npm en `qa/`.)

### 2. gcloud

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <PROJECT_ID>
```

El `<PROJECT_ID>` debe coincidir con `project:` en `definitions/agent.yaml` (por defecto `floristeria-petal-digital`).

### 3. Promptfoo (opcional, solo QA)

```bash
cd qa/
npm install
```

Ver `qa/README.md` para detalle de ejecucion.

---

## Comandos

### Listar Playbooks del agente

```bash
python src/push_examples.py --list-playbooks
```

### Crear / upsert Examples desde YAML

```bash
# dry-run — recomendado antes de tocar producción
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

El campo `tool` (full path) se inyecta automaticamente en cada `toolUse` desde `definitions/agent.yaml` — los YAMLs de Examples NO lo llevan, son agnosticos.

### Validar capacidades de la API

```bash
python src/validate_api.py
```

Crea un Example dummy (`__VALIDATION_DUMMY_<ts>__`) en el Playbook configurado, ejecuta 9 tests (PATCH, DELETE, paginacion, rate limit, retry, diff, concurrencia), y limpia al final con `atexit`. Reporte timestamped en `reports/`.

### QA con Promptfoo

```bash
cd qa/
PROMPTFOO_PYTHON=../.venv/bin/python ./node_modules/.bin/promptfoo eval
```

---

## Decisiones arquitectonicas

Estas son **no negociables** — se definieron en S57 (brief Sprint 1) tras descubrir comportamientos de la API CX:

- **CI/CD**: GitHub Actions (no Cloud Build).
- **Auth API CX**: `gcloud auth print-access-token` para todos los scripts nuevos. No `google.auth.default()`.
- **Header obligatorio**: `x-goog-user-project: <project>` en todas las llamadas a la API. Se carga desde `definitions/agent.yaml.api.required_headers`.
- **Workaround R1 (playbooks)**: en `europe-west1`, `playbooks.patch` parcial puede fallar silenciosamente. Para mutar Playbooks usar Full Update (GET → modify → PATCH completo). Documentado como riesgo R1.
- **Agnosticismo**: todas las constantes especificas del agente (project, location, IDs, etc.) en `definitions/agent.yaml` o env vars. Nada hardcoded en Python.
- **Secretos**: en GitHub Actions usar Workload Identity Federation con un Service Account, NO Service Account Key files. Localmente: `gcloud auth login` + ADC.
- **Concurrencia**: la API CX no tiene optimistic locking (last-write-wins). En CI usar `concurrency: 1` para evitar race conditions.

---

## Schema de Examples (descubierto en S60)

```yaml
displayName: str
actions:
  - userUtterance: { text: str }
  - agentUtterance: { text: str }
  - toolUse:
      action: consultarDatos       # operationId del Tool (NO 'petaldatatool', es legacy)
      inputActionParameters:
        # campos sueltos top-level (recurso, accion, ...)
      outputActionParameters:
        '200':                     # CRITICO: un solo top-level key — convencion HTTP status
          # JSON entero anidado aqui
playbookOutput:
  actionParameters:
    # parametros de salida del Playbook
```

**Hallazgo critico**: la API rechaza con 400 si `outputActionParameters` tiene mas de un top-level key. Convencion: envolver bajo `"200"`.

---

## Roadmap (resumen)

- **Sprint 1** ✅ — Estructura base, push_examples agnostico, Promptfoo skeleton, validate_api re-ubicado.
- **Sprint 2** — Migracion legacy: 12 Examples con `action: petaldatatool` → `consultarDatos`. Detalle en `reports/audit_legacy_examples_*.txt`.
- **Sprint 3+** — CI/CD GitHub Actions, mas agentes, mas Playbooks declarativos.

---

*Estado al 7-may-2026: Sprint 1 entregado. Ver `📋 Claude Code Reports` en Notion para logs de ejecucion autonoma.*
