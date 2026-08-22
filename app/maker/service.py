import re
import tempfile
import unicodedata
from pathlib import Path

import httpx
from playwright.async_api import Page, async_playwright

from app.cards.enums import CardType, LinkMarker, MonsterRace, SpellTrapSubtype
from app.cards.models import CardData
from app.cards.service import find_card_by_name
from app.config import HEADLESS, OUTPUT_DIR

MAKER_URL = "https://yugiohcardmaker.org/pt#card-editor"
OUTPUT_PATH = Path(OUTPUT_DIR)


def _container(page: Page, texto_label: str):
    """Acha o container (div pai) de 1 campo do formulario a partir do texto do <label>.

    O site nao associa <label> ao input/select via `for` nem aninhamento -
    label e campo sao irmaos soltos na mesma div, entao nao da pra usar
    `page.get_by_label()`. Em vez disso: acha o <label> pelo texto exato, sobe
    pro elemento pai (`..`) e devolve esse container; quem chamar decide se
    busca `input`, `select` ou `textarea` de dentro dele.
    """
    return page.locator("label", has_text=re.compile(f"^{texto_label}$")).locator("..")


# O <select> nativo de raca do site traduz errado varias delas pro PT oficial
# da Konami (conferido contra https://www.db.yugioh-card.com): Spellcaster
# sai como "Conjurador" (deveria ser "Mago"), Zombie/Cyberse/Pyro saem sem
# traduzir, Fiend sai com acento errado ("Demónio" em vez de "Demônio"),
# Beast-Warrior sai no genero errado ("Besta-Guerreiro" em vez de
# "Besta-Guerreira"). Em vez de ter 2 caminhos (select nativo pras raças
# certas, campo customizado só pras erradas), usamos SEMPRE o campo
# "Personalizado" do site com o termo oficial - mais simples e garante
# consistencia, sem depender de nenhuma traducao do proprio maker.
RACA_PT_OFICIAL: dict[MonsterRace, str] = {
    MonsterRace.AQUA: "Aqua",
    MonsterRace.BEAST: "Besta",
    MonsterRace.BEAST_WARRIOR: "Besta-Guerreira",
    MonsterRace.CREATOR_GOD: "Deus Criador",
    MonsterRace.CYBERSE: "Ciberso",
    MonsterRace.DINOSAUR: "Dinossauro",
    MonsterRace.DIVINE_BEAST: "Besta Divina",
    MonsterRace.DRAGON: "Dragão",
    MonsterRace.FAIRY: "Fada",
    MonsterRace.FIEND: "Demônio",
    MonsterRace.FISH: "Peixe",
    MonsterRace.ILLUSION: "Ilusão",
    MonsterRace.INSECT: "Inseto",
    MonsterRace.MACHINE: "Máquina",
    MonsterRace.PLANT: "Planta",
    MonsterRace.PSYCHIC: "Psíquico",
    MonsterRace.PYRO: "Piro",
    MonsterRace.REPTILE: "Réptil",
    MonsterRace.ROCK: "Rocha",
    MonsterRace.SEA_SERPENT: "Serpente Marinha",
    MonsterRace.SPELLCASTER: "Mago",
    MonsterRace.THUNDER: "Trovão",
    MonsterRace.WARRIOR: "Guerreiro",
    MonsterRace.WINGED_BEAST: "Besta Alada",
    MonsterRace.WYRM: "Wyrm",
    MonsterRace.ZOMBIE: "Zumbi",
}


def _subtipo_para_value_do_site(subtipo: SpellTrapSubtype) -> str:
    """O <select> de Subtipo usa "Quick" pro nosso SpellTrapSubtype.QUICK_PLAY ("Quick-Play") - o resto bate igual."""
    return "Quick" if subtipo == SpellTrapSubtype.QUICK_PLAY else subtipo.value


