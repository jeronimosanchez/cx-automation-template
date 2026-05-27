---
name: bugs-pendientes-checkout-compra
description: Bugs reales detectados en conversación de usuario real (2026-05-27). Dos corregidos y revertidos para demo, dos pendientes de fix.
metadata:
  node_type: memory
  type: project
  originSessionId: 355c502d-d654-4309-91d4-934b4e3abeab
---

# Bugs pendientes — Checkout + Compra (detectados 27-may-2026)

Origen: conversación real de usuario (ramo de rosas + email no registrado). Análisis completo en `qa/tc_analysis/20260527_1913/adhoc-registro-loop.md`.

---

## Bugs corregidos y revertidos (listos para restaurar post-demo)

### Bug #1 — Pérdida de filtro color en refinamiento
- **Archivo:** `compra.yaml` — FLUJO REFINAMIENTO
- **Síntoma:** usuario pide rosas rojas → refina precio → agente muestra rosas de otro color
- **Fix:** regla explícita "color del turno anterior sigue activo aunque el usuario no lo repita"
- **Commit con fix:** `74fd071`
- **Commit de revert (demo):** `5b812e0`
- **Restaurar:** `git revert 5b812e0 --no-edit && git push origin main`

### Bug #2 — Loop infinito de registro (email no encontrado)
- **Archivo:** `checkout.yaml` — BUCLE EMAIL + EMAIL NO ENCONTRADO
- **Síntoma A:** usuario dice "ese" → agente pide el correo de nuevo (no entiende la referencia anafórica)
- **Síntoma B:** usuario repite el mismo email → agente vuelve a checkear en lugar de ir a registro
- **Fix:** excepción anafórica + detección de mismo email → invocar Registro_Task directamente
- **Commit con fix:** `74fd071`
- **Commit de revert (demo):** `5b812e0`
- **Restaurar:** misma línea que Bug #1 (mismo commit)

---

## Bugs nuevos pendientes de fix

### Bug #3 — Error factual en precio mínimo
- **Archivo:** `compra.yaml` — clasificación de input tras mostrar catálogo
- **Síntoma:** usuario dice "la de 15 euros" pero el catálogo mostrado no tiene ninguna a ese precio → agente dice "no tengo a 15€, los más baratos son 25€" cuando SÍ existe Rosa M a 15€
- **Causa:** "la de 15 euros" se clasifica como selección fallida en lugar de REFINAMIENTO con precio_max=15 → no se relanza query
- **Fix propuesto:** en la sección de clasificación de input, añadir: si el precio pedido no coincide con ningún producto mostrado → tratar como REFINAMIENTO, no como selección fallida
- **Impacto:** alta — respuesta factualmente incorrecta al usuario

### Bug #4 — Transición registro abrupta (UX)
- **Archivo:** `checkout.yaml` — excepción anafórica de registro
- **Síntoma:** tras "ese" (para registrarse), agente pregunta nombre sin confirmar con qué email se registra
- **Fix propuesto:** antes de invocar Registro_Task, confirmar: "Perfecto, te registro con $email. ¿Cuál es tu nombre?"
- **Impacto:** medio — UX confusa pero el flujo funciona

---

## Patrón común detectado

Los bugs #3 y el no-determinismo del catálogo (también en TC-MULTI-PRODUCTO-01 run 3) apuntan al mismo origen: queries a PetalDataTool con filtros blandos devuelven subsets inconsistentes. Investigar si la API soporta `orden=precio_asc` para anclar resultados.
