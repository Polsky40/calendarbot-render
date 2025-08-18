from fastapi import FastAPI, Query
from calendar_utils import get_eventos
import datetime
import pytz

app = FastAPI()
zona_local = pytz.timezone("America/Argentina/Buenos_Aires")

@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Visitá /agenda para ver la agenda."}

@app.get("/agenda")
def agenda():
    eventos = get_eventos()
    agrupado = {}
    for ev in eventos:
        agrupado.setdefault(ev['fecha'], []).append(ev)

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
            for e in sorted(agrupado[fecha], key=lambda x: (x["calendario"], x["hora_inicio"])):
                if e['hora_inicio'] and e['hora_fin']:
                    duracion_txt = f" ({e['duracion']} min)" if e['duracion'] else ""
                    lines.append(f"  {e['hora_inicio']} - {e['hora_fin']}{duracion_txt} - {e['titulo']} ({e['calendario']})")
                else:
                    lines.append(f"  Todo el día - {e['titulo']} ({e['calendario']})")

    return {"agenda": "\n".join(lines)}


@app.get("/buscar_horario")
def buscar_horario(
    duracion: int = Query(..., ge=30, le=60),
    hora_preferencia: str = "18:30",
    profesor: str = None,
    sala: str = None
):
    eventos = get_eventos()
    hoy = datetime.datetime.now(zona_local)
    lunes = hoy - datetime.timedelta(days=hoy.weekday())
    domingo = lunes + datetime.timedelta(days=13)

    agenda_por_dia = {}
    for e in eventos:
        if not (e['hora_inicio'] and e['hora_fin']):
            continue
        dia = e['fecha']
        agenda_por_dia.setdefault(dia, []).append(e)

    resultados = []

    for dia, eventos_dia in agenda_por_dia.items():
        disponibles = buscar_huecos_disponibles(
            eventos_dia,
            duracion,
            hora_preferencia,
            profesor,
            sala
        )
        if disponibles:
            resultados.append({
                "fecha": dia,
                "opciones": disponibles
            })

    return {"resultados": resultados}


def buscar_huecos_disponibles(eventos_dia, duracion, hora_preferencia, profesor, sala):
    from datetime import datetime, timedelta

    disponibles = []
    preferida_dt = datetime.strptime(hora_preferencia, "%H:%M")

    # Agrupar eventos por sala y profe
    por_sala_prof = {}
    for e in eventos_dia:
        key = (e['calendario'], e['titulo'])  # sala, profesor
        por_sala_prof.setdefault(key, []).append(e)

    for (sala_ev, prof_ev), evs in por_sala_prof.items():
        if sala and sala.lower() != sala_ev.lower():
            continue
        if profesor and profesor.lower() not in prof_ev.lower():
            continue

        evs_ordenados = sorted(evs, key=lambda x: x['hora_inicio'])
        hora_anterior = datetime.strptime("08:00", "%H:%M")

        for e in evs_ordenados:
            inicio = datetime.strptime(e['hora_inicio'], "%H:%M")
            delta = (inicio - hora_anterior).total_seconds() / 60
            if delta >= duracion:
                nuevo_inicio = hora_anterior
                nuevo_fin = nuevo_inicio + timedelta(minutes=duracion)
                if nuevo_inicio.time() == preferida_dt.time():
                    disponibles.append({
                        "sala": sala_ev,
                        "profesor": prof_ev,
                        "hora_inicio": nuevo_inicio.strftime("%H:%M"),
                        "hora_fin": nuevo_fin.strftime("%H:%M")
                    })
            hora_anterior = datetime.strptime(e['hora_fin'], "%H:%M")

        # Revisa hueco final del día
        fin_jornada = datetime.strptime("21:00", "%H:%M")
        delta_final = (fin_jornada - hora_anterior).total_seconds() / 60
        if delta_final >= duracion:
            nuevo_inicio = hora_anterior
            nuevo_fin = nuevo_inicio + timedelta(minutes=duracion)
            if nuevo_inicio.time() == preferida_dt.time():
                disponibles.append({
                    "sala": sala_ev,
                    "profesor": prof_ev,
                    "hora_inicio": nuevo_inicio.strftime("%H:%M"),
                    "hora_fin": nuevo_fin.strftime("%H:%M")
                })

    return disponibles


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
