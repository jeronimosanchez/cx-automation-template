/**
 * act/validate_html_dom_cloudrun.js — el panel conectado, ejecutado de verdad.
 *
 * Carga `docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html` en un DOM
 * real (jsdom), sustituye `fetch` por un servidor de mentira **cuyas respuestas
 * tienen la forma exacta que devuelve `act/server_cloudrun.py`**, pulsa los
 * botones y comprueba lo que queda en pantalla.
 *
 * **Por qué esto y no un `grep`.** Un análisis de texto confirma que el código
 * llama al servidor; no confirma que el botón dispare, que el aviso aparezca ni
 * que un error se pinte como error. Los tres fallos que más caro salen —un
 * `status: "error"` con HTTP 200 pintado como éxito, un doble clic que escribe
 * dos veces y un paso que se queda colgado— solo se ven ejecutando.
 *
 * Cada comprobación está escrita para **fallar si se corta su cable**: si se
 * quita el `fetch` de un paso, si se cambia un endpoint por otro, si un aviso
 * deja de pintarse. Eso es lo que la separa de una prueba que pasa siempre.
 *
 * Salida: una línea por comprobación y un JSON final con el recuento, que es lo
 * que lee `act/validate_html_cloudrun.py`.
 *
 * Uso:  node act/validate_html_dom_cloudrun.js [ruta-del-panel]
 */

const fs = require('fs');
const path = require('path');

let JSDOM;
try {
  ({JSDOM} = require('jsdom'));
} catch (e) {
  console.log(JSON.stringify({
    error: 'sin_jsdom',
    detalle: 'Falta jsdom. Instálalo con `npm install --no-save jsdom` en la ' +
             'raíz del repositorio (queda fuera de git, ya está en .gitignore).',
  }));
  process.exit(2);
}

const RAIZ = path.resolve(__dirname, '..');
const PANEL = process.argv[2] ||
  path.join(RAIZ, 'docs/panels/act_cx_resources_deploy_v2_output_cloudrun.html');
const ORIGEN = 'http://servidor-de-prueba.test';

const PROYECTO = 'proyecto-de-prueba';
const AGENTE = 'agente-de-prueba-0001';
const AGENTE_NOMBRE = 'agente-desechable-de-prueba';
const REPO = 'ejemplo/repositorio-de-prueba';

// ── El servidor de mentira ───────────────────────────────────────────────────
//
// Devuelve el mismo sobre `{status, log, data}` que el servidor real. Las
// respuestas se declaran por escenario; lo que no esté declarado es un fallo
// del propio escenario, no una respuesta por defecto que lo dejaría pasar.

function sobre(status, log, data) {
  return {status, log: log || [], data: data || {}};
}

class ServidorFalso {
  constructor(rutas) {
    this.rutas = rutas;
    this.llamadas = [];
  }

  fetch(recurso, opciones) {
    const conf = opciones || {};
    const ruta = String(recurso);
    const cuerpo = conf.body ? JSON.parse(conf.body) : null;
    this.llamadas.push({ruta, metodo: conf.method || 'GET', cuerpo,
                        cabeceras: conf.headers || {}});

    const clave = Object.keys(this.rutas)
      .sort((a, b) => b.length - a.length)
      .find(k => ruta === k || ruta.startsWith(k));
    if (!clave) {
      return Promise.reject(new TypeError(`Failed to fetch (ruta no declarada: ${ruta})`));
    }
    let respuesta = this.rutas[clave];
    if (typeof respuesta === 'function') respuesta = respuesta(cuerpo, ruta, conf);
    if (respuesta instanceof Error) return Promise.reject(respuesta);

    const http = respuesta.http || 200;
    const texto = respuesta.texto !== undefined
      ? respuesta.texto : JSON.stringify(respuesta.sobre);
    const cabeceras = respuesta.cabeceras || {};
    const entregar = () => ({
      ok: http >= 200 && http < 300,
      status: http,
      // `headers.get` existe porque el panel negocia el flujo por el
      // `Content-Type` de la respuesta. Devuelve `null` para lo no declarado,
      // igual que `Headers` de verdad.
      headers: {get: n => cabeceras[String(n).toLowerCase()] || null},
      // El cuerpo como flujo, solo cuando el escenario lo declara: un `fetch`
      // sin `body` es lo que ve el panel cuando el servidor contesta JSON de
      // una pieza, y esa rama tiene que seguir funcionando igual.
      body: respuesta.flujo || undefined,
      text: () => Promise.resolve(texto),
    });
    // `espera` retiene la respuesta hasta que el escenario la suelte. Es lo
    // que permite mirar la pantalla **con la petición todavía en vuelo**, que
    // es donde ocurren los defectos de este archivo: un segundo clic que
    // dispara una segunda llamada idéntica, o un log que no aparece hasta el
    // final. Sin esto solo se puede comprobar el estado final, y ahí los dos
    // defectos son invisibles.
    return respuesta.espera ? respuesta.espera.then(entregar)
                            : Promise.resolve(entregar());
  }

  llamadasA(fragmento) {
    return this.llamadas.filter(l => l.ruta.includes(fragmento));
  }
}

// ── Un cuerpo que llega por trozos ───────────────────────────────────────────
//
// El servidor puede mandar el registro de un paso largo según ocurre, en vez de
// entero al terminar. Para probarlo hace falta un cuerpo que el escenario vaya
// soltando a mano: si los trozos estuvieran todos listos de antemano, «llegó
// según ocurría» y «llegó todo junto» serían indistinguibles desde la pantalla.

const TIPO_FLUJO = 'text/event-stream';

class FlujoDeMentira {
  constructor() {
    this.listos = [];      // trozos que ya se soltaron y nadie ha leído
    this.esperando = [];   // lecturas pendientes de que llegue un trozo
  }

  _entregar(trozo) {
    const lectura = this.esperando.shift();
    if (lectura) lectura(trozo); else this.listos.push(trozo);
  }

  /** Un evento con nombre, tal cual lo escribe el servidor. */
  evento(nombre, datos) {
    this._entregar({done: false, value: new TextEncoder().encode(
      `event: ${nombre}\ndata: ${JSON.stringify(datos)}\n\n`)});
  }

  /** Texto crudo, para partir un evento por la mitad o mandar comentarios. */
  crudo(texto) {
    this._entregar({done: false, value: new TextEncoder().encode(texto)});
  }

  /** Se acabó la conexión. Sin evento de fin, es un corte. */
  cortar() { this._entregar({done: true}); }

  get cuerpo() {
    const yo = this;
    return {getReader: () => ({
      read: () => yo.listos.length
        ? Promise.resolve(yo.listos.shift())
        : new Promise(resolver => yo.esperando.push(resolver)),
    })};
  }
}

/** La respuesta con la que el servidor abre un flujo. */
function respuestaEnFlujo(flujo) {
  return {cabeceras: {'content-type': `${TIPO_FLUJO}; charset=utf-8`},
          flujo: flujo.cuerpo, texto: ''};
}

// Respuestas que sirven de base a casi todos los escenarios. Cada uno cambia
// solo lo suyo, para que se vea qué está probando.
function rutasBase(extra) {
  const base = {
    '/health': {sobre: sobre('ok', ['servidor en marcha'], {endpoints: ['/health']})},
    '/discover?project=': {sobre: sobre('ok', ['✓ 1 agentes'], {
      proyectos: [], repo: REPO, rama_principal: 'principal-de-prueba',
      ninguno_vinculado: false,
      agentes: [{agentId: AGENTE, displayName: AGENTE_NOMBRE, region: 'europe-west1',
                 repo: REPO, rama: 'rama-de-prueba', vinculado: true,
                 registrado: true, rama_propuesta: null}],
    })},
    '/discover': {sobre: sobre('ok', ['✓ 2 proyectos GCP'], {
      proyectos: [{projectId: PROYECTO, name: 'Proyecto de prueba'},
                  {projectId: 'floristeria-petal-digital', name: 'Petal'}],
      agentes: [],
    })},
  };
  return Object.assign(base, extra || {});
}

// ── Utilidades del escenario ─────────────────────────────────────────────────

const abiertos = [];

async function abrirPanel(servidor, estadoGuardado) {
  const html = fs.readFileSync(PANEL, 'utf8');
  const dom = new JSDOM(html, {
    url: `${ORIGEN}/panel`,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = (r, o) => servidor.fetch(r, o);
      window.confirm = () => true;
      window.alert = () => {};
      if (estadoGuardado) {
        window.localStorage.setItem('act_panel_cloudrun_v1',
                                    JSON.stringify(estadoGuardado));
      }
    },
  });
  abiertos.push(dom);
  await reposar(dom, 6);
  return dom;
}

/** Cierra las ventanas del escenario, después de dejar que terminen sus
 *  promesas: cerrar con una petición en vuelo mata el proceso al despertar su
 *  temporizador sin documento debajo. */
async function cerrarAbiertos() {
  await new Promise(r => setTimeout(r, 80));
  if (abiertos.length) await reposar(abiertos[abiertos.length - 1], 8);
  while (abiertos.length) {
    const dom = abiertos.pop();
    try { dom.window.close(); } catch (e) { /* ya cerrada */ }
  }
}

/** Deja correr las promesas pendientes. Sin esto se mira la pantalla antes de
 *  que llegue ninguna respuesta, y todo parece vacío por un motivo falso. */
function reposar(dom, vueltas) {
  let p = Promise.resolve();
  for (let i = 0; i < (vueltas || 4); i++) {
    p = p.then(() => new Promise(r => dom.window.setTimeout(r, 0)));
  }
  return p;
}

function texto(dom, id) {
  const e = dom.window.document.getElementById(id);
  return e ? e.textContent.replace(/\s+/g, ' ').trim() : null;
}

function visible(dom, id) {
  const e = dom.window.document.getElementById(id);
  return !!e && e.style.display !== 'none';
}

/** Si un elemento se ve de verdad, subiendo por sus padres.
 *
 *  `visible()` mira el `display` del propio elemento y no vale para preguntar
 *  por un botón: ocultar el bloque que lo contiene lo quita de la pantalla sin
 *  tocarlo, así que su `style.display` sigue vacío y la comprobación diría que
 *  se ofrece cuando no se ofrece. Sin subir por los padres, una prueba sobre
 *  «esta acción ya no está» pasaría con la acción todavía ahí.                */
function visibleDeVerdad(dom, id) {
  let e = dom.window.document.getElementById(id);
  if (!e) return false;
  while (e && e !== dom.window.document.documentElement) {
    if (e.style && e.style.display === 'none') return false;
    e = e.parentElement;
  }
  return true;
}

function pulsar(dom, id) {
  const e = dom.window.document.getElementById(id);
  if (!e) throw new Error(`no existe el elemento ${id}`);
  if (e.disabled) throw new Error(`el botón ${id} está deshabilitado`);
  e.click();
}

