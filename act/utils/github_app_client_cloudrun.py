#!/usr/bin/env python3
"""
act/utils/github_app_client_cloudrun.py — Lectura y escritura del repositorio
por la GitHub App.

En el pipeline local las definiciones salían del árbol de git en el disco del
Mac. En el contenedor no hay repositorio ni binario de git, así que todo pasa
por la API: se lee con la Git Trees API y se escribe con la Git Data API.

**Por qué Git Trees y no la Contents API** (S5): la Contents API sobre un
directorio devuelve solo el primer nivel, y `definitions/examples/` tiene
subdirectorios. Los examples anidados desaparecerían a ojos del servidor y el
pull los reescribiría encima.

**Por qué Git Data y no un PUT por archivo** (Fase 4, Nivel 3): un PUT por
archivo no es atómico — si el proceso muere entre el archivo 3 y el 4, el
repositorio queda con un commit a medias. Con Git Data, todo lo que se trae en
una misma pulsación entra en un único commit.

**Por qué el merge es directo y no un pull request** (S6): la GitHub App solo
tiene permiso `Contents: write`. `gh pr merge` necesita permiso de pull
requests, que no está concedido; `POST /repos/{repo}/merges` no.

El token de instalación se guarda en la instancia del cliente, nunca en una
variable de módulo: su vida es la de la petición que lo creó. Un contenedor
reutilizado entre peticiones de dos repositorios distintos no comparte token.
"""

import base64
import io
import os
import tarfile
import time
from datetime import datetime, timezone

import jwt
import requests

from . import cx_client_cloudrun as cx


GITHUB_API = "https://api.github.com"

# GitHub rechaza un JWT con más de 10 minutos de vida. Se pide corto porque
# solo sirve para canjearlo por el token de instalación, en el acto.
JWT_TTL_SECONDS = 540

# Margen antes de la caducidad real. Un token que caduca a mitad de una
# operación larga rompe la operación sin decir por qué.
TOKEN_MARGIN_SECONDS = 300

MODO_ARCHIVO = "100644"


