---
status: INESTABLE
tipo: Flakiness Orquestador
veredicto: Bug intermitente del Orquestador. A veces no accede a los datos de horario de negocio. **Baja prioridad** — no es de Compra, no afecta flujo crítico de venta.
---

## T1

**Input:** `"A que hora abris?"` — pregunta legítima sobre horario de la tienda.

**Comportamiento observado:**
- Runs 1-2: *"No tengo ese dato ahora mismo. ¿Hay algo más en lo que pueda ayudarte?"* — ❌ el Orquestador no recupera la info de horario, debería tenerla en su contexto o en un datastore.
- Run 3: *"...abrimos de lunes a sábado de 9:00 a 20:00"* — ✅ respuesta correcta, pero solo 1/3 veces.

**Análisis del check:** `horario|lunes|sabado|9|20` — el test está bien calibrado, espera ver palabras clave del horario.

**Causa raíz probable:** el Orquestador depende de un Tool / Sheet para recuperar info de negocio. Llamada intermitente o caché frío en Cloud Run = a veces falla.

**Recomendación:** investigar latencia/disponibilidad del endpoint que sirve info de negocio. No urgente.
