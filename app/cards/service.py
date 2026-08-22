import asyncio
import logging
import unicodedata
from typing import Any

import httpx

from app.cards.konami import buscar_traducao_oficial
from app.cards.models import CardData

BASE_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
ARCHETYPES_URL = "https://db.ygoprodeck.com/api/v7/archetypes.php"
CARDSETS_URL = "https://db.ygoprodeck.com/api/v7/cardsets.php"

logger = logging.getLogger(__name__)

# Campos de texto que fazem sentido conferir se a API traduziu de verdade pro PT
CAMPOS_DE_TEXTO = ("desc", "pend_desc", "monster_desc")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return sem_acento.lower().strip()


def _konami_id_de(bruto: dict[str, Any]) -> int | None:
    return (bruto.get("misc_info") or [{}])[0].get("konami_id")


async def _tentar_traducao_oficial(carta: CardData, bruto: dict[str, Any]) -> None:
    """Ultima tentativa antes de desistir da traducao PT: usa o konami_id
    (misc_info da API) pra puxar nome+texto do banco oficial da Konami -
    cobre o caso da YGOPRODeck ainda nao ter importado uma traducao que a
    Konami ja lancou (ver app.cards.konami)."""
    konami_id = _konami_id_de(bruto)
    traducao = await buscar_traducao_oficial(konami_id) if konami_id else None
    if traducao:
        carta.name = traducao["name"]
        carta.desc = traducao["desc"]
        logger.info(
            '"%s": sem traducao PT na YGOPRODeck, mas achada no banco oficial da Konami',
            carta.name,
        )
    else:
        carta.traduzida = False
        logger.warning(
            '"%s": sem traducao PT em nenhuma das 2 fontes, usando o texto em ingles',
            carta.name,
        )


async def _avisar_se_traducao_incompleta(
    client: httpx.AsyncClient, carta: CardData
) -> None:
    """A API as vezes devolve `language=pt` sem ter traduzido de fato algum
    campo (ex: pend_desc de Pendulum mais novas) - volta identico ao ingles,
    dado incompleto na base deles mesmo. Detecta comparando com a versao em
    ingles (mesmo id, sem language) e so avisa via logging - nao ha como
    corrigir o texto, so sinalizar revisao manual.
    """
    resp = await client.get(BASE_URL, params={"id": carta.id})
    if resp.status_code != 200:
        return
    dados_en = (resp.json().get("data") or [None])[0]
    if not dados_en:
        return

    campos_nao_traduzidos = [
        campo
        for campo in CAMPOS_DE_TEXTO
        if getattr(carta, campo, None) and getattr(carta, campo) == dados_en.get(campo)
    ]
    if campos_nao_traduzidos:
        logger.warning(
            '"%s": campo(s) %s vieram identicos ao ingles - API oficial nao tem traducao PT '
            "pra esse dado especifico dessa carta, revise manualmente",
            carta.name,
            ", ".join(campos_nao_traduzidos),
        )


async def find_card_by_id(card_id: int) -> CardData | None:
    """Busca 1 carta pelo id/passcode exato - usado pra resolver deck (main/extra
    do .ydk/ydke/scraping vem como passcode numerico, nao nome).

    Diferente de fname, `id` + `language=pt` devolve 400 (nao faz fallback
    sozinho) quando a carta ainda nao tem traducao PT na base deles - por
    isso tentamos de novo sem language nesse caso, em vez de tratar como
    "carta nao existe".
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            BASE_URL, params={"id": card_id, "language": "pt", "misc": "yes"}
        )
        sem_traducao_pt = resp.status_code == 400
        if sem_traducao_pt:
            resp = await client.get(BASE_URL, params={"id": card_id, "misc": "yes"})
            if resp.status_code == 400:
                return None
        resp.raise_for_status()

        dados = resp.json().get("data") or []
        if not dados:
            return None

        carta = CardData.model_validate(dados[0])
        if sem_traducao_pt:
            await _tentar_traducao_oficial(carta, dados[0])
        else:
            await _avisar_se_traducao_incompleta(client, carta)

    return carta


async def find_card_by_name(nome_pt: str) -> CardData | None:
    """Busca 1 carta na API oficial YGOPRODeck pelo nome em portugues.

    `name` (busca exata) nao aceita `language=pt` junto - so casa contra o
    nome em ingles. `fname` (parcial/fuzzy) aceita os 2 e casa contra o nome
    ja traduzido, por isso usamos fname. Como e parcial pode vir mais de 1
    resultado (ex: "Mago Negro" tambem acha "Mago Negro do Caos") -
    preferimos o nome que bate exato (ignorando acento/caixa), senao o 1o.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(BASE_URL, params={"fname": nome_pt, "language": "pt"})

        if resp.status_code == 400:
            return None  # API retorna 400 quando nenhuma carta bate com o filtro
        resp.raise_for_status()

        dados = resp.json().get("data") or []
        if not dados:
            return None

        alvo = _normalizar(nome_pt)
        exata = next((c for c in dados if _normalizar(c["name"]) == alvo), None)
        carta = CardData.model_validate(exata or dados[0])

        await _avisar_se_traducao_incompleta(client, carta)

    return carta


