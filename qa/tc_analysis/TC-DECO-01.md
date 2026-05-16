---
status: FAIL
tipo: Bug Playbook + Infra
veredicto: **Bug real del playbook.** El agente alucina ("no tengo margaritas") cuando el inventario sí las tiene. Causa raíz: la tool call mapea `decorar` → `ocasion=Decoracion`, pero en el catálogo "Decoración" está en `Categoria_Uso`, no en `Ocasion`. La tool no encuentra nada → el agente improvisa alternativas que NO son margaritas.
---

## T1

**Input:** `"quiero un ramo de margaritas para decorar mi recibidor"` — input claro con tipo=Ramo, flor=margaritas, uso=decoración.

**Comportamiento observado:**
- Los 3 runs: ERROR 400 Bad Request (en el momento del repro). Cuando responde (visto en runs anteriores), dice *"no tengo margaritas"* y ofrece alternativas como tulipanes o gerberas — ❌ alucinación, el inventario SÍ tiene margaritas.

**Análisis de checks:**
- `Margarita.{0,40}--.{0,5}[SMLX]|Margarita.{0,80}euros` — ✅ check correcto, espera ver producto real con formato del catálogo ("Margarita -- S" o "Margarita ... euros").
- `not_expected: no tengo.{0,40}margarit|no tenemos.{0,40}margarit` — ✅ no debería decir "no tengo margaritas" si existen en inventario.

**Causa raíz (confirmada con el repro de S60):**

El playbook Compra detecta `decorar` → infiere `ocasion=Decoracion`. La tool call se hace con:
```json
{
  "recurso": "inventario",
  "tipo": "Ramo",
  "producto": "margaritas",
  "ocasion": "Decoracion"   ← problema aquí
}
```

Pero en el inventario real de petal-sheet-api, los productos para decoración tienen `Ocasion="Regalo"` (u otros) y `Categoria_Uso="Decoración"`. El campo `ocasion=Decoracion` filtra a 0 resultados → la tool devuelve vacío → el agente improvisa.

**Recomendación:**

1. **Opción A (Playbook):** ajustar cómo Compra mapea "decorar" → pasar como `categoria_uso=Decoracion` en vez de `ocasion=Decoracion`. Requiere que el Tool acepte ese param.
2. **Opción B (Tool/Backend):** ampliar el endpoint `inventario` para que cuando `ocasion=Decoracion` filtre por `Categoria_Uso=Decoración` en lugar de por `Ocasion`. Más invasivo pero retrocompatible.
3. **Opción C (No mapear):** Compra no asume `ocasion` cuando detecta "decorar" — simplemente pasa `producto=margaritas` y deja que el catálogo devuelva lo que tenga.

Mi voto: **Opción C** (más simple, menos asunciones del agente). Test debería pasar inmediatamente porque la tool encontraría las margaritas reales del catálogo sin filtro restrictivo.
