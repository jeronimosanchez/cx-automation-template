# Modelo de agnosticidad — la cadena juicio → medición → personalización → transferencia

> Material de fundamento del SRS. Capturado 2026-06-11.
> Responde a la pregunta nuclear del posicionamiento: **¿qué hace agnóstico al sistema,
> y por qué eso es IP y no una commodity?** Es la columna vertebral conceptual sobre la
> que se apoya todo lo demás (mercado, requisitos, arquitectura).

---

## El problema que resuelve este modelo

"Agnóstico" se usa de forma vaga. Cuando alguien dice "mi sistema es agnóstico de
plataforma", puede querer decir tres cosas distintas, y confundirlas debilita el
argumento. Este documento las separa y muestra cómo encajan en una sola cadena.

---

## Dos sentidos de "agnóstico" (ambos reales, complementarios)

| Sentido | Qué significa | Mecanismo | Demostrable con |
|---|---|---|---|
| **Adaptable** | El sistema no está cableado a ningún cliente; lo apuntas a uno nuevo, mide con sus datos y se ajusta cuantitativamente | Personalización por datos (barrido de niveles N, % resolución, ROI por cluster) | **1 cliente** (Petal basta) |
| **Transferible** | Lo que el sistema aprende viaja entre clientes sin reescribirse | Destilado a la capa universal (kb_ag_) | **2+ clientes** (requiere transfer real) |

No compiten. Son el motor y lo que el motor transporta. El error común es defender
solo uno: si defiendes solo "adaptable", suenas a un hyperparameter sweep (commodity);
si defiendes solo "transferible", no lo puedes probar con un único cliente.

---

## La cadena canónica (el modelo)

```
[1] CAPA DE JUICIO          define QUÉ es una buena conversación
    (rúbricas + kb_ag_)      → criterio explícito y evaluable
        ↓
[2] MEDICIÓN                Sistema A mide cuantitativamente contra ese criterio
    (los 12 pasos)           → % resolución, ROI, veredictos PASS/FAIL
        ↓
[3] PERSONALIZACIÓN         los datos del cliente ajustan el agente a ese cliente
    (barrido N, fixes)       → config que puntúa más alto para ESTE cliente
        ↓
[4] TRANSFERENCIA           los patrones que aciertan en 2+ clientes suben a kb_ag_
    (Sistema B)              → conocimiento client-independent = IP
        ↓
    (realimenta [1]: el juicio universal crece y aterriza en rúbricas del próximo cliente)
```

---

## La dependencia que lo sostiene todo

**La personalización cuantitativa NO se sostiene sola. Depende de la capa de juicio
para que los números signifiquen algo.**

Ejemplo concreto: Sistema A escupe *"N5 resuelve 85%, N1 resuelve 40%"*. Ese número es
la personalización por datos. Pero **¿85% de qué?** De TCs "resueltos correctamente".
¿Quién define "correctamente"? La rúbrica. Sin rúbrica, ese 85% es ruido — optimizas
contra un medidor arbitrario, y eso lo hace cualquiera.

- Los **datos** son la evidencia.
- El **juicio** es el criterio que hace interpretable esa evidencia.

Lo que hace valiosa la personalización cuantitativa no es que sea cuantitativa (un
grid-search también lo es). Es que está **guiada por juicio**: los datos dicen *qué
config puntúa más*; el juicio dice *qué significa "más" y por qué falló lo que falló*.

> **Frase de cierre para el SRS:** los datos personalizan, pero el juicio decide contra
> qué se personaliza. Ninguno de los dos solo te hace agnóstico — te hace agnóstico el
> bucle completo.

---

## Dónde vive físicamente cada capa

| Capa de la cadena | Artefacto físico | Estado hoy |
|---|---|---|
| [1] Juicio | Rúbricas (ejecutable, por TC) + kb_ag_ (almacenado, abstracto) | 🔴 casi vacío — el grueso está en kb_proj_petal, aún no destilado |
| [2] Medición | Sistema A — pipeline de 12 pasos | 🔴 diseñado, no construido (bloquea en gate ADK >85%) |
| [3] Personalización | Barrido de niveles N + fixes validados | 🔴 depende de [1] y [2] |
| [4] Transferencia | Sistema B (extractor → classifier → writer) | 🔴 placeholders escritos |

---

## Implicación estratégica (orden de construcción)

El instinto natural es pulir el orquestador del Sistema A (el chasis). Es un error: el
chasis es replicable (cualquier vendor lo copia en una tarde). El **combustible** es la
capa de juicio — rúbricas + kb_ag_ + el gate de fidelidad ADK. Esas son las piezas que:

1. **kb_ag_ / rúbricas** — son lo único que viaja entre clientes = la IP literal.
2. **Gate ADK >85%** — sin fidelidad local, solo puedes validar en la plataforma real
   de cada cliente, y ahí dejas de ser agnóstico y vuelves a ser dependiente de CX/Rasa.

**Orden correcto: primero las rúbricas y el gate ADK; después, más pulido del motor.**

---

## Matiz para un solo cliente (situación actual)

Con un único cliente (Petal), casi todo el juicio está todavía en `kb_proj_` —
específico, no agnóstico. La agnosticidad no es algo que ya tengas; es algo que
**demuestras que sabes producir**. Con un solo cliente, lo que vendes no es "tengo el
juicio universal", sino **"tengo el método que lo destila"** — y eso es exactamente
Sistema A + Sistema B funcionando sobre la capa de juicio.

Por eso el SRS no debe prometer un KB universal ya hecho. Debe demostrar dominio del
**método de destilación**: la cadena de arriba, corriendo end-to-end sobre Petal, con
la arquitectura preparada para que el cliente #2 active la transferencia.

---

## Conexión con el resto del SRS

- Enlaza con la estrategia agnostic-first / discipline-first (las specs se escriben
  sobre la disciplina durable, no sobre CX).
- El reposicionamiento "de CI/CD a CX → método QA + juicio conversacional en cualquier
  plataforma": el **juicio** es el sustantivo, Sistema A es el verbo.
- Los criterios de aceptación del SRS = las rúbricas = la capa [1]. El puente entre el
  spec y el adversarial pasa por aquí.
