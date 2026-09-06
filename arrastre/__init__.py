import requests
import logging
import azure.functions as func
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID = 8172

# Los ThreadPoolExecutor iban sin limite (32 hilos por defecto) y ademas
# anidados: uno por propiedad y otro por tarea dentro de cada propiedad, o sea
# cientos de peticiones simultaneas contra Breezeway. De ahi los "403 - <html>"
# del log, que son bloqueo de proxy y no error de la API. 6x4 = 24 como maximo.
MAX_WORKERS_PROPIEDADES = 6
MAX_WORKERS_TAREAS = 4

def fecha():
    zona_horaria_españa = ZoneInfo("Europe/Madrid")
    fecha_hoy_utc = datetime.now(timezone.utc)
    fecha_hoy = fecha_hoy_utc.astimezone(zona_horaria_españa)
    fecha_hoy = fecha_hoy + timedelta(days=1)
    fecha_hoy_str = fecha_hoy.strftime("%Y-%m-%d")
    logging.info(f"Fecha planificada: {fecha_hoy_str}")
    return fecha_hoy_str

# ============================================================================
# LOGICA DE PRIORIDADES DESACTIVADA (comentada, no borrada)
#
# Se comenta a peticion: ya no se sube la prioridad de las tareas.
# Con ella queda sin uso hayReservaHoy(), que solo existia para decidir si
# habia que corregir prioridades en esa propiedad. Comentarla ahorra ademas
# ~250 llamadas HTTP por ejecucion (una por propiedad), que eran la mitad
# del total.
#
# Para reactivarlo: descomentar este bloque y la llamada marcada en
# procesarPropiedad().
# ============================================================================
# def hayReservaHoy(propertyID, token):
#     if propertyID is None:
#         return False
#     fecha_hoy = fecha()
#     logging.info(f"Verificando reservas para propiedad {propertyID} en fecha {fecha_hoy}")
#     endpoint = URL + f"public/inventory/v1/reservation/external-id?reference_property_id={propertyID}"
#     headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
#     response = requests.get(endpoint, headers=headers)
#     if response.status_code in [200, 201, 202, 204]:
#         reservas = response.json()
#         for reserva in reservas:
#             if reserva["checkin_date"] == fecha_hoy:
#                 logging.info(f"Reserva encontrada para propiedad {propertyID} en fecha {fecha_hoy}")
#                 return True
#         return False
#     else:
#         raise Exception(f"Error al consultar reservas: {response.status_code} - {response.text}")
#
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

# def ponerEnHigh(task_id, token):
#     logging.info(f"Actualizando prioridad a alta para tarea {task_id}")
#     endpoint = URL + f"public/inventory/v1/task/{task_id}"
#     headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
#     payload = {"type_priority": "high"}
#     response = requests.patch(endpoint, json=payload, headers=headers)
#     if response.status_code in [200, 201, 202, 204]:
#         return f"Tarea {task_id} actualizada a prioridad alta."
#     else:
#         return f"Error actualizando tarea {task_id} a prioridad alta: {response.status_code} {response.text}"
#
# def corregirPrioridades(propertyID, token, property_name):
#     fecha_hoy = fecha()
#     logging.info(f"Propiedad {property_name}: Corrigiendo prioridades para tareas con fecha {fecha_hoy}")
#     respuesta_log = []
#     endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&scheduled_date={fecha_hoy},{fecha_hoy}"
#     headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
#     response = requests.get(endpoint, headers=headers)
#     if response.status_code in [200, 201, 202, 204]:
#         tasks = response.json()["results"]
#         with ThreadPoolExecutor(max_workers=MAX_WORKERS_TAREAS) as executor:
#             futures = [
#                 executor.submit(ponerEnHigh, task["id"], token)
#                 for task in tasks
#                 if task["type_task_status"]["name"] not in ["Finished", "Closed"]
#                    and (logging.info(f"Propiedad {property_name}: Actualizando prioridad para tarea {task.get('name', 'Sin nombre')}") or True)
#             ]
#             for future in as_completed(futures):
#                 respuesta_log.append(future.result())
#         return respuesta_log
#     else:
#         raise Exception(f"Error al consultar tareas: {response.status_code} - {response.text}")
#
def moverLimpiezasConSusIncidencias(propertyID, token, property_name):
    fecha_hoy = fecha()

    def espasado(fechaTarea):
        if fechaTarea is None:
            return True
        fecha_hoy_dt = datetime.strptime(fecha_hoy, "%Y-%m-%d")
        fecha_tarea_dt = datetime.strptime(fechaTarea, "%Y-%m-%d")
        return fecha_tarea_dt < fecha_hoy_dt

    year = datetime.now().year
    start_date = f"{year}-01-01"
    logging.info(f"Propiedad {property_name} (ID: {propertyID}): Buscando tareas desde {start_date} hasta {fecha_hoy}")
    endpoint = URL + f"public/inventory/v1/task/?reference_property_id={propertyID}&created_at={start_date},{fecha_hoy}&sort_order=desc"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    response = requests.get(endpoint, headers=headers)

    if response.status_code in [200, 201, 202]:
        respuesta_log = []
        tasks = response.json()["results"]
        with ThreadPoolExecutor(max_workers=MAX_WORKERS_TAREAS) as executor:
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
    payload = {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}
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
    endpoint = URL + f"public/inventory/v1/property?company_id={COMPANY_ID}&limit=450"
    headers = {'Content-Type': 'application/json', 'Authorization': f'JWT {token}'}
    response = requests.get(endpoint, headers=headers)
    return response.json()

