import os, json, datetime
from typing import List, Dict, Any, Optional, Tuple, Set
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Zona horaria
ZONA_LOCAL = pytz.timezone("America/Argentina/Buenos_Aires")

# Calendarios (salas)
CALENDAR_IDS = {
    "Sala grande":  "dq9te3mprqg1ljp5tnjpb8v6ns@group.calendar.google.com",
    "Sala piano":   "4lagj76akl5n37gejf030qv3do@group.calendar.google.com",
    "Sala picola":  "mpncunafqtkig51qm35rs84t28@group.calendar.google.com",
    "Sala terraza": "adso7d591imkgl4s1e7vom5npk@group.calendar.google.com",
}

# Profes/Instrumentos (para hints y validaciones)
PROFES_VALIDOS = {"sam","fede","franco","francou","marcos",
                  "andrés","andres","tomas","tomás","pablo","ceci","sabri","lorenzo","tati"}  # extendible
INSTRUMENTOS_VALIDOS = {"piano","guitarra","bajo","batería","bateria","violín","violin",
                        "iniciación","iniciacion","armónica","armonica","acordeón","acordeon",
                        "cello","ukelele"}

# Preferencias/restricciones por instrumento
def salas_permitidas_por_instrumento(instr: Optional[str]) -> List[str]:
    if not instr:
        return list(CALENDAR_IDS.keys())
    i = instr.lower()
    if i in {"batería","bateria"}:
        return ["Sala piano","Sala terraza"]
    if i == "piano":
        # priorizamos piano/grande (las dos primeras), pero permitimos picola/terraza
        return ["Sala piano","Sala grande","Sala picola","Sala terraza"]
    # resto: cualquier sala
    return list(CALENDAR_IDS.keys())

def _build_service():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON","")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON no está definido.")
    creds = service_account.Credentials.from_service_account_info(json.loads(creds_json))
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def _to_local(dt_iso: str) -> datetime.datetime:
    # Acepta 'YYYY-MM-DD' (all-day) o RFC3339
    if "T" in dt_iso:
        return datetime.datetime.fromisoformat(dt_iso.replace("Z","+00:00")).astimezone(ZONA_LOCAL)
    else:
        # evento de todo el día
        base = datetime.datetime.fromisoformat(dt_iso + "T00:00:00").replace(tzinfo=pytz.utc).astimezone(ZONA_LOCAL)
        return base

def _parse_desc(summary: str) -> Tuple[Optional[str], Optional[str], str]:
    s = (summary or "").lower()
    # instrumento
    instr = None
    for i in INSTRUMENTOS_VALIDOS:
        if i in s:
            instr = "batería" if i in {"bateria"} else ("violín" if i in {"violin"} else ("armónica" if i in {"armonica"} else ("acordeón" if i in {"acordeon"} else i)))
            break
    # profe
    profe = None
    for p in PROFES_VALIDOS:
        if p in s:
            profe = "andrés" if p in {"andres"} else ("tomás" if p in {"tomas"} else p)
            break
    return instr, profe, s