def _tamanho_fonte(texto: str) -> int:
    """Tamanho de fonte pro campo de texto (Informacao da Carta / Efeito do
    Pendulo), maior pra texto curto e menor pra texto longo (pra sempre
    caber). Escala linear calibrada com o proprio default do site: o card de
    exemplo tinha 486 caracteres no texto principal e usava fonte 17 - usamos
    isso como ponto de referencia (com uma pequena folga, 16 em vez de 17) e
    extrapolamos pra cima (texto curto) e pra baixo (texto longo).
    """
    fonte_maxima = 22  # texto bem curto (poucas dezenas de caracteres)
    fonte_referencia = 16  # no comprimento de referencia (486 chars)
    fonte_minima = 10  # piso pra texto bem longo, nunca fica ilegivel
    comprimento_referencia = 486

    fonte = fonte_maxima - (fonte_maxima - fonte_referencia) * (
        len(texto) / comprimento_referencia
    )
    return round(max(fonte_minima, min(fonte_maxima, fonte)))


def _slug(texto: str) -> str:
    """Nome de carta -> nome de arquivo seguro (sem acento/espaco/maiuscula)."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()


async def _baixar_imagem_temp(url: str) -> Path:
    """Baixa a arte da carta (sem moldura) da API oficial pra um arquivo temporario,
    pronto pra fazer upload no maker."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
    extensao = Path(url).suffix or ".jpg"
    arquivo_temp = Path(tempfile.gettempdir()) / f"yugioh-art{extensao}"
    arquivo_temp.write_bytes(resp.content)
    return arquivo_temp


async def _enviar_imagem(page: Page, carta: CardData) -> None:
    """Baixa a arte (image_url_cropped: so a ilustracao, sem moldura - a
    moldura quem desenha e o proprio maker) e faz upload no input de arquivo."""
    caminho_imagem = await _baixar_imagem_temp(carta.card_images[0].image_url_cropped)
    await page.locator("input[type=file]").set_input_files(str(caminho_imagem))


async def _descarregar_carta(page: Page, nome_carta: str) -> Path:
    """Clica em "Atualizar Agora" (o preview/canvas nao reage sozinho aos
    campos - sem isso, "Descarregar" baixa sempre o estado inicial/padrao da
    pagina, igual em toda execucao, ignorando tudo que preenchemos; foi assim
    que descobri isso: 2 cartas diferentes geraram o MESMO arquivo, hash
    identico), depois clica "Descarregar", captura o download que o
    Playwright intercepta, e salva em OUTPUT_PATH (config OUTPUT_DIR) com nome
    baseado no nome da carta."""
    OUTPUT_PATH.mkdir(exist_ok=True)
    await page.get_by_role("button", name="Atualizar Agora", exact=True).click()
    async with page.expect_download() as download_info:
        # exact=True: a pagina tem outro elemento role=button cujo texto
        # tambem CONTEM "Descarregar" (um item de FAQ) - sem exact, ambigua
        await page.get_by_role("button", name="Descarregar", exact=True).click()
    download = await download_info.value
    extensao = Path(download.suggested_filename).suffix or ".png"
    destino = OUTPUT_PATH / f"{_slug(nome_carta)}{extensao}"
    await download.save_as(destino)
    return destino


class ConfigSubtipo:
    def __init__(self, subtipo: str, traco1: str, traco2: str, pendulo: bool):
        self.subtipo = subtipo
        self.traco1 = traco1
        self.traco2 = traco2
        self.pendulo = pendulo


