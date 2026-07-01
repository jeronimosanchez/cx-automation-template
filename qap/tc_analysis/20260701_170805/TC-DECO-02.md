# Análisis TC-DECO-02

**Fecha:** 2026-07-01
**Batch:** 20260701_170805
**Estado:** FAIL (0/1 runs)
**Tipo:** EDGE · Grupo: COMPRA-INV

---

## Resumen ejecutivo

**Diagnóstico:** Doble causa — Bug Playbook (formato `--` no seguido) + Test mal calibrado (regex no acepta símbolo `€`). El agente usa formato libre `(15 flores, 37€)` en lugar del formato canónico `-- M (15 flores, 37euros)` exigido en `compra.yaml`. El check del TC falla en ambas rutas: la rama `Rosa.{0,40}--` falla porque el agente omite el `--`, y la rama de escape `Rosa.{0,80}euros` falla porque el agente usa `€` en lugar de `euros`. Ambos problemas son independientes y deben corregirse por separado.

**Causa raíz primaria:** La instrucción `FORMATO AL USUARIO` en `compra.yaml` no se está respetando en el turno observado. La respuesta del agente muestra los productos sin el separador `--` y sin la talla explícita, y usa el símbolo `€` en lugar de `euros` como indica el playbook.

**cx_truth:** PASS (el TC tiene criterio de calidad válido — las rosas deben existir en catálogo y mostrarse con formato canónico).

---

## Respuesta observada vs esperada

**Input:** `quiero un ramo de rosas para decorar mi salon`

**Respuesta del agente:**
```
Claro, para decorar tu salón con rosas tenemos estas opciones de ramos, todos en tamaño M:

* Ramo de Rosas Morado (15 flores, 37€)
* Ramo de Rosas Amarillo (12 flores, 25€)
* Ramo de Rosas Blanco (12 flores, 25€)

¿Cuál te gusta más?
```

**Formato que exige el playbook (`compra.yaml` sección TOOLS):**
```
[Producto] [Color] -- [Tamaño] ([Descripcion_Cantidad], [Precio]euros)
Ej: Orquídea Phalaenopsis Blanca -- M (1 planta, 24euros)
```

**Formato que produciría PASS en el check:**
```
Ramo de Rosas Morado -- M (15 flores, 37euros)
```

---

## 9 Capas de análisis

### Capa 1 — Síntoma observable
El check regex `Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,40}—.{0,5}[SMLX]|Rosa.{0,40}–.{0,5}[SMLX]|Rosa.{0,80}euros` falla contra la respuesta real. La respuesta contiene "Rosas" pero no contiene `--` (ni `—` ni `–`) ni la palabra `euros` escrita — solo el símbolo `€`.

### Capa 2 — Qué parte del check falla y por qué

El regex tiene dos ramas de escape:

| Rama | Patrón | ¿Pasa? | Motivo |
|------|---------|--------|--------|
| Principal | `Rosa.{0,40}--.{0,5}[SMLX]` | NO | Agente usa `(15 flores, 37€)`, sin `--` ni letra de talla separada |
| Escape símbolo | `Rosa.{0,40}—.{0,5}[SMLX]` | NO | Agente no usa `—` |
| Escape guion en | `Rosa.{0,40}–.{0,5}[SMLX]` | NO | Agente no usa `–` |
| Escape precio | `Rosa.{0,80}euros` | NO | Agente usa símbolo `€`, no la palabra `euros` |

**Conclusión:** ninguna rama del regex pasa. El fallo es real: la respuesta no cumple el formato canónico del playbook.

### Capa 3 — Bug playbook: formato no seguido

`compra.yaml` sección `# TOOLS` (línea 672) establece explícitamente:

> `FORMATO AL USUARIO: '[Producto] [Color] -- [Tamano] ([Descripcion_Cantidad], [Precio]euros)'. Precio: entero sin decimales (37euros, no 37.0euros).`

La respuesta del agente viola esta instrucción en dos dimensiones:
1. **Omite `--` y la talla como campo separado:** usa `(15 flores, 37€)` en lugar de `-- M (15 flores, 37euros)`.
2. **Usa símbolo `€` en lugar de la palabra `euros`:** el playbook es explícito: `37euros`, no `37€`.

La instrucción `FORMATO AL USUARIO` fue añadida en el commit `aa05036` (`refactor(compra): convierte prohibiciones en reglas positivas (parcial)`). El agente en CX probablemente todavía no tiene desplegada esta versión del playbook, o la instrucción no tiene suficiente peso para imponerse sobre el formato natural del LLM.

