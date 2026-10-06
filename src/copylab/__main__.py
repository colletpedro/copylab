"""Ponto de entrada de ``python -m copylab``.

Despacha para o app Typer definido em :mod:`copylab.cli`.
"""

from copylab.cli import app


def main() -> None:
    """Executa o CLI."""
    app()


if __name__ == "__main__":
    main()
