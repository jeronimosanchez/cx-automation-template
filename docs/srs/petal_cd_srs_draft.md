# Petal CD — Software Requirements Specification

> Versión: 0.1 (borrador) | Fecha: 2026-06-16 | Autor: Jerónimo Sánchez
> Documento de especificación del sistema Petal CD para AI Pods · Globant

---

## Convención de nombres

- **Petal CD** — el sistema completo (automatización, QA, KB, metodología)
- **CX Agente Petal** — el bot conversacional en Dialogflow CX

---

## 1. Propósito y alcance

Este documento describe **Petal CD** — un sistema de gobernanza de calidad y optimización continua de agentes conversacionales diseñado para operar en entornos de producción reales.

**Qué cubre:** metodología de calidad conversacional, arquitectura de las 4 líneas, Sistemas A y B, y el caso demo CX Agente Petal.

**A quién va dirigido:** equipos técnicos que trabajan en diseño, construcción y operación de agentes con IA.

**Alcance actual:** el núcleo de validación (QAP) y despliegue (ACT) están operativos. Los Sistemas A y B están diseñados y en construcción activa.

---

## 2. El problema

CX Agente Petal tiene 6 playbooks que Gemini interpreta en tiempo real. Gemini no es determinista: ante la misma entrada puede producir respuestas distintas. Un cambio en un playbook puede cascadear a los adyacentes sin aviso. Una tool que falla silenciosamente deja al agente respondiendo sin datos reales.

El problema no es escribir el playbook. Es **gobernar lo que Gemini hace con él en producción** — con qué criterio, con qué visibilidad, con qué capacidad de corrección.

El mercado de IA conversacional crece de 14,8B$ en 2025 a 82,5B$ en 2034 (Fortune Business Insights, 2025). A medida que la IA genera más artefactos conversacionales a mayor velocidad, el cuello de botella deja de ser la generación y pasa a ser el control de lo que se genera. Sin gobernanza, la automatización produce fallos a escala.

El problema tiene tres capas:

**1. Falta de criterio conversacional.** No existe una metodología que traduzca los principios de diseño conversacional en decisiones técnicas concretas: cómo estructurar las instrucciones al agente, qué arquitectura elegir según el tipo de interacción, cómo calibrar el comportamiento del LLM para cada contexto de cliente.

**2. Falta de conocimiento específico de herramientas.** Cada plataforma conversacional tiene su propia lógica, sus propios límites y sus propias palancas de optimización. Sin ese conocimiento granular — de CX, de ADK, de los mecanismos disponibles — es imposible conseguir el tailoring preciso que cada cliente necesita.

**3. El conocimiento crece en islas.** Lo que aprende un equipo en un proyecto no llega al siguiente. El expertise conversacional queda atrapado en personas, no en sistemas. En una empresa que entrega proyectos a escala como Globant, esto se traduce en valor no acumulado, dependencia personal y calidad variable entre proyectos.

**Petal CD es la capa de gobernanza de calidad que resuelve ese gap:** la IA orquesta el ciclo completo; el humano interviene en los gates donde su juicio es irreemplazable — define qué es calidad, aprueba lo que va a producción, decide qué fix se aplica.

---

## 3. El enfoque

Petal CD parte de una premisa concreta: **la calidad conversacional es definible, medible y mejorable de forma sistemática.**

### 3.1 Qué es calidad conversacional

El sistema trabaja con un conjunto de **principios de diseño conversacional** — criterios flexibles e incrementales que definen cómo debe comportarse un agente para que la conversación funcione. No son reglas fijas: son una base viva que evoluciona con cada proyecto y se enriquece con la experiencia acumulada.

Su función principal es servir de fundamento para el diseño de los casos de prueba: cada TC se construye garantizando que cumple con los patrones de CD que esos principios recogen.

Ejemplos representativos:
- **P1 — Pide los datos cuando los necesitas:** el agente no anticipa ni acumula preguntas innecesarias.
- **P7 — Nunca un callejón sin salida:** cualquier situación irresuelta termina con un siguiente paso concreto.
- **P13 — Cada "no" lleva una alternativa:** toda negativa va acompañada de una opción real.

Estos principios son agnósticos de plataforma y de motor (NLU, LLM o híbrido).

### 3.2 Cómo se hace medible

Los principios se traducen en **casos de prueba (TCs)** que cubren cuatro dimensiones:
- **Cumplimiento de principios CD** — verifica que el agente respeta los patrones conversacionales
- **Variables de cliente** — cubre las reglas de negocio y contexto específico del cliente
- **Happy path** — los flujos principales que deben funcionar siempre
- **Edge cases** — situaciones límite, ambigüedad, frustración, casos imposibles

