import requests
import json
import azure.functions as func
from datetime import datetime

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID = 8172

def hayReservaHoy(propertyID, token):
    try:
        endpoint = URL + f"public/inventory/v1/reservation/external-id?reference_property_id={propertyID}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }
        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code == 200:
            reservas = response.json()
            fecha_hoy = datetime.now().strftime("%Y-%m-%d")
            # Buscar si alguna reserva tiene la fecha de check-in igual a la fecha de hoy
            for reserva in reservas:
                if reserva["checkin_date"] == fecha_hoy:
                    return True  # Reserva encontrada para hoy
            return False  # No se encontraron reservas para hoy
        else:
            # Si la respuesta HTTP no es exitosa, levantar una excepción con el código de estado y el cuerpo de la respuesta
            raise Exception(f"Error al consultar reservas: {response.status_code} - {response.text}")
    except Exception as e:
        # Levantar cualquier excepción capturada durante la solicitud HTTP
        raise Exception(f"Excepción al consultar reservas: {e}")


def moverAHoy(task_id, token):
    try:
        hoy = datetime.now().strftime("%Y-%m-%d")
        endpoint = URL + f"public/inventory/v1/task/{task_id}"
        headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
        payload = {"scheduled_date": f"{hoy}"}
        response = requests.patch(endpoint, json=payload, headers=headers)
        if response.status_code == 200:
            return f"Tarea {task_id} movida a hoy."
        else:
            return f"Error moviendo tarea {task_id} a hoy: {response.text}"
    except Exception as e:
        return f"Excepción moviendo tarea {task_id} a hoy: {e}"

def ponerEnHigh(task_id, token):
    try:
        endpoint = URL + f"public/inventory/v1/task/{task_id}"
        headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
        payload = {"type_priority": "high"}
        response = requests.patch(endpoint, json=payload, headers=headers)
        if response.status_code == 200:
            return f"Tarea {task_id} actualizada a prioridad alta."
        else:
            return f"Error actualizando tarea {task_id}: {response.text}"
    except Exception as e:
        return f"Excepción actualizando tarea {task_id}: {e}"

def corregirPrioridades(propertyID, token):
    try:
        year = datetime.now().year
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={start_date},{end_date}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }
        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code == 200:
            tasks = response.json()["results"]
            for task in tasks:
                estado = task["type_task_status"]["name"]
                if estado not in ["Finished", "Closed"]:
                    # Aquí, asumiendo que ponerEnHigh maneja sus propios errores internamente
                    # o devuelve un mensaje de error sin levantar una excepción.
                    ponerEnHigh(task["id"], token)
        else:
            # Levantar una excepción si la respuesta de la API no es exitosa
            raise Exception(f"Error al consultar tareas: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        # Capturar errores específicos de las solicitudes y levantar una excepción
        raise Exception(f"Error de solicitud al consultar tareas: {e}")
    except Exception as e:
        # Levantar cualquier otra excepción que ocurra durante el proceso
        raise Exception(f"Excepción al corregir prioridades: {e}")

            
            
def moverLimpiezasConSusIncidencias(propertyID, token):
    try:
        year = datetime.now().year
        start_date = f"{year}-01-01"
        end_date = datetime.now().strftime("%Y-%m-%d")
        endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={start_date},{end_date}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }

        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code == 200:
            tasks = response.json()["results"]
            for task in tasks:
                estado = task["type_task_status"]["name"]
                if estado not in ["Finished", "Closed", "In-Progress"]:
                    # Asumiendo que moverAHoy gestiona internamente cualquier error o excepción
                    moverAHoy(task["id"], token)
        else:
            # Levantar una excepción si la respuesta de la API no es exitosa
            raise Exception(f"Error al consultar tareas para mover: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        # Capturar errores específicos de las solicitudes y levantar una excepción
        raise Exception(f"Error de solicitud al consultar tareas para mover: {e}")
    except Exception as e:
        # Levantar cualquier otra excepción que ocurra durante el proceso
        raise Exception(f"Excepción al mover limpiezas e incidencias: {e}")

            
            
    
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
    updates_log = []  # Para almacenar los logs de las actualizaciones
    if token:
         # Ejemplo de ID de propiedad
        propiedades = conseguirPropiedades()
        for propiedad in data['results']:
            propertyID = propiedad["reference_property_id"]
            updates_log.append(moverLimpiezasConSusIncidencias(propertyID, token))
            if hayReservaHoy(propertyID, token):              
                updates_log.append(corregirPrioridades(propertyID, token))
            return func.HttpResponse(
                body=json.dumps({"message": "Tareas Actualizadas Correctamente", "updates": updates_log}),
                status_code=200,
                mimetype="application/json"
            )
    else:
        return func.HttpResponse("Error al obtener token", status_code=400)