# Mapeia os 29 valores de CardType pro Subtipo + tracos do site.
#
# O site tem 2 selects de traco independentes (confirmado testando ao vivo):
# o 1o (label "Efeito") e obrigatorio, sem opcao vazia; o 2o (sem label, na
# mesma linha, sempre o ultimo <select> dela) tem opcao "none" e serve pra
# combinar um 2o traco. Cada select remove da propria lista de opcoes o valor
# que esta selecionado no OUTRO (pra nao poder repetir); por isso sempre
# preenchemos traco1 antes de traco2.
#
# O valor "normal" do traco2 tem rotulo DIFERENTE do traco1: no traco1 e
# "Normal", no traco2 e "Efeito" (confirmado no <option> do proprio site).
# O cabecalho de tipo que o site desenha acima da caixa de texto (ex:
# "[Cyberse/Link]") concatena os tracos ativos - setar traco2="normal" faz
# esse cabecalho ganhar "/Efeito", batendo com o formato oficial da Konami
# ("Raca／Subtipo／Efeito", ver https://www.db.yugioh-card.com). So NAO
# fazemos isso pros tipos que sao normais de verdade (sem efeito real: Normal,
# Ritual sem efeito, Pendulum Normal, Normal Tuner, Token) e no caso unico de
# traco2 ja ocupado por um 2o traco real (Flip Tuner Effect Monster - nesse
# caso o cabecalho fica sem "/Efeito", limitacao aceita: so 1 slot de traco2).
CONFIG_POR_TIPO: dict[CardType, ConfigSubtipo] = {
    CardType.NORMAL_MONSTER: ConfigSubtipo("Normal", "normal", "none", False),
    CardType.EFFECT_MONSTER: ConfigSubtipo("Effect", "normal", "normal", False),
    CardType.FUSION_MONSTER: ConfigSubtipo("Fusion", "normal", "normal", False),
    CardType.RITUAL_MONSTER: ConfigSubtipo("Ritual", "normal", "none", False),
    CardType.RITUAL_EFFECT_MONSTER: ConfigSubtipo("Ritual", "normal", "normal", False),
    CardType.SYNCHRO_MONSTER: ConfigSubtipo("Synchro", "normal", "normal", False),
    CardType.SYNCHRO_TUNER_MONSTER: ConfigSubtipo("Synchro", "tuner", "normal", False),
    CardType.SYNCHRO_PENDULUM_EFFECT_MONSTER: ConfigSubtipo(
        "Synchro", "normal", "normal", True
    ),
    CardType.XYZ_MONSTER: ConfigSubtipo("Xyz", "normal", "normal", False),
    CardType.XYZ_PENDULUM_EFFECT_MONSTER: ConfigSubtipo(
        "Xyz", "normal", "normal", True
    ),
    CardType.LINK_MONSTER: ConfigSubtipo("Link", "normal", "normal", False),
    CardType.PENDULUM_NORMAL_MONSTER: ConfigSubtipo("Normal", "normal", "none", True),
    CardType.PENDULUM_EFFECT_MONSTER: ConfigSubtipo("Effect", "normal", "normal", True),
    CardType.PENDULUM_EFFECT_FUSION_MONSTER: ConfigSubtipo(
        "Fusion", "normal", "normal", True
    ),
    CardType.PENDULUM_EFFECT_RITUAL_MONSTER: ConfigSubtipo(
        "Ritual", "normal", "normal", True
    ),
    CardType.PENDULUM_FLIP_EFFECT_MONSTER: ConfigSubtipo(
        "Effect", "flip", "normal", True
    ),
    CardType.PENDULUM_TUNER_EFFECT_MONSTER: ConfigSubtipo(
        "Effect", "tuner", "normal", True
    ),
    CardType.FLIP_EFFECT_MONSTER: ConfigSubtipo("Effect", "flip", "normal", False),
    CardType.FLIP_TUNER_EFFECT_MONSTER: ConfigSubtipo("Effect", "flip", "tuner", False),
    CardType.GEMINI_MONSTER: ConfigSubtipo("Effect", "gemini", "normal", False),
    CardType.SPIRIT_MONSTER: ConfigSubtipo("Effect", "spirit", "normal", False),
    CardType.TOON_MONSTER: ConfigSubtipo("Effect", "toon", "normal", False),
    CardType.TUNER_MONSTER: ConfigSubtipo("Effect", "tuner", "normal", False),
    CardType.NORMAL_TUNER_MONSTER: ConfigSubtipo("Normal", "tuner", "none", False),
    CardType.UNION_EFFECT_MONSTER: ConfigSubtipo("Effect", "union", "normal", False),
    CardType.TOKEN: ConfigSubtipo("Token", "normal", "none", False),
}

