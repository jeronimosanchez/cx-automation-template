# REPARA — modo CX · Paso 2 del Sistema A

Mismo patrón que DIAGNOSTICA, pero produce y prueba el **cambio**. Ordenado por coste.

**Entrada:** el diferencial ranqueado de DIAGNOSTICA (la hipótesis más probable primero).

**Estado:** diseño conceptual ✅ · etapas 4-5 operativas · 1-3 por construir (la criba local depende de ADK, aún sin validar).

| # | Etapa | Qué hace | Coste | Ejecuta | Estado |
|---|---|---|---|---|---|
| **1** | **GENERAR PARCHES** | Para la causa más probable, genera varios candidatos de fix diversos (multinivel). Dirección de `kb_ag`, implementación de `kb_plat_cx` | medio | GLM (`gen_plat_cx_hypothesis_fixer`) | ❌ |
| **2** | **CRIBAR ($0)** | Reconstruye el agente con cada parche en local (ADK) y lo prueba sobre: el **TC afectado** + **edge cases generados** parecidos + una **muestra de los buenos** (regresión). Puntúa (regex + juez) y rankea. Todo $0 | $0 | ADK + `check_turn` + `judge` | ❌ gated (ADK no validado) |
| **3** | **SELECCIONAR** | Elige el parche más barato-reversible que pasa la criba; confirma que no contradice decisiones del sistema | $0 | código + `kb_sys` | 🟡 |
| **4** | **APLICAR + AUDITAR** | Aplica el cambio al YAML y re-audita estática para no meter nuevos problemas de diseño | $0 | Write + `static_audit` | ✅ |
| **5** | **PR** | Commit + push + abre PR con la causa, el fix y los TCs esperados | $0 | git + gh | ✅ mecánico |

→ pasa a **VALIDA** (deploy + re-test + anti-regresión).

## Ejemplo (tulipanes)

Causa de entrada: *"Compra no llama a la tool de precio"*.

1. **GENERAR** — parche A [local]: añadir step "consulta la tool de precio". Parche B [estructural]: dividir Compra (es demasiado grande).
2. **CRIBAR ($0)** — ADK prueba A y B con el TC de precio + edge cases ("¿precio de las rosas?", "cuánto vale el ramo grande", etc.) + una muestra de regresión. A pasa todo y es barato; B también pero es caro. Rankea **A primero**.
3. **SELECCIONAR** — A (barato, reversible, pasa).
4. **APLICAR + AUDITAR** — edita el YAML de Compra; `static_audit` confirma que no rompe nada.
5. **PR** — abre *"fix TC-PRECIO: añade consulta de precio en Compra"*.
6. → **VALIDA** — deploy + re-test. Si A pasa → resuelto. Si A falla → vuelve, sube B (el estructural). *(Esto es el recorrido de prueba del diferencial.)*

## Hoy vs a escala

| | Hoy (Petal, ADK sin validar) | A escala (ADK funcionando) |
|---|---|---|
| Cuántos parches | 1-2, generados con LLM | muchos, diversos |
| Dónde se criban | sin criba local → CX (VALIDA) es el validador | ADK los criba todos $0; solo el finalista va a CX |
| Etapa 2 | se salta | activa |

Hoy, sin ADK, generas 1-2 parches y dejas que CX (VALIDA) decida — funciona, solo que no exploras el abanico. Cuando ADK funcione, la etapa 2 desbloquea probar muchos gratis.

## Notas de diseño

- **Forma de coste distinta a DIAGNOSTICA:** aquí la generación (GLM) va *primero* por necesidad — no puedes cribar lo que no has generado. El embudo sigue protegiendo lo caro: la criba ADK ($0) filtra antes del deploy a CX.
- **Criba generosa porque es gratis:** como ADK es $0, la criba no prueba solo el TC — prueba también **edge cases generados** parecidos al afectado (defensa contra *patch overfitting*: confirma que el fix **generaliza**, no que solo aprueba el caso exacto) y una **muestra de los buenos** (regresión barata). ADK filtra barato; **CX (VALIDA) sigue siendo el árbitro** de la regresión real sobre el agente.
- **Dos guardas de regresión:** la re-auditoría estática (etapa 4) caza regresiones de *diseño*; las de *comportamiento* las caza VALIDA.
- **Hoy se apuesta por el ranking de DIAGNOSTICA:** sin criba local, cada parche cuesta un deploy, así que la calidad del diferencial de entrada importa más.

## Futuro programado (experimentar más adelante)
- **Criba ADK ($0)** — la etapa 2 completa: probar parches en local con edge cases + muestra de regresión. Gated por ADK validado.
- **Generación diversa multi-agente** — generar parches con razonamiento adversarial / varios modelos (*guided diversity*), no uno solo.
- **Ranking dinámico de parches** — si el parche barato falla en VALIDA, promover el estructural.

_Leyenda: ✅ operativo · 🟡 por construir · ❌ por construir._
