# Setup CI/CD para `cx-automation-template`

Guia exhaustiva paso a paso de la **Fase B** del Sprint 4 (configuracion humana). El codigo del repo (workflows + push_versions/push_environments) ya esta listo desde Sprint 4 — esto es lo unico que falta para activar el pipeline.

**Tiempo estimado:** 30-45 min siguiendo esta guia.

---

## Que hace cada workflow

| Workflow | Trigger | Que hace |
|---|---|---|
| `.github/workflows/qa.yml` | push a `feature/**` o PR a `main` | Ejecuta `promptfoo eval` contra el Default Environment de Petal. Bloquea merge si falla. |
| `.github/workflows/deploy.yml` | push a `main` (post-merge) | Despliega Examples / Playbooks / Tools / Agent Config a Petal y crea un snapshot inmutable de Version. |

Ambos autentican a GCP via **Workload Identity Federation (WIF)**. NO Service Account Keys — son un riesgo de leak y rotacion.

---

## Prerequisitos

- Acceso `owner` o `editor` al proyecto GCP `floristeria-petal-digital`.
- Acceso `admin` al repo GitHub `jeronimosanchez/cx-automation-template`.
- `gcloud` autenticado en local con la cuenta correcta:
  ```
  gcloud auth login
  gcloud config set project floristeria-petal-digital
  gcloud auth application-default set-quota-project floristeria-petal-digital
  ```
- `gh` CLI opcional pero recomendado para validar rapido.

---

## Paso 1 — Crear Service Account en GCP

Crea el SA que va a usar GitHub Actions para autenticar contra la API CX.

```
gcloud iam service-accounts create cx-template-deployer \
    --display-name="CX Template Deployer" \
    --description="Service Account usado por GitHub Actions para deploy/QA del template cx-automation-template" \
    --project=floristeria-petal-digital
```

**Verifica:**

```
gcloud iam service-accounts list \
    --project=floristeria-petal-digital \
    --filter="email:cx-template-deployer@*"
```

Debe aparecer `cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com`.

---

## Paso 2 — Asignar el rol `dialogflow.admin` al SA

`dialogflow.admin` cubre todas las operaciones que hacen los `push_*.py` (LIST/GET/PATCH/POST/DELETE sobre Examples, Playbooks, Tools, Agent, Flows, Pages, Intents, Entity Types, Webhooks, Generators, Environments y Versions).

```
gcloud projects add-iam-policy-binding floristeria-petal-digital \
    --member="serviceAccount:cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com" \
    --role="roles/dialogflow.admin"
```

Si quieres aplicar el principio de minimo privilegio en una iteracion futura, sustituye por `roles/dialogflow.editor` (no permite eliminar agentes ni ediciones de IAM internas) y verifica que los workflows siguen pasando.

**Verifica:**

```
gcloud projects get-iam-policy floristeria-petal-digital \
    --flatten="bindings[].members" \
    --filter="bindings.members:cx-template-deployer*" \
    --format="table(bindings.role)"
```

Debe aparecer `roles/dialogflow.admin`.

---

## Paso 3 — Crear el Workload Identity Pool

El pool es el contenedor logico bajo el que GCP confia en identidades externas (en este caso, tokens OIDC de GitHub Actions).

```
gcloud iam workload-identity-pools create github-pool \
    --location=global \
    --display-name="GitHub Pool" \
    --description="Pool para repos GitHub que necesitan autenticarse contra GCP via OIDC" \
    --project=floristeria-petal-digital
```

**Verifica:**

```
gcloud iam workload-identity-pools describe github-pool \
    --location=global \
    --project=floristeria-petal-digital
```

Debe mostrar `state: ACTIVE`.

---

## Paso 4 — Crear el Workload Identity Provider

El provider declara como mapear un token OIDC de GitHub a un principal de GCP. La `attribute-condition` es **critica**: limita el acceso a tokens emitidos para este repo concreto.

```
gcloud iam workload-identity-pools providers create-oidc github-provider \
    --location=global \
    --workload-identity-pool=github-pool \
    --display-name="GitHub Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository=='jeronimosanchez/cx-automation-template'" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --project=floristeria-petal-digital
```

> Si quieres restringir aun mas (p. ej. solo `main`), anade a la condicion:
> `&& assertion.ref=='refs/heads/main'`. Esto rompe el `qa.yml` de PRs — usar con cuidado.

**Verifica:**

```
gcloud iam workload-identity-pools providers describe github-provider \
    --location=global \
    --workload-identity-pool=github-pool \
    --project=floristeria-petal-digital
```

Debe mostrar el `attributeCondition` aplicado y `state: ACTIVE`.

---

## Paso 5 — Permitir que el repo GitHub use el SA

Vincula la identidad federada del repo (cualquier ejecucion del repo) al SA, dandole permiso de impersonacion.

```
PROJECT_NUMBER=$(gcloud projects describe floristeria-petal-digital --format="value(projectNumber)")

gcloud iam service-accounts add-iam-policy-binding \
    cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/jeronimosanchez/cx-automation-template" \
    --project=floristeria-petal-digital
```

**Anota el `PROJECT_NUMBER`** que devuelve `gcloud projects describe` — lo necesitas en el Paso 6.

**Verifica:**

```
gcloud iam service-accounts get-iam-policy \
    cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com \
    --project=floristeria-petal-digital
```

Debe aparecer un binding `roles/iam.workloadIdentityUser` con el `principalSet://...attribute.repository/jeronimosanchez/cx-automation-template`.

---

## Paso 6 — Configurar GitHub Repository Variables

Con `PROJECT_NUMBER` del paso anterior, configura **dos Variables** (NO Secrets — no son sensibles, solo identifiers).

Ve a:
`https://github.com/jeronimosanchez/cx-automation-template/settings/variables/actions`

