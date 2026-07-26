# Pipeline ACT — Documento de diseño

Versión: draft | Fecha: 2026-07-27 | Autor: Claude Code

> Especifica el rediseño del pipeline ACT para cubrir las tres brechas identificadas:
> diff unificado, cobertura de artefactos CX, y corrección del flujo de snapshot.
> Cada sección parte del estado actual (leído directamente del código) antes de proponer cambios.

---

## Flujo de 3 pasos — arquitectura definitiva

Se descarta el flujo anterior de 5 pasos. El nuevo pipeline tiene 3 pasos:

```
1. Commit   → git commit (local)                        — snapshot local del código
2. Push     → git push → GitHub + push_*.py → CX Draft  — sube al remoto y deploya al agente
3. Staging  → snapshot + apuntar Staging                — promoción a entorno estable para QA
```

**Reglas del flujo:**
- El orden 1→2→3 es obligatorio
- Los pasos 1 y 2 son repetibles — se pueden ejecutar N veces antes de avanzar al siguiente
- El paso 3 es una decisión consciente: solo cuando el Draft está listo para QA

**Por qué los pasos 2 y 3 van juntos:**
GitHub y CX Draft se ejecutan en el mismo paso de forma deliberada. La justificación: en un contexto de developer solo, cada push a GitHub es siempre un deploy intencionado — no hay riesgo de push accidental sin querer deployar. Separar los dos pasos añadiría fricción sin ningún beneficio real.

Esta es una decisión de diseño adaptada al contexto, no una limitación técnica. En un equipo con múltiples developers y Pull Requests, el paso 2 se separaría en push a rama + merge + deploy automático vía CI/CD.

**Por qué 3 pasos y no 5:**
- Draft CX es el destino del deploy del paso 2, no un paso de confirmación independiente
- Snapshot y Staging son una sola operación atómica
- Esta separación es la arquitectura estándar GitOps adaptada a un contexto de developer solo

---

## 1. Diff completo — rediseño

### Estado actual

`act/diff.py` es una función pura que compara **dos diccionarios Python** campo a campo y devuelve un `DiffResult` con `needs_update`, `update_mask` y `patch_payload`. No hace red, no conoce git, no conoce GitHub.

`act/deploy.py` usa `git diff --name-only HEAD` para detectar **nombres de archivos** modificados (no el contenido de los cambios). Cada `push_*.py` ejecuta su propio diff interno (LIST CX → diff_resource → PATCH/POST), pero ese resultado no se agrega en ningún sitio.

Hoy existen **tres comparaciones distintas** que el pipeline necesita pero ninguna está unificada:

| Dimensión | Hoy | Problema |
|---|---|---|
| Local vs último commit | `git diff --name-only HEAD` en deploy.py | Solo nombres de archivo, no contenido |
| Local vs CX | Cada push_*.py lo hace internamente | No hay vista agregada antes de ejecutar |
| Local vs GitHub remoto | No existe | Sin visibilidad de divergencia local/remoto |

### Diseño propuesto: `diff.py` rediseñado

El `diff.py` actual se **mantiene tal como está** (es útil para los push scripts). Se crea un nuevo módulo `act/diff_pipeline.py` con tres modos de operación independientes y una vista agregada.

#### Modo 1 — Local vs último commit (`--git`)

**Qué hace:** ejecuta `git diff HEAD --name-only` y `git ls-files --others --exclude-standard definitions/` para encontrar archivos modificados o nuevos.

**Qué devuelve:**

```
{
  "modified": ["definitions/playbooks/Compra.yaml", "definitions/intents/comprar_flores.yaml"],
  "added":    ["definitions/examples/Compra/exh.yaml"],
  "deleted":  [],
  "areas":    ["playbooks", "examples", "intents"]
}
```

**Por qué importa:** `deploy.py` ya hace esto parcialmente, pero sin distinguir modified/added/deleted. Con deleted se puede detectar si un artefacto local fue borrado (acción que hoy no se propaga a CX).

#### Modo 2 — Local vs CX (`--cx`)

**Qué hace:** para cada recurso cubierto, hace LIST en CX y compara contra el YAML local usando `diff_resource`. Agrega los resultados.

