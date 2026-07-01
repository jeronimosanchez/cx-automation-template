# TC-TONO-APLICACION-CORP-01 — Análisis de causa raíz

**Grupo:** TONO | **Tipo:** EDGE | **Estado:** FAIL (0/1)
**Fecha análisis:** 2026-07-01
**Rama analizada:** `qa/analyze-batch-20260701_170805`

---

## Resumen ejecutivo

El TC tiene **dos FAILs con causas distintas**:

- **Turn 1 FAIL** — Bug de test. La regla `not_expected: [mira,|genial|fenomenal|🌸]` se aplica globalmente al turno 1 aunque "Mira," es un conector explícitamente permitido para registro `estandar` en el playbook. El agente se comporta correctamente; el test penaliza un comportamiento válido.
- **Turn 3 FAIL** — Bug de playbook. El agente recibió "perfecto, ese mismo" con tres opciones idénticas en mesa (turno 1 = turno 2) y preguntó "¿A cuál te refieres?" en lugar de resolver la ambigüedad de forma inteligente — idealmente reduciendo opciones en turno 2 según el presupuesto. La pregunta de devolución es legítima *dado el estado conversacional previo*, pero ese estado previo es en sí un bug: el playbook no filtró por presupuesto en turno 2, lo que hace inevitablemente ambigua la selección en turno 3. La check de turno 3 espera checkout-language; el agente no llega a ese punto porque nunca hubo desambiguación real.

---

## 9 capas de causa raíz

### Capa 1 — Síntoma observable

| Turn | Status | Respuesta del agente | Check que falla |
|------|--------|----------------------|-----------------|
| 1 | FAIL | "Mira, para la recepción de tu empresa..." | `not_expected: [mira,]` |
| 2 | PASS | "Entendido, algo elegante..." — repropone las MISMAS 3 opciones | `elegante` presente ✅ |
| 3 | FAIL | "¿A cuál te refieres, por favor?" | espera `confirm\|pedido\|datos\|checkout\|registr\|direcc` |

### Capa 2 — Flujo de datos del runner

El runner (`test_qa_playbooks.py`, líneas 276-279) aplica `not_expected` a nivel TC **solo en el turno 1**:

```python
not_exp = list(turn.get("not_expected", []))
if i == 0:
    not_exp += test.get("not_expected", [])
```

La lista `not_expected: [mira,|genial|fenomenal|🌸]` está declarada **a nivel TC** (sin `turn_index`), por lo que se acumula exclusivamente en `i=0`. El turno 1 es el que produce el FAIL.

### Capa 3 — Regla del playbook sobre "Mira,"

`compra.yaml`, línea 251:
```
- estandar: natural, fresco. 'Mira,', 'genial', emoji 🌸 ocasional.
```

Y línea 218:
```
Usa conectores discursivos naturales segun $registro: estandar=[claro, vale, mira, entonces, bueno]
```

"Mira," está **explícitamente listado** como conector válido para registro `estandar`. El Orquestador inicia la sesión con `$registro` no especificado (la TC no inyecta `session_params`), por lo que Compra opera en modo `estandar` (el default). El agente usa un conector de estandar → comportamiento correcto.

### Capa 4 — Origen del not_expected en el test

La restricción `not_expected: [mira,|genial|fenomenal|🌸]` es válida para registro `solemne` y es la anti-regla documentada en el playbook (`compra.yaml`, línea 248: "solemne: sin exclamaciones, sin emoji 🌸, sin 'genial'/'perfecto!'"). Sin embargo, el TC se titula "Modo corporativo sostenido" y asume que corporativo implica registro solemne — esto **no está explicitado** en la TC ni en el playbook: "Corporativo" como `$ocasion_detectada` no mapea automáticamente a `$registro=solemne`. La TC presupone una regla de tono que el playbook no implementa.

### Capa 5 — Turn 2: fallo de filtrado por presupuesto

El usuario dice "algo elegante, presupuesto de 200 euros". El agente responde con las **mismas 3 opciones** del turno 1 (máximo 42 €). Dos problemas:

1. El playbook no instruyó filtrar por presupuesto en PASO 2 cuando el presupuesto ofrecido es mayor al precio máximo mostrado. En este caso particular los 3 productos caben bien dentro del presupuesto de 200 €, por lo que la lista no cambia — esto es técnicamente correcto desde inventario.
2. Pero al no cambiar la lista, el usuario recibe la misma oferta dos veces. Cuando dice "ese mismo" en turno 3, hay ambigüedad real (tres opciones).

### Capa 6 — Turn 3: ¿la pregunta del agente es un bug?

La pregunta "¿A cuál te refieres?" es **lógicamente correcta** dado el estado previo: hay tres opciones en mesa y "ese mismo" es ambiguo. El FAIL del check es consecuencia del estado previo (turno 2 sin convergencia), no de un error autónomo en turno 3. Dicho esto, hay una falla de experiencia: el playbook no instruye al agente a ayudar a resolver la ambigüedad (p.ej. "¿Al Centro de Mesa Orquídeas Blancas a 42€, al Centro de Rosas y Eucalipto a 26€ o a la Orquídea Phalaenopsis a 24€?") — en lugar de eso lanza una pregunta abierta que paraliza la compra.

### Capa 7 — Clasificación de los FAILs

| FAIL | Clasificación | Evidencia |
|------|---------------|-----------|
| Turn 1: "Mira," | **Bug de test** | "Mira," es conector estandar explícito en `compra.yaml` L218+L251; la TC asume registro solemne sin que ningún mecanismo lo active |
| Turn 3: sin checkout-language | **Bug de playbook** (secundario a bug de UX en T2) | El playbook no enseña a desambiguar con lista nombrada; la check es razonablemente calibrada — si el agente hubiera llegado al checkout el check habría pasado |