La suite actual cubre **51 TCs (v1.0)**, mantenida fija intencionalmente para garantizar comparabilidad. Cada TC se ejecuta **3 veces** y el resultado es un **porcentaje de éxito** (0%, 33%, 67%, 100%) — no un binario. Esta granularidad permite distinguir fallos consistentes de comportamiento no determinista del LLM.

### 3.3 Cómo se diagnostica cuando falla

Cuando un TC no alcanza el umbral esperado, el sistema aplica un framework de análisis en **8 dimensiones** que cubre todo el stack del agente:

| # | Dimensión | Qué analiza |
|---|---|---|
| 1 | Diseño conversacional | ¿El diseño del flujo, la instrucción o los examples son la causa? |
| 2 | Routing | ¿La conversación va al módulo equivocado? |
| 3 | Parámetros / Slots | ¿Se pierde información entre componentes? |
| 4 | Integración | ¿Falla una llamada a tool o backend? |
| 5 | Datos | ¿La fuente de datos es coherente? |
| 6 | Infraestructura | ¿El deploy y la versión activa son correctos? |
| 7 | Modelo base | ¿El modelo subyacente es la fuente del fallo — no determinismo, límite de contexto, comportamiento inesperado? |
| 8 | Test | ¿El TC está mal calibrado? |

*Contexto transversal — Histórico:* no determina la causa, pero acelera el diagnóstico (¿ya hemos visto este patrón? ¿hubo un cambio reciente?).

Cada dimensión recibe una marca con fuente trazable. El diagnóstico produce candidatos de fix priorizados.

### 3.4 Validación basada en datos

Un principio transversal de Petal CD: **las decisiones se toman contra evidencia medible, no contra opiniones.** Cada fix propuesto se valida con los resultados reales del sistema — el TC re-corre, el resultado mide si el mecanismo funcionó, y ese outcome alimenta el KB. El mismo dato que detectó el problema confirma que está resuelto.

---

## 4. El sistema — arquitectura

Petal CD está organizado en **4 líneas de automatización** que cubren el ciclo de vida completo de un agente conversacional, más dos motores transversales que aprenden con cada ciclo.

### 4.1 Las 4 líneas

**ACT — Despliegue automático** ✅ Operativo

Convierte definiciones locales en cambios vivos en la plataforma conversacional. El control se ejerce íntegramente desde una IDE de LLM (Claude Code): sin acceder a la plataforma directamente, sin cambios manuales. El LLM conoce el estado completo del agente, propone cambios y los aplica mediante scripts de despliegue. Cualquier modificación aprobada se despliega automáticamente vía pipeline CI/CD: un `git push` activa el proceso completo. Patrón de idempotencia garantizada: detecta qué cambió, aplica solo eso, nunca recrea lo que ya existe. Reversible en segundos vía `git revert`.

**QAP — Validación y gobernanza de calidad** ✅ v1.0 Operativo · 🔵 v1.1 En construcción

QAP 1.1 = **Sistema A** (optimización) + **Sistema B** (capitalización). El ciclo completo: detectar → optimizar enfocado en el problema detectado → capitalizar el aprendizaje.

**v1.0 (operativo):** ejecuta la suite de 51 TCs contra el agente real, publica resultados en un dashboard accesible y aplica el framework de 8 dimensiones cuando detecta fallos. Incluye análisis estático pre-deploy (criterios de consistencia estructural y de diseño conversacional) y análisis dinámico post-deploy (comportamiento real del agente desde el JSON de CX).

**v1.1 (en construcción):** incorpora los Sistemas A y B. Ver sección 4.2.

**GEN — Generación adversarial de artefactos** 🔵 En construcción

Genera playbooks, examples, TCs y variantes de optimización. Opera en dos modos: reactivo (cuando Sistema A detecta un problema concreto) y proactivo (genera alternativas de alto nivel sin fallo previo). Integra el motor adversarial — produce múltiples candidatos enfrentados entre sí para cribar los débiles antes de escalar a validación.

**RES — Investigación continua** 🔵 Diseñado

Búsquedas programadas recurrentes que alimentan el KB con novedades de plataforma, investigación de CD y experiencias de otros proyectos. Mantiene el sistema actualizado sin intervención manual.

### 4.2 Los dos motores — QAP v1.1

**Sistema A — Optimización autónoma** 🔵 En construcción

Motor que cierra el bucle de mejora. Arranca desde el diagnóstico del fallo concreto detectado por QAP y recorre tres pasos en secuencia. Principio de diseño: **ordenado por coste** — código barato primero, LLM al final sobre evidencia ya depurada, plataforma real solo para los finalistas.

**Paso 1 — DIAGNOSTICA** *(diseño ✅ · parcialmente operativo)*

