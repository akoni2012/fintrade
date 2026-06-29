# Market Data — Unified Python Interface

This document describes the unified interface for retrieving stock prices in FinAlly, covering: the abstract contract (`MarketDataSource`), the shared data model (`PriceUpdate`), the price cache (`PriceCache`), the factory that selects an implementation, and the rules all implementations must follow.

The implementation lives in `backend/app/market/`. This document is the design contract; the code is the source of truth for details.

---

## Design Goals

1. **Source-agnostic consumers** — SSE streaming, portfolio valuation, and trade execution all read from `PriceCache`. They never know or care whether prices come from the simulator or the Massive API.
2. **Single write path** — exactly one background task writes to the cache at any time.
3. **Dynamic watchlist** — tickers can be added and removed at runtime without restarting the data source.
4. **Fast startup** — the cache must have at least one price per ticker before the first SSE client connects, so `start()` populates the cache synchronously before returning.

---

## Data Model: `PriceUpdate`

Defined in `backend/app/market/models.py`. An immutable frozen dataclass carrying one ticker's price at a point in time.

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float                  # Latest price, rounded to 2 dp
    previous_price: float         # Price at the prior update, rounded to 2 dp
    timestamp: float              # Unix seconds (float)
    session_open: float | None    # Per-ticker daily baseline; set once on first update

    # Computed properties (not stored):
    @property
    def change(self) -> float: ...          # price - previous_price, 4 dp
    @property
    def change_percent(self) -> float: ...  # per-tick %, 4 dp
    @property
    def direction(self) -> str: ...         # "up" | "down" | "flat"
    @property
    def day_change(self) -> float: ...      # price - session_open, 4 dp
    @property
    def day_change_percent(self) -> float: ...  # day_change / session_open * 100, 4 dp

    def to_dict(self) -> dict: ...          # JSON-serializable dict for SSE
```

### SSE Payload (output of `to_dict()`)

```json
{
  "ticker": "AAPL",
  "price": 190.42,
  "previous_price": 190.18,
  "timestamp": 1754059930.5,
  "change": 0.24,
  "change_percent": 0.1262,
  "direction": "up",
  "session_open": 189.50,
  "day_change": 0.92,
  "day_change_percent": 0.4855
}
```

**Consumer guide:**
- Watchlist "change %" column → `day_change_percent` (stable session baseline)
- Price flash animation (uptick/downtick) → `change` / `direction` (per-tick)
- Portfolio P&L → `price` (latest)

---

## Price Cache: `PriceCache`

Defined in `backend/app/market/cache.py`. The single shared store between producers (data sources) and consumers (SSE, portfolio, trades).

```python
class PriceCache:
    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        session_open: float | None = None,   # supply once on first update
    ) -> PriceUpdate: ...

    def get(self, ticker: str) -> PriceUpdate | None: ...
    def get_price(self, ticker: str) -> float | None: ...
    def get_all(self) -> dict[str, PriceUpdate]: ...
    def remove(self, ticker: str) -> None: ...

    @property
    def version(self) -> int: ...   # monotonic counter; bumped on every update
```

### Session-open semantics

`PriceCache.update()` preserves `session_open` across updates:
- **First update for a ticker:** uses `session_open` argument if provided, otherwise uses the first `price` as the baseline.
- **Subsequent updates:** carries the existing baseline forward — the argument is ignored.

This means the data source is responsible for supplying `session_open` exactly once per ticker (on the first `update()` call). The simulator uses the seed price; Massive uses `day.o` from the snapshot (falling back to `prevDay.c`).

---

## Abstract Interface: `MarketDataSource`

Defined in `backend/app/market/interface.py`.

```python
class MarketDataSource(ABC):

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates. Seeds the cache before returning."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Safe to call multiple times."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. Seeds the cache immediately."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker. Also removes it from the cache."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of tracked tickers."""
```

### Rules all implementations must follow

1. **Tickers are always normalised to uppercase before storage** — `ticker.upper().strip()` at the point of entry.
2. **`start()` populates the cache synchronously** — the first price for each ticker must be in the cache before `start()` returns. Downstream code may read from the cache immediately after `start()`.
3. **`add_ticker()` is idempotent** — adding a ticker already in the active set is a no-op.
4. **`remove_ticker()` calls `cache.remove(ticker)`** — it is the implementation's responsibility to evict the ticker from the cache, not the caller's.
5. **All exceptions in the background poll/step loop are caught and logged** — the loop must not crash on transient errors (network, rate-limits, bad data). Log at `ERROR` level and continue.

---

## Factory: `create_market_data_source()`

Defined in `backend/app/market/factory.py`. Called once at application startup.

```python
def create_market_data_source(cache: PriceCache) -> MarketDataSource:
    """Return MassiveDataSource if MASSIVE_API_KEY is set, else SimulatorDataSource."""
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveDataSource(api_key=api_key, price_cache=cache)
    return SimulatorDataSource(price_cache=cache)
```

---

## Lifecycle (FastAPI integration)

The source and cache are created once in the FastAPI lifespan event and stored on `app.state` so all route handlers can access them.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(DEFAULT_TICKERS)   # Cache has prices after this returns

    app.state.price_cache = cache
    app.state.market_source = source

    yield   # App is running

    await source.stop()

app = FastAPI(lifespan=lifespan)
```

---

## Watchlist Route Integration

When a user adds or removes a ticker via `POST /api/watchlist` or `DELETE /api/watchlist/{ticker}`, the route handler must inform the running data source **in addition to** updating the database.

```python
# POST /api/watchlist
async def add_watchlist_ticker(ticker: str, request: Request):
    ticker = ticker.upper().strip()
    # 1. Write to DB
    db_add_watchlist_ticker(ticker)
    # 2. Notify the running data source (adds to cache immediately)
    await request.app.state.market_source.add_ticker(ticker)
    return {"ticker": ticker}

# DELETE /api/watchlist/{ticker}
async def remove_watchlist_ticker(ticker: str, request: Request):
    ticker = ticker.upper().strip()
    # 1. Remove from DB
    db_remove_watchlist_ticker(ticker)
    # 2. Evict from source + cache
    await request.app.state.market_source.remove_ticker(ticker)
    return {"ticker": ticker}
```

Forgetting step 2 is a common bug: the DB is updated but the price stream continues (or stops) without the data source knowing.

---

## Cold-Start Contract

Before the first tick arrives (or for the simulator, before `start()` returns), the cache is empty or partially populated. Consumers must handle `None` from `cache.get()`:

```python
update = cache.get("AAPL")
if update is None:
    # Not yet available — return null/loading state to frontend
    return {"price": None, "direction": None}
```

The frontend should show a loading/dash state for prices that are `null` rather than rendering `NaN` or crashing.

---

## Module Summary

```
backend/app/market/
├── models.py          PriceUpdate dataclass + to_dict()
├── cache.py           PriceCache (thread-safe, version counter)
├── interface.py       MarketDataSource ABC
├── factory.py         create_market_data_source() factory
├── simulator.py       GBMSimulator + SimulatorDataSource
├── massive_client.py  MassiveDataSource (Polygon.io REST poller)
├── seed_prices.py     Seed prices, GBM params, correlation groups
├── stream.py          create_stream_router() → FastAPI SSE endpoint
└── __init__.py        Public re-exports
```

Public API (re-exported from `__init__.py`):

```python
from app.market import (
    PriceUpdate,
    PriceCache,
    MarketDataSource,
    create_market_data_source,
    create_stream_router,
)
```
