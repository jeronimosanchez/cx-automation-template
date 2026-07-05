# Estado de la lógica compensatoria — compra.yaml + petal_cx_orchestrator.yaml

> Auditoría de diseño conversacional. Solo lectura. No se modificó ningún artefacto.
>
> **Qué es "lógica compensatoria":** reglas en la instrucción del playbook que parchean un hueco de la capa de datos (en vez de arreglar el dato). Patrones: listas hardcodeadas que deberían venir del tool/facets · mapas concepto→campo que el LLM debe recordar · proyección mental (descartar campos ruido del backend) · estado en el prompt (backend stateless) · reglas nacidas de un TC concreto (cicatriz de bug de datos).
>
> **Baseline:** `docs/diagnostico_reglas_seleccion_compra.md` (C1–C5). Contexto de datos verificado allí: el backend filtra por color/precio/ocasion/tamano/categoria/tipo/producto(fuzzy)/productos_excluidos; **NO** filtra por `flor` (columna `Flor` vacía) — pero **SÍ** existe ya un filtro `especie` (filtro exacto por especie botánica); NO proyecta (devuelve 16 columnas); es stateless.
>
> **Cambio clave desde el baseline:** el refactor de `producto`(fuzzy) → `especie` está **HECHO**. TT-28 y la desambiguación ROSAS ahora emiten `especie=<flor>`, no `producto`. Esto degrada C1 de "COMPENSATORIA pura" a "A MEDIAS": la vía de filtrado ya es un param dedicado (`especie`), pero la **lista de vocabulario FLORES sigue hardcodeada en el prompt** porque no hay endpoint de facets que la provea.

---

## Playbook 1 — `compra.yaml`

| Pieza compensatoria | Playbook | Bloque/línea | Estado | Arreglo de datos que la elimina |
|---|---|---|---|---|
| Lista hardcodeada FLORES (~28 especies) | compra.yaml | L260 | **SIGUE** | Endpoint de facets (`GET /facets` → especies válidas). El param `especie` ya existe; falta el vocabulario servido. |
| Definición ESPECIE (v42) apoyada en "una de FLORES" | compra.yaml | L261 | **A MEDIAS** | El filtro `especie` ya existe (mitad hecha). La lista de referencia sigue en prompt → facets la elimina. |
| Desambiguación ROSAS especie-vs-color (6 reglas + ejemplos) | compra.yaml | L263-277 | **A MEDIAS** | El acoplamiento al fuzzy `producto` **ya se eliminó** (ahora emite `especie=Rosas`). Queda la NLU flor/color pura (legítima, ambigüedad del español) + la dependencia de la lista FLORES (facets). ~⅓ es NLU irreducible; ~⅔ es cicatriz de datos. |
| TT-28 "si mencionó flor de FLORES, SIEMPRE `especie=<flor>`" | compra.yaml | L305 | **A MEDIAS** | El rodeo "forzar `producto` fuzzy" **ya no existe** (usa `especie`). Pero la regla sigue anclada a la lista FLORES y a un TC (TT-28). Facets + `especie` poblado la vuelven innecesaria. |
| Lista hardcodeada COLORES (14 valores) | compra.yaml | L259 | **SIGUE** | Endpoint de facets (colores válidos). |
| Mapeo Decoración → `categoria` (v40, TC-DECO-01/02) | compra.yaml | (ausente) | **ELIMINADA** | Ya no está en compra.yaml. `categoria` sobrevive solo como nombre de filtro pasivo en la lista de HERRAMIENTAS (L613), sin mandato "recuerda que Decoracion va en categoria". La cicatriz TC-DECO se resolvió aquí (parcialmente migró al Orquestador, ver P2). |
| R2 Persistencia de filtros (`filtros_activos`) | compra.yaml | L580-583 | **SIGUE** | Estado de búsqueda server-side (sesión/carrito con ID). Compensatoria arquitectónica — no se arregla con columna ni facets. Baja prioridad. |
| REGLA PLACEHOLDER [otros tipos disponibles] (no inventar tipos) | compra.yaml | L536-543 | **SIGUE** | Endpoint de facets (tipos válidos por ocasión). Reduce la ansiedad anti-alucinación. |
| Formato al usuario + omitir Stock + concordancia género (proyección mental) | compra.yaml | L614 | **SIGUE** | Proyección server-side (devolver ~6 columnas en vez de 16). El LLM descarta Ventas_Anuales, Descripcion_Corta, Flor(vacío), Tipo_Flor, Entrega_Mismo_Dia en cada turno. Ahorro en tokens de *response*. |
| R4 Presupuesto duro ("nunca por encima de `precio_max`") | compra.yaml | L587 | **SIGUE** (redundante) | Ninguno — ya es redundante hoy. El backend aplica `precio_max` en el WHERE. Limpieza directa sin depender de datos. |
| "Completar hasta 3 con MISMA OCASION+COLOR" | compra.yaml | L358 (nota) | **SIGUE** (redundante) | Ninguno — redundante hoy. Subir `limit` o leer fallback en vez de re-filtrar en prompt. |

