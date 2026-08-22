from fastapi import FastAPI

from app.cards.routes import router as cards_router
from app.config import PORT

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(cards_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, port=PORT)
