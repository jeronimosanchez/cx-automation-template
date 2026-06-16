# Sistema A — Paso 1: DIAGNOSTICA

**Estado:** WIP — solo Paso 1 completo. Pasos 2 (REPARA) y 3 (VALIDA) pendientes.
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

## Pasos 2 y 3 — pendientes de definir

- **Paso 2 — REPARA:** recibe hipótesis de causa + candidatos de fix → aplica el fix en `definitions/` → genera PR.
- **Paso 3 — VALIDA:** re-ejecuta los TCs afectados contra el fix → confirma PASS sin regresiones → cierra el ciclo.

---

*Repositorio fuente: `cx-automation-template` · Rama: `extract-qap`*
