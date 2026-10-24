"""User-facing portfolio errors."""


class PortfolioError(Exception):
    """Base class; the message is human-readable and returned as a 400 error."""


class TradeError(PortfolioError):
    """A trade or watchlist request broke a business rule (PLAN §7)."""
