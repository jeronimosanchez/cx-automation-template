---
name: epic-optimizar-analisis-qa-anti-alucinacion
description: "Épica: reducir alucinaciones del skill qa-tc-analyzer inyectando contexto verificable (git log, memoria, PRs) en el prompt."
metadata: 
  node_type: memory
  type: project
  originSessionId: aba78269-83d9-450d-9b27-639b9a2827f7
---

# Épica — Optimizar análisis QA y reducir alucinaciones

**Origen:** 21-may-2026, demo Petal. Detectada divergencia entre análisis del skill `qa-tc-analyzer` y análisis en sesión interactiva.

**Corrección importante (21-may, tarde):** mi acusación inicial de que el skill "alucinaba PR #83/#84" estaba equivocada — esos PRs existen y dicen exactamente lo que el skill citaba (verificable con `git log --grep`). **No fue invento del skill, fue invento mío al asumirlo sin verificar.**

**El problema real:** el skill puede citar cosas correctas o incorrectas, pero **el usuario no tiene forma de distinguir sin verificación manual**. La épica no es sobre "evitar invenciones" sino sobre **dar al lector las herramientas para verificar cada afirmación**.

**Hipótesis:** el skill `qa-tc-analyzer` opera con contexto limitado (solo el JSON del TC + el playbook actual). Sin histórico ni memoria del proyecto, "rellena" con afirmaciones plausibles sobre PRs, decisiones de negocio y cambios pasados que no son verificables.

**Valor:** análisis fiable → fixes correctos al primer intento → reducción de iteraciones y de coste por TC analizado.

---

## US-1 — Acceso al `git log` reciente del playbook afectado

**Como** ingeniero de QA usando `/qa-tc-analyzer TC-X`
**Quiero** que el análisis incluya los últimos commits que tocan el playbook implicado (últimos 30 días, con diff resumido)
**Para** que las afirmaciones sobre "esta funcionalidad existía y fue revertida" sean verificables o no se hagan.

**Criterio de aceptación:**
- El prompt del skill ejecuta `git log --since="30 days ago" --oneline -- definitions/playbooks/<archivo>.yaml` antes del análisis.
- En el output, cualquier mención a un commit/PR va acompañada del SHA corto.
- Si no hay commits recientes que expliquen el bug, el análisis lo dice explícitamente en lugar de inventar histórico.

---

## US-2 — Acceso a la memoria del proyecto

**Como** ingeniero de QA usando `/qa-tc-analyzer TC-X`
**Quiero** que el análisis tenga acceso a la memoria del proyecto (`shared/`, `petal/`, `automatizacion/`, `current/`)
**Para** que el skill conozca decisiones de negocio, deudas técnicas previas y aprendizajes documentados, en lugar de suponerlos.

**Criterio de aceptación:**
- El skill lee al menos `MEMORY.md` + los `.md` relevantes según el grupo del TC (ej: si el TC es COMPRA, lee `petal/` y `shared/`).
- En el output, las afirmaciones sobre política de producto o decisiones pasadas citan el fichero de memoria correspondiente.

---

## US-3 — Acceso a histórico de PRs cerrados

**Como** ingeniero de QA usando `/qa-tc-analyzer TC-X`
**Quiero** que el skill consulte `gh pr list --state merged --limit 20` antes de citar PRs específicos
**Para** que ninguna referencia a un PR sea inventada.

**Criterio de aceptación:**
- Cualquier cita a un PR (#N) viene acompañada del título real del PR.
- Si el skill no encuentra un PR relevante, no inventa uno: lo dice y propone basarse solo en el código actual.

---

## US-4 — Distinción explícita entre "verificado" y "supuesto"

**Como** ingeniero de QA leyendo el análisis
**Quiero** que cada afirmación del skill esté marcada como verificada (✓) o especulativa (?)
**Para** poder revisar rápido qué partes del análisis necesito comprobar antes de aplicar el fix.

**Criterio de aceptación:**
- Las afirmaciones técnicas verificables (lectura de código, log, PR existente) van con ✓ + cita.
- Las hipótesis sobre intención, motivación o historia no documentada van con ? + nota "(no verificado)".
- El plan de acción solo se apoya en afirmaciones ✓.

---

## US-5 — Análisis de dependencias cruzadas (relacionada — ya en otra deuda)

Ver `automatizacion/deuda_analisis_dependencias_TC.md`. Cuando el skill detecte que un FAIL probablemente comparte causa raíz con otros TCs, lo señalaría aquí.

---

## Coste estimado

- US-1, US-2, US-3: ~1 día (modificar el prompt del skill y los hooks de contexto que se le pasan).
- US-4: ~0.5 día (instrumentar las anotaciones ✓/? en el formato de salida + reglas en el prompt).
- US-5: ya estimado en su deuda técnica.

**Total épica**: ~2 días de sprint.

---

## Cuándo abordar

- Después de la demo de hoy (no toca rato).
- Idealmente antes del próximo sprint con uso intensivo de QA, para que los análisis sean fiables y se reduzca el "re-trabajo" por fixes basados en supuestos incorrectos.
- Prerequisito para escalar a otros agentes/clientes: si el template se usa fuera de Petal, las alucinaciones del skill serían más costosas porque ya no las pillas tan fácil.
