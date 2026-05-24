---
name: Pendiente — Refactor estructural Compra (reducir tokens + bugs sistémicos)
description: Compra ~11.4k tokens tras EP-STRUCT-1. Plan de sub-playbook ConsultaInventario pendiente. Optimización de estilo de prompt descartada por bajo ROI.
type: project
originSessionId: 2800ed63-37ac-4a68-82e5-d9fed4887cb5
---
**Estado al cierre 16 may 2026:** Optimizaciones A4-A9 + EP-STRUCT-1 completadas y desplegadas. Token count: 11,383 (EP-STRUCT-1 añadió +96 tk por headers de sección).

**Historial de optimizaciones:**
- A4-A9: consolidar reglas, comprimir prosa, eliminar redundancias (-939 tk, -7.7%) — PRs #37, #39, #40
- EP-STRUCT-1: reorganizar en 8 secciones explícitas (+96 tk, +0.9%) — PR #46
- PRs #41-#44: petaldatatool → consultarDatos + Full Update en push_examples.py

**Tamaños actuales (post EP-STRUCT-1):**
```
Compra:        ~785 líneas · ~11.4k tokens   ← objetivo: reducir a ~6-7k
Checkout:      543 líneas · ~5.1k tokens
Orquestador:   364 líneas · ~4.2k tokens
Registro_Task: 197 líneas · ~1.4k tokens
```

**Descartado:** optimización de estilo de prompt ("hablarle a Gemini") — ROI estimado ~500-800 tk, pero los 6 FAILs no son de comprensión de instrucciones sino de zona gris (C38, C41-43) y tool calling (DECO-01/02). No merece la pena sin antes clasificar qué es bug real vs test mal calibrado.

**Siguiente target de optimización:** 7 bloques EJEMPLO inline (~1,524 tk, 13.4% del script). Requiere mover ejemplos a Examples de CX y configurar selection strategy = "Always select" en consola (NO disponible vía API).

**Propuesta de refactor estructural (pendiente, no priorizada):**
1. Sub-playbook `ConsultaInventario` como TASK — centraliza tool calling para inventario.
2. Extraer bloques internos (TT-11, FLUJO REFINAMIENTO, FLUJO EXPANSION, CANTIDAD AMBIGUA) a sub-playbooks.

**API limitation:** Example selection strategy (Always/Dynamic/Never) es solo consola, no REST API.

**How to apply:** no priorizar más optimización de prompt hasta clasificar los 9 TCs que no pasan (ver project_pendientes_post_sprint7.md).