# Simbolo dentro do <label> de cada checkbox de marcador de Link (grade 3x3
# sem centro). O <input> ESTA aninhado dentro do <label> (`<label><input>◤</label>`),
# mas mesmo assim precisa clicar no <label> - ver nota em fill_monster_card sobre
# o checkbox Pendulo (mesmo problema de elemento escondido atras do label estilizado).
SIMBOLO_LINK_MARKER: dict[LinkMarker, str] = {
    LinkMarker.TOP_LEFT: "◤",
    LinkMarker.TOP: "▲",
    LinkMarker.TOP_RIGHT: "◥",
    LinkMarker.LEFT: "◀",
    LinkMarker.RIGHT: "▶",
    LinkMarker.BOTTOM_LEFT: "◣",
    LinkMarker.BOTTOM: "▼",
    LinkMarker.BOTTOM_RIGHT: "◢",
}


async def _resolver_carta(nome_ou_carta: str | CardData) -> CardData:
    """Aceita nome (busca na API) ou uma CardData ja carregada - usado pelo
    dispatcher fill_card pra buscar so 1 vez e repassar pronta, sem cada
    fill_* buscar de novo (isso chegou a duplicar avisos de log)."""
    if isinstance(nome_ou_carta, CardData):
        return nome_ou_carta
    carta = await find_card_by_name(nome_ou_carta)
    if not carta:
        raise ValueError(f'Carta "{nome_ou_carta}" nao encontrada na API')
    return carta


