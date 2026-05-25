---
status: FAIL
tipo: Bug Playbook
estimacion: ~20min
---

# TC-FRUSTRACION-01 — Multiples rechazos consecutivos — debe escalar o reformular

**Grupo:** COMPRA-ZG | **Tipo:** EDGE | **Runs:** 0/1 PASS | **Fecha:** 2026-05-25 16:11

---

## Turnos vs Problemas detectados

| Turno | Usuario | Agente (resumen) | Check | Problema |
|-------|---------|------------------|-------|----------|
| T1 | "quiero rosas" | Pregunta por ocasión especial | ✅ PASS | Ninguno |
| T2 | "no me gustan" | Reconoce y pregunta por color preferido | ✅ PASS | Ninguno |
| T3 | "tampoco me convencen, dame otras" | Muestra 3 alternativas del catálogo | ❌ FAIL | Regex espera `[propongo\|alternativ.{0,30}tipo\|otra ocasion\|equipo\|persona\|humano]`; el agente preguntó por "color" en T2 y en T3 mostró catálogo — ningún token del regex aparece en la respuesta de T3 |
| T4 | "ninguna me gusta" | Escala al equipo humano | ✅ PASS | Ninguno — escalación funciona correctamente |

---

## Causa raíz — 9 capas [v1.1]

### Capa 1 — Instrucción de playbook 📄 [CAUSA RAÍZ]

**compra.yaml, línea 726**, sección `GESTION DE FRUSTRACION`:

```
Rechazo 2 pregunta motivo.
```

"Motivo" es ambiguo: el LLM lo interpreta como preguntar por preferencia de color, que es una respuesta válida y sensata, pero no alineada con lo que verifica el test. La instrucción no especifica qué dimensión explorar (tipo de flor, ocasión, estilo) ni prohíbe mostrar catálogo en este paso. El comportamiento en T2 y T3 es coherente con la instrucción ambigua — el agente no falla, la instrucción falla.

### Capa 2 — Lógica de flujo / condiciones 🔀 [LIMPIA]

El mecanismo de conteo de rechazos funciona: T4 (Rechazo 3 acumulado) escala correctamente al equipo humano. La progresión Rechazo 1 → 2 → 3 → 4 está operativa. No hay bug de flujo.

### Capa 3 — Datos / Sheet 📊 [NO APLICA]

SHEET_OK. La lógica de frustración es puramente comportamental y no depende de datos externos.

### Capa 4 — Regex / Verificación del test 🔍 [CONTRIBUYENTE SECUNDARIO]

El regex de T3 verifica: `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano]`

No incluye "color" ni tokens relacionados con preguntar preferencias de color. Esto es un síntoma: si la instrucción se corrige para guiar al agente a preguntar por tipo/ocasión, el regex quedará cubierto. El regex no es el problema primario, pero vale revisar si "color" debería añadirse como alternativa válida.

### Capa 5 — Prompt del orquestador 🧠 [LIMPIA]

Orquestador v65. La gestión de frustración es responsabilidad del playbook Compra, no del orquestador. No hay evidencia de interferencia.

### Capa 6 — Contexto conversacional / slots 🗂️ [LIMPIA]

No hay slots relevantes en este flujo de rechazo. El agente no pierde contexto entre turnos — recuerda que se habían rechazado rosas y peonías/girasoles/gerberas.

### Capa 7 — Herramientas / Tools 🔧 [NO APLICA]

No se invocan tools en este flujo. El catálogo mostrado en T3 proviene del LLM directamente (no de una tool call verificable en el TC).

### Capa 8 — NLU / Clasificación de intent 🎯 [LIMPIA]

Los inputs del usuario son claros y cortos. No hay ambigüedad de clasificación. El agente entiende correctamente que T3 es otro rechazo y contabiliza acumulado.

### Capa 9 — Modelo / Temperatura 🌡️ [LIMPIA]

El comportamiento es determinista y consistente con la instrucción ambigua. No es variación estocástica — en todas las ejecuciones con esta instrucción el agente preguntaría algo similar. Cambiar temperatura no resolvería el bug.

---

### Resumen visual de capas

| Capa | Nombre | Estado |
|------|--------|--------|
| 1 | Instrucción de playbook | 🔴 CAUSA RAÍZ |
| 2 | Lógica de flujo / condiciones | ✅ LIMPIA |
| 3 | Datos / Sheet | ⬜ NO APLICA |
| 4 | Regex / Verificación del test | 🟡 CONTRIBUYENTE SECUNDARIO |
| 5 | Prompt del orquestador | ✅ LIMPIA |
| 6 | Contexto conversacional / slots | ✅ LIMPIA |
| 7 | Herramientas / Tools | ⬜ NO APLICA |
| 8 | NLU / Clasificación de intent | ✅ LIMPIA |
| 9 | Modelo / Temperatura | ✅ LIMPIA |

---

## Dimensionamiento del bug

