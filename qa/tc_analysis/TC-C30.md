---
status: INESTABLE
tipo: Bug Orquestador
veredicto: Bug intermitente del Orquestador. Ante input ambiguo sin contexto, a veces termina la conversación en lugar de pedir clarificación. El test está bien calibrado.
---

## T1

**Input:** `"Las de siempre"` — ambiguo sin contexto previo. El agente no puede saber qué son "las de siempre" porque no hay historial reciente con este cliente.

**Comportamiento esperado:** preguntar *"¿a qué te refieres?"* — clarificación.

**Comportamiento observado:**
- Runs 1-2: *"Parece que no he podido ayudarte como me gustaría... ¡Hasta pronto! 🌸"* — ❌ se despide directamente sin intentar clarificar.
- Run 3: *"¿A qué te refieres con 'las de siempre'? ¿Me puedes dar más detalles?"* — ✅ comportamiento esperado.

**Análisis de checks:**
- `cuales|refiere|que flores|que producto` — ✅ check correcto.
- `not_expected: ramo|bouton|precio` — ✅ el agente no debería inventar productos sin info.

**Causa raíz probable:** el Orquestador tiene una ruta de "input ininteligible → cierre amable" que se dispara demasiado pronto. Debería tener un paso intermedio de clarificación.

**Recomendación:** añadir regla en el Orquestador: "ante input ambiguo, hacer 1 intento de clarificación antes de cerrar".
