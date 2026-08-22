"""Fallback de traducao PT via banco de dados oficial da Konami
(db.yugioh-card.com) - usado quando a YGOPRODeck ainda nao importou a
traducao PT de uma carta (defasagem entre as 2 bases: confirmado que a
Konami ja tinha "Red Supernova Dragon" traduzida quando a YGOPRODeck ainda
so tinha em ingles).

A busca por nome do site oficial exige o nome ja em portugues - a ponte e
`misc_info.konami_id` (a API YGOPRODeck ja devolve isso com `misc=yes`),
que abre a pagina da carta certa direto por `cid=`, em qualquer idioma."""

import httpx
from bs4 import BeautifulSoup

KONAMI_DB_URL = "https://www.db.yugioh-card.com/yugiohdb/card_search.action"


async def buscar_traducao_oficial(konami_id: int) -> dict[str, str] | None:
    """Busca nome + texto do efeito em PT direto do site oficial, pelo
    konami_id. None se a carta nao tiver traducao PT nem la (ou o id nao
    existir - mesmo comportamento de pagina vazia)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            KONAMI_DB_URL, params={"ope": 2, "cid": konami_id, "request_locale": "pt"}
        )
    if resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    titulo = soup.select_one(".sp.cardname h1")
    bloco_texto = soup.select_one(".CardText .item_box_text")
    if not titulo or not bloco_texto:
        return None

    rotulo = bloco_texto.select_one(".text_title")
    if rotulo:
        rotulo.extract()  # tira o "Texto do Card" que fica dentro do mesmo bloco

    nome = titulo.get_text(strip=True)
    desc = bloco_texto.get_text("\n", strip=True)
    if not nome or not desc:
        return None
    return {"name": nome, "desc": desc}
