---
name: Patrón de iteración QA-loop autorizado por "lanza" o "dale"
description: Cuando Jero diga "lanza" / "dale" para un fix con plan claro, ejecutar end-to-end sin pedir gates intermedios (commit + branch + PR + merge --admin + deploy + QA local + comparar). Validado durante Sprint 7.
type: feedback
originSessionId: 288e30ad-19ad-43ff-9e5f-fca510d83ba2
---
Cuando Jero ya ha revisado un análisis y dice "lanza", "dale", "vamos", etc., autoriza el ciclo completo: edit → pytest → dry-run → commit → push branch → PR → merge (con `--admin` si branch protection bloquea) → deploy.yml → QA local o full → comparar contra baseline → reportar.

**Why:** durante Sprint 7 (14 may 2026) este patrón permitió 7 PRs en una tarde con feedback rápido. Pararse a pedir aprobación entre pasos rompe el flujo y le frustra.

**How to apply:**
- Solo aplica TRAS un análisis aprobado por él (no en el fix inicial, solo en el ciclo de ejecución).
- Sigue valiendo CLAUDE.md §7: nada de IAM/Secrets/Petal manual sin OK explícito.
- Al final del ciclo, dar URLs del HTML público + tabla de diff vs baseline. Él lo revisa y decide siguiente paso.
- Si hay regresiones reales (no flakiness), parar y reportar antes de seguir.
- "Lanza" autoriza UN PR + verificación. No autoriza una cadena indefinida.