async def find_cards_by_names(nomes: list[str]) -> tuple[list[CardData], list[str]]:
    """Busca varias cartas por nome (fluxo de lista/.txt) - 1 nome que falha nao
    derruba os outros, so entra na lista de nao encontradas."""
    encontradas: list[CardData] = []
    nao_encontradas: list[str] = []
    for nome in nomes:
        carta = await find_card_by_name(nome)
        if carta:
            encontradas.append(carta)
        else:
            nao_encontradas.append(nome)
    return encontradas, nao_encontradas


async def _buscar_cartas(params: dict[str, str]) -> list[CardData]:
    """Chama cardinfo.php com o mesmo gotcha de fallback pras 3 formas de
    filtro (fname/archetype/cardset) + `language=pt`: devolve 400 (nao lista
    vazia) quando NENHUM resultado do filtro tem traducao PT - ex: "albaz" so
    bate em cartas ainda nao traduzidas. Cai pra ingles nesse caso em vez de
    fingir que nao achou nada.
    """
    sem_traducao_pt = False
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            BASE_URL, params={**params, "language": "pt", "misc": "yes"}
        )
        if resp.status_code == 400:
            resp = await client.get(BASE_URL, params={**params, "misc": "yes"})
            if resp.status_code == 400:
                return []  # dessa vez sim, nenhuma carta bate com o filtro
            sem_traducao_pt = True
        resp.raise_for_status()
        dados = resp.json().get("data") or []

    cartas = [CardData.model_validate(item) for item in dados]
    if sem_traducao_pt:
        # 1 tentativa de traducao oficial por carta, em paralelo - senao,
        # buscar um resultado com varias cartas sem traducao ficaria lento
        await asyncio.gather(
            *(
                _tentar_traducao_oficial(carta, bruto)
                for carta, bruto in zip(cartas, dados)
            )
        )
    return cartas


async def search_cards(
    termo: str = "", *, arquetipo: str | None = None
) -> list[CardData]:
    """Busca varias cartas de uma vez por nome parcial e/ou arquetipo - usado
    no fluxo Cartas > Buscar por arquetipo (diferente de find_card_by_name,
    que resolve so 1 carta exata pra gerar direto)."""
    params: dict[str, str] = {}
    if termo:
        params["fname"] = termo
    if arquetipo:
        params["archetype"] = arquetipo
    return await _buscar_cartas(params)


async def search_cards_by_term(termo: str) -> list[CardData]:
    """Busca unificada pro fluxo Cartas > Buscar por nome/id: numero puro
    vira busca por id exato (find_card_by_id); texto vira nome parcial
    (search_cards, que ja cai pro ingles quando falta traducao PT - cobre
    "nome em ingles" tambem)."""
    termo = termo.strip()
    if termo.isdigit():
        carta = await find_card_by_id(int(termo))
        return [carta] if carta else []
    return await search_cards(termo)


async def find_cards_by_cardset(nome_set: str) -> list[CardData]:
    """Busca todas as cartas de 1 set/produto oficial pelo nome exato (ex: 1
    Structure Deck, ver list_structure_decks) - direto na API, sem depender
    de ninguem ter subido esse decklist como deck publico."""
    return await _buscar_cartas({"cardset": nome_set})


async def list_archetypes() -> list[str]:
    """Lista os arquetipos oficiais (ex: "Blue-Eyes", "Dark Magician") pra
    usar como filtro em search_cards."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(ARCHETYPES_URL)
        resp.raise_for_status()
        dados = resp.json() or []
    return sorted(
        {item["archetype_name"] for item in dados if item.get("archetype_name")}
    )


async def list_structure_decks() -> list[str]:
    """Lista os nomes oficiais de "Structure Deck: X" via cardsets.php (API
    oficial de sets/produtos) - usado no fluxo Decks > Buscar por
    estruturais junto com find_cards_by_cardset."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(CARDSETS_URL, timeout=15)
        resp.raise_for_status()
        sets = resp.json() or []
    return sorted(
        {s["set_name"] for s in sets if "structure deck" in s["set_name"].lower()}
    )
