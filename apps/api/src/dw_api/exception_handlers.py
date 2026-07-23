"""Maps kernel error taxonomy onto the unified HTTP error schema."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dw_api.errors import ErrorResponse, status_for
from dw_kernel.errors import DWError, ErrorCode


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DWError)
    async def handle_dw_error(request: Request, exc: DWError) -> JSONResponse:
        body = ErrorResponse(
            code=exc.code.value,
            message=exc.message,
            details={k: str(v) for k, v in exc.details.items()},
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=status_for(exc.code), content=body.model_dump())

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals; taxonomy code only.
        body = ErrorResponse(
            code=ErrorCode.INTERNAL.value,
            message="internal error",
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=500, content=body.model_dump())