def fetch_eventos(time_min: datetime.datetime, time_max: datetime.datetime) -> List[Dict[str,Any]]:
    """Devuelve eventos normalizados en la zona local, entre time_min y time_max (aware)."""
    service = _build_service()
    eventos_json: List[Dict[str,Any]] = []

    time_min_rfc3339 = time_min.astimezone(pytz.utc).isoformat()
    time_max_rfc3339 = time_max.astimezone(pytz.utc).isoformat()

    for sala, cal_id in CALENDAR_IDS.items():
        items = service.events().list(
            calendarId=cal_id,
            timeMin=time_min_rfc3339,
            timeMax=time_max_rfc3339,
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        for ev in items:
            try:
                start_str = ev["start"].get("dateTime", ev["start"].get("date"))
                end_str   = ev["end"].get("dateTime", ev["end"].get("date"))

                dt_start_local = _to_local(start_str)
                dt_end_local   = _to_local(end_str)

                # Bloquea el día completo si es all-day
                if "T" not in start_str and "T" not in end_str:
                    # cubrir todo el día [00:00, 23:59:59]
                    dt_end_local = dt_start_local.replace(hour=23, minute=59, second=59, microsecond=0)

                dur_min = max(0, int((dt_end_local - dt_start_local).total_seconds() // 60))
                summary = ev.get("summary","")
                instrumento, profe, alumno = _parse_desc(summary)

                eventos_json.append({
                    "id": ev.get("id"),
                    "sala": sala,
                    "start_local": dt_start_local.strftime("%Y-%m-%dT%H:%M"),
                    "end_local": dt_end_local.strftime("%Y-%m-%dT%H:%M"),
                    "start_iso": dt_start_local.astimezone(pytz.utc).isoformat(),
                    "end_iso": dt_end_local.astimezone(pytz.utc).isoformat(),
                    "duracion_min": dur_min,
                    "instrumento": instrumento,
                    "profe": profe,
                    "alumno": alumno,
                    "summary": summary,
                    "fecha": dt_start_local.strftime("%Y-%m-%d"),
                    "dia": dt_start_local.strftime("%A"),
                })
            except Exception as e:
                print(f"Error procesando evento: {e}")
                continue
    return eventos_json

def get_eventos(dias: int = 14) -> List[Dict[str,Any]]:
    hoy = datetime.datetime.now(ZONA_LOCAL).replace(hour=0, minute=0, second=0, microsecond=0)
    fin = hoy + datetime.timedelta(days=dias)
    return fetch_eventos(hoy, fin)

def _profes_presentes_por_dia(eventos: List[Dict[str,Any]]) -> Dict[str, Set[str]]:
    presentes: Dict[str, Set[str]] = {}
    for e in eventos:
        f = e["fecha"]
        p = e.get("profe")
        if p:
            presentes.setdefault(f, set()).add(p)
    return presentes

def _gaps(en_dia: List[Dict[str,Any]], fecha: str,
          sala: str, window_start: str, window_end: str) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """Huecos libres por sala en una fecha (local), dados eventos ya normalizados."""
    dia_dt = datetime.datetime.strptime(fecha, "%Y-%m-%d")
    ws_h, ws_m = map(int, window_start.split(":"))
    we_h, we_m = map(int, window_end.split(":"))

    day_start = ZONA_LOCAL.localize(dia_dt.replace(hour=ws_h, minute=ws_m, second=0, microsecond=0))
    day_end   = ZONA_LOCAL.localize(dia_dt.replace(hour=we_h, minute=we_m, second=0, microsecond=0))

    # eventos de esa sala en ese día, ordenados
    evs = [e for e in en_dia if e["sala"] == sala]
    evs.sort(key=lambda x: x["start_local"])

    gaps: List[Tuple[datetime.datetime, datetime.datetime]] = []
    cursor = day_start
    for e in evs:
        s = datetime.datetime.strptime(e["start_local"], "%Y-%m-%dT%H:%M").replace(tzinfo=ZONA_LOCAL)
        f = datetime.datetime.strptime(e["end_local"], "%Y-%m-%dT%H:%M").replace(tzinfo=ZONA_LOCAL)
        if f <= cursor:
            continue
        if s > cursor:
            # hueco [cursor, s]
            gaps.append((cursor, s))
        cursor = max(cursor, f)
    if cursor < day_end:
        gaps.append((cursor, day_end))
    return gaps

def disponibilidad(eventos: List[Dict[str,Any]],
                   start_date: str, end_date: str,
                   instrumento: Optional[str],
                   profe: Optional[str],
                   dur_min: Optional[int],
                   salas_csv: Optional[str],
                   window_start: str = "14:00",
                   window_end: str = "21:00") -> List[Dict[str,Any]]:
    """
    Calcula slots disponibles cumpliendo reglas:
    - franja libre >= 30 min
    - slot de 30/45/60
    - encastre válido (ofrece también opción que termine justo al inicio del siguiente evento)
    - si se pasa 'profe', sólo días donde ese profe ya tiene al menos 1 clase
    - restricciones por instrumento (batería, piano prioridad)
    """
    assert window_start < window_end, "window_start debe ser < window_end"

    # Profes presentes por día
    presentes = _profes_presentes_por_dia(eventos)

    # Fechas del rango
    d0 = datetime.datetime.strptime(start_date, "%Y-%m-%d")
    d1 = datetime.datetime.strptime(end_date, "%Y-%m-%d")
    total_dias = (d1 - d0).days + 1
    fechas = [(d0 + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(total_dias)]

    # Filtrado de salas
    salas = [s.strip() for s in (salas_csv.split(",") if salas_csv else salas_permitidas_por_instrumento(instrumento))]
    # Ordenar salas para priorizar piano/grande si instrumento = piano
    if (instrumento or "").lower() == "piano":
        prefer = ["Sala piano","Sala grande","Sala picola","Sala terraza"]
        salas.sort(key=lambda s: prefer.index(s) if s in prefer else 99)

    # Duraciones válidas
    duraciones = [dur_min] if dur_min in {30,45,60} else [30,45,60]

    # Indexar por fecha para acelerar
    ev_por_fecha: Dict[str, List[Dict[str,Any]]] = {}
    for e in eventos:
        ev_por_fecha.setdefault(e["fecha"], []).append(e)

    resultados: List[Dict[str,Any]] = []
    for fecha in fechas:
        # Si se pide un profe, debe estar presente ese día
        if profe:
            p = profe.lower()
            if p not in {x.lower() for x in presentes.get(fecha, set())}:
                # no ofrecer con ese profe; igual se pueden ofrecer salas sin profe (lo decide el GPT)
                continue

        en_dia = ev_por_fecha.get(fecha, [])
        for sala in salas:
            gaps = _gaps(en_dia, fecha, sala, window_start, window_end)
            for g_start, g_end in gaps:
                gap_min = int((g_end - g_start).total_seconds() // 60)
                if gap_min < 30:
                    continue

                for d in duraciones:
                    if d > gap_min:
                        continue
                    # 1) slot al inicio del hueco (cumple “no hay evento que empiece/termine dentro del rango”)
                    s1 = g_start
                    f1 = g_start + datetime.timedelta(minutes=d)
                    resultados.append({
                        "fecha": fecha,
                        "sala": sala,
                        "instrumento": instrumento,
                        "profe": profe,
                        "start_local": s1.strftime("%Y-%m-%dT%H:%M"),
                        "end_local": f1.strftime("%Y-%m-%dT%H:%M"),
                        "dur_min": d,
                        "tipo": "inicio_hueco"
                    })
                    # 2) slot encastre que termina justo al inicio del siguiente evento (si entra)
                    s2 = g_end - datetime.timedelta(minutes=d)
                    if s2 >= g_start:
                        resultados.append({
                            "fecha": fecha,
                            "sala": sala,
                            "instrumento": instrumento,
                            "profe": profe,
                            "start_local": s2.strftime("%Y-%m-%dT%H:%M"),
                            "end_local": g_end.strftime("%Y-%m-%dT%H:%M"),
                            "dur_min": d,
                            "tipo": "encastre_fin"
                        })

    # Quitar duplicados exactos
    uniq = {(r["sala"], r["start_local"], r["end_local"], r.get("profe") or "", r.get("instrumento") or ""): r for r in resultados}
    # Orden por fecha, sala, inicio
    ordenados = sorted(uniq.values(), key=lambda x: (x["fecha"], x["sala"], x["start_local"]))
    return ordenados
