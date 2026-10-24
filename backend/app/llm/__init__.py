"""LLM chat integration for FinAlly (PLAN §9).

Public API:
    handle_chat         - Run one chat turn; returns the stored assistant message
    LLMNotConfigured    - No OPENROUTER_API_KEY and not in mock mode (-> 503)
    LLMCallFailed       - LLM error or unparseable output (-> 502)
    ChatResponse        - Structured output schema
"""

from .chat import handle_chat
from .client import NOT_CONFIGURED_MESSAGE, LLMCallFailed, LLMNotConfigured
from .schema import ChatResponse, TradeRequest, WatchlistChange

__all__ = [
    "handle_chat",
    "LLMNotConfigured",
    "LLMCallFailed",
    "NOT_CONFIGURED_MESSAGE",
    "ChatResponse",
    "TradeRequest",
    "WatchlistChange",
]