### Capa 4 — Bug test: rama de escape `euros` no cubre símbolo `€`

El TC incluye una rama de escape `Rosa.{0,80}euros` diseñada para pasar si el agente, aunque omita el `--`, al menos muestra el precio con la palabra `euros`. Esta rama **no cubre** el caso en que el agente usa el símbolo `€`. Si el agente hubiera respondido `37euros` pero sin `--`, la rama de escape habría pasado.

Este es un gap de calibración real: el regex debería incluir `Rosa.{0,80}[0-9]+euros|Rosa.{0,80}[0-9]+€` para ser robusto frente a ambas representaciones de precio.

Sin embargo, el bug principal sigue siendo el playbook (formato `--` no seguido). La rama de escape es un mecanismo de tolerancia para variaciones menores, no el criterio de calidad principal.

### Capa 5 — Params de la llamada y comportamiento del tool

Los params del turno muestran:
- `grupo_intent: G5` → modo compra directa
- `ocasion_detectada: Decoracion`
- `producto: rosas`

La instrucción `CRITICO v40 (TC-DECO-01/02)` en el playbook (línea 357) establece que cuando `$ocasion_detectada='Decoracion'` y el usuario menciona flor explícita, se debe pasar `producto=<flor>+categoria='Decoracion'` al tool. La respuesta muestra rosas reales del catálogo (Morado, Amarillo, Blanco), lo que indica que el tool devolvió resultados correctos. El problema es exclusivamente de **formato de presentación**, no de routing ni de llamada al inventario.

### Capa 6 — Timing del bug vs commit

La instrucción `FORMATO AL USUARIO` con el separador `--` fue añadida en `aa05036`. Si este commit no ha sido desplegado a CX en el momento del run QA, el agente seguía usando el formato libre pre-commit. Esto explicaría la respuesta observada. El run QA usa el Default Environment de CX, que recibe el playbook tras `git push → deploy.yml`. Si el run QA se ejecutó antes del deploy de `aa05036`, el FAIL es esperado y el fix está en espera de deploy.

Si el run se ejecutó **después** del deploy, el bug es que la instrucción de formato no tiene suficiente adherencia en el LLM de CX (problema de peso de la instrucción).

### Capa 7 — Impacto funcional

El agente devuelve productos correctos (rosas reales del catálogo, talla M implícita en el texto de cabecera). El usuario recibe información útil. El problema es de **formato de catálogo**, no de correctitud de datos ni de flujo. Impacto de negocio: bajo (el usuario puede continuar la compra). Impacto de calidad: medio (inconsistencia con el estándar de formato definido).

### Capa 8 — Anti-regresión

La corrección del playbook no debe romper:
- TC-DECO-01 (mismo patrón con margaritas) — comparte regex y depende del mismo `FORMATO AL USUARIO`
- TCs del grupo G5 que validan formato de catálogo en respuestas de compra
- El `not_expected` de TC-DECO-02: `no tengo.{0,40}rosa` y `no tenemos.{0,40}rosa` — la corrección de formato no afecta a estos checks negativos

### Capa 9 — Causa raíz consolidada

**Dos causas independientes, prioridad distinta:**

1. **Bug Playbook (primario):** la instrucción `FORMATO AL USUARIO` con `-- [Tamaño]` y `[Precio]euros` no se aplica en la respuesta. Puede ser por: (a) deploy pendiente, o (b) instrucción con peso insuficiente en el LLM. Fix: verificar que `aa05036` está desplegado; si sí, reforzar la instrucción de formato en el playbook.

2. **Bug Test (secundario, menor):** la rama de escape `Rosa.{0,80}euros` no cubre el símbolo `€`. Si el agente usa `€` (comportamiento natural del LLM), la rama de escape no activa. Fix: ampliar la rama a `Rosa.{0,80}(?:euros|€)`.

---

## Dimensionamiento

| Solución | Tipo | Archivo | Impacto | Riesgo | Tiempo |
|----------|------|---------|---------|--------|--------|
| S1: Verificar deploy `aa05036` + reforzar instrucción formato | Bug Playbook | `compra.yaml` | Alto | Bajo | ~15 min |
| S2: Ampliar regex rama de escape para cubrir `€` | Bug Test | `tc_1_0.yaml` | Medio | Muy bajo | ~5 min |

---

## Soluciones (ordenadas por prioridad DESC)

### S1 — Reforzar instrucción FORMATO AL USUARIO en compra.yaml (Bug Playbook)

**Prioridad:** 1 — cierra el bug de fondo.

