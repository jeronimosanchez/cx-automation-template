---
name: Aprendizaje — Diseño conversacional enterprise (NLU + LLM híbrido)
description: Patrones de arquitectura conversacional. Referencia para evolución de Petal y portfolio.
type: project
originSessionId: trusting-fermat-3ada03
---

## Patrón híbrido NLU + LLM (estándar enterprise)

**Arquitectura de 3 capas:**
1. **NLU** (clasificador): entrena intents con frases ejemplo. Rápido, barato, predecible. Resuelve ~80% del tráfico.
2. **Router** (decisor): score > 0.85 → ruteo directo. Score 0.50-0.85 → LLM decide. Score < 0.50 → fallback LLM.
3. **LLM** (conversacional): solo interviene en zona gris. Gestiona la conversación, slot-filling, edge cases.

**En Dialogflow CX:** Flows+Pages+Intents = NLU. Playbooks = LLM. Se pueden mezclar en el mismo agente.

**Ventajas del híbrido:** velocidad (80% sin LLM), coste (menos tokens), predecibilidad (NLU determinista), auditabilidad (scores visibles).

## Distinción clave: clasificación vs slot-filling

- **Clasificación** (Orquestador): ¿a qué grupo/playbook pertenece la intención? Puede preguntar para aclarar destino.
- **Slot-filling** (Playbook destino): rellenar datos necesarios para completar la acción. Solo lo hace el playbook dueño (Compra, Registro, etc.).
- El Orquestador NUNCA hace slot-filling. Si necesita más info, es para CLASIFICAR, no para rellenar slots.

## Petal actual vs target

- **Actual:** LLM para todo (Orquestador = playbook que clasifica con reglas en prompt + examples).
- **Target futuro:** Flow NLU como primera línea (15-20 intents entrenados) + Orquestador como fallback solo para ambiguos.
- **Beneficio esperado:** eliminar problemas como TC-C41 (LLM confunde clasificación con slot-filling).

## Pendiente investigar
- Ejemplos concretos de arquitecturas conversacionales enterprise (Google, Amazon, Microsoft)
- Mejores prácticas de diseño de intents y frases de entrenamiento
- Cuándo merece la pena híbrido vs LLM-only (umbral de tráfico, complejidad)
- Documentación oficial de CX sobre mezcla Flows+Playbooks
