# CLAUDE.md

Versión: V0 | Fecha: 2026-05-11 | Proyecto: cx-automation-template (Petal)

> **Este documento es una V0 en evolución.**
>
> `cx-automation-template` automatiza el despliegue de **Petal**, un agente conversacional de comercio de flores diseñado como simulación de un proyecto profesional real — con la estructura, procesos y calidad que tendría en producción.
>
> Cubre lo que Claude Code necesita para operar en cada sesión: estado actual, reglas no negociables, constraints y protocolo de trabajo. El README cubre el resto.
>
> Claude Code propone mejoras al final de cada sesión cuando detecta patrones repetidos o bloqueos graves. Jero aprueba cada cambio antes de modificar este archivo. Cuando se modifica, Claude Code pregunta: "¿Hago commit y push ahora?"
>
> **Control de versiones:** todos los artefactos de Petal están versionados en GitHub vía este repo. Si un cambio rompe producción, `git revert` + pipeline lo restaura automáticamente. Claude Code nunca aplica cambios destructivos sin verificar que existe versión anterior recuperable.

---

## 1. Qué es este repo

`cx-automation-template` es el repo de la línea **ACT** del sistema de Automatización CD de Jero. Automatiza el despliegue de artefactos al agente conversacional **Petal** en Dialogflow CX.

**Recursos cubiertos (12):** Playbooks, Examples, Tools, Agent Config, Flows, Pages, Intents, Entity Types, Webhooks, Generators, Environments y Versions, más CI/CD vía GitHub Actions.

**Contexto de negocio:** Petal es una floristería online en español. No es un proyecto de juguete: es una simulación profesional construida con la estructura y calidad de un proyecto de producción real, que sirve como portfolio y sandbox de validación.

**Alcance V0:** Petal-específico. La generalización a otros agentes se aborda en V1, después del Sprint 5.

**Sistema completo de Automatización CD (4 líneas):**

- **ACT** → despliegue de artefactos a Dialogflow CX (este repo, operativo).
- **GEN** → generación de playbooks, examples y artefactos (por definir).
- **QAP** → quality assurance y validación (por definir).
- **RES** → investigación y recursos, corre en segundo plano (por definir).

Cada línea tendrá su propio repo y su propio `CLAUDE.md`. Existirá además un `CLAUDE.md` global del orquestador (EP-02) que coordina las 4 líneas. Este `CLAUDE.md` es **solo de ACT**.

---

## 2. Estado actual

**Commit HEAD:** `f3d8384` (pre-Sprint 6)

### Sprints

| Sprint | Estado | Contenido |
|---|---|---|
| Sprint 1 | ✅ | Estructura base, Promptfoo skeleton, `validate_api` |
| Sprint 2 | ✅ | Playbooks, Tools, Agent Config, idempotencia |
| Sprint 3 | ✅ | Flows, Pages, Intents, Entity Types, Webhooks, Generators |
| Sprint 4 | ✅ | CI/CD GitHub Actions + WIF, Environments, Versions, autopilot |
| Sprint 5 | ✅ | Migración real de Petal: 11 pull scripts + refactor `push_examples`, los 12 recursos exportados (round-trip-clean validado contra CX) |
| Sprint 6 | ✅ | Integración runner QA real (`test_QA_Playbooks_v23.py`, 29 TCs) en pipeline ACT contra Default Environment + publicación de reportes en GitHub Pages. Promptfoo skeleton archivado en `qa/_legacy_promptfoo/` |

### Bugs resueltos en S58-S59 (no reintroducir)

1. **LRO polling en `POST /versions`** — la llamada es asíncrona. La API devuelve 200 inmediato con un `Operation`, no la `Version`. Hay que polear `GET /operations/{id}` hasta `done=true`. Sin esto el script reporta éxito cuando en realidad ha fallado en segundo plano.
2. **`displayName` obligatorio en `POST /versions`** — sin él la API devuelve 200 pero la operation falla silenciosamente con `code=3`. Incluir siempre.
3. **`push_examples.py --all`** — el workflow `deploy.yml` llamaba al script con `--all` pero el script no aceptaba el flag. Añadido y testeado.
4. **`PROMPTFOO_PYTHON` en `qa.yml`** — el workflow usaba ruta relativa `../.venv/bin/python` que no existe en el runner de GitHub Actions. Eliminado: el runner usa el Python del `PATH`.
5. **`roles/serviceusage.serviceUsageConsumer`** — el SA `cx-template-deployer` requería este rol adicional a `dialogflow.admin` para llamar a la API.

### Pendientes inmediatos

- **Fáse B Sprint 6** — pasos manuales en `docs/setup-qa.md` (activar GitHub Pages, permisos workflow Read+Write, verificar email, primer run E2E).
- TT-01-03 — siguiente tarea de la cadena de setup.
- EP-02 — orquestador central de las 4 líneas y su `CLAUDE.md` global.
- EP-QA-02 — cerrar tras validación Fáse B del Sprint 6.
- Deuda técnica anotada en S60: reconciliar `push_playbooks.py` (usa `PATCH+updateMask`) con §3.8 (Full Update obligatorio en `europe-west1`).