// Estado ya recorrido hasta el paso que toque, para no repetir en cada
// escenario los cuatro pasos anteriores.
function estadoHasta(paso, extra) {
  const estados = ['done','done','done','done','done'];
  for (let i = paso - 1; i < 5; i++) estados[i] = i === paso - 1 ? 'gate' : 'pending';
  return Object.assign({
    project: PROYECTO, agentId: AGENTE, agentName: AGENTE_NOMBRE,
    region: 'europe-west1', repo: REPO, rama: 'rama-de-prueba',
    ramaPrincipal: 'principal-de-prueba',
    stepStates: estados, current: paso, viewingStep: paso,
    inventario: {
      project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
      rama: 'rama-de-prueba', commit: 'abc1234567', total_cx: 3,
      total_borrador: 3, versiones: 1, total_archivos: 4,
      tiene_entorno_produccion: true, otros_agentes: 0,
      emparejados: [{tipo:'playbook', cx_id:'p1', display_name:'Uno', ruta:'a.yaml'}],
      solo_cx: [{tipo:'intent', cx_id:'i1', display_name:'Solo en CX',
                 nativo:false, traible:true}],
      solo_repo: [], sin_agente: [],
    },
    eliminar: [], traido: null, plan: null, aplicadas: null,
    paso3Cerrado: false, paso4: null, versionLabel: '', publicacion: null,
    enCurso: null, rutaLocal: '',
  }, extra || {});
}

// ── Los escenarios ───────────────────────────────────────────────────────────

const escenarios = [

/* De quién cuelga cada bloque de pantalla. No es maqueta: cada paso empieza
   escondiendo el bloque de sus mandos, y lo que quede dentro de ese bloque se
   apaga con él. Un bloque que debería sobrevivir a ese gesto —el registro que
   se llena, el resultado, el error que explica el fallo— no puede colgar de lo
   que se esconde.

   Se comprueba el padre y no la visibilidad porque un `</div>` de menos no lo
   ve nadie: el navegador no se queja, la vista se sigue pintando y el
   JavaScript no falla. Solo cambia el árbol, en silencio. Pasó de verdad —un
   cierre perdido al borrar un bloque vecino metió el registro, el resultado y
   el error dentro de los mandos del Paso 1, y pulsar el botón dejaba la
   pantalla en blanco para siempre, sin log, sin error y sin forma de saber por
   qué. Los 35 checks pasaron con el defecto dentro, porque todos preguntaban
   por el `display` propio de cada bloque, que era el correcto.              */
{
  nombre: 'Cada bloque de pantalla cuelga de quien debe: esconder los mandos no esconde la respuesta',
  porQue: 'Si el registro, el resultado o el error cuelgan del bloque que el paso ' +
          'esconde al arrancar, se apagan con él: la pantalla queda en blanco y ' +
          'muda aunque el paso vaya bien y aunque falle.',
  async ejecutar() {
    // id → id del ancestro con id más cercano que le corresponde.
    //
    // El patrón es el mismo en los cuatro pasos: un bloque con los mandos que
    // el paso esconde al arrancar, y a su lado —nunca dentro— el registro, el
    // resultado y el error. En los Pasos 2 y 5 los mandos son `traer-gate` y
    // `prod-gate`, y sus hermanos cuelgan del contenedor de la vista.
    const PADRE_ESPERADO = {
      // Paso 1 — los mandos son `inv-start`.
      'inv-start': 'view-1',
      'inv-log': 'view-1', 'inv-done': 'view-1', 'error-1': 'view-1',
      'btn-start-inventory': 'inv-start',
      'inv-log-block': 'inv-log', 'grupos-inventario': 'inv-done',
      // Paso 2 — los mandos son `traer-gate`, dentro del bloque «hay cambios».
      'traer-gate': 'diff-has-changes',
      'btn-traer': 'traer-gate', 'btn-eliminar': 'traer-gate',
      'traer-log': 'diff-has-changes', 'traer-done': 'diff-has-changes',
      'error-2': 'diff-has-changes',
      'traer-log-block': 'traer-log',
      // Paso 3 — los mandos son `deploy-gate`.
      'deploy-gate': 'view-3', 'btn-confirm-deploy': 'deploy-gate',
      'deploy-log': 'view-3', 'deploy-done': 'view-3',
      'deploy-fail': 'view-3', 'error-3': 'view-3',
      'deploy-log-block': 'deploy-log',
      // Paso 5 — los mandos son `prod-gate`.
      'prod-gate': 'view-5', 'btn-confirm-prod': 'prod-gate',
      'prod-log': 'view-5', 'error-5': 'view-5',
      'prod-log-block': 'prod-log',
    };
    const servidor = new ServidorFalso(rutasBase());
    const dom = await abrirPanel(servidor);
    const mal = [];
    for (const [id, esperado] of Object.entries(PADRE_ESPERADO)) {
      const e = dom.window.document.getElementById(id);
      if (!e) { mal.push(`${id}: no existe`); continue; }
      let p = e.parentElement, real = null;
      while (p) { if (p.id) { real = p.id; break; } p = p.parentElement; }
      if (real !== esperado) mal.push(`${id} cuelga de ${real} y no de ${esperado}`);
    }
    return {ok: mal.length === 0, detalle: mal.length ? mal.join(' · ') : `${Object.keys(PADRE_ESPERADO).length} bloques en su sitio`};
  },
},

{
  nombre: 'Al abrir, el panel pregunta al servidor por su salud y por los proyectos',
  porQue: 'Los desplegables no pueden salir de una lista escrita en el HTML: sin ' +
          'la llamada real, el panel parecería multi-proyecto sirviendo siempre lo mismo.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase());
    const dom = await abrirPanel(servidor);
    const opciones = [...dom.window.document.querySelectorAll('#project-select option')]
      .map(o => o.value).filter(Boolean);
    const salud = servidor.llamadasA('/health').length;
    return {
      ok: salud === 1 && opciones.includes(PROYECTO) && opciones.length === 2,
      detalle: `salud=${salud} opciones=${JSON.stringify(opciones)}`,
    };
  },
},

{
  nombre: 'Elegir proyecto llama al Descubrimiento con ese proyecto y encadena el agente',
  porQue: 'Es la cascada: sin la segunda llamada, el desplegable de agentes se ' +
          'quedaría vacío o mostraría los del proyecto anterior.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase());
    const dom = await abrirPanel(servidor);
    const sel = dom.window.document.getElementById('project-select');
    sel.value = PROYECTO;
    dom.window.onProjectSelected();
    await reposar(dom, 6);
    const agentes = [...dom.window.document.querySelectorAll('#agent-select option')]
      .map(o => o.value).filter(Boolean);
    const conProyecto = servidor.llamadasA(`/discover?project=${PROYECTO}`);
    return {
      ok: conProyecto.length === 1 && agentes.length === 1 && agentes[0] === AGENTE,
      detalle: `llamadas=${conProyecto.length} agentes=${JSON.stringify(agentes)}`,
    };
  },
},

{
  nombre: 'Con el destino guardado, el Descubrimiento de ese proyecto se pide una sola vez',
  porQue: 'Medido contra el servicio real: `/discover?project=…` dos veces en una sola carga, ' +
          '12,8 s y 16,0 s, encoladas una detrás de otra porque el servicio corre con ' +
          '`--concurrency 1`. La primera la encadena la restauración del estado; la segunda la ' +
          'dispara quien vuelve a elegir el proyecto viendo el desplegable de agentes en ' +
          '«cargando…». Las dos devuelven lo mismo, y el desplegable tarda el doble en llenarse.',
  async ejecutar() {
    let soltar;
    const retenida = new Promise(r => { soltar = r; });
    const servidor = new ServidorFalso(rutasBase({
      '/discover?project=': {espera: retenida, sobre: sobre('ok', ['✓ 1 agentes'], {
        proyectos: [], repo: REPO, rama_principal: 'principal-de-prueba',
        ninguno_vinculado: false,
        agentes: [{agentId: AGENTE, displayName: AGENTE_NOMBRE, region: 'europe-west1',
                   repo: REPO, rama: 'rama-de-prueba', vinculado: true,
                   registrado: true, rama_propuesta: null}],
      })},
    }));
    // Estado guardado con el destino ya elegido: es la recarga a mitad de
    // trabajo, el caso normal de este panel.
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    const traslaCarga = servidor.llamadasA('/discover?project=').length;

    // La respuesta sigue sin llegar, y quien mira vuelve a elegir el proyecto.
    const sel = dom.window.document.getElementById('project-select');
    sel.value = PROYECTO;
    dom.window.onProjectSelected();
    await reposar(dom, 4);
    const conUnaEnVuelo = servidor.llamadasA('/discover?project=').length;

    // Llega la respuesta, y se vuelve a elegir lo que ya está en pantalla.
    soltar();
    await reposar(dom, 8);
    dom.window.onProjectSelected();
    await reposar(dom, 6);
    const total = servidor.llamadasA('/discover?project=').length;
    const agentes = [...dom.window.document.querySelectorAll('#agent-select option')]
      .map(o => o.value).filter(Boolean);
    return {
      ok: traslaCarga === 1 && conUnaEnVuelo === 1 && total === 1
          && agentes.length === 1 && agentes[0] === AGENTE,
      detalle: `tras-la-carga=${traslaCarga} con-una-en-vuelo=${conUnaEnVuelo} ` +
               `total=${total} agentes=${JSON.stringify(agentes)}`,
    };
  },
},

{
  nombre: 'Dar de alta un agente sí vuelve a pedir el Descubrimiento: acaba de cambiar',
  porQue: 'No pedir dos veces lo mismo no puede convertirse en no enterarse de lo que cambió. ' +
          'El alta crea la rama del agente, y con la respuesta anterior el desplegable seguiría ' +
          'diciendo «(sin dar de alta)» del agente que se acaba de dar de alta.',
  async ejecutar() {
    let dado = false;
    const agenteDe = () => ({
      agentId: AGENTE, displayName: AGENTE_NOMBRE, region: 'europe-west1', repo: REPO,
      rama: dado ? 'rama-de-prueba' : null, vinculado: true, registrado: dado,
      rama_propuesta: dado ? null : 'agente/propuesta',
    });
    const servidor = new ServidorFalso(rutasBase({
      '/discover?project=': () => ({sobre: sobre('ok', ['✓ 1 agentes'], {
        proyectos: [], repo: REPO, rama_principal: 'principal-de-prueba',
        ninguno_vinculado: false, agentes: [agenteDe()],
      })}),
      '/register-agent': () => { dado = true;
        return {sobre: sobre('ok', ['✓ rama creada'], {rama: 'rama-de-prueba'})}; },
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null, rama: ''}));
    await reposar(dom, 8);
    const antes = servidor.llamadasA('/discover?project=').length;
    pulsar(dom, 'btn-alta-agente');
    await reposar(dom, 12);
    const despues = servidor.llamadasA('/discover?project=').length;
    const opciones = [...dom.window.document.querySelectorAll('#agent-select option')]
      .map(o => o.textContent);
    return {
      ok: antes === 1 && despues === 2
          && !opciones.some(t => t.includes('sin dar de alta')),
      detalle: `antes=${antes} después=${despues} opciones=${JSON.stringify(opciones)}`,
    };
  },
},

