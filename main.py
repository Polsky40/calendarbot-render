# -*- coding: utf-8 -*-
from fastapi import FastAPI, Query, Header, HTTPException
from typing import Optional
import datetime
import pytz
import os  # <- importante

from calendar_utils import get_eventos, fetch_eventos, disponibilidad, ZONA_LOCAL

app = FastAPI(title="ECM Agenda API")

API_KEY = os.environ.get("ECM_API_KEY", "valen")  # setear en tu entorno

def _auth(x_api_key: Optional[str]) -> None:
    # Si definís ECM_API_KEY, el header debe venir y coincidir.
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")

@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Endpoints: /agenda, /availability"}

@app.get("/agenda")
def agenda(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD"),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    if start and end:
        d0 = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
        d1 = datetime.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
        eventos = fetch_eventos(d0, d1 + datetime.timedelta(days=1))
    else:
        eventos = get_eventos(dias=14)
    eventos.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    return eventos

@app.get("/availability")
def availability(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    instrumento: Optional[str] = Query(None, description="piano/guitarra/batería/..."),
    profe: Optional[str] = Query(None, description="sam/fede/franco/francou/marcos/..."),
    dur_min: Optional[int] = Query(None, description="30|45|60"),
    salas: Optional[str] = Query(None, description="CSV de salas (opcional)"),
    window_start: str = Query("14:00"),
    window_end: str = Query("21:00"),
    x_api_key: Optional[str] = Header(None),
):
    _auth(x_api_key)
    d0 = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    d1 = datetime.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    eventos = fetch_eventos(d0, d1 + datetime.timedelta(days=1))
    resp = disponibilidad(
        eventos=eventos,
        start_date=start,
        end_date=end,
        instrumento=instrumento,
        profe=profe,
        dur_min=dur_min,
        salas_csv=salas,
        window_start=window_start,
        window_end=window_end,
    )
    return resp

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
