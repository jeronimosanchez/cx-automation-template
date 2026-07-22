# CLAUDE.md

Versión: V0 | Fecha: 2026-05-11 | Proyecto: cx-automation-template (Petal)

> Cubre lo que Claude Code necesita para operar en cada sesión: reglas no negociables, constraints y protocolo de trabajo. El README cubre el resto.
> Claude Code propone mejoras al final de cada sesión cuando detecta patrones repetidos. Jero aprueba antes de modificar este archivo.

---

## 1. Qué es este repo

`cx-automation-template` es el repo de la línea **ACT** del sistema de Automatización CD de Jero. Automatiza el despliegue de artefactos al agente conversacional **Petal** en Dialogflow CX.

**Recursos cubiertos (12):** Playbooks, Examples, Tools, Agent Config, Flows, Pages, Intents, Entity Types, Webhooks, Generators, Environments y Versions, más CI/CD vía GitHub Actions.

**Contexto de negocio:** Petal es una floristería online en español. No es un proyecto de juguete: es una simulación profesional construida con la estructura y calidad de un proyecto de producción real, que sirve como portfolio y sandbox de validación.

**Sistema de Automatización CD (4 líneas):** ACT (este repo) · GEN · QAP · RES. Cada línea tendrá su propio repo. Este `CLAUDE.md` es **solo de ACT**.

**Dos repos del sistema:**
- `cx-automation-template` — fuente de verdad de todos los YAMLs (`definitions/`). Scripts de despliegue (`push_*.py`) y CI/CD.
- `agent-validation-engine` — simulación y QA local. Su `definitions/` es un symlink a este repo. Contiene scripts de simulación (`qap/sim/`), skills (`qap/skills/`), runner QA y test cases.

---

---

## 3. Decisiones técnicas no negociables

Estas decisiones están validadas en producción. No cambiar sin gate humano explícito.

1. **Auth:** usar siempre `gcloud auth print-access-token`. Nunca `google.auth.default()`.
2. **Headers obligatorios en toda llamada a la API de Dialogflow CX:**
   - `Authorization: Bearer <token>`
   - `Content-Type: application/json`
   - `x-goog-user-project: <GCP_PROJECT>`
3. **WIF (Workload Identity Federation):** nunca usar SA keys. La autenticación de GitHub Actions a GCP es exclusivamente vía WIF.
4. **Idempotencia:** todo `push_*.py` sigue el patrón `LIST → diff → PATCH/POST solo lo que cambió`. Nunca recrear recursos existentes.
5. **LRO polling:** `POST /versions` requiere polear `GET /operations/{id}` hasta `done=true`. No reportar éxito antes.
6. **`displayName` obligatorio en `POST /versions`** — sin él la API devuelve 200 pero la operation falla silenciosamente con `code=3`.
7. **`concurrency: 1`** en los workflows CI/CD. Evita races entre despliegues paralelos sobre el mismo agente.
8. **Región `europe-west1` — bug conocido en Playbooks:** `PATCH` con `updateMask` falla. Usar **Full Update**: `GET` del objeto completo → modificar `instruction.steps` → `PATCH` del objeto completo **sin** `updateMask`. Es un bug conocido del backend de Dialogflow CX en regiones no-global. No hay workaround oficial — Full Update es la única solución validada.

---

## 4. Mapa de dependencias

Cuando se modifica un área, hay otras que deben actualizarse en el mismo cambio.

| Si cambias | Actualiza |
|---|---|
| `definitions/` | los 12 `push_*.py` · `deploy.yml` |
| `act/` | `act/tests/` · `deploy.yml` · `qa.yml` · README |
| `act/tests/` | `qa.yml` · README |
| `.github/workflows/` | `docs/setup-cicd.md` · comandos de monitoreo |
| `qap/` | `qa.yml` · README |
| `qap/test_qa_playbooks.py` | `qa.yml` · Default Environment de CX · GitHub Pages (`docs/setup-qa.md`) |
| `docs/` | README · `deploy.yml` · `docs/setup-qa.md` (Sprint 6) |
| `reports/` | `qa.yml` · `.gitignore` (no committear) |
| `requirements.txt` | cualquier script que use la librería nueva |


---

## 5. Comandos comunes

Set base. Se amplía con el uso vía protocolo de auto-mejora (ver final de sección).

