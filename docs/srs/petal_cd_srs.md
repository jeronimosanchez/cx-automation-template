# Petal CD — Software Requirements Specification

> Versión: 0.1 (en construcción) | Fecha: 2026-06-14 | Autor: Jerónimo Sánchez
> Documento de especificación del sistema Petal CD para AI Pods · Globant

---

## Convención de nombres

- **Petal CD** — el sistema completo (automatización, QA, KB, metodología)
- **CX Agente Petal** — el bot conversacional en Dialogflow CX

---

## 1. Propósito y alcance

Este documento describe **Petal CD** — un sistema de validación y optimización continua de agentes conversacionales diseñado para operar en entornos de producción reales.

**Qué cubre:** metodología de calidad conversacional, arquitectura de las 4 líneas, Sistemas A y B, y el caso demo CX Agente Petal.

**A quién va dirigido:** equipos técnicos que trabajan en diseño, construcción y operación de agentes con IA.

**Alcance actual:** el núcleo de validación (QAP) y despliegue (ACT) están operativos. Los Sistemas A y B están diseñados y en construcción.

---

## 2. El problema

El mercado de IA conversacional crece de 14,8B$ en 2025 a 82,5B$ en 2034 (Fortune Business Insights, 2025). El 70% de los clientes espera experiencias conversacionales en los canales digitales, y el 87% prefiere sistemas que se comuniquen de forma natural (Salesforce · Zoom/Morning Consult, 2025). Para 2027, el 50% de los casos de atención al cliente serán resueltos por IA (Salesforce, 2025).

La demanda existe. El problema es otro: **construir bien estos sistemas es más difícil de lo que parece, y por razones que van más allá de la ingeniería.**

Forrester lo define con precisión: *"Getting the user experience right requires two types of design expertise: human-centered design and conversational design."* (Forrester Research, ene. 2025). Los agentes conversacionales no fallan por falta de ingeniería — fallan por falta de criterio conversacional: instrucciones ambiguas, enrutado incorrecto, comportamiento inconsistente del LLM, pérdida de contexto entre componentes.

Pero el problema tiene tres capas:

**1. Falta de criterio conversacional.** No existe una metodología que traduzca los principios de diseño conversacional en decisiones técnicas concretas: cómo estructurar las instrucciones al agente, qué arquitectura elegir según el tipo de interacción, cómo calibrar el comportamiento del LLM para cada contexto de cliente.

**2. Falta de conocimiento específico de herramientas.** Cada plataforma conversacional tiene su propia lógica, sus propios límites y sus propias palancas de optimización. Sin ese conocimiento granular — de CX, de ADK, de los mecanismos disponibles — es imposible conseguir el tailoring preciso que cada cliente necesita ni proponer alternativas con criterio.

**3. El conocimiento crece en islas.** Lo que aprende un equipo en un proyecto no llega al siguiente. El expertise conversacional queda atrapado en personas, no en sistemas — y cuando esa persona cambia de proyecto o de empresa, el aprendizaje desaparece. En una empresa que entrega proyectos a escala como Globant, esto se traduce en valor no acumulado, dependencia personal y calidad variable entre proyectos.

**Petal CD es la respuesta a ese gap en sus tres dimensiones:** metodología conversacional formalizada, conocimiento específico de plataforma estructurado y un sistema de KB que convierte el aprendizaje de cada proyecto en activo compartido que crece con cada cliente.

---

## 3. El enfoque

Petal CD parte de una premisa concreta: **la calidad conversacional es definible, medible y mejorable de forma sistemática.**

### 3.1 Qué es calidad conversacional

El sistema trabaja con un conjunto de **principios de diseño conversacional** — criterios flexibles e incrementales que definen cómo debe comportarse un agente para que la conversación funcione. No son reglas fijas: son una base viva que evoluciona con cada proyecto y se enriquece con la experiencia acumulada.

