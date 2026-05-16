---
status: FAIL
tipo: Test (resuelto en PR #48, esperar próximo QA run)
veredicto: **Test fue reescrito en PR #48** (`24af3d6`) para ajustarse al flujo real Compra→Checkout y al manejo de input ambiguo en PASO 0 de Checkout (re-pedir email en lugar de cancelar). **Esperar próximo QA run para reevaluar.**
---

## Contexto

El test ORIGINAL asumía un flujo donde T4 ofrecía opciones de cambiar/dejar/modificar. El comportamiento REAL es que tras `"1"` (cantidad), Compra transfiere a Checkout que pide email; ante input ambiguo como `"Mmm no sé"`, Checkout re-pide el email en lugar de cancelar.

PR #48 corrigió el test: ahora T4 espera `correo|email|arroba|nombre@` y prohíbe `cancelar|adios|pronto|otro producto`. Esto refleja el flujo correcto.

## T1, T2, T3

Idénticos al flujo de TC-C42 hasta entrar en Checkout. Ver análisis ahí.

## T4 (nuevo, post PR #48)

**Input:** `"Mmm no sé"` — input ambiguo cuando Checkout pide email.

**Comportamiento esperado:** Checkout interpreta el input como "no es un email", re-pide cordialmente sin cancelar.

**Análisis de checks (corregido):**
- `correo|email|arroba|nombre@` — espera ver re-petición del email.
- `not_expected: cancelar|adios|pronto|otro producto` — no debe abortar.

## Recomendación

**Re-ejecutar QA con `--runs 3`** tras el deploy de PR #48 para confirmar. Si sigue FAIL, investigar errores 400 que afectaron este TC originalmente.
