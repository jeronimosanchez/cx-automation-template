---
status: FAIL
tipo: Bug Playbook + Infra
veredicto: Idéntico patrón a TC-DECO-01. **Bug real del playbook**: el mapeo de "decorar/decoración" a filtros de la tool call es incorrecto. + Errores 400 transitorios. Mismo fix.
---

## T1

**Input:** `"quiero un ramo de rosas para decorar mi salon"` — tipo=Ramo, flor=rosas, uso=decoración.

**Comportamiento observado:**
- Run 1, Run 3: ERROR 400 — ❌ error de infraestructura.
- Run 2: *"No tengo ramos de rosas para decoración, pero mira estas opciones: Tulipanes Mix, Narcisos..."* — ❌ **BUG REAL**: propone flores que NO son rosas. El inventario SÍ tiene rosas, pero la tool call con `ocasion=Decoracion` no las encuentra.

**Análisis de checks:**
- `Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,80}euros` — ✅ check correcto, espera ver rosas reales del catálogo.
- `not_expected: no tengo.{0,40}rosa|no tenemos.{0,40}rosa` — ✅ no debería decir "no tengo rosas".

**Causa raíz:** misma que TC-DECO-01 — Compra envía `ocasion=Decoracion` cuando el catálogo tiene "Decoración" en `Categoria_Uso`, no en `Ocasion`.

## Recomendación

Ver TC-DECO-01 para el fix. **Una vez resuelto TC-DECO-01, TC-DECO-02 pasa automáticamente** (mismo bug, distinta flor).

Adicionalmente: investigar los errores 400 que afectan tanto a TC-DECO-01 como a TC-DECO-02 (puede ser rate limit del agente o conflicto de sesión).
