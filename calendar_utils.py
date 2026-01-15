import os
import json
import datetime
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
zona_local = pytz.timezone("America/Argentina/Buenos_Aires")

CALENDAR_IDS = {
    "Sala grande": "dq9te3mprqg1ljp5tnjpb8v6ns@group.calendar.google.com",
    "Sala piano": "4lagj76akl5n37gejf030qv3do@group.calendar.google.com",
    "Sala piccola": "mpncunafqtkig51qm35rs84t28@group.calendar.google.com",  # ojo: renombré "picola" -> "piccola"
    "Sala terraza": "adso7d591imkgl4s1e7vom5npk@group.calendar.google.com",
}

def _parse_dt(value: str) -> datetime.datetime:
    """
    Convierte dateTime ISO (con Z o con offset) a datetime aware en zona_local.
    """
    # Google suele devolver 'Z' en UTC
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(zona_local)

def _localize_date(date_str: str) -> datetime.datetime:
    """
    Para eventos all-day: date_str viene como 'YYYY-MM-DD'.
    Creamos un datetime local a medianoche en zona_local (aware).
    """
    y, m, d = map(int, date_str.split("-"))
    return zona_local.localize(datetime.datetime(y, m, d, 0, 0, 0))

def get_eventos():
    service_account_info = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    service = build("calendar", "v3", credentials=creds)

    hoy = datetime.datetime.now(zona_local)
    inicio = hoy.replace(hour=0, minute=0, second=0, microsecond=0)
    fin = inicio + datetime.timedelta(days=14)

    time_min = inicio.astimezone(pytz.utc).isoformat()
    time_max = fin.astimezone(pytz.utc).isoformat()

    eventos_json = []

    for nombre_cal, cal_id in CALENDAR_IDS.items():
        items = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                showDeleted=False,
                maxResults=2500,
            )
            .execute()
            .get("items", [])
        )

        for event in items:
            start = event.get("start", {})
            end = event.get("end", {})

            start_dt = start.get("dateTime")
            start_date = start.get("date")
            end_dt = end.get("dateTime")
            end_date = end.get("date")

            # Timed event
            if start_dt and end_dt:
                dt_start = _parse_dt(start_dt)
                dt_end = _parse_dt(end_dt)

                hora_inicio = dt_start.strftime("%H:%M")
                hora_fin = dt_end.strftime("%H:%M")
                duracion_min = int((dt_end - dt_start).total_seconds() // 60)

                fecha_iso = dt_start.date().isoformat()

            # All-day event
            elif start_date and end_date:
                # En all-day, end.date es el día siguiente (fin exclusivo).
                dt_start = _localize_date(start_date)
                fecha_iso = dt_start.date().isoformat()

                hora_inicio = ""
                hora_fin = ""
                duracion_min = None

            else:
                # evento raro/incompleto
                continue

            eventos_json.append(
                {
                    "calendario": nombre_cal,
                    "sala": nombre_cal,  # alias explícito
                    "fecha": fecha_iso,  # ✅ CLAVE: YYYY-MM-DD
                    "hora_inicio": hora_inicio,
                    "hora_fin": hora_fin,
                    "duracion": duracion_min,
                    "titulo": event.get("summary", "Sin título"),
                    "event_id": event.get("id"),
                }
            )

    # Orden estable para consumo
    eventos_json.sort(key=lambda e: (e["fecha"], e["calendario"], e["hora_inicio"] or ""))
    return eventos_json
