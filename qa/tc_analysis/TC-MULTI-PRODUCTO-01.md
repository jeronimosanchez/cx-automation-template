---
status: FAIL
tipo: Bug Playbook
estimacion: ~20 min (Solución #1 recomendada)
---

## T1

### Turnos vs Problemas detectados

| # | Quién | Acción / Texto | Problema detectado |
|---|-------|----------------|--------------------|
| 1 | User | *"quiero un ramo de rosas y un centro de mesa para una boda"* | — |
| 2 | Orquestador | Clasifica como G5 (compra), extrae `ocasion_detectada=Boda`, `modo_tono=estandar`. NO extrae `producto`. `intencion_inicial` contiene el texto completo con ambos ítems. | ⚠️ No extrae `producto` cuando hay múltiples ítems. La señal de multi-producto (dos tipos distintos) no se reconoce ni marca como slot. |
| 3 | Compra | Recibe G5 + `ocasion=Boda` sin slot `producto`. Infiere desde `intencion_inicial` el producto más relevante para boda (ramo de novia rosas). Ignora "centro de mesa". | 🔴 Trata la petición como mono-producto. Muestra "Ramo de Novia Rosas — L (12 flores, 45€)" y pregunta si gusta, sin mencionar el segundo ítem ni la naturaleza multi-item del pedido. |
| 4 | Agente | *"Claro, para boda tengo el Ramo de Novia Rosas — L (12 flores, 45€). ¿Te gusta o miramos otras opciones?"* | 🔴 El segundo ítem (centro de mesa) desaparece por completo. El usuario puede sentir que el agente no le escucha. |
| 5 | Test (check) | Regex: `centro.{0,80}ramo\|ramo.{0,80}centro\|empez.{0,20}por\|uno.{0,20}vez\|un producto` | 🔴 FAIL — el agente no menciona "centro", no indica que gestiona ítems de uno en uno, ni explica ninguna limitación. Check bien calibrado. |

### Causa raíz (descompuesta en 3 capas)

1. **Playbook Compra (capa principal)**: no tiene CASO ESPECIAL para peticiones multi-producto. Ante la presencia de "X y Y" en el mensaje (dos productos distintos), debería: (a) reconocer ambos explícitamente, (b) explicar que gestiona un producto a la vez, y (c) preguntar por cuál empezar.
2. **Orquestador (secundaria)**: no extrae `producto` cuando hay múltiples ítems — el slot queda vacío. Sin señal de multi-producto, el Playbook Compra no puede distinguir este caso del flujo estándar y actúa en modo mono-producto.
3. **Arquitectura de slots (estructural)**: el esquema actual (`producto`, `ocasion`, `modo_tono`) está diseñado para peticiones mono-producto. Para soportar multi-ítem correctamente se necesitaría un slot `multi_producto` o `productos_adicionales` en el orquestador.

## Recomendación

### Solución recomendada: #1 — Playbook Compra: CASO ESPECIAL "petición multi-producto"

🟢 **8/10** · ~20 min · Sin dependencias externas

**Por qué**: fix conservador y directo. Mismo patrón arquitectónico que TC-URGENCIA-01 (CASOS ESPECIALES). Detectar la conjunción "X y Y" con dos tipos de producto y responder: "Perfecto, te ayudo con los dos. Empiezo por el ramo de rosas — [opciones]. Cuando terminemos, pasamos al centro de mesa." Sin cambios en orquestador ni en schema de slots.

### Soluciones evaluadas (ordenadas por score)

| # | Solución | Score | Dependencias | Por qué este scoring |
|---|----------|-------|--------------|----------------------|
| 3 | **Combinación #1 + #2** (Playbook CASO ESPECIAL + Orquestador extrae `multi_producto`) | 🟢 8.5/10 | Tests Orquestador | Más robusto: orquestador pasa señal explícita al playbook en lugar de inferir del texto. ~50 min. Mejor arquitectura a largo plazo. |
| 1 | **Playbook Compra: CASO ESPECIAL "petición multi-producto"** — detectar "X y Y" y gestionar uno a uno, reconociendo ambos ítems desde el primer turno | 🟢 8/10 | — | Fix de raíz accesible. Mismo patrón que CASOS ESPECIALES de urgencia. ~20 min. Resuelve test y UX real. |
| 2 | **Orquestador: extraer `multi_producto=true`** cuando hay ≥2 ítems distintos + `productos_solicitados` como lista | 🟢 7/10 | Tests Orquestador | Solución elegante pero incompleta sola: el Playbook Compra todavía necesita lógica para reaccionar al flag. Solo tiene efecto combinado con #1. ~30 min. |
| 4 | **Examples: EX-MULTI-01** anclando "ramo y centro de mesa para boda" → respuesta que reconoce ambos + gestiona de uno en uno | 🟡 6/10 | — | Refuerza determinismo del LLM en este input específico. ~10 min. Alcance limitado: solo inputs cercanos al ejemplo. Multiplicador de #1, no sustituto. |
| 5 | **Playbook Compra: instrucción general** "si detectas múltiples productos en `intencion_inicial`, menciónalos todos y gestiona de uno en uno" sin CASO ESPECIAL explícito | 🟡 5/10 | — | Menos robusto que #1: instrucción general más susceptible a ser ignorada por el LLM en variaciones. Más flakiness probable. Menos trabajo inicial pero más retrabajo futuro. |
| 6 | **Test: relajar regex** para aceptar respuesta solo al primer producto | 🔴 4/10 | — | Falso fix: el agente está ignorando el segundo ítem. Relajar el test pierde señal real. Solo válido si negocio decide que multi-producto no es un caso soportado Y el agente comunica esa limitación explícitamente. |
| 7 | **No hacer nada** | 🔴 2/10 | — | UX real deficiente: usuario que pide dos productos ve que uno desaparece sin explicación. La frecuencia de pedidos multi-ítem en florería para eventos justifica el fix. Test seguirá fallando. |

### Plan de acción (Solución #1)

1. **Editar Playbook Compra** (`definitions/playbooks/compra.yaml`) → añadir bloque al inicio de CASOS ESPECIALES:
   ```
   - **Petición multi-producto** (el usuario menciona dos o más productos distintos unidos por "y"):
     ANTES de mostrar catálogo, reconocer ambos explícitamente:
     "Perfecto, te ayudo con los dos. Empiezo por [primer producto] — [opciones].
     Cuando terminemos, seguimos con [segundo producto]."
     No mostrar catálogo genérico hasta que el usuario confirme con cuál empieza.
   ```
2. **Commit + push** → CI corre `Deploy to Petal CX` + `QA Petal`.
3. **Re-ejecutar QA** con `--runs 3` para confirmar PASS estable.

**Coste total**: ~20 min (edit + commit + verificación post-merge).
