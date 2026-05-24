# Handoff — Demo Petal QA — 2026-05-20

**De**: sesión larga (16-20 may) en worktree `hungry-sanderson-d8def1`, rama `qa/html-redesign`
**Para**: nueva sesión para terminar de preparar la demo de esta TARDE
**Estado**: agente en estado roto listo para demo. 3 skills creadas (qa-analyze, qa-fix, qa-revert). Pendiente: terminar preparación + ensayar guion.

---

## ⚠️ ANTES DE NADA — LEER

1. **`CLAUDE.md`** (en raíz del repo) — **el usuario ha cambiado políticas de permiso recientemente**. Léelas antes de actuar (sección §8.2 "Gate obligatorio").
2. **`MEMORY.md`** y este handoff completo.

---

## Contexto general

**Petal** es un agente conversacional de comercio de flores en Dialogflow CX (LLM=Gemini). Este repo (`cx-automation-template`) automatiza su despliegue + tests de QA.

**La demo** muestra el ciclo completo "agente con bug → análisis con 7 soluciones → aplicar fix → validar → volver al estado roto":

```
1. Chat embebido con agente: usuario pide "rosas para hoy a las 6"
   → agente IGNORA la urgencia, muestra catálogo (bug real)

2. Abrir HTML del QA en gh-pages
   → ver TC-URGENCIA-01 en FAIL

3. /qa-analyze TC-URGENCIA-01 (o en chat: "analiza TC-URGENCIA-01")
   → genera análisis con 7 soluciones + score, publica al HTML

4. Usuario elige solución (la #1: añadir CASOS ESPECIALES urgencia al Playbook Compra)

5. /qa-fix TC-URGENCIA-01 1
   → branch + edit compra.yaml + PR + merge + Deploy CX (~2 min) + valida (PASS)

6. Volver al chat → agente ahora responde bien (informa plazo 24-48h + ofrece equipo)

7. /qa-revert TC-URGENCIA-01 (opcional, post-demo)
   → vuelve al estado roto
```

---

## Estado actual

| Recurso | Estado |
|---|---|
| Agente en producción (Default Environment) | 🔴 Estado ROTO (revert mergeado, sin CASOS ESPECIALES urgencia) |
| Último run en gh-pages | `20260520_095116` — 49 TCs, 43 PASS, 5 FAIL, 87% |
| Commit del fix (para cherry-pick) | `3f041df` |
| PR del fix original | #83 (mergeado) |
| PR del revert | #84 (mergeado, restauró el estado roto) |
| Skills locales (en `.claude/skills/`) | qa-analyze (existente), qa-fix (nueva), qa-revert (nueva), README.md |

URL del HTML actual: https://jeronimosanchez.github.io/cx-automation-template/qa/20260520_095116/qa_latest.html

---

## Skills creadas hoy

3 skills atómicas (responsabilidad única). README en `.claude/skills/README.md`.

| Skill | Invocación | Qué hace | Tiempo |
|---|---|---|---|
| **qa-analyze** | `/qa-analyze TC-XYZ` o lenguaje natural | Análisis + .md + HTML + publica gh-pages | ~30 seg |
| **qa-fix** | `/qa-fix TC-XYZ <num>` o lenguaje natural | Aplica solución N: edit + PR + merge + deploy + valida | ~3 min |
| **qa-revert** | `/qa-revert TC-XYZ` o lenguaje natural | Revert: PR + merge + deploy + confirma FAIL | ~2-3 min |

**Lenguaje natural también funciona**: "analiza TC-XYZ", "aplica la solución 1", "revierte TC-XYZ" → la skill correcta se invoca automáticamente.

---

## Recursos y scripts clave

| Recurso | Para qué |
|---|---|
| `qa/test_QA_Playbooks_v23.py` | Runner principal del QA. Acepta `--test TC-XYZ` y `--tests CSV` |
| `qa/regenerate_html.py` | Regenera HTML desde JSONs (gh-pages o local) SIN llamar a CX |
| `qa/publish_html.sh` | Sube HTML existente a gh-pages (actualiza TS existente) |
| `qa/rerun_single_tc.sh` | Re-ejecuta UN TC + combina con histórico + publica nuevo TS en gh-pages (validación rápida tras fix) |
| `qa/list_fails.py` | Lista FAILs y estado de análisis |

Ubicación: `~/cx-automation-template/`. El venv está en `~/cx-automation-template/.venv/`. Gcloud auth ya hecho.

---

## Pasos comprobados hoy (los 5 FAILs actuales)

1. **TC-DECO-02** — Rosas para decorar (bug catálogo, no demo-friendly)
2. **TC-FRUSTRACION-01** — Múltiples rechazos consecutivos (bug agente, demo-able)
3. **TC-URGENCIA-01** — ⭐ **TC ESTRELLA DE LA DEMO** — Entrega urgente (bug Playbook, fix validado hoy)
4. **TC-MULTI-PRODUCTO-01** — Pedido multi-item (bug agente, demo-able)
5. **TC-IMPOSIBLE-01** — Descuento 50% (test mal calibrado, fix ya mergeado, ahora PASS; no usar en demo porque no cambia el chat)

---

## Pendientes para la nueva sesión

1. **Leer CLAUDE.md actualizado** (políticas nuevas sobre permisos)
2. **Ensayar el guion de demo**:
   - Verificar que el chat embebido sigue funcionando con el agente actual
   - Validar `/qa-analyze TC-URGENCIA-01` en una sesión nueva
   - Posiblemente hacer un ensayo completo de fix → revert con TC distinto si quieres practicar
3. **Posibles mejoras pre-demo** (si hay tiempo):
   - Pulir mensajes de output de las skills
   - Verificar que el botón "Borrar análisis" + badges AUTO/LLM se ven bien
   - Comprobar que los tiempos de Deploy CX están dentro de lo esperado (~2 min)

---

## Cómo arrancar la nueva sesión

```bash
cd ~/cx-automation-template/.claude/worktrees/hungry-sanderson-d8def1
claude
```

Pega esto:

> Retomo la demo Petal QA. Lee `~/.claude/projects/-Users-jeronimosanchezmorote-cx-automation-template/memory/current/handoff_2026-05-20_demo-petal-qa.md` para el contexto completo. Después lee `CLAUDE.md` del repo para las nuevas políticas de permiso. Estado: agente roto con TC-URGENCIA-01 fallando, 3 skills creadas (qa-analyze, qa-fix, qa-revert), demo esta tarde. Dime por dónde quieres continuar.

---

## Política vigente (al cierre de hoy)

- **Permiso explícito** del usuario para: `git commit`, `git push`, `gh workflow run`, modificar archivos del repo.
- **Lectura sin pedir permiso** (read-only: gh view/list/run, git status/log/diff, grep, find, curl GET, Read, WebFetch).
- **Antes de `gh workflow run`**: avisar al usuario (evita cancelaciones por concurrency).
- Los `.md` de análisis (`qa/tc_analysis/*.md`) **NO se commitean a main** — viven solo en local + gh-pages.
- ⚠️ **Verificar CLAUDE.md** porque el usuario ha actualizado políticas hoy.
