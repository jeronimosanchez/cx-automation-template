# TC-FRUSTRACION-LEX-01 — Análisis de causa raíz

**Fecha:** 2026-07-01  
**Batch:** 20260701_170805  
**Status:** FAIL (0/1 runs)  
**Tipo:** EDGE | Grupo: COMPRA-ZG  
**Sheet CX:** No disponible (unauthorized)

---

## Resumen ejecutivo

FAIL doble: el check regex del turno 2 está mal calibrado (patrón `entend` no coincide con `Entiendo`) y el playbook ejecuta un comportamiento incorrecto (pregunta de clarificación de producto en lugar de reconocimiento + alternativa/escalación). Ambos problemas son independientes y requieren fixes separados. El fix del test es urgente (5 min); el del playbook requiere validación funcional adicional.

---

## Reproducción del fallo

**Turno 1**
- Usuario: `quiero rosas`
- Agente: `¿Es para alguna ocasión especial? Cumpleaños, boda, decoración...`
- Check: `rosa|ramo|opcion|tamano|ocasion` → **PASS** ✅

**Turno 2**
- Usuario: `esto no funciona, que desastre`
- Agente: `Entiendo tu frustración. Lamento que no estemos conectando bien. ¿Te refieres a la flor rosa o a algo en color rosa?`
- Check: `disculp|entend|alternativ|equipo|persona|propong|reformul|tipo` → **FAIL** ❌

---

## Análisis de 9 capas

### C1 — Regex (causa raíz primaria del FAIL)

El patrón `entend` NO coincide con `Entiendo`:

```
"entend"   → e-n-t-e-n-d
"Entiendo" → E-n-t-i-e-n-d-o
```

La subcadena `entend` busca la secuencia `e·n·t·e·n·d`. En `entiendo` la secuencia es `e·n·t·i·e·n·d·o` — el cuarto carácter es `i`, no `e`. El flag `re.IGNORECASE` solo afecta mayúsculas/minúsculas, no inserta vocales.

Verificación:
```python
import re
re.search("entend", "Entiendo", re.IGNORECASE)  # → None
re.search("entien", "Entiendo", re.IGNORECASE)  # → <Match>
re.search("lament", "Lamento",  re.IGNORECASE)  # → <Match>
```

`lament` sí matchearía `Lamento` — pero `lament` no está en el check actual. Resultado: la respuesta del agente contiene dos señales de reconocimiento (`Entiendo`, `Lamento`) que el check no detecta por estar mal escrito.

### C2 — Comportamiento del agente (causa raíz secundaria)

El agente responde correctamente en la parte emocional (`Entiendo tu frustración. Lamento que no estemos conectando bien.`) pero luego hace una pregunta de clarificación de producto (`¿Te refieres a la flor rosa o a algo en color rosa?`), interpretando "esto no funciona" como referencia al producto "rosa" en lugar de como expresión de frustración.

Este comportamiento no cumple la instrucción del playbook:

- **`compra.yaml` §260 (VIGILANCIA DE CAMBIO):** `FRUSTRACION ('no funciona','un desastre'...) → $registro=solemne · $usuario_frustrado=true`
- **`compra.yaml` §610 (GESTION DE FRUSTRACION):** `PALABRAS NEGATIVAS ('no funciona', 'que mal', ..., 'un desastre', ...) → $frustracion_detectada=true. Siguiente turno: TONO RECONOCIMIENTO + alternativa o escalar.`

La instrucción prescribe: reconocimiento + **alternativa o escalar**. El agente reconoció pero luego preguntó por el tipo de producto, lo cual no es ni alternativa ni escalación — es ignorar el contexto de frustración para resolver una ambigüedad de slot.

### C3 — Cobertura del check (diagnóstico)

El check del turno 2 (`disculp|entend|alternativ|equipo|persona|propong|reformul|tipo`) tiene dos problemas:

1. `entend` es un patrón inválido para capturar `entiendo` (ver C1)
2. `lament` y `sentim` (señales de reconocimiento frecuentes en LLMs) no están incluidas

El check busca 8 señales pero ninguna captura `Lamento` ni formas de `entender` en primera persona del singular.

### C4 — Contexto de turno

El turno 2 llega sin los parámetros `frustracion_detectada` ni `usuario_frustrado` en el JSON del run (ambos ausentes en `params`). Esto sugiere que el Orquestador no propagó la señal de frustración, o que el playbook Compra no detectó el trigger en tiempo real y lo procesó como input de slot-filling en lugar de señal emocional.

### C5 — Instrucción del playbook (evaluación de completitud)

La instrucción en `compra.yaml` §260 y §610 está presente y es correcta en estructura. Sin embargo, existe una ambigüedad: el usuario dice `"esto no funciona, que desastre"` en el turno 2, que aún no hay producto seleccionado ni error real de la herramienta. El agente puede haber interpretado `"esto no funciona"` como ambigüedad sobre el producto `rosas` (¿flor o color?), ejecutando primero el flujo de clarificación de slot y después el reconocimiento emocional. La instrucción no especifica prioridad explícita entre detección de frustración y resolución de slots pendientes.

