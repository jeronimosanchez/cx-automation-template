#!/usr/bin/env python3
"""
act/utils/firestore_client_cloudrun.py — Estado que tiene que sobrevivir entre
peticiones.

Cloud Run no recuerda nada: no hay disco que persista ni memoria compartida, y
cada llamada puede caer en un contenedor recién arrancado. Todo lo que deba
seguir existiendo entre el Paso 1 y el Paso 5 —o entre un deploy y el
siguiente— vive aquí. Son cuatro cosas, con cuatro vidas distintas:

1. **Mapeo agente → repositorio, rama y región** (S4). Configuración: se
   escribe una vez al vincular y se lee en todos los deploys posteriores. Es
   lo que hace que el panel no tenga selector de repositorio, y lo que evita
   que el servidor acepte un repositorio del cliente (C3).

2. **Candado de concurrencia** (S13/S13b). Vive lo que dura la operación y se
   libera solo, por caducidad. En Firestore y no en memoria del proceso porque
   una instancia de Cloud Run con concurrencia 1 **encola** las peticiones en
   vez de rechazarlas: sin candado explícito, un segundo deploy no rebota —
   espera y se ejecuta con un diff calculado antes de que aterrizara el
   primero. Y caduca por tiempo, no porque el código llegue a liberarlo: un
   contenedor terminado de golpe no ejecuta ningún `finally`.

3. **Log de auditoría** (S12). Dos partes con necesidades distintas: el último
   estado de cada resource, que no crece porque se sobrescribe, y el historial
   de ejecuciones, que sí crece y se poda a las últimas 50 por agente.

4. **`previous_versions`** (S8). A qué versiones apuntaba producción antes de
   la última publicación. Es lo único que hace posible un rollback y no se
   regenera con nada. Se sobrescribe en cada publicación, no se acumula.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

from google.cloud import firestore


# Colecciones. Nombres en singular-plural del dominio, no técnicos: quien abra
# la consola de Firestore tiene que entender qué mira sin un mapa aparte.
COL_AGENTES = "agentes"
COL_CANDADOS = "candados"
COL_VERSIONES_PREVIAS = "versiones_previas"

# La auditoría cuelga del agente en vez de vivir en colecciones planas. No es
# una preferencia de organización: Firestore exige un **índice compuesto** para
# cualquier consulta que combine varios filtros, y una colección plana obligaba
# a filtrar por `project` y `agent_id` en cada lectura. Colgando del agente, la
# consulta ya está acotada por la ruta y solo queda un criterio —ordenar por
# fecha, o filtrar por pendiente— que Firestore resuelve con sus índices
# automáticos. Verificado contra Firestore real: la versión plana fallaba con
# FAILED_PRECONDITION pidiendo crear el índice a mano.
SUB_EJECUCIONES = "ejecuciones"
SUB_RESOURCES = "resources"

# El servicio de Cloud Run tiene 60 minutos de timeout máximo, así que ninguna
# operación legítima puede seguir viva pasado ese tiempo. Un candado que sigue
# tomado después es de un contenedor muerto, no de un deploy en curso.
LOCK_TTL_SECONDS = 3900

# Cuántas ejecuciones se conservan por agente. Acota el historial sin depender
# de que pase el tiempo, y un problema que se investiga es casi siempre de los
# últimos deploys.
HISTORIAL_MAX_EJECUCIONES = 50

CAMPOS_OBLIGATORIOS_AGENTE = ("project", "agent_id", "region", "repo", "rama")


class LockBusy(RuntimeError):
    """Otro proceso tiene el candado de este agente."""

    def __init__(self, message, holder=None, expires_at=None):
        super().__init__(message)
        self.holder = holder
        self.expires_at = expires_at


class MappingNotFound(RuntimeError):
    """Ese agente no tiene repositorio vinculado."""


class MappingIncomplete(RuntimeError):
    """El documento del agente existe pero le faltan campos obligatorios.

    Se distingue de MappingNotFound porque la salida es distinta: uno se
    resuelve vinculando el agente, el otro reparando un documento a medias.
    Continuar con un campo ausente como None implícito es exactamente el tipo
    de fallo que no se nota hasta que ya causó daño.
    """


def _now():
    return datetime.now(timezone.utc)


def get_client(firestore_project=None):
    """Cliente de Firestore del proyecto del propio servidor.

    Es el proyecto donde corre el servicio, no el proyecto CX del agente que
    se está desplegando. Sale de la variable de entorno o, si no está, del
    proyecto por defecto de las credenciales — nunca de una constante escrita
    en el código.
    """
    project = firestore_project or os.environ.get("FIRESTORE_PROJECT")
    return firestore.Client(project=project) if project else firestore.Client()


def _doc_id(project, agent_id):
    """Clave de agente.

    Lleva el proyecto además del agente porque un `agent_id` solo es único
    dentro de su proyecto.
    """
    return f"{project}__{agent_id}"


# ── 1. Mapeo agente → repositorio ────────────────────────────────────────────

def save_agent_mapping(client, project, agent_id, region, repo, rama,
                       rama_principal="main"):
    """Vincula un agente con su repositorio. Se llama una vez, al hacer onboarding."""
    if not all([project, agent_id, region, repo, rama]):
        raise ValueError(
            "El mapeo exige project, agent_id, region, repo y rama — "
            "ninguno admite valor por defecto."
        )
    documento = {
        "project": project,
        "agent_id": agent_id,
        "region": region,
        "repo": repo,
        "rama": rama,
        "rama_principal": rama_principal,
        "vinculado_en": _now(),
    }
    client.collection(COL_AGENTES).document(_doc_id(project, agent_id)).set(documento)
    return documento


def get_agent_mapping(client, project, agent_id):
    """Repositorio, rama y región de un agente.

    La región sale de aquí y no de una constante: es lo que permite que el
    pipeline opere sobre agentes de cualquier región (S4).
    """
    snapshot = (client.collection(COL_AGENTES)
                .document(_doc_id(project, agent_id)).get())
    if not snapshot.exists:
        raise MappingNotFound(
            f"El agente {agent_id} del proyecto {project} no tiene repositorio "
            f"vinculado. Usa la herramienta de vincular agente y repositorio."
        )
    documento = snapshot.to_dict()
    faltan = [c for c in CAMPOS_OBLIGATORIOS_AGENTE if not documento.get(c)]
    if faltan:
        raise MappingIncomplete(
            f"El documento del agente {agent_id} está incompleto — faltan: "
            f"{', '.join(faltan)}. Vuelve a vincular el agente."
        )
    return documento


def list_agent_mappings(client, project=None):
    """Los agentes vinculados, opcionalmente los de un solo proyecto.

    El descubrimiento lo usa para decir, agente por agente, cuál tiene
    repositorio y cuál no — nunca para omitir los que no lo tienen.
    """
    coleccion = client.collection(COL_AGENTES)
    consulta = (
        coleccion.where(filter=firestore.FieldFilter("project", "==", project))
        if project else coleccion
    )
    return [snapshot.to_dict() for snapshot in consulta.stream()]


# ── 2. Candado de concurrencia ───────────────────────────────────────────────

def acquire_lock(client, project, agent_id, motivo, ttl_seconds=LOCK_TTL_SECONDS):
    """Toma el candado del agente, o falla si otro lo tiene.

    La comprobación y la escritura van dentro de una transacción: sin ella,
    dos peticiones podrían leer "libre" a la vez y las dos creerse dueñas.
    Devuelve un token que hace falta para soltarlo — así una petición no puede
    liberar el candado de otra.
    """
    referencia = client.collection(COL_CANDADOS).document(_doc_id(project, agent_id))
    token = uuid.uuid4().hex
    ahora = _now()

    @firestore.transactional
    def _tomar(transaction):
        snapshot = referencia.get(transaction=transaction)
        if snapshot.exists:
            actual = snapshot.to_dict()
            caduca = actual.get("expires_at")
            if caduca and caduca > ahora:
                raise LockBusy(
                    f"Ya hay una operación en curso sobre {agent_id}: "
                    f"{actual.get('motivo', 'sin motivo declarado')}. "
                    f"Caduca a las {caduca.isoformat()}.",
                    holder=actual.get("token"),
                    expires_at=caduca,
                )
        transaction.set(referencia, {
            "project": project,
            "agent_id": agent_id,
            "token": token,
            "motivo": motivo,
            "taken_at": ahora,
            "expires_at": ahora + timedelta(seconds=ttl_seconds),
        })
        return token

    return _tomar(client.transaction())


def release_lock(client, project, agent_id, token):
    """Suelta el candado, solo si el token coincide.

    Si no coincide, no borra nada: significaría que el candado ya caducó y lo
    tomó otra petición, y borrarlo dejaría a esa otra sin protección.
    """
    referencia = client.collection(COL_CANDADOS).document(_doc_id(project, agent_id))

    @firestore.transactional
    def _soltar(transaction):
        snapshot = referencia.get(transaction=transaction)
        if not snapshot.exists:
            return False
        if snapshot.to_dict().get("token") != token:
            return False
        transaction.delete(referencia)
        return True

    return _soltar(client.transaction())


class agent_lock:
    """Candado como contexto, para que ningún camino de código se olvide de soltarlo.

    El `finally` no es la garantía —un contenedor terminado de golpe no lo
    ejecuta— sino la vía rápida: la garantía real es la caducidad.
    """

    def __init__(self, client, project, agent_id, motivo,
                 ttl_seconds=LOCK_TTL_SECONDS):
        self.client = client
        self.project = project
        self.agent_id = agent_id
        self.motivo = motivo
        self.ttl_seconds = ttl_seconds
        self.token = None

    def __enter__(self):
        self.token = acquire_lock(
            self.client, self.project, self.agent_id, self.motivo, self.ttl_seconds
        )
        return self.token

    def __exit__(self, exc_type, exc, traceback):
        if self.token:
            release_lock(self.client, self.project, self.agent_id, self.token)
        return False


# ── 3. Log de auditoría ──────────────────────────────────────────────────────

def _resource_doc_id(tipo, cx_id):
    """Clave de resource dentro de la subcolección de su agente.

    Lleva el tipo además del `cx_id` porque un `cx_id` solo es único dentro de
    su tipo: verificado con caso real — el Playbook orquestador de Petal y el
    Intent "Default Welcome Intent" comparten el ID
    00000000-0000-0000-0000-000000000000.
    """
    return f"{tipo}__{cx_id}"


def _sub(client, project, agent_id, subcoleccion):
    return (client.collection(COL_AGENTES)
            .document(_doc_id(project, agent_id))
            .collection(subcoleccion))


def record_resource_write(client, project, agent_id, tipo, cx_id, archivo,
                          display_name=None, operacion=None):
    """Deja constancia de qué archivo del repo escribió este resource.

    Se sobrescribe: solo interesa el último estado, así que esta parte no
    crece con el uso. Es lo que permite avisar si un `cx_id` cambia de archivo
    entre deploys (§12), síntoma de un YAML copiado de otro repo sin vaciar.

    `pendiente_publicar` marca lo que se escribió en el borrador y todavía no
    ha llegado a producción. Es lo que permite que el Paso 5 versione solo lo
    que el diff tocó en vez del agente entero (H4): sin esta marca, la única
    alternativa sería versionar todo y el tiempo del paso crecería con el
    tamaño del agente en vez de con el del cambio.
    """
    _sub(client, project, agent_id, SUB_RESOURCES).document(
        _resource_doc_id(tipo, cx_id)
    ).set({
        "tipo": tipo,
        "cx_id": cx_id,
        "archivo": archivo,
        "display_name": display_name,
        "operacion": operacion,
        "escrito_en": _now(),
        "pendiente_publicar": True,
    })


def get_resource_record(client, project, agent_id, tipo, cx_id):
    snapshot = _sub(client, project, agent_id, SUB_RESOURCES).document(
        _resource_doc_id(tipo, cx_id)
    ).get()
    return snapshot.to_dict() if snapshot.exists else None


def list_pending_publication(client, project, agent_id):
    """Resources escritos en el borrador que aún no se han publicado."""
    return [
        snapshot.to_dict() for snapshot in
        _sub(client, project, agent_id, SUB_RESOURCES)
        .where(filter=firestore.FieldFilter("pendiente_publicar", "==", True))
        .stream()
    ]


def mark_published(client, project, agent_id, resources):
    """Quita la marca de pendiente a los resources que ya llegaron a producción.

    Se llama al final del Paso 5, después de apuntar el entorno. Si el paso
    falla antes, la marca se queda y el reintento vuelve a considerarlos.
    """
    for resource in resources:
        _sub(client, project, agent_id, SUB_RESOURCES).document(
            _resource_doc_id(resource["tipo"], resource["cx_id"])
        ).update({"pendiente_publicar": False, "publicado_en": _now()})


def record_run(client, project, agent_id, paso, status, log, data=None,
               max_ejecuciones=HISTORIAL_MAX_EJECUCIONES):
    """Guarda una ejecución y poda el historial del agente.

    Es el único rastro forense de lo que se escribió: en el pipeline local
    esto iba a disco, y el disco de Cloud Run desaparece con el contenedor.

    **Nunca propaga un fallo.** Anotar lo que pasó es contabilidad, no la
    operación: si la anotación falla, la escritura en CX o en el repositorio
    ya ocurrió igual. Dejar que reventara aquí convertiría una operación
    correcta en un error de cara a quien lo usa, y le empujaría a reintentar
    algo que ya está hecho. Verificado en vivo: un índice ausente de Firestore
    hizo fallar un `pull` que había escrito sus 4 archivos y su commit.
    """
    try:
        _sub(client, project, agent_id, SUB_EJECUCIONES).add({
            "paso": paso,
            "status": status,
            "log": log,
            "data": data or {},
            "ejecutado_en": _now(),
        })
        _podar_historial(client, project, agent_id, max_ejecuciones)
        return True
    except Exception as error:
        print(f"[auditoría] No se pudo registrar la ejecución del paso {paso} "
              f"de {agent_id}: {error}")
        return False


def _podar_historial(client, project, agent_id, max_ejecuciones):
    entradas = list(
        _sub(client, project, agent_id, SUB_EJECUCIONES)
        .order_by("ejecutado_en", direction=firestore.Query.DESCENDING)
        .offset(max_ejecuciones)
        .stream()
    )
    for entrada in entradas:
        entrada.reference.delete()


def list_runs(client, project, agent_id, limite=HISTORIAL_MAX_EJECUCIONES):
    return [
        snapshot.to_dict() for snapshot in
        _sub(client, project, agent_id, SUB_EJECUCIONES)
        .order_by("ejecutado_en", direction=firestore.Query.DESCENDING)
        .limit(limite)
        .stream()
    ]


# ── 4. previous_versions ─────────────────────────────────────────────────────

def save_previous_versions(client, project, agent_id, version_names, entorno):
    """A qué versiones apuntaba un entorno antes de la última publicación.

    Se sobrescribe en cada publicación: solo hace falta la anterior, no todas.
    """
    client.collection(COL_VERSIONES_PREVIAS).document(
        _doc_id(project, agent_id)
    ).set({
        "project": project,
        "agent_id": agent_id,
        "entorno": entorno,
        "version_names": list(version_names),
        "guardado_en": _now(),
    })


def get_previous_versions(client, project, agent_id):
    snapshot = client.collection(COL_VERSIONES_PREVIAS).document(
        _doc_id(project, agent_id)
    ).get()
    return snapshot.to_dict() if snapshot.exists else None
