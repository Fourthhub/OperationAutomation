"""Lectura de fichajes de CrossChex Cloud.

Notas de la API, comprobadas contra la cuenta real y no todas documentadas:

  - Solo existen dos llamadas: authorize.token y attendance.record/getrecord.
    El resto de espacios de nombres responden "undefined method", porque el
    despacho va por nameAction y no por nameSpace.

  - La documentacion dice que per_page admite 100 como maximo. En realidad
    devuelve hasta 200, y si pides mas te da 200 sin avisar. Por eso nunca se
    asume que una pagina traiga todo: se leen pageCount y count.

  - Hay un limite de una peticion cada 15 segundos que la documentacion no
    recoge. Y lo peor: llega como HTTP 200 con el error dentro del cuerpo,
    asi que hay que mirar el contenido, no el codigo de estado.

  - checktime viene etiquetado como +00:00 pero es hora LOCAL. Confirmado con
    operaciones: las entradas se agolpan a las 09:00 y las salidas a las 17:00,
    lo que como hora espanola cuadra y como UTC no. Se lee tal cual, sin
    convertir.

  - checktype es 0 en todos los registros de esta cuenta: los marcajes no
    distinguen entrada de salida. Se deduce por orden.
"""

import datetime
import logging
import time
import uuid

import requests

URL = "https://api.us.crosschexcloud.com/"
ESPERA_ENTRE_PAGINAS = 16   # el limite real es 1 peticion cada 15 s
POR_PAGINA = 200            # maximo real, aunque la documentacion diga 100
TIMEOUT = 60


def _ahora():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _llamar(espacio, accion, payload, token=None):
    cuerpo = {
        "header": {
            "nameSpace": espacio,
            "nameAction": accion,
            "version": "1.0",
            "requestId": str(uuid.uuid4()),
            "timestamp": _ahora(),
        },
        "payload": payload,
    }
    if token:
        cuerpo["authorize"] = {"type": "token", "token": token}

    respuesta = requests.post(URL, json=cuerpo, timeout=TIMEOUT)
    respuesta.raise_for_status()
    datos = respuesta.json()

    # CrossChex devuelve los errores con HTTP 200 y el detalle en el payload:
    # AUTH_ERROR, TOKEN_EXPIRES, MISS_PARAM y el no documentado FREQUENT_REQUEST.
    p = datos.get("payload") or {}
    if "type" in p and "message" in p:
        raise RuntimeError("CrossChex: {} - {}".format(p["type"], p["message"]))
    return datos


def token(api_key, api_secret):
    datos = _llamar("authorize.token", "token", {"api_key": api_key, "api_secret": api_secret})
    return datos["payload"]["token"]


def descargar(api_key, api_secret, desde, hasta):
    """Todos los fichajes entre dos fechas (YYYY-MM-DD), paginando."""
    tk = token(api_key, api_secret)
    registros = []
    pagina = 1

    while True:
        datos = _llamar(
            "attendance.record", "getrecord",
            {
                "begin_time": "{}T00:00:00+00:00".format(desde),
                "end_time": "{}T23:59:59+00:00".format(hasta),
                "order": "asc",
                "page": pagina,
                "per_page": POR_PAGINA,
            },
            tk,
        )
        p = datos["payload"]
        registros += p["list"]
        logging.info("CrossChex: pagina %s de %s, %s registros", pagina, p["pageCount"], len(p["list"]))

        if pagina >= p["pageCount"]:
            break
        pagina += 1
        time.sleep(ESPERA_ENTRE_PAGINAS)

    esperados = p.get("count")
    if esperados is not None and len(registros) != esperados:
        # No se aborta: es mejor un informe con aviso que ningun informe.
        logging.warning("CrossChex dice %s registros y se han bajado %s", esperados, len(registros))

    return registros
