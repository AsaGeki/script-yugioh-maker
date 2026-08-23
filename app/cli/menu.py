"""Menu interativo do CLI (banner + navegacao por seta via questionary) -
alternativa ao modo direto `cli.py fill "nome"` pra quem quer explorar sem
decorar flag nenhuma. 2 categorias: Cartas (avulsa) e Decks (varias de uma
vez).

Todo prompt usa `ask_async()`, nunca `ask()` (sincrono) - o menu roda dentro
de 1 `asyncio.run()` so, ver main().
"""

import asyncio
from pathlib import Path
from typing import Any

import pyfiglet
import questionary
from playwright.async_api import Browser, async_playwright
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.cards.models import CardData
from app.cards.service import (
    find_cards_by_cardset,
    list_archetypes,
    list_structure_decks,
    search_cards,
    search_cards_by_term,
)
from app.cli.preview import escolher_variante, mostrar_ficha
from app.cli.stdio import configurar_stdio_utf8
from app.config import HEADLESS, OUTPUT_DIR
from app.deck.api import search_decks
from app.deck.service import buscar_cartas_de_resultado, buscar_cartas_do_deck
from app.errors import AppError
from app.maker.service import fill_card
from app.print import layout
from app.print import pdf as print_pdf
from app.print.service import montar_lote
from app.slug import slug

console = Console()

CATEGORIA_CARTAS = "Cartas"
CATEGORIA_DECKS = "Decks"
CATEGORIA_IMPRIMIR = "PDF"
OPCAO_SAIR = "Sair"
VOLTAR = "Voltar"

# Estrutura padrao de output/: cartas avulsas em cards/ (default de fill_card,
# ver PASTA_CARTAS_AVULSAS em app.maker.service); cada fluxo de Decks monta
# a propria subpasta dentro de DECKS_DIR - ver cada _fluxo_* abaixo.
DECKS_DIR = Path(OUTPUT_DIR) / "decks"


def mostrar_banner() -> None:
    console.print(
        f"[bold cyan]{pyfiglet.figlet_format('Yu-Gi-Oh Maker', font='slant')}[/]"
    )


def _mostrar_tabela(cartas: list[CardData]) -> None:
    tabela = Table(title=f"Cartas ({len(cartas)})")
    tabela.add_column("Nome")
    tabela.add_column("Tipo")
    tabela.add_column("PT")
    for carta in cartas:
        pt = "[green]sim[/]" if carta.traduzida else "[red]nao[/]"
        tabela.add_row(carta.name, str(carta.type), pt)
    console.print(tabela)


