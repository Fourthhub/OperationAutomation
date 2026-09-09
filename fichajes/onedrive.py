"""Un fichero de Excel por empleado, con una hoja por mes, en OneDrive.

La organizacion importa: como el sueldo por hora se escribe a mano, tenerlo en
un sitio por persona y no por mes evita volver a teclear 49 precios cada primero
de mes. Vive en la hoja "Ficha", y las hojas de cada mes lo referencian.

Por eso cada ejecucion no genera el libro de cero: descarga el que ya existe,
le anade o reemplaza la hoja del mes y lo vuelve a subir. Asi se conserva lo que
haya escrito una persona: el precio hora y cualquier correccion a mano.
"""

import io
import logging
import re
import time

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 120

CABECERAS = [("fecha", 12), ("entrada", 10), ("salida", 10), ("horas", 9), ("aviso", 46)]

AMARILLO = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
# Azul claro para lo que rellena una persona: el amarillo ya significa
# "este dia hay que revisarlo" y no conviene mezclar los dos sentidos.
AZUL_EDITABLE = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
BORDE = Border(*[Side(style="thin", color="9BC2E6")] * 4)

EUROS = '#,##0.00 "€"'

HOJA_FICHA = "Ficha"
FILA_SUELDO = 6            # Ficha!B6 es la unica celda que se rellena a mano
FILA_TABLA_MESES = 9       # cabecera de la tabla de meses en la Ficha
PRIMERA_FILA_DATOS = 8     # en la hoja de un mes: 1 titulo, 3-5 totales, 7 cabeceras

PROHIBIDOS_HOJA = re.compile(r"[:\\/?*\[\]]")
PROHIBIDOS_FICHERO = re.compile(r'[<>:"/\\|?*]')


def nombre_de_fichero(empleado, workno):
    """'Ana Canales - 54.xlsx'. Ordena por nombre y el numero lo hace unico."""
    base = PROHIBIDOS_FICHERO.sub(" ", empleado or "").strip() or "Sin nombre"
    base = " ".join(base.split())
    return "{} - {}.xlsx".format(base[:80], workno)


