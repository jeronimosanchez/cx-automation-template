#!/usr/bin/env python3
"""
act/validate_html.py — Análisis estático del panel conectado.

Comprueba, leyendo el código fuente, que docs/panels/act_cx_resources_deploy_v1.html
quedó conectado al servidor tras la Fase 7: sin simulaciones residuales y con
llamadas reales a los endpoints correctos.

No arranca el servidor ni hace peticiones — eso ya lo cubren validate_server.py
y el recorrido manual. Aquí se busca lo que un test funcional no ve: una
simulación que sobrevivió y sigue pintando datos de mentira en un paso que
parece funcionar.

Uso:
    python act/validate_html.py
    python act/validate_html.py --panel docs/panels/otro.html
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.validate_pipeline import FAIL, PASS, SKIP, CheckRunner

PANEL = REPO_ROOT / "docs" / "panels" / "act_cx_resources_deploy_v1.html"
ORIGINAL = REPO_ROOT / "docs" / "panels" / "act_cx_resources_deploy.html"

# Arrays y flags del panel simulado. Si alguno sobrevive, ese paso sigue
# pintando datos escritos a mano aunque el resto ya esté conectado.
SIMULACION = (
    "INV_LINES", "CHECK_RESULTS", "DIFF_COUNT", "DEPLOY_COUNT", "TEST_COUNT",
    "DEPLOY_RESOURCES", "ROLLBACK_LINES", "PUSH_SIMULATE_FAIL",
    "DEPLOY_SIMULATE_FAIL", "PRODUCTION_SIMULATE_CONFLICT", "completeAuto",
)

# Funciones que ejecutan un paso. Un setTimeout aquí dentro es animación
# simulada; fuera puede ser legítimo (feedback de un botón, orden de pintado).
FUNCIONES_DE_PASO = (
    "startInventory", "executePush", "renderStep2Checks", "renderStep3Diff",
    "confirmDeploy", "retryFailed", "confirmVersions", "rollbackStaging",
    "ejecutarRollbackStep7", "confirmProduction",
)


def script_de(html):
    return html[html.index("<script>") + 8:html.rindex("</script>")]


def cuerpo_de_funcion(js, nombre):
    patron = re.compile(rf"(async\s+)?function\s+{re.escape(nombre)}\s*\(")
    encontrado = patron.search(js)
    if not encontrado:
        return None
    inicio = encontrado.start()
    # Saltar la lista de parámetros antes de buscar el cuerpo: un parámetro
    # con valor por defecto (extra = {}) trae su propia llave.
    parentesis, pos = 0, encontrado.end() - 1
    while pos < len(js):
        if js[pos] == "(":
            parentesis += 1
        elif js[pos] == ")":
            parentesis -= 1
            if parentesis == 0:
                break
        pos += 1
    profundidad, i = 0, js.index("{", pos)
    for pos in range(i, len(js)):
        if js[pos] == "{":
            profundidad += 1
        elif js[pos] == "}":
            profundidad -= 1
            if profundidad == 0:
                return js[inicio:pos + 1]
    return js[inicio:]


def run_checks(runner, html, js):

    def sin_arrays_de_simulacion():
        vivos = [nombre for nombre in SIMULACION
                 if re.search(rf"^\s*(const|let|var|function)\s+{nombre}\b", js, re.M)]
        return not vivos, (
            f"sobreviven: {vivos}" if vivos
            else f"ninguno de los {len(SIMULACION)} identificadores de simulación")

    def sin_setTimeout_en_los_pasos():
        """Un setTimeout dentro de un paso es la animación que sustituía a la
        espera real de la API. Fuera puede ser legítimo, así que se reporta
        aparte en vez de fallar."""
        culpables = []
        for nombre in FUNCIONES_DE_PASO:
            cuerpo = cuerpo_de_funcion(js, nombre)
            if cuerpo and "setTimeout" in cuerpo:
                culpables.append(nombre)
        return not culpables, (
            f"setTimeout dentro de: {culpables}" if culpables
            else f"ninguna de las {len(FUNCIONES_DE_PASO)} funciones de paso usa setTimeout")

    def sin_datos_de_ejemplo_en_el_html():
        """Los conteos del inventario y las filas del diff se pintan desde la
        respuesta del servidor: si quedan escritos en el HTML, un paso podría
        mostrarlos sin haber llamado a nadie."""
        marcas = []
        if re.search(r'<div class="stat-value">\s*\d+\s*</div>', html):
            marcas.append("stat-value con número fijo")
        cuerpo_diff = re.search(r'<tbody id="diff-rows">(.*?)</tbody>', html, re.S)
        if re.search(r'class="diff-table".*?<tbody>\s*<tr', html, re.S):
            marcas.append("filas escritas en la tabla del diff")
        return not marcas, "; ".join(marcas) or "sin conteos ni filas fijas en el HTML"

    def un_fetch_por_cada_paso():
        """El fetch está centralizado en llamarPaso(); lo que se verifica es
        que exista y que los 8 pasos pasen por él."""
        centralizado = re.search(r"fetch\(\s*`\$\{SERVER\}/step/\$\{[^}]+\}`", js)
        invocados = {int(n) for n in re.findall(r"llamarPaso\(\s*(\d)", js)}
        faltan = sorted(set(range(1, 9)) - invocados)
        return bool(centralizado) and not faltan, (
            f"fetch a /step/<n>: {'sí' if centralizado else 'NO'} · "
            f"pasos invocados: {sorted(invocados)}"
            + (f" · FALTAN {faltan}" if faltan else ""))

    def project_y_agent_en_cada_llamada():
        cuerpo = cuerpo_de_funcion(js, "llamarPaso") or ""
        tiene = "seleccion.project" in cuerpo and "seleccion.agent" in cuerpo
        return tiene, (
            "llamarPaso() manda project y agent en el body" if tiene
            else "el body de llamarPaso() no incluye project y/o agent")

    def selectores_por_fetch():
        proyectos = "'/projects'" in js or '"/projects"' in js
        agentes = re.search(r"/projects/\$\{[^}]+\}/agents", js)
        return bool(proyectos and agentes), (
            f"GET /projects: {'sí' if proyectos else 'NO'} · "
            f"GET /projects/<p>/agents: {'sí' if agentes else 'NO'}")

    def sin_options_hardcodeadas():
        """Una lista de <option> con valores reales haría que el panel
        pareciera multi-agente mostrando siempre lo mismo."""
        markup = html[:html.index("<script>")] + html[html.rindex("</script>"):]
        opciones = re.findall(r'<option value="([^"]+)"', markup)
        con_valor = [o for o in opciones if o.strip()]
        return not con_valor, (
            f"hay <option> con valor fijo: {con_valor}" if con_valor
            else "los <option> con valor se generan por JS")

    def manejo_de_servidor_caido():
        hay_clase = "ServidorCaido" in js
        hay_mensaje = re.search(r"servidor local", js, re.I)
        hay_captura = re.search(r"catch\s*[({]", js)
        return bool(hay_clase and hay_mensaje and hay_captura), (
            f"clase propia: {'sí' if hay_clase else 'NO'} · "
            f"mensaje explícito: {'sí' if hay_mensaje else 'NO'} · "
            f"captura: {'sí' if hay_captura else 'NO'}")

    def respuesta_que_no_es_del_pipeline():
        """El puerto puede estar ocupado por otro programa — en macOS, AirPlay
        responde 403 sin cuerpo. Eso no llega como conexión rechazada."""
        cuerpo = cuerpo_de_funcion(js, "leerJson") or ""
        tiene = bool(cuerpo) and "pipeline" in cuerpo and "ServidorCaido" in cuerpo
        return bool(tiene), (
            "detecta una respuesta que no es JSON del servidor" if tiene
            else "un cuerpo no-JSON daría un SyntaxError crudo")

    def aviso_en_paso_no_idempotente():
        cuerpo = cuerpo_de_funcion(js, "confirmVersions") or ""
        tiene = re.search(r"duplicad", cuerpo, re.I)
        return bool(tiene), (
            "el Paso 5 avisa de que un reintento a ciegas puede duplicar" if tiene
            else "el Paso 5 no distingue su fallo del genérico, y no es idempotente")

    def estado_en_localstorage():
        guarda = "localStorage.setItem" in js
        lee = "localStorage.getItem" in js
        cuerpo = cuerpo_de_funcion(js, "guardarEstado") or ""
        completo = all(x in cuerpo for x in ("stepStates", "project", "agent"))
        return bool(guarda and lee and completo), (
            f"guarda: {guarda} · lee: {lee} · "
            f"incluye stepStates, project y agent: {completo}")

    def restaura_al_arrancar():
        tiene = "cargarEstado()" in js
        aplica = re.search(r"viewStep\(\s*restaurado\s*\?", js)
        return bool(tiene and aplica), (
            "cargarEstado() se llama al arrancar y decide qué paso mostrar" if tiene and aplica
            else f"cargarEstado: {tiene} · se aplica al arrancar: {bool(aplica)}")

    def original_intacto():
        """La Fase 7 trabaja sobre una copia: el panel de specs es la
        documentación de referencia y no se toca."""
        if not ORIGINAL.exists():
            return False, "no existe el panel original"
        contenido = ORIGINAL.read_text()
        tiene_specs = '<aside class="specs-panel' in contenido
        return tiene_specs, (
            "el original conserva su columna de specs" if tiene_specs
            else "al original le falta la columna de specs — ¿se editó por error?")

    runner.check(1, "Sin arrays ni flags de simulación", sin_arrays_de_simulacion)
    runner.check(1, "Sin setTimeout dentro de las funciones de paso", sin_setTimeout_en_los_pasos)
    runner.check(1, "Sin conteos ni filas de ejemplo en el HTML", sin_datos_de_ejemplo_en_el_html)
    runner.check(2, "Un fetch a /step/<n> y los 8 pasos lo usan", un_fetch_por_cada_paso)
    runner.check(2, "project y agent en el body de cada llamada", project_y_agent_en_cada_llamada)
    runner.check(2, "Los 2 selectores llaman a los endpoints reales", selectores_por_fetch)
    runner.check(2, "Sin <option> con valores fijos en el HTML", sin_options_hardcodeadas)
    runner.check(2, "Manejo explícito de servidor caído", manejo_de_servidor_caido)
    runner.check(2, "Detecta una respuesta que no es del pipeline", respuesta_que_no_es_del_pipeline)
    runner.check(2, "El Paso 5 avisa de su falta de idempotencia", aviso_en_paso_no_idempotente)
    runner.check(3, "El estado se guarda en localStorage", estado_en_localstorage)
    runner.check(3, "El estado se restaura al arrancar", restaura_al_arrancar)
    runner.check(3, "El panel original sigue intacto", original_intacto)


def informar_setTimeout_restantes(js, html):
    """Los que quedan fuera de los pasos: se enseñan para que se vean, no
    para fallar. Silenciarlos sería perder la señal el día que uno vuelva."""
    fuera = []
    for encontrado in re.finditer(r"setTimeout", html):
        linea = html[:encontrado.start()].count("\n") + 1
        contexto = html[max(0, encontrado.start() - 60):encontrado.start() + 40]
        fuera.append((linea, " ".join(contexto.split())[-70:]))
    if fuera:
        print(f"\nsetTimeout fuera de las funciones de paso ({len(fuera)}), para revisión:")
        for linea, contexto in fuera:
            print(f"  línea {linea}: …{contexto}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Análisis estático del panel conectado (no arranca el servidor).")
    parser.add_argument("--panel", type=Path, default=PANEL)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.panel.exists():
        print(f"ERROR: no existe {args.panel}", file=sys.stderr)
        return 1

    html = args.panel.read_text()
    js = script_de(html)
    try:
        etiqueta = args.panel.relative_to(REPO_ROOT)
    except ValueError:
        etiqueta = args.panel  # puede analizarse un panel fuera del repo
    print(f"Analizando {etiqueta} ({len(html.splitlines())} líneas)\n")

    runner = CheckRunner()
    run_checks(runner, html, js)
    informar_setTimeout_restantes(js, html)

    counts = runner.summary()
    print(f"\nRESUMEN: {counts[PASS]} PASS · {counts[FAIL]} FAIL · {counts[SKIP]} SKIP")
    if runner.failed:
        print("\nChecks fallidos:")
        for level, name, _, detail in runner.failed:
            print(f"  {name}\n        {detail}")
        return 1
    print("El panel está conectado al servidor, sin simulaciones residuales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
