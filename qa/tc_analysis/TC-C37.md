---
status: INESTABLE
tipo: Infra (errores 400 transitorios)
veredicto: Test bien calibrado. Las fallas son por errores 400 transitorios del endpoint de Dialogflow CX. Cuando el agente responde, el comportamiento es correcto.
---

## T1

**Input:** `"Quiero rosas rojas para cumpleaños"` — Compra recibe.

**Comportamiento observado:** Muestra lista de 3 opciones (S/M/XL). ✅ Correcto en los 3 runs.

**Análisis del check:** `talla|tamano|S|M|L|opcion` — ✅ matchea correctamente.

## T2

**Input:** `"El 3"` — el usuario referencia con número. Podría ser la 3ª opción o no tener sentido.

**Comportamiento observado:**
- Runs 1-2: *"Entiendo que te refieres al Ramo San Valentín Rosas Rojas — XL. ¿Es correcto?"* — ✅ interpreta "el 3" como la tercera opción y pide confirmación (correcto por TT-11 PASO 0).
- Run 3: ERROR 400 — ⚠️ error transitorio de infraestructura.

**Análisis de checks:**
- `refiere|cual|opcion|talla|tamano` — ✅ check correcto.
- `not_expected: confirma|resumen` — ✅ no debe confirmar pedido sin verificar primero la opción elegida.

**Causa raíz:** las fallas que vemos son por errores 400 transitorios, no por comportamiento del agente. El comportamiento es correcto cuando responde.

**Recomendación:** ninguna sobre el playbook. Investigar los 400 (puede ser rate limit, quota o conflicto de sesión).
