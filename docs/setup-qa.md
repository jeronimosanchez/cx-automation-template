# Setup QA — Sprint 6 (Fáse B humano)

Esta guía cubre los pasos manuales que Jero debe ejecutar **una sola vez** para
activar el pipeline QA y la publicación de reportes en GitHub Pages. La parte de
código está terminada (Fáse A, autopilot). Esta Fáse B no la ejecuta Claude Code.

> **Tiempo estimado:** 10–15 min.
> **Referencia:** EP-QA-02 (ACT_Backlog).

---

## Resumen del flujo

```
push a main  ─►  workflow_dispatch en Actions  ─►  qa.yml
                                                     │
                                ┌────────────────────┴────────────────────┐
                                │                                         │
                          python qap/test_qa_playbooks.py        upload-artifact
                          (29 TCs vs Default Env CX)                (descarga directa)
                                │
                                ▼
                          reports/qa_<TS>.{html,txt}
                          reports/qa_latest.{html,txt}
                                │
                                ▼
                          peaceiris/actions-gh-pages
                                │
                                ▼
                          rama gh-pages, ruta /qa/
                                │
                                ▼
   https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.html
   https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.txt
```

Email de GitHub Actions notifica con link al run y al reporte tras cada ejecución.

---

## Paso 1 — Verificar permisos del workflow

Necesario para que `peaceiris/actions-gh-pages` pueda hacer push a la rama
`gh-pages`.

1. Ir a `https://github.com/jeronimosanchez/cx-automation-template/settings/actions`.
2. Sección **Workflow permissions** → seleccionar **Read and write permissions**.
3. Marcar **Allow GitHub Actions to create and approve pull requests** (opcional).
4. Save.

> Sin este paso el primer run fallará en el step *"Publish reports to GitHub Pages"*
> con error `Permission denied to push to gh-pages`.

---

## Paso 2 — Crear la rama `gh-pages` (solo la primera vez)

Si la rama no existe todavía, `peaceiris/actions-gh-pages@v3` la crea
automáticamente en el primer run con `keep_files: true`. **No es necesario
crearla manualmente.**

Si prefieres crearla a mano para tener la URL pública lista antes del primer run:

```bash
git checkout --orphan gh-pages
git rm -rf .
echo "# QA reports" > README.md
git add README.md
git commit -m "init gh-pages"
git push origin gh-pages
git checkout main
```

---

## Paso 3 — Activar GitHub Pages

1. Ir a `https://github.com/jeronimosanchez/cx-automation-template/settings/pages`.
2. **Source:** Deploy from a branch.
3. **Branch:** `gh-pages` · **Folder:** `/ (root)`.
4. Save.
5. GitHub muestra un banner: *"Your site is ready to be published at
   https://jeronimosanchez.github.io/cx-automation-template/"*. La activación
   puede tardar 1-2 min la primera vez.

> Si la rama `gh-pages` no existe todavía, el selector la mostrará tras el primer
> run del workflow. En ese caso, ejecuta el workflow primero (Paso 5) y vuelve
> aquí.

---

## Paso 4 — Verificar notificaciones por email

1. Perfil GitHub → **Settings** → **Notifications**.
2. Sección **Actions**:
   - **Send notifications for** → marca al menos `Failed workflows only` (o
     `Workflow runs on repositories I'm watching` para todo).
   - Verifica que el email de destino es `jerosan1@gmail.com`.
3. Save.

---

## Paso 5 — Test E2E del workflow

1. Ir a `https://github.com/jeronimosanchez/cx-automation-template/actions`.
2. Seleccionar el workflow **QA Petal** en el panel izquierdo.
3. Botón **Run workflow** → branch `main` → **Run workflow**.
4. Esperar a que el run termine (≈ 3-5 min para 29 TCs × 1 run).

### Verificaciones

| Comprobación | Cómo |
|---|---|
| Run completado | Estado verde o rojo (en fase 1 con `continue-on-error` el step QA puede salir en warning). El run global debería ser verde. |
| Artifact descargable | En la página del run → sección **Artifacts** → `qa-reports-<run_id>` con HTML + TXT. |
| URL pública accesible | `https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.html` carga el reporte. |
| URL TXT accesible | `https://jeronimosanchez.github.io/cx-automation-template/qa/qa_latest.txt` carga el txt plano. |
| Email recibido | Bandeja de `jerosan1@gmail.com` con notificación del run y link. |

> La primera publicación a `gh-pages` puede tardar 1-2 min en propagarse a la URL
> pública tras el merge a la rama. Si la URL devuelve 404 inmediato, espera y
> recarga.

---

## Cierre del círculo con Claude (sesión web)

Una vez activo el pipeline, el flujo de análisis con Claude desde sesión web es:

1. Tras un run, Jero recibe email con link al reporte.
2. Jero copia la URL `qa_latest.txt` (o la específica `qa_<TS>.txt` de ese run).
3. En sesión web de Claude.ai, pega: *"Analiza este reporte y propón soluciones
   para los FAIL: <URL>"*.
4. Claude usa WebFetch para leer el TXT (formato plano optimizado para LLM) y
   propone fixes.

---

## Troubleshooting

| Síntoma | Causa probable | Fix |
|---|---|---|
| Run falla en *Auth to GCP via WIF* | `GCP_WIF_PROVIDER` o `GCP_SERVICE_ACCOUNT` mal configurados | Revisar Settings → Secrets and variables → Actions → Variables. |
| Run falla en *Publish reports* con `permission denied` | Paso 1 no completado | Activar Read and write permissions en Settings → Actions → General. |
| URL pública devuelve 404 | Pages no activado o rama gh-pages no existe | Paso 3 + esperar primer run a completar. |
| Email no llega | Notificaciones no activadas | Paso 4 + revisar spam. |
| Reportes generados pero `qa_latest.*` no actualiza | `keep_files: true` con conflicto raro | Editar `.github/workflows/qa.yml`: cambiar a `keep_files: false` (sobrescribe todo el `/qa/`). |

---

## Siguiente paso

Si todo funciona end-to-end, marca **EP-QA-02 = Done** en ACT_Backlog y
desbloquea las épicas dependientes (EP-QA-03, EP-QA-04).

Si algo no funciona, abre un ticket en S64 con el error concreto y el run_id.
