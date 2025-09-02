# Importa las herramientas necesarias
import os
import json
from datetime import datetime
from flask import Flask, request
import gspread
import requests
from google.oauth2.service_account import Credentials

# --- CONFIGURACIÓN INICIAL ---
app = Flask(__name__)

# --- FUNCIONES AUXILIARES ---

def get_google_creds():
    """Carga las credenciales de Google desde la variable de entorno."""
    creds_json_str = os.environ.get('GOOGLE_CREDS_JSON')
    if not creds_json_str:
        raise ValueError("La variable de entorno GOOGLE_CREDS_JSON no está configurada.")
    
    creds_info = json.loads(creds_json_str)
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    return Credentials.from_service_account_info(creds_info, scopes=scopes)

def get_campaign_name(source_id):
    """Obtiene el nombre de la campaña a partir de un ID de origen (anuncio, adset, etc.)."""
    access_token = os.environ.get('META_GRAPH_API_TOKEN')
    if not access_token:
        print("Error: El token de la API de Meta no está configurado.")
        return "Token no configurado"

    # Esta es la nueva petición inteligente: pide el nombre de la campaña anidada
    url = f"https://graph.facebook.com/v23.0/{source_id}"
    params = {
        'fields': 'campaign{name}',
        'access_token': access_token
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        # El resultado ahora está anidado: data['campaign']['name']
        return data.get('campaign', {}).get('name', 'Nombre de campaña no encontrado')
    except requests.exceptions.RequestException as e:
        print(f"Error al contactar la API Graph de Meta: {e}")
        return "Error al obtener nombre"

def save_to_google_sheet(data_row):
    """Guarda una fila de datos en la hoja de cálculo de Google."""
    sheet_name = os.environ.get('SHEET_NAME')
    if not sheet_name:
        print("Error: El nombre de la hoja de Google (SHEET_NAME) no está configurado.")
        return

    try:
        creds = get_google_creds()
        client = gspread.authorize(creds)
        sheet = client.open(sheet_name).sheet1
        sheet.append_row(data_row, value_input_option='USER_ENTERED')
        print(f"Lead guardado en Google Sheet: {data_row}")
    except Exception as e:
        print(f"Error al escribir en Google Sheets: {e}")

# --- RUTA PRINCIPAL DEL WEBHOOK (VERSIÓN MEJORADA) ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # Verificación inicial del Webhook con Meta
    if request.method == 'GET':
        verify_token = os.environ.get('VERIFY_TOKEN')
        if request.args.get('hub.mode') == 'subscribe' and request.args.get('hub.verify_token') == verify_token:
            return request.args.get('hub.challenge', '')
        return 'Forbidden', 403

    # Procesamiento de notificaciones de nuevos leads
    if request.method == 'POST':
        data = request.get_json()
        print("Webhook recibido:", json.dumps(data, indent=2))

        try:
            entry = data.get('entry', [])
            if not entry: return 'OK', 200

            changes = entry[0].get('changes', [])
            if not changes: return 'OK', 200

            value = changes[0].get('value', {})
            if value.get('messaging_product') == 'whatsapp':

                # --- NUEVA SECCIÓN PARA CAPTURAR DATOS DEL CONTACTO ---
                contact_info = value.get('contacts', [{}])[0]
                contact_name = contact_info.get('profile', {}).get('name', 'Nombre no disponible')
                contact_wa_id = contact_info.get('wa_id', 'ID no disponible')
                # --- FIN DE LA NUEVA SECCIÓN ---

                if 'messages' in value:
                    message = value['messages'][0]
                    if 'referral' in message:
                        referral = message['referral']
                        source_id = referral.get('source_id')

                        if source_id:
                            campaign_name = get_campaign_name(source_id)
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                            # Lista de datos actualizada para incluir nombre y ID
                            new_lead_data = [
                                timestamp,
                                campaign_name,
                                source_id,
                                referral.get('ad_id', 'N/A'),
                                contact_name,      # Nuevo dato
                                contact_wa_id      # Nuevo dato
                            ]

                            # Aplicamos el filtro de prefijo de campaña
                            campaign_prefix = os.environ.get('CAMPAIGN_PREFIX', None)
                            if not campaign_prefix or campaign_name.startswith(campaign_prefix):
                                save_to_google_sheet(new_lead_data)
                            else:
                                print(f"Campaña '{campaign_name}' ignorada por no coincidir con el prefijo.")
        except (IndexError, KeyError) as e:
            print(f"Error procesando el payload del webhook: {e}")

        return 'OK', 200

# Punto de entrada para Render
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