{
  nombre: 'Elegir Petal devuelve 403 y el panel lo explica como destino bloqueado, no como avería',
  porQue: 'La lista negra del servidor es una protección funcionando. Un mensaje ' +
          'genérico la convierte en lo que parece un fallo del panel, y se pierde ' +
          'media hora buscando qué se rompió.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/discover?project=floristeria-petal-digital': {http: 403, sobre: sobre(
        'error',
        ['Este servidor no atiende el destino floristeria-petal-digital/—: está ' +
         'en la lista de destinos protegidos mientras se construye y valida el ' +
         'pipeline. No se ha emitido ninguna llamada.'],
        {reason: 'destino_protegido'})},
    }));
    const dom = await abrirPanel(servidor);
    const sel = dom.window.document.getElementById('project-select');
    sel.value = 'floristeria-petal-digital';
    dom.window.onProjectSelected();
    await reposar(dom, 6);
    const caja = dom.window.document.getElementById('error-1');
    const contenido = caja.textContent.toLowerCase();
    const botonIniciar = dom.window.document.getElementById('btn-start-inventory').disabled;
    return {
      ok: visible(dom, 'error-1')
          && contenido.includes('bloquead')
          && contenido.includes('propósito')
          && contenido.includes('no se ha emitido ninguna llamada')
          && botonIniciar === true,
      detalle: `iniciar-deshabilitado=${botonIniciar} texto=${contenido.slice(0, 140)}`,
    };
  },
},

{
  nombre: 'Sin servidor, el mensaje dice a qué dirección se llamó y el paso no queda colgado',
  porQue: 'Con el panel servido desde el propio servicio, el fallo más probable ' +
          'es que el servicio no esté. Un «cargando» eterno o un éxito falso son ' +
          'los dos peores desenlaces posibles.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': new TypeError('Failed to fetch'),
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    // Se mira el párrafo del mensaje, no la caja entera: la caja lleva además
    // un pie con la dirección, y conformarse con él dejaría pasar un mensaje
    // que no dice a dónde llamó — que es justo lo que se está comprobando.
    const parrafo = dom.window.document.querySelector('#error-1 p');
    const mensaje = parrafo ? parrafo.textContent : '';
    const iniciarVisible = visible(dom, 'inv-start');
    const boton = dom.window.document.getElementById('btn-start-inventory');
    return {
      ok: mensaje.includes(`${ORIGEN}/step/1`)
          && /no se pudo conectar/i.test(mensaje)
          && iniciarVisible && boton.disabled === false,
      detalle: `reintentable=${!boton.disabled} mensaje=${mensaje.slice(0, 160)}`,
    };
  },
},

{
  nombre: 'El Paso 1 pinta los números que devuelve el servidor, no unos fijos',
  porQue: 'Si las tarjetas salieran del HTML, el inventario parecería funcionar ' +
          'sin haber leído nunca el agente.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {sobre: sobre('ok', ['✓ Emparejados 7 · solo en CX 3 · solo en el repositorio 2'], {
        project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
        rama: 'rama-de-prueba', commit: 'fedcba9876', total_cx: 10,
        total_borrador: 11, versiones: 4, total_archivos: 12,
        tiene_entorno_produccion: false, otros_agentes: 1,
        emparejados: Array.from({length: 7}, (_, i) => ({tipo:'playbook', cx_id:'e'+i, display_name:'Emparejado '+i, ruta:'e'+i+'.yaml'})),
        solo_cx: Array.from({length: 3}, (_, i) => ({tipo:'intent', cx_id:'c'+i, display_name:'SoloCX '+i, nativo:false, traible:true})),
        solo_repo: Array.from({length: 2}, (_, i) => ({tipo:'example', cx_id:null, display_name:'SoloRepo '+i, ruta:'r'+i+'.yaml', motivo:'sin cx_id'})),
        sin_agente: [{ruta:'huerfano.yaml', tipo:'playbook', display_name:'H', motivo:'sin campo agente'}],
      })},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const numeros = [...dom.window.document.querySelectorAll('#grupos-inventario .grupo-num')]
      .map(e => e.textContent.trim());
    const resumen = texto(dom, 'inv-resumen') || '';
    const avisoEntorno = visible(dom, 'aviso-sin-entorno');
    const cuerpo = servidor.llamadasA('/step/1')[0].cuerpo;
    return {
      ok: JSON.stringify(numeros) === JSON.stringify(['7','3','2','1'])
          && resumen.includes('fedcba9') && avisoEntorno === true
          && cuerpo.project === PROYECTO && cuerpo.agent === AGENTE,
      detalle: `numeros=${numeros} entorno=${avisoEntorno} resumen=${resumen.slice(0,90)}`,
    };
  },
},

{
  nombre: 'Lo que cambió se dice con palabras y con sitio propio, no solo con un color',
  porQue: 'Un resource modificado y uno idéntico caen los dos en «Emparejados». Si la ' +
          'única diferencia fuera el color, quien no lo distingue vería ocho iguales ' +
          'y el cambio no llegaría al Paso 3 con nadie mirándolo. Y la tarjeta se ' +
          'pliega a tres filas: lo que cambió puede ser la séptima, así que el bloque ' +
          'que lo nombra tiene que estar fuera de lo plegado. Ya se perdió una vez en ' +
          'silencio —un argumento de más en la función de la tarjeta— sin que nada avisara.',
  async ejecutar() {
    const emparejados = [
      {tipo:'flow', cx_id:'f1', display_name:'Sin tocar 1'},
      {tipo:'playbook', cx_id:'p9', display_name:'El que cambió'},
      {tipo:'intent', cx_id:'i1', display_name:'Sin tocar 2'},
      {tipo:'example', cx_id:'x1', display_name:'Sin tocar 3'},
    ];
    const monta = async difieren => {
      const servidor = new ServidorFalso(rutasBase({
        '/step/1': {sobre: sobre('ok', ['✓'], {
          project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
          rama: 'rama-de-prueba', commit: 'abc1234', total_cx: 4, total_borrador: 4,
          versiones: 0, total_archivos: 4, tiene_entorno_produccion: true,
          emparejados, solo_cx: [], solo_repo: [], sin_agente: [],
          difieren_del_repositorio: difieren,
        })},
      }));
      const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
      pulsar(dom, 'btn-start-inventory');
      await reposar(dom, 6);
      return dom;
    };

    const dom = await monta([{tipo:'playbook', cx_id:'p9'}]);
    const tarjeta = dom.window.document.querySelector('#grupos-inventario .grupo-card.emp');
    const num = tarjeta.querySelector('.grupo-num').textContent.trim();
    const bloque = dom.window.document.getElementById('bloque-con-cambios');
    const textoBloque = bloque ? bloque.textContent.replace(/\s+/g, ' ').trim() : '';
    const lista = dom.window.document.getElementById('grupo-emp');

    // El número grande cuenta los emparejados ENTEROS —cambiados incluidos—
    // aunque la lista de arriba tenga una fila menos por cada uno.
    const filasArriba = (lista.textContent.match(/·/g) || []).length;

    // Una vez y en un solo sitio: en el apartado propio, no en la lista.
    const vecesEnLaTarjeta = (tarjeta.textContent.match(/El que cambió/g) || []).length;
    const enLaLista = lista.textContent.includes('El que cambió');

    // Ámbar dentro del bloque: el atajo visual sigue estando.
    const ambar = bloque ? [...bloque.querySelectorAll('*')]
      .some(e => /f59e0b|--gate/.test(e.getAttribute('style') || '')) : false;

    // El bloque vive fuera de lo que se pliega: se ve con la tarjeta cerrada.
    const dentroDeLoPlegado = !!(bloque && bloque.closest('.grupo-extra'));

    // Sin ningún cambio: el total sigue, sin paréntesis y sin bloque.
    const limpio = await monta([]);
    const tarjetaLimpia = limpio.window.document.querySelector('#grupos-inventario .grupo-card.emp');
    const numLimpio = tarjetaLimpia.querySelector('.grupo-num').textContent.trim();
    const filasLimpio = (limpio.window.document.getElementById('grupo-emp').textContent.match(/·/g) || []).length;
    const bloqueLimpio = !!limpio.window.document.getElementById('bloque-con-cambios');

    const ok = num === '4 (1 con cambios)' && filasArriba === 3
      && textoBloque.toLowerCase().includes('con cambios')
      && textoBloque.includes('El que cambió')
      && vecesEnLaTarjeta === 1 && enLaLista === false
      && ambar === true && !dentroDeLoPlegado
      && numLimpio === '4' && filasLimpio === 4 && bloqueLimpio === false;
    return {ok, detalle: `num="${num}" filas-arriba=${filasArriba} veces-en-la-tarjeta=${vecesEnLaTarjeta} ` +
      `en-la-lista=${enLaLista} bloque="${textoBloque}" ambar=${ambar} plegado=${dentroDeLoPlegado} · ` +
      `sin-cambios: num="${numLimpio}" filas=${filasLimpio} bloque=${bloqueLimpio}`};
  },
},

{
  nombre: 'El registro del Paso 1 se pinta según llega, no al terminar el paso',
  porQue: 'Un paso de minutos con la pantalla quieta se lee como colgado, y lo que se ' +
          'hace entonces es recargar a mitad de una escritura. El pipeline ya emitía cada ' +
          'línea en el momento; lo que faltaba era traerlas. Se comprueba **con el paso a ' +
          'medias**: mirar el final no distingue «llegó según ocurría» de «llegó todo junto».',
  async ejecutar() {
    const flujo = new FlujoDeMentira();
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': respuestaEnFlujo(flujo),
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 4);
    const pedidoAsi = ((servidor.llamadasA('/step/1')[0] || {}).cabeceras || {}).Accept;

    flujo.evento('log', {linea: '· Leyendo Dialogflow CX'});
    await reposar(dom, 4);
    const conUna = texto(dom, 'inv-log-block') || '';
    const terminadoAntesDeTiempo = visible(dom, 'inv-done');

    flujo.evento('log', {linea: '✓ 10 resources en el borrador'});
    await reposar(dom, 4);
    const conDos = texto(dom, 'inv-log-block') || '';

    flujo.evento('fin', {http: 200, sobre: sobre('ok',
      ['· Leyendo Dialogflow CX', '✓ 10 resources en el borrador'], {
        project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
        rama: 'rama-de-prueba', commit: 'fedcba9876', total_cx: 10,
        total_borrador: 11, versiones: 4, total_archivos: 12,
        tiene_entorno_produccion: true, otros_agentes: 0,
        emparejados: [{tipo:'playbook', cx_id:'e1', display_name:'Uno', ruta:'a.yaml'}],
        solo_cx: [], solo_repo: [], sin_agente: [],
      })});
    flujo.cortar();
    await reposar(dom, 8);
    const numeros = [...dom.window.document.querySelectorAll('#grupos-inventario .grupo-num')]
      .map(e => e.textContent.trim());

    return {
      ok: pedidoAsi === TIPO_FLUJO
          && conUna.includes('Leyendo Dialogflow CX')
          && !conUna.includes('10 resources')
          && !terminadoAntesDeTiempo
          && conDos.includes('10 resources')
          && visible(dom, 'inv-done')
          && JSON.stringify(numeros) === JSON.stringify(['1','0','0','0']),
      detalle: `accept=${pedidoAsi} con-una=${JSON.stringify(conUna.slice(0,60))} ` +
               `terminado-antes=${terminadoAntesDeTiempo} números=${numeros}`,
    };
  },
},