**Qué devuelve:**

```
{
  "playbooks": {
    "Compra":     {"status": "changed", "fields": ["instruction.steps"]},
    "Handoff":    {"status": "ok"},
    "Nuevo_PB":   {"status": "local_only"}   # existe local, no en CX
  },
  "intents": {
    "comprar_flores": {"status": "remote_only"}  # existe en CX, no local
  },
  ...
  "summary": {"ok": 42, "changed": 3, "local_only": 1, "remote_only": 2}
}
```

**Por qué importa:** hoy no hay forma de saber "qué hay en CX que no está en definitions/" sin ejecutar todos los push scripts. Esto es la base de la detección de deriva.

#### Modo 3 — Local vs GitHub remoto (`--github`)

**Qué hace:** ejecuta `git fetch origin --dry-run` y `git diff HEAD origin/main --name-only` para detectar archivos que están en local pero no en el remoto, o viceversa.

**Qué devuelve:**

```
{
  "local_ahead":  ["definitions/examples/Compra/exh.yaml"],
  "remote_ahead": [],
  "diverged":     false
}
```

**Por qué importa:** detecta trabajo local sin push que podría perderse, o cambios en remoto que no se han bajado.

#### Vista agregada (`--all` o sin flags)

Ejecuta los tres modos y combina los resultados en una tabla ASCII:

```
Área           Git        CX         GitHub
─────────────────────────────────────────────
playbooks      2 cambios  1 drift    ok
examples       1 nuevo    ok         pendiente
intents        ok         1 drift    ok
...
```

---

## 2. Push y Pull — mantener sin cambios

Los `push_*.py` y `pull_*.py` están en buen estado y no requieren modificaciones.

**Push scripts** (`push_agent_config.py`, `push_entity_types.py`, `push_flows.py`, `push_pages.py`, `push_intents.py`, `push_webhooks.py`, `push_generators.py`, `push_tools.py`, `push_playbooks.py`, `push_examples.py`, `push_environments.py`, `push_versions.py`):
- Patrón uniforme: `LIST CX → diff_resource → PATCH si cambios / POST si nuevo`
- Traducen YAML local → payload JSON para la API de CX
- Idempotentes: solo tocan lo que cambió
- Excepción documentada: `push_playbooks.py` usa Full Update (sin `updateMask`) por el bug de `europe-west1` registrado en CLAUDE.md §3.8

**Pull scripts** (`pull_agent_config.py`, `pull_entity_types.py`, `pull_flows.py`, `pull_pages.py`, `pull_intents.py`, `pull_webhooks.py`, `pull_generators.py`, `pull_tools.py`, `pull_playbooks.py`, `pull_examples.py`, `pull_environments.py`, `pull_versions.py`):
- Descargan el estado actual de CX → YAML en `definitions/`
- Útiles para sincronización inversa cuando alguien modifica directamente en la consola de CX
- No sustituyen al pipeline de CI/CD: su uso es puntual y manual

---

## 3. Cobertura de artefactos CX

### Recursos de la API Dialogflow CX v3 (europe-west1)

| Recurso | Script ACT | Estado |
|---|---|---|
| Agents | `push_agent_config.py` / `pull_agent_config.py` | Cubierto |
| Flows | `push_flows.py` / `pull_flows.py` | Cubierto |
| Pages | `push_pages.py` / `pull_pages.py` | Cubierto |
| Intents | `push_intents.py` / `pull_intents.py` | Cubierto |
| Entity Types | `push_entity_types.py` / `pull_entity_types.py` | Cubierto |
| Webhooks | `push_webhooks.py` / `pull_webhooks.py` | Cubierto |
| Generators | `push_generators.py` / `pull_generators.py` | Cubierto |
| Tools | `push_tools.py` / `pull_tools.py` | Cubierto |
| Playbooks | `push_playbooks.py` / `pull_playbooks.py` | Cubierto |
| Examples | `push_examples.py` / `pull_examples.py` | Cubierto |
| Environments | `push_environments.py` / `pull_environments.py` | Cubierto |
| Versions | `push_versions.py` / `pull_versions.py` | Cubierto |
| Session Entity Types | — | No aplica (ver abajo) |
| TransitionRouteGroups | — | No aplica (ver abajo) |
| Experiments | — | Fuera de scope (ver abajo) |
| TestCases | — | Línea QAP, no ACT |
| Changelogs | — | Read-only, no desplegable |
| Deployments | — | Read-only, historial |
| Agent Validations | — | Candidato futuro (ver abajo) |

