"""Genera el libro de Excel y lo sube a OneDrive con Microsoft Graph.

Se sube el fichero entero en lugar de escribir celda a celda con la API de
Excel: para un informe mensual que se regenera completo es una sola llamada en
vez de cientos, y de paso evita el choque de nombres que sufre el escenario de
Liquidaciones, porque el PUT reemplaza el fichero si ya existe.
"""

import collections
import io
import logging
import re
import time

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 120

CABECERAS = [("fecha", 12), ("entrada", 10), ("salida", 10), ("horas", 9), ("aviso", 46)]

AMARILLO = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
# Azul claro para la celda que rellena una persona, para que no se confunda con
# el amarillo, que aqui significa "este dia hay que revisarlo".
AZUL_EDITABLE = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
BORDE = Border(*[Side(style="thin", color="9BC2E6")] * 4)

EUROS = '#,##0.00 "€"'
PRIMERA_FILA_DATOS = 9   # 1 titulo, 2 blanco, 3-6 bloque de sueldo, 7 blanco, 8 cabeceras

# Excel no admite mas de 31 caracteres ni estos caracteres en el nombre de una hoja.
PROHIBIDOS = re.compile(r"[:\\/?*\[\]]")


def nombre_de_hoja(empleado, workno, usados):
    """Nombre de hoja valido y unico.

    Se limpia lo que Excel no admite y se recorta a 31 caracteres. Si dos
    empleados acabaran coincidiendo se anade el numero, que si es unico.
    """
    base = PROHIBIDOS.sub(" ", empleado or "").strip() or "Sin nombre"
    base = " ".join(base.split())[:31]
    if base.lower() not in usados:
        usados.add(base.lower())
        return base
    sufijo = " ({})".format(workno)
    base = base[:31 - len(sufijo)] + sufijo
    usados.add(base.lower())
    return base


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


def _hoja_persona(libro, titulo, filas):
    """Una hoja con los dias de un solo empleado.

    Los dias que hay que revisar a mano van en amarillo en vez de en una hoja
    aparte, para que cada persona vea su mes completo de un vistazo.

    Arriba queda el bloque de sueldo: B3 es la unica celda que se rellena a
    mano, y las horas y el total a pagar son formulas de Excel, no numeros
    calculados aqui. Asi el total se recalcula solo en cuanto se escribe el
    precio hora, y tambien si alguien corrige a mano las horas de un dia que
    estaba en amarillo.
    """
    hoja = libro.create_sheet(titulo)
    primera = filas[0]
    completas = [f for f in filas if f["horas"] is not None]

    hoja["A1"] = "{} — nº {} — {}".format(primera["empleado"], primera["workno"], primera["departamento"])
    hoja["A1"].font = Font(bold=True, size=13)

    ultima = PRIMERA_FILA_DATOS + len(filas) - 1
    rango_horas = "D{}:D{}".format(PRIMERA_FILA_DATOS, ultima)

    hoja["A3"] = "Sueldo por hora"
    hoja["B3"] = None                      # lo rellena una persona
    hoja["B3"].fill = AZUL_EDITABLE
    hoja["B3"].border = BORDE
    hoja["B3"].number_format = EUROS
    hoja["C3"] = "← escribe aquí el precio hora"
    hoja["C3"].font = Font(italic=True, color="808080")

    hoja["A4"] = "Horas del mes"
    hoja["B4"] = "=ROUND(SUM({}),2)".format(rango_horas)
    hoja["B4"].number_format = "0.00"

    hoja["A5"] = "Total a pagar"
    hoja["B5"] = '=IF($B$3="","",ROUND($B$4*$B$3,2))'
    hoja["B5"].font = Font(bold=True)
    hoja["B5"].number_format = EUROS

    hoja["A6"] = "Días a revisar"
    hoja["B6"] = len(filas) - len(completas)

    hoja["A3"].font = Font(bold=True)
    hoja["A5"].font = Font(bold=True)

    for i, (cabecera, ancho) in enumerate(CABECERAS, start=1):
        celda = hoja.cell(row=8, column=i, value=cabecera)
        celda.font = Font(bold=True)
        hoja.column_dimensions[get_column_letter(i)].width = ancho
    hoja.freeze_panes = "A{}".format(PRIMERA_FILA_DATOS)

    for n, f in enumerate(filas):
        fila = PRIMERA_FILA_DATOS + n
        hoja.cell(row=fila, column=1, value=f["fecha"])
        hoja.cell(row=fila, column=2, value=f["entrada"])
        hoja.cell(row=fila, column=3, value=f["salida"])
        celda_horas = hoja.cell(row=fila, column=4, value=f["horas"])
        celda_horas.number_format = "0.00"
        hoja.cell(row=fila, column=5, value=f["aviso"])
        if f["aviso"]:
            for col in range(1, len(CABECERAS) + 1):
                hoja.cell(row=fila, column=col).fill = AMARILLO

    return hoja


