import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from playwright.async_api import Browser, Page, async_playwright

from app.cards.enums import CardType, LinkMarker, MonsterRace, SpellTrapSubtype
from app.cards.models import CardData, CardImage
from app.cards.service import find_card_by_name
from app.config import HEADLESS, OUTPUT_DIR
from app.errors import BadRequestError, NotFoundError
from app.slug import slug

MAKER_URL = "https://yugiohcardmaker.org/pt#card-editor"
# pasta padrao pra carta avulsa (busca por nome/id, busca por arquetipo) -
# quem monta deck (estrutural/publico/importado/montado na mao) passa a
# propria pasta em `pasta_destino`, ver app.cli.menu
PASTA_CARTAS_AVULSAS = Path(OUTPUT_DIR) / "cards"


def _container(page: Page, texto_label: str):
    """Acha o container (div pai) de 1 campo do formulario a partir do texto do <label>.

    O site nao associa <label> ao input/select via `for` nem aninhamento -
    label e campo sao irmaos soltos na mesma div, entao nao da pra usar
    `page.get_by_label()`. Em vez disso: acha o <label> pelo texto exato, sobe
    pro elemento pai (`..`) e devolve esse container; quem chamar decide se
    busca `input`, `select` ou `textarea` de dentro dele.
    """
    return page.locator("label", has_text=re.compile(f"^{texto_label}$")).locator("..")


# O <select> nativo de raca do site traduz errado varias pro PT oficial da
# Konami (Spellcaster -> "Conjurador", devia ser "Mago"; Zombie/Cyberse/Pyro
# sem traducao; Fiend com acento errado; Beast-Warrior no genero errado).
# Por isso usamos SEMPRE o campo "Personalizado" com o termo certo, em vez
# de decidir caso a caso quando confiar no select nativo.
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


FONTE_MAXIMA = 28  # texto bem curto (poucas dezenas de caracteres)
FONTE_MINIMA = 12  # piso pra texto bem longo, nunca fica ilegivel

# Calibrado gerando carta de teste com linhas fixas e vendo onde estoura, no
# tamanho de fonte 20: Informacao da Carta de monstro cabe 8 linhas TOTAIS
# (1 delas e sempre o cabecalho "[Raca/Subtipo/Efeito]" que o site injeta
# sozinho - ver `linhas_reservadas`); Magia/Armadilha (sem ATK/DEF nem
# cabecalho) cabe 11; Efeito do Pendulo cabe 6, mais estreito tambem (~44
# chars/linha vs ~54 do resto). K_LARGURA/K_ALTURA = chars-por-linha e
# linhas-que-cabem nesse tamanho de referencia, escalam na proporcao inversa
# da fonte.
_FONTE_REFERENCIA = 20
_K_LARGURA = 54 * _FONTE_REFERENCIA
_K_ALTURA = 8 * _FONTE_REFERENCIA
_SPELL_TRAP_K_ALTURA = 11 * _FONTE_REFERENCIA
_PENDULO_K_LARGURA = 44 * _FONTE_REFERENCIA
_PENDULO_K_ALTURA = 6 * _FONTE_REFERENCIA


def _quebrar_linha(palavras_restantes: str, largura: int) -> list[str]:
    """Quebra 1 paragrafo em linhas de ate `largura` caracteres, so em
    espaco - palavra sozinha maior que `largura` e hifenizada no limite (e
    continua na(s) linha(s) seguinte(s)) em vez de estourar a linha, que e
    o que o proprio site faz (corta no meio, sem "-" nenhum) quando a fonte
    escolhida nao coube."""
    linhas: list[str] = []
    linha_atual = ""
    for palavra in palavras_restantes.split(" "):
        candidata = f"{linha_atual} {palavra}".strip()
        if len(candidata) <= largura:
            linha_atual = candidata
            continue
        if linha_atual:
            linhas.append(linha_atual)
            linha_atual = ""
        while len(palavra) > largura:
            linhas.append(palavra[: largura - 1] + "-")
            palavra = palavra[largura - 1 :]
        linha_atual = palavra
    if linha_atual or not linhas:
        linhas.append(linha_atual)
    return linhas