class GitHubError(RuntimeError):
    """La API de GitHub respondió con un estado inesperado."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class TreeTruncated(RuntimeError):
    """El árbol del repositorio no cabe en una sola respuesta.

    GitHub trunca el árbol recursivo por encima de cierto tamaño y lo avisa
    con `truncated: true`. Seguir adelante con un árbol truncado significa
    tratar los archivos que faltan como inexistentes: el diff los propondría
    crear de nuevo y el pull los reescribiría encima.
    """


class GitHubAppClient:
    """Cliente de un repositorio concreto, con la vida de una petición."""

    def __init__(self, repo, app_id=None, secret_project=None, secret_id=None):
        if not repo or "/" not in repo:
            raise ValueError(
                f"El repositorio se declara como 'owner/nombre'. Recibido: {repo!r}"
            )
        self.repo = repo
        self.app_id = app_id or os.environ.get("GITHUB_APP_ID")
        self.secret_project = secret_project or os.environ.get(
            "GITHUB_APP_SECRET_PROJECT"
        )
        self.secret_id = secret_id or os.environ.get(
            "GITHUB_APP_SECRET_ID", "github-app-private-key"
        )
        if not self.app_id:
            raise ValueError(
                "Falta GITHUB_APP_ID — el App ID no se escribe en el código, "
                "llega por variable de entorno."
            )
        if not self.secret_project:
            raise ValueError(
                "Falta GITHUB_APP_SECRET_PROJECT — el proyecto donde vive la "
                "clave privada no se escribe en el código."
            )
        self._token = None
        self._token_expires_at = None

    # ── Auth ─────────────────────────────────────────────────────────────────

    def _private_key(self):
        """Clave privada de la App, leída de Secret Manager en el momento.

        Nunca se guarda en disco ni se registra en ningún log.
        """
        return cx.access_secret(self.secret_project, self.secret_id)

    def _app_jwt(self):
        ahora = int(time.time())
        payload = {
            # 60 s de margen hacia atrás: GitHub rechaza un JWT cuyo `iat` esté
            # en el futuro, y los relojes no van perfectamente sincronizados.
            "iat": ahora - 60,
            "exp": ahora + JWT_TTL_SECONDS,
            "iss": self.app_id,
        }
        return jwt.encode(payload, self._private_key(), algorithm="RS256")

    def _installation_id(self, app_jwt):
        respuesta = requests.get(
            f"{GITHUB_API}/repos/{self.repo}/installation",
            headers={"Authorization": f"Bearer {app_jwt}",
                     "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        if respuesta.status_code == 404:
            raise GitHubError(
                f"La GitHub App no está instalada en {self.repo}. "
                f"Instálala en el repositorio antes de vincularlo.",
                status_code=404,
            )
        if respuesta.status_code != 200:
            raise GitHubError(
                f"No se pudo localizar la instalación de la App en {self.repo}: "
                f"{respuesta.status_code} {respuesta.text[:200]}",
                status_code=respuesta.status_code,
            )
        return respuesta.json()["id"]

    def token(self):
        """Token de instalación, reutilizado mientras siga siendo válido.

        Vive en la instancia, no en el módulo: dos peticiones distintas usan
        dos clientes distintos y nunca comparten token. Dentro de una misma
        petición se reutiliza porque regenerarlo en cada llamada añadiría dos
        viajes a Secret Manager y a GitHub por cada archivo leído.
        """
        ahora = datetime.now(timezone.utc)
        if self._token and self._token_expires_at:
            restante = (self._token_expires_at - ahora).total_seconds()
            if restante > TOKEN_MARGIN_SECONDS:
                return self._token

        app_jwt = self._app_jwt()
        installation_id = self._installation_id(app_jwt)
        respuesta = requests.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}",
                     "Accept": "application/vnd.github+json"},
            timeout=30,
        )
        if respuesta.status_code != 201:
            raise GitHubError(
                f"No se pudo generar el token de instalación: "
                f"{respuesta.status_code} {respuesta.text[:200]}",
                status_code=respuesta.status_code,
            )
        payload = respuesta.json()
        self._token = payload["token"]
        self._token_expires_at = datetime.fromisoformat(
            payload["expires_at"].replace("Z", "+00:00")
        )
        return self._token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method, path, body=None, params=None, esperado=(200,)):
        respuesta = requests.request(
            method, f"{GITHUB_API}{path}", headers=self._headers(),
            json=body, params=params, timeout=60,
        )
        if respuesta.status_code not in esperado:
            raise GitHubError(
                f"{method} {path} devolvió {respuesta.status_code}: "
                f"{respuesta.text[:300]}",
                status_code=respuesta.status_code,
            )
        return respuesta.json() if respuesta.text else {}

    # ── Lectura ──────────────────────────────────────────────────────────────

    def branch_head(self, rama):
        """SHA del commit en la punta de una rama.

        Fija qué es "el repositorio" durante toda la ejecución: sin él, decir
        que algo difiere no significaría nada.
        """
        datos = self._request("GET", f"/repos/{self.repo}/git/ref/heads/{rama}")
        return datos["object"]["sha"]

    def list_tree(self, commit_sha, sufijos=(".yaml", ".yml")):
        """Todos los archivos del repositorio, entrando en cada subcarpeta.

        `recursive=1` es lo que distingue esto de la Contents API. Si GitHub
        trunca la respuesta, se para: un árbol incompleto se lee como archivos
        que no existen, y eso propondría crearlos de nuevo en CX.
        """
        datos = self._request(
            "GET", f"/repos/{self.repo}/git/trees/{commit_sha}",
            params={"recursive": "1"},
        )
        if datos.get("truncated"):
            raise TreeTruncated(
                f"GitHub truncó el árbol de {self.repo}@{commit_sha[:7]}: el "
                f"repositorio tiene demasiados archivos para una sola lectura. "
                f"Hay que leerlo por partes antes de fiarse del inventario."
            )
        return [
            item for item in datos.get("tree", [])
            if item.get("type") == "blob"
            and (not sufijos or item["path"].endswith(sufijos))
        ]

    def read_repo_files(self, ref, sufijos=(".yaml", ".yml")):
        """Todo el contenido del repositorio en **una sola petición**.

        Devuelve {ruta: bytes}. GitHub sirve el árbol completo como tarball, y
        eso sustituye a una lectura por archivo: el pipeline pasaba de leer un
        blob por YAML —158 peticiones en un repositorio con tres agentes— a
        una. Con el repositorio compartido entre los agentes de un proyecto,
        esa cuenta crece con cada agente que se añade, y el límite de la API de
        GitHub (5.000 peticiones/hora por instalación) se alcanzó en un día de
        trabajo real.

        No se filtra por carpeta para descartar archivos ajenos: la estructura
        del repositorio es libre y lo que dice de quién es un archivo es su
        cabecera, no dónde está. Leerlo todo y repartir después es lo único
        que respeta esa regla — y ahora cuesta una petición.
        """
        respuesta = requests.get(
            f"{GITHUB_API}/repos/{self.repo}/tarball/{ref}",
            headers=self._headers(), timeout=120,
        )
        if respuesta.status_code != 200:
            raise GitHubError(
                f"No se pudo descargar el repositorio {self.repo}@{ref}: "
                f"{respuesta.status_code} {respuesta.text[:200]}",
                status_code=respuesta.status_code,
            )

        archivos = {}
        with tarfile.open(fileobj=io.BytesIO(respuesta.content), mode="r:gz") as tar:
            for miembro in tar.getmembers():
                if not miembro.isfile():
                    continue
                # El tarball cuelga todo de una carpeta <owner>-<repo>-<sha>.
                ruta = miembro.name.split("/", 1)[-1]
                if sufijos and not ruta.endswith(sufijos):
                    continue
                extraido = tar.extractfile(miembro)
                if extraido is not None:
                    archivos[ruta] = extraido.read()
        return archivos

    def read_blob(self, sha):
        datos = self._request("GET", f"/repos/{self.repo}/git/blobs/{sha}")
        if datos.get("encoding") != "base64":
            raise GitHubError(
                f"Blob {sha[:7]} con codificación inesperada: {datos.get('encoding')}"
            )
        return base64.b64decode(datos["content"])

    # ── Escritura ────────────────────────────────────────────────────────────

    def commit_files(self, rama, archivos, mensaje):
        """Escribe varios archivos en un único commit, o ninguno.

        `archivos` es {ruta: contenido en texto}. Devuelve el SHA del commit,
        o None si el contenido ya coincidía con lo que había — repetir la
        misma traída sin cambios intermedios no debe producir un segundo
        commit vacío.
        """
        if not archivos:
            return None

        base_sha = self.branch_head(rama)
        commit_base = self._request(
            "GET", f"/repos/{self.repo}/git/commits/{base_sha}"
        )
        tree_base = commit_base["tree"]["sha"]

        entradas = []
        for ruta, contenido in archivos.items():
            blob = self._request(
                "POST", f"/repos/{self.repo}/git/blobs",
                body={"content": contenido, "encoding": "utf-8"},
                esperado=(201,),
            )
            entradas.append({
                "path": ruta, "mode": MODO_ARCHIVO, "type": "blob",
                "sha": blob["sha"],
            })

        arbol = self._request(
            "POST", f"/repos/{self.repo}/git/trees",
            body={"base_tree": tree_base, "tree": entradas},
            esperado=(201,),
        )
        # Un árbol idéntico al de partida significa que ningún archivo cambió.
        # Commitearlo crearía un commit vacío en cada pasada por el paso.
        if arbol["sha"] == tree_base:
            return None

        commit = self._request(
            "POST", f"/repos/{self.repo}/git/commits",
            body={"message": mensaje, "tree": arbol["sha"], "parents": [base_sha]},
            esperado=(201,),
        )
        self._request(
            "PATCH", f"/repos/{self.repo}/git/refs/heads/{rama}",
            body={"sha": commit["sha"]},
        )
        return commit["sha"]

    def merge_branches(self, base, head, mensaje=None):
        """Fusiona `head` en `base` sin pasar por un pull request.

        Devuelve (fusionado, detalle). Un 409 es un conflicto real y se
        distingue de un fallo de permisos o de red: con conflicto no se toca
        producción, que es lo que exige el orden del Paso 5.
        """
        respuesta = requests.post(
            f"{GITHUB_API}/repos/{self.repo}/merges",
            headers=self._headers(),
            json={"base": base, "head": head,
                  "commit_message": mensaje or f"Merge {head} into {base}"},
            timeout=60,
        )
        if respuesta.status_code == 201:
            return True, respuesta.json().get("sha", "")
        if respuesta.status_code == 204:
            # Nada que fusionar: base ya contiene head. Un reintento del Paso 5
            # sobre un commit ya publicado cae aquí, y es un no-op correcto.
            return True, ""
        if respuesta.status_code == 409:
            return False, f"Conflicto al fusionar {head} en {base}: {respuesta.text[:200]}"
        return False, (
            f"El merge de {head} en {base} falló: "
            f"{respuesta.status_code} {respuesta.text[:200]}"
        )
