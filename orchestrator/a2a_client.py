"""Thin wrapper over the a2a-sdk client.

All client-side SDK imports and version-specific churn are confined here.
Downstream code (the orchestrator graph) imports only ``call_agent``.
"""
import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import Role, SendMessageRequest
from opentelemetry.trace import Status, StatusCode

from common.telemetry import inject, tracer


def _text_of(obj) -> str:
    """Best-effort extraction of concatenated text parts from an a2a response.

    The a2a-sdk's send_message async-generator yields protobuf Message objects
    whose repr looks like:
        message { role: ROLE_AGENT parts { text: "hello" } }

    We defensively walk several possible shapes:
      - obj.parts[].text          (obj IS the Message)
      - obj.message.parts[].text  (obj wraps the Message)
      - with a possible .root shim on each Part
    """
    parts = getattr(obj, "parts", None)
    if parts is None:
        msg = getattr(obj, "message", None)
        parts = getattr(msg, "parts", None) if msg is not None else None
    out = []
    for p in parts or []:
        # Some SDK versions wrap Part in a OneOf with a .root attribute
        root = getattr(p, "root", p)
        t = getattr(root, "text", None)
        if t:
            out.append(t)
    return "".join(out)


async def call_agent(base_url: str, text: str, *, agent_name: str | None = None) -> str:
    """Resolve the agent card at *base_url*, send *text*, and return the reply.

    Wrapped in an "a2a SendMessage" client span; W3C trace context is injected
    into the outgoing message metadata (best-effort) inside that span, so the
    agent-side spans join the orchestrator's trace.

    Args:
        base_url: Root URL of the remote A2A agent (e.g. ``"http://host:9111"``).
        text: User message text to send.
        agent_name: Optional logical agent name, recorded as the ``agent.name``
            span attribute.

    Returns:
        Concatenated text of all reply parts received from the agent.
    """
    with tracer(__name__).start_as_current_span("a2a SendMessage") as span:
        span.set_attribute("server.url", base_url)
        span.set_attribute("a2a.method", "SendMessage")
        if agent_name:
            span.set_attribute("agent.name", agent_name)
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                # Resolve the agent card from the well-known endpoint
                card = await A2ACardResolver(http, base_url=base_url).get_agent_card()

                # ClientConfig(streaming=False, httpx_client=http) passes our 60s-timeout client
                client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

                # Build the outgoing message
                msg = new_text_message(text, role=Role.ROLE_USER)
                request = SendMessageRequest(message=msg)

                # Inject W3C trace context into SendMessageRequest metadata (best-effort).
                # inject runs inside the client span, so traceparent encodes this span.
                try:
                    carrier: dict[str, str] = inject({})
                    if carrier:
                        request.metadata.update(carrier)
                except Exception:
                    pass

                chunks: list[str] = []
                async for stream_response in client.send_message(request):
                    chunks.append(_text_of(stream_response))

                return "".join(c for c in chunks if c)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