{
  nombre: 'El evento de fin trae el sobre entero, y es de él de donde sale la pantalla',
  porQue: 'El flujo sirve para ver el registro llenarse; la fuente de verdad sigue siendo ' +
          'el sobre. Si la pantalla se compusiera de las líneas sueltas, un flujo al que le ' +
          'falta una llegaría a un resultado distinto del que dice el servidor.',
  async ejecutar() {
    const flujo = new FlujoDeMentira();
    const servidor = new ServidorFalso(rutasBase({'/step/1': respuestaEnFlujo(flujo)}));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 4);
    // Una línea suelta que el sobre final **no** repite: si la pantalla saliera
    // del flujo y no del sobre, se quedaría dentro.
    flujo.evento('log', {linea: '· línea que solo existe en el flujo'});
    // Y un evento partido en dos trozos, que es lo que ocurre de verdad cuando
    // el corte de red cae a mitad de un evento.
    flujo.crudo('event: log\ndata: {"linea": "· partida');
    flujo.crudo(' por la mitad"}\n\n');
    await reposar(dom, 4);
    const partidaLlego = (texto(dom, 'inv-log-block') || '').includes('partida por la mitad');

    flujo.evento('fin', {http: 200, sobre: sobre('ok', ['✓ solo esto dice el sobre'], {
      project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
      rama: 'rama-de-prueba', commit: 'abc1234567', total_cx: 3, total_borrador: 3,
      versiones: 1, total_archivos: 4, tiene_entorno_produccion: true, otros_agentes: 0,
      emparejados: [], solo_cx: [{tipo:'intent', cx_id:'i1', display_name:'X',
                                  nativo:false, traible:true}],
      solo_repo: [], sin_agente: [],
    })});
    flujo.cortar();
    await reposar(dom, 8);
    const registro = texto(dom, 'inv-log-block') || '';
    const numeros = [...dom.window.document.querySelectorAll('#grupos-inventario .grupo-num')]
      .map(e => e.textContent.trim());
    const guardado = JSON.parse(
      dom.window.localStorage.getItem('act_panel_cloudrun_v1') || '{}');
    return {
      ok: partidaLlego
          && registro.includes('solo esto dice el sobre')
          && !registro.includes('solo existe en el flujo')
          && JSON.stringify(numeros) === JSON.stringify(['0','1','0','0'])
          && guardado.inventario && guardado.inventario.total_cx === 3
          && !guardado.enCurso,
      detalle: `partida=${partidaLlego} números=${numeros} ` +
               `registro=${JSON.stringify(registro.slice(0,70))} en-curso=${!!guardado.enCurso}`,
    };
  },
},

{
  nombre: 'Un flujo cortado a mitad no se lee como terminado: se dice que no se sabe',
  porQue: 'Una respuesta de una pieza llega o no llega, y las dos cosas se distinguen ' +
          'solas. Un flujo puede traer la mitad de las líneas y morir, y eso se parece ' +
          'muchísimo a un paso corto que acabó pronto. Sin el evento de fin, dar el paso ' +
          'por bueno significa avanzar el pipeline sobre una escritura que nadie confirmó.',
  async ejecutar() {
    const flujo = new FlujoDeMentira();
    const servidor = new ServidorFalso(rutasBase({'/step/2': respuestaEnFlujo(flujo)}));
    const dom = await abrirPanel(servidor, estadoHasta(2, {
      inventario: Object.assign(estadoHasta(2).inventario, {solo_cx: [
        {tipo:'intent', cx_id:'i1', display_name:'Uno', nativo:false, traible:true},
      ]}),
    }));
    dom.window.viewStep(2);
    await reposar(dom, 4);
    dom.window.marcarTodos('tabla-repo', true);
    await reposar(dom, 2);
    pulsar(dom, 'btn-traer');
    await reposar(dom, 4);
    flujo.evento('log', {linea: '· escribiendo en el repositorio'});
    await reposar(dom, 4);
    // Y aquí se muere la conexión, sin evento de fin.
    flujo.cortar();
    await reposar(dom, 10);

    const caja = (texto(dom, 'error-2') || '').toLowerCase();
    const guardado = JSON.parse(
      dom.window.localStorage.getItem('act_panel_cloudrun_v1') || '{}');

    // Y al recargar, el aviso de operación sin confirmar sigue ahí: es el
    // mismo criterio que cuando la página se cierra a mitad de un paso.
    const servidor2 = new ServidorFalso(rutasBase());
    const dom2 = await abrirPanel(servidor2, guardado);
    const alVolver = (texto(dom2, 'aviso-interrumpido') || '').toLowerCase();

    return {
      ok: visible(dom, 'error-2')
          && caja.includes('no se sabe si se completó')
          && caja.includes('comprueba el estado real')
          && !visible(dom, 'traer-done')
          && guardado.traido === null
          && !!guardado.enCurso && guardado.enCurso.ruta === 'POST /step/2'
          && visible(dom2, 'aviso-interrumpido')
          && alVolver.includes('sin respuesta'),
      detalle: `error=${JSON.stringify(caja.slice(0,90))} en-curso=${JSON.stringify(guardado.enCurso)} ` +
               `traer-done=${visible(dom, 'traer-done')} al-volver=${JSON.stringify(alVolver.slice(0,60))}`,
    };
  },
},

{
  nombre: 'Si el servidor contesta de una pieza aunque se le pida el flujo, el paso va igual',
  porQue: 'El flujo es un canal añadido, no el único. Un servidor que no lo ofrezca —o una ' +
          'versión anterior, o un proxy que lo convierta— tiene que seguir funcionando: si ' +
          'el panel dependiera de él, negociar mal dejaría el pipeline sin camino.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      // Sin `content-type` de flujo y sin cuerpo por trozos: JSON de una pieza,
      // exactamente lo que devolvía el servidor antes de que esto existiera.
      '/step/1': {sobre: sobre('ok', ['✓ Emparejados 2'], {
        project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
        rama: 'rama-de-prueba', commit: 'fedcba9876', total_cx: 5, total_borrador: 5,
        versiones: 2, total_archivos: 6, tiene_entorno_produccion: true, otros_agentes: 0,
        emparejados: [{tipo:'playbook', cx_id:'e1', display_name:'Uno', ruta:'a.yaml'},
                      {tipo:'playbook', cx_id:'e2', display_name:'Dos', ruta:'b.yaml'}],
        solo_cx: [], solo_repo: [], sin_agente: [],
      })},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 8);
    const pedidoAsi = ((servidor.llamadasA('/step/1')[0] || {}).cabeceras || {}).Accept;
    const numeros = [...dom.window.document.querySelectorAll('#grupos-inventario .grupo-num')]
      .map(e => e.textContent.trim());
    const guardado = JSON.parse(
      dom.window.localStorage.getItem('act_panel_cloudrun_v1') || '{}');
    return {
      ok: pedidoAsi === TIPO_FLUJO
          && visible(dom, 'inv-done')
          && JSON.stringify(numeros) === JSON.stringify(['2','0','0','0'])
          && (texto(dom, 'inv-log-block') || '').includes('Emparejados 2')
          && guardado.inventario && guardado.inventario.total_cx === 5
          && !guardado.enCurso,
      detalle: `accept=${pedidoAsi} números=${numeros} done=${visible(dom, 'inv-done')}`,
    };
  },
},

{
  nombre: 'El Paso 1 avisa, con una fila por contenedor, de lo que publicar retiraría de producción',
  porQue: 'Producción puede estar sirviendo algo que el borrador ya no tiene — ' +
          'porque se borró en la consola de CX, donde el pipeline no interviene. ' +
          'El Paso 5 lo retira, y esa es la única pantalla donde eso se puede ' +
          'saber antes de que pase. Un número suelto obligaría a adivinar cuál: ' +
          'la decisión es de cada contenedor, así que va una fila por cada uno.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {sobre: sobre('ok', ['✓ leído'], {
        project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
        rama: 'rama-de-prueba', commit: 'fedcba9876', total_cx: 2,
        total_borrador: 2, versiones: 3, total_archivos: 2,
        tiene_entorno_produccion: true, otros_agentes: 0,
        emparejados: [], solo_cx: [], solo_repo: [], sin_agente: [],
        comparacion_produccion: {
          cambiados: [{tipo:'flow', cx_id:'f1', display_name:'Default Start Flow',
                       motivo:'el borrador difiere de lo que producción sirve'}],
          borrados: [
            {tipo:'playbook', cx_id:'p9', display_name:'Compra'},
            {tipo:'tool', cx_id:'t9', display_name:'Inventario'},
          ],
          iguales: [],
        },
      })},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const visibleAntes = visible(dom, 'aviso-borrados-produccion');
    const filas = dom.window.document
      .querySelectorAll('#lista-borrados-produccion > div').length;
    const contenido = (texto(dom, 'lista-borrados-produccion') || '');
    // Informa, no bloquea: se puede cerrar y seguir. Publicar retira eso de
    // producción, y a veces es exactamente lo que se quiere.
    dom.window.cerrarAvisoBorrados();
    const visibleDespues = visible(dom, 'aviso-borrados-produccion');
    return {
      ok: visibleAntes === true && filas === 2 && visibleDespues === false
          && contenido.includes('Compra') && contenido.includes('Inventario')
          && contenido.includes('Playbook') && contenido.includes('Tool'),
      detalle: `visible=${visibleAntes} filas=${filas} cerrable=${!visibleDespues} ` +
               `texto=${contenido.replace(/\s+/g, ' ').slice(0, 120)}`,
    };
  },
},

{
  nombre: 'El aviso de retirada cuenta el recorrido entero, y dice si el archivo lo va a resucitar',
  porQue: 'Decía una sola cosa: «producción lo sirve, el borrador ya no lo tiene». Se ' +
          'callaba lo único que sorprende — que el archivo puede seguir en el ' +
          'repositorio, y entonces el Paso 3 vuelve a crear el resource en CX con un ' +
          'identificador NUEVO. Quien borra en la consola de CX creyendo que ha ' +
          'borrado se encuentra una pasada después con dos resources donde había uno ' +
          'y un puntero muerto en producción. Pasó de verdad, probándolo. Y va en ' +
          'pasado lo hecho y en futuro lo que falta: un aviso que anuncia como ' +
          'pendiente algo ya ocurrido hace buscar dónde confirmarlo.',
  async ejecutar() {
    const monta = async borrados => {
      const servidor = new ServidorFalso(rutasBase({
        '/step/1': {sobre: sobre('ok', ['✓'], {
          project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
          rama: 'rama-de-prueba', commit: 'fedcba9', total_cx: 1, total_borrador: 1,
          versiones: 1, total_archivos: 1, tiene_entorno_produccion: true,
          emparejados: [], solo_cx: [], solo_repo: [], sin_agente: [],
          comparacion_produccion: {cambiados: [], borrados, iguales: []},
        })},
      }));
      const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
      pulsar(dom, 'btn-start-inventory');
      await reposar(dom, 6);
      return (texto(dom, 'lista-borrados-produccion') || '').replace(/\s+/g, ' ');
    };

    // Con archivo vivo: el Paso 3 lo resucitaría con otro identificador.
    const conArchivo = await monta([{tipo:'playbook', cx_id:'p9',
      display_name:'2_prueba_2', ruta:'definitions/a/playbooks/2_prueba_2.yaml'}]);
    // Sin archivo: el borrado es completo.
    const sinArchivo = await monta([{tipo:'playbook', cx_id:'p9',
      display_name:'2_prueba_2', ruta:null}]);

    const problemas = [];
    // Lo que ya ocurrió, en pasado, en los dos casos.
    for (const [caso, t] of [['con-archivo', conArchivo], ['sin-archivo', sinArchivo]]) {
      if (!/ya no está en el borrador/i.test(t)) problemas.push(`${caso}: no dice lo ya hecho`);
      if (!/Paso 5/.test(t) || !/puntero/i.test(t)) problemas.push(`${caso}: no dice quién lo retira`);
    }
    // La línea que cambia según el archivo — y no debe filtrarse al otro caso.
    if (!/sigue en el repositorio/i.test(conArchivo)) problemas.push('con-archivo: no avisa de que el archivo sigue');
    if (!/2_prueba_2\.yaml/.test(conArchivo)) problemas.push('con-archivo: no nombra el archivo');
    if (!/identificador nuevo/i.test(conArchivo)) problemas.push('con-archivo: no avisa del identificador nuevo');
    if (!/tampoco está en el repositorio/i.test(sinArchivo)) problemas.push('sin-archivo: no dice que el borrado es completo');
    if (/sigue en el repositorio/i.test(sinArchivo)) problemas.push('sin-archivo: dice que el archivo sigue, y no está');

    return {ok: problemas.length === 0,
            detalle: problemas.length ? problemas.join(' · ')
              : `con-archivo="${conArchivo.slice(0, 150)}" | sin-archivo="${sinArchivo.slice(0, 90)}"`};
  },
},

