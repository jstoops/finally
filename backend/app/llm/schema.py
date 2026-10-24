"""Structured output schema the LLM must answer with (PLAN §9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TradeRequest(BaseModel):
    """A trade the LLM wants to auto-execute."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    side: Literal["buy", "sell"]
    quantity: float


class WatchlistChange(BaseModel):
    """A watchlist add/remove the LLM wants to apply."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    action: Literal["add", "remove"]


class ChatResponse(BaseModel):
    """The complete structured response: message plus optional actions."""

    model_config = ConfigDict(extra="forbid")

    message: str
    trades: list[TradeRequest] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)
