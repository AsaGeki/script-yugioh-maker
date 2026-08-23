"""Exporta as folhas montadas (ver layout.py) pra 1 arquivo PDF, 1 pagina
por folha - pro fluxo "gerar PDF e imprimir manualmente"."""

from pathlib import Path

from PIL import Image

from app.config import OUTPUT_DIR
from app.errors import BadRequestError

OUTPUT_PATH = Path(OUTPUT_DIR)


def exportar_pdf(folhas: list[Image.Image], nome_arquivo: str) -> Path:
    if not folhas:
        raise BadRequestError("Nenhuma folha pra exportar")
    OUTPUT_PATH.mkdir(exist_ok=True)
    destino = OUTPUT_PATH / nome_arquivo
    primeira, *resto = folhas
    primeira.save(
        destino, "PDF", resolution=float(300), save_all=True, append_images=resto
    )
    return destino
