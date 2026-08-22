import logging
import unicodedata

import httpx

from app.cards.models import CardData

BASE_URL = "https://db.ygoprodeck.com/api/v7/cardinfo.php"

logger = logging.getLogger(__name__)

# Campos de texto que fazem sentido conferir se a API traduziu de verdade pro PT
CAMPOS_DE_TEXTO = ("desc", "pend_desc", "monster_desc")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return sem_acento.lower().strip()


async def _avisar_se_traducao_incompleta(
    client: httpx.AsyncClient, carta: CardData
) -> None:
    """A API oficial as vezes devolve `language=pt` mas nao traduziu de fato
    algum campo especifico dessa carta (ex: pend_desc de cartas Pendulum mais
    novas) - o texto volta identico ao ingles, sem erro nenhum, dado
    incompleto na base deles mesmo. Detecta comparando com a versao em ingles
    da mesma carta (mesmo id, sem language) e avisa via logging - nao tem como
    corrigir o texto em si, so sinalizar que essa carta precisa de revisao
    manual.
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


async def find_card_by_name(nome_pt: str) -> CardData | None:
    """Busca 1 carta na API oficial YGOPRODeck pelo nome em portugues.

    `name` (busca exata) nao aceita `language=pt` junto (a API so casa nome
    exato contra o nome em ingles). Mas `fname` (busca parcial/fuzzy) aceita
    os 2 juntos e casa contra o nome ja traduzido - por isso usamos fname aqui.

    Como fname e parcial, pode retornar varias cartas (ex: "Mago Negro"
    tambem acha "Mago Negro do Caos", "Cortina de Mago Negro" etc).
    Preferimos o resultado cujo nome bate exato (ignorando acento/caixa);
    senao, usamos o primeiro da lista.
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
