from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    """Envelope padrao das respostas da API: sucesso sempre com
    success/message/data, erro (ver app.errors) com success/message via
    exception handler central em main.py."""

    success: bool = True
    message: str
    data: T