async def _gerar_uma(
    carta: CardData,
    *,
    browser: Browser | None = None,
    confirmar: bool = True,
    pasta_destino: Path | None = None,
) -> None:
    """No lote (`confirmar=False`), a selecao no checkbox ja e a confirmacao -
    so pergunta de novo quando ha variante de arte (escolher_variante).
    `pasta_destino` None cai no padrao de fill_card (output/cards)."""
    if not carta.traduzida:
        console.print(
            f'  [red]![/] "{carta.name}" sem traducao PT - vai sair em ingles'
        )
    imagem = await escolher_variante(carta)
    if (
        confirmar
        and not await questionary.confirm(
            f'Gerar "{carta.name}"?', default=True
        ).ask_async()
    ):
        return
    destino = await fill_card(carta, imagem, browser=browser, pasta_destino=pasta_destino)
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _gerar_varias(
    cartas: list[CardData], *, pasta_destino: Path | None = None
) -> None:
    """Abre 1 Chromium so e reusa pra todas as cartas do lote - abrir/fechar
    1 browser por carta era o gargalo de velocidade gerando varias de uma vez."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        try:
            for indice, carta in enumerate(cartas, start=1):
                console.rule(f"{indice}/{len(cartas)}: {carta.name}")
                try:
                    await _gerar_uma(
                        carta, browser=browser, confirmar=False, pasta_destino=pasta_destino
                    )
                except AppError as erro:
                    console.print(f"  [red]![/] {erro.message}")
        finally:
            await browser.close()


async def _escolher_e_gerar(
    cartas: list[CardData],
    *,
    pre_marcadas: bool = False,
    pasta_destino: Path | None = None,
) -> None:
    """Mostra a tabela de resultado + checkbox de selecao multipla - usado
    por todo fluxo que termina numa lista de cartas candidatas (arquetipo,
    estrutural, deck publico, deck importado, deck montado na mao).
    `pasta_destino` decide em que pasta de output/ as cartas escolhidas caem."""
    if not cartas:
        console.print("  [red]![/] Nenhuma carta encontrada.")
        return
    _mostrar_tabela(cartas)
    sufixo = " (ja vem todas marcadas)" if pre_marcadas else ""
    escolhidas = await questionary.checkbox(
        f"Selecione quais gerar{sufixo}:",
        choices=[
            questionary.Choice(
                f"{carta.name} ({carta.type})", carta, checked=pre_marcadas
            )
            for carta in cartas
        ],
    ).ask_async()
    if escolhidas:
        await _gerar_varias(escolhidas, pasta_destino=pasta_destino)


# --- Cartas ------------------------------------------------------------


async def _fluxo_buscar_nome_id() -> None:
    termo = await questionary.text("Nome, nome em ingles ou id da carta:").ask_async()
    if not termo:
        return
    resultados = await search_cards_by_term(termo)
    if not resultados:
        console.print(f'  [red]![/] Nada encontrado pra "{termo}"')
        return
    if len(resultados) == 1:
        mostrar_ficha(resultados[0])
        await _gerar_uma(resultados[0])
        return
    await _escolher_e_gerar(resultados)


async def _fluxo_buscar_arquetipo() -> None:
    console.print("Carregando arquetipos...")
    arquetipo = await questionary.select(
        "Escolha o arquetipo:", choices=await list_archetypes()
    ).ask_async()
    if arquetipo is None:
        return
    await _escolher_e_gerar(await search_cards(arquetipo=arquetipo))


FLUXOS_CARTAS = {
    "Buscar por nome/id": _fluxo_buscar_nome_id,
    "Buscar por arquetipo": _fluxo_buscar_arquetipo,
}


# --- Decks ---------------------------------------------------------------


async def _fluxo_estruturais() -> None:
    console.print("Carregando lista de estruturais...")
    nome_set = await questionary.select(
        "Escolha o estrutural:", choices=await list_structure_decks()
    ).ask_async()
    if nome_set is None:
        return
    pasta = DECKS_DIR / "decks-estruturais" / slug(nome_set)
    await _escolher_e_gerar(
        await find_cards_by_cardset(nome_set), pre_marcadas=True, pasta_destino=pasta
    )


def _rotulo_deck_publico(deck: dict[str, Any]) -> str:
    return f"{deck['deck_name']} - {deck['username']} ({deck['deck_views']} views, {deck['format']})"


async def _fluxo_buscar_deck_por_nome() -> None:
    nome = await questionary.text(
        "Nome do deck (ex: Kashtira, Albaz Strike):"
    ).ask_async()
    if not nome:
        return
    console.print("Buscando decks publicos...")
    decks = await search_decks(nome)
    if not decks:
        console.print(f'  [red]![/] Nenhum deck publico achado com "{nome}"')
        return
    escolhido = await questionary.select(
        "Qual deck?",
        choices=[questionary.Choice(_rotulo_deck_publico(d), d) for d in decks],
    ).ask_async()
    if escolhido is None:
        return
    cartas, nao_encontradas = await buscar_cartas_de_resultado(escolhido)
    if nao_encontradas:
        console.print(f"  [yellow]![/] nao encontrado(s): {', '.join(nao_encontradas)}")
    pasta = DECKS_DIR / "decks-publicos" / slug(escolhido["deck_name"])
    await _escolher_e_gerar(cartas, pre_marcadas=True, pasta_destino=pasta)


async def _pasta_deck_importado(fonte: str) -> Path:
    """.txt cai em decks-txt (nome do arquivo); ydke://, link do
    ygoprodeck.com e .ydk local nao tem nome de deck pronto pra usar (ydke/
    link nao carregam nome nenhum, e o .ydk pode ter nome de arquivo generico)
    - todos esses caem em decks-links, com nome pedido na hora (sugere o nome
    do arquivo quando for .ydk)."""
    caminho = Path(fonte.strip().strip('"'))
    if caminho.suffix.lower() == ".txt":
        return DECKS_DIR / "decks-txt" / slug(caminho.stem)
    sugestao = caminho.stem if caminho.suffix.lower() == ".ydk" else ""
    nome = await questionary.text(
        "Nome pra pasta desse deck:", default=sugestao
    ).ask_async()
    return DECKS_DIR / "decks-links" / slug(nome or "deck-importado")


async def _fluxo_importar_deck() -> None:
    fonte = await questionary.text(
        "Link ydke://, link ygoprodeck.com/deck/..., ou caminho de .ydk/.txt:"
    ).ask_async()
    if not fonte:
        return
    console.print("Resolvendo deck...")
    cartas, nao_encontradas = await buscar_cartas_do_deck(fonte)
    if nao_encontradas:
        console.print(f"  [yellow]![/] nao encontrado(s): {', '.join(nao_encontradas)}")
    pasta = await _pasta_deck_importado(fonte)
    await _escolher_e_gerar(cartas, pre_marcadas=True, pasta_destino=pasta)


async def _adicionar_carta_ao_monte(acumuladas: list[CardData]) -> None:
    termo = await questionary.text("Nome, nome em ingles ou id da carta:").ask_async()
    if not termo:
        return
    resultados = await search_cards_by_term(termo)
    if not resultados:
        console.print(f'  [red]![/] Nada encontrado pra "{termo}"')
        return
    escolhida = resultados[0]
    if len(resultados) > 1:
        escolha = await questionary.select(
            "Qual delas?",
            choices=[questionary.Choice(f"{c.name} ({c.type})", c) for c in resultados],
        ).ask_async()
        if escolha is None:
            return
        escolhida = escolha
    acumuladas.append(escolhida)
    console.print(
        f"  [green]+[/] {escolhida.name} adicionada ({len(acumuladas)} no total)"
    )


async def _remover_carta_do_monte(acumuladas: list[CardData]) -> list[CardData]:
    if not acumuladas:
        console.print("  [yellow]![/] Deck ainda vazio.")
        return acumuladas
    remover = await questionary.checkbox(
        "Remover quais?",
        choices=[questionary.Choice(f"{c.name} ({c.type})", c) for c in acumuladas],
    ).ask_async()
    if not remover:
        return acumuladas
    return [c for c in acumuladas if c not in remover]


async def _fluxo_montar_deck() -> None:
    """Vai buscando carta por carta (reusa a mesma busca nome/id/ingles de
    Cartas) e acumulando - so decide o que gerar de verdade no final, com
    chance de remover algo adicionado por engano antes de fechar."""
    acumuladas: list[CardData] = []
    while True:
        console.print(f"\n[bold]Deck em montagem: {len(acumuladas)} carta(s)[/]")
        acao = await questionary.select(
            "O que fazer?",
            choices=["Adicionar carta", "Remover carta", "Finalizar", "Descartar tudo"],
        ).ask_async()
        if acao in (None, "Descartar tudo"):
            return
        if acao == "Finalizar":
            break
        try:
            if acao == "Remover carta":
                acumuladas = await _remover_carta_do_monte(acumuladas)
            else:
                await _adicionar_carta_ao_monte(acumuladas)
        except AppError as erro:
            console.print(f"  [red]![/] {erro.message}")

    if not acumuladas:
        return
    nome_deck = await questionary.text("Nome pra pasta desse deck:").ask_async()
    pasta = DECKS_DIR / "decks-montados" / slug(nome_deck or "deck-sem-nome")
    await _escolher_e_gerar(acumuladas, pre_marcadas=True, pasta_destino=pasta)


FLUXOS_DECKS = {
    "Buscar por estruturais": _fluxo_estruturais,
    "Buscar por nome de deck": _fluxo_buscar_deck_por_nome,
    "Importar deck (link/.ydk/.txt)": _fluxo_importar_deck,
    "Montar deck": _fluxo_montar_deck,
}


# --- PDF -------------------------------------------------------------------


def _imagens_em(pasta: Path) -> list[Path]:
    return sorted(
        p for p in pasta.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")
    )


def _pastas_de_deck() -> list[Path]:
    """1 pasta de deck = 1 sub-subpasta de DECKS_DIR (ex:
    decks-estruturais/structure-deck-albaz-strike) - a carta avulsa individual
    quem lista e cards/, aqui e so a pasta do deck inteiro."""
    if not DECKS_DIR.exists():
        return []
    return sorted(
        pasta
        for bucket in DECKS_DIR.iterdir()
        if bucket.is_dir()
        for pasta in bucket.iterdir()
        if pasta.is_dir()
    )


def _opcoes_selecao() -> list[questionary.Choice]:
    """1 opcao por carta avulsa (cards/*.jpg) + 1 opcao por deck INTEIRO (cada
    pasta de _pastas_de_deck, todas as cartas dali juntas numa escolha so) -
    e por isso que existe pasta por deck: selecionar o deck marca ele de 1 vez,
    sem listar carta por carta. O valor de cada Choice ja e a lista de
    caminhos que aquela opcao representa (1 elemento se for carta avulsa)."""
    opcoes = []
    pasta_cards = Path(OUTPUT_DIR) / "cards"
    if pasta_cards.exists():
        opcoes += [
            questionary.Choice(f"cards/{caminho.name}", [caminho])
            for caminho in _imagens_em(pasta_cards)
        ]
    for pasta_deck in _pastas_de_deck():
        imagens = _imagens_em(pasta_deck)
        if imagens:
            rotulo = pasta_deck.relative_to(DECKS_DIR).as_posix()
            opcoes.append(
                questionary.Choice(f"[deck] {rotulo} ({len(imagens)} cartas)", imagens)
            )
    return opcoes


async def _escolher_cartas_para_imprimir() -> list[Path] | None:
    opcoes = _opcoes_selecao()
    if not opcoes:
        console.print(f'  [red]![/] Nenhuma carta encontrada em "{OUTPUT_DIR}"')
        return None
    escolhidos = await questionary.checkbox(
        "Selecione cartas avulsas e/ou decks inteiros:", choices=opcoes
    ).ask_async()
    if not escolhidos:
        return None
    return [caminho for grupo in escolhidos for caminho in grupo]


def _verso_padrao() -> Path | None:
    """Verso fica no mesmo lugar que o PDF (raiz de output/), como
    "verso.jpg"/"verso.png" - achando, pre-preenche o prompt (so apertar
    Enter) em vez de digitar o caminho de novo toda vez."""
    for extensao in (".jpg", ".jpeg", ".png"):
        caminho = Path(OUTPUT_DIR) / f"verso{extensao}"
        if caminho.is_file():
            return caminho
    return None


async def _escolher_verso() -> Path | None:
    incluir = await questionary.confirm(
        "Incluir verso (parte de tras) nas folhas?", default=False
    ).ask_async()
    if not incluir:
        return None
    padrao = _verso_padrao()
    if padrao is None:
        console.print(
            f'  [yellow]Dica:[/] salve a imagem como "{Path(OUTPUT_DIR) / "verso.jpg"}" '
            "pra nao precisar digitar o caminho de novo da proxima vez"
        )
    caminho_texto = await questionary.path(
        "Caminho da imagem do verso:", default=str(padrao) if padrao else ""
    ).ask_async()
    if not caminho_texto:
        return None
    caminho = Path(caminho_texto)
    if not caminho.is_file():
        console.print(f'  [red]![/] Arquivo "{caminho}" nao encontrado - seguindo so com a frente')
        return None
    return caminho


async def _exportar_pdf_frente_verso(
    folhas_frente: list, folhas_verso: list, prefixo: str
) -> None:
    destino_frente = print_pdf.exportar_pdf(folhas_frente, f"{prefixo}-frente.pdf")
    console.print(f"  [green]OK[/] frente salva em [bold]{destino_frente}[/]")
    if folhas_verso:
        destino_verso = print_pdf.exportar_pdf(folhas_verso, f"{prefixo}-verso.pdf")
        console.print(f"  [green]OK[/] verso salvo em [bold]{destino_verso}[/]")


async def _fluxo_montar_pdf() -> None:
    cartas = await _escolher_cartas_para_imprimir()
    if not cartas:
        return
    caminho_verso = await _escolher_verso()
    folhas_frente, folhas_verso = montar_lote(cartas, caminho_verso)
    await _exportar_pdf_frente_verso(folhas_frente, folhas_verso, "cartas")


INSTRUCOES_PREVIEW = """\
[bold]Antes de imprimir de verdade:[/]
 1. Ao mandar o PDF pra impressora, confira: papel A4, [bold]"Tamanho Real" /
    sem escala (100%)[/] - NUNCA "Ajustar a pagina", senao a grade sai de
    posicao.
 2. Pra esse teste, imprima em [bold]1 folha de sulfite comum[/] - so depois
    de bater o alinhamento e que vale gastar o papel triplex 300g.
 3. Depois de imprimir, meca 1 carta com regua: tem que dar 59x86mm certinho,
    cortando bem no meio da linha vermelha entre as celulas.

[bold]Se for testar o verso tambem:[/]
 4. Antes de tirar a folha da bandeja, repare QUAL BORDA entrou primeiro e
    QUAL LADO ficou virado pra cima.
 5. Vire a folha sempre pela [bold]mesma borda[/] (ex: sempre a borda comprida)
    antes de reinserir pro verso - se trocar de borda, o verso sai
    espelhado/fora de posicao.
 6. Se nao bater de primeira, ajuste e repita SO com essa 1 folha - nao vale a
    pena gastar o papel 300g testando em lote.
"""


async def _fluxo_preview() -> None:
    console.print(
        Panel(INSTRUCOES_PREVIEW, title="Prova de impressao", border_style="yellow")
    )
    cartas = await _escolher_cartas_para_imprimir()
    if not cartas:
        return
    cartas_teste = cartas[: layout.CARTAS_POR_FOLHA]
    if len(cartas_teste) < len(cartas):
        console.print(
            f"  [yellow]![/] Prova usa so as primeiras {len(cartas_teste)} carta(s) "
            "(1 folha) - o resto fica de fora desse teste"
        )

    caminho_verso = await _escolher_verso()
    folhas_frente, folhas_verso = montar_lote(cartas_teste, caminho_verso)
    await _exportar_pdf_frente_verso(folhas_frente, folhas_verso, "prova-impressao")


FLUXOS_IMPRIMIR = {
    "Montar PDF": _fluxo_montar_pdf,
    "Preview (so 1 folha)": _fluxo_preview,
}


# --- Menu principal --------------------------------------------------------


async def _rodar_submenu(titulo: str, fluxos: dict) -> None:
    while True:
        escolha = await questionary.select(
            titulo, choices=[*fluxos, VOLTAR]
        ).ask_async()
        if escolha is None or escolha == VOLTAR:
            return
        try:
            await fluxos[escolha]()
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelado.[/]")
        except AppError as erro:
            console.print(f"  [red]![/] {erro.message}")
        except Exception as erro:  # noqa: BLE001 - 1 fluxo com erro nao pode derrubar o menu inteiro
            console.print(f"  [red]![/] Erro inesperado: {erro}")
        console.print()


async def rodar_menu() -> None:
    mostrar_banner()
    while True:
        categoria = await questionary.select(
            "O que voce quer fazer?",
            choices=[CATEGORIA_CARTAS, CATEGORIA_DECKS, CATEGORIA_IMPRIMIR, OPCAO_SAIR],
        ).ask_async()
        if categoria is None or categoria == OPCAO_SAIR:
            break
        if categoria == CATEGORIA_CARTAS:
            await _rodar_submenu("Cartas - o que fazer?", FLUXOS_CARTAS)
        elif categoria == CATEGORIA_DECKS:
            await _rodar_submenu("Decks - o que fazer?", FLUXOS_DECKS)
        else:
            await _rodar_submenu("PDF - o que fazer?", FLUXOS_IMPRIMIR)


def main() -> None:
    configurar_stdio_utf8()
    try:
        asyncio.run(rodar_menu())
    except KeyboardInterrupt:
        console.print("\nAte mais!")
