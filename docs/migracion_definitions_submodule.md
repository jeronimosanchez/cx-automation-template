# Migración: `definitions/` → repo único `petal-definitions` (submodule)

**Tipo:** cambio estructural cross-repo · **Sesión dedicada** · **Modelo recomendado:** Opus 4.8
**Decisión de origen:** `memory/automatizacion/decision_definitions_fuente_verdad.md` (opción A confirmada)
**Fecha de redacción del brief:** 2026-06-16

---

## 0. Objetivo en una línea

Convertir `definitions/` en un **repo independiente (`petal-definitions`)** que sea la **única fuente de verdad** de los artefactos del agente, consumido por ACT, QAP y (futuro) GEN vía **git submodule** montado en la ruta `definitions/`. Eliminar las copias duplicadas. Verificar exhaustivamente el flujo completo de alta/baja antes de cerrar.

## 1. Por qué (contexto)

- `definitions/` contiene los YAMLs del agente Petal (playbooks, tools, flows, intents, agent.yaml). Son **la última versión de lo que está desplegado en CX**.
- Hoy existen **dos copias idénticas**: `cx-automation-template/definitions/` (ACT) y `agent-validation-engine/definitions/` (QAP).
- Ciclo de vida: **GEN crea → ACT despliega a CX → QAP analiza.** Los tres necesitan el mismo archivo.
- Copias separadas → drift inevitable → QAP analizaría una versión distinta de la desplegada. Inaceptable.
- **Imagen profesional:** un lector externo debe ver un repo de definiciones y tres consumidores que apuntan a él. Cero copias manuales, cero esfuerzo de comprensión.

## 2. Estado de partida (verificado 2026-06-16)

| Repo | Remote | Ruta definitions |
|---|---|---|
| ACT | `https://github.com/jeronimosanchez/cx-automation-template.git` | `definitions/` |
| QAP | `https://github.com/jeronimosanchez/agent-validation-engine.git` | `definitions/` |
| GEN | (no existe aún) | — |

**Contenido de `definitions/` (idéntico en ambos repos):**
- `agent.yaml` — config (project, location, agent_id Petal 1.1, IDs de playbooks)
- `playbooks/` — 6 playbooks: `petal_cx_orchestrator.yaml`, `compra.yaml`, `checkout.yaml`, `registro_task.yaml`, `gestion_deuda.yaml`, `handoff.yaml`
- `tools/` — `petaldatatool.yaml` + `petaldatatool_openapi.yaml`
- `intents/`, `flows/` — recursos CX adicionales
- `examples/`, `pages/`, `webhooks/`, `generators/`, `entity_types/`, `environments/`, `versions/` — con `.gitkeep`

**Cómo referencian los scripts la ruta (CLAVE):**
- ACT: `REPO_ROOT = Path(__file__).resolve().parent.parent`, luego `REPO_ROOT / "definitions"`.
- QAP `static_audit.py`: `os.path.join(root, "definitions", ...)` con flag `--root` (ya agnóstico).
- QAP `petal_qa.py`: rutas relativas `definitions/playbooks/*.yaml` (solo strings de display para hints de fix, no I/O de carga).

→ **Conclusión: si el submodule se monta en `definitions/`, los scripts NO requieren cambios de ruta.** El submodule ocupa el mismo path que la carpeta actual.

## 3. Trampas conocidas (NO romper)

### TRAMPA 1 — detección de cambios en `deploy.yml` (ACT)
`deploy.yml` usa `dorny/paths-filter` sobre `definitions/playbooks/**`, `definitions/tools/**`, etc. Con `definitions/` como submodule, **el repo padre solo versiona un gitlink (el SHA del submodule), no los archivos internos.** El filtro `definitions/playbooks/**` dejará de matchear → el deploy no detectará qué recurso cambió → no desplegará nada.