### Análisis de los no cubiertos

**Session Entity Types — no aplica.**
Son entidades de sesión que viven en runtime (dentro de una conversación activa). No son configuración desplegable: se crean y destruyen dentro de una sesión. Sin fichero YAML que gestionar.

**TransitionRouteGroups — no aplica para Petal.**
Son grupos de rutas de transición asociados a Flows en el modelo NLU clásico de CX. Petal 1.x usa arquitectura basada en Playbooks (LLM-pure), no en Flows+NLU. Los Flows de Petal son mínimos (Default Start Flow como contenedor). No hay TransitionRouteGroups configurados.

**Experiments — fuera de scope.**
Son experimentos A/B sobre versiones del agente. La gestión de Experiments requiere criterio humano en cada caso (qué variante, qué split, qué métrica). No es automatizable como despliegue declarativo. Si Petal llega a usar Experiments, se gestionarían manualmente desde la consola.

**TestCases — pertenece a la línea QAP.**
La API de TestCases permite crear y ejecutar test cases directamente desde CX. La línea QAP tiene su propia gestión de TCs. Si se automatiza el push/pull de TCs hacia la API de CX, corresponde a QAP, no a ACT.

**Changelogs y Deployments — read-only.**
Son registros de auditoría que genera CX automáticamente. No hay nada que desplegar.

**Agent Validations — candidato para auditoría.**
La API permite lanzar una validación del agente (detecta referencias rotas, configuraciones inconsistentes). No es un recurso desplegable, pero sí es útil como paso de comprobación post-deploy. Se propone como extensión del sistema de validación (ver sección 4).

---

## 4. Sistema de validación

### Estado actual

**`validate_api.py`** — estado: **funcional, mantener**.
- Valida conectividad + 9 capacidades básicas de la API
- Auth correcto: `gcloud auth print-access-token`
- Crea un Example dummy, ejecuta pruebas, limpia al final
- Resultado probado en sesiones anteriores: 9/9 PASS

**`validate_api_v2.py`** — estado: **bugs, candidato a eliminar** (ver sección 6).
- Auth incorrecto: usa `google.auth.default()` en lugar de `gcloud auth print-access-token`
- Valida 4 casos edge (PATCH con updateMask, displayName duplicado, tamaño máximo, paginación profunda)
- Los hallazgos de sus tests están ya documentados en CLAUDE.md §3 y en la implementación de los push scripts

### Propuesta: sistema de validación en dos niveles

#### Nivel 1 — Conectividad (existente, mantener)

`validate_api.py` se mantiene sin cambios. Se ejecuta manualmente cuando hay dudas sobre auth o conectividad. No forma parte del pipeline automático.

#### Nivel 2 — Smoke test de extremo a extremo (nuevo)

Un `validate_pipeline.py` que verifica que cada push script funciona correctamente en modo end-to-end, sin necesidad de tener cambios reales que desplegar:

- Para cada recurso cubierto: ejecuta el push script en `--dry-run` y verifica que no hay errores de auth, schema o conectividad
- Verifica que `diff_resource` detecta correctamente un cambio sintético
- Verifica que la rotación de versiones funciona (lista, cuenta, no está en el límite)
- Verifica que el Environment staging apunta a una versión válida

Este nivel no muta nada en CX (todo `--dry-run` o GET). Se puede ejecutar en CI/CD como paso previo al deploy real.

#### Nivel 3 — Auditoría de consistencia (nuevo, parte del diff rediseñado)

Cubierto por `diff_pipeline.py --cx` (sección 1). Detecta deriva entre `definitions/` y CX sin ejecutar ningún push. Útil para detectar:
- Recursos en CX que no están en `definitions/` (posible edición manual en consola)
- Recursos en `definitions/` que no están en CX (posible fallo de deploy anterior)