def _preparar_texto_e_fonte(
    texto: str,
    *,
    k_largura: int = _K_LARGURA,
    k_altura: int = _K_ALTURA,
    linhas_reservadas: int = 0,
) -> tuple[str, int]:
    """Decide o tamanho de fonte E ja quebra o texto em linhas (\\n) antes de
    mandar pro site - o yugiohcardmaker.org nao redimensiona a fonte sozinho
    (o campo "Tamanho do Texto" e so um numero fixo) e corta palavra no meio
    quando a linha nao cabe, em vez de quebrar ou hifenizar. Testa do maior
    fonte pro menor e usa o primeiro que couber, ja com a quebra aplicada.

    `k_largura`/`k_altura` trocam a calibracao pro box em questao (ver
    constantes acima). `linhas_reservadas` reserva linhas do topo pro
    cabecalho que o site injeta sozinho em carta de monstro.
    """
    paragrafos = texto.split("\n")
    for fonte in range(FONTE_MAXIMA, FONTE_MINIMA - 1, -1):
        largura = max(1, round(k_largura / fonte))
        altura_max = max(1, round(k_altura / fonte) - linhas_reservadas)
        linhas_por_paragrafo = [_quebrar_linha(p, largura) for p in paragrafos]
        total_linhas = sum(len(linhas) for linhas in linhas_por_paragrafo)
        if fonte == FONTE_MINIMA or total_linhas <= altura_max:
            texto_final = "\n".join(
                "\n".join(linhas) for linhas in linhas_por_paragrafo
            )
            return texto_final, fonte
    raise AssertionError("loop sempre retorna ate FONTE_MINIMA")


