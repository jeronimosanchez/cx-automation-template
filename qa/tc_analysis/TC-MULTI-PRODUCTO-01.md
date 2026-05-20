---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"quiero un ramo de rosas y un centro de mesa para una boda"* | — |
| 2 | Orquestador | clasifica como G5 (Compra), extrae `ocasion_detectada=Boda`, `modo_tono=estandar`, `producto=∅` | ⚠️ Detecta correctamente Boda pero NO captura que hay 2 productos distintos ("ramo" + "centro de mesa") — slot `producto` queda vacío porque no hay convención para multi-producto |
| 3 | Compra | recibe `producto=∅` + `ocasion=Boda` → flujo "sugerir productos para boda" → elige Ramo de Novia Rosas L | 🔴 Ignora silenciosamente el "centro de mesa" mencionado en `intencion_inicial`. No hay rama en el Playbook que detecte "X y Y" |
| 4 | Agente | *"Claro, para boda tengo el Ramo de Novia Rosas — L (12 flores, 45€). ¿Te gusta o miramos otras opciones?"* | 🔴 Respuesta mono-producto. No reconoce el segundo ítem, no propone secuenciar, no explica limitación |
| 5 | Test (check) | regex `centro.{0,80}ramo\|ramo.{0,80}centro\|empez.{0,20}por\|uno.{0,20}vez\|un producto` | 🔴 FAIL — la respuesta solo menciona "ramo"; nunca aparece "centro", ni "empezamos por", ni mención de limitación. Check bien calibrado |

### Causa raíz (descompuesta en 3 capas)

1. **Capa 1 (Orquestador — slots mono-producto)**: El esquema de slots es singular (`producto`). No existe `productos[]` ni flag `multi_producto_detectado`. La `intencion_inicial` se preserva como texto libre pero no se inspecciona para detectar conjunciones ("y", "también", "además").
2. **Capa 2 (Playbook Compra — sin rama multi-ítem)**: No hay CASO ESPECIAL que dispare cuando el usuario menciona ≥2 productos distintos. El flujo asume 1 producto por turno y va directo a recomendar. La señal de multi-ítem queda enterrada en `intencion_inicial` sin extraerla.
3. **Capa 3 (convención conversacional indefinida)**: No hay política sobre cómo manejar pedidos multi-ítem (¿secuencial? ¿explicar limitación? ¿lista combinada?). El agente, sin instrucción explícita, elige la peor opción: silenciar el segundo ítem.

## Recomendación

### Solución recomendada: #1 — CASO ESPECIAL multi-producto en Playbook Compra

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: Reutiliza el patrón arquitectónico ya validado de CASOS ESPECIALES (mismo mecanismo que TC-URGENCIA-01). Local al Playbook Compra, no toca Orquestador ni schema de slots. Detecta multi-ítem inspeccionando `intencion_inicial` con conjunciones y dispara una respuesta que reconoce ambos productos y propone "empezamos por X". Cubre exactamente la regex del check (`ramo.*centro` + `empez.*por`). Bajo coste, bajo riesgo de regresión.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **CASO ESPECIAL multi-producto en Playbook Compra**: detectar 2+ productos en `intencion_inicial` ("X y Y"), reconocer ambos y proponer secuenciar | 🟢 9/10 | — | Patrón ya probado (urgencia). Local, rápido, sin regresión en flujo mono-producto. Cubre la regex del check y la UX real |
| 2 | **Combinación #1 + #3**: Playbook con CASO ESPECIAL + Orquestador marca `multi_item=true` y pasa lista de productos | 🟢 8/10 | Edit Orquestador + contrato de slots | Solución arquitectónica más limpia (separa detección de gestión). Coste mayor y más superficie de regresión. Recomendable a medio plazo |
| 3 | **Detección en Orquestador**: nuevo flag `multi_item=true` y `productos_solicitados=[ramo, centro]` | 🟡 7/10 | Edit Orquestador + reacción en Compra | Sin lógica en Compra el flag no produce respuesta correcta. Solo aporta valor combinado con #1 |
| 4 | **Instrucción genérica anti-omisión** en Playbook Compra ("si el user menciona varios productos, recónocelos todos antes de elegir uno") | 🟡 6/10 | — | Más flexible que el CASO ESPECIAL pero menos determinista. Gemini puede ignorarla en variaciones léxicas. Útil como red complementaria a #1 |
| 5 | **Few-shot example multi-producto** ("ramo y centro para boda" → respuesta correcta) sin CASO ESPECIAL explícito | 🟡 5/10 | Generar 1-2 examples nuevos | Refuerza determinismo en inputs cercanos pero alcance limitado por similitud léxica. Multiplicador útil de #1, no sustituto |
| 6 | **Ampliar slot `producto` a lista** + carrito implícito multi-ítem real | 🟡 5/10 | Refactor slots + catálogo + carrito | Cambia el modelo de datos end-to-end. Alto impacto en 49 TCs. Anti-regresión costoso para 1 TC actual |
| 7 | **Recalibrar test**: aceptar respuesta mono-producto como válida | 🔴 2/10 | — | Esconde el bug UX real. El user percibe que el agente "ignora" parte de su petición. El check refleja comportamiento legítimamente esperado, no es falso negativo |

### Plan de acción (Solución #1)

1. **Añadir CASO ESPECIAL multi-producto** al Playbook Compra (sección CASOS ESPECIALES, junto a urgencia/plazo) → `definitions/playbooks/compra.yaml`
   - Trigger: el user menciona 2+ productos distintos unidos por "y"/"también"/"además" en `intencion_inicial` (p.ej. `ramo|centro|corona|bouquet|arreglo|caja` × 2)
   - Acción: reconocer ambos productos explícitamente y proponer secuenciar. Respuesta tipo:
     *"Perfecto, te ayudo con los dos. Empiezo por el ramo y luego vemos el centro de mesa, ¿te parece? Para boda tengo el Ramo de Novia Rosas — L (12 flores, 45€). ¿Te encaja?"*
2. **Commit + push** → CI corre `Deploy to Petal CX` + `QA Petal` automáticamente
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable de TC-MULTI-PRODUCTO-01 y 0 regresiones en TCs mono-producto

**Coste total**: ~15 min (10 edición + 5 validación, +2 min deploy CX)