{
  nombre: 'Sin nada borrado, el aviso de retirada no aparece',
  porQue: 'Pasa poco. Un popup que sale siempre se cierra sin leerlo, y el día ' +
          'que dice algo tampoco se lee.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {sobre: sobre('ok', ['✓ leído'], {
        project: PROYECTO, agent_id: AGENTE, region: 'europe-west1', repo: REPO,
        rama: 'rama-de-prueba', commit: 'fedcba9876', total_cx: 2,
        total_borrador: 2, versiones: 3, total_archivos: 2,
        tiene_entorno_produccion: true, otros_agentes: 0,
        emparejados: [], solo_cx: [], solo_repo: [], sin_agente: [],
        comparacion_produccion: {cambiados: [], borrados: [], iguales: []},
      })},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const visibleAviso = visible(dom, 'aviso-borrados-produccion');
    return {ok: visibleAviso === false, detalle: `visible=${visibleAviso}`};
  },
},

{
  nombre: 'Un doble clic en un botón que escribe dispara una sola petición',
  porQue: 'El Paso 2 escribe en el repositorio y el 3 en el agente. Dos peticiones ' +
          'en paralelo chocan con el candado o, peor, aplican dos veces.',
  async ejecutar() {
    let enVuelo;
    const servidor = new ServidorFalso(rutasBase({
      '/step/2': () => ({sobre: sobre('ok', ['✓ a.yaml'], {
        traidos: [{tipo:'intent', cx_id:'i1', ruta:'a.yaml', display_name:'Solo en CX'}],
        commit: 'aaaaaaa', repo: REPO, rama: 'rama-de-prueba'})}),
    }));
    // La respuesta se retrasa a propósito: sin ventana entre el clic y la
    // respuesta, cualquier panel pasaría esta prueba por casualidad.
    const original = servidor.fetch.bind(servidor);
    servidor.fetch = (r, o) => {
      const p = original(r, o);
      return String(r).includes('/step/2')
        ? new Promise(res => setTimeout(() => res(p), 30)).then(x => x) : p;
    };
    const dom = await abrirPanel(servidor, estadoHasta(2));
    dom.window.viewStep(2);
    await reposar(dom, 4);
    const casilla = dom.window.document.querySelector('#tabla-repo tbody input:not(:disabled)');
    casilla.click();
    pulsar(dom, 'btn-traer');
    const boton = dom.window.document.getElementById('btn-traer');
    const deshabilitadoAlInstante = boton.disabled;
    boton.click();   // el segundo clic del doble clic
    await reposar(dom, 12);
    const peticiones = servidor.llamadasA('/step/2').length;
    return {
      ok: peticiones === 1 && deshabilitadoAlInstante,
      detalle: `peticiones=${peticiones} deshabilitado-al-instante=${deshabilitadoAlInstante}`,
    };
  },
},

{
  nombre: 'El Paso 3 pide el plan al servidor en dry-run y no lo inventa',
  porQue: 'El servidor recalcula el diff en fresco (S1). Un panel que propusiera ' +
          'operaciones por su cuenta sería una segunda fuente de verdad.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/3': (cuerpo) => ({sobre: sobre('ok', ['[dry-run] Plan de 2 operaciones:'], {
        dry_run: true,
        operaciones: [
          {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml',
           resource:'Uno', sin_version:false, conflicto:true, result:null},
          {operacion:'POST', tipo:'example', cx_id:null, ruta:'dos.yaml',
           resource:'Dos', sin_version:false, conflicto:false, result:null},
        ],
        avisos_cambio_archivo: [], sin_version: [], conflictos: [],
      })}),
    }));
    const dom = await abrirPanel(servidor, estadoHasta(3));
    dom.window.viewStep(3);
    await reposar(dom, 8);
    const filas = [...dom.window.document.querySelectorAll('#tabla-cx tbody tr')];
    const cuerpo = servidor.llamadasA('/step/3')[0].cuerpo;
    const conConflicto = filas[0] && /conflicto/i.test(filas[0].textContent);
    return {
      ok: filas.length === 2 && cuerpo.dry_run === true
          && cuerpo.project === PROYECTO && cuerpo.agent === AGENTE && conConflicto,
      detalle: `filas=${filas.length} dry_run=${cuerpo && cuerpo.dry_run} conflicto-visible=${conConflicto}`,
    };
  },
},

{
  nombre: 'En el plan, la operación va delante y el archivo enlaza al commit que ese plan leyó',
  porQue: 'La operación es lo que se decide al marcar la casilla, y estaba la última: ' +
          'la ruta del archivo ensanchaba la tabla y la empujaba fuera de la vista, ' +
          'con una leyenda abajo explicando unos distintivos que no se alcanzaban. Y el ' +
          'enlace tiene que ir al commit de ESTE plan, no a la rama ni al del Paso 1: ' +
          'el Paso 2 escribe commits, así que para cuando se mira el plan la rama ya se ' +
          'movió. Un enlace que abre otro contenido del que la tabla describe engaña más ' +
          'que no tener enlace.',
  async ejecutar() {
    const RUTA = 'definitions/agente-de-prueba/playbooks/01_prueba_fake.yaml';
    const COMMIT = 'abc1234def5678';
    const plan = extra => ({sobre: sobre('ok', ['[dry-run]'], Object.assign({
      dry_run: true,
      operaciones: [{operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:RUTA,
                     resource:'01_prueba-fake', sin_version:false, conflicto:false,
                     result:null}],
      avisos_cambio_archivo: [], sin_version: [], conflictos: [],
    }, extra))});

    const monta = async extra => {
      const servidor = new ServidorFalso(rutasBase({'/step/3': () => plan(extra)}));
      const dom = await abrirPanel(servidor, estadoHasta(3));
      dom.window.viewStep(3);
      await reposar(dom, 8);
      return dom;
    };

    // El plan trae su propio commit: el enlace sale de ahí.
    const dom = await monta({repo: REPO, rama: 'rama-de-prueba', commit: COMMIT});
    const doc = dom.window.document;
    const cabeceras = [...doc.querySelectorAll('#tabla-cx thead th')]
      .map(t => t.textContent.trim()).filter(Boolean);
    const celdas = [...doc.querySelectorAll('#tabla-cx tbody tr td')];
    const enlace = doc.querySelector('#tabla-cx tbody a');

    const laOperacionVaPrimero = cabeceras[0] === 'Operación'
      && /Modificar/.test(celdas[1].textContent);   // celdas[0] es la casilla
    const soloElNombre = enlace && enlace.textContent.trim().startsWith('01_prueba_fake.yaml')
      && !enlace.textContent.includes('definitions/');
    const alCommit = enlace &&
      enlace.getAttribute('href') === `https://github.com/${REPO}/blob/${COMMIT}/${RUTA}`;
    const laRutaEnElTooltip = enlace && enlace.getAttribute('title') === RUTA;
    const seAbreFuera = enlace && enlace.getAttribute('target') === '_blank'
      && /noopener/.test(enlace.getAttribute('rel') || '');

    // Sin commit no se inventa una dirección: queda el nombre y su tooltip.
    const sinCommit = await monta({});
    const a2 = sinCommit.window.document.querySelector('#tabla-cx tbody a');
    const codigo = sinCommit.window.document
      .querySelectorAll('#tabla-cx tbody tr td')[4];
    const degradaBien = !a2 && codigo
      && codigo.textContent.trim() === '01_prueba_fake.yaml'
      && codigo.querySelector('[title]').getAttribute('title') === RUTA;

    const ok = laOperacionVaPrimero && soloElNombre && alCommit
      && laRutaEnElTooltip && seAbreFuera && degradaBien;
    return {ok, detalle: `cabeceras=${JSON.stringify(cabeceras)} operación-primero=${laOperacionVaPrimero} ` +
      `solo-el-nombre=${soloElNombre} al-commit=${alCommit} tooltip=${laRutaEnElTooltip} ` +
      `fuera=${seAbreFuera} sin-commit-degrada=${degradaBien}`};
  },
},

{
  nombre: 'Un deploy parcial (HTTP 200 con status "error") se pinta como fallo, nunca como éxito',
  porQue: 'Es el fallo silencioso más caro del contrato: el servidor devuelve el ' +
          'resultado del pipeline tal cual con código 200, así que un panel que ' +
          'mire `response.ok` da por bueno un borrador a medias.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/3': (cuerpo) => cuerpo.dry_run
        ? {sobre: sobre('ok', ['[dry-run]'], {dry_run:true, operaciones:[
            {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml', resource:'Uno', sin_version:false, conflicto:false, result:null},
            {operacion:'POST', tipo:'example', cx_id:'e1', ruta:'dos.yaml', resource:'Dos', sin_version:false, conflicto:false, result:null},
          ], avisos_cambio_archivo:[], sin_version:[], conflictos:[]})}
        : {http: 200, sobre: sobre('error', ['ERROR playbook/Uno: 400 rechazado'], {
            fallo: true, aplicadas: 0,
            operaciones: [
              {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml', resource:'Uno', result:'ERROR', error:'400 rechazado'},
              {operacion:'POST', tipo:'example', cx_id:'e1', ruta:'dos.yaml', resource:'Dos', result:'NO_INTENTADO'},
            ], avisos_cambio_archivo:[], sin_version:[], conflictos:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(3));
    dom.window.viewStep(3);
    await reposar(dom, 8);
    dom.window.document.querySelectorAll('#tabla-cx tbody input').forEach(c => c.click());
    pulsar(dom, 'btn-confirm-deploy');
    await reposar(dom, 8);
    const fallo = visible(dom, 'deploy-fail');
    const exito = visible(dom, 'deploy-done');
    const resumen = texto(dom, 'deploy-fail-summary') || '';
    return {
      ok: fallo === true && exito === false && resumen.includes('1 fallido')
          && resumen.includes('1 no intentado'),
      detalle: `parcial=${fallo} exito=${exito} resumen=${resumen.slice(0,90)}`,
    };
  },
},

{
  nombre: 'El reintento manda solo lo fallido y lo no intentado, nunca lo que ya salió bien',
  porQue: 'Repetir una operación que ya se aplicó la escribe dos veces. El ' +
          'servidor acepta `only_pending` justo para esto.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/3': () => ({sobre: sobre('ok', ['OK PATCH playbook/Dos'], {
        fallo:false, aplicadas:1, operaciones:[
          {operacion:'PATCH', tipo:'playbook', cx_id:'p2', ruta:'dos.yaml', resource:'Dos', result:'OK'},
        ], avisos_cambio_archivo:[], sin_version:[], conflictos:[]})}),
    }));
    const dom = await abrirPanel(servidor, estadoHasta(3, {
      paso3Cerrado: true,
      aplicadas: {fallo: true, aplicadas: 1, operaciones: [
        {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml', resource:'Uno', result:'OK'},
        {operacion:'PATCH', tipo:'playbook', cx_id:'p2', ruta:'dos.yaml', resource:'Dos', result:'ERROR', error:'400'},
        {operacion:'POST', tipo:'example', cx_id:'e1', ruta:'tres.yaml', resource:'Tres', result:'NO_INTENTADO'},
      ]},
    }));
    dom.window.viewStep(3);
    await reposar(dom, 4);
    pulsar(dom, 'btn-retry-failed');
    await reposar(dom, 8);
    const cuerpo = (servidor.llamadasA('/step/3')[0] || {}).cuerpo || {};
    const pendientes = (cuerpo.only_pending || []).map(p => p.cx_id).sort();
    return {
      ok: JSON.stringify(pendientes) === JSON.stringify(['e1','p2']),
      detalle: `only_pending=${JSON.stringify(pendientes)}`,
    };
  },
},

