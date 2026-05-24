# Handoff sesión HTML Optimize Buttons — 2026-05-19

**De**: sesión larga (16-19 may) en worktree `hungry-sanderson-d8def1`, rama `qa/html-redesign` (~940k tokens)
**Para**: próxima sesión que retome este scope
**Estado**: TODO mergeado a main. HTML en producción funcionando. Workflow Optimizar end-to-end operativo. Pendiente: ejecutar el workflow completo en demo real.

---

## Lo que se hizo (resumen ejecutivo)

### Iteraciones de HTML (PR #65 → #76, mergeados)

**v1-v2 (sesiones anteriores)**: render unificado PASS/FAIL, plegable, modal Metodología con 5 KPIs, JSON button por TC, tooltips, filtros en 2 filas, cursivas+comillas.

**v3 (esta sesión)**:
- **3 botones nuevos** en barra superior: `[🗑 Borrar optimización] [⚙ Optimizar] [📊 Histórico]`
- **Optimizar**: abre panel con tabla de FAILs + checkboxes
- **Run**: copia prompt completo al portapapeles (contexto + datos + URL JSON + template EXACTO)
- **Borrar optimización**: cierra panel y resetea estado (Optimizar sigue activo si hay FAILs)
- **Cleanup masivo**: borrados 14 .md de `qa/tc_analysis/` (análisis viejos eliminados)
- **Diagnóstico determinístico**: ahora muestra datos REALES del JSON (grupo_intent observado vs esperado, slots extraídos, checks no superados, respuesta del agente) en vez de texto hardcodeado
- **Causa raíz placeholder**: "Pendiente análisis. Click Optimizar..." (se rellena vía Claude)
- **Recomendación/Acción placeholder**: igual

### Infraestructura nueva (commiteada en main)

- `qa/regenerate_html.py` — regenera HTML desde JSONs locales o gh-pages SIN llamar a CX (5 seg, 0€)
- `qa/publish_html.sh` — clona gh-pages, sustituye HTML, commit + push
- `qa/list_fails.py` — lista FAILs y su estado de análisis (.md presente o no)
- `.claude/skills/qa-tc-analyzer/SKILL.md` — skill local (NO en git, está en `~/cx-automation-template/.claude/skills/qa-tc-analyzer/`)

### Fixes adicionales

- Workflow `qa.yml`: `cp -r` para publicar JSONs en gh-pages (antes solo HTML)
- Workflow `qa.yml`: índice ordenado DESC + links a qa_latest.html (antes carpetas que daban 404)
- Workflow `qa.yml`: cleanup de cp + más cosas
- `qa/test_QA_Playbooks_v23.py`: `--test` acepta lista CSV

---

## Estado actual

| Recurso | Estado |
|---|---|
| Último QA exitoso | `20260519_115033` — 44/49 PASS, 5 FAIL |
| Botones Optimizar/Borrar/Run | ✅ En main, en producción |
| Diagnóstico determinístico (datos reales) | ✅ En main, en producción |
| Causa raíz + Recomendación: pendiente análisis | ✅ En main, en producción |
| Skill `/qa-tc-analyzer` (local) | ✅ Operativa |
| Scripts regenerate_html.py + publish_html.sh + list_fails.py | ✅ En main |
| Bookmark histórico de runs | https://jeronimosanchez.github.io/cx-automation-template/qa/ |

---

## Los 5 FAILs actuales (todos sin análisis manual)

1. **TC-DECO-02** — Rosas para decorar (bug catálogo + falta fallback escalonado)
2. **TC-FRUSTRACION-01** — Múltiples rechazos consecutivos (escalación tardía)
3. **TC-IMPOSIBLE-01** — Descuento 50% (falso negativo del test, regex incompleto)
4. **TC-MULTI-PRODUCTO-01** — Pedido multi-item (ignora 2º producto)
5. **TC-URGENCIA-01** — Entrega urgente (ignora urgencia)

---

## Workflow operativo (a partir de ahora)