async def _baixar_imagem_temp(url: str) -> Path:
    """Baixa a arte (sem moldura) pra um arquivo temporario, pronto pra upload no maker."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
    extensao = Path(url).suffix or ".jpg"
    arquivo_temp = Path(tempfile.gettempdir()) / f"yugioh-art{extensao}"
    arquivo_temp.write_bytes(resp.content)
    return arquivo_temp


async def _enviar_imagem(page: Page, imagem_url: str) -> None:
    """Baixa a arte (image_url_cropped: so a ilustracao, sem moldura - a
    moldura quem desenha e o proprio maker) e faz upload no input de arquivo."""
    caminho_imagem = await _baixar_imagem_temp(imagem_url)
    await page.locator("input[type=file]").set_input_files(str(caminho_imagem))


async def _descarregar_carta(
    page: Page, nome_carta: str, id_variante: int, pasta_destino: Path
) -> Path:
    """Clica "Atualizar Agora" (o preview nao reage sozinho aos campos - sem
    isso "Descarregar" sempre baixa o estado padrao da pagina, ignorando tudo
    que preenchemos; descoberto porque 2 cartas diferentes geraram o MESMO
    arquivo, hash identico), depois "Descarregar", captura o download via
    Playwright e salva em `pasta_destino` (cria se nao existir - decks salvam
    em subpasta propria, ver app.cli.menu). `id_variante` (id da arte usada,
    ver CardImage) vai sempre no nome do arquivo - a API nao da nome de
    variante nenhum, so o id e estavel o suficiente pra diferenciar."""
    pasta_destino.mkdir(parents=True, exist_ok=True)
    await page.get_by_role("button", name="Atualizar Agora", exact=True).click()
    async with page.expect_download() as download_info:
        # exact=True: a pagina tem outro elemento role=button cujo texto
        # tambem CONTEM "Descarregar" (um item de FAQ) - sem exact, ambigua
        await page.get_by_role("button", name="Descarregar", exact=True).click()
    download = await download_info.value
    extensao = Path(download.suggested_filename).suffix or ".png"
    destino = pasta_destino / f"{slug(nome_carta)}-{id_variante}{extensao}"
    await download.save_as(destino)
    return destino


# A barra do nome e preta/bem escura em Xyz e Link - com a "Cor do Titulo"
# padrao (preto) o nome some. So esses 2 subtipos trocam pra branco.
COR_TITULO_PADRAO = "#000000"
COR_TITULO_CLARA = "#FFFFFF"
SUBTIPOS_FRAME_ESCURO = {"Xyz", "Link"}


async def _definir_cor_do_titulo(page: Page, subtipo: str) -> None:
    """input[type=color] nao aceita `.fill()` do Playwright - seta o value
    via JS e dispara input/change manualmente pra o site (Vue) reagir."""
    cor = COR_TITULO_CLARA if subtipo in SUBTIPOS_FRAME_ESCURO else COR_TITULO_PADRAO
    campo = _container(page, "Cor do Título").locator("input[type=color]")
    await campo.evaluate(
        "(el, cor) => {"
        " el.value = cor;"
        " el.dispatchEvent(new Event('input', {bubbles: true}));"
        " el.dispatchEvent(new Event('change', {bubbles: true}));"
        "}",
        cor,
    )


class ConfigSubtipo:
    def __init__(self, subtipo: str, traco1: str, traco2: str, pendulo: bool):
        self.subtipo = subtipo
        self.traco1 = traco1
        self.traco2 = traco2
        self.pendulo = pendulo


# Mapeia os 29 valores de CardType pro Subtipo + tracos do site.
#
# O site tem 2 selects de traco independentes: o 1o (label "Efeito") e
# obrigatorio, sem opcao vazia; o 2o (sem label, ultimo <select> da linha) tem
# opcao "none" e combina um 2o traco. Cada select remove da lista a opcao ja
# selecionada no OUTRO - por isso sempre preenchemos traco1 antes de traco2.
#
# traco2="normal" tem rotulo "Efeito" (diferente do traco1, que e "Normal") e
# faz o cabecalho de tipo do card ganhar "/Efeito", batendo com o formato
# oficial da Konami ("Raca／Subtipo／Efeito"). So NAO fazemos isso pros tipos
# realmente normais (Normal, Ritual sem efeito, Pendulum Normal, Normal
# Tuner, Token) nem quando traco2 ja tem um 2o traco real (Flip Tuner Effect
# Monster - cabecalho fica sem "/Efeito" nesse caso, so 1 slot disponivel).
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


async def _bloquear_font_e_media(route) -> None:
    """Corta font/media do carregamento do maker - acelera sem afetar o
    resultado (canvas so precisa de "image")."""
    if route.request.resource_type in ("font", "media"):
        await route.abort()
    else:
        await route.continue_()


@asynccontextmanager
async def _pagina_do_maker(browser: Browser | None):
    """Abre 1 pagina do maker pronta pra preencher. Reusa `browser` se for
    passado (fluxo de lote no menu); senao abre e fecha um Chromium novo so
    pra essa chamada (uso avulso, `cli.py fill`)."""
    if browser is not None:
        page = await browser.new_page()
        page.set_default_timeout(60000)
        try:
            await page.route("**/*", _bloquear_font_e_media)
            await page.goto(MAKER_URL, wait_until="domcontentloaded")
            yield page
        finally:
            await page.close()
        return

    async with async_playwright() as p:
        browser_local = await p.chromium.launch(headless=HEADLESS)
        try:
            page = await browser_local.new_page()
            page.set_default_timeout(60000)
            await page.route("**/*", _bloquear_font_e_media)
            await page.goto(MAKER_URL, wait_until="domcontentloaded")
            yield page
        finally:
            await browser_local.close()


async def _resolver_carta(nome_ou_carta: str | CardData) -> CardData:
    """Aceita nome (busca na API) ou uma CardData ja carregada - usado pelo
    dispatcher fill_card pra buscar so 1 vez e repassar pronta, sem cada
    fill_* buscar de novo (isso chegou a duplicar avisos de log)."""
    if isinstance(nome_ou_carta, CardData):
        return nome_ou_carta
    carta = await find_card_by_name(nome_ou_carta)
    if not carta:
        raise NotFoundError(f'Carta "{nome_ou_carta}" nao encontrada na API')
    return carta


async def fill_monster_card(
    nome_carta: str | CardData,
    imagem: CardImage | None = None,
    *,
    browser: Browser | None = None,
    pasta_destino: Path | None = None,
) -> Path:
    """Busca a carta (ou usa uma ja carregada, ver _resolver_carta), preenche
    o Yu-Gi-Oh! Card Maker (dados + arte) e descarrega o resultado. Cobre
    qualquer monstro (Normal/Effect/Fusion/Ritual/Synchro/Xyz/Link, Pendulum
    ou nao, com traco Toon/Spirit/Union/Gemini/Flip/Tuner). Spell/Trap ficam
    de fora - ver fill_spell_trap_card. `imagem` escolhe a variante de arte;
    `browser` reusa um Chromium ja aberto; `pasta_destino` (default
    PASTA_CARTAS_AVULSAS) e onde o arquivo baixado vai parar. Retorna o
    caminho do arquivo baixado.
    """
    carta = await _resolver_carta(nome_carta)
    if carta.type in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        raise BadRequestError(
            f'"{carta.name}" nao e um monstro (type: "{carta.type}") - fill_monster_card so suporta monstros'
        )
    if carta.attribute is None:
        raise BadRequestError(f'"{carta.name}" esta sem atributo')
    if carta.atk is None:
        raise BadRequestError(f'"{carta.name}" esta sem ataque')
    config = CONFIG_POR_TIPO.get(carta.type)
    if not config:
        raise BadRequestError(
            f'Tipo "{carta.type}" nao tem mapeamento de Subtipo/traco em CONFIG_POR_TIPO'
        )

    eh_link = config.subtipo == "Link"
    if eh_link:
        if not carta.linkmarkers:
            raise BadRequestError(
                f'"{carta.name}" e Link Monster mas nao tem linkmarkers'
            )
    elif carta.level is None or carta.def_ is None:
        # Link Monster manda level/def como null de verdade (usa linkval/sem defesa) - so exigimos aqui fora do caso Link
        raise BadRequestError(f'"{carta.name}" esta sem nivel/defesa')
    if config.pendulo and (carta.scale is None or carta.pend_desc is None):
        raise BadRequestError(
            f'"{carta.name}" e carta Pendulum mas nao tem scale/pend_desc'
        )

    async with _pagina_do_maker(browser) as page:
        # espera o campo Nome existir ANTES de mexer em outro campo - sinal
        # de que o form (fontes/JS async) terminou de carregar. Sem isso os
        # campos do fim do form ainda nao existem e a interacao trava.
        campo_nome = _container(page, "Nome da Carta").locator("input")
        await campo_nome.wait_for()

        variante_usada = imagem or carta.card_images[0]
        await _enviar_imagem(page, variante_usada.image_url_cropped)

        await (
            _container(page, "Tipo de Carta").locator("select").select_option("Monster")
        )
        await (
            _container(page, "Subtipo").locator("select").select_option(config.subtipo)
        )
        await _definir_cor_do_titulo(page, config.subtipo)

        # traco1 SEMPRE antes de traco2 (ver nota em CONFIG_POR_TIPO)
        await _container(page, "Efeito").locator("select").select_option(config.traco1)
        row_do_traco = _container(page, "Efeito").locator("..")
        await row_do_traco.locator("select").last.select_option(config.traco2)

        await campo_nome.fill(carta.name)

        await (
            _container(page, "Atributo")
            .locator("select")
            .select_option(carta.attribute.value)
        )
        # Select nativo de raca traduz errado (ver RACA_PT_OFICIAL) - em vez
        # de usa-lo, marcamos "Personalizado" (mesmo padrao label.btn/input
        # escondido do Pendulo, ver nota abaixo) e preenchemos o texto livre.
        # carta.race e MonsterRace | SpellTrapSubtype, mas ja barramos Spell/Trap
        # acima - aqui so pode ser MonsterRace.
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

        # <input type=checkbox> real fica escondido atras do <label
        # class="btn ..."> (Bootstrap estiliza como botao toggle) - clicar
        # direto no input falha, so no label; leitura de estado continua no input
        container_pendulo = _container(page, "Pêndulo")
        campo_pendulo_input = container_pendulo.locator("input[type=checkbox]")
        campo_pendulo_label = container_pendulo.locator("label.btn")
        pendulo_ja_marcado = await campo_pendulo_input.is_checked()
        if pendulo_ja_marcado != config.pendulo:
            await campo_pendulo_label.click()
        if config.pendulo:
            await _container(page, "AZUL").locator("input").fill(str(carta.scale))
            await _container(page, "VERMELHO").locator("input").fill(str(carta.scale))
            texto_pendulo_ajustado, fonte_pendulo = _preparar_texto_e_fonte(
                carta.pend_desc or "",
                k_largura=_PENDULO_K_LARGURA,
                k_altura=_PENDULO_K_ALTURA,
            )
            await (
                _container(page, "Efeito do Pêndulo")
                .locator("textarea")
                .fill(texto_pendulo_ajustado)
            )
            # 2 campos identicos "Tamanho do Texto" no form (sem outro
            # jeito de diferenciar pelo label) - o 1o (nth(0)) e sempre o
            # do Efeito do Pendulo, ordem estavel no DOM
            await (
                page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
                .nth(0)
                .locator("..")
                .locator("input")
                .fill(str(fonte_pendulo))
            )

        # card de exemplo padrao do site vem com esse checkbox MARCADO
        # (injeta cabecalho tipo "[Conjurador/Invocacao Especial]" no
        # texto) - errado pra quase toda carta, entao sempre desmarcamos
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
        texto_principal_ajustado, fonte_principal = _preparar_texto_e_fonte(
            texto_principal, linhas_reservadas=1
        )
        await (
            _container(page, "Informação da Carta")
            .locator("textarea")
            .fill(texto_principal_ajustado)
        )
        # 2o "Tamanho do Texto" do form = o do texto principal (ver nota
        # identica no bloco do Efeito do Pendulo acima)
        await (
            page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
            .nth(1)
            .locator("..")
            .locator("input")
            .fill(str(fonte_principal))
        )

        # usa carta.name (nome oficial), nao o argumento recebido -
        # que pode ser so o texto de busca (parcial) quando fill_card
        # ainda nao tinha resolvido a carta
        return await _descarregar_carta(
            page, carta.name, variante_usada.id, pasta_destino or PASTA_CARTAS_AVULSAS
        )


async def fill_spell_trap_card(
    nome_carta: str | CardData,
    imagem: CardImage | None = None,
    *,
    browser: Browser | None = None,
    pasta_destino: Path | None = None,
) -> Path:
    """Busca a carta (ou usa uma ja carregada, ver _resolver_carta), preenche
    o Yu-Gi-Oh! Card Maker (dados + arte) e descarrega o resultado, pra uma
    Magia ou Armadilha. Bem mais simples que fill_monster_card: nenhum campo
    de monstro (Atributo/Tipo/Nivel/ATK/DEF/Pendulo/Link) existe pra
    Spell/Trap, todos ficam invisiveis no form. `imagem` escolhe a variante
    de arte; `browser` reusa um Chromium ja aberto; `pasta_destino` (default
    PASTA_CARTAS_AVULSAS) e onde o arquivo baixado vai parar. Retorna o
    caminho do arquivo baixado.
    """
    carta = await _resolver_carta(nome_carta)
    if carta.type not in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        raise BadRequestError(
            f'"{carta.name}" nao e Magia/Armadilha (type: "{carta.type}") - use fill_monster_card'
        )
    # o model so aceita SpellTrapSubtype pra Spell/Trap Card
    subtipo: SpellTrapSubtype = carta.race  # type: ignore[assignment]

    async with _pagina_do_maker(browser) as page:
        campo_nome = _container(page, "Nome da Carta").locator("input")
        await campo_nome.wait_for()

        variante_usada = imagem or carta.card_images[0]
        await _enviar_imagem(page, variante_usada.image_url_cropped)

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
        texto_ajustado, fonte = _preparar_texto_e_fonte(
            carta.desc, k_altura=_SPELL_TRAP_K_ALTURA
        )
        await (
            _container(page, "Informação da Carta").locator("textarea").fill(texto_ajustado)
        )
        # mesmos 2 campos "Tamanho do Texto" do form de monstro continuam
        # no DOM aqui (so ficam ocultos, nao removidos) - nth(1) e sempre
        # o do texto principal, ver nota identica em fill_monster_card
        await (
            page.locator("label", has_text=re.compile("^Tamanho do Texto$"))
            .nth(1)
            .locator("..")
            .locator("input")
            .fill(str(fonte))
        )

        return await _descarregar_carta(
            page, carta.name, variante_usada.id, pasta_destino or PASTA_CARTAS_AVULSAS
        )


async def fill_card(
    nome_carta: str | CardData,
    imagem: CardImage | None = None,
    *,
    browser: Browser | None = None,
    pasta_destino: Path | None = None,
) -> Path:
    """Busca a carta (ou usa uma ja carregada, ver _resolver_carta) e despacha
    pro preenchimento certo (monstro vs magia/armadilha - formularios bem
    diferentes, cada um com seu proprio service). `imagem` escolhe a variante
    de arte; `browser` reusa um Chromium ja aberto; `pasta_destino` (default
    PASTA_CARTAS_AVULSAS) e onde o arquivo baixado vai parar. Retorna o
    caminho baixado.
    """
    carta = await _resolver_carta(nome_carta)
    if carta.type in (CardType.SPELL_CARD, CardType.TRAP_CARD):
        return await fill_spell_trap_card(
            carta, imagem, browser=browser, pasta_destino=pasta_destino
        )
    return await fill_monster_card(
        carta, imagem, browser=browser, pasta_destino=pasta_destino
    )
