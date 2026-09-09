"""POST /api/v1/channel-link/code — mint a code to link a chat account.

The web half of the exchange. SSO has already established who is asking, so
the code is minted for them and nobody else; the chat side later proves only
that it was holding the code.

No authorization beyond having a context. The strongest thing a code can do is
attach a chat account to the person who asked for it, so there is nothing here
to escalate to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from dw_api.bootstrap import ApiContainer
from dw_api.dependencies.auth import RequireAccessContext, get_container
from dw_kernel.errors import InfrastructureError


class LinkCodeResponse(BaseModel):
    code: str = Field(description="Nhắn nguyên mã này cho bot để liên kết.")
    expires_at: datetime
    channel: str


router = APIRouter(tags=["identity"])


@router.post("/channel-link/code", response_model=LinkCodeResponse)
async def issue_link_code(
    context: RequireAccessContext,
    container: Annotated[ApiContainer, Depends(get_container)],
    channel: str = "zalo",
) -> LinkCodeResponse:
    if container.issue_channel_link is None:
        raise InfrastructureError("channel linking is not configured")
    issued = await container.issue_channel_link.handle(context, issuer=channel)
    return LinkCodeResponse(code=issued.code, expires_at=issued.expires_at, channel=channel)
