"""Preview de carta no terminal antes de confirmar a geracao: ficha (rich
Panel) e a imagem de verdade (term-image - desenha via protocolo grafico do
terminal quando suportado, cai pra blocos coloridos sozinho quando nao)."""

import questionary
from rich.console import Console
from rich.panel import Panel
from term_image.image import from_url

from app.cards.models import CardData, CardImage

console = Console()


def mostrar_ficha(carta: CardData) -> None:
    linhas = [f"[bold]{carta.name}[/] ({carta.type})"]
    if carta.attribute:
        linhas.append(f"Atributo: {carta.attribute}")
    if carta.race:
        linhas.append(f"Raca/Subtipo: {carta.race}")
    if carta.level is not None:
        linhas.append(f"Nivel/Rank: {carta.level}")
    if carta.linkval is not None:
        linhas.append(f"Link: {carta.linkval}")
    if carta.atk is not None:
        def_texto = carta.def_ if carta.def_ is not None else "-"
        linhas.append(f"ATK/DEF: {carta.atk}/{def_texto}")
    if carta.desc:
        linhas.append(f"\n{carta.desc}")
    console.print(
        Panel("\n".join(linhas), title="Carta encontrada", border_style="cyan")
    )


def mostrar_imagem_no_terminal(url: str, largura: int = 60) -> None:
    """So-o-melhor-esforco: se o terminal nao aceita nenhum protocolo grafico
    (Kitty/iTerm2/Sixel), term-image cai pra blocos coloridos sozinho - ainda
    assim, se falhar por qualquer motivo, so avisa e segue sem travar o fluxo."""
    try:
        from_url(url, width=largura).draw()
    except Exception as exc:  # noqa: BLE001 - preview e so-o-melhor-esforco, nunca deve travar o fluxo
        console.print(f"  [yellow]![/] Nao consegui mostrar a imagem aqui: {exc}")


async def escolher_variante(carta: CardData) -> CardImage:
    """Se a carta so tem 1 arte, devolve ela direto. Se tem mais de 1 (reprint
    com arte alternativa), mostra o preview de cada uma e deixa escolher."""
    if len(carta.card_images) == 1:
        return carta.card_images[0]

    console.print(
        f"\n[bold]'{carta.name}' tem {len(carta.card_images)} variantes de arte:[/]"
    )
    for indice, imagem in enumerate(carta.card_images, start=1):
        console.print(f"\n[bold]Variante {indice}[/] (id {imagem.id})")
        mostrar_imagem_no_terminal(imagem.image_url_cropped)

    escolha = await questionary.select(
        "Qual variante usar?",
        choices=[
            questionary.Choice(f"Variante {indice} (id {imagem.id})", imagem)
            for indice, imagem in enumerate(carta.card_images, start=1)
        ],
    ).ask_async()
    if escolha is None:
        raise KeyboardInterrupt
    return escolha
