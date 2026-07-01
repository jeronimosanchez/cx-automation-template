# TC-BODA-01 — Análisis de causa raíz

**TC:** TC-BODA-01 · Modo Boda — ramo nupcial  
**Grupo:** G5  
**Estado:** FAIL (0/1)  
**Fecha análisis:** 2026-07-01  
**Analista:** qa-tc-analyzer  

---

## Resumen ejecutivo

El TC falla por la presencia del emoji 🌸 (cherry blossom) en la segunda mitad de la respuesta del agente. La respuesta completa es una **doble respuesta concatenada**: un turno del Orquestador seguido de un turno de Compra pegados en el mismo mensaje. Eso es el síntoma arquitectónico central. El 🌸 aparece en el turno de Compra en registro `celebracion`, donde la instrucción lo **permite** (max. 1 emoji 🌸 por turno). El fallo es una **combinación de dos problemas independientes**: doble respuesta (arquitectura) + check de test posiblemente mal calibrado (el 🌸 puede ser válido en celebración). El fix depende de cuál de los dos problemas es el root cause real.

---

## 1. Input y output

| Campo | Valor |
|---|---|
| Input | `quiero un ramo de novia para mi boda` |
| $grupo_intent | G5 |
| $intencion_inicial | `quiero un ramo de novia para mi boda` |
| $producto | `ramo de novia` |
| $registro | `celebracion` |
| $ocasion_detectada | `Boda` |
| Check fallido | `not_expected: [🌸]` |
| Check OK | `expected: [ramo]` |

---

## 2. Respuesta completa del agente

```
¡Enhorabuena por tu boda! 💐 Tenemos ramos de novia preciosos. ¿Tienes alguna flor o estilo en mente?
¡Qué bonito, una boda! 🌸 Tenemos el Ramo de Novia Rosas Blancas — S (6 flores, 35€). ¿Te gustaría pedirlo?
```

Dos frases completas separadas por `\n`. Síntoma inequívoco de doble respuesta.

---

## 3. Análisis — 9 capas

### Capa 1 — Check / Test

El check `not_expected: [🌸]` detecta correctamente que 🌸 apareció. La pregunta es si ese check está bien calibrado.

Según `compra.yaml` sección TONO:
```
- celebracion: max. 1 exclamacion y 1 emoji 🌸 por turno. Calidez genuina.
- estandar: natural, fresco. 'Mira,', 'genial', emoji 🌸 ocasional.
- solemne: sin exclamaciones, sin emoji 🌸, sin 'genial'/'perfecto!'.
```

Para `$registro=celebracion` el 🌸 está **permitido** (hasta 1 por turno). El check `not_expected: [🌸]` sería incorrecto si asume que celebración prohíbe este emoji. Sin embargo, si el check pretende detectar el 🌸 del segundo mensaje (el turno de Compra que no debería existir como respuesta visible), el check es correcto como proxy de la doble respuesta.

**Veredicto capa 1:** check ambiguo — puede ser mal calibrado (prohíbe algo permitido) o correcto como proxy indirecto de la doble respuesta. Requiere resolución en capas siguientes.

### Capa 2 — Instrucción de emoji (Compra)

`compra.yaml` L248-252:
```
solemne: sin exclamaciones, sin emoji 🌸, sin 'genial'/'perfecto!'.
celebracion: max. 1 exclamacion y 1 emoji 🌸 por turno. Calidez genuina.
estandar: natural, fresco. 'Mira,', 'genial', emoji 🌸 ocasional.
```

La instrucción es coherente. Para `celebracion` el 🌸 en el turno de Compra es válido. **No hay bug de instrucción en Compra** respecto al emoji.

### Capa 3 — Instrucción de emoji (Orquestador)

`petal_cx_orchestrator.yaml` sección TONO (L209-212):
```
APLICACIÓN:
Aplica $registro en cada respuesta.
Si $registro=solemne: sin exclamaciones, sin "¡Genial!", foco en la tarea.
```