Su función principal es servir de fundamento para el diseño de los casos de prueba: cada TC se construye garantizando que cumple con los patrones de CD que esos principios recogen — y por tanto, que el sistema conversacional alcanza el nivel de calidad esperado.

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

La suite actual cubre **51 TCs (v1.0)**, mantenida fija intencionalmente para garantizar comparabilidad: mientras el sistema está bajo medición, los TCs no cambian — eso es lo que permite comparar entre versiones con la misma vara. Cuando se libere CX Agente Petal 1.1, la suite se actualizará para reflejar las optimizaciones de la nueva versión, estableciendo un nuevo baseline.

Cada TC se ejecuta **3 veces** y el resultado es un **porcentaje de éxito** (0%, 33%, 67%, 100%) — no un binario. Esta granularidad permite distinguir fallos consistentes de comportamiento no determinista del LLM.

### 3.3 Cómo se diagnostica cuando falla

Cuando un TC no alcanza el umbral esperado, el sistema aplica un framework de análisis en **9 dimensiones** que cubre todo el stack del agente:

| # | Dimensión | Qué analiza |
|---|---|---|
| 1 | Comportamiento | ¿La instrucción al agente es ambigua o contradictoria? |
| 2 | Routing | ¿La conversación va al módulo equivocado? |
| 3 | Parámetros / Slots | ¿Se pierde información entre componentes? |
| 4 | Integración | ¿Falla una llamada a tool o backend? |
| 5 | Datos | ¿La fuente de datos es coherente? |
| 6 | Infraestructura | ¿El deploy y la versión activa son correctos? |
| 7 | Modelo / LLM | ¿El LLM se comporta de forma no determinista? |
| 8 | Histórico | ¿Hay regresión por un cambio reciente? |
| 9 | Test | ¿El propio test está mal calibrado? |

Cada dimensión recibe una marca con fuente trazable. El diagnóstico produce una recomendación de fix con soluciones priorizadas.

### 3.4 Validación basada en datos

Un principio transversal de Petal CD: **las decisiones se toman contra evidencia medible, no contra opiniones.** Cada análisis, cada fix propuesto y cada mejora aplicada se valida con los resultados reales del sistema — el TC re-corre, el resultado mide si el mecanismo funcionó, y ese outcome alimenta el KB. Sin anotadores externos, sin validación puntual: continua, automática y acumulativa.

---

## 4. El sistema — arquitectura

Petal CD está organizado en **4 líneas de automatización** que cubren el ciclo de vida completo de un agente conversacional, más dos motores transversales que aprenden con cada ciclo.

### 4.1 Las 4 líneas

**ACT — Despliegue automático** ✅ Operativo

Convierte definiciones locales en cambios vivos en la plataforma conversacional. El control se ejerce íntegramente desde una IDE de LLM (Claude Code): sin acceder a la plataforma directamente, sin cambios manuales. El LLM conoce el estado completo del agente, propone cambios y los aplica mediante scripts de despliegue. Cualquier modificación aprobada se despliega automáticamente vía pipeline CI/CD: un `git push` activa el proceso completo. Patrón de idempotencia garantizada: detecta qué cambió, aplica solo eso, nunca recrea lo que ya existe. Reversible en segundos vía `git revert`.

**QAP — Validación y diagnóstico** ✅ v1.0 Operativo · 🔵 v1.1 En construcción

**v1.0 (operativo):** ejecuta la suite de 51 TCs contra el agente real, publica resultados en un dashboard accesible y aplica el framework de 9 dimensiones cuando detecta fallos. Incluye análisis estático pre-deploy (8 criterios de consistencia estructural) y análisis dinámico post-deploy (comportamiento real del agente).

**v1.1 (en construcción):** amplía el alcance incorporando los Sistemas A y B — mayor capacidad de análisis, pronóstico de soluciones y optimización autónoma. Ver sección 4.2.

