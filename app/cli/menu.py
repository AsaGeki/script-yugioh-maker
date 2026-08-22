"""Menu interativo do CLI (banner + navegacao por seta via questionary) -
alternativa ao modo direto `cli.py fill "nome"` pra quem quer explorar sem
decorar flag nenhuma. 2 categorias: Cartas (avulsa) e Decks (varias de uma
vez).

Todo prompt usa `ask_async()`, nunca `ask()` (sincrono) - o menu roda dentro
de 1 `asyncio.run()` so, ver main().
"""

import asyncio
from typing import Any

import pyfiglet
import questionary
from playwright.async_api import Browser, async_playwright
from rich.console import Console
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
from app.config import HEADLESS
from app.deck.api import search_decks
from app.deck.service import buscar_cartas_de_resultado, buscar_cartas_do_deck
from app.errors import AppError
from app.maker.service import fill_card

console = Console()

CATEGORIA_CARTAS = "Cartas"
CATEGORIA_DECKS = "Decks"
OPCAO_SAIR = "Sair"
VOLTAR = "Voltar"


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
    carta: CardData, *, browser: Browser | None = None, confirmar: bool = True
) -> None:
    """No lote (`confirmar=False`), a selecao no checkbox ja e a confirmacao -
    so pergunta de novo quando ha variante de arte (escolher_variante)."""
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
    destino = await fill_card(carta, imagem, browser=browser)
    console.print(f"  [green]OK[/] salvo em [bold]{destino}[/]")


async def _gerar_varias(cartas: list[CardData]) -> None:
    """Abre 1 Chromium so e reusa pra todas as cartas do lote - abrir/fechar
    1 browser por carta era o gargalo de velocidade gerando varias de uma vez."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        try:
            for indice, carta in enumerate(cartas, start=1):
                console.rule(f"{indice}/{len(cartas)}: {carta.name}")
                try:
                    await _gerar_uma(carta, browser=browser, confirmar=False)
                except AppError as erro:
                    console.print(f"  [red]![/] {erro.message}")
        finally:
            await browser.close()


async def _escolher_e_gerar(
    cartas: list[CardData], *, pre_marcadas: bool = False
) -> None:
    """Mostra a tabela de resultado + checkbox de selecao multipla - usado
    por todo fluxo que termina numa lista de cartas candidatas (arquetipo,
    estrutural, deck publico, deck importado, deck montado na mao)."""
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
        await _gerar_varias(escolhidas)


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
    await _escolher_e_gerar(await find_cards_by_cardset(nome_set), pre_marcadas=True)


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
    await _escolher_e_gerar(cartas, pre_marcadas=True)


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
    await _escolher_e_gerar(cartas, pre_marcadas=True)


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

    await _escolher_e_gerar(acumuladas, pre_marcadas=True)


FLUXOS_DECKS = {
    "Buscar por estruturais": _fluxo_estruturais,
    "Buscar por nome de deck": _fluxo_buscar_deck_por_nome,
    "Importar deck (link/.ydk/.txt)": _fluxo_importar_deck,
    "Montar deck": _fluxo_montar_deck,
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
            choices=[CATEGORIA_CARTAS, CATEGORIA_DECKS, OPCAO_SAIR],
        ).ask_async()
        if categoria is None or categoria == OPCAO_SAIR:
            break
        if categoria == CATEGORIA_CARTAS:
            await _rodar_submenu("Cartas - o que fazer?", FLUXOS_CARTAS)
        else:
            await _rodar_submenu("Decks - o que fazer?", FLUXOS_DECKS)


def main() -> None:
    configurar_stdio_utf8()
    try:
        asyncio.run(rodar_menu())
    except KeyboardInterrupt:
        console.print("\nAte mais!")
