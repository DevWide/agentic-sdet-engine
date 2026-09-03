"""Token and cost accounting for LLM calls.

Prices are USD per 1M tokens and are hardcoded on purpose: the OpenAI API does not
return pricing, so any cost figure is an estimate against this table. Update it when
prices move — a stale table silently produces wrong numbers, which is worse than none.
Last checked: 2026-09.
"""

from typing import Optional

from langchain_core.messages import AIMessage

PRICE_PER_1M_TOKENS = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}


class Usage:
    """Token counts and estimated cost for one or more LLM calls."""

    __slots__ = ("input_tokens", "output_tokens", "cost_usd", "priced")

    def __init__(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        priced: bool = True,
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost_usd = cost_usd
        # False when the model was absent from the price table, so callers can say
        # "cost unknown" instead of reporting a confident $0.00.
        self.priced = priced

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cost_usd + other.cost_usd,
            self.priced and other.priced,
        )

    def __repr__(self) -> str:
        return f"Usage(in={self.input_tokens}, out={self.output_tokens}, ${self.cost_usd:.6f})"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]:
    """Return (cost_usd, priced). `priced` is False for models absent from the table."""
    prices = PRICE_PER_1M_TOKENS.get(model)
    if prices is None:
        # Try the base name, so "gpt-4o-mini-2024-07-18" still prices as "gpt-4o-mini".
        for known, known_prices in PRICE_PER_1M_TOKENS.items():
            if model.startswith(known):
                prices = known_prices
                break
    if prices is None:
        return 0.0, False

    input_price, output_price = prices
    cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return cost, True


def usage_from_message(message: Optional[AIMessage], model: str) -> Usage:
    """Extract token usage from a raw LangChain response, tolerating providers that omit it."""
    metadata = getattr(message, "usage_metadata", None) or {}
    input_tokens = int(metadata.get("input_tokens", 0))
    output_tokens = int(metadata.get("output_tokens", 0))
    cost, priced = estimate_cost(model, input_tokens, output_tokens)
    return Usage(input_tokens, output_tokens, cost, priced)


def record_usage_on_span(span, usage: Usage) -> None:
    """Attach usage to an OTel span using the gen_ai.* semantic convention names."""
    span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
    span.set_attribute("sdet.cost_usd", round(usage.cost_usd, 6))
    if not usage.priced:
        span.set_attribute("sdet.cost_estimated", False)