---

## 5. Flujo de snapshot según CX

### El bug actual

`act/deploy.py` en modo "Reemplazar snapshot anterior" ejecuta:

```
1. DELETE version antigua  ←── BUG: staging aún apunta a ella
2. POST /versions          (crea snapshot nuevo, LRO)
3. PATCH /environments     (apunta staging al nuevo snapshot)
```

El paso 1 falla con error 400/409 porque el Environment staging referencia la versión que se intenta borrar. CX no permite borrar una versión referenciada por un environment activo.

### Flujo correcto

El orden que nunca falla:

```
┌─────────────────────────────────────────────────────────────┐
│                   FLUJO CORRECTO DE SNAPSHOT                │
└─────────────────────────────────────────────────────────────┘

  ESTADO INICIAL
  ┌──────────┐    apunta a    ┌──────────────────┐
  │ staging  │ ─────────────► │ version_antigua  │
  └──────────┘                └──────────────────┘

  PASO 1 — POST /flows/{flow}/versions
  ┌──────────┐                ┌──────────────────┐
  │ staging  │ ─────────────► │ version_antigua  │  (staging sin tocar)
  └──────────┘                └──────────────────┘
                              ┌──────────────────┐
                              │  version_nueva   │  (LRO → poll → done)
                              └──────────────────┘

  PASO 2 — PATCH /environments/{env}  (apuntar staging a la nueva)
  ┌──────────┐                ┌──────────────────┐
  │ staging  │ ──────────┐   │ version_antigua  │  (libre, no referenciada)
  └──────────┘           │   └──────────────────┘
                         └──► ┌──────────────────┐
                              │  version_nueva   │
                              └──────────────────┘

  PASO 3 — DELETE /flows/{flow}/versions/{old}
  ┌──────────┐                   (eliminada)
  │ staging  │ ──────────────► ┌──────────────────┐
  └──────────┘                 │  version_nueva   │
                               └──────────────────┘
```

**Por qué el orden importa:**
- Si se borra la versión antes de reasignar el environment (orden actual 1→3→2), CX rechaza el DELETE porque staging la referencia activamente.
- Si se reasigna el environment primero (orden correcto 1→2→3), la versión antigua queda sin ninguna referencia y el DELETE procede sin restricciones.

### Casos especiales

**Primer deploy (no hay snapshot anterior):**
- Solo se ejecutan pasos 1 y 2 (POST + PATCH). No hay paso 3.
- `deploy.py` ya maneja este caso: si `candidates` está vacío, no ofrece la opción de reemplazar.

**Límite de 20 versiones por flow:**
- Documentado en `push_versions.py` (`_MAX_VERSIONS_PER_FLOW = 20`).
- La función `rotate_versions_if_full()` borra la más antigua por `createTime` antes del POST.
- IMPORTANTE: la rotación automática solo borra versiones no referenciadas. Si todas las versiones están referenciadas por environments, el DELETE fallará y se aborta el create.
- Implicación para el flujo correcto: la rotación debe ejecutarse en el PASO 1, antes del POST, no antes del DELETE del snapshot anterior.

### Cambio a implementar en `deploy.py`

En la función `main()`, en el bloque `if create_snap:`, el orden debe cambiarse de:

```python
# ORDEN ACTUAL (buggy):
delete_version(...)      # paso 1 — falla si staging referencia la versión
create_version(...)      # paso 2
update_staging(...)      # paso 3
```

A:

```python
# ORDEN CORRECTO:
create_version(...)      # paso 1 — POST + LRO polling
version_name = get_latest_version_name(...)
update_staging(...)      # paso 2 — PATCH environment
if replace_snap:
    delete_version(...)  # paso 3 — DELETE seguro, ya no referenciada
```

---

## 6. Eliminación de `validate_api_v2.py` y auditoría del sistema

### Decisión sobre `validate_api_v2.py`

**Propuesta: eliminar.**

