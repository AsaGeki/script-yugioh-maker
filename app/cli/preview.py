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
    if not carta.traduzida:
        linhas.append("[red]Sem traducao PT - nome/texto em ingles[/]")
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


def _renderizar_imagem(url: str, largura: int) -> list[str]:
    """Baixa e renderiza 1 imagem, devolve as linhas ja prontas (BaseImage
    tem __str__ que devolve o texto renderizado, sem escrever no stdout) -
    assim da pra compor varias lado a lado em vez de so uma por vez."""
    try:
        return str(from_url(url, width=largura)).splitlines()
    except Exception as exc:  # noqa: BLE001 - preview e so-o-melhor-esforco, nunca deve travar o fluxo
        return [f"[nao consegui mostrar: {exc}]"]


def mostrar_variantes_em_grade(
    variantes: list[CardImage], *, colunas: int = 3, largura_cada: int = 28
) -> None:
    """Mostra as variantes lado a lado (ate `colunas` por linha) em vez de
    empilhadas - evita rolar o terminal pra comparar."""
    for inicio in range(0, len(variantes), colunas):
        lote = variantes[inicio : inicio + colunas]
        print(
            "  ".join(
                f"Variante {inicio + i + 1}".center(largura_cada)
                for i in range(len(lote))
            )
        )

        blocos = [_renderizar_imagem(v.image_url_cropped, largura_cada) for v in lote]
        altura = max(len(bloco) for bloco in blocos)
        for bloco in blocos:
            bloco.extend([" " * largura_cada] * (altura - len(bloco)))
        for linha in range(altura):
            print("  ".join(bloco[linha] for bloco in blocos))


async def escolher_variante(carta: CardData) -> CardImage:
    """Se a carta so tem 1 arte, devolve ela direto. Se tem mais de 1 (reprint
    com arte alternativa), mostra o preview de cada uma e deixa escolher."""
    if len(carta.card_images) == 1:
        return carta.card_images[0]

    console.print(
        f"\n[bold]'{carta.name}' tem {len(carta.card_images)} variantes de arte:[/]"
    )
    mostrar_variantes_em_grade(carta.card_images)

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
