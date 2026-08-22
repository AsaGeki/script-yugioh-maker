import asyncio
import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from app.cli.menu import main as rodar_menu_interativo
from app.cli.stdio import configurar_stdio_utf8
from app.errors import AppError
from app.maker.service import fill_card

configurar_stdio_utf8()

app = typer.Typer()
console = Console()
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    handlers=[RichHandler(console=console, show_time=False, show_path=False)],
)


@app.callback(invoke_without_command=True)
def principal(ctx: typer.Context):
    """Sem subcomando nenhum, abre o menu interativo. Com `fill "nome"`, gera direto sem menu."""
    if ctx.invoked_subcommand is None:
        rodar_menu_interativo()


@app.command()
def fill(nome_carta: str):
    """Busca a carta pelo nome na API oficial e preenche o Yu-Gi-Oh! Card Maker com ela."""
    console.print(f"[bold cyan]Buscando[/bold cyan] '{nome_carta}'...")
    try:
        destino = asyncio.run(fill_card(nome_carta))
    except AppError as erro:
        console.print(f"[bold red]Erro:[/bold red] {erro.message}")
        raise typer.Exit(code=1)
    console.print(f"[bold green]OK[/bold green] salvo em [bold]{destino}[/bold]")


if __name__ == "__main__":
    app()