Motivos:
1. **Bug de auth estructural**: usa `google.auth.default()` en lugar de `gcloud auth print-access-token`. No es un bug menor — viola la decisión técnica no negociable §3.1 del CLAUDE.md.
2. **Hallazgos ya incorporados**: los 4 tests del v2 generaron conocimiento que está documentado e implementado:
   - Test 10 (PATCH con updateMask): resultado incorporado en `push_playbooks.py` (Full Update para `europe-west1`)
   - Test 11 (displayName duplicado): resultado incorporado en todos los push scripts (LIST previo antes de POST)
   - Test 12 (tamaño máximo): informativo, no genera ninguna restricción operativa
   - Test 13 (paginación profunda): incorporado (`pageSize=100` en todos los LIST)
3. **No se ejecuta**: tiene bugs que impiden correrlo, y nadie lo está usando.

### Sistema de auditoría alternativo

En lugar de `validate_api_v2.py`, el sistema de auditoría del pipeline ACT se articula en tres herramientas:

| Herramienta | Cuándo | Qué detecta |
|---|---|---|
| `validate_api.py` | Manual, ante dudas de conectividad | Auth roto, endpoints caídos, 9 capacidades básicas |
| `diff_pipeline.py --cx` | Manual antes de un deploy crítico | Deriva entre `definitions/` y CX, recursos huérfanos |
| `validate_pipeline.py` (nuevo) | CI/CD como smoke test pre-deploy | Cada push script funciona en dry-run, environments coherentes |

**Auditoría de consistencia** (el hueco real del v2):

`diff_pipeline.py --cx` cubre el caso más importante: detectar qué hay en CX que no está en `definitions/` (deriva por edición manual en consola). Esto es lo que `validate_api_v2.py` nunca llegó a hacer.

**Agent Validations API:**

El endpoint `POST /agents/{agent}/validate` de CX lanza una validación interna del agente (referencias rotas, configuraciones inconsistentes). Se propone añadir una llamada a este endpoint como paso final de `validate_pipeline.py`: después del smoke test, validar el agente y reportar cualquier error de configuración sin modificar nada.

---

## Decisiones pendientes

Las siguientes decisiones requieren aprobación de Jero antes de implementar:

| # | Decisión | Opciones | Impacto |
|---|---|---|---|
| D1 | Corrección del orden en `deploy.py` (1→3→2 → 1→2→3) | Aplicar ahora / diferir | Bugfix en el flujo de reemplazo de snapshot. Bajo riesgo — solo reordena operaciones existentes. |
| D2 | Eliminar `validate_api_v2.py` | Eliminar / mover a `archived/` | Limpieza. Los hallazgos están documentados e incorporados. |
| D3 | Crear `diff_pipeline.py` (nuevo módulo) | Crear / no crear | Añade visibilidad de deriva. No cambia nada existente. |
| D4 | Crear `validate_pipeline.py` (smoke test) | Crear / no crear | Añade gate de calidad en CI/CD. No cambia nada existente. |
| D5 | Cobertura de Agent Validations en post-deploy | Añadir a validate_pipeline / ignorar | Detectaría errores de configuración post-deploy sin mover datos. |
| D6 | Scope de `diff_pipeline.py --github` | Incluir / excluir | El modo GitHub requiere `git fetch` (acceso a red). Determinar si es aceptable en CI/CD. |

---

*Fin del documento. Actualizar tras aprobación de las decisiones pendientes.*

---

## Roadmap de implementación

Las tres piezas pendientes son el nuevo orquestador, `diff_pipeline.py` y GitHub Actions. El orden de implementación se deriva de las dependencias reales entre ellas.

### Análisis de dependencias

| Pieza | Depende de | Bloquea |
|---|---|---|
| Nuevo orquestador | Nada (reemplaza deploy.py, que ya existe) | GitHub Actions |
| `diff_pipeline.py` | Nada (módulo independiente) | Orquestador (upgrade) |
| GitHub Actions | Orquestador estable | — |

**¿Puedes tener GitHub Actions sin el orquestador?** No de forma útil. GitHub Actions invocaría el orquestador: si el orquestador no existe, CI/CD no tiene qué llamar. Se podría llamar directamente a los `push_*.py` desde el workflow, pero eso es el estado anterior al rediseño — no el objetivo.