El Orquestador **no tiene tabla de emoji** equivalente a la de Compra. Solo restringe para solemne ("sin exclamaciones"). Para `celebracion`, el Orquestador no tiene regla de emoji explícita. El Orquestador usó 💐 (bouquet) en su turno, que es correcto. Pero la ausencia de regla explícita para celebración en el Orquestador no causó el 🌸 — ese emoji viene del turno de Compra.

**No hay bug de instrucción de emoji en el Orquestador.** El 💐 es correcto. El 🌸 pertenece al turno de Compra y es legítimo por instrucción.

### Capa 4 — Doble respuesta (síntoma arquitectónico)

La respuesta concatenada indica que **el Orquestador respondió al usuario Y luego transfirió a Compra sin silencio**, y Compra también respondió. Ambas respuestas llegaron concatenadas al usuario en el mismo turno.

Según `petal_cx_orchestrator.yaml` L165-166:
```
⛔ NUNCA 'te transfiero con companeros' ni 'te paso con especialista' al ir a Compra.
Las transiciones son invisibles - 'Dejame buscarte opciones' o simplemente actua.
```

Y según `compra.yaml` L465:
```
⛔ NO digas nada al usuario. Transfiere silencioso (salvo TT-25).
```

La instrucción del Orquestador exige transición invisible, pero el Orquestador en este TC **sí respondió** ("¡Enhorabuena por tu boda! 💐 Tenemos ramos de novia preciosos. ¿Tienes alguna flor o estilo en mente?") antes de transferir. Eso viola la regla de transición invisible.

En la arquitectura de Dialogflow CX, cuando un playbook responde Y luego invoca un sub-playbook que también responde en el mismo turno de usuario, ambas respuestas se concatenan. Esto es comportamiento nativo de CX: el Orquestador emitió un mensaje y Compra emitió otro, llegando juntos.

**Root cause primario: el Orquestador respondió al usuario antes de transferir a Compra**, violando la regla de transición invisible para G5. Para G5 la instrucción es capturar y transferir sin turno intermedio (`⛔ NO explores en el Orquestador. Captura y transfiere.`).

### Capa 5 — Routing G5 en Orquestador

El input `quiero un ramo de novia para mi boda` cumple todos los criterios de G5:
- Contiene tipo concreto: `ramo`
- Contiene `novia` (disparador de `Boda` en OCASION silenciosa: `ramo de novia - Boda`)
- Contiene verbo de acción: `quiero`

La regla ANTI-G3-FALSO-POSITIVO confirma G5. La instrucción G5 dice:
```
⛔ NO pidas email. NUNCA.
- Guarda $intencion_inicial.
- Parsea $ocasion_detectada, $cantidad, $precio_max del utterance.
- $grupo_intent='G5'
- Si $id_cliente vacio - ${PLAYBOOK:Compra} con $intencion_inicial, ...
```

No hay "responde al usuario" entre esos pasos. El Orquestador debería haber transferido directamente sin emitir mensaje. Sin embargo, emitió "¡Enhorabuena por tu boda! 💐...". Esto sugiere que el LLM del Orquestador interpretó la detección de `$registro=celebracion` como una oportunidad de responder emocionalmente antes de transferir.

**Bug confirmado: el Orquestador respondió en G5 cuando no debería.** La instrucción no es lo suficientemente explícita en prohibir una respuesta emocional de acuse de recibo para `$registro=celebracion` antes de transferir.

### Capa 6 — Comportamiento de Compra (segundo mensaje)

El segundo mensaje "¡Qué bonito, una boda! 🌸 Tenemos el Ramo de Novia Rosas Blancas — S (6 flores, 35€). ¿Te gustaría pedirlo?" corresponde a Compra respondiendo al input inicial con `$registro=celebracion`. El comportamiento de Compra en sí es correcto:
- ECO: "¡Qué bonito, una boda!" (conector de celebración válido)
- CONTINUIDAD: muestra un producto
- El 🌸 está dentro del límite (1 por turno)