Convierte los FAILs en hipótesis de causa falsables. Seis etapas en cascada:

| Etapa | Qué hace | Estado |
|---|---|---|
| EJECUTAR | Lanza los TCs contra CX 3× y captura respuesta + trace completo (playbook, slots, tools) | ✅ |
| DETECTAR | Marca fallos por estática y por comportamiento (FN/FP) | ✅ |
| CONFIAR | Comprueba que el fallo es real: varianza ≥2/3, coherencia veredicto↔trace | 🟡 |
| LOCALIZAR | Atribuye el fallo al elemento señalado por la evidencia (routing, slot, tool, diseño) | 🟡 |
| PRIORIZAR | Agrupa fallos por firma de localización para atacar primero los de más impacto | ❌ |
| SINTETIZAR + HIPÓTESIS | El modelo recibe solo lo implicado + su evidencia y formula un diferencial ranqueado de 2-4 hipótesis (granular + estructural), ordenadas por evidencia convergente | 🟡 |

Contrato de salida: un diferencial ranqueado. Cada hipótesis = (claim · evidencia convergente · condición de falsación · mejora esperada). El ranking es un plan de prueba — REPARA/VALIDA lo caminan desde la #1.

**Paso 2 — REPARA** *(diseño ✅ · parcialmente operativo)*

De la causa al fix, ordenado por coste. Para la hipótesis más probable: genera candidatos de parche → los criba a coste cero con ADK (reconstruye el agente localmente, prueba el TC afectado + edge cases generados + muestra de regresión anti-patch-overfitting) → selecciona el más barato y reversible que pasa → aplica al YAML y re-audita estáticamente → abre PR con causa, fix y TCs esperados.

*Hoy, sin ADK validado:* genera 1-2 parches y deja que VALIDA (CX real) decida. Cuando ADK esté operativo, la criba local filtra todo el abanico a coste cero y solo el finalista llega a CX.

**Paso 3 — VALIDA** *(diseño ✅ · mayoritariamente operativo)*

Árbitro empírico: una hipótesis es verdadera solo si su fix hace pasar el test. Despliega el fix vía pipeline → re-ejecuta solo los TCs del scope (¿el FAIL se volvió PASS?) → corre la suite completa 3× para cazar regresiones → emite veredicto. Si no resuelto, sube a la siguiente hipótesis del diferencial. Lo resuelto se entrega a Sistema B para destilarlo en receta reutilizable del KB.

*Tres niveles de diagnóstico (eje de entrada al Sistema A):*
- **Reactivo** — por síntoma de TC fallido (dinámico, post-deploy)
- **Proactivo micro** — por elemento (estático, por playbook/tool antes del deploy)
- **Proactivo macro** — sistémico, arquitectónico (estático, entre componentes)

**Sistema B — Capitalización del conocimiento** 🔵 En construcción

Genera y estructura conocimiento desde la operación de cada ciclo a tres niveles:
- `kb_proj_` — comportamientos y mecanismos específicos del agente del cliente
- `kb_plat_` — aprendizajes sobre la plataforma concreta (CX, ADK, etc.)
- `kb_ag_` — principios universales de diseño conversacional

Retroalimenta a Sistema A (mecanismos efectivos vs anti-patrones) y al siguiente proyecto (el conocimiento acumulado no se pierde).

### 4.3 El KB — base de conocimiento estratificada

| Capa | Contenido | Alcance |
|---|---|---|
| `kb_ag_` | Principios de diseño conversacional | Universal — cualquier agente, cualquier cliente |
| `kb_sys_` | Arquitectura y operación del sistema | Petal CD internamente |
| `kb_plat_` | Conocimiento específico por plataforma (CX, ADK…) | Por plataforma — adaptable |
| `kb_proj_` | Diseño concreto del agente del cliente | Por proyecto — tailored |

La estratificación permite al sistema ser **agnóstico y preciso a la vez**: las capas altas crecen una vez y benefician a todos los proyectos; la capa de proyecto es específica de cada cliente.

### 4.4 Tres sistemas de control

El sistema integra tres mecanismos de control con roles distintos y complementarios:

- **Hard eval (regex)** ✅ Operativo — validación determinista para lo verificable con certeza
- **Juez soft (Gemma)** ✅ Operativo — evalúa calidad conversacional con 6 dimensiones derivadas de principios de diseño (tono, vocabulario, invisibilidad de la fontanería, confirmación, enganche, alternativa ante negativa)
- **Adversarial (GEN)** 🔵 En construcción — genera y enfrenta candidatos entre sí para cribar los débiles

### 4.5 Principio de austeridad

