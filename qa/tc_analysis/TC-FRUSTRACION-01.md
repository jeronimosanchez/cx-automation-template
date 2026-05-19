---
status: FAIL
tipo: Bug Playbook (escalación tardía) + Test calibración fina
estimacion: ~1h (Solución #7 recomendada)
---

## T3

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"quiero rosas"* | — |
| 2 | Compra | Extrae slots: `producto=rosas`, `grupo_intent=G5`. Responde *"¿Para qué ocasión las quieres?"* | ✅ Correcto. Pregunta legítima de refinamiento (PASO 1 de Compra: slot filling) |
| 3 | User | *"no me gustan"* | — |
| 4 | Compra | Responde *"¿No te gustan las rosas? Sin problema, cuéntame para quién es y te propongo algo."* | ✅ Acusa recibo + ofrece refinamiento |
| 5 | User | *"tampoco me convencen, dame otras"* (2º rechazo consecutivo) | — |
| 6 | Compra | Responde *"Claro, te busco otras. ¿Dime para quién es y yo me encargo?"* | 🔴 **Bug**: el agente debería escalar (handoff a humano) tras 2 rechazos consecutivos. En cambio, sigue insistiendo en refinar. La frase es bienintencionada pero **no aporta valor nuevo** (ya pidió la ocasión en T2). |
| 7 | User | *"ninguna me gusta"* (3º rechazo) | — |
| 8 | Compra | Finalmente escala: *"Creo que lo mejor es que hables con mi equipo - ellos te encontrarán exactamente lo que buscas. Hola, soy Alicia..."* | ✅ Handoff correcto, pero **TARDÍO** (debería haber sido en T3, no T4) |

### Causa raíz (descompuesta en 2 capas)

1. **Playbook Compra — falta regla de escalación temprana**: el playbook no tiene una regla explícita de *"si usuario rechaza N veces consecutivas, escalar al equipo humano"*. El agente intenta refinar indefinidamente hasta que el usuario explícitamente dice *"ninguna me gusta"* (T4). El bug es que en T3 ya hay 2 rechazos consecutivos (T2 + T3) y eso debería ser señal suficiente para escalar.

2. **Test calibrado finamente, pero correctamente**: el regex de T3 (`propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano`) exige que el agente proponga alternativas concretas o escale. El agente dice *"te busco otras"* y *"yo me encargo"* — semánticamente similar pero NO matchea palabras concretas del regex. Este FAIL es **legítimo**: el test detecta correctamente que el agente no escala cuando debería.

**Limitación del análisis**: con los datos del JSON solo vemos `params` finales (no la traza interna del playbook). No sabemos si Compra tiene una variable `rechazos_consecutivos` o similar que debería incrementarse — probablemente no, lo que confirma la causa raíz.

## Recomendación

### Solución recomendada: #7 — Combinar #1 + #3 (Regla escalación + Example ancla)

🟢 **9/10** · ~1h total · Sin dependencias externas

**Por qué**: fix estructural en playbook (escalación tras 2 rechazos) + ancla determinística en Example que muestre el comportamiento esperado. Reduce flakiness entre runs. Demuestra empatía del agente sin alargar conversaciones infructuosas. UX significativamente mejor.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 7 | **Combinar #1 + #3** (Regla escalación tras 2 rechazos + Example ancla) | 🟢 9/10 | — | **RECOMENDADO**. Fix estructural + ancla determinística. Resuelve el bug real y reduce flakiness del LLM. Patrón validado en otros TCs (Checkout, Registro). ~1h. |
| 1 | **Fix Playbook Compra: añadir regla `ESCALACIÓN TEMPRANA` en `CASOS ESPECIALES`**. Si usuario rechaza ≥2 veces consecutivas (ej. "no me gusta", "ninguna me convence"), escalar al equipo humano con `razon_handoff=frustracion_usuario` | 🟢 8.5/10 | — | Bug fix directo. Sin Example, el LLM puede ejecutar la regla de forma inconsistente entre runs. ~30 min. |
| 3 | **Fix Examples: añadir `EX-FRUSTRACION-ESCALADA`** mostrando comportamiento: T1 propuesta → T2 alternativa → T3 escalación con handoff | 🟢 8/10 complementario | — | Reduce flakiness. NO resuelve el bug del playbook por sí solo. **Multiplicador** de #1. ~20 min. |
| 2 | **Fix Test: ampliar regex T3** para aceptar `busco|encargo` además de `propongo|alternativ|equipo` | 🟡 6/10 | — | Hace que el test pase pero **enmascara el bug**. El agente seguiría sin escalar a tiempo. Solo aceptable si combinamos con #1 (ampliar regex Y arreglar playbook). ~5 min. |
| 4 | **Tracking explícito de rechazos en `params`**: añadir contador `n_rechazos` que el playbook actualiza por turno | 🟡 6/10 | Refactor params en Compra | Solución más robusta pero requiere refactor. Permite escalación basada en estado, no en NLP. ~2h + tests. |
| 5 | **Detectar frustración semánticamente** (sentiment analysis del usuario) y escalar cuando detecte negatividad | 🟡 5/10 | Tool externa o LLM extra | Sobre-ingeniería. El playbook actual ya escala correctamente cuando el usuario insiste, solo le falta hacerlo antes. ~3-5h + dependencia externa. |
| 6 | **No hacer nada** (aceptar FAIL como deuda técnica) | 🔴 2/10 | — | El test seguirá fallando. Pierde señal de regresión real. El bug del agente (escalación tardía) seguirá afectando UX. NO recomendado. |

### Plan de acción (Solución #7)

1. **Editar `definitions/playbooks/compra.yaml`** → sección `# CASOS ESPECIALES`. Añadir bloque `ESCALACIÓN TEMPRANA`:
   - Trigger: usuario expresa rechazo ≥2 veces consecutivas (frases como "no me gusta", "no me convence", "ninguna me sirve", "dame otras")
   - Acción: escalar inmediatamente con `razon_handoff=frustracion_usuario` (sin pedir más refinamiento)
   - Mensaje: *"Veo que las opciones no te encajan. Te paso con mi equipo, ellos podrán darte una atención más personalizada."*

2. **Crear Example `EX-FRUSTRACION-ESCALADA`** en `definitions/examples/`:
   - Input simulado de 3 turnos con rechazos progresivos
   - Output esperado: T1 oferta inicial → T2 alternativa → T3 escalación con handoff (NO T4)

3. **Re-ejecutar QA** con `--runs 3`:
   - TC-FRUSTRACION-01 debe pasar mostrando escalación en T3 (no T4)
   - Verificar que el handoff incluye `razon_handoff` y que el mensaje del agente menciona "equipo" o "humano"

**Coste total**: ~1h (playbook 30 min + example 20 min + QA 10 min).

### Nota: ¿por qué este caso es interesante para QA?

Este TC ilustra una sutileza importante:

- **El agente NO está roto** — termina escalando correctamente en T4
- **Pero la UX es subóptima** — un cliente frustrado en T3 ya está cerca de abandonar. Esperar a T4 puede perder el lead
- **El test endurecido detecta esa sutileza** — exige escalación temprana

Es un buen ejemplo de **calidad conversacional avanzada**: no basta con que el agente "haga lo correcto eventualmente", debe hacerlo **en el turno adecuado** para minimizar fricción.