async def fill_monster_card(nome_carta: str | CardData) -> Path:
    """Busca a carta na API oficial (ou usa uma ja carregada, ver
    _resolver_carta), preenche o Yu-Gi-Oh! Card Maker (dados + arte) e
    descarrega o resultado. Cobre qualquer monstro
    (Normal/Effect/Fusion/Ritual/Synchro/Xyz/Link, Pendulum ou nao, com traco
    Toon/Spirit/Union/Gemini/Flip/Tuner). Spell/Trap ficam de fora (fora de
    escopo deste service - ver fill_spell_trap_card). Retorna o caminho do
    arquivo baixado.
    """
    carta = await _resolver_carta(nome_carta)
    if carta.type in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        raise ValueError(
            f'"{carta.name}" nao e um monstro (type: "{carta.type}") - fill_monster_card so suporta monstros'
        )
    if carta.attribute is None:
        raise ValueError(f'"{carta.name}" esta sem atributo')
    if carta.atk is None:
        raise ValueError(f'"{carta.name}" esta sem ataque')
    config = CONFIG_POR_TIPO.get(carta.type)
    if not config:
        raise ValueError(
            f'Tipo "{carta.type}" nao tem mapeamento de Subtipo/traco em CONFIG_POR_TIPO'
        )

    eh_link = config.subtipo == "Link"
    if eh_link:
        if not carta.linkmarkers:
            raise ValueError(f'"{carta.name}" e Link Monster mas nao tem linkmarkers')
    elif carta.level is None or carta.def_ is None:
        # Link Monster manda level/def como null de verdade (usa linkval/sem defesa) - so exigimos aqui fora do caso Link
        raise ValueError(f'"{carta.name}" esta sem nivel/defesa')
    if config.pendulo and (carta.scale is None or carta.pend_desc is None):
        raise ValueError(f'"{carta.name}" e carta Pendulum mas nao tem scale/pend_desc')

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        page = await browser.new_page()
        # o carregamento inicial (fontes) pode demorar bastante numa pagina
        # sem cache - o timeout default de 30s as vezes nao e suficiente
        page.set_default_timeout(60000)

        try:
            await page.goto(MAKER_URL)

            # espera o campo Nome existir ANTES de mexer em qualquer outro
            # campo - e o sinal de que o form terminou de carregar (fontes/JS
            # async). Sem isso, os primeiros selects as vezes respondem mas
            # os campos mais pro fim do form ainda nao existem, e a interacao
            # trava ate estourar o timeout.
            campo_nome = _container(page, "Nome da Carta").locator("input")
            await campo_nome.wait_for()

            await _enviar_imagem(page, carta)

            await (
                _container(page, "Tipo de Carta")
                .locator("select")
                .select_option("Monster")
            )
            await (
                _container(page, "Subtipo")
                .locator("select")
                .select_option(config.subtipo)
            )

            # traco1 SEMPRE antes de traco2 (ver nota em CONFIG_POR_TIPO)
            await (
                _container(page, "Efeito")
                .locator("select")
                .select_option(config.traco1)
            )
            row_do_traco = _container(page, "Efeito").locator("..")
            await row_do_traco.locator("select").last.select_option(config.traco2)

            await campo_nome.fill(carta.name)

            await (
                _container(page, "Atributo")
                .locator("select")
                .select_option(carta.attribute.value)
            )
            # O select nativo de raca traduz varias raças errado pro PT
            # oficial (ver nota em RACA_PT_OFICIAL) - em vez de usa-lo,
            # marcamos "Personalizado" (checkbox rotulado "Tipo", mesmo
            # padrao label.btn/input escondido do Pendulo) e preenchemos o
            # campo de texto livre que aparece no lugar do select.
            # carta.race e MonsterRace | SpellTrapSubtype, mas ja barramos Spell/Trap acima -
            # nesse ponto so pode ser MonsterRace (o model so aceita SpellTrapSubtype pra Spell/Trap)
            container_personalizado = _container(page, "Tipo")
            campo_personalizado_input = container_personalizado.locator(
                "input[type=checkbox]"
            )
            campo_personalizado_label = container_personalizado.locator("label.btn")
            if not await campo_personalizado_input.is_checked():
                await campo_personalizado_label.click()
            await page.get_by_placeholder("Por favor insira o tipo").fill(
                RACA_PT_OFICIAL[carta.race]
            )

            # o <input type=checkbox> real fica escondido atras do <label
            # class="btn ..."> que o Bootstrap estiliza como botao toggle -
            # clicar direto no input falha (o label intercepta o clique
            # visualmente); a leitura de estado (is_checked) continua no
            # input, mas o clique tem que mirar no label clicavel
            container_pendulo = _container(page, "Pêndulo")
            campo_pendulo_input = container_pendulo.locator("input[type=checkbox]")
            campo_pendulo_label = container_pendulo.locator("label.btn")
            pendulo_ja_marcado = await campo_pendulo_input.is_checked()
            if pendulo_ja_marcado != config.pendulo:
                await campo_pendulo_label.click()
            if config.pendulo:
                await _container(page, "AZUL").locator("input").fill(str(carta.scale))
                await (
                    _container(page, "VERMELHO").locator("input").fill(str(carta.scale))
                )
                texto_pendulo = carta.pend_desc or ""
                await (
                    _container(page, "Efeito do Pêndulo")
                    .locator("textarea")
                    .fill(texto_pendulo)
                )
                # 2 campos identicos "Tamanho do Texto" no form (sem outro
                # jeito de diferenciar pelo label) - o 1o (nth(0)) e sempre o
                # do Efeito do Pendulo, ordem estavel no DOM
                await (
                    page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
                    .nth(0)
                    .locator("..")
                    .locator("input")
                    .fill(str(_tamanho_fonte(texto_pendulo)))
                )

            # o card de exemplo que o site carrega por padrao vem com esse
            # checkbox MARCADO, o que injeta um cabecalho tipo
            # "[Conjurador/Invocacao Especial]" no topo do texto - errado pra
            # quase toda carta (nao temos como saber pela API quando isso
            # deveria estar ligado), entao sempre desmarcamos
            container_invocacao = _container(page, "Invocação Especial")
            campo_invocacao_input = container_invocacao.locator("input[type=checkbox]")
            campo_invocacao_label = container_invocacao.locator("label.btn")
            if await campo_invocacao_input.is_checked():
                await campo_invocacao_label.click()

            if eh_link:
                # mesmo problema do checkbox Pendulo: clica no <label> (o
                # <input> real fica visualmente coberto por ele)
                for marcador in carta.linkmarkers or []:
                    simbolo = SIMBOLO_LINK_MARKER[marcador]
                    await page.locator(
                        "label.btn", has_text=re.compile(f"^{re.escape(simbolo)}$")
                    ).click()
            else:
                await (
                    _container(page, "Nível/Rank")
                    .locator("select")
                    .select_option(str(carta.level))
                )
                await _container(page, "Defesa").locator("input").fill(str(carta.def_))

            # Ataque e <input type="text"> (o site aceita "?" tambem, por isso nao e number)
            await _container(page, "Ataque").locator("input").fill(str(carta.atk))

            # carta Pendulum tem o texto de efeito separado em 2 (pend_desc + monster_desc);
            # o campo "Informacao da Carta" do site e so o efeito "de monstro"
            texto_principal = (
                (carta.monster_desc or carta.desc) if config.pendulo else carta.desc
            )
            await (
                _container(page, "Informação da Carta")
                .locator("textarea")
                .fill(texto_principal)
            )
            # 2o "Tamanho do Texto" do form = o do texto principal (ver nota
            # identica no bloco do Efeito do Pendulo acima)
            await (
                page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
                .nth(1)
                .locator("..")
                .locator("input")
                .fill(str(_tamanho_fonte(texto_principal)))
            )

            # usa carta.name (nome oficial), nao o argumento recebido -
            # que pode ser so o texto de busca (parcial) quando fill_card
            # ainda nao tinha resolvido a carta
            return await _descarregar_carta(page, carta.name)
        finally:
            # garante que o browser fecha mesmo se algum campo falhar - sem
            # isso, um erro no meio do preenchimento deixava o processo
            # Chromium aberto pra sempre (vazamento de recurso)
            await browser.close()


