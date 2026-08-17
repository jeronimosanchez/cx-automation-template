"""
act/tests/test_cache_repositorio_cloudrun.py — No descargar dos veces el mismo commit.

Una vuelta del pipeline llama a `cargar_repositorio` en los pasos 1, 2, 3 y 5:
cuatro descargas del repositorio entero para leer exactamente el mismo contenido.
GitHub cortó con un 429 de `codeload` —su protección antiscraping, que no es la
cuota de la API y no aparece en `/rate_limit`— y el Paso 1 dejó de arrancar.

El contenido de un commit **no cambia nunca**, así que la clave es el SHA. Estos
tests comprueban que se pide una vez, que dos commits distintos siguen siendo dos
descargas, y que el caché no se puede envenenar desde fuera.

Ninguno toca la red: `requests.get` es un doble que cuenta llamadas.
"""

import io
import sys
import tarfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from act.utils import github_app_client_cloudrun as gh


def _tarball(archivos):
    """Un tarball como el que sirve GitHub: todo bajo <owner>-<repo>-<sha>/."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for ruta, contenido in archivos.items():
            info = tarfile.TarInfo(f"org-repo-abc1234/{ruta}")
            info.size = len(contenido)
            tar.addfile(info, io.BytesIO(contenido))
    return buf.getvalue()


class _Respuesta:
    def __init__(self, status_code, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


@pytest.fixture
def cliente(monkeypatch):
    """Un cliente con el token resuelto y un `requests.get` que cuenta llamadas."""
    gh._CACHE_REPO.clear()
    llamadas = []
    cuerpo = _tarball({
        "definitions/a.yaml": b"metadata:\n  tipo: playbook\n",
        "README.md": b"no es yaml\n",
    })

    def get_falso(url, **kwargs):
        llamadas.append(url)
        return _Respuesta(200, cuerpo)

    monkeypatch.setattr(gh.requests, "get", get_falso)
    c = gh.GitHubAppClient.__new__(gh.GitHubAppClient)
    c.repo = "org/repo"
    monkeypatch.setattr(type(c), "_headers", lambda self: {}, raising=False)
    return c, llamadas


# ── Lo que arregla ───────────────────────────────────────────────────────────

def test_el_mismo_commit_se_descarga_una_sola_vez(cliente):
    c, llamadas = cliente
    primera = c.read_repo_files("abc1234")
    segunda = c.read_repo_files("abc1234")
    assert len(llamadas) == 1, f"se descargó {len(llamadas)} veces"
    assert primera == segunda


def test_cuatro_pasos_del_pipeline_una_descarga(cliente):
    """El caso real: pasos 1, 2, 3 y 5 leyendo el mismo commit."""
    c, llamadas = cliente
    for _ in range(4):
        c.read_repo_files("abc1234")
    assert len(llamadas) == 1


def test_solo_los_yaml_entran(cliente):
    c, _ = cliente
    archivos = c.read_repo_files("abc1234")
    assert "definitions/a.yaml" in archivos
    assert "README.md" not in archivos


# ── Lo que NO debe romper ────────────────────────────────────────────────────

def test_otro_commit_es_otra_descarga(cliente):
    """Sin esto el caché serviría contenido viejo, que es peor que no tenerlo."""
    c, llamadas = cliente
    c.read_repo_files("abc1234")
    c.read_repo_files("def5678")
    assert len(llamadas) == 2


def test_otros_sufijos_es_otra_descarga(cliente):
    """La clave incluye el filtro: pedir otros sufijos no puede devolver el filtrado."""
    c, llamadas = cliente
    c.read_repo_files("abc1234")
    c.read_repo_files("abc1234", sufijos=(".md",))
    assert len(llamadas) == 2


def test_tocar_lo_devuelto_no_envenena_el_cache(cliente):
    """Quien recibe el diccionario puede modificarlo: es suyo, no del caché.

    Hay que copiar en las DOS direcciones, y la prueba tiene que tocarlas las
    dos. La primera versión solo modificaba el resultado de la descarga —que no
    es el diccionario guardado— y pasaba igual devolviendo el del caché sin
    copiar. Se vio rompiendo `_cache_get` a propósito: no falló.
    """
    c, _ = cliente
    limpio = b"metadata:\n  tipo: playbook\n"

    # 1 · tocar lo que devuelve la DESCARGA no debe afectar a lo guardado.
    descargado = c.read_repo_files("abc1234")
    descargado["definitions/a.yaml"] = b"MODIFICADO"
    descargado["inventado.yaml"] = b"x"
    assert c.read_repo_files("abc1234")["definitions/a.yaml"] == limpio

    # 2 · ni tocar lo que devuelve el CACHÉ.
    del_cache = c.read_repo_files("abc1234")
    del_cache["definitions/a.yaml"] = b"TAMBIEN MODIFICADO"
    del_cache["otro.yaml"] = b"y"
    tercera = c.read_repo_files("abc1234")
    assert tercera["definitions/a.yaml"] == limpio
    assert "inventado.yaml" not in tercera and "otro.yaml" not in tercera


def test_el_cache_no_crece_sin_limite(cliente):
    """Un contenedor de larga vida no puede acumular un tarball por commit."""
    c, _ = cliente
    for i in range(gh.CACHE_MAX_COMMITS + 3):
        c.read_repo_files(f"commit{i}")
    assert len(gh._CACHE_REPO) <= gh.CACHE_MAX_COMMITS


def test_el_mas_viejo_es_el_que_se_va(cliente):
    c, llamadas = cliente
    for i in range(gh.CACHE_MAX_COMMITS):
        c.read_repo_files(f"commit{i}")
    c.read_repo_files("commit0")          # lo vuelve a poner en la cola
    c.read_repo_files("uno-nuevo")        # expulsa al más antiguo, que ya no es commit0
    antes = len(llamadas)
    c.read_repo_files("commit0")
    assert len(llamadas) == antes, "commit0 debería seguir en el caché"


# ── El 429 ───────────────────────────────────────────────────────────────────

def test_el_429_se_explica_por_lo_que_es(monkeypatch):
    """Decía «no se pudo descargar el repositorio: 429» y el volcado de GitHub.

    Eso manda a buscar el fallo en las credenciales o en el agente, que es donde
    no está: es el límite de descargas de código, se cuenta aparte de la cuota de
    la API y se levanta solo.
    """
    gh._CACHE_REPO.clear()
    monkeypatch.setattr(gh.requests, "get",
                        lambda url, **k: _Respuesta(429, b"", "Too Many Requests"))
    c = gh.GitHubAppClient.__new__(gh.GitHubAppClient)
    c.repo = "org/repo"
    monkeypatch.setattr(type(c), "_headers", lambda self: {}, raising=False)

    with pytest.raises(gh.GitHubError) as error:
        c.read_repo_files("abc1234")
    texto = str(error.value)
    assert error.value.status_code == 429
    assert "no es la cuota de la api" in texto.lower()
    assert "se levanta" in texto.lower()


def test_un_429_no_deja_nada_guardado(monkeypatch):
    """Si se guardara un fallo, el reintento devolvería el fallo para siempre."""
    gh._CACHE_REPO.clear()
    monkeypatch.setattr(gh.requests, "get",
                        lambda url, **k: _Respuesta(429, b"", "Too Many Requests"))
    c = gh.GitHubAppClient.__new__(gh.GitHubAppClient)
    c.repo = "org/repo"
    monkeypatch.setattr(type(c), "_headers", lambda self: {}, raising=False)
    with pytest.raises(gh.GitHubError):
        c.read_repo_files("abc1234")
    assert len(gh._CACHE_REPO) == 0