def token(tenant_id, client_id, client_secret):
    respuesta = requests.post(
        "https://login.microsoftonline.com/{}/oauth2/v2.0/token".format(tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=TIMEOUT,
    )
    respuesta.raise_for_status()
    return respuesta.json()["access_token"]


# --- Graph -----------------------------------------------------------------

INTENTOS_SI_BLOQUEADO = 3
ESPERA_SI_BLOQUEADO = 20


def _cabeceras(tk, tipo=None):
    h = {"Authorization": "Bearer {}".format(tk)}
    if tipo:
        h["Content-Type"] = tipo
    return h


def descargar(tk, drive_id, carpeta_id, nombre):
    """Contenido del fichero, o None si todavia no existe."""
    url = "{}/drives/{}/items/{}:/{}:/content".format(GRAPH, drive_id, carpeta_id, nombre)
    respuesta = requests.get(url, headers=_cabeceras(tk), timeout=TIMEOUT)
    if respuesta.status_code == 404:
        return None
    respuesta.raise_for_status()
    return respuesta.content


def subir(tk, drive_id, carpeta_id, nombre, contenido):
    """Sube o reemplaza el fichero.

    Si alguien lo tiene abierto en Excel, OneDrive lo bloquea y Graph responde
    423 resourceLocked. Se reintenta un par de veces por si es un guardado
    momentaneo y si sigue bloqueado se avisa de que hay que cerrarlo.
    """
    url = "{}/drives/{}/items/{}:/{}:/content".format(GRAPH, drive_id, carpeta_id, nombre)
    tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    for intento in range(1, INTENTOS_SI_BLOQUEADO + 1):
        respuesta = requests.put(url, headers=_cabeceras(tk, tipo), data=contenido, timeout=TIMEOUT)

        if respuesta.status_code in (200, 201):
            datos = respuesta.json()
            logging.info("Subido %s (%s bytes)", datos.get("name"), datos.get("size"))
            return datos.get("webUrl")

        if respuesta.status_code == 423 and intento < INTENTOS_SI_BLOQUEADO:
            logging.warning("%s bloqueado, reintento %s de %s en %s s",
                            nombre, intento, INTENTOS_SI_BLOQUEADO, ESPERA_SI_BLOQUEADO)
            time.sleep(ESPERA_SI_BLOQUEADO)
            continue

        if respuesta.status_code == 423:
            raise RuntimeError(
                "No se pudo escribir {}: alguien lo tiene abierto en Excel.".format(nombre))

        raise RuntimeError("Graph rechazo la subida de {}: {} {}".format(
            nombre, respuesta.status_code, respuesta.text[:250]))


# --- Construccion del libro ------------------------------------------------

def _ficha(libro, empleado, workno, departamento):
    """Crea la hoja Ficha si no existe. Nunca pisa el sueldo ya escrito."""
    if HOJA_FICHA in libro.sheetnames:
        hoja = libro[HOJA_FICHA]
    else:
        hoja = libro.create_sheet(HOJA_FICHA, 0)
        hoja["A6"] = "SUELDO POR HORA"
        hoja["A6"].font = Font(bold=True)
        hoja["B6"].fill = AZUL_EDITABLE
        hoja["B6"].border = BORDE
        hoja["B6"].number_format = EUROS
        hoja["C6"] = "← se escribe una sola vez, vale para todos los meses"
        hoja["C6"].font = Font(italic=True, color="808080")

    hoja["A1"] = empleado
    hoja["A1"].font = Font(bold=True, size=14)
    hoja["A3"] = "Nº de empleado"
    hoja["B3"] = workno
    hoja["A4"] = "Departamento"
    hoja["B4"] = departamento
    hoja.column_dimensions["A"].width = 22
    hoja.column_dimensions["B"].width = 16
    for col in ("C", "D", "E"):
        hoja.column_dimensions[col].width = 15
    return hoja


def _tabla_de_meses(hoja_ficha, libro):
    """Rehace la tabla de meses de la Ficha a partir de las hojas que hay."""
    for fila in range(FILA_TABLA_MESES, hoja_ficha.max_row + 2):
        for col in range(1, 6):
            hoja_ficha.cell(row=fila, column=col).value = None

    cabeceras = ["Mes", "Horas", "Días", "A revisar", "Total a pagar"]
    for i, c in enumerate(cabeceras, start=1):
        celda = hoja_ficha.cell(row=FILA_TABLA_MESES, column=i, value=c)
        celda.font = Font(bold=True)

    meses = sorted(h for h in libro.sheetnames if h != HOJA_FICHA)
    for n, mes in enumerate(meses, start=1):
        fila = FILA_TABLA_MESES + n
        ref = "'{}'".format(mes)
        hoja_ficha.cell(row=fila, column=1, value=mes)
        hoja_ficha.cell(row=fila, column=2, value="={}!$B$3".format(ref)).number_format = "0.00"
        hoja_ficha.cell(row=fila, column=3, value="={}!$B$5".format(ref))
        hoja_ficha.cell(row=fila, column=4, value="={}!$B$4".format(ref))
        hoja_ficha.cell(row=fila, column=5, value="={}!$B$6".format(ref)).number_format = EUROS

    if meses:
        fila_total = FILA_TABLA_MESES + len(meses) + 1
        hoja_ficha.cell(row=fila_total, column=1, value="TOTAL").font = Font(bold=True)
        celda = hoja_ficha.cell(
            row=fila_total, column=5,
            value="=SUM(E{}:E{})".format(FILA_TABLA_MESES + 1, FILA_TABLA_MESES + len(meses)))
        celda.font = Font(bold=True)
        celda.number_format = EUROS


def _hoja_mes(libro, periodo, filas):
    """Crea o reemplaza la hoja de un mes. Reemplazar permite rehacer un mes."""
    if periodo in libro.sheetnames:
        del libro[periodo]
    hoja = libro.create_sheet(periodo)

    completas = [f for f in filas if f["horas"] is not None]
    ultima = PRIMERA_FILA_DATOS + len(filas) - 1

    hoja["A1"] = "{} — {}".format(filas[0]["empleado"], periodo)
    hoja["A1"].font = Font(bold=True, size=13)

    hoja["A3"] = "Horas del mes"
    hoja["B3"] = "=ROUND(SUM(D{}:D{}),2)".format(PRIMERA_FILA_DATOS, ultima)
    hoja["B3"].number_format = "0.00"

    hoja["A4"] = "Días a revisar"
    hoja["B4"] = len(filas) - len(completas)

    hoja["A5"] = "Días con horas"
    hoja["B5"] = len(completas)

    hoja["A6"] = "Total a pagar"
    # El sueldo se lee de la Ficha, no se repite en cada mes.
    hoja["B6"] = '=IF({0}!$B${1}="","",ROUND($B$3*{0}!$B${1},2))'.format(HOJA_FICHA, FILA_SUELDO)
    hoja["B6"].font = Font(bold=True)
    hoja["B6"].number_format = EUROS

    for f in ("A3", "A6"):
        hoja[f].font = Font(bold=True)

    for i, (cabecera, ancho) in enumerate(CABECERAS, start=1):
        celda = hoja.cell(row=PRIMERA_FILA_DATOS - 1, column=i, value=cabecera)
        celda.font = Font(bold=True)
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = "A{}".format(PRIMERA_FILA_DATOS)

    for n, f in enumerate(filas):
        fila = PRIMERA_FILA_DATOS + n
        hoja.cell(row=fila, column=1, value=f["fecha"])
        hoja.cell(row=fila, column=2, value=f["entrada"])
        hoja.cell(row=fila, column=3, value=f["salida"])
        hoja.cell(row=fila, column=4, value=f["horas"]).number_format = "0.00"
        hoja.cell(row=fila, column=5, value=f["aviso"])
        if f["aviso"]:
            for col in range(1, len(CABECERAS) + 1):
                hoja.cell(row=fila, column=col).fill = AMARILLO

    return hoja


def actualizar_libro(contenido, periodo, filas):
    """Devuelve el libro con la hoja del mes anadida o reemplazada.

    contenido es el fichero que ya hay en OneDrive, o None la primera vez.
    """
    if contenido:
        libro = load_workbook(io.BytesIO(contenido))
    else:
        libro = Workbook()
        libro.remove(libro.active)

    primera = filas[0]
    _hoja_mes(libro, periodo, filas)
    ficha = _ficha(libro, primera["empleado"], primera["workno"], primera["departamento"])

    # Ficha primero y los meses en orden.
    orden = [HOJA_FICHA] + sorted(h for h in libro.sheetnames if h != HOJA_FICHA)
    libro._sheets = [libro[h] for h in orden]

    _tabla_de_meses(ficha, libro)

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()