El sistema opera bajo un principio de **embudo austero**: los candidatos de fix se generan y filtran localmente (sin coste, con modelos locales) antes de escalar a la plataforma real. Solo los candidatos con potencial real llegan a validación en CX. Esto permite explorar múltiples hipótesis y pruebas A/B sin disparar el coste operativo.

### 4.6 Agnóstico de plataforma y motor

Petal CD opera hoy sobre Dialogflow CX con arquitectura LLM (playbooks). Su diseño contempla adaptación a otras plataformas vía adapters de plataforma en el KB, y a otros motores (NLU clásico, híbrido NLU+LLM) sin cambiar el núcleo metodológico.

---

## 5. Demo case: CX Agente Petal

> ⚠️ *Sección en construcción — se completará con capturas del dashboard y resultados actualizados del GitHub.*

### El agente

CX Agente Petal es un agente de floristería online en Dialogflow CX construido como simulación de un proyecto de producción real. Sus problemas de robustez iniciales se convirtieron en la razón de construir el sistema CD: cada optimización pasa por el pipeline, cerrando el ciclo. Petal y el sistema co-evolucionan.

### Números reales

| Métrica | Valor |
|---|---|
| Playbooks en producción | 6 (Orchestrator, Compra, Checkout, Registro Task, Gestión Deuda, Handoff) |
| Suite QA | 51 TCs |
| Último run estable | 90% — 46/51 PASS |
| Rango histórico | 88–95% |
| Tests unitarios ACT | 432 |
| Tests unitarios QAP | 60 |
| Cribador local | 64% acuerdo vs CX · 0 falsos negativos |
| Limitaciones conocidas documentadas | 3 (LIMIT-01, LIMIT-02, LIMIT-03) |

### Artefactos disponibles

- [Repo ACT](https://github.com/jeronimosanchez/cx-automation-template) — deploy, scripts, CI/CD
- [Repo QAP](https://github.com/jeronimosanchez/agent-validation-engine) — validación, cribador, dashboard
- [Portfolio](https://jeronimosanchez.github.io) — chat en producción + demo

> ⚠️ *Pendiente: capturas del dashboard QA HTML y screenshot del chat en producción.*

---

## 6. Petal CD en AI Pods

> ⚠️ *Sección en construcción.*

### Dos roles

**Rol externo — por proyecto de cliente: Conversational Quality Architect**

Los developers construyen la fontanería. Este rol define qué tiene que salir por el grifo y mide si sale bien.

- **Fase 1 — Antes de construir:** define qué es calidad para este cliente → principios aplicados, TCs y rúbricas. Arquitectura conversacional (qué tareas hace el agente, cómo responde, qué nunca puede hacer).
- **Fase 2 — Durante el build:** static audit de lo que los developers escriben. Aporta el KB de plataforma (footguns que ellos no conocen: bugs de región, example-first, exit paths, parámetros no declarados).
- **Fase 3 — Gate previo a producción:** el PR no se mergea sin visto bueno. Corre el QA, revisa resultados, decide si cumple los criterios.
- **Fase 4 — Post-deploy y optimización:** monitoriza resultados, activa Sistema A cuando hay FAILs, supervisa propuestas de GEN, aprueba fixes.

**Rol interno — sobre el sistema Petal CD: Conversational Design & Quality Lead**

- Metodología — define y evoluciona el framework de análisis (dimensiones, niveles de diagnóstico, rúbricas)
- Knowledge Engineering — construye y curada la KB estratificada
- Skill Design — diseña y afina las skills del sistema
- Evolución del sistema — define las versiones (QAP 1.0→1.1, GEN, RES) y sus capacidades
- Platform Adaptation — diseña los adapters para nuevas plataformas conversacionales
- Dirección de investigación — qué investiga RES y cómo se incorpora al KB

---

## 7. Visión y continuidad

> ⚠️ *Sección en construcción.*

### Objetivo a medio plazo

Petal CD como sistema completo de gobernanza de calidad conversacional:

- **Ciclo completo automatizado** — análisis → generación adversarial → validación → pruebas A/B → deploy → medición
- **KB completa para 3 plataformas** — Dialogflow CX (ADK) · Rasa · Azure Bot Framework
- **Sistema ecléctico** — el núcleo metodológico es el mismo; los adapters de plataforma lo hacen funcionar en cualquier infraestructura con capacidad de testing local
- **Sistemas A y B completados** — optimización autónoma y capitalización del conocimiento operativos

### El valor que se acumula

Cada proyecto enriquece el sistema: más mecanismos verificados en el KB, rúbricas más calibradas, adapters para más plataformas. El valor no queda en el proyecto — queda en el sistema, disponible para el siguiente cliente.

---

*Documento en construcción — versión 0.1*
*Próxima actualización: definición completa de Sistemas A y B + capturas de artefactos.*
