from pydantic import BaseModel, ConfigDict, Field

from app.cards.enums import (
    CardAttribute,
    CardType,
    LinkMarker,
    MonsterRace,
    SpellTrapSubtype,
)


class CardImage(BaseModel):
    id: int
    image_url: str
    image_url_small: str
    image_url_cropped: str


class CardData(BaseModel):
    """Mesmo shape da API oficial YGOPRODeck (snake_case).

    extra="allow" repassa qualquer campo que a API mande alem dos declarados
    aqui (card_sets, card_prices, archetype, typeline etc) - decisao
    deliberada (equivalente ao `...resto` da versao TS), nao filtramos.

    Diferente do TS: nao precisa de uma funcao separada tipo `mapYgoApiCard` -
    o Pydantic ja valida type/race/attribute/linkmarkers contra os enums no
    momento do parse (`CardData.model_validate(...)`), lancando
    `pydantic.ValidationError` sozinho se a API mandar um valor desconhecido.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    name: str
    name_en: str | None = None
    type: CardType
    desc: str
    atk: int | None = None
    # "def" e palavra reservada em Python (define funcao) - usamos o alias do
    # Pydantic pra continuar lendo/escrevendo a chave "def" do JSON da API,
    # mas o atributo Python se chama "def_" (convencao PEP8 pra esse caso).
    # Link Monster manda def/level como `null` de verdade (nao omite a chave)
    # - level porque Link usa linkval no lugar, def porque Link nao tem defesa.
    def_: int | None = Field(default=None, alias="def")
    level: int | None = None
    race: MonsterRace | SpellTrapSubtype
    attribute: CardAttribute | None = None
    card_images: list[CardImage]
    # Exclusivos de Link Monster
    linkval: int | None = None
    linkmarkers: list[LinkMarker] | None = None
    # Exclusivos de carta Pendulum: scale e a mesma escala pros 2 lados
    # (AZUL/VERMELHO no site); pend_desc e monster_desc sao os 2 textos
    # separados que a carta pendulum tem (o `desc` normal vem com os 2 juntos,
    # com cabecalhos "[ Pendulum Effect ]"/"[ Monster Effect ]").
    scale: int | None = None
    pend_desc: str | None = None
    monster_desc: str | None = None