**Fix obligatorio:** rediseñar la detección. Opciones:
- (a) Detectar que el puntero del submodule cambió (`definitions` aparece en el diff) y entonces hacer `git diff` DENTRO del submodule entre el SHA viejo y el nuevo para saber qué carpetas cambiaron.
- (b) Si el puntero cambió, ejecutar **todos** los `push_*.py` (más simple, idempotente — cada push hace LIST→diff→PATCH solo lo que cambió, así que correr todos es seguro aunque más lento).
- **Recomendado: (b)** por simplicidad y porque la idempotencia ya protege. Documentar el trade-off.

### TRAMPA 2 — detección de cambios en `qa.yml` (QAP)
`qa.yml` filtra con `gh api ... select(startswith("definitions/"))`. Mismo problema: un bump de submodule aparece como un único path `definitions`. **Fix:** tratar cualquier cambio del puntero del submodule como "definitions cambió" → correr QA.

### TRAMPA 3 — CI necesita checkout recursivo
Ambos workflows hacen `actions/checkout`. Hay que añadir `submodules: recursive` (o `git submodule update --init --recursive`) o el CI tendrá `definitions/` vacío y todo fallará.

### TRAMPA 4 — preservar historial git al extraer
NO mover los archivos con `mv` (pierde historial). Usar `git subtree split --prefix=definitions` (o `git filter-repo`) para extraer `definitions/` con su historial a un repo nuevo.

## 4. Plan de ejecución (orden estricto)

> **Gates de aprobación (CLAUDE.md):** los pasos marcados 🔴 requieren OK EXPLÍCITO de Jero en el momento (crear repo, cualquier `git push`, deploy a CX). Los marcados 🟢 son auto.

1. 🟢 **Backup defensivo.** Tag local en ambos repos (`pre-submodule-migration`) por si hay que revertir.
2. 🟢 **Extraer con historial.** En ACT: `git subtree split --prefix=definitions -b definitions-only` → genera una rama con solo el contenido de `definitions/` y su historial.
3. 🔴 **Crear repo `petal-definitions`** (privado) en GitHub: `gh repo create jeronimosanchez/petal-definitions --private`.
4. 🔴 **Push del contenido extraído** a `petal-definitions` (`git push petal-definitions definitions-only:main`).
5. 🟢 **ACT: reemplazar carpeta por submodule.**
   - `git rm -r definitions/` (queda el historial en git)
   - `git submodule add https://github.com/jeronimosanchez/petal-definitions.git definitions`
   - commit.
6. 🟢 **QAP: ídem.** Borrar `agent-validation-engine/definitions/`, `git submodule add ... definitions`.
7. 🟢 **Arreglar TRAMPA 1** en `deploy.yml` (detección por puntero de submodule → opción b).
8. 🟢 **Arreglar TRAMPA 2** en `qa.yml`.
9. 🟢 **Arreglar TRAMPA 3** en ambos workflows (`submodules: recursive` en checkout).
10. 🟢 **Verificación local** (sección 5) — TODA antes de cualquier push a main.
11. 🔴 **Push a main** de ACT y QAP (dispara CI). Vigilar runs.
12. 🟢 **Actualizar docs:** `script_catalog.md`, READMEs de ambos repos, `CLAUDE.md` (mapa de dependencias), y la nota de memoria a "implementado".

## 5. Verificación exhaustiva (el corazón de esta sesión)

> Objetivo: demostrar que el flujo **alta → propagación → baja** funciona de extremo a extremo para **los 6 playbooks**, y que ACT y QAP consumen el submodule sin fricción.
>
> **No tocar el agente CX en producción salvo gate explícito.** El round-trip se valida a nivel de submodule + `--dry-run` del deploy + ejecución real de `static_audit`. El deploy real a CX (Petal 1.1) es un paso OPCIONAL y GATED al final.

### 5.A — Round-trip de propagación (por cada uno de los 6 playbooks)