async def fill_spell_trap_card(nome_carta: str | CardData) -> Path:
    """Busca a carta na API oficial (ou usa uma ja carregada, ver
    _resolver_carta), preenche o Yu-Gi-Oh! Card Maker (dados + arte) e
    descarrega o resultado, pra uma Magia ou Armadilha. Bem mais simples que
    fill_monster_card: nenhum campo de monstro
    (Atributo/Tipo/Nivel/ATK/DEF/Pendulo/Link) existe pra Spell/Trap -
    confirmado testando ao vivo, todos ficam invisiveis no form. Retorna o
    caminho do arquivo baixado.
    """
    carta = await _resolver_carta(nome_carta)
    if carta.type not in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        raise ValueError(
            f'"{carta.name}" nao e Magia/Armadilha (type: "{carta.type}") - use fill_monster_card'
        )
    # o model so aceita SpellTrapSubtype pra Spell/Trap Card
    subtipo: SpellTrapSubtype = carta.race  # type: ignore[assignment]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        page = await browser.new_page()
        page.set_default_timeout(60000)

        try:
            await page.goto(MAKER_URL)

            campo_nome = _container(page, "Nome da Carta").locator("input")
            await campo_nome.wait_for()

            await _enviar_imagem(page, carta)

            tipo_valor = "Spell" if carta.type == CardType.SPELL_CARD else "Trap"
            await (
                _container(page, "Tipo de Carta")
                .locator("select")
                .select_option(tipo_valor)
            )
            await (
                _container(page, "Subtipo")
                .locator("select")
                .select_option(_subtipo_para_value_do_site(subtipo))
            )

            await campo_nome.fill(carta.name)
            await (
                _container(page, "Informação da Carta")
                .locator("textarea")
                .fill(carta.desc)
            )
            # mesmos 2 campos "Tamanho do Texto" do form de monstro continuam
            # no DOM aqui (so ficam ocultos, nao removidos) - nth(1) e sempre
            # o do texto principal, ver nota identica em fill_monster_card
            await (
                page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
                .nth(1)
                .locator("..")
                .locator("input")
                .fill(str(_tamanho_fonte(carta.desc)))
            )

            return await _descarregar_carta(page, carta.name)
        finally:
            await browser.close()


async def fill_card(nome_carta: str) -> Path:
    """Busca a carta pelo nome e despacha pro preenchimento certo (monstro vs
    magia/armadilha) - os 2 formularios sao bem diferentes no site, entao
    cada um tem seu proprio service. Busca so 1 vez aqui e repassa a CardData
    ja carregada pro fill_* especifico (_resolver_carta aceita os 2 - nome ou
    CardData -, entao cada fill_* continua utilizavel sozinho com so o nome).
    Retorna o caminho do arquivo baixado.
    """
    carta = await find_card_by_name(nome_carta)
    if not carta:
        raise ValueError(f'Carta "{nome_carta}" nao encontrada na API')

    if carta.type in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        return await fill_spell_trap_card(carta)
    return await fill_monster_card(carta)