def _hoja_resumen(libro, filas, resumen_departamentos, periodo, hojas_por_persona):
    hoja = libro.create_sheet("Resumen", 0)
    completas = [f for f in filas if f["horas"] is not None]

    hoja["A1"] = "Control horario {}".format(periodo)
    hoja["A1"].font = Font(bold=True, size=14)
    hoja.append([])
    hoja.append(["Jornadas con horas", len(completas)])
    hoja.append(["Pendientes de revisar (en amarillo)", len(filas) - len(completas)])
    hoja.append(["Empleados", len(hojas_por_persona)])
    hoja.append([])

    hoja.append(["Departamento", "Horas", "Días"])
    for celda in hoja[hoja.max_row]:
        celda.font = Font(bold=True)
    for depto, d in resumen_departamentos.items():
        hoja.append([depto, d["horas"], d["dias"]])

    hoja.append([])
    hoja.append(["Empleado", "Horas", "Días", "A revisar", "Sueldo/hora", "Total a pagar"])
    for celda in hoja[hoja.max_row]:
        celda.font = Font(bold=True)

    # El sueldo y el total se traen de la hoja de cada persona con formulas, para
    # que el resumen se actualice solo en cuanto se rellenen los precios hora y
    # sirva de vista de conjunto para pagar.
    for titulo, suyas in hojas_por_persona:
        con_horas = [f for f in suyas if f["horas"] is not None]
        hoja.append([titulo, round(sum(f["horas"] for f in con_horas), 2),
                     len(con_horas), len(suyas) - len(con_horas)])
        fila = hoja.max_row
        ref = "'{}'".format(titulo.replace("'", "''"))
        hoja.cell(row=fila, column=5, value="={}!$B$3".format(ref)).number_format = EUROS
        hoja.cell(row=fila, column=6, value="={}!$B$5".format(ref)).number_format = EUROS

    fila_total = hoja.max_row + 1
    hoja.cell(row=fila_total, column=1, value="TOTAL").font = Font(bold=True)
    primera_persona = fila_total - len(hojas_por_persona)
    celda = hoja.cell(row=fila_total, column=6,
                      value="=SUM(F{}:F{})".format(primera_persona, fila_total - 1))
    celda.font = Font(bold=True)
    celda.number_format = EUROS

    hoja.column_dimensions["A"].width = 36
    for col in ("B", "C", "D", "E", "F"):
        hoja.column_dimensions[col].width = 13
    hoja["A1"].alignment = Alignment(vertical="center")
    return hoja


def construir_libro(filas, resumen_departamentos, periodo):
    """Un resumen y una hoja por empleado, con los dias a revisar en amarillo."""
    libro = Workbook()
    libro.remove(libro.active)

    por_persona = collections.OrderedDict()
    for f in sorted(filas, key=lambda x: (x["empleado"].lower(), x["fecha"])):
        por_persona.setdefault((f["workno"], f["empleado"]), []).append(f)

    usados = set()
    hojas = []
    for (workno, empleado), suyas in por_persona.items():
        titulo = nombre_de_hoja(empleado, workno, usados)
        _hoja_persona(libro, titulo, suyas)
        hojas.append((titulo, suyas))

    _hoja_resumen(libro, filas, resumen_departamentos, periodo, hojas)
    logging.info("Libro con %s hojas de empleado mas el resumen", len(hojas))

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


INTENTOS_SI_BLOQUEADO = 3
ESPERA_SI_BLOQUEADO = 20


def subir(tk, drive_id, carpeta_id, nombre, contenido):
    """Sube (o reemplaza) el fichero dentro de la carpeta indicada.

    Si alguien tiene el libro abierto en Excel, OneDrive lo bloquea y Graph
    responde 423 resourceLocked. En la ejecucion mensual normal no puede pasar,
    porque el nombre del mes es nuevo y nadie puede tenerlo abierto todavia; se
    da al rehacer un mes que alguien esta consultando. Se reintenta un par de
    veces por si es un guardado momentaneo y, si sigue bloqueado, se falla con
    un mensaje que diga que hay que cerrarlo, en lugar de un 423 a secas.
    """
    url = "{}/drives/{}/items/{}:/{}:/content".format(GRAPH, drive_id, carpeta_id, nombre)
    cabeceras = {
        "Authorization": "Bearer {}".format(tk),
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    for intento in range(1, INTENTOS_SI_BLOQUEADO + 1):
        respuesta = requests.put(url, headers=cabeceras, data=contenido, timeout=TIMEOUT)

        if respuesta.status_code in (200, 201):
            datos = respuesta.json()
            logging.info("Subido %s (%s bytes)", datos.get("name"), datos.get("size"))
            return datos.get("webUrl")

        if respuesta.status_code == 423 and intento < INTENTOS_SI_BLOQUEADO:
            logging.warning(
                "%s esta bloqueado (alguien lo tiene abierto). Reintento %s de %s en %s s",
                nombre, intento, INTENTOS_SI_BLOQUEADO, ESPERA_SI_BLOQUEADO,
            )
            time.sleep(ESPERA_SI_BLOQUEADO)
            continue

        if respuesta.status_code == 423:
            raise RuntimeError(
                "No se pudo escribir {}: alguien lo tiene abierto en Excel. "
                "Cierralo y vuelve a lanzar la funcion.".format(nombre)
            )

        raise RuntimeError("Graph rechazo la subida: {} {}".format(respuesta.status_code, respuesta.text[:300]))
