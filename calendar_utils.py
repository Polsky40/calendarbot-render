import json
import os
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
SERVICE_ACCOUNT_INFO = json.loads(os.environ['GOOGLE_CREDENTIALS_JSON'])

creds = service_account.Credentials.from_service_account_info(
    SERVICE_ACCOUNT_INFO, scopes=SCOPES
)

service = build('calendar', 'v3', credentials=creds)

# Lista de calendarios a consultar
CALENDARIOS = {
    "Piano": "piano@ecmusica.com",
    "Batería": "bateria@ecmusica.com",
    "Guitarra": "guitarra@ecmusica.com",
    "Sala grande": "salagrande@ecmusica.com",
    # Agregá los que quieras
}

def get_eventos():
    ahora = datetime.utcnow().isoformat() + 'Z'
    fin = (datetime.utcnow() + timedelta(days=14)).isoformat() + 'Z'
    eventos_todos = []

    for nombre, calendario_id in CALENDARIOS.items():
        eventos = (
            service.events()
            .list(calendarId=calendario_id, timeMin=ahora, timeMax=fin, singleEvents=True, orderBy='startTime')
            .execute()
            .get('items', [])
        )

        for evento in eventos:
            inicio = evento['start'].get('dateTime', evento['start'].get('date'))
            fin_ = evento['end'].get('dateTime', evento['end'].get('date'))

            try:
                hora_inicio = datetime.fromisoformat(inicio)
                hora_fin = datetime.fromisoformat(fin_)
                duracion = int((hora_fin - hora_inicio).total_seconds() / 60)
                fecha = hora_inicio.strftime('%Y-%m-%d')
                evento_obj = {
                    "fecha": fecha,
                    "hora_inicio": hora_inicio.strftime('%H:%M'),
                    "hora_fin": hora_fin.strftime('%H:%M'),
                    "titulo": evento.get('summary', 'Sin título'),
                    "calendario": nombre,
                    "duracion": duracion
                }
            except Exception as e:
                evento_obj = {
                    "fecha": inicio,
                    "hora_inicio": None,
                    "hora_fin": None,
                    "titulo": evento.get('summary', 'Sin título'),
                    "calendario": nombre,
                    "duracion": None
                }

            eventos_todos.append(evento_obj)

    return eventos_todos
