"""Extrai a lista de cartas de um deck publico do proprio ygoprodeck.com
(ex: https://ygoprodeck.com/deck/nome-123456) via scraping - a API oficial
nao expoe deck publico nenhum (so cardinfo/archetypes/cardsets/checkDBVer).

Cada carta do deck aparece na pagina como um link
`<a href="/card/?search={passcode}">` (1 link por copia), entao so
precisamos coletar esses hrefs.
"""

import re
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

from app.config import HEADLESS
from app.errors import NotFoundError

PADRAO_LINK_DECK = re.compile(r"ygoprodeck\.com/deck/", re.IGNORECASE)


def eh_link_de_deck(fonte: str) -> bool:
    return bool(PADRAO_LINK_DECK.search(fonte))


async def extrair_ids_do_deck(url: str) -> list[int]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        page = await browser.new_page()
        try:
            await page.goto(url)
            links = page.locator('a[href*="/card/?search="]')
            hrefs = [
                await links.nth(i).get_attribute("href")
                for i in range(await links.count())
            ]
        finally:
            await browser.close()

    ids = [
        int(passcode[0])
        for href in hrefs
        if href
        and (passcode := parse_qs(urlparse(href).query).get("search"))
        and passcode[0].isdigit()
    ]
    if not ids:
        raise NotFoundError(
            f'Nenhuma carta encontrada em "{url}" - o deck existe e esta publico?'
        )
    return ids
