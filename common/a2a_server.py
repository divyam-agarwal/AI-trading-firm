"""Thin wrapper over a2a-sdk server wiring. All SDK churn is contained here.

Downstream agents must NOT import a2a-sdk directly; use the interfaces below.
"""
from collections.abc import Callable

import uvicorn
from starlette.applications import Starlette

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
)
from a2a.utils.constants import DEFAULT_RPC_URL, PROTOCOL_VERSION_1_0, TransportProtocol

from common import telemetry


class _FunctionExecutor(AgentExecutor):
    """Wraps a plain ``handler(text: str) -> str`` callable as an A2A executor."""

    def __init__(self, handler: Callable[[str], str], name: str) -> None:
        self._handler = handler
        self._name = name

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        # Read the incoming W3C carrier (verified to live on context.metadata).
        try:
            carrier = dict(context.metadata or {})
        except Exception:
            carrier = {}
        # Run the handler inside a server span that continues the remote trace,
        # so any LLM span created inside the handler parents into this span.
        with telemetry.server_span(self._name, carrier):
            result = self._handler(text)
        await event_queue.enqueue_event(new_text_message(result, role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def build_agent_app(
    *,
    name: str,
    description: str,
    skill_id: str,
    skill_name: str,
    url: str,
    handler: Callable[[str], str],
) -> Starlette:
    """Build and return a Starlette app that serves the A2A agent card and JSON-RPC endpoint.

    Args:
        name: Human-readable agent name (appears in the agent card).
        description: Short description of what the agent does.
        skill_id: Stable identifier for the agent's single skill.
        skill_name: Human-readable skill name.
        url: Public URL the agent card advertises (fed into AgentInterface).
        handler: Callable that receives the user's text and returns a reply string.

    Returns:
        A configured Starlette application ready to be served with uvicorn.
    """
    card = AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=description,
                tags=["finance"],
            )
        ],
        supported_interfaces=[
            AgentInterface(
                protocol_binding=TransportProtocol.JSONRPC,
                url=url,
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=_FunctionExecutor(handler, name),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )

    routes = create_agent_card_routes(agent_card=card) + create_jsonrpc_routes(
        request_handler=request_handler, rpc_url=DEFAULT_RPC_URL
    )
    return Starlette(routes=routes)


def run_agent(app: Starlette, *, host: str, port: int) -> None:
    """Start a uvicorn server (blocking) for the given Starlette app."""
    uvicorn.run(app, host=host, port=port, log_level="info")
