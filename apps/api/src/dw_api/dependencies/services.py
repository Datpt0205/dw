"""Container dependency shared by route modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

if TYPE_CHECKING:
    from dw_api.bootstrap import ApiContainer


def get_container(request: Request) -> ApiContainer:
    container: ApiContainer = request.app.state.container
    return container


RequireContainer = Annotated["ApiContainer", Depends(get_container)]