---

## 3. Decisiones técnicas no negociables

Estas decisiones están validadas en producción. No cambiar sin gate humano explícito.

1. **Auth:** usar siempre `gcloud auth print-access-token`. Nunca `google.auth.default()`.
2. **Headers obligatorios en toda llamada a la API de Dialogflow CX:**
   - `Authorization: Bearer <token>`
   - `Content-Type: application/json`
   - `x-goog-user-project: floristeria-petal-digital`
3. **WIF (Workload Identity Federation):** nunca usar SA keys. La autenticación de GitHub Actions a GCP es exclusivamente vía WIF.
4. **Idempotencia:** todo `push_*.py` sigue el patrón `LIST → diff → PATCH/POST solo lo que cambió`. Nunca recrear recursos existentes.
5. **LRO polling:** `POST /versions` requiere polear `GET /operations/{id}` hasta `done=true`. No reportar éxito antes.
6. **`displayName` obligatorio en `POST /versions`** (ver bug 2 en sección 2).
7. **`concurrency: 1`** en los workflows CI/CD. Evita races entre despliegues paralelos sobre el mismo agente.
8. **Región `europe-west1` — bug conocido en Playbooks:** `PATCH` con `updateMask` falla. Usar **Full Update**: `GET` del objeto completo → modificar `instruction.steps` → `PATCH` del objeto completo **sin** `updateMask`. Es un bug conocido del backend de Dialogflow CX en regiones no-global. No hay workaround oficial — Full Update es la única solución validada.

---

## 4. Mapa de dependencias

Cuando se modifica un área, hay otras que deben actualizarse en el mismo cambio.

| Si cambias | Actualiza |
|---|---|
| `definitions/` | los 12 `push_*.py` · `deploy.yml` |
| `src/` | `tests/` · `deploy.yml` · `qa.yml` · README |
| `tests/` | `qa.yml` · README |
| `.github/workflows/` | `docs/setup-cicd.md` · comandos de monitoreo |
| `qa/` | `qa.yml` · README |
| `qa/test_QA_Playbooks_v23.py` | `qa.yml` · Default Environment de CX · GitHub Pages (`docs/setup-qa.md`) |
| `docs/` | README · `deploy.yml` · `docs/setup-qa.md` (Sprint 6) |
| `reports/` | `qa.yml` · `.gitignore` (no committear) |
| `requirements.txt` | cualquier script que use la librería nueva |

**Regla pendiente (Sprint 5):** añadir test automático que verifique que todas las librerías importadas en `src/` están declaradas en `requirements.txt`.

---

## 5. Comandos comunes

Set base. Se amplía con el uso vía protocolo de auto-mejora (ver final de sección).

```bash
# Activar entorno virtual
source .venv/bin/activate

# Tests
python -m pytest tests/ -q

# Deploy manual (SIEMPRE dry-run primero)
python src/push_playbooks.py --all --dry-run
python src/push_playbooks.py --all

# Listar versiones de un flow
python src/push_versions.py --list --flow "Default Start Flow"

# Validar credenciales y conectividad con la API
python src/validate_api.py
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
2. **Agente Petal en producción** — `745375ba-ac7e-4eb8-b8a0-d742891f2aa4`. Ningún cambio sin aprobación.
3. **GitHub Secrets** — nunca crear, modificar ni leer sin aprobación.
4. **`petal-sheet-api`** — proyecto separado (backend Cloud Run de inventario). Vive en tres instancias, ninguna se toca desde este repo:
   - `~/petal-sheet-api/` (local) — código fuente editable.
   - `github.com/jeronimosanchez/petal-sheet-api` (privado) — copia de seguridad.
   - Cloud Run `europe-west1` — servidor que corre 24/7.
5. **Sprint 5** — nunca en autopilot. Gate humano obligatorio en cada paso de migración de artefactos reales.

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

## 9. Referencias técnicas y protocolo de arranque

### Identificadores

- **Repo GitHub:** `jeronimosanchez/cx-automation-template`
- **Proyecto GCP:** `floristeria-petal-digital`
- **PROJECT_NUMBER:** `920225907399`
- **Agente CX Petal:** `745375ba-ac7e-4eb8-b8a0-d742891f2aa4` (region `europe-west1`)
- **Service Account de despliegue:** `cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com`
- **Roles del SA:** `roles/dialogflow.admin` + `roles/serviceusage.serviceUsageConsumer`
- **Workload Identity Pool:** `github-pool` (global)
- **Workload Identity Provider:** `github-provider` (attribute-condition: `jeronimosanchez/cx-automation-template`)
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
