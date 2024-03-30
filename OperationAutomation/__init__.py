import requests
import json
import azure.functions as func

URL = "https://api.breezeway.io/"
CLIENT_ID = "vn7uqu3ubj9zspgz16g0fff3g553vnd7"
CLIENT_SECRET = "6wfbx65utxf2tarrkj2m4097vv3pc40j"
COMPANY_ID = 8172

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
    token = response.json().get('token')  # Ajustar la clave según la respuesta real
    return token

def organizarTareas(token):
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
        data = organizarTareas(token)
        # Convertir 'data' a una cadena JSON para enviar en la respuesta HTTP si es necesario
        return func.HttpResponse(body=json.dumps(data), status_code=200, mimetype="application/json")
    else:
        return func.HttpResponse("Error al obtener token", status_code=400)
