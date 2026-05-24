# Memoria del proyecto — cx-automation-template

Organizada en 5 carpetas según capa y estado. **Lee la sección que aplique a tu sesión** antes de empezar.

---

## 📋 SESIONES_ACTIVAS.md ← LEE ESTO PRIMERO

Lista de sesiones paralelas trabajando en este proyecto, qué archivos toca cada una, y qué NO debes pisar. Actualiza tu entrada al empezar/cerrar.

→ [SESIONES_ACTIVAS.md](SESIONES_ACTIVAS.md)

---

## 🌐 `shared/` — contexto transversal (toda sesión puede leer)

Aprendizajes, políticas y feedback que valen para cualquier capa (Petal o Automatización) y cualquier sesión.

- [`shared/feedback_validation_scope.md`](shared/feedback_validation_scope.md) — parar cuando el flujo principal está probado; no investigar subdetalles secundarios.
- [`shared/feedback_gh_run_view_logs.md`](shared/feedback_gh_run_view_logs.md) — `gh run view --log-failed` para inspeccionar fallos sin envoltura.
- [`shared/feedback_iteration_pattern_qa_loop.md`](shared/feedback_iteration_pattern_qa_loop.md) — patrón "lanza/dale" del CLAUDE.md §8.3. **ANULADO por política nueva del 16-may** (permiso explícito siempre).
- [`shared/feedback_analysis_decision_execution.md`](shared/feedback_analysis_decision_execution.md) — separar SIEMPRE análisis → decisión → ejecución. "No permisos" aplica solo dentro de ejecución, no salta la decisión.
- [`shared/feedback_tono_y_lenguaje.md`](shared/feedback_tono_y_lenguaje.md) — nunca copiar coloquialismos de Jero ("tiro", "dale", "lanza"). Tono formal, directo y cercano usando mi propio registro.
- [`shared/feedback_qa_runs1_flakiness.md`](shared/feedback_qa_runs1_flakiness.md) — QA `--runs 1` tiene flakiness ±2-3 TCs.
- [`shared/learning_diseno_conversacional_enterprise.md`](shared/learning_diseno_conversacional_enterprise.md) — patrón híbrido NLU+LLM, distinción clasificación vs slot-filling.

---

## 🌸 `petal/` — Capa Petal (caso de uso: florería)

Decisiones, pendientes y aprendizajes específicos del agente Petal (no reusables para otros clientes).

- [`petal/pendiente_refactor_compra.md`](petal/pendiente_refactor_compra.md) — Compra ~11.4k tokens. Plan: sub-playbook ConsultaInventario como Task. Anti-regresión: 49 TCs actuales.

---

## ⚙️ `automatizacion/` — Capa Automatización CD (template/infra)

Aprendizajes y pendientes del template reusable (sirve para Petal y futuros clientes como Farma).

- [`automatizacion/estrategia_comercial_consultoria.md`](automatizacion/estrategia_comercial_consultoria.md) — posicionamiento como consultor frente a vendors (Google CX, AWS, Microsoft, Rasa). Trade-off de créditos POC vs credibilidad. Recomendación: independiente declarado hasta tener 5-10 clientes, luego multi-partner declarado.
- [`automatizacion/mercado_renovacion_legacy.md`](automatizacion/mercado_renovacion_legacy.md) — mercado de renovación de sistemas conversacionales legacy (IVR, Dialogflow ES→CX, LUIS, Watson, chatbots 1ª gen). Por qué es mejor que greenfield. Segmentos, pitch, posicionamiento mid-market vs grandes consultoras, 7 piezas faltantes, cadena estratégica 1-18 meses.
- [`automatizacion/deuda_analisis_dependencias_TC.md`](automatizacion/deuda_analisis_dependencias_TC.md) — deuda técnica: análisis de causa raíz común entre TCs que fallan. Hoy cada TC aislado, no se sabe por dónde empezar a fixear. Abordar cuando suite >50 TCs o release con >10 FAILs simultáneos. ~3 días de sprint.
- [`automatizacion/epic_optimizar_analisis_QA.md`](automatizacion/epic_optimizar_analisis_QA.md) — épica: reducir alucinaciones del skill `qa-tc-analyzer` inyectando contexto verificable (git log, memoria, gh pr list). 4 historias de usuario + criterios de aceptación. ~2 días de sprint. Detectado en demo 21-may por divergencia entre análisis chat (verificable) y análisis del skill (con invenciones).
- [`automatizacion/epic_backlog_conversational_design.md`](automatizacion/epic_backlog_conversational_design.md) — **épica precursora**: construir el Backlog de Conversational Design (user stories, políticas, decisiones, roadmap, changelog narrativo). Hoy ese conocimiento vive en la cabeza de Jero. Pre-requisito de la épica anti-alucinación. ~8 días, incrementales en 4-6 semanas.
- [`automatizacion/proceso_analisis_qa.md`](automatizacion/proceso_analisis_qa.md) — puntero al documento maestro del proceso de análisis QA. **Fuente real:** `docs/qa_analysis_process.md` en el repo. Allí está la versión activa (v1.0), la propuesta (v1.1), el caso testigo TC-URGENCIA-01 y el changelog.
- [`automatizacion/epic_benchmark_skills_qa.md`](automatizacion/epic_benchmark_skills_qa.md) — épica: benchmark comparativo entre versiones del skill qa-tc-analyzer con KPIs cuantitativos (tiempo, tokens, % fix acierta) y cualitativos (calidad, alucinaciones). Permite A/B testing real. ~1 día construir + 0.5 día por benchmark. Abordar cuando v1.1 esté completa.
- [`automatizacion/arquitectura_sistema_hibrido_local_cloud.md`](automatizacion/arquitectura_sistema_hibrido_local_cloud.md) — arquitectura objetivo del sistema completo: divergencia local (M4 + Ollama + multi-agente) + convergencia cloud (Claude). 8 capas, ~40-65€/ciclo, escalable 1:N. Service Model AI-native. **Decisión 22-may**: benchmarkear 30-50 candidatos técnicamente viables (no top 10 filtrado humano) — el humano sube de filtro mid-funnel a decisor estratégico final. Pre-requisitos: bottom-up Petal + comparison engine + adversarial. Sprint S10-S11. PoC inicial de 2-3 días antes de comprometer construcción completa.
- [`automatizacion/vision_dashboard_qa_interactivo.md`](automatizacion/vision_dashboard_qa_interactivo.md) — visión post v2.0: dashboard QA pasa de HTML estático a interactivo con chat IA sobre los datos de análisis (patrones cruzados, ROI de fixes, drill-down conversacional). NO implementar ahora; documentado para no perderlo.

