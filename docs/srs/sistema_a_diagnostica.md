# Sistema A — DIAGNOSTICA · REPARA · VALIDA

**Estado:** Completo (borrador v0.1 — pendiente de validación con Jero).
**Fecha:** 2026-06-16

---

## Contrato del Sistema A

**diagnostica → repara → valida**

El Sistema A es el motor de optimización. Opera entre BUILD (diseño del agente) y VALIDATE (QA en producción). Su función: recibir FAILs, identificar su causa, proponer y aplicar fixes, y confirmar que el fix funciona sin introducir regresiones.

---

## Paso 1 — DIAGNOSTICA

Objetivo: transformar un conjunto de FAILs en hipótesis de causa con evidencia suficiente para proponer un fix.

| Fase | Acción concreta | Pieza · script | Pieza · KB (el criterio) | Estado |
|---|---|---|---|---|
| **1. Auditoría estática** | a) Confronta los **playbooks** contra criterios **generales de diseño conversacional** y **específicos de la plataforma (CX)** | `qap/static_audit.py` | diseño conversacional (`kb_ag`) + plataforma CX (`kb_plat_cx`: CX-25, CX-13…) | ✅ |
| | b) Confronta la **estructura** del agente contra reglas de integridad de la plataforma | `qap/cx_validate.py` | reglas NLU/flow de CX (`kb_plat_cx`) | ❌ por construir |
| **2. Ejecución + veredicto** | a) **Ejecuta** los casos de prueba contra el agente real en CX | `qap/petal_qa.py` | catálogo de TCs (`petal_tests.yaml`, `kb_proj_petal`) | ✅ |
| | b) Confronta cada **respuesta** contra la **rúbrica esperada** → PASS/FAIL | `check_turn()` en `qap/petal_qa.py` | checks + not_expected por TC (`kb_ag_metricas`) | 🟡 rúbrica en calibración |
| **3. Saneamiento** | a) Confronta la respuesta contra **patrones de invalidez** (fuga de prompt, degeneración) → descarta el TC | `qap/sim/static_leak_gate.py` | lexicón + patrones CX-DSL (`kb_plat_cx`) | ✅ |
| | b) Corrige **veredictos falsos** (normalización de tildes, FP/FN conocidos del test) | helper NFD en `qap/petal_qa.py` | criterio FP/FN del test (`kb_ag_metricas`) | ✅ / 🟡 |
| **4. Causa raíz** | a) Clasifica el FAIL contra una **taxonomía de capas** de causa | skills `qap_ag_hypothesis_generator` + `qap_plat_cx_playbook_expert` + `qap_proj_petal_inventory_expert` + `qap_ag_git_expert` | taxonomía 9 capas + `system_knowledge` (`kb_sys` + `kb_ag`) | 🟡 skills activas, knowledge parcial |
| | b) **Propone** candidatos de fix según **recetas de solución conocidas** | skill `gen_plat_cx_hypothesis_fixer` | recetas/patrones de fix (`kb_plat_cx` + `kb_proj_petal`) | 🟡 |
| **5. Correlación** | a) Cruza hallazgos estáticos × dinámicos y puntúa causalidad | `qap/correlate_static_dynamic.py` | tabla de plausibilidad mecánica (`kb_ag`) | ❌ por construir |
| | b) Agrupa FAILs por **causa común** para priorizar fixes | skill `qap_ag_cluster_analyzer` | criterios de agrupación (`kb_ag`) | ❌/🟡 |

### Leyenda KB

| Código | Qué contiene |
|---|---|
| `kb_ag` | Criterios **agnósticos** — válidos para cualquier agente conversacional |
| `kb_plat_cx` | Criterios **específicos de Dialogflow CX** (NLU, flows, playbooks, CX-DSL) |
| `kb_sys` | Conocimiento del **sistema** (ACT+QAP+GEN, pipeline, decisiones técnicas) |
| `kb_proj_petal` | Conocimiento **específico de Petal** (florería, inventario, casos de uso) |

### Estado de las piezas

| Estado | Significado |
|---|---|
| ✅ | Operativo en producción |
| 🟡 | Implementado pero en calibración / knowledge parcial |
| ❌ | Por construir |

---

## Paso 2 — REPARA

Objetivo: aplicar el fix de mayor plausibilidad al YAML del playbook y generar un PR verificable.