```
1. Lanzar QA:
   gh workflow run "QA Petal" --ref main
   (o automático tras cada merge a main)

2. Abrir HTML del último run:
   https://jeronimosanchez.github.io/cx-automation-template/qa/

3. Para analizar FAILs (2 opciones):
   
   OPCIÓN A (via botón en HTML):
   - Click "Optimizar" → seleccionas TCs → Click "Run"
   - El prompt se copia al portapapeles
   - Pegas en cualquier sesión de Claude
   - Claude devuelve análisis siguiendo el template
   - Si es ESTA sesión: yo guardo .md + regenero HTML
   - Si es otra sesión: copias respuesta y la pegas aquí
   
   OPCIÓN B (directo, sin botón):
   - Me dices "/qa-tc-analyzer TC-XYZ" o "analiza TC-XYZ"
   - Yo leo JSON, genero análisis, guardo .md, regenero HTML, publico
```

---

## Pendientes (futuro)

### Inmediato (próxima sesión, si quieres)
- **Demo del miércoles**: workflow operativo, decide si analizas algún FAIL antes para tenerlo de muestra
- **TC-IMPOSIBLE-01 fix de test** (~2 min): extender regex con `no tenemos|ayudar` — pasa el TC sin tocar agente

### Medio plazo
- **Análisis automático en CI** (EP-QA-08): cuando un FAIL aparece, llamar a Anthropic API para generar análisis automáticamente. Coste: ~0.05-0.20€/FAIL/run. Descartado por ahora por coste.
- **Bugs reales del agente**: TC-DECO-02 fallback escalonado, TC-FRUSTRACION-01 escalación temprana, TC-MULTI-PRODUCTO-01 multi-producto, TC-URGENCIA-01 detección de urgencia
- **Resumen agrupado dinámico**: workflow asistido (lee JSONs de FAILs, reescribe `_resumen.md` si se vuelve a crear)
- **Rotación de gh-pages**: cuando se acumulen ~700-1000 runs, montar rotación de runs viejos

---

## Cómo retomar mañana (próxima sesión)

```bash
cd ~/cx-automation-template/.claude/worktrees/hungry-sanderson-d8def1
claude
```

Y pega esto:

> Retomo el proyecto Petal QA. Lee `memory/current/handoff_2026-05-19_html-optimize-buttons.md` para el contexto completo. Estado: HTML v3 con botones Optimizar/Borrar/Run funcionando, Diagnóstico determinístico, Causa raíz + Recomendación pendientes. Último QA: 44/49 PASS. Workflow Claude para analizar TCs: skill `/qa-tc-analyzer` o botón Optimizar en el HTML. Dime qué hacer.

---

## Archivos clave (locations)

| Archivo | Para qué |
|---|---|
| `qa/test_QA_Playbooks_v23.py` | Runner principal (1900+ líneas, contiene generate_html con CSS/JS inlineado) |
| `qa/regenerate_html.py` | Regenera HTML sin tocar CX |
| `qa/publish_html.sh` | Sube HTML a gh-pages |
| `qa/list_fails.py` | Lista FAILs y estado de análisis |
| `.github/workflows/qa.yml` | Workflow CI (lanza QA + publica HTML/JSONs en gh-pages) |
| `qa/tc_analysis/` | Carpeta vacía actualmente (era donde vivían los `.md` manuales, borrados) |
| `~/cx-automation-template/.claude/skills/qa-tc-analyzer/SKILL.md` | Skill local (NO en git) |

---

## Política vigente (recordatorio)

- Permiso explícito a Jero para: `git commit`, `git push`, `gh workflow run`, modificar archivos del repo
- Anula el patrón "lanza/dale" del CLAUDE.md §8.3
- Lectura sin pedir permiso (verbos read-only: gh view/list/run, git status/log/diff, grep, find, curl GET, Read, WebFetch)
- Antes de `gh workflow run`: avisar para evitar cancelaciones por concurrency