### Notas sobre C1–C5 del baseline (compra.yaml)

- **C1** (FLORES + ROSAS + TT-28) → **A MEDIAS**. Confirmado lo esperado: `fuzzy→especie` **hecho**; la lista FLORES **sigue**. La inteligencia de filtrado migró a un param dedicado; el vocabulario no.
- **C2** (Decoración→categoria) → **ELIMINADA** en compra.yaml. Confirmado lo esperado. (Ojo: reaparece parcialmente en el Orquestador como decorar/hogar/casa/jardin→Decoracion, ver P2.)
- **C3** (persistencia filtros) → **SIGUE**, sin tocar. Correcto.
- **C4** (proyección/supresión de ruido) → **SIGUE**, sin tocar (es backend). Correcto.
- **C5** (COLORES + anti-placeholder) → **SIGUE**, sin tocar. Correcto.

---

## Playbook 2 — `petal_cx_orchestrator.yaml` (el clasificador/router)

El Orquestador NO estaba cubierto por el diagnóstico C1–C5. Tiene su **propia** carga compensatoria, y es densa: al ser el router, todo el vocabulario que decide "a qué grupo va esto" está hardcodeado en el prompt, y varias reglas son cicatrices literales de TCs.

| Pieza compensatoria | Playbook | Bloque/línea | Estado | Arreglo de datos que la elimina |
|---|---|---|---|---|
| Lista FLORES anti-saludo (FIX v63): "si contiene rosas/tulipanes/… no es saludo" | orchestrator | L252 | **SIGUE** | Facets de especies + un clasificador NLU/intent que no dependa de enumerar el catálogo en el prompt. Es la misma taxonomía de C1, duplicada aquí. |
| Lista de palabras de producto (ramo/flores/planta/bouquet/centro/corona/orquidea…) | orchestrator | L252 | **SIGUE** | Facets de tipos de producto. Vocabulario controlado que hoy vive en el prompt. |
| Lista FLORES anti-G3-falso-positivo (FIX TC-DECO-02, v66): 20 especies + tipos | orchestrator | L272 | **SIGUE** | Facets (especies + tipos). Cicatriz doble: nace de TC-DECO-02 y reencarna la lista FLORES una **tercera** vez. |
| Mapeo OCASION: funeral/boda/cumpleanos/… → Funeral/Boda/Regalo/… | orchestrator | L213-222 | **SIGUE** | Mapa concepto→ocasión canónica. Debería venir de un recurso de negocio (tabla de ocasiones/sinónimos) o de un clasificador entrenado, no del prompt. |
| Mapeo RECEPTOR: madre/pareja/jefe/bebe → ocasión inferida | orchestrator | L223-230 | **SIGUE** | Mapa concepto→ocasión. Mismo hueco que OCASION: reglas de negocio hardcodeadas en el prompt. |
| Mapeo decorar/hogar/casa/jardin → Decoracion | orchestrator | L220, L284 | **SIGUE** | Es el **residuo migrado de C2**: la unificación ocasión/categoría que salió de compra.yaml reaparece aquí como enrutado. Un param semántico `uso` unificado en el backend lo cerraría. |
| Mapeo PRECIO_MAX: "barato"→20, "precio medio"→50, "caro"→vacío | orchestrator | L232-237 | **A MEDIAS** | Extraer el número del utterance es NLU legítima. Pero los umbrales fijos (20/50) son una política de negocio hardcodeada; deberían venir de config, no del prompt. |
| REGLA $producto EXACTO vs GENERICO (FIX 1.3-A): tamaño → prellena producto | orchestrator | L239-246, L319 | **A MEDIAS** | Mitad NLU (detectar tamaño), mitad cicatriz de bug (FIX 1.3-A) para no romper el hand-off a Compra. El acoplamiento nombre-exacto-con-tamaño es frágil; un contrato de params más limpio entre Orquestador↔Compra lo reduce. |
| ZG-1..ZG-5 (micro-reglas de desempate por grupo, atadas a casos) | orchestrator | L264, L266, L269, L303 | **SIGUE** | Cicatrices de disambiguación de intent. Un clasificador de intent con confianza las absorbe; hoy son parches en el prompt. |
| Precedencia de tono + tabla DETECCIÓN (duelo/frustración/prisa/ocasión) | orchestrator | L186-207 | **SIGUE** (legítima-compensatoria) | Listas de disparadores léxicos de tono. Es detección de señal legítima, pero el vocabulario (todas las variantes de "funeral", "inaceptable"…) está hardcodeado; un servicio de clasificación de emoción/registro lo externalizaría. Baja prioridad — funciona y es barato. |

### Lectura del Orquestador

