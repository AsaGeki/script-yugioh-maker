"""Resolve um deck de qualquer uma das fontes suportadas pra lista de cartas
- dedup por id/nome, ja que um deck real repete a mesma carta ate 3x e gerar
a mesma imagem de novo seria so desperdicio de tempo (cada carta abre um
Chromium). Fontes: link `ydke://`, arquivo `.ydk` ou `.txt` (nomes) local,
link publico do ygoprodeck.com (scraping, ver app.deck.scraper), ou 1
resultado de busca por nome (app.deck.api, ids ja prontos no proprio JSON)."""

from pathlib import Path
from typing import Any

from app.cards.models import CardData
from app.cards.service import find_card_by_id, find_cards_by_names
from app.deck.api import deck_ids
from app.deck.scraper import eh_link_de_deck, extrair_ids_do_deck
from app.deck.ydk import parse_ydk_arquivo, parse_ydke
from app.errors import BadRequestError


def _sem_duplicatas(ids: list[int]) -> list[int]:
    vistos: set[int] = set()
    unicos = []
    for id_carta in ids:
        if id_carta not in vistos:
            vistos.add(id_carta)
            unicos.append(id_carta)
    return unicos


def _sem_duplicatas_nomes(nomes: list[str]) -> list[str]:
    vistos: set[str] = set()
    unicos = []
    for nome in nomes:
        chave = nome.lower()
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(nome)
    return unicos


async def _resolver_por_ids(ids: list[int]) -> tuple[list[CardData], list[str]]:
    """Busca cada id na API - 1 id que falha (banido da base, invalido etc)
    nao derruba o resto."""
    encontradas: list[CardData] = []
    nao_encontradas: list[str] = []
    for id_carta in _sem_duplicatas(ids):
        carta = await find_card_by_id(id_carta)
        if carta:
            encontradas.append(carta)
        else:
            nao_encontradas.append(str(id_carta))
    return encontradas, nao_encontradas


async def resolver_ids_do_deck(fonte: str) -> list[int]:
    if fonte.startswith("ydke://"):
        return parse_ydke(fonte)
    if eh_link_de_deck(fonte):
        return await extrair_ids_do_deck(fonte)
    return parse_ydk_arquivo(Path(fonte))


async def buscar_cartas_do_deck(fonte: str) -> tuple[list[CardData], list[str]]:
    """Resolve a fonte (link `ydke://`, link do site, `.ydk` ou `.txt` local
    com nomes) pra lista de cartas."""
    fonte = fonte.strip().strip('"')
    caminho = Path(fonte)
    if caminho.suffix.lower() == ".txt":
        if not caminho.exists():
            raise BadRequestError(f'Arquivo "{caminho}" nao encontrado')
        nomes = caminho.read_text(encoding="utf-8").splitlines()
        nomes = _sem_duplicatas_nomes([n.strip() for n in nomes if n.strip()])
        return await find_cards_by_names(nomes)

    if not (
        fonte.startswith("ydke://")
        or eh_link_de_deck(fonte)
        or caminho.suffix.lower() == ".ydk"
    ):
        raise BadRequestError(
            f'"{fonte}" nao e um link ydke://, um link de deck do ygoprodeck.com '
            "nem um arquivo .ydk/.txt"
        )
    return await _resolver_por_ids(await resolver_ids_do_deck(fonte))


async def buscar_cartas_de_resultado(
    deck: dict[str, Any],
) -> tuple[list[CardData], list[str]]:
    """Resolve as cartas de 1 resultado de app.deck.api.search_decks (deck
    publico achado por nome) - os ids de main/extra ja vem prontos no proprio
    resultado da busca, sem precisar abrir a pagina do deck."""
    return await _resolver_por_ids(deck_ids(deck))