Para cada playbook `P` en {orchestrator, compra, checkout, registro_task, gestion_deuda, handoff}:

1. En `petal-definitions`: añadir una palabra inocua a un comentario o a un step de `P` (ej. `# MIGRATION-TEST-MARKER`). Commit + push.
2. **ACT:** `git submodule update --remote definitions` → confirmar que el marcador aparece en el archivo dentro de ACT.
3. **ACT:** `python act/push_playbooks.py --file definitions/playbooks/P.yaml --dry-run` → confirmar que detecta el cambio y mostraría el PATCH (sin desplegar).
4. **QAP:** `git submodule update --remote definitions` → confirmar que el marcador aparece.
5. **QAP:** `python qap/static_audit.py --root .` → confirmar que corre sin error sobre el playbook modificado.
6. **Baja:** en `petal-definitions`, revertir el cambio (quitar el marcador). Commit + push.
7. **ACT y QAP:** `git submodule update --remote` → confirmar que el marcador desaparece en ambos.
8. **ACT:** `push_playbooks.py --file ... --dry-run` → confirmar que ya NO detecta cambios (vuelve al estado base).

Registrar PASS/FAIL por playbook en una tabla. Los 6 deben dar PASS en alta y en baja.

### 5.B — Consumo desde ACT, QAP y preparación para GEN

- **ACT:** `python act/validate_api.py` (no debe romperse por el cambio de estructura) + un `pull_playbooks.py --dry-run` para confirmar que sigue resolviendo rutas.
- **QAP:** `python -m pytest qap/tests/ -q` (los 60 tests verdes) + `python qap/petal_qa.py --test TC-C29 --runs 1 --dry-run` si existe dry-run, o confirmar que `agent.yaml` se lee correctamente desde el submodule.
- **GEN (preparación):** documentar en el README de `petal-definitions` el comando exacto que un tercer repo usaría: `git submodule add https://github.com/jeronimosanchez/petal-definitions.git definitions`. No crear GEN, solo dejar el patrón listo.

### 5.C — Clone limpio (la prueba del lector externo)

En `/tmp`, clonar ACT y QAP **desde cero** con `git clone --recurse-submodules`. Confirmar que `definitions/` aparece poblado sin pasos manuales. Esta es la prueba de "el lector no hace ningún esfuerzo".

### 5.D — CI verde

Tras el push a main: confirmar que `deploy.yml` (ACT) y `qa.yml` (QAP) pasan en verde, que la detección de cambios reformada funciona, y que el checkout recursivo trae el submodule.

## 6. Criterio de cierre (Definition of Done)

- [ ] `petal-definitions` existe, privado, con historial preservado.
- [ ] ACT y QAP montan `definitions/` como submodule; cero copias duplicadas.
- [ ] Round-trip alta/baja PASS en los 6 playbooks (tabla 5.A).
- [ ] Tests unitarios QAP verdes (60), `validate_api` ACT OK.
- [ ] `deploy.yml` y `qa.yml` con detección de cambios reformada (trampas 1-3 resueltas).
- [ ] Clone recursivo limpio funciona en ambos repos (5.C).
- [ ] CI verde en ambos repos tras push a main.
- [ ] Docs actualizadas: `script_catalog.md`, READMEs, `CLAUDE.md` §4, nota de memoria → "implementado".

## 7. Rollback

Si algo se rompe irreversiblemente: `git reset --hard pre-submodule-migration` en ambos repos (tags del paso 1) restaura el estado con carpetas duplicadas. El repo `petal-definitions` puede quedar huérfano sin daño.

## 8. Lo que NO entra en esta sesión

- No tocar la lógica de los playbooks (solo el marcador de prueba, que se revierte).
- No desplegar a CX producción salvo gate explícito final opcional.
- No crear el repo GEN (solo dejar el patrón documentado).
- No abordar V1 multi-cliente (cada cliente su repo de definiciones) — futuro.
