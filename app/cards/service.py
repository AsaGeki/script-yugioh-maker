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
