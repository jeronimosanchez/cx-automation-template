---
status: FAIL
tipo: Test mal calibrado + Infra
veredicto: El agente se comporta correctamente cuando responde. El test falla por (1) regex potencialmente case-sensitive y (2) errores 400 transitorios. **Fix de test trivial.**
---

## T1

**Input:** `"Quiero rosas rojas para cumpleaños"` — setup normal.

**Comportamiento observado:** Muestra opciones S/M/XL en Run 3 (Runs 1-2 dan ERROR 400).

## T2

**Input:** `"I want the medium one"` — cambio a inglés mid-flow.

**Comportamiento observado (Run 3):** *"Perfecto, Ramo de Rosas Rojo — M (15 flores, 37€). **¿Cuántos quieres?**"* — ✅ entiende el inglés y avanza correctamente.

**Análisis del check:** `cuantos|cantidad|medium|mediano` — ❌ la regex no matchea "Cuántos" si fuera case-sensitive, pero **`re.search` con `re.IGNORECASE` SÍ está aplicado** (líneas 385, 390 de `check_turn`). El fallo del check probablemente es por otra razón.

**Causa raíz probable:**
1. Errores 400 en Runs 1-2 fuerzan FAIL automático (no se llega a T2).
2. En Run 3 que sí funciona, verificar si el check realmente falla — puede ser que el agente diga "Cuántas" (femenino) y el regex tenga "Cuantos" masculino. **`cu.ntos|cantidad|medium|mediano`** sí cubre cuantas/cuantos por el `.` wildcard... pero `re.search` busca substring así que "Cuántas" matchea `cu.ntos`? No: `.` es un solo caracter, así que matchea `cuantos`, `cuántos`, `cuantas`, `cuántas`. Debería pasar.

**Recomendación:** investigar logs reales. Si el agente responde y el regex falla, probablemente es por errores 400 + el run de éxito hace que `pass_count=1/3` siga siendo FAIL (necesita ≥1 para INESTABLE). El PR #49 (throttle + retry quota) puede haber resuelto los 400.