### Capa 8 — Riesgo de la solución errónea

- Si se elimina "Mira," del not_expected sin más: el TC pasa artificialmente pero la hipótesis original (corporativo = solemne) permanece sin resolver.
- Si se endurece el playbook para usar solemne con "Corporativo" sin validación de negocio: riesgo de sobre-formalizar contextos donde el tono estandar es apropiado.
- Si se corrige solo el turno 3 (desambiguación): el turno 1 seguirá fallando.

### Capa 9 — Dependencias sistémicas

El sistema de tono (Orquestador → `$registro` → Compra) fue migrado en `d582d66`. La lógica de cuándo `Corporativo` activa `solemne` debería vivir en el Orquestador, no en Compra. Esta TC está probando una política de tono que el Orquestador debería inyectar antes de que Compra reciba la sesión.

---

## Dimensionamiento

| Dimensión | Evaluación |
|-----------|------------|
| Impacto en usuario real | Medio — usuario corporativo recibe tono coloquial ("Mira,") que puede percibir como poco profesional |
| Complejidad del fix | Baja (turno 1 = fix de test) / Media (turno 3 = fix de playbook) |
| Riesgo de regresión | Bajo si se separan los dos fixes |
| TCs potencialmente afectados | Todos los TCs de grupo TONO con ocasion Corporativo que no inyecten `$registro` explícito |

---

## Soluciones ordenadas por score

### Solución A — Fix de test: corregir not_expected al turno correcto ⭐ Score: 9/10

**Qué:** Mover `not_expected` al turno que sí espera registro solemne (turno 3, cuando el agente ya debería haber cerrado la venta), o bien eliminar "mira," del not_expected global si la TC no inyecta `$registro=solemne`.

**Archivo:** `qap/tc_1_0.yaml`, TC-TONO-APLICACION-CORP-01

**Cambio concreto:**
```yaml
# Opción A1 (recomendada): inyectar $registro=solemne vía session_params + mantener not_expected
- id: TC-TONO-APLICACION-CORP-01
  turns:
  - user: necesito un arreglo floral para la recepcion de mi empresa
    session_params:
      registro: solemne        # ← activa el modo que el test quiere validar
    checks:
    - arreglo|flores|empresa|opcion|recepcion|elegante|corporativ
  ...
  not_expected:
  - mira,|genial|fenomenal|🌸

# Opción A2 (alternativa más simple): eliminar "mira," del not_expected
  not_expected:
  - genial|fenomenal|🌸        # mira, es válido en estandar
```

**Por qué es el mejor fix:** resuelve el FAIL sin tocar el playbook; la opción A1 hace la TC semánticamente correcta (valida lo que dice validar).

**Tiempo estimado:** 5 min.

---

### Solución B — Fix de playbook: desambiguación activa en turno 3 ⭐ Score: 7/10

**Qué:** Añadir instrucción en PASO 2 de `compra.yaml` para que cuando el usuario diga "ese mismo" / "el primero" / "la última" con múltiples opciones en mesa, el agente liste las opciones por nombre en la pregunta de desambiguación en lugar de devolver una pregunta abierta.

**Archivo:** `definitions/playbooks/compra.yaml`

**Sección afectada:** PASO 2, bloque de APERTURA / manejo de referencia ambigua.

**Instrucción a añadir (tras la regla de APERTURA):**
```
Si el usuario usa referencia deíctica ambigua ('ese mismo', 'el primero', 'la última', 'esa') 
y hay 2+ opciones en mesa: NO preguntar '¿A cuál te refieres?' abierto. 
DESAMBIGUAR con lista nombrada: '¿Te refieres al [opcion_1], al [opcion_2] o al [opcion_3]?'
```

**Tiempo estimado:** 15 min (redacción + deploy).

**Nota:** este fix no resuelve el FAIL del turno 1. Debe combinarse con Solución A.

---

### Solución C — Fix sistémico: mapear Corporativo → solemne en Orquestador ⭐ Score: 6/10

**Qué:** Definir en el Orquestador que `$ocasion_detectada=Corporativo` activa `$registro=solemne` antes de transferir a Compra.

**Por qué no es el fix inmediato:** requiere entender si corporativo siempre debe ser solemne (puede que no — una empresa pequeña puede preferir trato casual). Es una decisión de diseño conversacional que excede este TC.

**Recomendación:** abrir issue de diseño antes de implementar. No aplicar en este ciclo.

**Tiempo estimado:** 30 min + gate de decisión.

---

## Plan de acción recomendado

1. **Aplicar Solución A1** (5 min): inyectar `session_params: {registro: solemne}` en turno 1 del TC para que el test valide lo que su nombre promete.
2. **Aplicar Solución B** (15 min): añadir instrucción de desambiguación nombrada en PASO 2 de compra.yaml.
3. **Abrir nota de diseño** (5 min): documentar la pregunta "¿Corporativo siempre implica solemne?" como pendiente de decisión de diseño conversacional.

**Tiempo total:** ~25 min + deploy CI/CD.

---

## Referencias

- `definitions/playbooks/compra.yaml` L218, L248-251 — reglas de conector por registro
- `qap/tc_1_0.yaml` L776-792 — definición del TC
- `qap/test_qa_playbooks.py` L276-279 — lógica de aplicación de `not_expected` (solo turno 1)
- Commit `d582d66` — migración sistema de tono 1.0→1.1 en Compra y Checkout
