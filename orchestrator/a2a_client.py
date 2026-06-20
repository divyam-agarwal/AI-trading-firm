"""Thin wrapper over the a2a-sdk client.

All client-side SDK imports and version-specific churn are confined here.
Downstream code (the orchestrator graph) imports only ``call_agent``.
"""
import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import new_text_message
from a2a.types import Role, SendMessageRequest

from common.telemetry import inject


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


async def call_agent(base_url: str, text: str) -> str:
    """Resolve the agent card at *base_url*, send *text*, and return the reply.

    W3C trace context is injected into the outgoing message metadata (best-effort)
    so that agent-side spans can join the orchestrator's trace.

    Args:
        base_url: Root URL of the remote A2A agent (e.g. ``"http://host:9111"``).
        text: User message text to send.

    Returns:
        Concatenated text of all reply parts received from the agent.
    """
    async with httpx.AsyncClient(timeout=60) as http:
        # Resolve the agent card from the well-known /.well-known/agent.json endpoint
        card = await A2ACardResolver(http, base_url=base_url).get_agent_card()

        # ClientConfig(streaming=False, httpx_client=http) passes our 60s-timeout client
        # into the SDK's send path (httpx_client is a known ClientConfig field).
        client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

        # Build the outgoing message
        msg = new_text_message(text, role=Role.ROLE_USER)
        request = SendMessageRequest(message=msg)

        # Inject W3C trace context into SendMessageRequest metadata (best-effort).
        # SendMessageRequest is a protobuf message; its `metadata` field is a
        # map<string, string>.  We use try/except so injection never breaks the send.
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
