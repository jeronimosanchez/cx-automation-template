---
name: estado-actual
description: "Estado al 20-may — 46/49 PASS, 3 análisis listos, agente roto para demo, skills mejoradas"
metadata: 
  node_type: memory
  type: project
  originSessionId: 98f2eccc-717f-49ea-91ff-41b63a7ceeb7
---

Estado al 2026-05-20 (sesión morning demo prep).

**Why**: preparación demo de esta tarde + mejoras al flujo QA.
**How to apply**: leer antes de cualquier sesión nueva.

## QA

- Último run: `20260520_085020` — **46/49 PASS (94%)**, 3 FAIL
- HTML: https://jeronimosanchez.github.io/cx-automation-template/qa/20260520_085020/qa_latest.html
- FAILs:
  - **TC-URGENCIA-01** ⭐ TC estrella demo — Bug Playbook, agente ignora urgencia. Análisis listo (`qa/tc_analysis/TC-URGENCIA-01.md`). Fix: CASO ESPECIAL en compra.yaml (~15 min).
  - **TC-MULTI-PRODUCTO-01** — Bug Playbook, ignora segundo producto. Análisis listo (`qa/tc_analysis/TC-MULTI-PRODUCTO-01.md`). Fix: CASO ESPECIAL multi-item (~20 min).
  - **TC-DECO-02** — Bug Catálogo (sin rosas para Decoración en backend). Análisis listo. Fix requiere backend petal-sheet-api — no aplicable desde repo.

## Agente Petal

- **Estado ROTO** (intencionado para demo) — revert PR #84 mergeado
- Fix cherry-pickable: `3f041df`

## Skills (locales, gitignoreadas)

- `qa-tc-analyzer` — actualizada hoy: **paralelo** (≥2 TCs → sub-agentes simultáneos) + **auto-publish** sin pausa de confirmación
- `qa-fix` / `qa-revert` — sin cambios

## Permisos (settings.local.json, activos próxima sesión)

Añadidos: `python qa/regenerate_html.py *`, `./qa/publish_html.sh *`, `Write(qa/tc_analysis/*)` + variantes con `cd /path &&`

## Demo de hoy

Guion: TC-URGENCIA-01 como estrella.
1. Chat embebido → agente ignora urgencia (bug)
2. HTML → TC-URGENCIA-01 en FAIL
3. `/qa-tc-analyzer TC-URGENCIA-01` → 7 soluciones + score (el MD ya existe, se sobreescribirá o se salta)
4. `/qa-fix TC-URGENCIA-01 1` → branch + edit + PR + deploy (~3 min) + PASS
5. Chat → agente ahora responde bien
6. `/qa-revert TC-URGENCIA-01` → vuelve roto (opcional post-demo)

## Política vigente

Permiso explícito para: `git commit`, `git push`, `gh workflow run`, modificar archivos. Anula §8.3 "lanza/dale".
