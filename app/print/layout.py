"""Monta a folha A4 com as cartas em grade 3x3 (9 por folha), com linha de
corte vermelha entre as celulas - 1 "folha" = 1 Image do Pillow representando
1 pagina A4 inteira a 300dpi. pdf.py so consome essa lista de Image, nao sabe
nada de grade/mm.
"""

from pathlib import Path

from PIL import Image, ImageDraw

DPI = 300
MM_POR_POLEGADA = 25.4

A4_LARGURA_MM = 210
A4_ALTURA_MM = 297
CARTA_LARGURA_MM = 59
CARTA_ALTURA_MM = 86
COLUNAS = 3
LINHAS = 3
CARTAS_POR_FOLHA = COLUNAS * LINHAS

# Espaco entre cartas vizinhas na grade - da margem de corte de verdade (a
# linha vermelha fica no meio desse espaco), em vez de cartas coladas.
ESPACO_ENTRE_CARTAS_MM = 0
LINHA_CORTE_COR = "red"
LINHA_CORTE_ESPESSURA_PX = 3


def _mm_para_px(mm: float) -> int:
    return round(mm * DPI / MM_POR_POLEGADA)


A4_LARGURA_PX = _mm_para_px(A4_LARGURA_MM)
A4_ALTURA_PX = _mm_para_px(A4_ALTURA_MM)
CARTA_LARGURA_PX = _mm_para_px(CARTA_LARGURA_MM)
CARTA_ALTURA_PX = _mm_para_px(CARTA_ALTURA_MM)
ESPACO_ENTRE_CARTAS_PX = _mm_para_px(ESPACO_ENTRE_CARTAS_MM)

_GRADE_LARGURA_PX = (
    CARTA_LARGURA_PX * COLUNAS + ESPACO_ENTRE_CARTAS_PX * (COLUNAS - 1)
)
_GRADE_ALTURA_PX = CARTA_ALTURA_PX * LINHAS + ESPACO_ENTRE_CARTAS_PX * (LINHAS - 1)
_MARGEM_X_PX = (A4_LARGURA_PX - _GRADE_LARGURA_PX) // 2
_MARGEM_Y_PX = (A4_ALTURA_PX - _GRADE_ALTURA_PX) // 2


def _posicoes_grade() -> list[tuple[int, int]]:
    """Canto superior-esquerdo (x, y) em px de cada 1 das 9 celulas, grade
    centralizada na folha - ordem linha a linha (esquerda->direita, cima->baixo)."""
    passo_x = CARTA_LARGURA_PX + ESPACO_ENTRE_CARTAS_PX
    passo_y = CARTA_ALTURA_PX + ESPACO_ENTRE_CARTAS_PX
    return [
        (_MARGEM_X_PX + col * passo_x, _MARGEM_Y_PX + lin * passo_y)
        for lin in range(LINHAS)
        for col in range(COLUNAS)
    ]


def _fronteiras_de_corte(margem_px: int, tamanho_celula_px: int, quantidade: int) -> list[int]:
    """Posicao (px), num eixo, de cada linha de corte: comeca na borda
    externa da grade, passa pelo meio do espaco entre cada par de celulas
    vizinhas, termina na borda externa oposta - sempre `quantidade + 1`
    linhas pra `quantidade` celulas."""
    passo_px = tamanho_celula_px + ESPACO_ENTRE_CARTAS_PX
    fronteiras = [margem_px]
    for indice in range(1, quantidade):
        fronteiras.append(margem_px + indice * passo_px - ESPACO_ENTRE_CARTAS_PX // 2)
    fronteiras.append(margem_px + quantidade * tamanho_celula_px + (quantidade - 1) * ESPACO_ENTRE_CARTAS_PX)
    return fronteiras


def _desenhar_linhas_de_corte(desenho: ImageDraw.ImageDraw) -> None:
    """Grade INTEIRA de linhas vermelhas (bordas externas + 1 linha no meio
    de cada espaco entre celulas) - sempre a grade fixa de 3x3, mesmo com
    celula vazia (verso pode ter menos cartas que celulas). Linhas atravessam
    a folha de ponta a ponta (nao param na borda da grade) pra servir de
    guia de alinhamento na guilhotina."""
    xs = _fronteiras_de_corte(_MARGEM_X_PX, CARTA_LARGURA_PX, COLUNAS)
    ys = _fronteiras_de_corte(_MARGEM_Y_PX, CARTA_ALTURA_PX, LINHAS)
    for x in xs:
        desenho.line([(x, 0), (x, A4_ALTURA_PX)], fill=LINHA_CORTE_COR, width=LINHA_CORTE_ESPESSURA_PX)
    for y in ys:
        desenho.line([(0, y), (A4_LARGURA_PX, y)], fill=LINHA_CORTE_COR, width=LINHA_CORTE_ESPESSURA_PX)


def _nova_folha() -> Image.Image:
    return Image.new("RGB", (A4_LARGURA_PX, A4_ALTURA_PX), "white")


def montar_folhas_frente(
    caminhos_cartas: list[Path], *, marca_corte: bool = True
) -> list[Image.Image]:
    """Monta 1 ou mais folhas A4 com as cartas em grade 3x3, na ordem
    recebida (9 por folha). A ultima folha fica com celulas sobrando em
    branco se o total nao for multiplo de 9."""
    folhas: list[Image.Image] = []
    for inicio in range(0, len(caminhos_cartas), CARTAS_POR_FOLHA):
        lote = caminhos_cartas[inicio : inicio + CARTAS_POR_FOLHA]
        folha = _nova_folha()
        for (x, y), caminho in zip(_posicoes_grade(), lote):
            carta = Image.open(caminho).convert("RGB").resize(
                (CARTA_LARGURA_PX, CARTA_ALTURA_PX), Image.LANCZOS
            )
            folha.paste(carta, (x, y))
        if marca_corte:
            _desenhar_linhas_de_corte(ImageDraw.Draw(folha))
        folhas.append(folha)
    return folhas


def montar_folha_verso(
    caminho_verso: Path, quantidade: int, *, marca_corte: bool = True
) -> Image.Image:
    """Monta 1 folha A4 so com o verso, repetido em ate `quantidade` celulas
    (bate com o tanto de cartas da folha de frente correspondente, pra nao
    desenhar verso de celula vazia). Como o verso e IGUAL em toda carta, nao
    importa casar posicao com a frente - so a grade em si (mesma
    margem/tamanho/espaco de montar_folhas_frente) precisa bater."""
    verso = Image.open(caminho_verso).convert("RGB").resize(
        (CARTA_LARGURA_PX, CARTA_ALTURA_PX), Image.LANCZOS
    )
    folha = _nova_folha()
    for x, y in _posicoes_grade()[:quantidade]:
        folha.paste(verso, (x, y))
    if marca_corte:
        _desenhar_linhas_de_corte(ImageDraw.Draw(folha))
    return folha
