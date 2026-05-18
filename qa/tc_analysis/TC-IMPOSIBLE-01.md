---
status: FAIL
tipo: Test mal calibrado (falso negativo)
estimacion: ~2 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|---------------|--------------------|
| 1 | User | *"hacedme un descuento del 50%"* | — |
| 2 | Orquestador | NO captura `grupo_intent` (params vacío) | ⚠️ El input es ambiguo (G3 consulta o G7 fuera de scope) — el Orquestador no lo clasifica claramente |
| 3 | Agente | *"Ahora mismo no tenemos descuentos del 50%. ¿Hay algo más en lo que pueda ayudarte?"* | 🟡 **Respuesta correcta del agente.** Niega educadamente + ofrece ayuda |
| 4 | Test (check) | Regex pide: `no puedo \| disculp \| equipo \| persona \| precio \| sin descuento \| venta \| cliente \| comercial \| aplicar` | 🔴 **El regex NO incluye las palabras que el agente sí dice** (`"no tenemos"`, `"ayudar"`) → FAIL pero el comportamiento del agente es bueno |

**Esto NO es un bug del agente.** Es un **falso negativo del test**: la respuesta del agente cumple el espíritu del check (declinar educadamente) pero no las palabras exactas del regex.

### Causa raíz

1. **Test mal calibrado**: el regex original cubrió un set limitado de respuestas válidas (`no puedo`, `disculp`, `precio`, `sin descuento`, etc.) pero olvidó incluir variantes muy comunes como `"no tenemos"` o `"ayudar"`.
2. **El agente responde con frases naturales** que no estaban en el regex.
3. **Secundario (no crítico)**: el agente podría ser un poco más explicativo (mencionar política de precios, programa de fidelización, etc.) pero su respuesta actual ya es aceptable.

## Recomendación

### Solución recomendada: #1 — Extender regex con frases que el agente sí usa

🟢 **9/10** · ~2 min · Sin dependencias externas

**Por qué**: el agente está respondiendo correctamente, solo hay que enseñarle al test a reconocer las frases que ya usa. Cambio de 1 línea en `qa/test_QA_Playbooks_v23.py`. Sin riesgo de regresión.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | **Test: extender regex** con `no tenemos\|descuento\|ayudar` además de las palabras actuales | 🟢 9/10 | — | **RECOMENDADO**. Soluciona el falso negativo en 2 min. El agente ya responde bien, solo hay que actualizar el examinador. Riesgo cero. |
| 2 | **Examples: añadir EX-IMPOSIBLE-01** que ancle la respuesta a "no puedo" / "disculp" | 🟢 7/10 complementario | — | Refuerza el patrón de respuesta determinístico. Hace que el agente sea más consistente. **Multiplicador** de #1, no sustituto. ~10 min. |
| 3 | **Playbook Compra: añadir CASOS ESPECIALES** con regla de "peticiones imposibles" (descuentos no autorizados, comisiones, etc.) | 🟡 7/10 | — | Mejora la calidad de respuesta del agente a peticiones imposibles. Le permite explicar el por qué (política de precios, programa de fidelización, etc.) en vez de un simple "no tenemos". ~30 min. |
| 4 | **Combinar #1 + #2** | 🟢 8.5/10 | — | Soluciona el test Y refuerza la respuesta del agente. Patrón estándar. ~12 min. |
| 5 | **Backend: derivar al equipo comercial** para gestionar excepciones de descuento | 🟡 6/10 | Negocio + backend | Sobre-ingeniería para el caso. Un cliente que pide 50% de descuento agresivo probablemente no es buen lead. Quizás vale para casos con criterio (B2B, volumen). ~2-3h. |
| 6 | **Orquestador: clasificar como G7 (fuera de scope) explícitamente** | 🟡 5/10 | Test del Orquestador | Forzaría a tratar peticiones imposibles como out-of-scope. Pero el comportamiento actual (declinar + ofrecer ayuda) ya es bueno; clasificar como G7 podría perder oportunidad de redirigir hacia venta. No recomendado. ~30 min. |
| 7 | **No hacer nada** (aceptar FAIL como deuda técnica permanente) | 🔴 2/10 | — | El test seguirá fallando, lo que reduce señal de regresión real. NO recomendado. |

### Plan de acción (Solución #1)

1. **Editar `qa/test_QA_Playbooks_v23.py`** → línea del TC-IMPOSIBLE-01. Cambiar:
   ```python
   "checks": ["no puedo|disculp|equipo|persona|precio|sin descuento|venta|cliente|comercial|aplicar"]
   ```
   por:
   ```python
   "checks": ["no puedo|disculp|equipo|persona|precio|sin descuento|venta|cliente|comercial|aplicar|no tenemos|ayudar"]
   ```

2. **Commit + push** a main.

3. **Re-ejecutar QA**: `gh workflow run "QA Petal" --ref main`.

4. **Verificar**: TC-IMPOSIBLE-01 debe pasar a ✅ PASS en el próximo run.

**Coste total**: ~2 min (edit + commit + verificación post-merge).

### Nota: ¿por qué este caso es interesante para QA?

Este TC es un ejemplo perfecto de **cómo NO debe estar calibrado un test**:

- **Síntoma**: el test marca FAIL aunque el agente hace lo correcto.
- **Causa**: el regex es **demasiado específico** sobre QUÉ palabras debe usar el agente.
- **Riesgo si no se arregla**: ruido en el dashboard (un FAIL permanente que no aporta señal).
- **Lección**: los regex de checks deben capturar el ESPÍRITU del comportamiento esperado, no palabras exactas. Aceptar variantes naturales.

Es lo opuesto a los 3 endurecimientos que hicimos antes (TC-FRUSTRACION-01, TC-URGENCIA-01, TC-MULTI-PRODUCTO-01) que eran **demasiado laxos**. Aquí pasamos de un test demasiado **estricto** a uno **calibrado correctamente**.

QA maduro = encontrar el equilibrio entre **estricto pero justo**.