La respuesta de Compra es **funcionalmente correcta**. El problema es que llega concatenada con la del Orquestador.

### Capa 7 — Calibración del check

El check `not_expected: [🌸]` está diseñado para validar que ciertos emojis no aparezcan. En contexto `celebracion`, este check es **demasiado restrictivo**: prohíbe un emoji que la instrucción permite explícitamente.

Si el objetivo del check era detectar la doble respuesta, el check correcto sería detectar la concatenación (`\n¡` como patrón), no el emoji en sí.

**El check está mal calibrado** para el caso celebracion: prohíbe algo que el playbook permite. Esto hace que el TC falle incluso si la doble respuesta se corrige y Compra produce una respuesta correcta con 🌸.

### Capa 8 — Interacción de los dos bugs

Hay dos bugs independientes que interactúan:

1. **Bug A (Arquitectura):** El Orquestador responde en G5 antes de transferir → doble respuesta. Gravedad alta, siempre presente para `$registro=celebracion` + G5.
2. **Bug B (Test):** El check `not_expected: [🌸]` prohíbe un emoji válido en celebración. Gravedad media: hace que el TC falle incluso sin la doble respuesta.

Si se corrige solo Bug A (sin respuesta del Orquestador), Compra responde sola con 🌸 → el TC sigue fallando por Bug B.  
Si se corrige solo Bug B (remove 🌸 del check o cambia scope), el TC pasa pero la doble respuesta queda sin detectar.  
El fix óptimo resuelve ambos o redefine el check para detectar la doble respuesta directamente.

### Capa 9 — Patrón sistémico

Este patrón (Orquestador responde + transfiere en el mismo turno de detección emocional) puede afectar otros TCs de ocasión especial donde `$registro=celebracion` se detecta en el Orquestador. Si el LLM tiende a emitir un acuse emocional en celebración antes de transferir, cualquier TC con boda/aniversario/nacimiento en el turno inicial podría producir doble respuesta.

---

## 4. Diagnóstico

| # | Bug | Componente | Tipo | Gravedad |
|---|---|---|---|---|
| A | Orquestador responde antes de transferir en G5/celebracion | `petal_cx_orchestrator.yaml` | Bug Playbook | Alta |
| B | Check not_expected[🌸] prohíbe emoji válido en celebración | TC check | Test mal calibrado | Media |

**Root cause primario:** Bug A — instrucción del Orquestador no prohíbe explícitamente emitir respuesta emocional en G5 cuando detecta `$registro=celebracion`.

**Root cause secundario:** Bug B — el check `not_expected: [🌸]` asume que 🌸 nunca debe aparecer, sin discriminar por `$registro`.

---

## 5. Soluciones (ordenadas DESC por score)

### Solución 1 — Fix Orquestador: prohibir respuesta en G5 (score: 9/10)

**Tipo:** Bug Playbook  
**Tiempo estimado:** ~15 min  
**Archivo:** `definitions/playbooks/petal_cx_orchestrator.yaml`  
**Riesgo:** Bajo — refuerza instrucción existente sin cambiar lógica  

Añadir en la sección G5, inmediatamente antes de la transferencia, una regla explícita:

```
G5 COMPRA (comprar, explorar con producto concreto)
⛔ NO pidas email. NUNCA.
⛔ NO emitas ningún mensaje al usuario antes de transferir, aunque $registro=celebracion o solemne.
   La detección emocional es silenciosa — el tono lo aplica Compra, no el Orquestador.
- Guarda $intencion_inicial.
...
```

**Por qué score 9:** resuelve el root cause primario, impacto en todos los TCs de ocasión especial en G5, sin riesgo de regresión. El 🌸 en la respuesta de Compra será el único y estará dentro del límite permitido.

**Limitación:** si el check B no se corrige también, el TC seguirá fallando (Compra producirá 🌸 legítimo y el check lo rechazará).

---

### Solución 2 — Fix test: ajustar check not_expected[🌸] para solemne únicamente (score: 8/10)