{
  nombre: 'El Paso 4 declara el resultado al servidor y no avanza si dice que no avanza',
  porQue: 'El panel no lanza los tests: registra la declaración. Quien decide si ' +
          'se puede seguir es el servidor, con `avanza`.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/4': (cuerpo) => ({sobre: sobre('ok', [`Tests declarados ${cuerpo.resultado}`], {
        declarado: cuerpo.resultado, huella_borrador: 'abc',
        avanza: cuerpo.resultado === 'superados'})}),
    }));
    const dom = await abrirPanel(servidor, estadoHasta(4));
    dom.window.viewStep(4);
    await reposar(dom, 3);
    pulsar(dom, 'btn-tests-ko');
    await reposar(dom, 6);
    const falloVisible = visible(dom, 'tests-fail');
    const paso5 = dom.window.eval('estado.stepStates[4]');
    const cuerpo = servidor.llamadasA('/step/4')[0].cuerpo;
    return {
      ok: cuerpo.resultado === 'fallidos' && falloVisible && paso5 === 'pending',
      detalle: `declarado=${cuerpo.resultado} aviso=${falloVisible} paso5=${paso5}`,
    };
  },
},

{
  nombre: 'Publicar con status "aborted" muestra el motivo del servidor y no da por publicado',
  porQue: 'También llega con HTTP 200. Es el gate del borrador movido: pintarlo ' +
          'como éxito diría «publicado» sin que nada haya llegado a producción.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/5': {http: 200, sobre: sobre('aborted',
        ['⚠ El borrador ha cambiado desde que se declararon los tests.'],
        {fusionado:false, publicado:false,
         motivo:'el borrador se movió después de declarar los tests',
         huella_ahora:'zzz'})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    dom.window.document.getElementById('version-batch-label').value = 'v-prueba';
    dom.window.validarVersionLabel();
    pulsar(dom, 'btn-confirm-prod');
    await reposar(dom, 8);
    const avisoVisible = visible(dom, 'aviso-draft-movido');
    const motivo = texto(dom, 'aviso-draft-movido-motivo') || '';
    const enDone = visible(dom, 'view-done') &&
      dom.window.document.getElementById('view-done').classList.contains('visible');
    const boton = dom.window.document.getElementById('btn-confirm-prod').disabled;
    return {
      ok: avisoVisible && motivo.includes('se movió') && !enDone && boton === true,
      detalle: `aviso=${avisoVisible} motivo="${motivo}" done=${enDone} boton-bloqueado=${boton}`,
    };
  },
},

{
  nombre: 'Publicar con status "conflict" dice que no se tocó producción',
  porQue: 'Si el merge falla el servidor para antes de crear ninguna versión. ' +
          'Decirlo evita que alguien salga a revertir algo que no ocurrió.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/5': {http: 200, sobre: sobre('conflict',
        ['El merge falló — no se toca producción: conflicto en uno.yaml'],
        {fusionado:false, publicado:false})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    dom.window.document.getElementById('version-batch-label').value = 'v-prueba';
    dom.window.validarVersionLabel();
    pulsar(dom, 'btn-confirm-prod');
    await reposar(dom, 8);
    const mensaje = texto(dom, 'error-5') || '';
    const enDone = dom.window.document.getElementById('view-done').classList.contains('visible');
    return {
      ok: visible(dom, 'error-5') && /no se ha tocado producción/i.test(mensaje) && !enDone,
      detalle: `done=${enDone} mensaje=${mensaje.slice(0,120)}`,
    };
  },
},

{
  nombre: 'Publicar bien pinta las versiones creadas y el aviso de poda que devuelve el servidor',
  porQue: '`poda_pendiente` solo lo devuelve publicar. Si el panel se lo come, ' +
          'nadie se entera de que se cruzó el límite hasta que la API rechace la ' +
          'siguiente versión.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/5': {sobre: sobre('ok', ['✓ Producción sirviendo v-prueba'], {
        fusionado:true, publicado:true, version:'v-prueba',
        versiones_creadas:['proyecto/flows/f1/versions/9'],
        versiones_anteriores:['proyecto/flows/f1/versions/8'],
        repo: REPO, rama_principal:'principal-de-prueba',
        poda_pendiente:[{nombre_padre:'proyecto/flows/f1', tipo:'flow', vivas:21,
                         limite:20, candidatas:['proyecto/flows/f1/versions/1']}],
      })},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    dom.window.document.getElementById('version-batch-label').value = 'v-prueba';
    dom.window.validarVersionLabel();
    pulsar(dom, 'btn-confirm-prod');
    await reposar(dom, 8);
    const enDone = dom.window.document.getElementById('view-done').classList.contains('visible');
    const poda = visible(dom, 'fila-poda-pendiente');
    const total = texto(dom, 'poda-total');
    const versiones = texto(dom, 'done-version-desc') || '';
    return {
      ok: enDone && poda && total === '1' && versiones.includes('versions/9'),
      detalle: `done=${enDone} poda=${poda} total=${total}`,
    };
  },
},

