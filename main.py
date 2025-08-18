# -*- coding: utf-8 -*-
from fastapi import FastAPI, Query, Header, HTTPException, Body
from typing import Optional
import datetime
import pytz
import os

from calendar_utils import (
    get_eventos,         # próximos N días normalizados
    fetch_eventos,       # eventos entre datetimes (aware)
    disponibilidad,      # calcula huecos con reglas de negocio
    ZONA_LOCAL,          # pytz.timezone("America/Argentina/Buenos_Aires")
    create_event,        # crea evento (soporta dry_run)
    cancel_event,        # cancela por event_id
)

app = FastAPI(title="ECM Agenda API")

# === Configuración ===
API_KEY = (os.environ.get("ECM_API_KEY", "") or "").strip()
DRY_RUN_DEFAULT = (os.environ.get("ECM_BOOK_DRY_RUN", "1") or "1").lower() in ("1", "true", "yes")

# === Auth helpers (acepta X-API-Key, Authorization: Bearer y 'valen' como fallback temporal) ===
def _extract_token(
    x_api_key: Optional[str],
    authorization: Optional[str],
    valen: Optional[str] = None,  # fallback por compatibilidad si tu Action aún usa "valen"
) -> Optional[str]:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
    if valen:
        return valen.strip()
    return None

def _auth(
    x_api_key: Optional[str] = None,
    authorization: Optional[str] = None,
    valen: Optional[str] = None,
) -> None:
    # Si no hay API_KEY configurada en el server, se permite acceso sin auth (no recomendado).
    if not API_KEY:
        return
    token = _extract_token(x_api_key, authorization, valen)
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")

# === Endpoints ===
@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Endpoints: /agenda, /availability, /book, /cancel"}

@app.get("/agenda")
def agenda(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end: Optional[str]   = Query(None, description="YYYY-MM-DD"),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),  # fallback temporal
):
    _auth(x_api_key, authorization, valen)
    if start and end:
        # OJO: ZONA_LOCAL es pytz; usamos replace(tzinfo=ZONA_LOCAL) para mantener compat con calendar_utils
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
    end:   str = Query(..., description="YYYY-MM-DD"),
    instrumento: Optional[str] = Query(None, description="piano/guitarra/batería/..."),
    profe: Optional[str]       = Query(None, description="sam/fede/franco/francou/marcos/..."),
    dur_min: Optional[int]     = Query(None, description="30|45|60"),
    salas: Optional[str]       = Query(None, description="CSV de salas (opcional)"),
    window_start: str          = Query("14:00"),
    window_end:   str          = Query("21:00"),
    x_api_key: Optional[str]   = Header(None),
    authorization: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),  # fallback temporal
):
    _auth(x_api_key, authorization, valen)
    d0 = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    d1 = datetime.datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    eventos = fetch_eventos(d0, d1 + datetime.timedelta(days=1))
    resp = disponibilidad(
        eventos=eventos,
        start_date=start, end_date=end,
        instrumento=instrumento, profe=profe,
        dur_min=dur_min, salas_csv=salas,
        window_start=window_start, window_end=window_end
    )
    return resp

@app.post("/book")
def book(
    payload: dict = Body(...),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),  # fallback temporal
):
    """
    Crea una reserva (modo prueba por defecto):
    Body de ejemplo:
    {
      "sala": "Sala piano",
      "start_local": "2025-08-23T16:00",
      "end_local":   "2025-08-23T16:45",
      "summary": "Piano - con Fede (Valentino)",
      "alumno": "Valentino",
      "profe": "fede",
      "instrumento": "piano",
      "idempotency_key": "uid-123",
      "enforce_profesor_presente": true,
      "dry_run": true
    }
    """
    _auth(x_api_key, authorization, valen)
    try:
        dry_run = payload.get("dry_run")
        if dry_run is None:
            dry_run = DRY_RUN_DEFAULT

        res = create_event(
            sala             = payload.get("sala"),
            start_local      = payload.get("start_local"),
            end_local        = payload.get("end_local"),
            summary          = payload.get("summary"),
            alumno           = payload.get("alumno"),
            profe            = payload.get("profe"),
            instrumento      = payload.get("instrumento"),
            idempotency_key  = payload.get("idempotency_key"),
            enforce_profesor_presente = payload.get("enforce_profesor_presente", True),
            dry_run          = dry_run
        )

        if dry_run and res.get("status") == "validated":
            res["status"] = "validated_dry_run"
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/cancel")
def cancel(
    payload: dict = Body(...),
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),  # fallback temporal
):
    """
    Cancela una reserva por ID:
    { "event_id": "xxxxxxxxxxxx", "sala": "Sala piano" }  # sala opcional
    """
    _auth(x_api_key, authorization, valen)
    try:
        res = cancel_event(event_id=payload.get("event_id"), sala=payload.get("sala"))
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# === Runner local ===
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
