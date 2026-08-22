# script-yugioh-maker

Busca os dados oficiais de uma carta Yu-Gi-Oh! (traduzidos pra português) na
[API da YGOPRODeck](https://ygoprodeck.com/api-guide/) e usa Playwright pra
preencher sozinho o
[yugiohcardmaker.org](https://yugiohcardmaker.org/pt#card-editor): nome,
texto, ATK/DEF, atributo, raça, pêndulo, marcadores de Link e a arte da
carta. Cobre carta avulsa, arquétipo, structure deck oficial, deck público
ou importado (`ydke://`/`.ydk`/`.txt`), e deck montado na mão.

> A API FastAPI incluída aqui é só consulta de dados (pra conferir antes de
> gerar) — quem preenche e baixa a carta é o CLI.

## Stack

- Python 3.13+
- FastAPI (API de consulta de dados)
- Playwright (automação do navegador)
- Typer, questionary, rich (CLI interativo)
- Pydantic (validação dos dados da API oficial)
- uv (gerenciador de pacotes)

## Como rodar

Pré-requisitos: Python 3.13+, [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
uv run cli.py
```

Sem argumento abre o menu interativo (Cartas/Decks); `cli.py fill "nome"`
gera direto, sem menu. Nenhuma variável em `.env` é obrigatória — `PORT`,
`OUTPUT_DIR` e `HEADLESS` já têm default.

## Sobre

Meu nome é Arthur Gabriel e este projeto veio com a ideia de facilitar a sintetização de cartas de Yu-Gi-Oh em portugues e com boa qualidade.
Também feito para organiza-las e deixar pronto para impressão.

---

Feito com esforço por [AsaGeki](https://github.com/AsaGeki) 🐧❤️
