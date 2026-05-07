# QA — cx-automation-template

Suite minima de QA usando [Promptfoo](https://www.promptfoo.dev/) con un custom Python provider que llama a Dialogflow CX (`detectIntent`).

## Setup

Promptfoo se instala via npm (no Python).

```bash
cd qa/
npm install
```

Esto instala `promptfoo` como dev dependency localmente en `qa/node_modules/`.

El provider Python (`promptfoo_provider.py`) usa el venv del repo (`../.venv`) para `requests` y `pyyaml`. Asegura que esta activo o exportalo:

```bash
export PROMPTFOO_PYTHON=../.venv/bin/python
```

(Promptfoo lo detecta y lo usa para invocar el provider.)

Y autentica con `gcloud`:

```bash
gcloud auth login
gcloud auth application-default login   # o solo print-access-token
gcloud config set project floristeria-petal-digital
```

## Ejecucion

```bash
cd qa/
PROMPTFOO_PYTHON=../.venv/bin/python npm run eval
```

O equivalentemente:

```bash
cd qa/
npx promptfoo eval
```

Para ver el reporte en navegador:

```bash
npm run view
```

## Estructura

- `promptfooconfig.yaml` — suite de tests. Provider apunta al script Python.
- `promptfoo_provider.py` — provider que llama a CX `detectIntent` y devuelve el texto del agente.
- `package.json` — dependencia npm de Promptfoo.

## Anadir tests

Edita `promptfooconfig.yaml`. Cada `tests[i]` se ejecuta como un turno aislado (session_id distinto). Para escenarios multi-turno hay que extender el provider para mantener `session_id` entre prompts.
