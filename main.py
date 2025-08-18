# main.py — ECM Agenda API (no-auth, tolerante si faltan create/cancel)
from fastapi import FastAPI, Query, Body, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import datetime as dt
import os

# --- Importes base (deben existir) ------------------------------------------
from calendar_utils import (
    get_eventos,
    fetch_eventos,
    disponibilidad,
    ZONA_LOCAL,   # pytz.timezone("America/Argentina/Buenos_Aires")
)

# --- Importes opcionales (pueden NO existir) --------------------------------
try:
    from calendar_utils import create_event as _create_event  # type: ignore
    from calendar_utils import cancel_event as _cancel_event  # type: ignore
    _HAS_WRITE_FUNCS = True
except Exception:
    _create_event = None
    _cancel_event = None
    _HAS_WRITE_FUNCS = False

APP_TITLE = "ECM Agenda API (no-auth)"
APP_VERSION = "1.4.1"

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# ---- CORS (si consumís desde front) ----------------------------------------
CORS_ORIGINS = [o.strip() for o in (os.environ.get("ECM_CORS_ORIGINS", "*")).split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---- Controles de escritura -------------------------------------------------
WRITE_ENABLED   = (os.environ.get("ECM_ALLOW_WRITE", "0") or "0").lower() in ("1", "true", "yes")
DRY_RUN_DEFAULT = (os.environ.get("ECM_BOOK_DRY_RUN", "1") or "1").lower() in ("1", "true", "yes")

# ---- Helpers ----------------------------------------------------------------
def _parse_date(s: str) -> dt.datetime:
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fecha inválida '{s}'. Formato: YYYY-MM-DD") from e

def _norm(s: Optional[str]) -> Optional[str]:
    return s.strip().lower() if isinstance(s, str) else None

def _validate_dur(d: Optional[int]) -> Optional[int]:
    if d is None:
        return None
    if d not in (30, 45, 60):
        raise HTTPException(status_code=400, detail="dur_min debe ser 30, 45 o 60")
    return d

# ---- Salud / Debug ----------------------------------------------------------
@app.get("/")
def root():
    return {
        "mensaje": "¡API sin autenticación funcionando!",
        "title": APP_TITLE,
        "version": APP_VERSION,
        "endpoints": ["/agenda", "/availability", "/book", "/cancel", "/__whoami", "/healthz", "/__auth_debug"],
        "writes_enabled": WRITE_ENABLED,
        "dry_run_default": DRY_RUN_DEFAULT,
        "has_write_funcs": _HAS_WRITE_FUNCS,
    }

@app.get("/healthz")
def healthz():
    return {"ok": True, "title": APP_TITLE, "version": APP_VERSION}

@app.get("/__whoami")
def whoami():
    return {"server_file": __file__, "writes_enabled": WRITE_ENABLED, "dry_run_default": DRY_RUN_DEFAULT, "has_write_funcs": _HAS_WRITE_FUNCS}

@app.get("/__auth_debug")
def __auth_debug(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),
):
    return {
        "server_file": __file__,
        "has_authorization": bool(authorization),
        "has_x_api_key": bool(x_api_key),
        "has_valen": bool(valen),
        "auth_mode": "no-auth",
    }

# ---- Agenda -----------------------------------------------------------------
@app.get("/agenda")
def agenda(
    start: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end:   Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    if start and end:
        d0 = _parse_date(start)
        d1 = _parse_date(end)
        eventos = fetch_eventos(d0, d1 + dt.timedelta(days=1))
    else:
        eventos = get_eventos(dias=14)

    try:
        eventos.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    except Exception:
        pass
    return eventos

# ---- Disponibilidad ---------------------------------------------------------
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
    d0 = _parse_date(start)
    d1 = _parse_date(end)
    _validate_dur(dur_min)

    eventos = fetch_eventos(d0, d1 + dt.timedelta(days=1))
    resp = disponibilidad(
        eventos=eventos,
        start_date=start, end_date=end,
        instrumento=_norm(instrumento), profe=_norm(profe),
        dur_min=dur_min, salas_csv=salas,
        window_start=window_start, window_end=window_end
    )
    try:
        resp.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    except Exception:
        pass
    return resp

# ---- Reserva (modo prueba por defecto) --------------------------------------
@app.post("/book")
def book(payload: dict = Body(...)):
    """
    Crea una reserva. En no-auth corre en dry_run salvo que ECM_ALLOW_WRITE=1.
    Si calendar_utils no expone create_event, responde 400 claro.
    """
    if not _HAS_WRITE_FUNCS or _create_event is None:
        raise HTTPException(status_code=400, detail="create_event no está disponible en el servidor (calendar_utils). Subí una versión que lo implemente o dejá /book deshabilitado.")

    try:
        sala        = payload.get("sala")
        start_local = payload.get("start_local")
        end_local   = payload.get("end_local")
        if not sala or not start_local or not end_local:
            raise HTTPException(status_code=400, detail="Campos requeridos: sala, start_local, end_local")

        dry_run = payload.get("dry_run", DRY_RUN_DEFAULT) or True
        if not WRITE_ENABLED:
            dry_run = True

        res = _create_event(
            sala=sala,
            start_local=start_local,
            end_local=end_local,
            summary=payload.get("summary"),
            alumno=payload.get("alumno"),
            profe=_norm(payload.get("profe")),
            instrumento=_norm(payload.get("instrumento")),
            idempotency_key=payload.get("idempotency_key"),
            enforce_profesor_presente=payload.get("enforce_profesor_presente", True),
            dry_run=dry_run,
        )

        if dry_run and isinstance(res, dict) and res.get("status") == "validated":
            res["status"] = "validated_dry_run"
        if not WRITE_ENABLED and isinstance(res, dict):
            res["note"] = "WRITE_DISABLED: Setea ECM_ALLOW_WRITE=1 para confirmar reservas reales."
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---- Cancelación ------------------------------------------------------------
@app.post("/cancel")
def cancel(payload: dict = Body(...)):
    """
    Cancela una reserva por ID. Requiere ECM_ALLOW_WRITE=1 y cancel_event disponible.
    """
    if not WRITE_ENABLED:
        raise HTTPException(status_code=400, detail="Cancelación deshabilitada (ECM_ALLOW_WRITE=0).")
    if not _HAS_WRITE_FUNCS or _cancel_event is None:
        raise HTTPException(status_code=400, detail="cancel_event no está disponible en el servidor (calendar_utils).")

    try:
        event_id = payload.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="Falta event_id")
        return _cancel_event(event_id=event_id, sala=payload.get("sala"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---- Entry point local ------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
