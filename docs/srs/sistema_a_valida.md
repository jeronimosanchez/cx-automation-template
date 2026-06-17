# VALIDA — modo CX · Paso 3 del Sistema A

**Qué es:** confirma que el fix resuelve el fallo **sin romper nada más**. Es el árbitro empírico: una hipótesis de causa solo es verdadera si su fix hace pasar el test.

**Estado:** diseño conceptual ✅ · etapas 1-3 operativas · 4 parcial.

| # | Etapa | Qué hace | Coste | Ejecuta | Estado |
|---|---|---|---|---|---|
| **1** | **DEPLOY** | Merge del PR → `deploy.yml` despliega el fix a CX. Confirma que el deploy terminó sin error antes de testear | bajo | `deploy.yml` + `gh run view` | ✅ |
| **2** | **RE-EJECUCIÓN SELECTIVA** | Corre **solo los TCs del scope** (los que fallaban) contra el agente ya parcheado → ¿el FAIL se volvió PASS? | bajo | `petal_qa.py --test <TCs>` | ✅ |
| **3** | **ANTI-REGRESIÓN** | Corre la **suite completa** (3×) para cazar fallos nuevos que el fix haya introducido | medio | `petal_qa.py --runs 3` | ✅ |
| **4** | **VEREDICTO** | **RESUELTO** si scope-FAILs = 0 **y** nuevos-FAILs = 0. Si no → no resuelto, recorre el diferencial: sube a la siguiente hipótesis de DIAGNOSTICA | $0 | código (comparación pre/post) | 🟡 bucle por construir |

→ Lo **resuelto** se entrega al **Sistema B** (motor de aprendizaje, separado — *futuro*), que destilará el fix en receta reutilizable para el KB. Fuera del alcance de Sistema A.

**Es el árbitro, no un paso más:** DIAGNOSTICA propone causas, REPARA propone fixes, pero solo VALIDA **decide** qué era real — con el re-test. Por eso cada hipótesis lleva su condición de falsación.

**Dos redes de regresión:** comportamiento (etapa 3, suite completa) + diseño (la re-auditoría estática de REPARA). Nada se da por bueno sin ambas.

_Leyenda: ✅ operativo · 🟡 por construir, esfuerzo bajo · ❌ por construir._
