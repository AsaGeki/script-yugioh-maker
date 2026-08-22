from fastapi import APIRouter, HTTPException

from app.cards.service import find_card_by_name

router = APIRouter()


# GET /cards/{name} -> busca carta oficial pelo nome em portugues, retorna dados ja em PT
@router.get("/cards/{name}")
async def get_card(name: str):
    carta = await find_card_by_name(name)
    if not carta:
        raise HTTPException(status_code=404, detail=f'Carta "{name}" nao encontrada')
    return carta
