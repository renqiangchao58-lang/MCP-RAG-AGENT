import pytest

from support_pilot.agent import AgentService
from support_pilot.business import LocalBusinessGateway
from support_pilot.knowledge import KnowledgeService
from support_pilot.repository import SupportRepository


class UnavailableBusinessGateway:
    async def get_order(self, order_id):
        raise RuntimeError("service unavailable")

    async def get_customer(self, customer_id):
        raise RuntimeError("service unavailable")

    async def list_tickets(self, order_id):
        raise RuntimeError("service unavailable")

    async def create_ticket(self, **kwargs):
        raise RuntimeError("service unavailable")


@pytest.fixture
def agent_stack(app_settings):
    knowledge = KnowledgeService(app_settings)
    knowledge.rebuild()
    repository = SupportRepository(app_settings.support_db_path)
    agent = AgentService(knowledge, LocalBusinessGateway(repository))
    yield agent, repository
    knowledge.close()


@pytest.mark.asyncio
async def test_combined_rag_and_business_answer(agent_stack):
    agent, _ = agent_stack

    response = await agent.chat("thread-1", "订单 A1024 延迟五天，按政策是否能补偿？")

    assert response.route == "combined"
    assert "50 元" in response.answer
    assert response.citations[0].source == "售后补偿政策.md"
    assert response.tool_traces[0].name == "get_order"


@pytest.mark.asyncio
async def test_write_requires_confirmation_and_can_be_rejected(agent_stack):
    agent, repository = agent_stack
    initial_count = repository.counts()["tickets"]

    await agent.chat("thread-2", "查询订单 A1024 的状态")
    pending = await agent.chat("thread-2", "帮我创建工单")
    assert pending.pending_action is not None
    assert repository.counts()["tickets"] == initial_count

    rejected = agent.reject_action("thread-2", pending.pending_action.id)
    assert "没有执行" in rejected.answer
    assert repository.counts()["tickets"] == initial_count


@pytest.mark.asyncio
async def test_confirm_executes_exactly_one_write(agent_stack):
    agent, repository = agent_stack
    pending = await agent.chat("thread-3", "帮订单 A1024 创建工单")
    initial_count = repository.counts()["tickets"]

    confirmed = await agent.confirm_action("thread-3", pending.pending_action.id)

    assert "工单已创建" in confirmed.answer
    assert confirmed.tool_traces[0].name == "create_ticket"
    assert repository.counts()["tickets"] == initial_count + 1
    with pytest.raises(ValueError):
        await agent.confirm_action("thread-3", pending.pending_action.id)


@pytest.mark.asyncio
async def test_business_failure_returns_a_safe_actionable_message(app_settings):
    knowledge = KnowledgeService(app_settings)
    knowledge.rebuild()
    agent = AgentService(knowledge, UnavailableBusinessGateway())
    try:
        response = await agent.chat("thread-error", "查询订单 A1024 的状态")
    finally:
        knowledge.close()

    assert "业务系统暂时不可用" in response.answer
    assert response.tool_traces[0].status == "error"
