"""LiteLLM -> OpenRouter (Cerebras) client returning a parsed ChatResponse."""

from __future__ import annotations

import logging

import litellm
from pydantic import ValidationError

from app import config

from .schema import ChatResponse

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}
TIMEOUT_SECONDS = 60

NOT_CONFIGURED_MESSAGE = "AI assistant is not configured. Set OPENROUTER_API_KEY in .env."


class LLMNotConfigured(Exception):  # noqa: N818 - name fixed by TEAM_CONTRACTS
    """No OPENROUTER_API_KEY and not in mock mode (-> 503)."""

    def __init__(self, message: str = NOT_CONFIGURED_MESSAGE) -> None:
        super().__init__(message)


class LLMCallFailed(Exception):  # noqa: N818 - name fixed by TEAM_CONTRACTS
    """The LLM call errored or returned unparseable output (-> 502)."""


def is_mock_mode() -> bool:
    return config.llm_mock_enabled()


def is_configured() -> bool:
    return config.openrouter_api_key() is not None


def parse_response(content: str | None) -> ChatResponse:
    """Validate the model's JSON text against ChatResponse; raise LLMCallFailed if invalid."""
    if not content or not content.strip():
        raise LLMCallFailed("The AI assistant returned an empty response.")
    try:
        return ChatResponse.model_validate_json(content)
    except ValidationError as exc:
        logger.warning("Unparseable LLM output: %s", exc)
        raise LLMCallFailed("The AI assistant returned an invalid response.") from exc


async def call_llm(messages: list[dict]) -> ChatResponse:
    """Call the model with structured output and return the parsed response."""
    try:
        response = await litellm.acompletion(
            model=MODEL,
            messages=messages,
            response_format=ChatResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
            timeout=TIMEOUT_SECONDS,
        )
        content = response.choices[0].message.content
    except Exception as exc:
        logger.exception("LLM call failed")
        raise LLMCallFailed(f"The AI assistant request failed ({type(exc).__name__}).") from exc
    return parse_response(content)