### C6 — Playbook: Orquestador (dependencia upstream)

El JSON muestra `playbook: "unknown"` en ambos turnos — el trace de atribución no está disponible. No es posible confirmar desde los datos si Compra ejecutó directamente o si el Orquestador transfirió y Compra procesó el turno. La señal FRUSTRACION del §260 debería haberse activado al detectar `"no funciona"` y `"desastre"`.

### C7 — Severidad de comportamiento

El comportamiento del agente no es crítico (no da información falsa, no ignora al usuario) pero es subóptimo: mezcla reconocimiento emocional con pregunta de slot, lo cual puede aumentar la percepción de desconexión. En registro `solemne` (que debería haberse activado por la regla §260), este comportamiento sería especialmente inadecuado.

### C8 — Impacto en suite

TC único de este tipo (léxico negativo en mitad de flujo de compra). No hay otros TCs de frustración detectados en el batch con patrón similar. El fix del regex no tiene impacto negativo en otros TCs.

### C9 — Contexto histórico

El patrón de check mal calibrado (`entend` vs `entiendo`) es análogo a otros casos de la suite donde el patrón truncado no captura la forma conjugada real. Sin historial de regresión previo en este TC.

---

## Diagnóstico final

| Dimensión | Diagnóstico |
|---|---|
| Test | MAL CALIBRADO — patrón `entend` no captura `Entiendo`; falta `lament` en check |
| Playbook | COMPORTAMIENTO SUBÓPTIMO — reconoció frustración pero ejecutó clarificación de slot en lugar de alternativa/escalación |
| Tipo de FAIL | DOBLE: test falla porque el regex es incorrecto; el playbook no sigue la instrucción §610 completamente |
| Falso negativo | NO — el agente no se comporta correctamente (la pregunta de clarificación no es la respuesta esperada) |
| Falso positivo del check | SÍ (parcial) — si el regex fuera correcto, el check pasaría aunque el comportamiento sea incompleto |

---

## Soluciones ordenadas por impacto/esfuerzo

### S1 — Fix check regex (test) · ~5 min · RECOMENDADO INMEDIATO

**Archivo:** `qap/tc_1_0.yaml` línea 629  
**Cambio:**

```yaml
# ANTES
- disculp|entend|alternativ|equipo|persona|propong|reformul|tipo

# DESPUÉS
- disculp|entien|lament|sentim|alternativ|equipo|persona|propong|reformul|tipo
```

**Justificación:**
- `entien` captura `Entiendo`, `entiendes`, `entendemos` (formas conjugadas reales)
- `lament` captura `Lamento`, `lamentamos` (frecuente en LLMs hispanohablantes)
- `sentim` captura `sentimos`, `lo siento` (fallback de reconocimiento)
- Se conservan los demás patrones del check original

**Riesgo:** mínimo — amplía cobertura sin remover señales existentes.

### S2 — Fix instrucción playbook: prioridad frustración sobre slot-filling · ~20 min · RECOMENDADO

**Archivo:** `definitions/playbooks/compra.yaml` sección GESTION DE FRUSTRACION (§610)  
**Cambio:** añadir nota de prioridad explícita antes de la lista de disparadores:

```yaml
# Añadir después de "DISPARADORES:" en §610:
PRIORIDAD: la detección de frustración tiene PRECEDENCIA sobre cualquier
pregunta de clarificación de slot pendiente. Si hay señal emocional activa,
NO preguntes sobre slots — reconoce primero, ofrece alternativa o escala.
```

**Justificación:** el agente ejecutó simultáneamente reconocimiento emocional y pregunta de slot porque la instrucción no establece prioridad. La pregunta `¿Te refieres a la flor rosa o a algo en color rosa?` indica que el modelo resolvió primero la ambigüedad de producto, subordinando la respuesta emocional. Una instrucción explícita de prioridad elimina esta ambigüedad.

**Riesgo:** bajo — no afecta el flujo principal (sin frustración), solo añade claridad en el caso edge.

### S3 — Validación manual en CX · ~10 min · OPCIONAL post-fix

Ejecutar el TC manualmente en Default Environment con el fix S2 aplicado para verificar que:
1. El turno 2 genera respuesta sin pregunta de slot
2. La variable `$frustracion_detectada` se activa
3. El tono se ajusta a `solemne` según §260

---

## Fix recomendado

**Orden de ejecución:** S1 (regex, 5 min) → S2 (playbook, 20 min) → S3 (validación opcional).

S1 es suficiente para que el TC pase en el runner QA, pero S2 es necesario para que el comportamiento del agente sea correcto — sin S2, el TC pasaría con una respuesta que no cumple el espíritu de la instrucción §610.

---

*Análisis generado automáticamente por qa-tc-analyzer. Verificar S3 antes de cerrar.*
