import requests
import json
import azure.functions as func
from datetime import datetime, timezone,timedelta
from zoneinfo import ZoneInfo

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID =8172
zona_horaria_españa = ZoneInfo("Europe/Madrid")
fecha_hoy = datetime.now(zona_horaria_españa)
fecha_hoy = fecha_hoy + timedelta(days=1)
fecha_hoy = fecha_hoy.strftime("%Y-%m-%d")
app = func.FunctionApp()

def hayReservaHoy(propertyID, token):
    try:
        endpoint = URL + f"public/inventory/v1/reservation/external-id?reference_property_id={propertyID}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }
        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code in [200,201,202,204]:
            reservas = response.json()
            # Buscar si alguna reserva tiene la fecha de check-in igual a la fecha de hoy
            for reserva in reservas:
                if reserva["checkin_date"] == fecha_hoy:
                   # if (vieneConPerro()):
                    #    (crearTareaDePerro)
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
        endpoint = URL + f"public/inventory/v1/task/{task_id}"
        headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
        payload = {"scheduled_date": fecha_hoy}
        
        response = requests.patch(endpoint, json=payload, headers=headers)
        
        if response.status_code in [200,201,202,204]:
            return f"Tarea {task_id} movida a {fecha_hoy}."
        else:
            return f"Error moviendo tarea {task_id} a hoy: {response.status_code} {response.text}"
    except Exception as e:
        return f"Excepción moviendo tarea {task_id} a hoy: {e}"


def ponerEnHigh(task_id, token):
    try:
        endpoint = URL + f"public/inventory/v1/task/{task_id}"
        headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
        payload = {"type_priority": "high"}
        
        response = requests.patch(endpoint, json=payload, headers=headers)
        
        if response.status_code in [200,201,202,204]:
            return f"Tarea {task_id} actualizada a prioridad alta."
        else:
            return f"Error actualizando tarea {task_id} a prioridad alta: {response.status_code} {response.text}"
    except Exception as e:
        return f"Excepción actualizando tarea {task_id} a prioridad alta: {e}"

def corregirPrioridades(propertyID, token):
    respuesta_log = []
    try:
        endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={fecha_hoy},{fecha_hoy}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }
        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code in [200,201,202,204]:
            tasks = response.json()["results"]
            for task in tasks:
                estado = task["type_task_status"]["name"]
                if estado not in ["Finished", "Closed"]:
                    respuesta_log.append(ponerEnHigh(task["id"], token))
            return respuesta_log
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
    def espasado(fechaTarea):
        if fechaTarea is None:
            return True  
        fecha_hoy1 = datetime.strptime(fecha_hoy, "%Y-%m-%d")
        fecha_a_comparar = datetime.strptime(fechaTarea, "%Y-%m-%d")
        return fecha_a_comparar < fecha_hoy1
    try:
        year = datetime.now().year
        start_date = f"{year}-01-01"
        endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&created_at={start_date},{fecha_hoy}"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'JWT {token}'
        }

        response = requests.get(endpoint, headers=headers)
        
        # Verificar si la respuesta HTTP es exitosa
        if response.status_code in [200,201,202,204]:
            respuesta_log = []
            tasks = response.json()["results"]
            for task in tasks:
                respuesta_log.append(task["name"])
                estado = task["type_task_status"]["name"]
                if estado not in ["Finished", "Closed"]:
                    if espasado(task["scheduled_date"]):
                        respuesta_log.append(moverAHoy(task["id"], token))
            return respuesta_log
        else:
            # Levantar una excepción si la respuesta de la API no es exitosa
            raise Exception(f"Error al consultar tareas para mover {propertyID}: {response.status_code} - {response.text}")
            
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
    endpoint = URL + f"public/inventory/v1/property?company_id={COMPANY_ID}&limit=350"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'JWT {token}'
    }
    response = requests.get(endpoint, headers=headers)
    return response.json()

@app.function_name(name="operationautomation")
@app.schedule(schedule="0 53 21 * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False)
def operationautomation(myTimer: func.TimerRequest) -> None:
    token = conexionBreezeway()
    updates_log = []  # Para almacenar los logs de las actualizaciones
    if token:
         # Ejemplo de ID de propiedad
        propiedades = conseguirPropiedades(token)
        
        for propiedad in propiedades["results"]:
            propertyID=propiedad["reference_property_id"]
            if propertyID==None or propiedad["status"]!="active":
                continue
            updates_log.append(propiedad["name"] + ":" + str(moverLimpiezasConSusIncidencias(propertyID, token)))
            if hayReservaHoy(propertyID, token):              
                updates_log.append(propiedad["name"] + ":" + str(corregirPrioridades(propertyID, token)))

    else:
        raise BaseException("Error al acceder a breezeway")