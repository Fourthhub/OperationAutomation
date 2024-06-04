import requests
import json
import logging
import azure.functions as func
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID = 8172
fecha_hoy = ""
# Configura la zona horaria de España
def fecha():

    zona_horaria_españa = ZoneInfo("Europe/Madrid")

    # Obtiene la fecha y hora actuales en UTC
    fecha_hoy_utc = datetime.now(timezone.utc)

    # Convierte la fecha y hora actuales a la zona horaria de España
    fecha_hoy = fecha_hoy_utc.astimezone(zona_horaria_españa)
    logging.info(f"Comenzando ejecución a fecha {fecha_hoy}")

    # Incrementa la fecha actual en un día
    fecha_hoy = fecha_hoy + timedelta(days=1)
    logging.info(f"Planificando para {fecha_hoy}")

    fecha_hoy = fecha_hoy.strftime("%Y-%m-%d")

    return fecha_hoy

#logging.basicConfig(level=logging.WARNING)

def hayReservaHoy(propertyID, token):
    fecha_hoy = fecha()
    endpoint = URL + f"public/inventory/v1/reservation/external-id?reference_property_id={propertyID}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    if response.status_code in [200, 201, 202, 204]:
        reservas = response.json()
        for reserva in reservas:
            if reserva["checkin_date"] == fecha_hoy:
                return True
        return False
    else:
        raise Exception(f"Error al consultar reservas: {response.status_code} - {response.text}")


def moverAHoy(task_id, token):
    fecha_hoy = fecha()
    logging.info(f"Moviendo tarea {task_id}")
    endpoint = URL + f"public/inventory/v1/task/{task_id}"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    payload = {"scheduled_date": fecha_hoy}
    response = requests.patch(endpoint, json=payload, headers=headers)
    logging.info(f"Respuesta moviendo: {response.text} {response.status_code}")
    if response.status_code in [200, 201, 202, 204]:
        return f"Tarea {task_id} movida a {fecha_hoy}. Con respuesta {response.status_code}"
    else:
        return f"Error moviendo tarea {task_id} a hoy: {response.status_code} {response.text}"

def ponerEnHigh(task_id, token):
    fecha_hoy = fecha()
    endpoint = URL + f"public/inventory/v1/task/{task_id}"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    payload = {"type_priority": "high"}
    response = requests.patch(endpoint, json=payload, headers=headers)
    if response.status_code in [200, 201, 202, 204]:
        return f"Tarea {task_id} actualizada a prioridad alta."
    else:
        return f"Error actualizando tarea {task_id} a prioridad alta: {response.status_code} {response.text}"

def corregirPrioridades(propertyID, token):
    fecha_hoy = fecha()
    respuesta_log = []
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={fecha_hoy},{fecha_hoy}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    if response.status_code in [200, 201, 202, 204]:
        tasks = response.json()["results"]
        with ThreadPoolExecutor() as executor:
            futures = [executor.submit(ponerEnHigh, task["id"], token) for task in tasks if task["type_task_status"]["name"] not in ["Finished", "Closed"]]
            for future in as_completed(futures):
                respuesta_log.append(future.result())
        return respuesta_log
    else:
        raise Exception(f"Error al consultar tareas: {response.status_code} - {response.text}")

def moverLimpiezasConSusIncidencias(propertyID, token):
    fecha_hoy = fecha()
    def espasado(fechaTarea):
        if fechaTarea is None:
            return True
        fecha_hoy1 = datetime.strptime(fecha_hoy, "%Y-%m-%d")
        fecha_a_comparar = datetime.strptime(fechaTarea, "%Y-%m-%d")
        return fecha_a_comparar < fecha_hoy1

    year = datetime.now().year
    start_date = f"{year}-01-01"
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&created_at={start_date},{fecha_hoy}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    if response.status_code in [200, 201, 202]:
        respuesta_log = []
        tasks = response.json()["results"]
        with ThreadPoolExecutor() as executor:
            futures = [
                executor.submit(moverAHoy, task["id"], token) 
                for task in tasks 
                if task["type_task_status"]["name"] not in ["Finished", "Closed"] and espasado(task["scheduled_date"])
            ]
            for future in as_completed(futures):
                respuesta_log.append(future.result())
        return respuesta_log
    else:
        raise Exception(f"Error al consultar tareas para mover {propertyID}: {response.status_code} - {response.text}")

def conexionBreezeway():
    endpoint = URL + "public/auth/v1/"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {
        'Content-Type': 'application/json'
    }
    response = requests.post(endpoint, json=payload, headers=headers)
    token = response.json().get('access_token')
    return token

def conseguirPropiedades(token):
    endpoint = URL + f"public/inventory/v1/property?company_id={COMPANY_ID}&limit=350"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    return response.json()

def main(myTimer: func.TimerRequest) -> None:
    logging.info("Iniciando la función principal")
    token = conexionBreezeway()
    updates_log = []  
    fecha_hoy = fecha()
    

    if token:
        logging.info("Token obtenido con éxito")
        propiedades = conseguirPropiedades(token)
        logging.info(f"Propiedades obtenidas: {len(propiedades['results'])} encontradas")

        with ThreadPoolExecutor() as executor:
            futures = {}
            for propiedad in propiedades["results"]:
                propertyID = propiedad["reference_property_id"]
                if propertyID is None or propiedad["status"] != "active":
                    continue

                futures[executor.submit(moverLimpiezasConSusIncidencias, propertyID, token)] = propiedad["name"]
                
                if hayReservaHoy(propertyID, token):
                    futures[executor.submit(corregirPrioridades, propertyID, token)] = propiedad["name"]

            for future in as_completed(futures):
                updates_log.append(f"{futures[future]}: {future.result()}")
                logging.info(f"Resultado: {future.result()}")

    else:
        logging.error("Error al acceder a breezeway")
        raise BaseException("Error al acceder a breezeway")