**Tipo:** Test mal calibrado  
**Tiempo estimado:** ~10 min  
**Archivo:** `qap/test_qa_playbooks.py` o YAML de TCs  
**Riesgo:** Bajo — no toca producción  

El check `not_expected: [🌸]` debería restringirse a `$registro=solemne`. Para `celebracion` y `estandar`, 🌸 es válido. Reemplazar por:

```
not_expected_if_registro_solemne: [🌸]
```

o añadir condición en el runner:
- Si `$registro == 'solemne'` → 🌸 es not_expected
- Si `$registro == 'celebracion'` → 🌸 es permitido (hasta 1)

**Por qué score 8:** resuelve el Bug B de forma correcta semánticamente. Independiente del fix A. Sin embargo, si se aplica solo, el TC puede pasar aunque la doble respuesta persista (la respuesta de Compra con 🌸 sería válida).

---

### Solución 3 — Fix combinado: Orquestador + check (score: 10/10, combinación 1+2)

**Tipo:** Bug Playbook + Test mal calibrado  
**Tiempo estimado:** ~25 min  
**Archivos:** `definitions/playbooks/petal_cx_orchestrator.yaml` + runner/YAML TCs  
**Riesgo:** Bajo  

Aplicar Solución 1 y Solución 2 juntas. El TC pasa porque:
1. El Orquestador no emite mensaje → no hay doble respuesta
2. Compra emite respuesta correcta con 🌸 (dentro del límite celebración)
3. El check ya no penaliza 🌸 en celebración

Añadir un check adicional para detectar doble respuesta si se quiere cobertura explícita:
```
not_expected: ["?\n¡", "?\n¡"]   # patrón de dos frases completas en un turno
```

**Por qué score 10:** cierre completo de ambos bugs + cobertura futura de doble respuesta.

---

### Solución 4 — Fix alternativo: añadir ejemplo negativo en Orquestador (score: 6/10)

**Tipo:** Bug Playbook (mitigación parcial)  
**Tiempo estimado:** ~20 min  
**Archivo:** `definitions/playbooks/petal_cx_orchestrator.yaml` o `definitions/examples/`  
**Riesgo:** Bajo  

Añadir un ejemplo negativo explícito en el Orquestador que muestre el comportamiento incorrecto vs correcto para G5/celebración:

```
INCORRECTO (G5 + celebración): emitir "¡Enhorabuena por tu boda!" antes de transferir
CORRECTO (G5 + celebración): transferir directamente a Compra sin turno intermedio
```

**Por qué score 6:** los ejemplos ayudan pero son menos deterministas que la regla explícita de la Solución 1. Riesgo de que el LLM igual emita el mensaje en variaciones del input. Complementario a Solución 1, no sustituto.

---

## 6. Recomendación

**Fix recomendado: Solución 3 (combinación 1+2)**

Orden de ejecución:
1. Fix Orquestador (Solución 1) — 15 min
2. Fix check en runner/YAML (Solución 2) — 10 min
3. Verificar con rerun del TC

---

## 7. Impacto en otros TCs

| TC potencialmente afectado | Razón | Acción |
|---|---|---|
| Cualquier TC con boda/aniversario/nacimiento en turno 1 | Mismo patrón G5 + celebración en Orquestador | Revisar si produce doble respuesta |
| TCs con check `not_expected: [🌸]` y $registro=celebracion | Check mal calibrado | Revisar scope del check |

---

## 8. Evidencia

- `compra.yaml` L248-252: tabla de emoji por registro — celebración permite 🌸
- `petal_cx_orchestrator.yaml` L165-166: transiciones invisibles a Compra
- `petal_cx_orchestrator.yaml` L315-323: instrucción G5 — no menciona prohibición de respuesta emocional previa
- Respuesta del agente: dos frases completas con interrogación separadas por `\n` — inequívoco de doble respuesta

---

*Análisis generado por qa-tc-analyzer · batch 20260701_170805*
