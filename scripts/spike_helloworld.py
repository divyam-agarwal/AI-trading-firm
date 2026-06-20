"""Verify the installed a2a-sdk server+client round trip. Throwaway smoke test.

# VERIFIED API (a2a-sdk==1.1.0, Python 3.13.7):
#
# DEVIATIONS FROM BRIEF's DOCUMENTED SHAPE:
#
# 1. NO A2AStarletteApplication class exists.
#    Build Starlette app manually using route helpers:
#      from a2a.server.routes import create_jsonrpc_routes, create_agent_card_routes
#      from starlette.applications import Starlette
#      from starlette.routing import Route
#
# 2. NO a2a.utils.new_agent_text_message.
#    Correct import:
#      from a2a.helpers.proto_helpers import new_text_message
#
# 3. AgentCard, AgentCapabilities, AgentSkill, AgentInterface are PROTOBUF messages,
#    not pydantic. They live in a2a.types.a2a_pb2 (re-exported from a2a.types).
#    AgentCard requires `supported_interfaces` (list[AgentInterface]) to tell the
#    client which transport/URL to use:
#      from a2a.types import AgentCard, AgentCapabilities, AgentSkill, AgentInterface
#      from a2a.utils.constants import TransportProtocol, DEFAULT_RPC_URL, PROTOCOL_VERSION_1_0
#      card = AgentCard(
#          name="Echo", description="echo agent", version="0.0.1",
#          default_input_modes=["text/plain"], default_output_modes=["text/plain"],
#          capabilities=AgentCapabilities(streaming=False),
#          skills=[AgentSkill(id="echo", name="echo", description="echo text", tags=["demo"])],
#          supported_interfaces=[
#              AgentInterface(
#                  protocol_binding=TransportProtocol.JSONRPC,
#                  url="http://127.0.0.1:9999/",
#                  protocol_version=PROTOCOL_VERSION_1_0,
#              )
#          ],
#      )
#
# 4. DefaultRequestHandler = DefaultRequestHandlerV2 (alias in __init__.py).
#    LegacyRequestHandler is the old behaviour (previously called DefaultRequestHandler).
#    Both require agent_card= positional-or-keyword arg (brief omits this).
#      from a2a.server.request_handlers import DefaultRequestHandler
#      handler = DefaultRequestHandler(
#          agent_executor=EchoExecutor(),
#          task_store=InMemoryTaskStore(),
#          agent_card=card,
#      )
#
# 5. EventQueue (a2a.server.events.EventQueue) is now an ABC — executors NEVER
#    construct it; the framework passes one in. The execute signature is unchanged:
#      async def execute(self, context: RequestContext, event_queue: EventQueue) -> None
#
# 6. Client.send_message takes SendMessageRequest (protobuf), NOT a raw Message:
#      from a2a.types import SendMessageRequest, Role, Message
#      from a2a.helpers.proto_helpers import new_text_message
#      msg = new_text_message("hi", role=Role.ROLE_USER)
#      request = SendMessageRequest(message=msg)
#      async for stream_response in client.send_message(request):  # NO await — it's an AsyncGenerator
#          print("RESPONSE:", stream_response)
#
# 7. ClientFactory.create(card) -> Client (no ClientConfig needed for defaults).
#    ClientConfig is a @dataclass (not pydantic). streaming=False disables streaming.
#
# 8. InMemoryTaskStore import path unchanged:
#      from a2a.server.tasks import InMemoryTaskStore   # CORRECT (brief matches)
#
# 9. A2ACardResolver.get_agent_card() is async and takes no base_url constructor arg;
#    pass base_url to the constructor:
#      resolver = A2ACardResolver(http, base_url="http://127.0.0.1:9999")
#      card = await resolver.get_agent_card()
#
# SUMMARY: Working imports and call signatures used in main() below.
"""
import asyncio
import threading
import time

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.helpers.proto_helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
    SendMessageRequest,
)
from a2a.utils.constants import DEFAULT_RPC_URL, PROTOCOL_VERSION_1_0, TransportProtocol


class EchoExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        await event_queue.enqueue_event(new_text_message(f"echo: {text}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def build_app():
    card = AgentCard(
        name="Echo",
        description="echo agent",
        version="0.0.1",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        skills=[AgentSkill(id="echo", name="echo", description="echo text", tags=["demo"])],
        supported_interfaces=[
            AgentInterface(
                protocol_binding=TransportProtocol.JSONRPC,
                url="http://127.0.0.1:9999/",
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=EchoExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = (
        create_agent_card_routes(agent_card=card)
        + create_jsonrpc_routes(request_handler=handler, rpc_url=DEFAULT_RPC_URL)
    )
    return Starlette(routes=routes), card


async def call_it(server_card):
    from a2a.client import A2ACardResolver, ClientConfig, ClientFactory

    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, base_url="http://127.0.0.1:9999").get_agent_card()
        factory = ClientFactory(ClientConfig(streaming=False))
        client = factory.create(card)
        msg = new_text_message("hi", role=Role.ROLE_USER)
        request = SendMessageRequest(message=msg)
        async for stream_response in client.send_message(request):
            print("RESPONSE:", stream_response)


def main():
    app, card = build_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=9999, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(1.5)
    asyncio.run(call_it(card))
    server.should_exit = True


if __name__ == "__main__":
    main()
