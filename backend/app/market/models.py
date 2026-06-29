"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # Per-ticker baseline for daily change, set once when the ticker starts
    # streaming. Defaults to the first price if not supplied. The PriceCache is
    # responsible for carrying this value forward across subsequent updates.
    session_open: float | None = None

    def __post_init__(self) -> None:
        # Default the daily baseline to the first observed price. object.__setattr__
        # is required because the dataclass is frozen.
        if self.session_open is None:
            object.__setattr__(self, "session_open", self.price)

    @property
    def change(self) -> float:
        """Absolute price change from previous update (per-tick)."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update (per-tick)."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat' (per-tick)."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float:
        """Absolute price change from the session-open baseline."""
        base = self.session_open if self.session_open is not None else self.price
        return round(self.price - base, 4)

    @property
    def day_change_percent(self) -> float:
        """Percentage change from the session-open baseline."""
        base = self.session_open if self.session_open is not None else self.price
        if base == 0:
            return 0.0
        return round((self.price - base) / base * 100, 4)

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "session_open": self.session_open,
            "day_change": self.day_change,
            "day_change_percent": self.day_change_percent,
        }
