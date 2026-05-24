# Próximo Sprint — Ingeniería inversa de Petal

> **Cuándo arrancarlo**: en cuanto se cierren las automatizaciones de QA en curso
> (impact-based selection, SKIPPED status, GitHub Pages, botones Optimizar/Delete/Run).
> Las QA automations son la **fuente de verdad** del bottom-up: cuanto más sólidas,
> más fiable la pirámide reconstruida.

---

## Objetivo

Bottom-up de Petal: convertir el sistema actual (que solo vive en la cabeza de Jero)
en producto documentado y vendible, reconstruyendo la pirámide al revés.

```
TCs existentes (50)            ← "lo que verificamos hoy"
        ↑
User Stories (~25)             ← "qué necesidad cubre cada TC"
        ↑
Backlog organizado por Epics   ← "qué áreas funcionales hay"
        ↑
Roadmap multi-Sprint           ← "qué se construye primero, después, último"
        ↑
Brief del cliente reconstruido ← "qué es Petal realmente"
```

---

## Prerequisito

QA automations cerradas:
- [x] Impact map + SKIPPED status (commit pendiente)
- [ ] GitHub Pages activo y publicando
- [ ] Botones Optimizar/Delete/Run en HTML report
- [ ] Fix TC-IMPOSIBLE-01 verificado
- [ ] Trabajo del compactado actual commiteado

---

## Duración estimada

**4 días** (~6h Claude + ~2h Jero revisando).
Coste API estimado: ~0.50€.

---

## Plan diario

| Día | Tarea | Output |
|---|---|---|
| 1 | TCs → Stories (Claude lee los 50 TCs y agrupa por necesidad funcional) | ~25 stories en Notion con template conversacional (5 dimensiones: comprensión, slot-filling, tono, robustez, cierre) |
| 2 | Stories → Epics + matriz de trazabilidad | 8 Epics (EP-COMPRA, EP-DEUDA, EP-REGISTRO, EP-HANDOFF, EP-TONO, EP-ROBUSTEZ, ...) + tabla cruzada story↔TC |
| 3 | Epics → Roadmap multi-Sprint (S7-S16) | Vista roadmap en Notion: qué Sprint cubre qué Epic, dependencias, estado |
| 4 | Roadmap → Brief de cliente reconstruido | 1 doc maestro: visión, capacidades core, no-objetivos, KPIs, casos límite |

---

## Output esperado

- **Notion estructurado**: Epics → Stories → TCs con trazabilidad bidireccional
- **Brief maestro de Petal**: documento de 1-2 páginas que serviría como "input de cliente"
  si Petal fuera un proyecto real entrante
- **Matriz de cobertura**: % stories con TCs, % criterios de aceptación cubiertos,
  gaps identificados
- **Roadmap a 6 meses**: phases S7-S16 con epics asignados

---

## Por qué importa

1. **Petal sale de la cabeza de Jero** → vive en Notion como producto documentado
2. **Onboarding de futuros colaboradores** en ~1h leyendo brief + roadmap
3. **Caso de uso real para GEN**: el flujo "Petal existente → brief reverso" valida
   que GEN puede después hacer "brief → agente nuevo" (cafetería, farma, etc.)
4. **Ground truth para validar el generador top-down**: cuando se construya el
   flujo brief → backlog automático, se le da el brief de Petal y debe regenerar
   el backlog actual. Si no coincide, sabes que el generador necesita ajuste
5. **Demo más sólida**: "esto es Petal hoy + roadmap a 6 meses + cómo se conecta con QA"
6. **Producto vendible**: con esta documentación, Petal deja de ser prototipo y
   pasa a ser caso de estudio profesional usable en portfolio

---

## Referencias para arrancar

Al abrir este sprint, leer en orden:
1. `qa/test_QA_Playbooks_v23.py` — los 50 TCs son el input principal
2. `qa/impact_map.py` — agrupación por dominio ya existente (compra, deuda, registro, handoff, orquestador) — base para Epics
3. `definitions/playbooks/*.yaml` — los artefactos son la otra fuente de verdad
4. ACT_Backlog en Notion — backlog actual desordenado, se reorganizará en este Sprint
5. CLAUDE.md sección 2 (Sprints completados) — historia para contexto del roadmap

---

## Notas

- **No empezar hasta que QA esté cerrado** — los TCs son el input, si están en flux,
  el bottom-up se hace sobre arena movediza
- **Template de user story conversacional** ya discutido: "Como [persona con contexto],
  quiero expresar [intención + cómo la formula], para [resultado], y el agente debe
  [comportamiento esperado en comprensión, tono, cierre]"
- **5 dimensiones por criterio de aceptación**: comprensión, slot-filling, tono,
  robustez, cierre
- **7 grupos de TCs por dimensión**: G-HAPPY, G-LEX, G-SLOT, G-EDGE, G-ROBUST, G-ADV, G-QUAL
  (los actuales encajan, hay que reetiquetar)

Conversación de origen: sesión 2026-05-20, instancia worktree affectionate-archimedes-2f4f68.
