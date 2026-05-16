---
status: FAIL
tipo: Bug Playbook + Test mal calibrado
veredicto: **Doble problema.** (1) Bug del playbook en T2: no toma iniciativa cuando el usuario delega ("tú decides"). (2) Test mal calibrado en T1: el `not_expected` prohíbe "ocasion" pero el `check` lo requiere — contradicción interna del test.
---

## T1

**Input:** `"Quiero flores"` — input genérico sin ningún filtro.

**Comportamiento observado:** *"¿Es para alguna ocasión especial o tienes algún tipo de flor en mente?"* — ✅ pregunta legítima de refinamiento (PASO 1 de Compra: necesita slot filling).

**Análisis de checks:**
- `ocasion|motivo|tipo|flor|color` — ✅ matchea correctamente (el agente menciona "ocasión" y "flor").
- `not_expected: ocasion|motivo|color` — ❌ **TEST MAL CALIBRADO:** el `not_expected` prohíbe "ocasion" pero el `check` lo requiere. **Contradicción directa.** Preguntar por ocasión ES el comportamiento correcto en T1 — no hay forma de pasar ambos checks a la vez con la misma palabra.

**Recomendación T1:** revisar `not_expected`. La intención original probablemente era "no asumir ocasión sin preguntar" (ej. evitar *"Perfecto, para tu boda…"* sin haber preguntado). El regex actual es demasiado amplio. Soluciones:
- Quitar "ocasion" del `not_expected` (la regla T1 sigue siendo solo el `check`).
- O hacer el `not_expected` más específico: `\\bocasion\\s+(detectada|elegida|seleccionada)\\b` (solo penaliza si la palabra aparece como ASUNCIÓN, no como pregunta).

## T2

**Input:** `"No sé, lo que tú veas"` — usuario delega la decisión al agente.

**Comportamiento observado:** *"Sin problema, cuéntame para quién es y te propongo algo."* — ❌ **BUG REAL DEL PLAYBOOK:** sigue preguntando en vez de tomar iniciativa. El usuario ya dijo "tú decides" y el agente vuelve a pedir info.

**Análisis del check:** `ramo|bouton|rosa|opcion|popular|precio` — el test espera que Petal proponga productos concretos cuando el usuario delega.

**Causa raíz:** Compra v39 no tiene regla de "delegación" — cuando el usuario dice "tú decides", "lo que tú veas", "elige tú", el agente debería mostrar opciones populares por defecto en lugar de seguir refinando.

**Recomendación T2:** añadir regla al playbook Compra (sección Casos especiales): *"Si el usuario delega la decisión ('tú decides', 'lo que veas', 'elige tú'), mostrar 3 opciones populares de la ocasión inferida (o de regalo genérico si no hay ocasión) sin pedir más refinamiento."*
