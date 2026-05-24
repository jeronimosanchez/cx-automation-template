---
name: vision-dashboard-qa-interactivo
description: Visión de largo plazo (post v2.0) del dashboard QA — evolución de HTML estático a dashboard interactivo con IA analítica conversacional sobre los datos de análisis.
metadata: 
  node_type: memory
  type: project
  originSessionId: 66d5b3c2-48ae-4f79-95b1-1ce2b4868d6b
---

Visión de largo plazo del dashboard QA: evolucionar del HTML estático actual hacia un dashboard interactivo con IA analítica que permita chat conversacional sobre los datos de análisis.

**Estado actual (referencia):**
- Dashboard QA en GitHub Pages (HTML estático).
- Generado por `regenerate_all_html.sh`.
- Análisis almacenados como MDs en `qa/tc_analysis/` y JSONs en gh-pages.
- Framework de análisis con 9 capas: Comportamiento, Routing, Parámetros/Slots, Integración, Datos, Infraestructura, Modelo/LLM, Histórico, Test.
- Reports públicos: https://jeronimosanchez.github.io/cx-automation-template/qa/

**Visión objetivo (post v2.0):**
- Chat embebido en el propio dashboard para interactuar con los datos de análisis.
- Drill-down conversacional en patrones cruzados.
- Análisis ad-hoc sobre el histórico de runs.
- Ejemplos de preguntas que debe responder:
  - "¿qué TCs comparten causa raíz en la capa Comportamiento?"
  - "¿cuál es el fix de mayor ROI esta semana?"
  - Patrones cruzados entre capas, evolución temporal, clustering de fallos.

**Why:** anotada por Jero durante la sesión de diseño de v1.1 del skill qa-tc-analyzer (2026-05-24). El dashboard actual sirve para consultar TCs individuales, pero no permite descubrir patrones agregados sin lectura manual. La IA analítica sobre el corpus de análisis convierte el dashboard de "reporte" a "herramienta de investigación".

**How to apply:** NO implementar ahora. Es visión de largo plazo, ubicada después de cerrar v2.0 del skill qa-tc-analyzer. Documentada aquí para que no se pierda entre iteraciones. Si el usuario pregunta por el roadmap del dashboard o por evoluciones del análisis QA, mencionar esta visión como destino. Antes de abordarla deberían estar consolidadas: [[epic-optimizar-analisis-qa]] (v1.1 anti-alucinaciones), [[epic-benchmark-skills-qa]] (medir calidad), y [[deuda-analisis-dependencias-tc]] (análisis cruzado entre TCs ya estructurado en backend).

**Precursores técnicos probables:**
- Backend: pasar de MDs sueltos a base consultable (SQLite/DuckDB sobre los JSONs, o índice semántico).
- Frontend: reemplazar HTML estático por SPA (o añadir capa interactiva sobre el actual).
- Modelo: decidir si chat usa Claude API con RAG sobre los análisis, o un agente local (alineado con [[arquitectura-sistema-hibrido-local-cloud]]).