**¿Puedes tener el orquestador sin `diff_pipeline.py`?** Sí. El orquestador tiene una versión mínima viable que usa `git diff --name-only HEAD` directamente (igual que `deploy.py` hoy). `diff_pipeline.py` es un upgrade: cuando esté listo, el orquestador lo consume para ganar las dimensiones `--cx` y `--github`. No es un bloqueante.

**¿Qué es más urgente para que el pipeline funcione mínimamente?** El orquestador. Es la pieza que coordina los `push_*.py`, gestiona el orden correcto de snapshot (el bug de D1), y elimina la interactividad manual de `deploy.py`. Sin él, las otras dos piezas no tienen dónde encajar.

### Orden recomendado

```
1. Nuevo orquestador
2. generate_inventory.py + inventory.json + inventory.html + deploy_sim.html actualizado
3. diff_pipeline.py
4. GitHub Actions
```

**Paso 1 — Nuevo orquestador**

Es la pieza central. Cubre: detección de cambios por área (usando `git diff` en su versión inicial), selección de los `push_*.py` correspondientes, y gestión del snapshot con el orden correcto (crear → apuntar → borrar). Al terminar este paso, el pipeline de 3 pasos funciona de extremo a extremo de forma local y manual.

Por qué primero: es el único componente que resuelve el bug de snapshot (D1) y que unifica la coordinación de despliegue. Todo lo demás se construye encima.

**Paso 2 — `generate_inventory.py` + `inventory.json` + `inventory.html` + `deploy_sim.html` actualizado**

Una vez el orquestador funciona, el inventario añade visibilidad del estado completo del sistema. Un solo script (`generate_inventory.py`) genera un solo JSON intermedio (`inventory.json`) que alimenta dos HTMLs:

```
generate_inventory.py → inventory.json
                              ↓
              ┌───────────────┴───────────────┐
        inventory.html                  deploy_sim.html
        (vista completa)              (vista filtrada: cambios)
```

Un solo `.py`, un solo JSON, dos HTMLs. Sin duplicar lógica.

Por qué antes de `diff_pipeline.py`: el panel de commits necesita el inventario como fuente de verdad para mostrar qué cambió desde el último commit. Sin `inventory.json`, `deploy_sim.html` no tiene datos que mostrar. La vista filtrada (panel de commits) depende de la vista completa (inventario).

**Paso 3 — `diff_pipeline.py`**

Una vez el inventario existe, `diff_pipeline.py` añade la dimensión de diff de campos: no solo qué artefactos cambiaron, sino qué campos cambiaron dentro de cada artefacto. Consume `inventory.json` y añade el detalle de `diff_resource`. Los modos `--cx` y `--github` son herramientas de diagnóstico independientes del pipeline principal.

Por qué tercero: no bloquea el funcionamiento mínimo del inventario, pero sin él solo se sabe qué artefactos difieren, no qué campos. Desarrollarlo en este paso permite que el orquestador lo adopte antes de automatizarse.

**Paso 4 — GitHub Actions**

Solo cuando el orquestador sea estable. El workflow invoca el orquestador en el paso 2 (push → CX Draft automático) y expone `workflow_dispatch` para el paso 3 (Staging). En este punto el pipeline de 3 pasos queda completamente automatizado.

Por qué último: automatizar antes de que el orquestador esté probado propagaría bugs a CI/CD. GitHub Actions es el contenedor — lo que dentro esté roto, lo automatiza roto.

### Resumen visual

```
Semana N     Semana N+1        Semana N+2        Semana N+3
┌──────────────────┐
│ Nuevo orquestador│ ─────────────────────────────────────► pipeline funcional (manual)
└──────────────────┘
         ┌────────────────────────────┐
         │ HTML inventario + .py      │ ────────────────► inventory.json + panel
         └────────────────────────────┘
                   ┌─────────────────┐
                   │ diff_pipeline.py│ ──────────────► visibilidad 3 dimensiones
                   └─────────────────┘
                             ┌──────────────────┐
                             │ GitHub Actions   │ ──────► pipeline automatizado
                             └──────────────────┘
```

---

## HTML de inventario

### Arquitectura

