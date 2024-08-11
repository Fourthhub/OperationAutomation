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
    #logging.info(f"Comenzando ejecución a fecha {fecha_hoy}")

    # Incrementa la fecha actual en un día
    fecha_hoy = fecha_hoy + timedelta(days=1)
    #logging.info(f"Planificando para {fecha_hoy}")

    fecha_hoy = fecha_hoy.strftime("%Y-%m-%d")

    return fecha_hoy

#logging.basicConfig(level=logging.WARNING)

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

def haySalidahoy(propertyID, token):
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
            if reserva["checkout_date"] == fecha_hoy:
                revisarPerro(reserva["reference_reservation_id"],propertyID,token)
                return True
        return False
    else:
        raise Exception(f"Error al consultar reservas: {response.status_code} - {response.text}")

def revisarPerro(idReserva,propertyID,token):
    url= f"https://api.hostaway.com/v1/financeField/{idReserva}"
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-type': "application/json",
        'Cache-control': "no-cache",
    }
    response = requests.get(url, headers=headers)
    data = response.json()['result']
    
    for element in data:
        if element['name']=="petFee":
            marcarPerro(propertyID,token)
            return True
    return False

def marcarPerro(propertyID,token):
    taskID = 'preee'
    endpoint = URL + f"/public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={fecha_hoy},{fecha_hoy}"
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    data = response.json()['result']
    for element in data:
        if element["template_id"] == 101204:
            taskID = element["id"]
            nombreTarea = element["name"]
            cambiarNombreTarea(taskID,nombreTarea,token,)
            
    

    
def cambiarNombreTarea(taskId,nombreTarea,token):
    fecha_hoy = fecha()
    nombreConPerro = "🐶" + nombreTarea 
    #logging.info(f"Moviendo tarea {task_id}")
    endpoint = URL + f"public/inventory/v1/task/{taskId}"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    payload = {"name": nombreConPerro}
    response = requests.patch(endpoint, json=payload, headers=headers)
    logging.info(f"Respuesta cambiando nombre: {response.text} {response.status_code}")
    if response.status_code in [200, 201, 202, 204]:
        return f"Tarea {taskId} cambiada nombre. {response.status_code}"
    else:
        return f"Error cambiando nombre de {taskId}: {response.status_code} {response.text}"
    
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

                haySalidahoy(propertyID)

            for future in as_completed(futures):
                updates_log.append(f"{futures[future]}: {future.result()}")
                #logging.info(f"Resultado: {future.result()}")

    else:
        logging.error("Error al acceder a breezeway")
        raise BaseException("Error al acceder a breezeway")
