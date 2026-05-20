---
status: FAIL
tipo: Bug Playbook
estimacion: ~15 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"quiero un ramo de rosas para decorar mi salon"* | — |
| 2 | Orquestador | clasifica como G5, extrae `producto=ramo de rosas`, `ocasion_detectada=Decoracion` | ✅ extracción correcta |
| 3 | Compra | llama tool catálogo filtrando por `ocasion=Decoracion` sin priorizar/validar el slot `producto=rosas` | 🔴 ignora el slot `producto` explícito |
| 4 | Catálogo (petal-sheet-api) | devuelve productos de Decoración: Tulipanes Mix, Hortensias blancas y azules (cero rosas tagueadas como Decoración) | ⚠️ gap de datos, pero el playbook debería detectar el mismatch |
| 5 | Compra | presenta alternativas sin reconocer que el usuario pidió rosas explícitamente ni intentar buscar rosas en otras ocasiones | 🔴 sin fallback escalonado ni copy honesto |
| 6 | Agente | *"Mira, para decorar tu salón tengo estas opciones... Tulipanes, Hortensias..."* | 🔴 oferta opaca: no menciona que no hay rosas |
| 7 | Test (check) | regex `Rosa.{0,40}--.{0,5}[SMLX]\|Rosa.{0,80}euros` | 🔴 FAIL — el agente nunca menciona "Rosa" en la respuesta |

### Causa raíz (descompuesta en 3 capas)

1. **Capa 1 (Catálogo / datos)**: `petal-sheet-api` no tiene ningún producto de tipo "Rosa" tagueado con `ocasion=Decoracion`. El backend devuelve 0 rosas para ese filtro, aunque sí existen rosas para otras ocasiones (Aniversario, Cumpleaños) — validado por otros TCs PASS.
2. **Capa 2 (Playbook Compra)**: cuando el filtro `(producto+ocasion)` devuelve resultados pero ninguno coincide con el `producto` explícito del usuario, el playbook no hace un segundo intento (relajando `ocasion` o buscando rosas en otras categorías) ni reconoce el mismatch en la respuesta. Trata los resultados parciales como válidos.
3. **Capa 3 (UX conversacional)**: el agente no es transparente. En lugar de decir *"no tengo rosas específicas para decoración, pero estas rosas también quedan muy bien en un salón"*, muestra alternativas sin contexto. Rompe el contrato implícito con el usuario (pidió rosas, recibe tulipanes sin explicación).

## Recomendación

### Solución recomendada: #1 — Fallback escalonado en Playbook Compra (producto > ocasion)

🟢 **9/10** · ~15 min · Sin dependencias externas

**Por qué**: ataca la causa raíz en la capa controlable (el playbook) sin tocar catálogo ni test. Cambia la lógica para priorizar el slot `producto` cuando es explícito: si `(producto+ocasion)` no devuelve match, hacer un segundo intento solo por `producto` y mostrar rosas con copy honesto. Aprovecha que el catálogo SÍ tiene rosas en otras ocasiones (validado por otros TCs). Reusable para cualquier mismatch producto/ocasion futuro.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 1 | Fallback escalonado en Compra: si `(producto+ocasion)`=0 matches del producto explícito, reintentar solo por `producto` y mostrar con copy honesto ("no tengo rosas para decoración, pero estas...") | 🟢 9/10 | — | Resuelve causa raíz en la capa controlable, generaliza a otros productos/ocasiones, mejora UX honesta, permite que el regex haga match con "Rosa" |
| 2 | Tag rosas existentes con `ocasion=Decoracion` en `petal-sheet-api` | 🟢 8/10 | petal-sheet-api (repo separado, fuera de scope ACT) + criterio de negocio | Fix de datos directo, pero requiere tocar backend externo y no generaliza: cada mismatch nuevo requeriría tag manual |
| 3 | Añadir SKU "Ramo de Rosas Decoración" (S/M/L) al catálogo | 🟡 7/10 | petal-sheet-api + operaciones (foto, stock, precio, decisión negocio) | Solución de negocio, no técnica. Resuelve el TC pero no la clase de problema; coste alto y no reutilizable |
| 4 | Añadir solo copy de transparencia ("no tengo X para Y") sin reintento | 🟡 6/10 | — | Mejora UX, pero sin reintento el agente sigue sin mostrar rosas → el regex del test seguiría en FAIL |
| 5 | Priorizar slot `producto` sobre `ocasion` en la consulta inicial al catálogo | 🟡 5/10 | — | Resuelve este caso pero riesgo de romper TCs donde la `ocasion` es el driver principal (regalo sorpresa, condolencias, etc.). Requeriría análisis de impacto |
| 6 | Relajar el regex del test para aceptar "rosas no disponibles para decoración" | 🔴 4/10 | — | Falsea el test: el usuario pidió rosas y el contrato es que las vea (o que se le explique claramente). Resignación, no fix |
| 7 | Eliminar TC-DECO-02 de la suite | 🔴 1/10 | — | Esconder el bug en lugar de resolverlo; rompe el contrato del QA y la cobertura del grupo COMPRA-INV |

### Plan de acción (Solución #1)

1. **Editar instrucciones del Playbook Compra** para añadir fallback escalonado: si la tool catálogo devuelve resultados pero ninguno matchea el `producto` explícito del slot, reintentar la consulta solo por `producto` (sin filtrar por `ocasion`) → `definitions/playbooks/Compra/instruction.md` (o equivalente).
2. **Añadir copy honesto** cuando el reintento sustituye los resultados originales: *"No tengo rosas específicas para decoración, pero estas rosas también quedan muy bien en un salón:"* → mismo archivo.
3. **Push del Playbook** vía `push_playbooks.py` (Full Update obligatorio en `europe-west1`, §3.8 CLAUDE.md).
4. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable y verificar que TC-DECO-01 (margaritas, baseline PASS) y el resto del grupo COMPRA-INV siguen verdes.

**Coste total**: ~15 min (10 min edición + push, 5 min QA con `--runs 3`).
