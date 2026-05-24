---
name: epic-backlog-conversational-design
description: "Épica precursora: construir el Backlog de Conversational Design propio del proyecto. Pre-requisito para que el análisis QA deje de alucinar sobre política de producto."
metadata: 
  node_type: memory
  type: project
  originSessionId: aba78269-83d9-450d-9b27-639b9a2827f7
---

# Épica — Backlog de Conversational Design

**Origen:** 21-may-2026, demo Petal. Detectado que la épica `epic_optimizar_analisis_QA.md` depende de fuentes (políticas, changelog, roadmap) que **aún no existen como artefactos propios** del proyecto.

**Hipótesis raíz:** sin un Conversational Design backlog explícito, ningún análisis automático (skill `qa-tc-analyzer` o sesión interactiva) puede razonar sobre **intención** de un comportamiento. Es decir: si Petal no soporta same-day, ¿es un bug, una decisión de producto, o una feature pendiente? Hoy esa respuesta vive en la cabeza de Jero.

**Valor:**
- Análisis QA fiable (sin alucinación sobre política).
- Onboarding de nuevos colaboradores reducido (no necesitan a Jero presente para saber por qué algo es así).
- Backlog priorizable y vendible (sirve para mostrar a clientes en consultoría).
- Pre-requisito para escalar el template a otros agentes/clientes.

---

## Estructura mínima viable del backlog

5 documentos vivos en el repo (probablemente en `docs/conversational_design/` o equivalente):

### 1. `user_stories.md`
Stories del agente desde el punto de vista del cliente final:
- "Como cliente quiero comprar flores para una ocasión → Petal me guía con catálogo y plazos"
- "Como cliente quiero consultar el estado de mi pedido → Petal me da info o me deriva a humano"
- "Como cliente quiero registrarme rápido durante la compra → Petal toma mis datos sin fricción"
- Etc.

### 2. `politicas_producto.md`
Tabla con las reglas hard:
| Política | Valor | Razón |
|---|---|---|
| Plazo mínimo entrega | 24h | Logística simulada del proyecto |
| Importe máximo sin aprobación | 500€ | Escala a Handoff |
| Ocasiones soportadas | Regalo, Funeral, Boda, Decoración, Corporativo, Otro | Restricción de catálogo |
| Devoluciones | No soportadas | Out-of-scope; se deriva a Handoff |
| Multi-producto | Max 2 productos por pedido | Restricción del FLUJO MULTI-PRODUCTO |

### 3. `decisiones_diseno.md`
Decisiones de diseño + por qué:
- "Modo solemne no usa exclamaciones porque el contexto suele ser funerario/sensible"
- "TT-11 desambiguación SOLO si hay ambigüedad real porque sino el agente molesta con confirmaciones obvias"
- "El multi-producto se separa en CASO ESPECIAL porque el flujo estándar no extrapola bien a 2 productos"

### 4. `roadmap.md`
Lo que NO está soportado hoy y por qué:
- "Same-day delivery: no soportado, prioridad media, depende de integración logística real"
- "Suscripciones: no soportadas, en backlog Q3 2026"
- "Multi-producto >2: no soportado, evaluado y descartado por complejidad UX"

### 5. `changelog_narrativo.md`
Cronológico, breve, explicando POR QUÉ no solo qué:
- "S5: refactor de Compra para separar flujo G3 (explorar) de G5 (compra directa) porque…"
- "S6: integración runner QA real porque Promptfoo era insuficiente para…"
- Etc.

---

## Cómo construirlo (incremental, no de golpe)

**Sprint 1 (~3 días):**
- US-CD-1: redactar `politicas_producto.md` con las 10 políticas más usadas (en cabeza de Jero hoy).
- US-CD-2: extraer del CLAUDE.md y de los playbooks los decisiones de diseño implícitas → `decisiones_diseno.md`.

**Sprint 2 (~3 días):**
- US-CD-3: redactar `roadmap.md` con features pendientes/descartadas (Jero + Claude juntos en sesión de 1h).
- US-CD-4: redactar `user_stories.md` por dominio (Compra, Checkout, Registro, etc.).

**Sprint 3 (~2 días):**
- US-CD-5: extraer `changelog_narrativo.md` del git log + memoria de sesiones. Solo eventos relevantes, no todo commit.

**Total**: ~8 días, distribuibles a lo largo de 4-6 semanas.

---

## Dependencias con otras épicas

- **Pre-requisito** de `epic_optimizar_analisis_QA.md` (US-2: acceso a memoria del proyecto).
  → Una vez exista este backlog, el skill `qa-tc-analyzer` puede consultarlo automáticamente y dejar de alucinar sobre política.
- **Pre-requisito** de `proximo_sprint_ingenieria_inversa.md` (bottom-up Petal: TCs → stories → epics → roadmap).
  → Ese sprint es la versión "ingeniería inversa" rápida para arrancar; este epic es la versión madura y mantenida.

---

## Cuándo abordar

- **No bloquea hoy** (demo) — para ese día seguimos con el conocimiento en cabeza.
- **Idealmente en el siguiente sprint completo** post-demo, antes de cualquier intento de generalizar el template a otros agentes.
- **Crítico antes de** vender consultoría a un cliente: sin este backlog, no se puede entregar como producto.

---

## Anti-patrones a evitar

- Hacer los 5 documentos de golpe → se queda a la mitad. Mejor incremental.
- Documentar TODO → solo lo que tiene consecuencias en QA o producto. Lo trivial se ignora.
- Documentar para el repo y olvidar → cada decisión nueva entra al cambio del backlog en el mismo PR. Si no, el backlog se desactualiza y vuelve a ser "lo que Jero recuerda".