Y crea:

| Nombre | Valor |
|---|---|
| `GCP_WIF_PROVIDER` | `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider` |
| `GCP_SERVICE_ACCOUNT` | `cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com` |

Sustituye `<PROJECT_NUMBER>` por el valor real (el numero, no el ID).

**O via `gh` CLI:**

```
gh variable set GCP_WIF_PROVIDER \
    --body "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/providers/github-provider" \
    --repo jeronimosanchez/cx-automation-template

gh variable set GCP_SERVICE_ACCOUNT \
    --body "cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com" \
    --repo jeronimosanchez/cx-automation-template
```

**Verifica:**

```
gh variable list --repo jeronimosanchez/cx-automation-template
```

Deben aparecer ambas.

---

## Paso 7 — Test E2E del workflow

Con la configuracion ya en sitio, valida punta-a-punta sin tocar produccion.

1. Crea una rama feature:
   ```
   git checkout -b feature/test-cicd
   ```

2. Anade un cambio trivial (un comentario en el README, por ejemplo):
   ```
   echo "" >> README.md
   git add README.md
   git commit -m "test: validacion E2E del workflow QA"
   ```

3. Push:
   ```
   git push -u origin feature/test-cicd
   ```

4. Abre `https://github.com/jeronimosanchez/cx-automation-template/actions` y verifica que `QA Promptfoo` se dispara y termina **OK** (puede tardar 2-5 min).

5. Abre PR a `main`. Verifica que `QA Promptfoo` se dispara de nuevo (esta vez con trigger `pull_request`).

6. Merge el PR. **Verifica** que `Deploy to Petal CX` se dispara tras el merge y termina OK.

7. Comprueba que se creo una Version snapshot:
   ```
   python act/push_versions.py --list --flow "Default Start Flow"
   ```
   Debes ver una Version nueva con descripcion `Auto deploy <sha>`.

Si todos los pasos pasan, **CI/CD esta operativo**.

---

## Troubleshooting

### `Error 403: Permission 'iam.serviceAccounts.getAccessToken' denied`

El binding del Paso 5 no quedo aplicado o el `principalSet://` esta mal escrito (con espacios, sin escapar, etc).

```
gcloud iam service-accounts get-iam-policy \
    cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com
```

Compara con la cadena exacta del Paso 5. Si el binding falta, vuelve a aplicarlo.

### `Error 403: Permission 'dialogflow.examples.list' denied`

Falta el rol del Paso 2. Aplicalo y espera 1-2 min para que IAM propague.

### Workflow falla en `google-github-actions/auth@v2`

- Comprueba que `GCP_WIF_PROVIDER` y `GCP_SERVICE_ACCOUNT` existen en GitHub Variables.
- Comprueba que el provider tiene `attribute-condition` con el repo correcto (Paso 4).
- Comprueba `permissions: { id-token: write }` en el job.

### `assertion.repository` no coincide

Si fork-easte el repo, la condicion del Paso 4 esta hardcoded a `jeronimosanchez/cx-automation-template`. Edita el provider para tu repo:

```
gcloud iam workload-identity-pools providers update-oidc github-provider \
    --location=global \
    --workload-identity-pool=github-pool \
    --attribute-condition="assertion.repository=='<TU_USER>/<TU_REPO>'" \
    --project=floristeria-petal-digital
```

### Promptfoo falla con `detectIntent` 401/403

El SA no tiene permisos sobre el agente. Verifica Paso 2 y revisa que `definitions/agent.yaml` apunta al `agent_id` correcto del proyecto.

### El deploy crea una Version nueva en cada commit

Es esperado: cada push a `main` genera un snapshot inmutable. Si quieres reducir el numero, limita el trigger a tags o paths concretos en `deploy.yml`.

---

## Rollback

### Desactivar temporalmente CI/CD

Sin tocar IAM, basta con borrar las dos GitHub Variables:

```
gh variable delete GCP_WIF_PROVIDER --repo jeronimosanchez/cx-automation-template
gh variable delete GCP_SERVICE_ACCOUNT --repo jeronimosanchez/cx-automation-template
```

Los workflows seguiran disparandose pero fallaran limpio en `google-github-actions/auth@v2`. Si quieres que ni se disparen, anade `if: false` al `jobs.deploy` (y `jobs.qa`).

### Eliminar toda la configuracion GCP

> Operacion **destructiva**. Asegurate de que ningun otro repo usa el pool `github-pool`.

```
# 1. Eliminar el binding del SA
gcloud iam service-accounts remove-iam-policy-binding \
    cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-pool/attribute.repository/jeronimosanchez/cx-automation-template"

# 2. Eliminar el provider
gcloud iam workload-identity-pools providers delete github-provider \
    --location=global \
    --workload-identity-pool=github-pool

# 3. Eliminar el pool
gcloud iam workload-identity-pools delete github-pool --location=global

# 4. Quitar el rol del SA
gcloud projects remove-iam-policy-binding floristeria-petal-digital \
    --member="serviceAccount:cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com" \
    --role="roles/dialogflow.admin"

# 5. Eliminar el SA
gcloud iam service-accounts delete \
    cx-template-deployer@floristeria-petal-digital.iam.gserviceaccount.com
```

### Rollback parcial (revocar acceso a una rama concreta)

Edita la `attribute-condition` del Paso 4 para excluirla:

```
--attribute-condition="assertion.repository=='jeronimosanchez/cx-automation-template' && assertion.ref!='refs/heads/sandbox'"
```

---

## Referencias

- [Workload Identity Federation con GitHub (Google docs oficial)](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)
- [`google-github-actions/auth`](https://github.com/google-github-actions/auth)
- [Brief Sprint 4 (Notion)](https://www.notion.so/35abe9ca922e81f88371d591749ff01c)
