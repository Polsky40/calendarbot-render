import os
import json
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

# CONFIGURACIÓN
zona_local = pytz.timezone("America/Argentina/Buenos_Aires")

CALENDAR_IDS = {
    "Sala grande": "dq9te3mprqg1ljp5tnjpb8v6ns@group.calendar.google.com",
    "Sala piano": "4lagj76akl5n37gejf030qv3do@group.calendar.google.com",
    "Sala picola": "mpncunafqtkig51qm35rs84t28@group.calendar.google.com",
    "Sala terraza": "adso7d591imkgl4s1e7vom5npk@group.calendar.google.com",
}

def get_eventos():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not creds_json:
        raise ValueError("La variable de entorno GOOGLE_CREDENTIALS_JSON está vacía o no definida.")

    try:
        creds_dict = json.loads(creds_json)
    except json.JSONDecodeError as e:
        raise ValueError("Error al decodificar GOOGLE_CREDENTIALS_JSON: " + str(e))

    creds = service_account.Credentials.from_service_account_info(creds_dict)
    service = build('calendar', 'v3', credentials=creds)

    hoy = datetime.datetime.now(zona_local)
    inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = inicio + datetime.timedelta(days=14)
    time_min = inicio.astimezone(pytz.utc).isoformat()
    time_max = fin.astimezone(pytz.utc).isoformat()

    eventos_json = []
    for nombre_cal, cal_id in CALENDAR_IDS.items():
        try:
            eventos = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])
        except Exception as e:
            print(f"Error al acceder al calendario {nombre_cal}: {e}")
            continue

        for event in eventos:
            try:
                start_str = event['start'].get('dateTime', event['start'].get('date'))
                end_str = event['end'].get('dateTime', event['end'].get('date'))
                if 'T' in start_str:
                    dt_start = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00')).astimezone(zona_local)
                    dt_end = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00')).astimezone(zona_local)
                    hora_inicio = dt_start.strftime('%H:%M')
                    hora_fin = dt_end.strftime('%H:%M')
                    duracion_min = int((dt_end - dt_start).total_seconds() // 60)
                else:
                    hora_inicio = hora_fin = ''
                    duracion_min = None
                    dt_start = datetime.datetime.fromisoformat(start_str + "T00:00:00").astimezone(zona_local)

                eventos_json.append({
                    "calendario": nombre_cal,
                    "fecha": dt_start.strftime('%A %d/%m'),
                    "hora_inicio": hora_inicio,
                    "hora_fin": hora_fin,
                    "duracion": duracion_min,
                    "titulo": event.get('summary', 'Sin título'),
                })
            except Exception as e:
                print(f"Error procesando evento: {e}")
                continue

    return eventos_json
