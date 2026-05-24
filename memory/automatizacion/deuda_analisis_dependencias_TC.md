---
name: deuda-tecnica-analisis-dependencias-tc
description: "Deuda técnica: análisis de causa raíz común entre TCs que fallan, para priorizar qué bug fixear primero."
metadata: 
  node_type: memory
  type: project
  originSessionId: aba78269-83d9-450d-9b27-639b9a2827f7
---

# Deuda técnica — Análisis de dependencias entre TCs

**Detectado:** 21-may-2026 durante preparación de demo Petal.
**Origen:** Jero pregunta si el QA tiene análisis de problemas comunes entre TCs. No lo tiene.

## El problema

Hoy el QA reporta cada TC aislado:
- `qa-tc-analyzer` analiza un TC individual (turnos vs problemas + 7 soluciones).
- El HTML agrupa por **playbook** (COMPRA-ZG, COMPRA-G5, G6...), no por **causa raíz**.
- Si 5 TCs fallan por el mismo bug (ej: `Direccion_Entrega` vacío en PASO 3 de Checkout), aparecen como 5 incidencias separadas en el HTML.

**Consecuencia:** no se sabe por dónde empezar. Un fix de 1 línea que cierra 5 FAILs tiene la misma prioridad visual que 5 fixes independientes de 1 FAIL cada uno.

## Qué falta construir

**Análisis de causa raíz cruzada** sobre el conjunto de FAILs de un run:

1. **Detector de patrones:** tomar los `agent_text` de los turnos que fallan y agrupar por keywords/regex compartidos (ej: "Lo siento, algo no ha funcionado" = `error_generico` = probable fallo de tool call).

2. **Mapa de impacto:** "este bug afecta a estos N TCs". Ordenar por número de TCs afectados (mayor primero → mayor ROI).

3. **Trazabilidad a fix:** sugerir dónde mirar (compra.yaml Paso X, checkout.yaml PASO Y) según el patrón detectado.

4. **Vista en el HTML:** sección "Causas comunes" con ranking de bugs por impacto.

## Cuándo abordar

- Hoy (29 TCs) no compensa el coste — los FAILs se ven a ojo.
- Cuando la suite supere los **~50 TCs** o cuando un release reporte >10 FAILs simultáneos.
- Si se generaliza el template a otros agentes (no solo Petal), el análisis cross-cliente sería aún más valioso.

## Pieza relacionada que ya existe

`qa/impact_map.py` — no leído todavía, podría ser un esqueleto previo de esto. Revisar si ya hay algo construido antes de empezar de cero.

## Coste estimado

- Detector de patrones por keywords: 1 día.
- Mapa de impacto + integración HTML: 1-2 días.
- Total: **~3 días de sprint** cuando se priorice.