```
generate_inventory.py → inventory.json
                              ↓
              ┌───────────────┴───────────────┐
        inventory.html                  deploy_sim.html
        (vista completa)              (vista filtrada: cambios)
```

Un solo `.py`, un solo JSON, dos HTMLs. Sin duplicar lógica.

### Estado actual

No existe ningún HTML de inventario en el proyecto. Los archivos HTML publicados en `docs/panels/` son:

- `orquestador.html` — panel del playbook orquestador
- `skills.html` — registro de skills del sistema
- `deploy_sim.html` — simulación interactiva de la skill /deploy (en progreso)

Ninguno muestra el estado de los artefactos de Petal en CX ni compara `definitions/` contra el agente.

### Qué debería mostrar

Un panel `docs/panels/inventory.html` que liste todos los artefactos por tipo con su estado de sincronización:

| Columna | Descripción |
|---|---|
| Área | Tipo de artefacto: playbooks, examples, intents, tools, webhooks, flows, pages, entity_types, generators, environments, versions |
| Nombre | Identificador del artefacto (displayName o nombre de archivo YAML) |
| Local | Existe en `definitions/` (sí/no) |
| CX | Existe en el agente Draft (sí/no) |
| Estado | `ok` (sincronizado) · `changed` (local difiere de CX) · `local_only` (no está en CX) · `remote_only` (no está en `definitions/`) |

El estado se calcula a partir de `diff_pipeline.py --cx`: la vista agregada del modo 2 (local vs CX) es exactamente la fuente de datos que necesita este panel.

El panel incluiría también una fila de resumen por área (N ok / N changed / N local_only / N remote_only) y una marca de tiempo de la última actualización.

### Cómo se actualiza

El inventario se regenera como paso post-deploy, tras el paso 2 (push → CX Draft) o el paso 3 (Staging). El flujo propuesto:

```
deploy paso 2 o 3
  └── generate_inventory.py                 # genera inventory.json (estado local vs CX vs GitHub)
      ├── inventory.html                    # vista completa — todos los artefactos
      └── deploy_sim.html                   # vista filtrada — solo cambios pendientes de commit
          └── git commit docs/panels/
              └── git push → GitHub Pages   # publica automáticamente
```

`generate_inventory_html.py` sería un script de la línea ACT que lee la salida JSON de `diff_pipeline.py --cx` y renderiza el HTML estático. No requiere servidor — GitHub Pages lo sirve como archivo estático.

La regeneración puede integrarse en el GitHub Actions del paso 2: tras el deploy a CX Draft, el workflow llama a `diff_pipeline.py --cx` y publica el HTML actualizado como artefacto de la misma ejecución.

### Dónde viviría

- **Fuente:** `docs/panels/inventory.html`
- **URL pública:** `https://jeronimosanchez.github.io/cx-automation-template/panels/inventory.html`
- **Datos fuente:** `docs/data/inventory.json` (generado por `generate_inventory.py`)
- **Dependencia:** requiere que `generate_inventory.py` (Roadmap paso 2) esté implementado antes de poder regenerarse automáticamente

### Relación con el panel de commits (deploy_sim.html)

El panel de commits (`docs/panels/deploy_sim.html`) se nutre del inventario. El inventario es la fuente de verdad del estado del sistema — `inventory.json` — y el panel de commits es una vista de ese dato filtrada por "qué cambió desde el último commit".

La relación es:
- `inventory.json` — estado completo: todos los artefactos, su estado en local, en CX y en GitHub
- `deploy_sim.html` — vista filtrada: solo los artefactos con cambios desde el último commit
- `inventory.html` — vista completa: todos los artefactos con su estado actual

El HTML del inventario es siempre el mismo archivo (puntero estable en GitHub Pages). Lo que cambia en cada deploy es `inventory.json`, que ambos HTMLs consumen.

### El .py de verificación

`generate_inventory.py` hace:
- Lee `definitions/` — lista todos los YAMLs por tipo de artefacto
- Detecta scripts nuevos en `act/` que no estén registrados en el sistema
- Compara con CX vía los pull scripts (para detectar deriva)
- Genera `docs/data/inventory.json`

Se ejecuta automáticamente como paso post-deploy (tras el paso 2).
