# app.py — ECM Agenda API (no-auth)
# ---------------------------------
from fastapi import FastAPI, Query, Body, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import datetime as dt
import os

# ---- Dependencias internas (asumidas existentes) ---------------------------
from calendar_utils import (
    get_eventos,         # próximos N días normalizados
    fetch_eventos,       # eventos entre datetimes (aware)
    disponibilidad,      # calcula huecos con reglas del asistente
    ZONA_LOCAL,          # pytz.timezone("America/Argentina/Buenos_Aires")
    create_event,        # crea evento (respeta dry_run)
    cancel_event,        # cancela por event_id
)

APP_TITLE = "ECM Agenda API (no-auth)"
APP_VERSION = "1.4.0"

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# ---- CORS (útil si consumís desde front/browser) ---------------------------
# Podés limitar orígenes con la env ECM_CORS_ORIGINS="https://midominio.com,https://otro.com"
CORS_ORIGINS = [o.strip() for o in (os.environ.get("ECM_CORS_ORIGINS", "*")).split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---- Controles de escritura (seguro sin key) --------------------------------
# Por defecto NO se permiten escrituras reales.
WRITE_ENABLED   = (os.environ.get("ECM_ALLOW_WRITE", "0") or "0").lower() in ("1", "true", "yes")
DRY_RUN_DEFAULT = (os.environ.get("ECM_BOOK_DRY_RUN", "1") or "1").lower() in ("1", "true", "yes")

# ---- Helpers ----------------------------------------------------------------
def _parse_date_yyyy_mm_dd(s: str) -> dt.datetime:
    """Convierte 'YYYY-MM-DD' a datetime aware en ZONA_LOCAL (inicio del día)."""
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=ZONA_LOCAL)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fecha inválida '{s}'. Formato requerido YYYY-MM-DD") from e

def _norm(s: Optional[str]) -> Optional[str]:
    return s.strip().lower() if isinstance(s, str) else None

def _validate_dur(d: Optional[int]) -> Optional[int]:
    if d is None:
        return None
    if d not in (30, 45, 60):
        raise HTTPException(status_code=400, detail="dur_min debe ser 30, 45 o 60")
    return d

# ---- Raíz / Salud / Debug ---------------------------------------------------
@app.get("/")
def root():
    return {
        "mensaje": "¡API sin autenticación funcionando!",
        "title": APP_TITLE,
        "version": APP_VERSION,
        "endpoints": ["/agenda", "/availability", "/book", "/cancel", "/__whoami", "/healthz", "/__auth_debug"],
        "writes_enabled": WRITE_ENABLED,
        "dry_run_default": DRY_RUN_DEFAULT,
    }

@app.get("/healthz")
def healthz():
    return {"ok": True, "title": APP_TITLE, "version": APP_VERSION}

@app.get("/__whoami")
def whoami():
    """Diagnóstico: confirma el módulo que está corriendo en Render."""
    return {"server_file": __file__, "writes_enabled": WRITE_ENABLED, "dry_run_default": DRY_RUN_DEFAULT}

@app.get("/__auth_debug")
def __auth_debug(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
    valen: Optional[str] = Header(None),
):
    """Diagnóstico de headers (para verificar que no haya auth activa)."""
    # No usamos ECM_API_KEY en no-auth; sólo reportamos si alguien manda headers.
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
        d0 = _parse_date_yyyy_mm_dd(start)
        d1 = _parse_date_yyyy_mm_dd(end)
        # extendemos un día para incluir eventos del 'end' completo
        eventos = fetch_eventos(d0, d1 + dt.timedelta(days=1))
    else:
        eventos = get_eventos(dias=14)

    # Orden por fecha, sala, hora de inicio
    try:
        eventos.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    except Exception:
        # Si por alguna razón faltan claves, no fallamos
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
    d0 = _parse_date_yyyy_mm_dd(start)
    d1 = _parse_date_yyyy_mm_dd(end)
    _validate_dur(dur_min)

    eventos = fetch_eventos(d0, d1 + dt.timedelta(days=1))

    resp = disponibilidad(
        eventos=eventos,
        start_date=start, end_date=end,
        instrumento=_norm(instrumento), profe=_norm(profe),
        dur_min=dur_min, salas_csv=salas,
        window_start=window_start, window_end=window_end
    )
    # Normalizamos orden si el util retorna lista dict compatible
    try:
        resp.sort(key=lambda e: (e["fecha"], e["sala"], e["start_local"]))
    except Exception:
        pass
    return resp

# ---- Reserva (modo prueba por defecto) --------------------------------------
@app.post("/book")
def book(payload: dict = Body(...)):
    """
    Crea una reserva. En modo sin auth, por defecto corre en dry_run.
    Para habilitar escritura real, setea ECM_ALLOW_WRITE=1 en el entorno.
    """
    try:
        # Validaciones mínimas
        sala        = payload.get("sala")
        start_local = payload.get("start_local")
        end_local   = payload.get("end_local")
        if not sala or not start_local or not end_local:
            raise HTTPException(status_code=400, detail="Campos requeridos: sala, start_local, end_local")

        dry_run = payload.get("dry_run", DRY_RUN_DEFAULT) or True
        if not WRITE_ENABLED:
            dry_run = True

        res = create_event(
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

        # Normalizamos el status para dry_run
        if dry_run and res.get("status") == "validated":
            res["status"] = "validated_dry_run"
        if not WRITE_ENABLED:
            res["note"] = "WRITE_DISABLED: Setea ECM_ALLOW_WRITE=1 para confirmar reservas reales."
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---- Cancelación (bloqueada por defecto en no-auth) -------------------------
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
        event_id = payload.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="Falta event_id")
        return cancel_event(event_id=event_id, sala=payload.get("sala"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---- Entry point local ------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    # Local: uvicorn app:app --reload
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
