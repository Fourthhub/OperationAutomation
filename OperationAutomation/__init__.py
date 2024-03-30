import requests
import json
import azure.functions as func
from datetime import datetime

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID = 8172

def hayReservaHoy(propertyID,token):
    endpoint = URL + f"public/inventory/v1/reservation/external-id?reference_property_id={propertyID}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers).json()
    fecha_hoy = datetime.now().strftime("%Y-%m-%d")
    # Buscar si alguna reserva tiene la fecha de check-in igual a la fecha de hoy
    for reserva in response:
        if reserva["checkin_date"] == fecha_hoy:
            return True
    
    # Si termina el bucle sin encontrar ninguna fecha de check-in igual a la de hoy, devuelve False
        return False

def moverAHoy(task_id,token):
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        endpoint = URL + f"public/inventory/v1/task/{task_id}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }
        payload = {
            "scheduled_date": f"{hoy}",
        }
     
        response = requests.patch(endpoint, json=payload, headers=headers).json()
        
    except Exception as e:
        raise NameError(f"{e}") 

def ponerEnHigh(task_id,token):
    endpoint = URL + f"public/inventory/v1/task/{task_id}"

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    payload = {
        "type_priority": "high"
    }
    response = requests.patch(endpoint, json=payload, headers=headers)
    raise EnvironmentError(json.dumps(response) + "....." + endpoint)

def corregirPrioridades(propertyID,token):
    year = datetime.now().year
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={start_date},{end_date}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers).json()

# Iterar a través de las tareas y añadir  la prioridad de cada una 
    for tarea in response["results"]:
        estado = tarea["type_task_status"]["name"]
        if estado not in ["Finished", "Closed"]:
            ponerEnHigh(tarea["id"],token)
        
            
            
def moverLimpiezasConSusIncidencias(propertyID,token):
    
    year = datetime.now().year
    start_date = f"{year}-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={start_date},{end_date}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    
    response = requests.get(endpoint, headers=headers).json()


# Iterar a través de las tareas y añadir  la prioridad de cada una
    for tarea in response["results"]:
        estado = tarea["type_task_status"]["name"]
        if estado not in ["Finished", "Closed","In-Progress"]:
            moverAHoy(tarea["id"],token)
            
            
    
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
    print(response.text)
    # Asumiendo que la API devuelve un token JWT en un campo 'token' del JSON de respuesta
    token = response.json().get('access_token')  # Ajustar la clave según la respuesta real
    return token

def conseguirPropiedades(token):
    endpoint = URL + f"public/inventory/v1/property?company_id={COMPANY_ID}"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    return response.json()  # Asumiendo que quieres devolver el JSON respuesta

def main(req: func.HttpRequest) -> func.HttpResponse:
    token = conexionBreezeway()
    if token:
        #data = conseguirPropiedades(token)
        #for propiedad in data['results']:
            #propertyID = propiedad["reference_property_id"]
        propertyID=235728
        moverLimpiezasConSusIncidencias(propertyID,token)
        if hayReservaHoy(propertyID,token):              
            corregirPrioridades(propertyID,token)

        # Convertir 'data' a una cadena JSON para enviar en la respuesta HTTP si es necesario
        return func.HttpResponse("Tareas Actualizadas Correctamente", status_code=200, mimetype="application/json")
    else:
        return func.HttpResponse("Error al obtener token", status_code=400)