```bash
# Activar entorno virtual
source .venv/bin/activate

# Tests
python -m pytest act/tests/ -q

# Deploy manual (SIEMPRE dry-run primero)
python act/push_playbooks.py --all --dry-run
python act/push_playbooks.py --all

# Listar versiones de un flow
python act/push_versions.py --list --flow "Default Start Flow"

# Validar credenciales y conectividad con la API
python act/validate_api.py
```

**Protocolo de auto-mejora:** si un comando se repite 2 o más veces en una sesión, Claude Code propone añadirlo a esta sección al cierre. Jero aprueba antes del commit.

---

## 6. Flujo de trabajo

Reglas operativas sobre cómo cualquier cambio llega a producción.

1. **El único camino a producción es `git push` → GitHub → CI/CD con QA automático.** Ningún despliegue válido ocurre fuera de este flujo.
2. **`--dry-run` se usa solo para previsualizar cambios antes de commitear**, nunca despliega nada real.
3. **Los scripts `push_*.py` nunca se ejecutan directamente contra producción sin pasar por el CI/CD.** El uso local se limita a `--dry-run`. La pasada real la hace `deploy.yml` tras push a `main`.

---

## 7. Constraints (nunca tocar sin aprobación explícita)

1. **IAM y roles en GCP** — ningún cambio sin aprobación explícita de Jero.
2. **Agente Petal en producción** — `<AGENT_ID_PETAL_1.0>`. Ningún cambio sin aprobación.
3. **GitHub Secrets** — nunca crear, modificar ni leer sin aprobación.
4. **Templates — material sagrado del knowledgebase** — ningún template (TCs, examples, playbooks, schemas u otro artefacto de definición) se crea, modifica ni elimina sin validación explícita de Jero. Mostrar siempre "cómo quedaría" y esperar OK antes de tocar cualquier archivo. Aplica aunque el cambio sea retrocompatible o parezca trivial. **Modo por defecto en toda revisión: MOSTRAR y EXPLICAR para que Jero aprenda. Nunca ejecutar durante una revisión.** "Seguimos", "vamos", "continúa" son dirección, no autorización. Ejecución solo con "aplícalo", "hazlo", "cámbialo" sobre un cambio concreto ya revisado. Al mostrar "cómo quedaría" un cambio, incluir siempre una sección **Por qué** que explique el mecanismo o problema que resuelve.
5. **`petal-sheet-api`** — proyecto separado (backend Cloud Run de inventario). Vive en tres instancias, ninguna se toca desde este repo:
   - `~/petal-sheet-api/` (local) — código fuente editable.
   - `github.com/jeronimosanchez/petal-sheet-api` (privado) — copia de seguridad.
   - Cloud Run `europe-west1` — servidor que corre 24/7.

---

## 8. Autopilot — guardarraíles (7 gates)

Antes de cualquier commit autónomo, verificar los 7 gates. Los marcados como **AUTO** Claude Code los chequea sin pedir confirmación; los marcados como **GATE** requieren aprobación explícita de Jero antes de continuar.

1. **Tests 100% PASS** *(AUTO)* — si falla cualquier test, parar y avisar.
2. **Diff coherente** *(AUTO)* — solo archivos dentro del scope declarado, 0 fuera.
3. **Sin tocar producción ni IAM** *(AUTO)* — ningún cambio sobre GCP, IAM o GitHub Secrets.
4. **Commit limpio** *(AUTO)* — sin `TODO`, `FIXME` o `HACK` introducidos en el diff.
5. **Resumen pre-push** *(GATE)* — mostrar qué cambia, impacto funcional y riesgos. Jero aprueba antes del push.
6. **Anti-regresión** *(AUTO)* — verificar que no se han borrado ni desactivado tests para forzar el PASS.
7. **Scope check** *(GATE)* — si detecta archivos modificados fuera del scope declarado, parar y preguntar.

Si cualquier gate AUTO falla, parar inmediatamente y reportar a Jero. No intentar "arreglar para que pase".

---

Los 7 gates anteriores aplican al momento de un commit autónomo. Las sub-secciones siguientes regulan los permisos por defecto durante toda la sesión, haya o no commit autónomo en curso.

### 8.1 Permisos por defecto (sin pedir aprobación)

