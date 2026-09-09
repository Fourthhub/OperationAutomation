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
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 120

CABECERAS = [
    ("fecha", 12), ("entrada", 10), ("salida", 10), ("horas", 8),
    ("fichajes", 9), ("todos los fichajes", 30), ("aviso", 36),
]

AMARILLO = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")

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

    Las filas que hay que revisar a mano van en amarillo en vez de en una hoja
    aparte: asi cada persona ve su mes completo y de un vistazo que dias le
    faltan por cerrar.
    """
    hoja = libro.create_sheet(titulo)
    primera = filas[0]

    hoja["A1"] = "{} — nº {} — {}".format(primera["empleado"], primera["workno"], primera["departamento"])
    hoja["A1"].font = Font(bold=True, size=13)

    hoja.append([])
    hoja.append([c for c, _ in CABECERAS])
    for celda in hoja[3]:
        celda.font = Font(bold=True)
    hoja.freeze_panes = "A4"
    for i, (_, ancho) in enumerate(CABECERAS, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho

    for f in filas:
        hoja.append([f["fecha"], f["entrada"], f["salida"], f["horas"],
                     f["fichajes"], f["todos"], f["aviso"]])
        if f["aviso"]:
            for celda in hoja[hoja.max_row]:
                celda.fill = AMARILLO

    completas = [f for f in filas if f["horas"] is not None]
    hoja.append([])
    fila_total = hoja.max_row + 1
    hoja.cell(row=fila_total, column=1, value="TOTAL").font = Font(bold=True)
    hoja.cell(row=fila_total, column=4, value=round(sum(f["horas"] for f in completas), 2)).font = Font(bold=True)
    hoja.cell(row=fila_total, column=6,
              value="{} días con horas, {} a revisar".format(len(completas), len(filas) - len(completas)))
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
    hoja.append(["Empleado", "Horas", "Días", "A revisar"])
    for celda in hoja[hoja.max_row]:
        celda.font = Font(bold=True)
    for titulo, suyas in hojas_por_persona:
        con_horas = [f for f in suyas if f["horas"] is not None]
        hoja.append([titulo, round(sum(f["horas"] for f in con_horas), 2),
                     len(con_horas), len(suyas) - len(con_horas)])

    hoja.column_dimensions["A"].width = 36
    for col in ("B", "C", "D"):
        hoja.column_dimensions[col].width = 11
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
