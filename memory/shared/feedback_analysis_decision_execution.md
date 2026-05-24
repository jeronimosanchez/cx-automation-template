---
name: feedback-analysis-decision-execution
description: Separar SIEMPRE análisis → decisión del usuario → ejecución en 3 fases distintas
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 98f2eccc-717f-49ea-91ff-41b63a7ceeb7
---

Dos flujos distintos en este proyecto. Reconocer cuál aplica antes de actuar.

## Flujo 1 — QA analysis (automático, sin pausas)

```
Jero pega info del run / pide analizar TC-X
   ↓
Claude analiza + muestra en chat + escribe MD + regenera HTML + publica gh-pages + PR + merge
   ↓
Fin de la fase. No se pide confirmación intermedia.
```

**Why**: el análisis es información, no debate. Jero no va a cambiar el análisis, solo necesita verlo. Y necesita verlo en el HTML para luego decidir off-chat cuál solución aplicar.

**Después** (fuera del chat): Jero abre el HTML, lee turnos + 7 soluciones, decide.

**Después** (vuelta al chat): Jero dice "aplica solución N de TC-X" → Claude ejecuta qa-fix.

## Flujo 2 — Mejoras al sistema / decisiones de arquitectura

```
Claude propone N opciones con trade-offs
   ↓
Jero elige una (explícito: "vamos con la 3", "haz B", etc.)
   ↓
Claude ejecuta la opción elegida sin pausa intermedia
```

**Why**: una vez la opción está elegida, no hay más decisiones que tomar. "No me pidas permisos" / "hazlo" / "dale" → ejecutar sin parar.

**Cuándo SÍ parar dentro de ejecución**:
- Si aparece una sub-decisión NUEVA no anticipada en el análisis (raro, pero posible).
- Si algo falla y hay 2 caminos para recuperarse.

**Cuándo NO parar**:
- Pasos predecibles del plan que Claude ya describió (escribir script → modificar JS → workflow → PR → merge → backfill → republish). Eso es la ejecución de UNA opción.

## El incidente del 2026-05-20

Inicialmente Jero pensó que yo había mezclado fases — al final aclaramos que la ejecución estuvo bien hecha (todo era parte de "Opción 3"). El problema real fue que tras la ejecución, **la pantalla seguía mostrando el error**, lo que sugería un fallo de propagación/cache, no un fallo de proceso.

**How to apply**:
- Identificar primero qué flujo es: QA-analysis o mejora al sistema.
- QA-analysis: ejecutar todo automático, mostrar + publicar.
- Mejora al sistema: proponer opciones, esperar elección, después ejecutar todo automático.
- Cuando el usuario reporta "no funciona" tras ejecución: NO asumir que el proceso fue mal — investigar qué cambió en la pantalla vs. qué debería haber cambiado.
