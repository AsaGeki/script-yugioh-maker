"""Parse de deck em formato `.ydk` (arquivo local) ou `ydke://` (link
compartilhavel usado por EDOPro/Master Duel/pelo proprio ygoprodeck.com) - os
2 formatos padrao da comunidade Yu-Gi-Oh, sem precisar de API nem scraping.

`.ydk` tem secoes `#main`, `#extra`, `!side`, 1 passcode numerico por linha.
"""

import base64
import struct
from pathlib import Path

from app.errors import BadRequestError, NotFoundError

SECOES_YDK = {"#main": "main", "#extra": "extra", "!side": "side"}


def _parse_ydk_texto(texto: str) -> list[int]:
    """Devolve os passcodes de main+extra - ignora side (mesmas cartas do
    main guardadas pra troca; gerar de novo so duplicaria trabalho)."""
    ids: list[int] = []
    secao_atual = None
    for linha_bruta in texto.splitlines():
        linha = linha_bruta.strip()
        if not linha:
            continue
        secao = SECOES_YDK.get(linha.split()[0].lower())
        if secao:
            secao_atual = secao
            continue
        if secao_atual == "side" or not linha.isdigit():
            continue
        ids.append(int(linha))
    return ids


def _decodificar_bloco_ydke(bloco_base64: str) -> list[int]:
    """Cada 4 bytes do base64 decodificado = 1 passcode em uint32 little-endian."""
    bruto = base64.b64decode(bloco_base64 + "=" * (-len(bloco_base64) % 4))
    quantidade = len(bruto) // 4
    return list(struct.unpack(f"<{quantidade}I", bruto[: quantidade * 4]))


def parse_ydke(link: str) -> list[int]:
    """Decodifica um link `ydke://main!extra!side!` - devolve passcodes de main+extra."""
    corpo = link.removeprefix("ydke://").rstrip("!")
    blocos = corpo.split("!")
    if len(blocos) < 2:
        raise BadRequestError(
            'Link ydke:// invalido - esperado pelo menos "main!extra!"'
        )
    return _decodificar_bloco_ydke(blocos[0]) + _decodificar_bloco_ydke(blocos[1])


def parse_ydk_arquivo(caminho: Path) -> list[int]:
    if not caminho.exists():
        raise NotFoundError(f'Arquivo "{caminho}" nao encontrado')
    return _parse_ydk_texto(caminho.read_text(encoding="utf-8"))
