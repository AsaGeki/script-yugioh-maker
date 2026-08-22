from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.cards.routes import router as cards_router
from app.config import PORT
from app.errors import AppError

app = FastAPI()


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": exc.message})


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(cards_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=PORT)
