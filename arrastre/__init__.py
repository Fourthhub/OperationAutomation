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

def fecha():
    zona_horaria_españa = ZoneInfo("Europe/Madrid")
    fecha_hoy_utc = datetime.now(timezone.utc)
    fecha_hoy = fecha_hoy_utc.astimezone(zona_horaria_españa)
    fecha_hoy = fecha_hoy + timedelta(days=1)
    fecha_hoy_str = fecha_hoy.strftime("%Y-%m-%d")
    logging.info(f"Fecha planificada: {fecha_hoy_str}")
    return fecha_hoy_str

def hayReservaHoy(propertyID, token):
    fecha_hoy = fecha()
    logging.info(f"Verificando reservas para propiedad {propertyID} en fecha {fecha_hoy}")
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
                logging.info(f"Reserva encontrada para propiedad {propertyID} en fecha {fecha_hoy}")
                return True
        return False
    else:
        raise Exception(f"Error al consultar reservas: {response.status_code} - {response.text}")

def moverAHoy(task_id, token, property_name=""):
    fecha_hoy = fecha()
    logging.info(f"Propiedad {property_name}: Moviendo tarea {task_id} a {fecha_hoy}")
    endpoint = URL + f"public/inventory/v1/task/{task_id}"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    payload = {"scheduled_date": fecha_hoy}
    response = requests.patch(endpoint, json=payload, headers=headers)
    logging.info(f"Propiedad {property_name}: Respuesta al mover tarea {task_id}: {response.text} ({response.status_code})")
    if response.status_code in [200, 201, 202, 204]:
        return f"Tarea {task_id} movida a {fecha_hoy}. Respuesta {response.status_code}"
    else:
        return f"Error moviendo tarea {task_id}: {response.status_code} {response.text}"

def ponerEnHigh(task_id, token):
    logging.info(f"Actualizando prioridad a alta para tarea {task_id}")
    endpoint = URL + f"public/inventory/v1/task/{task_id}"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    payload = {"type_priority": "high"}
    response = requests.patch(endpoint, json=payload, headers=headers)
    if response.status_code in [200, 201, 202, 204]:
        return f"Tarea {task_id} actualizada a prioridad alta."
    else:
        return f"Error actualizando tarea {task_id} a prioridad alta: {response.status_code} {response.text}"

def corregirPrioridades(propertyID, token, property_name):
    fecha_hoy = fecha()
    logging.info(f"Propiedad {property_name}: Corrigiendo prioridades para tareas con fecha {fecha_hoy}")
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
            futures = [
                executor.submit(ponerEnHigh, task["id"], token)
                for task in tasks 
                if task["type_task_status"]["name"] not in ["Finished", "Closed"]
                   and (logging.info(f"Propiedad {property_name}: Actualizando prioridad para tarea {task.get('name', 'Sin nombre')}") or True)
            ]
            for future in as_completed(futures):
                respuesta_log.append(future.result())
        return respuesta_log
    else:
        raise Exception(f"Error al consultar tareas: {response.status_code} - {response.text}")

def moverLimpiezasConSusIncidencias(propertyID, token, property_name):
    fecha_hoy = fecha()
    logging.info(f"Propiedad {property_name} (ID: {propertyID}): Iniciando mover limpiezas con incidencias para tareas creadas desde {datetime.now().year}-01-01 hasta {fecha_hoy}")
    
    def espasado(fechaTarea):
        if fechaTarea is None:
            return True
        fecha_hoy_dt = datetime.strptime(fecha_hoy, "%Y-%m-%d")
        fecha_tarea_dt = datetime.strptime(fechaTarea, "%Y-%m-%d")
        return fecha_tarea_dt < fecha_hoy_dt

    year = datetime.now().year
    start_date = f"{year}-01-01"
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&created_at={start_date},{fecha_hoy}"
    logging.info(f"Propiedad {property_name}: Endpoint para tareas: {endpoint}")
    
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
                executor.submit(moverAHoy, task["id"], token, property_name)
                for task in tasks 
                if task["type_task_status"]["name"] not in ["Finished", "Closed"] 
                   and espasado(task["scheduled_date"])
                   and (logging.info(f"Propiedad {property_name}: Procesando tarea '{task.get('name', 'Sin nombre')}' (ID: {task['id']})") or True)
            ]
            for future in as_completed(futures):
                respuesta_log.append(future.result())
        return respuesta_log
    else:
        raise Exception(f"Error al consultar tareas para mover {propertyID}: {response.status_code} - {response.text}")

def conexionBreezeway():
    logging.info("Obteniendo token de Breezeway")
    endpoint = URL + "public/auth/v1/"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(endpoint, json=payload, headers=headers)
    token = response.json().get('access_token')
    if token:
        logging.info("Token obtenido correctamente")
    else:
        logging.error("No se obtuvo token")
    return token

def conseguirPropiedades(token):
    logging.info("Obteniendo propiedades")
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
        propiedades = conseguirPropiedades(token)
        logging.info(f"Propiedades obtenidas: {len(propiedades.get('results', []))} encontradas")
        with ThreadPoolExecutor() as executor:
            futures = {}
            for propiedad in propiedades["results"]:
                propertyID = propiedad["reference_property_id"]
                property_name = propiedad["name"]
                if propertyID is None or propiedad["status"] != "active":
                    logging.info(f"Propiedad {property_name} omitida (ID nulo o inactiva)")
                    continue

                logging.info(f"Iniciando procesamiento de propiedad: {property_name} (ID: {propertyID})")
                updates_log.append(f"Procesando Propiedad: {property_name}")
                # Enviar tareas de mover limpiezas
                futures[executor.submit(moverLimpiezasConSusIncidencias, propertyID, token, property_name)] = property_name
                # Enviar tareas de corregir prioridades si hay reserva hoy
                if hayReservaHoy(propertyID, token):
                    futures[executor.submit(corregirPrioridades, propertyID, token, property_name)] = property_name

            for future in as_completed(futures):
                result = future.result()
                prop_name = futures[future]
                updates_log.append(f"{prop_name}: {result}")
                logging.info(f"Resultado para propiedad {prop_name}: {result}")
    else:
        logging.error("Error al acceder a Breezeway")
        raise BaseException("Error al acceder a Breezeway")