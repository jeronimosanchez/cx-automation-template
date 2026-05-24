---
name: proceso-analisis-qa
description: "Puntero al documento maestro del proceso de análisis QA. La fuente real está en el repo: docs/qa_analysis_process.md."
metadata: 
  node_type: memory
  type: project
  originSessionId: aba78269-83d9-450d-9b27-639b9a2827f7
---

# Proceso de análisis QA — Puntero

**Fuente única de verdad:** `docs/qa_analysis_process.md` (en el repo del proyecto `cx-automation-template`).

## Por qué este puntero

El proceso de análisis QA (qué fuentes consulto, qué genero, cómo evoluciona) está documentado en el repo, no en memoria. Razones:

1. **Visibilidad para humanos**: cualquier persona que abra el repo lo ve, no solo Claude en sesión.
2. **Versionado**: vive en git, con changelog auditable.
3. **Un único sitio**: evita desincronización entre memoria y código.

Esta nota existe **solo para que en futuras sesiones lo encuentre fácilmente** desde el índice `MEMORY.md`.

## Cuándo consultarlo

- Antes de invocar el skill `qa-tc-analyzer`, para conocer la versión activa del proceso.
- Antes de proponer cambios al proceso, para entender la historia.
- Cuando se valide una nueva versión (v1.1, v1.2...), actualizar la sección Changelog del documento maestro.

## Estado actual (21-may-2026)

- **Versión documentada como activa:** v1.0
- **Versión propuesta:** v1.1 (pendiente de validar con TC-URGENCIA-01 + TC-URGENCIA-02 + TC-URGENCIA-03)
- **Implementación viva:** `.claude/skills/qa-tc-analyzer/SKILL.md` (refleja v1.0 actualmente)

## Relación con otras épicas

- [`automatizacion/epic_optimizar_analisis_QA.md`](epic_optimizar_analisis_QA.md) — epic de "anti-alucinación" cuyas US se materializan en la v1.1.
- [`automatizacion/deuda_analisis_dependencias_TC.md`](deuda_analisis_dependencias_TC.md) — el cambio 5 de v1.1 (detección de patrones cruzados) cubre parcialmente esta deuda.
- [`automatizacion/epic_backlog_conversational_design.md`](epic_backlog_conversational_design.md) — su existencia desbloquea v2.0 (acceso real a políticas de producto).