| Fase | Acción concreta | Pieza · script | Pieza · KB (el criterio) | Estado |
|---|---|---|---|---|
| **1. Selección** | a) Selecciona el candidato de fix con mayor **score de plausibilidad** entre los propuestos en Paso 1 | skill `qa_analyze` (síntesis de hipótesis) | criterios de priorización (`kb_ag_metricas`) | 🟡 |
| | b) Confirma que el fix **no contradice** decisiones técnicas documentadas del sistema | consulta `system_knowledge.md` + `CLAUDE.md` | decisiones técnicas (`kb_sys`) | 🟡 knowledge parcial |
| **2. Edición** | a) Aplica el fix en **`definitions/playbooks/<playbook>.yaml`** (modifica el step o la instrucción causante) | Write/Edit sobre `definitions/` | recetas de fix por tipo de error (`kb_plat_cx`) | 🟡 |
| | b) Confronta el playbook modificado contra **criterios estáticos** — descarta que el fix introduzca nuevos problemas | `qap/static_audit.py` | `kb_ag` + `kb_plat_cx` | ✅ |
| **3. PR** | a) Commit con mensaje estructurado (TC afectado + hipótesis aplicada) + push a rama `fix/TC-XXX` | `git commit` + `git push` | convención de commits (`kb_sys`) | 🟡 |
| | b) **Abre PR** con descripción del fix, evidencia de causa raíz y TCs de validación esperados | `gh pr create` | template de PR (`kb_sys`) | 🟡 |

---

## Paso 3 — VALIDA

Objetivo: confirmar que el fix resuelve los FAILs del scope sin introducir regresiones, y cerrar el ciclo.

| Fase | Acción concreta | Pieza · script | Pieza · KB (el criterio) | Estado |
|---|---|---|---|---|
| **1. Deploy del fix** | a) Merge del PR → deploy automático vía `deploy.yml` a Petal 1.1 | `deploy.yml` (ACT) | flujo CI/CD (`kb_sys`) | ✅ |
| | b) Confirma que el deploy completó sin errores antes de ejecutar QA | `gh run view` (polling) | — | ✅ |
| **2. Re-ejecución selectiva** | a) Ejecuta **solo los TCs del scope** (los que fallaron) contra el agente con el fix desplegado | `qap/petal_qa.py --test <TC-list>` | catálogo de TCs (`kb_proj_petal`) | ✅ |
| | b) Confronta cada respuesta contra la **rúbrica esperada** → confirma que el FAIL se convierte en PASS | `check_turn()` en `qap/petal_qa.py` | rúbrica por TC (`kb_ag_metricas`) | 🟡 |
| **3. Anti-regresión** | a) Ejecuta la **suite completa** (51 TCs) para detectar regresiones introducidas por el fix | `qap/petal_qa.py --runs 3` | umbrales de regresión (`kb_ag_metricas`) | ✅ |
| | b) Confronta los resultados pre/post fix — **RESUELTO** si FAILs del scope = 0 Y nuevos FAILs = 0 | lógica de comparación en `petal_qa.py` | criterio de éxito (`kb_ag_metricas`) | 🟡 |
| **4. Cierre** | a) Si RESUELTO: documenta el fix en `system_knowledge.md` como receta probada | Write sobre `system_knowledge.md` | recetas de fix (`kb_sys`) | ❌ por construir |
| | b) Si NO RESUELTO: vuelve a Paso 1 con los nuevos FAILs (segunda iteración del ciclo) | — | — | ❌ bucle no automatizado |

---

## Flujo completo

```
FAILs de QA
    │
    ▼
[DIAGNOSTICA] — 5 fases: estática · ejecución · saneamiento · causa raíz · correlación
    │
    ▼ hipótesis de causa + candidatos de fix
[REPARA] — 3 fases: selección · edición + auditoría estática · PR
    │
    ▼ fix desplegado en Petal 1.1
[VALIDA] — 4 fases: deploy · re-ejecución selectiva · anti-regresión · cierre
    │
    ├─► RESUELTO → documenta receta → cierra ciclo
    └─► NO RESUELTO → nueva iteración desde DIAGNOSTICA
```

---

### Leyenda KB

| Código | Qué contiene |
|---|---|
| `kb_ag` | Criterios **agnósticos** — válidos para cualquier agente conversacional |
| `kb_plat_cx` | Criterios **específicos de Dialogflow CX** (NLU, flows, playbooks, CX-DSL) |
| `kb_sys` | Conocimiento del **sistema** (ACT+QAP+GEN, pipeline, decisiones técnicas) |
| `kb_proj_petal` | Conocimiento **específico de Petal** (florería, inventario, casos de uso) |

### Estado de las piezas

| Estado | Significado |
|---|---|
| ✅ | Operativo en producción |
| 🟡 | Implementado pero en calibración / knowledge parcial |
| ❌ | Por construir |

---

*Repositorio fuente: `cx-automation-template` · Rama: `extract-qap`*
