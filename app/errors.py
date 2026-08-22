"""Erros de dominio conhecidos - diferente de bug (500), sao situacoes
esperadas (carta nao encontrada, dado invalido) que a API converte pra uma
resposta HTTP tratada em vez de deixar estourar como erro interno."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404


class BadRequestError(AppError):
    status_code = 400
