"""Control horario: un Excel por empleado, con una hoja por mes, en OneDrive.

Se ejecuta el dia 1 de cada mes. Descarga de CrossChex los marcajes del mes que
acaba de cerrarse, los agrupa en una fila por empleado y dia, y a cada empleado
le anade la hoja de ese mes a su propio fichero.

El sueldo por hora se escribe a mano una sola vez, en la hoja Ficha de cada
persona, y todas sus hojas mensuales lo referencian. Por eso el fichero se
descarga antes de tocarlo en vez de generarse de cero: hay que conservar lo que
haya escrito una persona.

Va en esta app y no en otra porque es la unica con functionTimeout de 10
minutos: CrossChex solo admite una peticion cada 15 segundos, asi que un mes
completo son unas 9 paginas y del orden de dos minutos y medio.
"""

import collections
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


def por_persona(filas):
    """{(workno, empleado): [filas]} ordenado por nombre y fecha."""
    gente = collections.OrderedDict()
    for f in sorted(filas, key=lambda x: (x["empleado"].lower(), x["fecha"])):
        gente.setdefault((f["workno"], f["empleado"]), []).append(f)
    return gente


def main(myTimer: func.TimerRequest) -> None:
    desde, hasta, periodo = mes_anterior()
    logging.info("Fichajes: procesando %s (%s a %s)", periodo, desde, hasta)

    registros = crosschex.descargar(
        os.environ["crosschex_api_key"],
        os.environ["crosschex_api_secret"],
        desde, hasta,
    )
    filas = jornadas.agrupar(registros)
    gente = por_persona(filas)
    a_revisar = sum(1 for f in filas if f["horas"] is None)
    logging.info("Fichajes: %s marcajes, %s jornadas de %s empleados, %s a revisar",
                 len(registros), len(filas), len(gente), a_revisar)

    tk = onedrive.token(
        os.environ["graph_tenant_id"],
        os.environ["graph_client_id"],
        os.environ["graph_client_secret"],
    )
    drive_id = os.environ["onedrive_drive_id"]
    carpeta_id = os.environ["onedrive_carpeta_id"]

    nuevos, actualizados, fallidos = 0, 0, []
    for (workno, empleado), suyas in gente.items():
        nombre = onedrive.nombre_de_fichero(empleado, workno)
        try:
            # Cada empleado se aisla del resto: si uno tiene su fichero abierto
            # en Excel, no puede tumbar los otros 48.
            existente = onedrive.descargar(tk, drive_id, carpeta_id, nombre)
            contenido = onedrive.actualizar_libro(existente, periodo, suyas)
            onedrive.subir(tk, drive_id, carpeta_id, nombre, contenido)
            if existente:
                actualizados += 1
            else:
                nuevos += 1
        except Exception as e:
            logging.error("Fichajes: fallo con %s: %s", nombre, e)
            fallidos.append(nombre)

    logging.info("Fichajes: %s ficheros nuevos, %s actualizados, %s con fallo",
                 nuevos, actualizados, len(fallidos))
    if fallidos:
        raise RuntimeError("No se pudo escribir el fichero de: {}".format(", ".join(fallidos)))