**Razonamiento:** La instrucción existe pero el agente no la sigue. Dos vectores de refuerzo:
1. Mover `FORMATO AL USUARIO` más arriba en la sección `# TOOLS`, inmediatamente antes de la regla `CRITICO - INVENTARIO`.
2. Añadir ejemplo explícito con rosas en formato canónico (la regla `CRITICO v39` del mismo playbook demuestra que los ejemplos tienen mayor adherencia que las instrucciones abstractas).

**Cambio propuesto en `compra.yaml` sección `# TOOLS`:**

Antes de `⛔ REGLA CRITICA - INVENTARIO ⛔`, añadir bloque de formato con ejemplo de rosas:

```
⛔ FORMATO OBLIGATORIO DE CATÁLOGO ⛔
SIEMPRE presenta cada producto en este formato exacto:
'[Producto] [Color] -- [Tamaño] ([Descripcion_Cantidad], [Precio]euros)'
Precio: entero sin decimales, escrito como 'euros' (37euros, NO 37€, NO 37.0euros).
Color OBLIGATORIO. Tamaño OBLIGATORIO como letra S/M/L/X después del '--'.
Ejemplo correcto: 'Ramo de Rosas Morado -- M (15 flores, 37euros)'
Ejemplo incorrecto: 'Ramo de Rosas Morado (15 flores, 37€)' ← falta '--', falta talla, precio con símbolo
⛔ FIN FORMATO OBLIGATORIO ⛔
```

**Archivos afectados:** `definitions/playbooks/compra.yaml`
**Dependencias:** verificar que el check de TC-DECO-01 y TC-DECO-02 sigue pasando tras el deploy.

### S2 — Ampliar regex en tc_1_0.yaml para cubrir símbolo `€` (Bug Test)

**Prioridad:** 2 — calibración del test, independiente del fix del playbook.

**Razonamiento:** La rama de escape `Rosa.{0,80}euros` es demasiado estricta. El LLM puede usar `€` de forma natural incluso con la instrucción vigente (es un comportamiento difícil de suprimir 100%). La rama de escape debe tolerar ambas representaciones.

**Cambio propuesto en `tc_1_0.yaml` línea 441:**

```yaml
# Antes:
- Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,40}—.{0,5}[SMLX]|Rosa.{0,40}–.{0,5}[SMLX]|Rosa.{0,80}euros

# Después:
- Rosa.{0,40}--.{0,5}[SMLX]|Rosa.{0,40}—.{0,5}[SMLX]|Rosa.{0,40}–.{0,5}[SMLX]|Rosa.{0,80}(?:euros|€)
```

**Archivos afectados:** `qap/tc_1_0.yaml`
**Nota:** Este fix solo debe aplicarse si el agente, tras el deploy de S1, sigue usando `€` en algunos casos. Si S1 hace que el agente use `euros` de forma consistente, S2 es opcional pero sigue siendo buena calibración defensiva.

**Consideración:** TC-DECO-01 tiene el mismo patrón. Evaluar si aplica el mismo fix a esa rama de escape también (`Margarita.{0,80}euros` → `Margarita.{0,80}(?:euros|€)`).

---

## Recomendación

1. **Verificar deploy de `aa05036`:** comprobar si el playbook desplegado en CX ya incluye la instrucción `FORMATO AL USUARIO`. Si no, el FAIL es esperado y se resuelve solo con el deploy.
   ```bash
   gh run list --workflow=deploy.yml --limit=5
   ```

2. **Si el deploy ya está activo y el agente sigue sin respetar el formato:** aplicar S1 (refuerzo de instrucción con ejemplo explícito de rosas). Branch → PR → deploy → rerun QA.

3. **En paralelo o tras confirmar S1:** aplicar S2 (ampliar regex) en la misma rama o en branch separado según criterio de Jero.

4. **Anti-regresión post-fix:** verificar que TC-DECO-01 sigue en PASS y que los TCs del grupo G5 que muestran catálogo no regresionan.

---

## Metadata

| Campo | Valor |
|-------|-------|
| `playbook` | unknown (CX no reportó el playbook activo en este turno) |
| `grupo_intent` | G5 |
| `ocasion_detectada` | Decoracion |
| `cx_truth` | PASS |
| `Sheet` | No disponible (unauthorized) — datos de negocio marcados 🟡 [supuesta] |
| Commit relevante | `aa05036` (añade `FORMATO AL USUARIO` en `compra.yaml`) |
| TCs relacionados | TC-DECO-01 (mismo patrón, misma regex, misma instrucción) |
