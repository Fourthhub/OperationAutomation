"""Genera el libro de Excel y lo sube a OneDrive con Microsoft Graph.

Se sube el fichero entero en lugar de escribir celda a celda con la API de
Excel: para un informe mensual que se regenera completo es una sola llamada en
vez de cientos, y de paso evita el choque de nombres que sufre el escenario de
Liquidaciones, porque el PUT reemplaza el fichero si ya existe.
"""

import io
import logging

import requests
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 120

CABECERAS = [
    ("fecha", 12), ("nº", 7), ("empleado", 28), ("departamento", 22),
    ("entrada", 10), ("salida", 10), ("horas", 8), ("fichajes", 9),
    ("todos los fichajes", 34), ("aviso", 34),
]


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


def _hoja(libro, titulo, filas):
    hoja = libro.create_sheet(titulo)
    hoja.append([c for c, _ in CABECERAS])
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    hoja.freeze_panes = "A2"
    for i, (_, ancho) in enumerate(CABECERAS, start=1):
        hoja.column_dimensions[get_column_letter(i)].width = ancho

    for f in filas:
        hoja.append([
            f["fecha"], f["workno"], f["empleado"], f["departamento"],
            f["entrada"], f["salida"], f["horas"], f["fichajes"],
            f["todos"], f["aviso"],
        ])
    return hoja


def construir_libro(filas, resumen_departamentos, periodo):
    """Tres hojas: las jornadas completas, las que hay que revisar y el resumen."""
    libro = Workbook()
    libro.remove(libro.active)

    completas = [f for f in filas if f["horas"] is not None]
    revisar = [f for f in filas if f["horas"] is None]

    _hoja(libro, "Jornadas", completas)
    _hoja(libro, "A revisar", revisar)

    resumen = libro.create_sheet("Resumen")
    resumen.append(["Periodo", periodo])
    resumen.append(["Jornadas completas", len(completas)])
    resumen.append(["Pendientes de revisar", len(revisar)])
    resumen.append([])
    resumen.append(["Departamento", "Horas", "Días"])
    for celda in resumen[5]:
        celda.font = Font(bold=True)
    for depto, d in resumen_departamentos.items():
        resumen.append([depto, d["horas"], d["dias"]])
    resumen.column_dimensions["A"].width = 26
    resumen.column_dimensions["B"].width = 12

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def subir(tk, drive_id, carpeta_id, nombre, contenido):
    """Sube (o reemplaza) el fichero dentro de la carpeta indicada."""
    url = "{}/drives/{}/items/{}:/{}:/content".format(GRAPH, drive_id, carpeta_id, nombre)
    respuesta = requests.put(
        url,
        headers={"Authorization": "Bearer {}".format(tk),
                 "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        data=contenido,
        timeout=TIMEOUT,
    )
    if respuesta.status_code not in (200, 201):
        raise RuntimeError("Graph rechazo la subida: {} {}".format(respuesta.status_code, respuesta.text[:300]))
    datos = respuesta.json()
    logging.info("Subido %s (%s bytes)", datos.get("name"), datos.get("size"))
    return datos.get("webUrl")
