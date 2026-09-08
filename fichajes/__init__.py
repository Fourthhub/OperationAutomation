"""Control horario: vuelca los fichajes del mes anterior a un Excel en OneDrive.

Se ejecuta el dia 1 de cada mes. Descarga de CrossChex todos los marcajes del
mes que acaba de cerrarse, los agrupa en una fila por empleado y dia, y sube el
libro a la carpeta de OneDrive configurada.

Va en esta app y no en otra porque es la unica con functionTimeout de 10
minutos: CrossChex solo admite una peticion cada 15 segundos, asi que un mes
completo (unas 9 paginas) tarda del orden de tres minutos.
"""

import datetime
import logging
import os

import azure.functions as func

from . import crosschex, jornadas, onedrive


def mes_anterior(hoy=None):
    """Primer y ultimo dia del mes anterior, y una etiqueta 'YYYY-MM'."""
    hoy = hoy or datetime.date.today()
    ultimo = hoy.replace(day=1) - datetime.timedelta(days=1)
    primero = ultimo.replace(day=1)
    return primero.isoformat(), ultimo.isoformat(), primero.strftime("%Y-%m")


def main(myTimer: func.TimerRequest) -> None:
    desde, hasta, periodo = mes_anterior()
    logging.info("Fichajes: procesando %s (%s a %s)", periodo, desde, hasta)

    registros = crosschex.descargar(
        os.environ["crosschex_api_key"],
        os.environ["crosschex_api_secret"],
        desde, hasta,
    )
    logging.info("Fichajes: %s marcajes descargados", len(registros))

    filas = jornadas.agrupar(registros)
    resumen = jornadas.resumen(filas)
    a_revisar = [f for f in filas if f["horas"] is None]
    logging.info(
        "Fichajes: %s jornadas, %s completas, %s a revisar",
        len(filas), len(filas) - len(a_revisar), len(a_revisar),
    )
    for depto, d in resumen.items():
        logging.info("Fichajes: %s -> %s h en %s dias", depto, d["horas"], d["dias"])

    contenido = onedrive.construir_libro(filas, resumen, periodo)
    tk = onedrive.token(
        os.environ["graph_tenant_id"],
        os.environ["graph_client_id"],
        os.environ["graph_client_secret"],
    )
    url = onedrive.subir(
        tk,
        os.environ["onedrive_drive_id"],
        os.environ["onedrive_carpeta_id"],
        "Fichajes {}.xlsx".format(periodo),
        contenido,
    )
    logging.info("Fichajes: informe de %s disponible en %s", periodo, url)
