"""Spec §8 error envelope: every 4xx/5xx body is {"error": "<pt-BR message>", "code": "<slug>"}."""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

# Fallbacks for errors raised without our own message (routing, framework, middleware).
DEFAULTS: dict[int, tuple[str, str]] = {
    400: ("Requisição inválida.", "bad_request"),
    403: ("Acesso negado.", "forbidden"),
    404: ("Não encontrado.", "not_found"),
    405: ("Método não permitido.", "method_not_allowed"),
    415: ("Envie os dados em JSON.", "json_required"),
    422: ("Dados inválidos.", "validation_error"),
    500: ("Erro interno do servidor.", "internal_error"),
}


class ApiError(HTTPException):
    """An HTTP error with a pt-BR message and a stable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code, {"error": message, "code": code})


def error_response(status_code: int, message: str | None = None, code: str | None = None,
                   headers: dict | None = None) -> JSONResponse:
    fallback = ("Erro.", "error" if status_code < 500 else "internal_error")
    default_message, default_code = DEFAULTS.get(status_code, fallback)
    return JSONResponse({"error": message or default_message, "code": code or default_code},
                        status_code=status_code, headers=headers)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and {"error", "code"} <= detail.keys():
        return error_response(exc.status_code, detail["error"], detail["code"], getattr(exc, "headers", None))
    return error_response(exc.status_code, headers=getattr(exc, "headers", None))  # English detail is not shown


def _field(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = sorted({f for f in (_field(tuple(e.get("loc", ()))) for e in exc.errors()) if f})
    message = f"Dados inválidos: {', '.join(fields)}." if fields else DEFAULTS[422][0]
    return error_response(422, message, "validation_error")


async def _server_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error")
    return error_response(500)


def install(app: FastAPI) -> None:
    # Starlette types handlers as taking `Exception`; ours take the subclass they are registered for.
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _server_error)
