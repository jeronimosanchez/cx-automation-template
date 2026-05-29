---
status: PASS
tipo: Caso de éxito documentado
estimacion: N/A (no requiere fix)
---

## T1-T3

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero rosas rojas para cumpleaños"* | — |
| 1 | Compra | Detecta G5 + ocasión Regalo, muestra 3 ramos | ✅ Correcto |
| 2 | User | *"el mediano"* | — |
| 2 | Compra | TT-11 univoco, captura producto + pregunta cantidad | ✅ Correcto |
| 3 | User | *"uy, mejor no, dejalo"* | — |
| 3 | Compra | Detecta abandono, cierre cortés + oferta continuar | ✅ Correcto |

### Causa raíz — evaluación de las 9 capas

🟢 1. **Capa Comportamiento** [verificada] · `Read compra.yaml + JSON log`

Compra gestiona correctamente el abandono mid-flow. Detecta lexemas de cancelación, cierra de forma cortés sin presionar, mantiene puerta abierta para nueva intención.

⚪ 2. **Capa Routing** · N/A — Petal usa Playbooks.

🟢 3. **Capa Parámetros/Slots** [verificada] · `JSON log`

Slots se mantienen consistentes entre turnos. Producto seleccionado se conserva hasta el abandono. No hay limpieza explícita, pero tampoco se requiere para este flujo.

🟢 4. **Capa Integración** [verificada] · `JSON log`

Sin tool calls problemáticas. Catálogo respondido correctamente en T1.

🟢 5. **Capa Datos** [verificada] · `curl business`

Sheet contiene inventario y precios coherentes con la respuesta del agente.

⚪ 6. **Capa Infraestructura** · N/A — deploy verde, comportamiento esperado.

🟢 7. **Capa Modelo/LLM** [verificada] · `3/3 runs PASS`

Reproducibilidad confirmada en 3 ejecuciones. Comportamiento determinístico.

🟢 8. **Capa Histórico** [verificada] · `git log -n 20 -- compra.yaml`

Sin regresiones detectadas. Funcionalidad estable.

🟢 9. **Capa Test** [verificada] · `JSON log`

Regex bien calibrado: captura "ayudar" como indicador de cierre cortés.

**Resumen visual:** 0 🔴 · 7 🟢 · 0 🟡 · 2 ⚪

## Recomendación

### No requiere acción

🟢 **PASS estable, sin recomendación de cambio**.

Este TC documenta un comportamiento correcto del agente: manejo elegante de abandono mid-flow. Sirve como **referencia** de cómo Compra debe cerrar conversaciones sin presión.

### Patrones replicables a otros flujos

| Mecanismo | Aplicable a |
|---|---|
| Detección lexema abandono ("mejor no", "dejalo") | Cualquier flujo G5/G3 |
| Cierre cortés sin presión | Checkout (cuando user no completa) |
| Oferta de continuar abierta | Toda conversación |

### Notas para el KB

Este caso refuerza el principio: el agente NO debe insistir cuando user expresa abandono. Comportamiento empáticamente correcto.
