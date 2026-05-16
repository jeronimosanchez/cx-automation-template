---
status: FAIL
tipo: Test (resuelto en PR #48, esperar próximo QA run)
veredicto: **Test fue reescrito en PR #48** (`24af3d6`) para ajustarse al flujo real Compra→Checkout. El comportamiento del agente (saltar confirmación e ir directo a Checkout pidiendo email) ahora es válido. **Esperar próximo QA run para reevaluar.**
---

## Contexto

El test ORIGINAL asumía un flujo de 4 pasos (elegir producto → cantidad → confirmar → pedir email). El comportamiento REAL del agente Compra v39 hace 3 pasos (elegir → cantidad → email directo), saltando confirmación si todos los slots están claros.

PR #48 corrigió el desajuste: ahora T3 acepta `correo|email|pedido|confirma|resumen` (cualquiera vale). Esto debería convertir el FAIL en PASS.

## T1

**Input:** `"Quiero rosas rojas para cumpleaños"` — setup.

**Comportamiento esperado:** muestra 3 opciones (S/M/XL).

**Análisis del check:** `talla|tamano|S|M|L|opcion` — ✅ check correcto.

## T2

**Input:** `"El mediano"` — elige talla.

**Comportamiento esperado:** *"Ramo de Rosas Rojas — M. ¿Cuántos quieres?"*.

**Análisis del check:** `cu.ntos|cantidad` — ✅ check correcto.

## T3

**Input:** `"1"` — da cantidad.

**Comportamiento esperado (post PR #48):** ya sea *"Para completar tu pedido necesito tu correo electrónico"* (flujo directo) o *"Confirmo tu pedido: …"* (con confirmación).

**Análisis del check (corregido):** `correo|email|pedido|confirma|resumen` — ✅ acepta ambos flujos.

## Recomendación

**Re-ejecutar QA con `--runs 3`** tras el deploy de PR #48 para confirmar que TC-C42 pasa a PASS o INESTABLE. Si sigue FAIL, investigar más.