{
  nombre: 'Sin poda pendiente, el aviso no aparece',
  porQue: 'Un aviso que se queda encendido siempre deja de significar nada.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/5': {sobre: sobre('ok', ['✓ Publicado'], {
        fusionado:true, publicado:true, version:'v-prueba',
        versiones_creadas:[], versiones_anteriores:[], repo: REPO,
        rama_principal:'principal-de-prueba', poda_pendiente:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    dom.window.document.getElementById('version-batch-label').value = 'v-prueba';
    dom.window.validarVersionLabel();
    pulsar(dom, 'btn-confirm-prod');
    await reposar(dom, 8);
    const poda = visible(dom, 'fila-poda-pendiente');
    const versiones = texto(dom, 'done-version-desc') || '';
    return {
      ok: poda === false && /no se cre/i.test(versiones),
      detalle: `poda=${poda} texto=${versiones.slice(0,90)}`,
    };
  },
},

{
  nombre: 'El desplegable de versiones lista de verdad, no deja marcar las que sirve un entorno y pinta el aviso de límite',
  porQue: 'Marcar una versión en uso haría creer que se borró: el servidor la ' +
          'rechaza y el panel no lo notaría. Y el contador contra el límite solo ' +
          'llega aquí.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/manage-versions': (cuerpo) => cuerpo.action === 'list'
        ? {sobre: sobre('ok', ['✓ 3 versiones · 1 en uso'], {
            versiones: [
              {name:'p/flows/f1/versions/1', display_name:'uno', creada:'2026-01-01', estado:'SUCCEEDED', en_uso:true},
              {name:'p/flows/f1/versions/2', display_name:'dos', creada:'2026-01-02', estado:'SUCCEEDED', en_uso:false},
              {name:'p/flows/f1/versions/3', display_name:'tres', creada:'2026-01-03', estado:'SUCCEEDED', en_uso:false},
            ],
            contenedores_cerca_del_limite: [
              {nombre_padre:'p/flows/f1', tipo:'flow', vivas:18, limite:20}]})}
        : {sobre: sobre('ok', ['OK borrada dos'], {
            borradas:['p/flows/f1/versions/2'], protegidas:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    pulsar(dom, 'btn-ver-versiones');
    await reposar(dom, 8);
    const casillas = [...dom.window.document.querySelectorAll('.chk-version')];
    const enUsoBloqueada = casillas[0] && casillas[0].disabled === true;
    const limites = visible(dom, 'version-limites');
    const textoLimites = texto(dom, 'version-limites-lista') || '';
    casillas[1].click();
    pulsar(dom, 'btn-borrar-versiones');
    await reposar(dom, 8);
    const borrado = servidor.llamadasA('/manage-versions')
      .find(l => l.cuerpo && l.cuerpo.action === 'delete');
    return {
      ok: casillas.length === 3 && enUsoBloqueada && limites
          && textoLimites.includes('18/20')
          && borrado && JSON.stringify(borrado.cuerpo.version_names) ===
             JSON.stringify(['p/flows/f1/versions/2']),
      detalle: `casillas=${casillas.length} en-uso-bloqueada=${enUsoBloqueada} ` +
               `limites=${limites} borradas=${borrado ? JSON.stringify(borrado.cuerpo.version_names) : 'ninguna'}`,
    };
  },
},

{
  nombre: 'Sin contenedores cerca del límite, ese aviso se oculta',
  porQue: 'Mismo motivo que la poda: un aviso permanente no informa de nada.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/manage-versions': {sobre: sobre('ok', ['✓ 1 versiones · 0 en uso'], {
        versiones: [{name:'p/flows/f1/versions/1', display_name:'uno', creada:'2026-01-01', estado:'SUCCEEDED', en_uso:false}],
        contenedores_cerca_del_limite: []})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(5));
    dom.window.viewStep(5);
    await reposar(dom, 3);
    pulsar(dom, 'btn-ver-versiones');
    await reposar(dom, 8);
    const limites = visible(dom, 'version-limites');
    return {ok: limites === false, detalle: `aviso-limite-visible=${limites}`};
  },
},

{
  nombre: 'Una respuesta sin la forma del sobre no se pinta como éxito',
  porQue: 'Un campo que llega `undefined` y se muestra vacío es indistinguible de ' +
          'un valor legítimo. Si el sobre no viene, hay que decirlo.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {http: 200, texto: JSON.stringify({resultado: 'vale'})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const mensaje = texto(dom, 'error-1') || '';
    const done = visible(dom, 'inv-done');
    return {
      ok: visible(dom, 'error-1') && /forma esperada/i.test(mensaje) && done === false,
      detalle: `done=${done} mensaje=${mensaje.slice(0,120)}`,
    };
  },
},

{
  nombre: 'Una respuesta que no es JSON tampoco se traga en silencio',
  porQue: 'Es lo que devuelve un proxy, una pantalla de login o un 502 de ' +
          'infraestructura: HTML donde se esperaba JSON.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {http: 200, texto: '<!doctype html><title>Inicia sesión</title>'},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const mensaje = texto(dom, 'error-1') || '';
    return {
      ok: visible(dom, 'error-1') && /no es json/i.test(mensaje),
      detalle: mensaje.slice(0, 140),
    };
  },
},

{
  nombre: 'Cada código de error del servidor trae su mensaje propio, no uno genérico',
  porQue: 'El servidor distingue 400, 403, 404, 409, 500 y 504 con un motivo cada ' +
          'uno. Fundirlos en «algo falló» tira justo la información que dice qué hacer.',
  async ejecutar() {
    const casos = [
      {http:400, reason:undefined,                 espera:/no es válida \(400\)/i},
      {http:403, reason:'missing_permission',      espera:/permiso/i},
      {http:404, reason:'sin_registrar',           espera:/dados de alta|alta/i},
      {http:409, reason:'ocupado',                 espera:/candado caduca el 2026-08-10/i},
      {http:500, reason:'sin_credenciales',        espera:/credenciales/i},
      {http:504, reason:'operacion_sin_terminar',  espera:/sigue corriendo|no terminó a tiempo/i},
    ];
    const fallos = [];
    for (const caso of casos) {
      const servidor = new ServidorFalso(rutasBase({
        '/step/1': {http: caso.http, sobre: sobre('error', ['detalle del servidor'],
                                                  caso.reason
                                                  ? Object.assign({reason: caso.reason},
                                                      caso.reason === 'ocupado'
                                                        ? {expires_at: '2026-08-10 12:00:00'} : {})
                                                  : {})},
      }));
      const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
      pulsar(dom, 'btn-start-inventory');
      await reposar(dom, 6);
      const mensaje = texto(dom, 'error-1') || '';
      if (!caso.espera.test(mensaje)) fallos.push(`${caso.http}/${caso.reason}: ${mensaje.slice(0,80)}`);
      }
    return {ok: fallos.length === 0, detalle: fallos.join(' || ') || 'los 6 con mensaje propio'};
  },
},

{
  nombre: 'Los gates de los Pasos 3 y 5 nombran el proyecto y el agente elegidos',
  porQue: 'Son los dos momentos de más consecuencia. Un ejemplo fijo en el texto ' +
          'de confirmación es una aprobación sobre un destino que no es.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/3': {sobre: sobre('ok', ['[dry-run]'], {dry_run:true, operaciones:[],
        avisos_cambio_archivo:[], sin_version:[], conflictos:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(3));
    dom.window.viewStep(3);
    await reposar(dom, 6);
    const gate3 = `${texto(dom,'gate3-project')}/${texto(dom,'gate3-agent')}`;
    dom.window.eval("estado.stepStates = ['done','done','done','done','gate']");
    dom.window.viewStep(5);
    await reposar(dom, 3);
    const gate5 = `${texto(dom,'gate5-project')}/${texto(dom,'gate5-agent')}` +
                  `/${texto(dom,'gate5-rama')}/${texto(dom,'gate5-rama-principal')}`;
    return {
      ok: gate3 === `${PROYECTO}/${AGENTE_NOMBRE}` &&
          gate5 === `${PROYECTO}/${AGENTE_NOMBRE}/rama-de-prueba/principal-de-prueba`,
      detalle: `gate3=${gate3} gate5=${gate5}`,
    };
  },
},

{
  nombre: 'Recargar recupera el estado guardado — paso activo, destino y resultado',
  porQue: 'Una llamada real tarda más que cualquier animación: recargar por ' +
          'costumbre no puede perder el progreso ni, sobre todo, el destino de ' +
          'las llamadas siguientes.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/1': {sobre: sobre('ok', ['✓ Emparejados 1 · solo en CX 1 · solo en el repositorio 0'], {
        project: PROYECTO, agent_id: AGENTE, region:'europe-west1', repo: REPO,
        rama:'rama-de-prueba', commit:'1234567890', total_cx:2, total_borrador:2,
        versiones:0, total_archivos:2, tiene_entorno_produccion:true, otros_agentes:0,
        emparejados:[{tipo:'playbook', cx_id:'p1', display_name:'Uno', ruta:'a.yaml'}],
        solo_cx:[{tipo:'intent', cx_id:'i1', display_name:'Solo', nativo:false, traible:true}],
        solo_repo:[], sin_agente:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(1, {inventario: null}));
    pulsar(dom, 'btn-start-inventory');
    await reposar(dom, 6);
    const guardado = dom.window.localStorage.getItem('act_panel_cloudrun_v1');

    // Segunda carga, con el mismo almacenamiento: es lo que hace un F5.
    const servidor2 = new ServidorFalso(rutasBase());
    const dom2 = await abrirPanel(servidor2, JSON.parse(guardado));
    const numeros = [...dom2.window.document.querySelectorAll('#grupos-inventario .grupo-num')]
      .map(e => e.textContent.trim());
    const destino = `${texto(dom2,'topbar-agent')}`;
    const inicioOculto = !visible(dom2, 'inv-start');
    return {
      ok: JSON.stringify(numeros) === JSON.stringify(['1','1','0','0'])
          && destino === AGENTE_NOMBRE && inicioOculto,
      detalle: `numeros=${numeros} destino=${destino} inicio-oculto=${inicioOculto}`,
    };
  },
},

{
  nombre: 'Una operación que se quedó sin respuesta se avisa al volver, no se da por no ocurrida',
  porQue: 'El servidor pudo terminarla. Repetirla a ciegas escribe dos veces; ' +
          'darla por no ocurrida es exactamente lo que lleva a repetirla.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase());
    const dom = await abrirPanel(servidor, estadoHasta(3, {
      enCurso: {paso: 3, ruta: 'POST /step/3', desde: '2026-08-10T10:00:00Z'},
    }));
    const aviso = texto(dom, 'aviso-interrumpido') || '';
    const visibleAviso = visible(dom, 'aviso-interrumpido');
    return {
      ok: visibleAviso && aviso.includes('Paso 3') && /comprueba el estado real/i.test(aviso),
      detalle: `visible=${visibleAviso} texto=${aviso.slice(0,120)}`,
    };
  },
},

{
  nombre: 'La Tool de vincular manda proyecto, URL y rama principal al servidor',
  porQue: 'Es el único sitio donde el servidor acepta un repositorio de quien ' +
          'llama. Si quedara simulada, el onboarding no existiría.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/link-project-repo': {sobre: sobre('ok', ['✓ Acceso al repositorio'], {
        project: PROYECTO, repo: REPO, rama_principal:'principal-de-prueba',
        ya_estaba:false, comando_iam:'gcloud projects add-iam-policy-binding …'})},
    }));
    const dom = await abrirPanel(servidor);
    dom.window.viewTool('onboarding');
    dom.window.document.getElementById('tool-project-input').value = PROYECTO;
    dom.window.document.getElementById('tool-repo-url-input').value = `https://github.com/${REPO}`;
    dom.window.document.getElementById('tool-rama-input').value = 'principal-de-prueba';
    pulsar(dom, 'btn-tool-onboarding');
    await reposar(dom, 8);
    const llamada = servidor.llamadasA('/link-project-repo')[0];
    const comando = texto(dom, 'tool-comando-iam') || '';
    return {
      ok: !!llamada && llamada.cuerpo.project === PROYECTO
          && llamada.cuerpo.repo_url.includes(REPO)
          && llamada.cuerpo.rama_principal === 'principal-de-prueba'
          && comando.startsWith('gcloud projects add-iam-policy-binding'),
      detalle: `cuerpo=${JSON.stringify(llamada && llamada.cuerpo)} comando=${comando.slice(0,50)}`,
    };
  },
},

{
  nombre: 'El botón de dar de alta un agente llama a su endpoint con el destino elegido',
  porQue: 'Vive dentro del Paso 1 y no parece una acción suelta, pero es el único ' +
          'camino para que un agente entre en el sistema.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/discover?project=': {sobre: sobre('ok', ['✓ 1 agentes'], {
        proyectos: [], repo: REPO, rama_principal:'principal-de-prueba',
        ninguno_vinculado:false,
        agentes: [{agentId: AGENTE, displayName: AGENTE_NOMBRE, region:'europe-west1',
                   repo: REPO, rama: null, vinculado:true, registrado:false,
                   rama_propuesta:'agente/propuesta'}]})},
      '/register-agent': {sobre: sobre('ok', ['✓ Rama creada: agente/propuesta'], {
        project: PROYECTO, agent_id: AGENTE, region:'europe-west1', repo: REPO,
        rama:'agente/propuesta', rama_creada:true, carpeta_raiz:'definitions'})},
    }));
    const dom = await abrirPanel(servidor);
    const sel = dom.window.document.getElementById('project-select');
    sel.value = PROYECTO;
    dom.window.onProjectSelected();
    await reposar(dom, 6);
    dom.window.document.getElementById('agent-select').value = AGENTE;
    dom.window.onAgentSelected();
    await reposar(dom, 3);
    const iniciarBloqueadoSinRama = dom.window.document.getElementById('btn-start-inventory').disabled;
    pulsar(dom, 'btn-alta-agente');
    await reposar(dom, 8);
    const llamada = servidor.llamadasA('/register-agent')[0];
    return {
      ok: iniciarBloqueadoSinRama === true && !!llamada
          && llamada.cuerpo.project === PROYECTO && llamada.cuerpo.agent === AGENTE
          && llamada.cuerpo.rama === 'agente/propuesta',
      detalle: `iniciar-bloqueado-sin-rama=${iniciarBloqueadoSinRama} cuerpo=${JSON.stringify(llamada && llamada.cuerpo)}`,
    };
  },
},

