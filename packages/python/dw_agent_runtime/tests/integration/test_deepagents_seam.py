"""Deep Agents cắm vào runner sẵn có mà không phải sửa runner (lab sandbox).

``create_deep_agent`` trả về graph ĐÃ compile, còn ``LangGraphWorkflowRunner``
gọi ``factory().compile(checkpointer=...)``. ``DeepAgentGraphSpec`` khớp hai
hình dạng đó lại. Test này giữ cho mối ghép ấy không âm thầm gãy:

- compile được với ``SqlAlchemyCheckpointSaver`` (đúng lời gọi của runner);
- checkpoint ghi thật xuống ``platform.run_checkpoints`` theo tenant;
- ``interrupt_on`` sinh ``state["__interrupt__"]`` — đúng thứ
  ``_handle_outcome`` biến thành ApprovalRequest;
- resume sau khi duyệt thì chạy nốt.

Model là fake nên test không gọi ra mạng.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.types import Command
from runtime_harness import RuntimeUrls
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dw_agent_runtime.adapters.checkpoint import SqlAlchemyCheckpointSaver
from dw_agent_runtime.adapters.deepagents_graph import DeepAgentGraphSpec

pytestmark = pytest.mark.integration

TENANT = uuid.uuid4()
WORKSPACE = uuid.uuid4()


@tool
def send_rfq(supplier: str) -> str:
    """Gửi RFQ cho nhà cung cấp (side effect — phải duyệt trước)."""
    return f"đã gửi RFQ cho {supplier}"


class _ToolThenAnswer(GenericFakeChatModel):
    """Lượt đầu gọi ``send_rfq``; sau khi có ToolMessage thì trả lời thường."""

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        already_ran = any(getattr(m, "type", "") == "tool" for m in messages)
        message = (
            AIMessage(content="Đã gửi RFQ xong.")
            if already_ran
            else AIMessage(
                content="",
                tool_calls=[{"name": "send_rfq", "args": {"supplier": "ACME"}, "id": "call_1"}],
            )
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


async def test_deep_agent_pauses_for_approval_and_resumes(urls: RuntimeUrls) -> None:
    engine = create_async_engine(urls.app)
    try:
        saver = SqlAlchemyCheckpointSaver(async_sessionmaker(engine, expire_on_commit=False))
        spec = DeepAgentGraphSpec(
            model=_ToolThenAnswer(messages=iter([])),
            system_prompt="Bạn là trợ lý mua hàng.",
            tools=[send_rfq],
            interrupt_on={"send_rfq": True},
        )
        graph = spec.compile(checkpointer=saver)

        run_id = uuid.uuid4()
        config: dict[str, Any] = {
            "configurable": {
                "thread_id": str(run_id),
                "tenant_id": str(TENANT),
                "workspace_id": str(WORKSPACE),
            }
        }

        paused = await graph.ainvoke({"messages": [("user", "Gửi RFQ cho ACME")]}, config)
        interrupts = paused.get("__interrupt__")
        assert interrupts, "interrupt_on phải làm agent dừng trước khi chạy tool"
        assert interrupts[0].value["action_requests"][0]["name"] == "send_rfq"

        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT)}
            )
            saved = (
                await conn.execute(
                    text("SELECT count(*) FROM platform.run_checkpoints WHERE run_id = :r"),
                    {"r": run_id},
                )
            ).scalar()
        assert saved and saved > 0, "state của deep agent phải nằm trong platform.run_checkpoints"

        # Middleware HITL của deepagents nhận {"decisions": [...]}, KHÔNG phải
        # {"approved": ...} mà ApproveAndResumeService đang gửi — chỗ cần một
        # lớp dịch khi đưa lõi này vào luồng duyệt thật.
        resumed = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
        assert not resumed.get("__interrupt__")
        assert "Đã gửi RFQ xong." in resumed["messages"][-1].content
    finally:
        await engine.dispose()