| Dimensión | Valor |
|-----------|-------|
| Severidad | Baja — el mecanismo de escalación funciona; solo falla el paso intermedio de reformulación |
| Alcance | Acotado — afecta exclusivamente al Rechazo 2 del bloque GESTION DE FRUSTRACION |
| Regresión | No — el bloque no ha sido tocado en los últimos 20 commits; bug preexistente |
| Complejidad del fix | Trivial — edición de una línea en compra.yaml |
| Impacto en usuario real | Bajo — el agente muestra alternativas válidas; experiencia degradada pero no rota |
| TCs potencialmente afectados | Solo TC-FRUSTRACION-01; otros TCs de compra no verifican este bloque |
| Clasificación | **Trivial** |

---

## Recomendación

### Solución #1 — Precisar instrucción Rechazo 2 en playbook ⭐ RECOMENDADA

**Archivo:** `definitions/playbooks/compra.yaml`, línea 726

**Cambio:**
```
# ANTES
Rechazo 2 pregunta motivo.

# DESPUÉS
Rechazo 2 pregunta tipo de flor preferido u ocasion concreta para reformular la busqueda (no añadir catalogo).
```

**Razonamiento:** La instrucción ambigua "pregunta motivo" deja al LLM libre de interpretar cualquier dimensión. La nueva instrucción fuerza que la pregunta sea sobre tipo de flor u ocasión — tokens que están cubiertos por el regex (`tipo`, `ocasion`) — y además prohíbe explícitamente mostrar catálogo en este paso, lo que mejora la experiencia de usuario (no saturar con opciones antes de entender la preferencia).

**Riesgo:** Muy bajo. El cambio solo afecta Rechazo 2; Rechazo 1, 3 y 4 mantienen su comportamiento actual.

---

### Solución #2 — Ampliar regex T3 para incluir "color"

**Archivo:** `qa/test_QA_Playbooks_v23.py`, sección TC-FRUSTRACION-01, check T3

**Cambio:** Añadir `color` al regex: `[propongo|alternativ.{0,30}tipo|otra ocasion|equipo|persona|humano|color]`

**Razonamiento:** Si preguntar por color es una respuesta válida al Rechazo 2, el test debería aceptarla. Soluciona el FAIL sin tocar el playbook.

**Riesgo:** Medio. El test se vuelve más permisivo y podría enmascarar comportamientos no deseados. La instrucción ambigua quedaría sin corregir, permitiendo que el LLM reformule de formas imprevisibles en el futuro. No se recomienda como solución única.

---

### Solución #3 — Combinar fix playbook + ampliar regex

**Archivos:** `definitions/playbooks/compra.yaml` (línea 726) + `qa/test_QA_Playbooks_v23.py` (regex T3)

**Cambio:** Aplicar Solución #1 y además añadir `color` al regex como token alternativo aceptable.

**Razonamiento:** Máxima robustez: la instrucción precisa guía al agente hacia tipo/ocasión (tokens verificables), y el regex ampliado cubre el caso borde si el agente pregunta por color como dimensión complementaria. Evita falsos negativos futuros ante formulaciones ligeramente distintas.

**Riesgo:** Bajo. El coste es mínimo (dos ediciones triviales) y la cobertura mejora. Recomendable si se quiere blindar el TC contra variabilidad del LLM.

---

### Plan de acción (Solución #1)

1. Abrir `definitions/playbooks/compra.yaml`
2. Localizar línea 726, sección `GESTION DE FRUSTRACION`
3. Reemplazar: `Rechazo 2 pregunta motivo.` → `Rechazo 2 pregunta tipo de flor preferido u ocasion concreta para reformular la busqueda (no añadir catalogo).`
4. Commit: `fix(compra): precisa instruccion Rechazo 2 en GESTION DE FRUSTRACION`
5. PR → merge → esperar deploy
6. Rerun TC-FRUSTRACION-01 — verificar PASS en T3

**Tiempo estimado:** ~20 min (5 min edición + 12-15 min deploy + 2 min rerun)

---

## Patrones cruzados

- **Instrucciones de un solo término sin dimensión explícita** — "pregunta motivo", "reformula", "ofrece alternativa" son instrucciones que el LLM interpreta con libertad. El patrón `[verbo] [objeto vago]` es propenso a comportamientos válidos-pero-no-verificables. Revisar si hay instrucciones similares en otros bloques del playbook Compra (GESTION_CLIENTE, SLOT_FILLING) y añadir dimensión explícita.

- **Regex con gap de cobertura** — el regex de T3 cubre tokens de texto de respuesta final (equipo, persona, humano) y de reformulación estructurada (tipo, ocasion), pero no cubre preguntas de exploración de preferencias (color, estilo, presupuesto). Si el patrón de frustración se amplía en el futuro, los checks deberían cubrir el espectro completo de reformulaciones válidas.

- **Bug preexistente no detectado** — el bloque GESTION DE FRUSTRACION no se ha tocado en 20 commits y el TC lleva tiempo en FAIL (pass_count: 0/1). Indica que los TCs de frustración no se ejecutaban con regularidad o que el TC es nuevo en la suite v23. Priorizar ejecución de todos los TCs EDGE del grupo COMPRA-ZG en el próximo ciclo para detectar bugs latentes similares.
