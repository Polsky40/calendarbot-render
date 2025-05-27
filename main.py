from fastapi import FastAPI
from calendar_utils import get_eventos

app = FastAPI()

@app.get("/")
def root():
    return {"mensaje": "¡API funcionando! Visitá /agenda para ver la agenda."}

@app.get("/agenda")
def agenda():
    try:
        return get_eventos()  # devuelve una lista de dicts con campos estructurados
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "Falla interna", "detalle": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
