---
name: Alcance de validación en tests E2E
description: Cuando el flujo principal ya está probado, no seguir validando subdetalles secundarios — cerrar y resumir.
type: feedback
originSessionId: 42db5725-85e2-43f8-bc20-5ca57f533f79
---
Si en una validación E2E el flujo principal (auth, build, deploy, etc.) está probado de punta a punta, no profundizar en sub-verificaciones secundarias (p. ej. polling de LROs, propagación asíncrona) salvo que el usuario lo pida.

**Why:** El usuario interrumpió un test E2E en `cx-automation-template` cuando estaba investigando por qué la Version snapshot no aparecía en `--list` (LRO asíncrona). Dijo: "El test E2E está suficientemente validado. Cierra el Paso 7 y termina." El deploy job ya había reportado success y los pasos críticos (WIF auth, deploy de Examples/Playbooks/Tools/Agent, POST version 200 OK) habían pasado. Insistir en cerrar la verificación de la LRO era over-engineering.

**How to apply:** Cuando un workflow CI o test E2E reporta success en los steps críticos, parar ahí y entregar el resumen. Si un detalle secundario se ve raro (LRO no propagada, métrica atrasada, etc.), mencionarlo en el resumen pero no bloquear el cierre intentando confirmarlo. El usuario decide si quiere profundizar.
