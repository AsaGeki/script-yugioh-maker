"""Reconfiguracao de encoding do terminal - modulo proprio pra ser chamado
tanto pelo cli.py (comando `fill` direto) quanto pelo app.cli.menu (menu
interativo), sem duplicar a funcao nos 2 entrypoints."""

import sys


def configurar_stdio_utf8() -> None:
    """O console padrao do Windows abre em cp1252/cp850, que nao tem varios
    caracteres que o app usa (acentos, letras gregas de nome de carta, blocos
    do preview de imagem) - sem isso, rich/term-image estouram
    UnicodeEncodeError no meio do fluxo."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