def procesarPropiedad(propiedad, token):
    """Todo el trabajo de una propiedad, dentro de UN hilo.

    Antes hayReservaHoy() se llamaba desde el hilo principal, dentro del mismo
    bucle que repartia el trabajo: eran ~250 llamadas HTTP en serie por
    ejecucion que imponian un suelo de varios minutos, al margen de cuantos
    hilos hubiera. Por eso ninguna ejecucion bajaba nunca de 60 segundos.

    Los dos pasos se aislan entre si: antes eran dos futures independientes, y
    al juntarlos aqui un fallo en el primero dejaria sin ejecutar el segundo.
    """
    propertyID = propiedad["reference_property_id"]
    property_name = propiedad["name"]
    resultado = []

    try:
        resultado += moverLimpiezasConSusIncidencias(propertyID, token, property_name) or []
    except Exception as e:
        resultado.append(f"Error moviendo limpiezas: {e}")

    # DESACTIVADO: correccion de prioridades (ver bloque comentado arriba).
    # try:
    #     if hayReservaHoy(propertyID, token):
    #         resultado += corregirPrioridades(propertyID, token, property_name) or []
    # except Exception as e:
    #     resultado.append(f"Error corrigiendo prioridades: {e}")

    return resultado

def main(myTimer: func.TimerRequest) -> None:
    logging.info("Iniciando la función principal")
    token = conexionBreezeway()
    updates_log = []
    fecha_hoy = fecha()

    if token:
        propiedades = conseguirPropiedades(token)
        logging.info(f"Propiedades obtenidas: {len(propiedades.get('results', []))} encontradas")

        propiedades_activas = [
            p for p in propiedades["results"]
            if p.get("reference_property_id") is not None and p.get("status") == "active"
        ]
        omitidas = len(propiedades["results"]) - len(propiedades_activas)
        if omitidas:
            logging.info(f"{omitidas} propiedades omitidas (ID nulo o inactivas)")
        logging.info(f"Propiedades a procesar: {len(propiedades_activas)}")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS_PROPIEDADES) as executor:
            futures = {
                executor.submit(procesarPropiedad, propiedad, token): propiedad["name"]
                for propiedad in propiedades_activas
            }

            for future in as_completed(futures):
                prop_name = futures[future]
                try:
                    result = future.result()
                    updates_log.append(f"{prop_name}: {result}")
                    logging.info(f"Resultado para propiedad {prop_name}: {result}")
                except Exception as e:
                    logging.error(f"Propiedad {prop_name}: Error durante el procesamiento: {e}")

        logging.info("Función principal completada.")
    else:
        logging.error("Error al acceder a Breezeway")
        raise BaseException("Error al acceder a Breezeway")