**Lectura y análisis**
- Verbos read-only de `gh`, `gcloud`, `git`, y MCP Notion read-only.
- `curl -s` GET a cualquier API (CX, GitHub, googleapis, etc.).
- `python3 -c` con `import / open / print / requests.get`.
- `gcloud auth print-access-token`.
- `source .venv` para activar entorno.
- Escritura en `/tmp/` como paso intermedio de análisis.
- Medición de tokens con `tiktoken` si está disponible (su instalación cae en §8.2).
- Lectura de archivos del repo (YAML, JSON, scripts).

**Monitorización**
- `gh run view`, `gh run list` y similares para estado de workflows.
- Bucles de espera observando runs de CI/CD sin disparar acciones.

**Documentación**
- WebFetch a URLs públicas de docs (cloud.google.com, googleapis.com, docs.anthropic.com, etc.).

### 8.2 Gate obligatorio (parar y pedir aprobación)

Solo 3 gates. Todo lo demás es auto.

| Gate | Por qué |
|---|---|
| `gh pr merge` / `git push` a `main` | Dispara deploy a producción |
| `curl POST/PATCH/DELETE` a API CX directamente | Muta el agente saltándose el pipeline — sin traza en GitHub |
| IAM / GitHub Secrets / GCP directo | Seguridad crítica, nunca negociable |

**Auto-permitido sin gate (todo lo demás):**
- Escribir/modificar archivos del repo (`definitions/`, `act/`, `qap/`, etc.)
- `git push origin <rama-que-no-sea-main>`
- `gh pr create`
- `pip install`, `npm install`
- Correr tests QA (hasta suite completa)

### 8.3 Modo libre — desactivar todos los gates para una acción concreta

Cuando Jero dice **"modo libre: <descripción de la acción>"**, Claude Code ejecuta esa acción concreta **sin ningún gate**, incluyendo los 3 de §8.2.

Condiciones:
- Jero debe especificar la acción concretamente ("modo libre: merge y deploy de este PR").
- El modo libre aplica **solo a esa acción**. Al terminar, vuelven los gates normales.
- No aplica a IAM / GitHub Secrets — esos son intocables siempre.

Ejemplo:
> "modo libre: merge del PR #72 y espera el deploy"
> → Claude Code hace merge + vigila deploy sin preguntar nada.


---

## 9. Referencias técnicas y protocolo de arranque

### Identificadores

- **Repo GitHub:** `<GITHUB_REPO>`
- **Proyecto GCP:** `<GCP_PROJECT>`
- **PROJECT_NUMBER:** `<PROJECT_NUMBER>`
- **Agente CX Petal:** `<AGENT_ID_PETAL_1.0>` (region `europe-west1`)
- **Service Account de despliegue:** `<SERVICE_ACCOUNT>`
- **Roles del SA:** `roles/dialogflow.admin` + `roles/serviceusage.serviceUsageConsumer`
- **Workload Identity Pool:** `<WIF_POOL>` (global)
- **Workload Identity Provider:** `<WIF_PROVIDER>` (attribute-condition: `<GITHUB_REPO>`)
- **GitHub Variables:** `GCP_WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT`

### Protocolo de arranque de sesión

1. `cd ~/cx-automation-template && claude`
2. Jero pega el link del brief de Notion del Sprint.
3. Claude Code lee el brief vía MCP, lee este `CLAUDE.md` y ejecuta.

### Situaciones no cubiertas

Si Claude Code encuentra una situación no documentada en este archivo:

1. Para.
2. Describe la situación en una línea.
3. Propone 2-3 opciones con su impacto.
4. Espera confirmación de Jero.

Nunca decide solo en territorio no cubierto.

---

## 10. Modos de trabajo (Research)

Si el usuario indica "modo research CX", "trabaja en research CX" o similar:
→ Lee `research/cx-dialogflow/CLAUDE.md` y opera desde ahí.

Si el usuario indica "modo research diseño conversacional" o similar:
→ Lee `research/conversational-design/CLAUDE.md` y opera desde ahí.

Si el usuario indica "modo research Anthropic", "modo research Claude" o similar:
→ Lee `research/claude-anthropic/CLAUDE.md` y opera desde ahí.

---

## 11. Comunicación por defecto

Cuando se presente información relevante sobre el sistema (decisiones de diseño, cambios propuestos, mecanismos internos), incluir siempre una sección **Por qué** con:
- el mecanismo por debajo, o
- el problema que resuelve

Aplica a: análisis de diseño, propuestas de cambio, explicaciones de comportamiento del agente, cambios en playbooks o examples.

No solo qué cambia — también por qué funciona así.
