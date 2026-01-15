from fastapi import FastAPI, Query
from typing import Optional, List, Dict, Tuple
from calendar_utils import get_eventos
import datetime
import pytz
import re

app = FastAPI()
zona_local = pytz.timezone("America/Argentina/Buenos_Aires")

# -----------------------------
# Normalización / parse helpers
# -----------------------------

ROOM_ALIASES = {
    "piano": ["piano", "sala piano"],
    "grande": ["grande", "sala grande"],
    "piccola": ["picola", "piccola", "sala picola", "sala piccola"],
    "terraza": ["terraza", "terrazza", "sala terraza"],
}

ALL_ROOMS = ["piano", "grande", "piccola", "terraza"]

TIME_RE = re.compile(r"^\d{2}:\d{2}$")

def normalize_room(calendario: str) -> str:
    c = (calendario or "").strip().lower()
    for room, aliases in ROOM_ALIASES.items():
        if any(a in c for a in aliases):
            return room
    return c or "desconocida"

def parse_hhmm(hhmm: str) -> datetime.time:
    if not TIME_RE.match(hhmm):
        raise ValueError(f"Hora inválida: {hhmm} (formato HH:MM)")
    h, m = hhmm.split(":")
    return datetime.time(int(h), int(m), 0)

def parse_date_any(date_str: str) -> datetime.date:
    """
    Acepta 'YYYY-MM-DD' o 'DD/MM/YYYY'.
    """
    s = (date_str or "").strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        y, m, d = map(int, s.split("-"))
        return datetime.date(y, m, d)
    if re.match(r"^\d{2}/\d{2}/\d{4}$", s):
        d, m, y = map(int, s.split("/"))
        return datetime.date(y, m, d)
    raise ValueError(f"Fecha inválida: {date_str} (usar YYYY-MM-DD o DD/MM/YYYY)")

def date_to_iso(d: datetime.date) -> str:
    return d.isoformat()

def dt_on_date(date_str: str, hhmm: str) -> datetime.datetime:
    d = parse_date_any(date_str)
    t = parse_hhmm(hhmm)
    dt = datetime.datetime(d.year, d.month, d.day, t.hour, t.minute, 0)
    return zona_local.localize(dt)

def minus_one_min(dt: datetime.datetime) -> datetime.datetime:
    return dt - datetime.timedelta(minutes=1)

