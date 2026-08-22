# script-yugioh-maker

Automação que busca os dados oficiais de uma carta Yu-Gi-Oh! (em português) na
API da [YGOPRODeck](https://ygoprodeck.com/api-guide/) e usa esses dados +
Playwright pra preencher o [yugiohcardmaker.org](https://yugiohcardmaker.org/pt#card-editor)
sozinho: nome, texto, ATK/DEF, atributo, raça, pêndulo, marcadores de Link,
e a arte da carta (baixada da própria API). No final, descarrega a imagem
gerada e salva em `output/`.

## Requisitos

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
uv run playwright install chromium
cp .env.example .env
```

### Configuração (`.env`)

| Variável | Default | Descrição |
|---|---|---|
| `PORT` | `3000` | Porta da API FastAPI |
| `OUTPUT_DIR` | `output` | Pasta onde as imagens geradas são salvas |
| `HEADLESS` | `true` | `false` abre a janela do Chrome durante a automação (debug visual) |

## Uso

### CLI (fluxo principal)

```bash
uv run cli.py "Mago Negro"
```

Busca a carta pelo nome em português, decide se é monstro ou magia/armadilha,
preenche o maker e salva o resultado em `output/<nome-da-carta>.png`.

Funciona pra qualquer tipo de carta: Normal, Efeito, Fusão, Ritual, Sincro,
Xyz, Link (com Pêndulo ou não), Magia e Armadilha.

### API (só consulta de dados)

```bash
uv run uvicorn app.main:app --port 3000
```

- `GET /health`
- `GET /cards/{nome}` — retorna o JSON cru da API oficial (já traduzido pra
  PT), útil pra conferir os dados antes de rodar a automação. Testável pela
  coleção em `bruno/`.

## Estrutura

```
app/
├── main.py          # FastAPI (so a API de consulta de cards)
├── config.py         # env (porta)
├── cards/
│   ├── enums.py       # CardAttribute, CardType, MonsterRace, SpellTrapSubtype, LinkMarker
│   ├── models.py       # CardData (Pydantic, valida contra os enums)
│   ├── service.py       # busca na API oficial (YGOPRODeck)
│   └── routes.py
└── maker/
    └── service.py      # automacao Playwright: preenche + baixa a imagem
cli.py                  # comando `fill` (typer)
bruno/                  # colecao de requests HTTP versionada
```

## Limitações conhecidas

- **Token**: a API não traz `attribute`/`atk`/`def`/`level` pra cartas Token
  (são só marcadores genéricos — a própria descrição diz "aplique o
  Tipo/Atributo/Nível/ATK/DEF de outra ficha"). `fill_monster_card` falha com
  erro claro em vez de inventar esses dados.

## Notas técnicas

- A API oficial não aceita busca exata (`name`) junto com `language=pt`; a
  busca usa `fname` (parcial) + `language=pt`, que funciona nos dois, e escolhe
  o resultado cujo nome bate exato.
- O `yugiohcardmaker.org` não associa `<label>` aos campos via `for` nem
  aninhamento — a automação localiza campos pelo texto do label e navega a
  estrutura ao redor (ver comentários em `app/maker/service.py`).
- `output/` (imagens geradas) não é versionado.
