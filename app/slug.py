"""Slug compartilhado - nome de carta/deck -> nome de arquivo/pasta seguro
(sem acento/espaco/maiuscula). Usado tanto pro nome do arquivo da carta
(app.maker.service) quanto pro nome das pastas de deck (app.cli.menu)."""

import re
import unicodedata


def slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()