{
  nombre: 'Aplicado el Paso 3, la tabla pasa a ser un resumen: sin casillas y sin «Seleccionar todos»',
  porQue: 'El deploy terminaba diciendo «2 de 2 se aplicaron en CX» y la tabla ' +
          'conservaba las casillas y el «Seleccionar todos», solo deshabilitados. ' +
          'Deshabilitar no basta: una casilla que se ve invita a marcar, y lo que ' +
          'hay debajo ya está escrito en el agente — volver a aplicarlo lo ' +
          'escribiría dos veces. Lo que queda tras escribir es un resumen, no un ' +
          'formulario. Se comprueba también que la cabecera pierde su columna: si ' +
          'se fueran las celdas y no ella, cada fila quedaría corrida un puesto.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/3': (cuerpo) => cuerpo.dry_run
        ? {sobre: sobre('ok', ['[dry-run] Plan de 2 operaciones:'], {dry_run:true, operaciones:[
            {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml', resource:'Uno', sin_version:false, conflicto:false, result:null},
            {operacion:'POST', tipo:'example', cx_id:'e1', ruta:'dos.yaml', resource:'Dos', sin_version:false, conflicto:false, result:null},
          ], avisos_cambio_archivo:[], sin_version:[], conflictos:[]})}
        : {sobre: sobre('ok', ['✓ Deploy completado — 2 resources'], {
            fallo:false, aplicadas:2, operaciones:[
              {operacion:'PATCH', tipo:'playbook', cx_id:'p1', ruta:'uno.yaml', resource:'Uno', result:'OK'},
              {operacion:'POST', tipo:'example', cx_id:'e1', ruta:'dos.yaml', resource:'Dos', result:'OK'},
            ], avisos_cambio_archivo:[], sin_version:[], conflictos:[]})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(3));
    dom.window.viewStep(3);
    await reposar(dom, 8);
    const casillasAntes = dom.window.document
      .querySelectorAll('#tabla-cx tbody input[type=checkbox]').length;
    dom.window.document.querySelectorAll('#tabla-cx tbody input').forEach(c => c.click());
    pulsar(dom, 'btn-confirm-deploy');
    await reposar(dom, 8);

    const casillas = dom.window.document
      .querySelectorAll('#tabla-cx tbody input[type=checkbox]').length;
    const selTodos = visibleDeVerdad(dom, 'sel-todos-cx');
    // Las columnas que quedan a la vista arriba y las celdas de cada fila
    // tienen que ser las mismas: es lo que separa quitar una columna de
    // descuadrar la tabla.
    const columnas = [...dom.window.document.querySelectorAll('#tabla-cx thead th')]
      .filter(th => th.style.display !== 'none').length;
    const filas = [...dom.window.document.querySelectorAll('#tabla-cx tbody tr')];
    const celdas = filas.map(f => f.cells.length);
    // Y sigue siendo el resumen que dice qué se escribió.
    const aplicados = filas.filter(f => /Aplicado/.test(f.textContent)).length;
    const pie = texto(dom, 'pie-cx') || '';
    return {
      ok: casillasAntes === 2 && casillas === 0 && selTodos === false
          && columnas === 4 && JSON.stringify(celdas) === JSON.stringify([4, 4])
          && aplicados === 2 && pie.includes('2 de 2'),
      detalle: `casillas antes=${casillasAntes} después=${casillas} ` +
               `sel-todos=${selTodos} columnas=${columnas} celdas=${JSON.stringify(celdas)} ` +
               `aplicados=${aplicados} pie="${pie.slice(0, 40)}"`,
    };
  },
},

{
  nombre: 'Mientras se confirma un borrado no se ofrece la acción contraria, y al cerrar la confirmación vuelve',
  porQue: 'Al marcar un resource y pulsar «Eliminar de CX» aparecía la ' +
          'confirmación «Apuntar para borrar en el Paso 3» y justo debajo seguía ' +
          '«Traer al repositorio» — lo opuesto de lo que se está confirmando, ' +
          'activo y sobre las mismas filas marcadas. Una confirmación que ofrece ' +
          'al lado lo contrario no confirma nada. Y tiene que volver al cerrarse: ' +
          'un arreglo que dejara el Paso 2 sin sus botones cambiaría un defecto ' +
          'por otro peor.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase());
    const dom = await abrirPanel(servidor, estadoHasta(2));
    dom.window.viewStep(2);
    await reposar(dom, 4);
    const traerAntes = visibleDeVerdad(dom, 'btn-traer');

    dom.window.document.querySelector('#tabla-repo tbody input:not(:disabled)').click();
    pulsar(dom, 'btn-eliminar');
    await reposar(dom, 2);
    const confirmacion = visible(dom, 'confirmar-borrado');
    const traerDurante = visibleDeVerdad(dom, 'btn-traer');
    const listaBorrado = texto(dom, 'lista-borrado') || '';

    dom.window.cancelarEliminarDeCx();
    await reposar(dom, 2);
    const traerTrasCancelar = visibleDeVerdad(dom, 'btn-traer');
    const confirmacionTrasCancelar = visible(dom, 'confirmar-borrado');

    // Y por el otro camino de salida: confirmando. Sigue marcado lo de antes,
    // así que el botón de borrar continúa habilitado.
    pulsar(dom, 'btn-eliminar');
    await reposar(dom, 2);
    dom.window.confirmarEliminarDeCx();
    await reposar(dom, 2);
    const traerTrasConfirmar = visibleDeVerdad(dom, 'btn-traer');
    const apuntados = dom.window.eval('estado.eliminar.length');

    return {
      ok: traerAntes === true && confirmacion === true && traerDurante === false
          && listaBorrado.includes('Solo en CX')
          && traerTrasCancelar === true && confirmacionTrasCancelar === false
          && traerTrasConfirmar === true && apuntados === 1,
      detalle: `traer antes=${traerAntes} durante=${traerDurante} ` +
               `tras-cancelar=${traerTrasCancelar} tras-confirmar=${traerTrasConfirmar} ` +
               `confirmacion=${confirmacion} apuntados=${apuntados}`,
    };
  },
},


{
  nombre: 'El Paso 2 ofrece borrar del repositorio solo los restos, nunca lo que aún no ha subido',
  porQue: 'Borrar en la consola de CX no borraba nada: el archivo sobrevivía y el ' +
          'Paso 3 recreaba el resource con un identificador NUEVO, dejando el ' +
          'puntero viejo muerto en producción. Pasó probándolo. Pero la oferta tiene ' +
          'que ser solo para los restos —cabecera con un cx_id que CX ya no ' +
          'reconoce—: un archivo SIN cx_id es trabajo recién escrito que aún no ha ' +
          'subido, y ofrecer borrarlo sería ofrecer tirarlo. Y la lista se congela al ' +
          'confirmar: releer las casillas dejaría enseñar unas y borrar otras.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/2': {sobre: sobre('ok', ['✗ borrado'], {
        traidos: [], borrados_del_repo: [{tipo:'playbook', cx_id:'muerto-1',
          ruta:'definitions/a/playbooks/viejo.yaml', display_name:'Viejo'}],
        commit:'ccccccc', repo: REPO, rama:'rama-de-prueba'})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(2, {
      inventario: Object.assign(estadoHasta(2).inventario, {solo_cx: [], solo_repo: [
        {tipo:'playbook', cx_id:'muerto-1', display_name:'Viejo',
         ruta:'definitions/a/playbooks/viejo.yaml', motivo:'cx_id fantasma'},
        {tipo:'playbook', cx_id:'muerto-2', display_name:'Otro viejo',
         ruta:'definitions/a/playbooks/otro.yaml', motivo:'cx_id fantasma'},
        {tipo:'example', cx_id:null, display_name:'Recién escrito',
         ruta:'definitions/a/examples/nuevo.yaml', motivo:'sin cx_id'},
      ]}),
    }));
    dom.window.viewStep(2);
    await reposar(dom, 4);
    const doc = dom.window.document;

    const filas = [...doc.querySelectorAll('#tabla-restos tbody tr')];
    const nombres = filas.map(f => f.dataset.nombre);
    const visible = dom.window.getComputedStyle(doc.getElementById('dir-restos')).display !== 'none';
    // El botón no se ofrece hasta que hay algo marcado.
    const apagadoSinMarcar = doc.getElementById('btn-borrar-repo').disabled === true;

    // Se marca el primero y se abre la confirmación.
    filas[0].querySelector('input').checked = true;
    dom.window.actualizarPies();
    const encendido = doc.getElementById('btn-borrar-repo').disabled === false;
    dom.window.pedirBorrarDelRepo();
    await reposar(dom, 2);
    const enLaConfirmacion = (doc.getElementById('lista-borrado-repo').textContent || '');

    // Alguien toca las casillas con el diálogo abierto: la lista congelada manda.
    filas[0].querySelector('input').checked = false;
    filas[1].querySelector('input').checked = true;

    pulsar(dom, 'btn-confirmar-borrado-repo');
    await reposar(dom, 8);
    const cuerpo = (servidor.llamadasA('/step/2')[0] || {}).cuerpo || {};
    const mandados = (cuerpo.borrar_del_repo || []).map(b => b.cx_id);

    const problemas = [];
    if (!visible) problemas.push('el bloque de restos no se ve');
    if (JSON.stringify(nombres) !== JSON.stringify(['Viejo', 'Otro viejo']))
      problemas.push(`filas=${JSON.stringify(nombres)} — debería listar solo los dos fantasma`);
    if (!apagadoSinMarcar) problemas.push('el botón se ofrece sin nada marcado');
    if (!encendido) problemas.push('el botón sigue apagado con una fila marcada');
    if (!/Viejo/.test(enLaConfirmacion)) problemas.push('la confirmación no nombra lo que va a borrar');
    if (JSON.stringify(mandados) !== JSON.stringify(['muerto-1']))
      problemas.push(`se mandó ${JSON.stringify(mandados)} y se había confirmado ["muerto-1"]`);
    if ((cuerpo.traer || []).length) problemas.push('borrar arrastró un traer que nadie pidió');

    return {ok: problemas.length === 0,
            detalle: problemas.length ? problemas.join(' · ')
              : `filas=${JSON.stringify(nombres)} mandados=${JSON.stringify(mandados)} ` +
                `apagado-sin-marcar=${apagadoSinMarcar}`};
  },
},

{
  nombre: 'El Paso 2 manda exactamente lo marcado y no ofrece traer lo nativo de la plataforma',
  porQue: 'Lo nativo no se puede traer: dejar marcarlo produce un error del ' +
          'servidor por algo que el panel ya sabía.',
  async ejecutar() {
    const servidor = new ServidorFalso(rutasBase({
      '/step/2': {sobre: sobre('ok', ['✓ uno.yaml'], {
        traidos:[{tipo:'intent', cx_id:'i1', ruta:'uno.yaml', display_name:'Uno'}],
        commit:'bbbbbbb', repo: REPO, rama:'rama-de-prueba'})},
    }));
    const dom = await abrirPanel(servidor, estadoHasta(2, {
      inventario: Object.assign(estadoHasta(2).inventario, {solo_cx: [
        {tipo:'intent', cx_id:'i1', display_name:'Uno', nativo:false, traible:true},
        {tipo:'tool', cx_id:'t1', display_name:'code-interpreter', nativo:true, traible:false},
      ]}),
    }));
    dom.window.viewStep(2);
    await reposar(dom, 4);
    const casillas = [...dom.window.document.querySelectorAll('#tabla-repo tbody input')];
    const nativaBloqueada = casillas[1] && casillas[1].disabled === true;
    dom.window.document.getElementById('sel-todos-repo').click();
    dom.window.marcarTodos('tabla-repo', true);
    await reposar(dom, 2);
    pulsar(dom, 'btn-traer');
    await reposar(dom, 8);
    const llamada = servidor.llamadasA('/step/2')[0];
    const traer = (llamada.cuerpo.traer || []).map(t => t.cx_id);
    return {
      ok: nativaBloqueada && JSON.stringify(traer) === JSON.stringify(['i1']),
      detalle: `nativa-bloqueada=${nativaBloqueada} traer=${JSON.stringify(traer)}`,
    };
  },
},

];

// ── Ejecución ────────────────────────────────────────────────────────────────

(async () => {
  const resultados = [];
  for (const escenario of escenarios) {
    let resultado;
    try {
      resultado = await escenario.ejecutar();
    } catch (error) {
      resultado = {ok: false, detalle: `${error.name}: ${error.message}`};
    }
    await cerrarAbiertos();
    resultados.push({nombre: escenario.nombre, ok: !!resultado.ok,
                     detalle: resultado.detalle || ''});
    console.error(`  ${resultado.ok ? '✓' : '✗'} ${escenario.nombre}`);
    if (!resultado.ok) console.error(`      ${resultado.detalle}`);
  }
  const fallos = resultados.filter(r => !r.ok);
  console.log(JSON.stringify({
    total: resultados.length, pass: resultados.length - fallos.length,
    fail: fallos.length, resultados,
  }));
  process.exit(fallos.length ? 1 : 0);
})();