def minutes_between(a: datetime.datetime, b: datetime.datetime) -> int:
    return int((b - a).total_seconds() // 60)

def clamp_interval(s: datetime.datetime, e: datetime.datetime, ws: datetime.datetime, we: datetime.datetime):
    s2, e2 = max(s, ws), min(e, we)
    if s2 >= e2:
        return None
    return (s2, e2)

def merge_intervals(intervals: List[Tuple[datetime.datetime, datetime.datetime]]) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    """
    Merge de intervalos ocupados (asume start<=end).
    Considera 'pegados' como un solo bloque ocupado si s <= prev_end.
    """
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged

def compute_free(busy_merged: List[Tuple[datetime.datetime, datetime.datetime]],
                 ws: datetime.datetime, we: datetime.datetime) -> List[Tuple[datetime.datetime, datetime.datetime]]:
    free = []
    cursor = ws
    for s, e in busy_merged:
        if cursor < s:
            free.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < we:
        free.append((cursor, we))
    return free

# -----------------------------
# Endpoints
# -----------------------------

@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Visitá /agenda para ver la agenda. También tenés /agenda_json y /salas_libres."}

@app.get("/agenda")
def agenda():
    """
    Mantiene tu endpoint original: devuelve un texto grande dentro de {"agenda": "..."}.
    """
    eventos = get_eventos()
    agrupado: Dict[str, List[dict]] = {}
    for ev in eventos:
        fecha = ev.get("fecha")
        if not fecha:
            continue
        agrupado.setdefault(fecha, []).append(ev)

    hoy = datetime.datetime.now(zona_local)
    lunes = hoy - datetime.timedelta(days=hoy.weekday())
    domingo = lunes + datetime.timedelta(days=13)
    titulo = f"📅 Agenda (2 semanas, del {lunes.strftime('%d/%m')} al {domingo.strftime('%d/%m')}):"

    lines = [titulo]
    if not agrupado:
        lines.append("\n⛔ No hay eventos cargados en los próximos 14 días.")
    else:
        for fecha in sorted(agrupado):
            lines.append(f"\n📆 {fecha}")
            for e in sorted(agrupado[fecha], key=lambda x: (x.get("calendario",""), x.get("hora_inicio",""))):
                if e.get("hora_inicio") and e.get("hora_fin"):
                    duracion_txt = f" ({e.get('duracion')} min)" if e.get("duracion") else ""
                    lines.append(f"  {e['hora_inicio']} - {e['hora_fin']}{duracion_txt} - {e.get('titulo','')} ({e.get('calendario','')})")
                else:
                    lines.append(f"  Todo el día - {e.get('titulo','')} ({e.get('calendario','')})")

    return {"agenda": "\n".join(lines)}

@app.get("/agenda_json")
def agenda_json(
    from_date: Optional[str] = Query(default=None, description="YYYY-MM-DD o DD/MM/YYYY (default: hoy)"),
    to_date: Optional[str] = Query(default=None, description="YYYY-MM-DD o DD/MM/YYYY (default: hoy+13)"),
    room: Optional[str] = Query(default=None, description="piano|grande|piccola|terraza"),
    teacher: Optional[str] = Query(default=None, description="Filtra por texto dentro de 'titulo' (simple)"),
):
    """
    Devuelve eventos estructurados (para que el GPT no 'interprete' texto).
    """
    eventos = get_eventos()

    hoy = datetime.datetime.now(zona_local).date()
    start = parse_date_any(from_date) if from_date else hoy
    end = parse_date_any(to_date) if to_date else (hoy + datetime.timedelta(days=13))

    room_norm = room.strip().lower() if room else None
    teacher_l = teacher.strip().lower() if teacher else None

    out = []
    for ev in eventos:
        fecha_raw = ev.get("fecha")
        if not fecha_raw:
            continue

        try:
            f = parse_date_any(fecha_raw)
        except Exception:
            # si algún evento trae fecha rara, lo salteamos
            continue

        if f < start or f > end:
            continue

        room_ev = normalize_room(ev.get("calendario", ""))
        if room_norm and room_ev != room_norm:
            continue

        title = (ev.get("titulo") or "")
        if teacher_l and teacher_l not in title.lower():
            continue

        # end_real para cálculo/razonamiento (si hay horas)
        end_real = None
        if ev.get("hora_fin"):
            try:
                end_real = minus_one_min(dt_on_date(fecha_raw, ev["hora_fin"])).strftime("%H:%M")
            except Exception:
                end_real = None

        out.append({
            "date": date_to_iso(f),
            "room": room_ev,
            "calendar": ev.get("calendario"),
            "start": ev.get("hora_inicio"),
            "end": ev.get("hora_fin"),
            "end_real": end_real,
            "duration": ev.get("duracion"),
            "title": title,
        })

    out.sort(key=lambda x: (x["date"], x["room"], x["start"] or ""))
    return {
        "timezone": "America/Argentina/Buenos_Aires",
        "range": {"from": date_to_iso(start), "to": date_to_iso(end)},
        "events": out
    }

@app.get("/salas_libres")
def salas_libres(
    date: str = Query(..., description="YYYY-MM-DD o DD/MM/YYYY"),
    window_from: str = Query(..., alias="from", description="HH:MM"),
    window_to: str = Query(..., alias="to", description="HH:MM"),
    min_minutes: int = Query(30, alias="min", ge=1, description="mínimo de minutos para considerar hueco"),
):
    """
    Devuelve BUSY y FREE por sala dentro de una ventana horaria,
    aplicando la regla ECM: fin real = fin - 1 minuto.
    """
    eventos = get_eventos()

    ws = dt_on_date(date, window_from)
    we = dt_on_date(date, window_to)

    # Agrupar BUSY por sala
    busy_by_room: Dict[str, List[Tuple[datetime.datetime, datetime.datetime]]] = {r: [] for r in ALL_ROOMS}

    for ev in eventos:
        fecha_raw = ev.get("fecha")
        if not fecha_raw:
            continue

        try:
            f = parse_date_any(fecha_raw)
            target = parse_date_any(date)
        except Exception:
            continue

        if f != target:
            continue

        room_ev = normalize_room(ev.get("calendario", ""))

        # si llega una sala desconocida, la ignoramos (o podés sumarla)
        if room_ev not in busy_by_room:
            continue

        # Evento todo el día: bloquea toda la ventana
        if not ev.get("hora_inicio") or not ev.get("hora_fin"):
            busy_by_room[room_ev].append((ws, we))
            continue

        try:
            s = dt_on_date(date, ev["hora_inicio"])
            e = dt_on_date(date, ev["hora_fin"])
        except Exception:
            continue

        e_real = minus_one_min(e)
        clamped = clamp_interval(s, e_real, ws, we)
        if clamped:
            busy_by_room[room_ev].append(clamped)

    rooms_out = []
    for room in ALL_ROOMS:
        merged = merge_intervals(busy_by_room.get(room, []))
        free = compute_free(merged, ws, we)

        busy_out = [[s.strftime("%H:%M"), e.strftime("%H:%M")] for s, e in merged]

        free_out = []
        for fs, fe in free:
            mins = minutes_between(fs, fe)
            if mins >= min_minutes:
                free_out.append([fs.strftime("%H:%M"), fe.strftime("%H:%M"), mins])

        rooms_out.append({
            "room": room,
            "busy": busy_out,
            "free": free_out
        })

    return {
        "timezone": "America/Argentina/Buenos_Aires",
        "date": date_to_iso(parse_date_any(date)),
        "from": window_from,
        "to": window_to,
        "min": min_minutes,
        "rooms": rooms_out
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
