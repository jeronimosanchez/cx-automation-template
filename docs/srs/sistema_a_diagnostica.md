# DIAGNOSTICA — modo CX · Paso 1 del Sistema A

**Qué es:** convierte un conjunto de FAILs de QA en hipótesis de causa falsables, listas para REPARA. Ordenado por coste: código barato arriba, el modelo (lo caro) solo al final, sobre evidencia ya depurada.

**Estado:** diseño conceptual ✅ · etapas 0-1 operativas · 2-5 por construir.

| # | Etapa | Qué hace | Coste | Ejecuta | Estado |
|---|---|---|---|---|---|
| **0** | **EJECUTAR** | Lanza los TCs contra CX 3× y captura: respuesta del agente, trace (playbook, slots, tools+resultado) y resultado de las 3 repeticiones. Las 3× compran cobertura (cazan los TCs que pasan por suerte). Es el 2.º centro de coste real | 3N req | `petal_qa.py` | ✅ |
| **1** | **DETECTAR** | Compara cada respuesta con lo esperado y marca los fallos candidatos, por dos vías: diseño (estática) y comportamiento (FN/FP). Aquí vive la cobertura — si un fallo se escapa, se escapa aquí | bajo | `static_audit.py` + `check_turn()` | ✅ |
| **2** | **CONFIAR** | Comprueba que el fallo es real y bien juzgado antes de gastar nada: (a) varianza ≥2/3 · (b) coherencia veredicto↔trace (trace limpio + FAIL = artefacto → descarta) | $0 | código (lee etapa 0) | 🟡 (b) por construir |
| **3** | **LOCALIZAR** | Lee el trace y atribuye el fallo solo a lo que la evidencia señala (routing, slot, tool, diseño…), marcando cada punto con su confianza | $0 | código (reglas) | 🟡 por construir |
| **4** | **PRIORIZAR** | Agrupa los fallos por **firma de localización** (no por texto ni por causa), para arreglarlos de una vez y atacar primero los de más impacto | bajo | código (groupby) | ❌ gated por escala |
| **5** | **SINTETIZAR + HIPÓTESIS** | El modelo recibe solo lo implicado + su evidencia (no la conversación cruda) y formula un **diferencial ranqueado de 2-4 hipótesis** (granular + estructural), ordenadas por evidencia. Emite lo que converge sobre lo verificado; si no → humano | alto | GLM | ✅ manual · 🟡 skill |

**Marca de capa (etapa 3) = veredicto × confianza.** Veredicto: 🟢 ok · 🔴 problema · ⚪ N/A. Confianza: verificado (contra dato real) · con duda (inferido). Solo se marcan los puntos implicados (1-3). La convergencia (etapa 5) cuenta solo lo verificado; lo dudoso → humano.

**Contrato de salida (5 → REPARA):** un diferencial ranqueado; cada hipótesis = (claim · evidencia convergente · condición de falsación · mejora esperada). La falsación nombra un resultado observable de VALIDA ("TC-X pasa a PASS tras cambiar Y").

**Recorrido de prueba:** el ranking no es una lista, es un **plan de prueba ordenado**. REPARA/VALIDA lo caminan: prueban el fix de la #1; si pasa, cerrado; si falla, bajan a la #2. (El reordenado dinámico al fallar → futuro.)

**Principio de acotación:** etapas 0-4 = código, sin IA. El modelo (etapa 5) nunca ve el transcript ni el JSON crudo, solo lo implicado + su evidencia.

## Futuro programado (experimentar más adelante)
- **A favor y en contra** — argumentar también la evidencia que contradice cada hipótesis.
- **Checklist de cobertura** — lista fija de familias (routing/slot/tool/diseño/NLU) para no saltarse ninguna.
- **Diff pass-vs-fail** — en TCs inestables, comparar el run que pasó con el que falló para aislar la causa.
- **Ranking dinámico** — VALIDA reordena (un fix barato que falla promueve la estructural). Requiere el bucle.
- **Atribución por espectro** — sospecha estadística a escala.

_Leyenda: ✅ operativo · 🟡 por construir, esfuerzo bajo · ❌ por construir, gated por escala._
