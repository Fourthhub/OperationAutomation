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
import time

import azure.functions as func

from . import crosschex, jornadas, onedrive

ESPERA_SEGUNDA_PASADA = 60   # margen para que alguien cierre su Excel


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

    resultado = _escribir(tk, drive_id, carpeta_id, periodo, gente)

    # Segunda pasada solo para los que estaban abiertos en Excel. Se hace al
    # final y una sola vez: esperar delante de cada uno agotaria los diez
    # minutos de la funcion si hay muchos abiertos a la vez.
    if resultado["bloqueados"]:
        logging.info("Fichajes: %s ficheros estaban abiertos, segunda pasada en %s s",
                     len(resultado["bloqueados"]), ESPERA_SEGUNDA_PASADA)
        time.sleep(ESPERA_SEGUNDA_PASADA)
        pendientes = {k: v for k, v in gente.items()
                      if onedrive.nombre_de_fichero(k[1], k[0]) in resultado["bloqueados"]}
        segunda = _escribir(tk, drive_id, carpeta_id, periodo, pendientes)
        resultado["nuevos"] += segunda["nuevos"]
        resultado["actualizados"] += segunda["actualizados"]
        resultado["bloqueados"] = segunda["bloqueados"]
        resultado["fallidos"] += segunda["fallidos"]

    logging.info("Fichajes: %s nuevos, %s actualizados, %s abiertos en Excel, %s con error",
                 resultado["nuevos"], resultado["actualizados"],
                 len(resultado["bloqueados"]), len(resultado["fallidos"]))

    if resultado["bloqueados"]:
        logging.warning("Fichajes: sin actualizar por estar abiertos: %s",
                        ", ".join(resultado["bloqueados"]))
    if resultado["fallidos"]:
        raise RuntimeError("Fallo al escribir: {}".format(", ".join(resultado["fallidos"])))


def _escribir(tk, drive_id, carpeta_id, periodo, gente):
    """Escribe el fichero de cada empleado. Cada uno aislado de los demas."""
    r = {"nuevos": 0, "actualizados": 0, "bloqueados": [], "fallidos": []}
    for (workno, empleado), suyas in gente.items():
        nombre = onedrive.nombre_de_fichero(empleado, workno)
        try:
            existente = onedrive.descargar(tk, drive_id, carpeta_id, nombre)
            contenido = onedrive.actualizar_libro(existente, periodo, suyas)
            onedrive.subir(tk, drive_id, carpeta_id, nombre, contenido)
            r["actualizados" if existente else "nuevos"] += 1
        except onedrive.Bloqueado:
            r["bloqueados"].append(nombre)
        except Exception as e:
            logging.error("Fichajes: fallo con %s: %s", nombre, e)
            r["fallidos"].append(nombre)
    return r