---

## 🟢 `current/` — estado activo

Estado en curso del proyecto. Lo que cualquier sesión nueva debería leer para saber dónde estamos.

- [`current/estado_actual.md`](current/estado_actual.md) — estado al 17-may: 7 PRs cerrados, suite 49 TCs, agente 95% real (98% efectivo). Plan inmediato: validar HTML rediseñado (PR #65) + fix TC-IMPOSIBLE-01 + fallback escalonado TC-DECO-02.
- [`current/proximo_sprint_ingenieria_inversa.md`](current/proximo_sprint_ingenieria_inversa.md) — siguiente Sprint post-QA: bottom-up Petal (TCs → stories → epics → roadmap → brief). 4 días. Convierte Petal de "en cabeza de Jero" a producto documentado vendible. Arrancar SOLO cuando QA automations estén cerradas.

---

## 📦 `archived/` — memorias de sesiones cerradas

Lo que ya no aplica pero se conserva por trazabilidad histórica.

- [`archived/pendientes_post_sprint7_14may.md`](archived/pendientes_post_sprint7_14may.md) — estado al 14-may, antes de la sesión 16/17-may. **Obsoleto** (las métricas han mejorado).

---

## Convención al añadir nueva información

| Tipo de info | Dónde guardar |
|---|---|
| Aprendizaje transversal (vale para cualquier cliente) | `shared/` |
| Decisión/aprendizaje específico de Petal (florería) | `petal/` |
| Decisión/aprendizaje sobre el template/infra | `automatizacion/` |
| Estado actual del trabajo en curso | `current/` |
| Handoff antes de cerrar sesión por tokens | `current/handoff_YYYY-MM-DD_<sesion>.md` |
| Memorias obsoletas | `archived/` (cuando ya no apliquen) |
| Sesiones activas | actualiza `SESIONES_ACTIVAS.md` |

---

## Política vigente (20-may, aclaración)

**Lenguaje:** no usar "lanza"/"dale" en el output (suena informal). Usar verbos directos en mi propio registro.

**Comportamiento:** lo que se quitó fue el coloquialismo, NO la auto-ejecución. Las operaciones read-only y de análisis (gcloud read, curl GET, gh run view, leer logs, ejecutar scripts QA conocidos, leer ficheros locales) siguen auto-ejecutándose sin preguntar.

**Permiso explícito sigue requerido para:** `git commit`, `git push`, `gh pr create/merge`, modificar archivos del repo (Edit/Write sobre el código fuente). Para escrituras a API GCP/IAM/CX. Para instalar dependencias.

**Regla práctica:** si dudo si una operación es trivial, primero ampliar `settings.local.json` para que la próxima vez no pregunte.

**Reglas específicas (20-may):**
- **1 QA test** = auto, sin preguntar.
- **Hasta 3 QA seguidos** = auto, sin preguntar.
- **Más de 3 QA en 5 min** = pedir permiso (puede ser abuso de tokens o loop infinito).
- **Suite QA completa (29 TCs)** = pedir permiso (cuesta más, ~0,30€).
- **Wait for deploy / polling con `until ... gh run`** = auto (read-only).
- **`git push` (que dispara deploy)** = SIEMPRE pedir permiso (modifica producción).
- **`gh pr create/merge`** = SIEMPRE pedir permiso.

**Heurística "read-only = auto-OK" (20-may):**
Si un comando solo lee (sin `>`, `>>`, `--out`, `--write`, sin `requests.post/patch/delete`, sin escrituras a APIs GCP/IAM, sin `pip install`, sin `git push/commit/checkout -b`) → auto-aprobar. Incluye: WebFetch, WebSearch, `python -c` leyendo locales, `curl -s` GET, `gcloud logging read`, `gh run view/list/watch`, `grep`, `find`, `cat`, `head`, `tail`, `git diff/log/status/show`.

---

## URLs públicas de Jero

| Recurso | URL |
|---|---|
| Portfolio personal (GitHub Pages) | https://jeronimosanchez.github.io |
| Repo del portfolio | https://github.com/jeronimosanchez/jeronimosanchez.github.io |
| Repo principal (ACT) | https://github.com/jeronimosanchez/cx-automation-template |
| Repo Petal (privado) | https://github.com/jeronimosanchez/Petal |
| Repo petal-sheet-api (privado) | https://github.com/jeronimosanchez/petal-sheet-api |
| Backend Petal (Cloud Run) | https://petal-sheet-api-920225907399.europe-west1.run.app |
| Reports QA (GitHub Pages) | https://jeronimosanchez.github.io/cx-automation-template/qa/ |
| Consola CX del agente Petal | https://dialogflow.cloud.google.com/cx/projects/floristeria-petal-digital/locations/europe-west1/agents/745375ba-ac7e-4eb8-b8a0-d742891f2aa4 |