El router concentra **tres copias** de la taxonomía de FLORES (L252 anti-saludo, L272 anti-G3, más la de compra.yaml L260) y **dos mapas concepto→ocasión** (OCASION L213-222 + RECEPTOR L223-230). Todo lo que el router necesita para decidir "esto es producto / esto es una ocasión / esto va a G3 vs G5" está enumerado a mano en el prompt porque no hay:
1. un **endpoint de facets** que sirva especies/tipos/colores/ocasiones válidos, y
2. un **clasificador de intent** que devuelva grupo + confianza sin que el LLM tenga que llevar el diccionario encima.

Las reglas más frágiles son las atadas a un TC literal: **FIX v63** (anti-saludo), **FIX TC-DECO-02 / v66** (anti-G3-falso-positivo), **FIX 1.3-A** (producto exacto). Cada una es la cicatriz de un bug de datos/enrutado que se manifestó como fallo y se parcheó en el prompt.

---

## Resumen

### Cuánta compensatoria queda

**compra.yaml:** de las 5 piezas del baseline C1–C5:
- **1 ELIMINADA** (C2, Decoración→categoria).
- **1 A MEDIAS** (C1 / familia `especie`: filtrado migrado a param dedicado, vocabulario FLORES aún en prompt).
- **3 SIGUEN** intactas (C3 estado, C4 proyección, C5 colores+placeholder), + 2 redundantes menores (R4, "completar hasta 3").

**orchestrator:** ~10 piezas, **casi todas SIGUEN**. Es el mayor foco de compensatoria del par y **no se había tocado**: triple copia de FLORES, dos mapas de ocasión, residuo migrado de C2, y 3 reglas atadas a TCs.

### % aproximado eliminado

Contando el conjunto de ambos playbooks (~15 piezas compensatorias identificadas):

- **Eliminado por completo:** ~1 pieza (C2 en compra.yaml) → **~7%**.
- **Reducido a medias:** ~4 piezas (C1/especie + TT-28 + ESPECIE-def + fragmentos NLU de ROSAS) → progreso parcial, quizá **~15-20% de reducción efectiva** sobre esas piezas.
- **Estimación global:** se ha eliminado/reducido en torno al **~15-20%** de la masa compensatoria total del par. El grueso sigue en pie, y el Orquestador — que concentra la mayor densidad — está prácticamente sin tocar.

En tokens (extrapolando el baseline, que cifraba ~950-1.050 tk recuperables solo en compra.yaml): el refactor `especie` ha recuperado poco de *prompt* (el filtrado cambió de vía, no se borró texto — la lista FLORES sigue). El ahorro real hasta ahora es sobre todo de **corrección/robustez** (filtro exacto por especie), no de tokens.

### Prioridad de lo que queda (qué atacar primero)

1. **Endpoint de facets (`GET /facets` → especies, tipos, colores, ocasiones válidas).** Máximo apalancamiento: elimina de un golpe **las tres copias de FLORES** (compra L260 + orchestrator L252 + L272), la lista COLORES (compra L259), buena parte de PLACEHOLDER (compra L536) y alimenta el `especie` ya existente. Ataca a la vez ambos playbooks. **Primero esto.**
2. **Poblar la columna `Flor` / especie en el sheet.** Complemento obligado del punto 1: el param `especie` ya existe pero el dato de origen (`Flor`) está vacío. Sin dato, el filtro exacto no muerde. Va emparejado con facets.
3. **Limpieza redundante sin dependencia de datos (hoy mismo):** R4 presupuesto duro (compra L587) y "completar hasta 3" (compra L358). Cero riesgo, cero espera de backend. Quick win.
4. **Param semántico `uso`/`contexto` unificado (Ocasion + Categoria_Uso).** Cierra el residuo migrado de C2 en el Orquestador (decorar→Decoracion, L220/L284) y la clase de bugs TC-DECO. Externaliza también los mapas OCASION/RECEPTOR si se acompaña de tabla de sinónimos.
5. **Proyección server-side (16→~6 columnas).** No libera prompt pero recorta el payload de cada tool call (se repite muchas veces por conversación). Mayor ahorro de tokens *reales*.
6. **Estado de búsqueda server-side (sesión).** Elimina R2 (compra L580-583). Arquitectónico, baja prioridad.
7. **Clasificador de intent con confianza.** Absorbería ZG-1..5 y las cicatrices FIX v63 / TC-DECO-02 / FIX 1.3-A del Orquestador. Mayor esfuerzo; abordar tras facets.

### Conclusión de una línea

El refactor tocó la **vía de filtrado** de compra.yaml (`producto`→`especie`, hecho) y borró un mapa concepto→campo (C2). Pero la **masa compensatoria** — el vocabulario hardcodeado — sigue casi entera, y está **triplicada en el Orquestador**, que no se auditó ni se tocó. El siguiente movimiento de mayor impacto no es tocar más prompt, sino construir el **endpoint de facets**: es el arreglo de datos que colapsa simultáneamente las listas de los dos playbooks.
