"""Cliente do endpoint que alimenta a busca de decks do proprio
ygoprodeck.com (`/api/decks/getDecks.php`) - nao documentado na api-guide,
mas publico e usado pelo frontend deles. Devolve os ids de main/extra ja
prontos no JSON, sem precisar abrir a pagina individual do deck (isso quem
faz e app.deck.scraper, pro fluxo de "colar link direto de 1 deck")."""

import json
from typing import Any

import httpx

GET_DECKS_URL = "https://ygoprodeck.com/api/decks/getDecks.php"


def _ids_de(deck: dict[str, Any], chave: str) -> list[int]:
    bruto = deck.get(chave)
    if not bruto:
        return []
    return [int(x) for x in json.loads(bruto)]


async def search_decks(nome: str, limite: int = 20) -> list[dict[str, Any]]:
    """Busca decks publicos pelo nome - usado no fluxo Decks > Buscar por
    nome de deck. Cada item tem deck_name/username/deck_views/pretty_url e
    main_deck/extra_deck (arrays de passcode em string JSON).

    `limit` da API e so um pedido - ela sempre devolve o proprio padrao dela
    (20); cortamos aqui do lado cliente pra `limite` valer de verdade.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GET_DECKS_URL, params={"name": nome, "limit": limite, "offset": 0}
        )
        resp.raise_for_status()
    return (resp.json() or [])[:limite]


def deck_ids(deck: dict[str, Any]) -> list[int]:
    """Ids de main+extra de 1 resultado de search_decks (ignora side - mesmo
    criterio do app.deck.ydk: sao as mesmas cartas do main guardadas pra
    troca, gerar de novo so duplicaria)."""
    return _ids_de(deck, "main_deck") + _ids_de(deck, "extra_deck")