**GEN — Generación de artefactos** 🔵 En construcción

Generará automáticamente playbooks, examples y TCs desde especificaciones del cliente, acelerando el time-to-market de nuevos agentes.

**RES — Investigación continua** 🔵 Diseñado

Búsquedas programadas recurrentes que alimentan el KB con novedades de plataforma, investigación de CD y experiencias de otros proyectos. Mantiene el sistema actualizado sin intervención manual.

### 4.2 Los dos motores (QAP v1.1)

**Sistema A — Optimización autónoma** 🔵 En construcción

Motor que cierra el bucle de mejora siguiendo el principio de validación basada en datos:

1. **Diagnóstico de causa raíz** — análisis en 9 dimensiones para identificar exactamente dónde falla el agente antes de proponer ninguna solución
2. **Consulta al KB de anti-patrones** — descarta mecanismos que ya fallaron en ciclos anteriores
3. **Generación adversarial de hipótesis** — produce múltiples candidatos de fix enfrentados entre sí
4. **Validación a coste cero** — las hipótesis se prueban localmente con simulación (sin llamadas a la plataforma real)
5. **Ranking de candidatos** — ordena las hipótesis por probabilidad de éxito
6. **Validación de los mejores candidatos** — los finalistas se validan contra la suite QA conversacional real
7. **Benchmark del sistema** — compara métricas antes/después para demostrar que la mejora es real y no rompe lo que funcionaba

**Sistema B — Capitalización del conocimiento** 🔵 En construcción

Genera y estructura conocimiento a tres niveles desde la operación de cada ciclo:
- **Nivel proyecto** (`kb_proj_`) — comportamientos, patrones y mecanismos específicos del agente del cliente
- **Nivel plataforma** (`kb_plat_`) — aprendizajes sobre la herramienta concreta utilizada (CX, ADK, etc.)
- **Nivel sistema** (`kb_sys_`) — conocimiento sobre el propio funcionamiento de Petal CD

Retroalimenta a Sistema A (mecanismos efectivos vs anti-patrones), a la metodología (principios que se refinan) y al siguiente proyecto (el conocimiento acumulado no se pierde).

### 4.3 El KB — base de conocimiento estratificada

El conocimiento del sistema se organiza en **4 capas** con alcance diferente:

| Capa | Contenido | Alcance |
|---|---|---|
| `kb_ag_` | Principios de diseño conversacional | Universal — cualquier agente, cualquier cliente |
| `kb_sys_` | Arquitectura y operación del sistema | Petal CD internamente |
| `kb_plat_` | Conocimiento específico por plataforma (CX, ADK…) | Por plataforma — adaptable |
| `kb_proj_` | Diseño concreto del agente del cliente | Por proyecto — tailored |

La estratificación es lo que permite al sistema ser **agnóstico y preciso a la vez**: las capas altas crecen una vez y benefician a todos los proyectos; la capa de proyecto es específica de cada cliente. El conocimiento no queda en islas — se acumula y se comparte.

### 4.4 Principio de austeridad

El sistema opera bajo un principio de **embudo austero**: las hipótesis de mejora se generan y filtran localmente (sin coste, con modelos locales) antes de escalar a la plataforma real. Solo los candidatos con potencial real llegan a validación en CX. Esto permite explorar múltiples opciones y pruebas A/B sin disparar el coste operativo.

### 4.5 Agnóstico de plataforma y motor

Petal CD opera hoy sobre Dialogflow CX con arquitectura LLM (playbooks). Su diseño contempla adaptación a otras plataformas (Amazon Lex, Azure Bot Framework, Rasa) vía adapters de plataforma en el KB, y a otros motores (NLU clásico, híbrido NLU+LLM) sin cambiar el núcleo metodológico.

---

<!-- SECCIONES PENDIENTES -->
## 5. Demo case: CX Agente Petal

## 6. Petal CD en AI Pods

## 7. Visión y continuidad
