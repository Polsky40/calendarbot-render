from fastapi import FastAPI
from calendar_utils import get_eventos
import datetime
import pytz

app = FastAPI()
zona_local = pytz.timezone("America/Argentina/Buenos_Aires")

def label_fecha(fecha_iso: str) -> str:
    """
    Convierte 'YYYY-MM-DD' a 'Jue 15/01' (para mostrar lindo).
    """
    y, m, d = map(int, fecha_iso.split("-"))
    dt = datetime.date(y, m, d)
    dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    return f"{dias[dt.weekday()]} {dt.strftime('%d/%m')}"

@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Visitá /agenda para ver la agenda."}

@app.get("/agenda")
def agenda():
    eventos = get_eventos()

    # Agrupar por fecha ISO (YYYY-MM-DD)
    agrupado = {}
    for ev in eventos:
        fecha = ev.get("fecha")
        if not fecha:
            continue
        agrupado.setdefault(fecha, []).append(ev)

    hoy = datetime.datetime.now(zona_local)
    lunes = (hoy - datetime.timedelta(days=hoy.weekday())).date()
    domingo = lunes + datetime.timedelta(days=13)
    titulo = f"📅 Agenda (2 semanas, del {lunes.strftime('%d/%m')} al {domingo.strftime('%d/%m')}):"

    lines = [titulo]
    if not agrupado:
        lines.append("\n⛔ No hay eventos cargados en los próximos 14 días.")
    else:
        for fecha_iso in sorted(agrupado.keys()):
            lines.append(f"\n📆 {label_fecha(fecha_iso)} ({fecha_iso})")

            # Orden por "calendario" (sala) y hora_inicio
            def sort_key(x):
                cal = x.get("calendario", "")
                hi = x.get("hora_inicio") or "99:99"  # all-day al final
                return (cal, hi)

            for e in sorted(agrupado[fecha_iso], key=sort_key):
                cal = e.get("calendario", "")
                titulo_ev = e.get("titulo", "Sin título")

                hora_inicio = e.get("hora_inicio") or ""
                hora_fin = e.get("hora_fin") or ""
                duracion = e.get("duracion")

                if hora_inicio and hora_fin:
                    duracion_txt = f" ({duracion} min)" if duracion else ""
                    lines.append(f"  {hora_inicio} - {hora_fin}{duracion_txt} - {titulo_ev} ({cal})")
                else:
                    lines.append(f"  Todo el día - {titulo_ev} ({cal})")

    return {"agenda": "\n".join(lines)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("mainrestore:app", host="0.0.0.0", port=8000, reload=True)
