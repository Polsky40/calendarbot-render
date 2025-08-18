# app.py  —  ECM Agenda API (sin autenticación)
# ----------------------------------------------
from fastapi import FastAPI, Query, Body, HTTPException
from typing import Optional
import datetime
import os

from calendar_utils import (
    get_eventos,         # próximos N días normalizados
    fetch_eventos,       # eventos entre datetimes (aware)
    disponibilidad,      # calcula huecos con reglas del asistente
    ZONA_LOCAL,          # pytz.timezone("America/Argentina/Buenos_Aires")
    create_event,        # crea evento (respeta dry_run)
    cancel_event,        # cancela por event_id
)

app = FastAPI(title="ECM Agenda API (no-auth)")

# --- Controles de escritura (para que sea seguro sin key) ---
# Por defecto, NO se permiten escrituras reales.
WRITE_ENABLED   = (os.environ.get("ECM_ALLOW_WRITE", "0") or "0").lower() in ("1", "true", "yes")
DRY_RUN_DEFAULT = (os.environ.get("ECM_BOOK_DRY_RUN", "1") or "1").lower() in ("1", "true", "yes")

@app.get("/")
def root():
    return {
        "mensaje": "¡API sin autenticación funcionando!",
        "endpoints": ["/agenda", "/availability", "/book", "/cancel"],
        "writes_enabled": WRITE_ENABLED,
        "dry_run_default": DRY_RUN_DEFAULT,
    }

@app.get("/agenda")
def agenda(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end:   Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    if start and end:
        # Mantengo el mismo criterio de calendar_utils: datetimes aware con la ZONA_LOCAL
        d0 = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
        d1 = datetime.datetime.strptime(end,   "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
        eventos = fetch_eventos(d0, d1 + datetime.timedelta(days=1))
    else:
        eventos = get_eventos(dias=14)

    # Orden: fecha, sala, hora inicio (como venías usando)
    eventos.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    return eventos

@app.get("/availability")
def availability(
    start: str = Query(..., description="YYYY-MM-DD"),
    end:   str = Query(..., description="YYYY-MM-DD"),
    instrumento: Optional[str] = Query(None, description="piano/guitarra/batería/..."),
    profe:       Optional[str] = Query(None, description="sam/fede/franco/francou/marcos/..."),
    dur_min:     Optional[int] = Query(None, description="30|45|60"),
    salas:       Optional[str] = Query(None, description="CSV de salas (opcional)"),
    window_start: str = Query("14:00"),
    window_end:   str = Query("21:00"),
):
    d0 = datetime.datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    d1 = datetime.datetime.strptime(end,   "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
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
def book(payload: dict = Body(...)):
    """
    Crea una reserva. Por defecto y sin key, corre en dry_run.
    Para habilitar escritura real, setea ECM_ALLOW_WRITE=1 en el entorno.
    """
    try:
        # Si no están habilitadas las escrituras, siempre forzamos dry_run=True
        dry_run = payload.get("dry_run", DRY_RUN_DEFAULT) or True
        if not WRITE_ENABLED:
            dry_run = True

        res = create_event(
            sala                    = payload.get("sala"),
            start_local             = payload.get("start_local"),
            end_local               = payload.get("end_local"),
            summary                 = payload.get("summary"),
            alumno                  = payload.get("alumno"),
            profe                   = payload.get("profe"),
            instrumento             = payload.get("instrumento"),
            idempotency_key         = payload.get("idempotency_key"),
            enforce_profesor_presente = payload.get("enforce_profesor_presente", True),
            dry_run                 = dry_run,
        )

        if dry_run and res.get("status") == "validated":
            res["status"] = "validated_dry_run"
        if not WRITE_ENABLED:
            res["note"] = "WRITE_DISABLED: Setea ECM_ALLOW_WRITE=1 para confirmar reservas reales."
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/cancel")
def cancel(payload: dict = Body(...)):
    """
    Cancela una reserva por ID. Bloqueado por defecto al estar sin auth.
    Habilitá ECM_ALLOW_WRITE=1 para permitir cancelaciones reales.
    """
    if not WRITE_ENABLED:
        raise HTTPException(
            status_code=400,
            detail="Cancelación deshabilitada en modo sin llave. Setea ECM_ALLOW_WRITE=1 para habilitar.",
        )
    try:
        return cancel_event(event_id=payload.get("event_id"), sala=payload.get("sala"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
