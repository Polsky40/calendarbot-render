from fastapi import FastAPI
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
