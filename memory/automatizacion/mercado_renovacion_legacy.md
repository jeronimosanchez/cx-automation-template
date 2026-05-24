# Mercado de renovación de sistemas conversacionales legacy

> Notas de la conversación 2026-05-20 sobre el segmento de mercado más
> vendible para la Automatización CD: renovación de chatbots/IVR/sistemas
> conversacionales existentes, vs greenfield.

---

## Tesis central

**Renovación es mejor mercado que greenfield para arrancar.**

| Greenfield (sistema nuevo) | Renovación (sistema existente) |
|---|---|
| Cliente no tiene datos → hay que inventar TCs | Cliente tiene histórico real → input gratis para benchmark |
| KPIs hipotéticos → difícil vender ROI | KPIs reales actuales → ROI cuantificable directo |
| Presupuesto nuevo → ciclo de aprobación largo | Presupuesto ya asignado a legacy → reasignable |
| Dolor abstracto | Dolor concreto y medible |
| Time-to-value 12-18 meses | Time-to-value 3-6 meses |
| Riesgo alto percibido | Riesgo bajo (baseline para comparar) |

**El cliente que renueva está pre-cualificado**: sabe que tiene dolor, conoce
su coste actual, tiene presupuesto reservado, y necesita evidencia de mejora
medible. Comercialmente más fácil que vender algo nuevo desde cero.

---

## Segmentos concretos del mercado de renovación

| Segmento | Volumen | Dolor específico | Madurez |
|---|---|---|---|
| **IVR tradicional → conversacional** | Muy grande (banca, seguros, salud, telco) | Abandono 60-70%, NPS bajo, coste por llamada alto | Alta urgencia |
| **Dialogflow ES → CX** | Grande, en crecimiento | Google empuja salida de ES | Decisión casi forzada |
| **Microsoft LUIS → Azure OpenAI** | Mediano | Microsoft anunció sunset oficial | Urgencia técnica real |
| **Watson legacy → moderno** | Mediano, decreciente | IBM pierde cuota, equipos quieren salir | IBM no defiende |
| **Chatbots 1ª gen (2017-2020)** | Enorme y disperso | Comparación con ChatGPT mata credibilidad interna | Momento perfecto |
| **Consolidación multi-plataforma** | Mediano, empresarial | Empresas con 3-4 sistemas distintos | Alto ticket |

**Los tres primeros tienen presión temporal explícita.** El cliente migra
quiera o no porque el vendor original deja de soportar. La conversación pasa
de "¿quieres mejorar?" a "¿quién te ayuda a migrar?".

---

## Cómo encaja la metodología actual (sin ajuste)

Lo construido ya **es** la metodología de renovación:

```
Cliente tiene legacy con 30K interacciones reales
        ↓
1. Bottom-up: TCs → stories → arquitectura del legacy actual
   (ingeniería inversa del sistema viejo — Sprint S7 planificado)
        ↓
2. Análisis KPIs reales del legacy (baseline a batir)
        ↓
3. Propuesta de 2-3 arquitecturas modernas candidatas
   (benchmark offline replay sobre las 30K)
        ↓
4. ACT despliega thin slice del ganador
        ↓
5. QAP valida que cumple KPIs baseline + mejora medible
        ↓
6. RES auto-corrige durante migración progresiva
        ↓
7. Cliente migra usuarios por cohortes con KPIs comparados
```

Cada pieza construida o planificada tiene rol directo. No es pivote — es
aplicación natural del stack a un mercado más vendible.

---

## Pitch concreto al cliente

> "Tienes un sistema conversacional que lleva X años en producción. Resuelve
> entre el 40-60% de interacciones automáticamente, el resto escala a humano.
> Te cuesta entre 50K y 200K al año.
>
> Yo trabajo así: dame acceso a tu histórico (30K interacciones con outcomes).
> En 4 semanas te entrego:
> - Análisis cuantitativo del sistema actual (KPIs reales por categoría)
> - 3 arquitecturas candidatas con coste estimado y mejora esperada
> - Benchmark offline de las 3 contra tu histórico real
> - Recomendación con razonamiento explícito y trade-offs documentados
>
> Si la recomendación cierra, ejecuto la migración progresiva en 3-6 meses
> con KPIs medidos por cohorte. Si no cierra, te quedas con el análisis y
> decides tú.
>
> Precio del análisis: X. Precio de la migración: Y, con cláusula de KPI
> mínimo a batir."

---

## Posicionamiento vs grandes consultoras

| Grandes (Deloitte, Accenture, Capgemini) | Tu posicionamiento posible |
|---|---|
| 500K-2M€ por proyecto | 50-150K€ por proyecto |
| 12-18 meses | 3-6 meses |
| Equipos de 8-15 personas | Tú + Claude como force multiplier |
| Vendor-aligned (Google/AWS/MS partner) | Vendor-neutral o multi-partner declarado |
| Metodología pesada, light en data | Metodología ligera, data-driven con offline replay |
| Cascada: discovery → diseño → build → test → deploy | Iterativo con QAP automatizado |

**Hueco de mercado: mid-market.** Empresas con presupuesto 50-200K€ que las
grandes no atienden (demasiado pequeño) y los freelancers no pueden ejecutar
(demasiado complejo). Segmento mal servido hoy.

---

## Las 7 piezas faltantes para arrancar este mercado

1. **Petal documentado como caso de estudio** (Sprint S7 bottom-up) — portfolio mostrable
2. **Metodología de offline replay funcional** — pieza técnica clave del pitch
3. **Plantilla de informe de análisis** — deliverable de las 4 semanas iniciales
4. **Stack de comparación interno** (CX + Lex + otro) — para benchmarks reales
5. **Adversarial testing automatizado** (Sprint S8/S9 planificado) — diferencial vs competencia
6. **Pricing model definido** — análisis vs migración separados, cláusulas KPI
7. **Material comercial mínimo** — one-pager, deck de pitch, 2-3 casos hipotéticos

**De estas 7, las 4 primeras salen de Sprints ya planificados.**
Las 3 últimas son trabajo comercial puro, ~2 semanas.

---

## Cadena estratégica 1-18 meses

```
1-3 meses:    QA automations cerrado + ingeniería inversa Petal + adversarial
4-5 meses:    Stack comparación interno + plantilla análisis + offline replay
6 meses:      Material comercial + primer cliente de prueba (descontado, portfolio)
7-12 meses:   2-3 clientes pagantes de renovación
12-18 meses:  Decisión: escalar como consultoría o como producto SaaS
```

---

## Notas clave de la metodología offline replay

**Crítico para este mercado.** El cliente entrega 30K interacciones reales con
outcomes conocidos → reproduces cada una contra los candidatos sin tener que
construir agentes completos. Mide capacidad del modelo, no UX final.

**Lo que NO puedes hacer**: construir agentes completos en 3-4 plataformas
para el mismo cliente. No es comercialmente viable. El offline replay filtra
a 1-2 finalistas. Solo el ganador recibe construcción real (thin slice + piloto).

**Coste real estimado por cliente**:
- Análisis 4 semanas: ~15-30K€ honorarios + ~2K€ API
- Migración 3-6 meses: ~50-150K€ según scope

---

## Referencias relacionadas

- `automatizacion/estrategia_comercial_consultoria.md` — posicionamiento vs vendors
- `current/proximo_sprint_ingenieria_inversa.md` — base metodológica (Sprint S7)
- `shared/learning_diseno_conversacional_enterprise.md` — patrón NLU+LLM (input al benchmarking)
