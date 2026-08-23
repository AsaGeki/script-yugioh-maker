"""Orquestra o fluxo de PDF: monta as folhas (layout.py) pra frente e/ou
verso. Consumido pelo menu (app.cli.menu), sem nenhum questionary aqui - so a
logica de montagem."""

from pathlib import Path

from PIL import Image

from app.print import layout


def montar_lote(
    caminhos_cartas: list[Path],
    caminho_verso: Path | None,
    *,
    marca_corte: bool = True,
) -> tuple[list[Image.Image], list[Image.Image]]:
    """Retorna (folhas_frente, folhas_verso). folhas_verso vem vazia se
    caminho_verso for None (fluxo "so frente"); senao, 1 folha de verso pra
    cada folha de frente, com a mesma quantidade de celulas preenchidas."""
    folhas_frente = layout.montar_folhas_frente(caminhos_cartas, marca_corte=marca_corte)
    if caminho_verso is None:
        return folhas_frente, []

    folhas_verso = []
    restante = len(caminhos_cartas)
    for _ in folhas_frente:
        quantidade = min(layout.CARTAS_POR_FOLHA, restante)
        folhas_verso.append(
            layout.montar_folha_verso(caminho_verso, quantidade, marca_corte=marca_corte)
        )
        restante -= quantidade
    return folhas_frente, folhas_verso
