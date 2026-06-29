# Market Data Backend — Design Document

**Status:** Reflects the implementation in `backend/app/market/` as built. This document supersedes `MARKET_INTERFACE.md`, `MARKET_SIMULATOR.md`, and `MASSIVE_API.md` as the single design reference for the market data subsystem — those documents remain for historical/deep-dive detail but this is the canonical contract, reconciled with `REVIEW.md` and `CODEX_REVIEW.md` findings.

This document covers, in order:

1. Architecture overview
2. The shared data model (`PriceUpdate`)
3. The price cache (`PriceCache`)
4. The abstract interface (`MarketDataSource`)
5. The simulator (`GBMSimulator` + `SimulatorDataSource`)
6. The Massive (Polygon.io) client (`MassiveDataSource`)
7. The factory (`create_market_data_source`)
8. SSE streaming (`create_stream_router`)
9. FastAPI lifecycle integration
10. Watchlist route integration contract
11. Known gaps and the fixes this design adopts

---

## 1. Architecture Overview

```
                     ┌────────────────────────┐
                     │   MarketDataSource     │   (ABC)
                     │  start/stop/add/remove │
                     └───────────┬────────────┘
                  ┌──────────────┴───────────────┐
                  ▼                               ▼
      ┌───────────────────────┐       ┌─────────────────────────┐
      │  SimulatorDataSource  │       │   MassiveDataSource     │
      │  (GBM, default)       │       │   (Polygon.io REST poll)│
      └───────────┬───────────┘       └────────────┬────────────┘
                  │                                 │
                  └───────────────┬─────────────────┘
                                  ▼
                         ┌──────────────────┐
                         │    PriceCache    │  (thread-safe, versioned)
                         └────────┬─────────┘
                  ┌───────────────┼────────────────────┐
                  ▼               ▼                    ▼
        SSE stream endpoint  Portfolio valuation  Trade execution
        (/api/stream/prices)  (GET /api/portfolio) (POST /api/portfolio/trade)
```

**Strategy pattern.** `SimulatorDataSource` and `MassiveDataSource` both implement `MarketDataSource`. Selection happens once, in `create_market_data_source()`, based on `MASSIVE_API_KEY`. No downstream code (SSE, portfolio, trades) ever imports either concrete class — only `PriceCache` and the abstract type.

**Single writer, many readers.** Exactly one background task (simulator loop or Massive poller) writes to `PriceCache` at a time. All other code reads. This avoids locking complexity beyond the cache's own internal mutex.

**Push, not pull, downstream.** The cache doesn't push to consumers — consumers (SSE generator) poll the cache's cheap `version` counter on their own loop and pull a snapshot only when it changes. This decouples the data source's tick rate from the SSE push rate.

---

## 2. Data Model: `PriceUpdate`

File: `backend/app/market/models.py`

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float                         # rounded to 2 dp by PriceCache
    previous_price: float                # rounded to 2 dp by PriceCache
    timestamp: float = field(default_factory=time.time)   # Unix seconds
    session_open: float | None = None    # set once; carried forward by PriceCache

    def __post_init__(self) -> None:
        if self.session_open is None:
            object.__setattr__(self, "session_open", self.price)

    @property
    def change(self) -> float:
        """Per-tick absolute change (price - previous_price), 4 dp."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Per-tick percent change, 4 dp. 0.0 if previous_price is 0."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up' | 'down' | 'flat', derived from per-tick change."""
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float:
        """Absolute change from the session-open baseline, 4 dp."""
        return round(self.price - self.session_open, 4)

    @property
    def day_change_percent(self) -> float:
        """Percent change from the session-open baseline, 4 dp. 0.0 if baseline is 0."""
        if self.session_open == 0:
            return 0.0
        return round((self.price - self.session_open) / self.session_open * 100, 4)

    def to_dict(self) -> dict:
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
```

`session_open` is typed `float | None` for constructor flexibility, but after `__post_init__` it is always a `float` — callers reading `update.session_open` from a cached value never see `None`.

### Field usage for consumers

| Field | Use for |
|---|---|
| `price` | Latest price; portfolio valuation, P&L |
| `change` / `direction` | Per-tick flash animation (green/red highlight) |
| `day_change_percent` | Watchlist "today" column — stable across reloads |
| `session_open` | Display "open" reference if needed |
| `timestamp` | Unix seconds (float) — **not** an ISO string |

---

## 3. Price Cache: `PriceCache`

File: `backend/app/market/cache.py`

```python
from threading import Lock
import time
from .models import PriceUpdate


class PriceCache:
    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        session_open: float | None = None,
    ) -> PriceUpdate:
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            if prev is not None:
                baseline = prev.session_open          # carried forward, argument ignored
            elif session_open is not None:
                baseline = round(session_open, 2)      # first update: caller-supplied baseline
            else:
                baseline = round(price, 2)             # first update: price becomes baseline

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
                session_open=baseline,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        with self._lock:           # see Section 11, gap L1
            return self._version
```

### Session-open contract

- **First `update()` call for a ticker:** uses the `session_open` argument if supplied (e.g. Massive's day-open), else the first `price` becomes the baseline.
- **Every subsequent call:** the existing baseline is carried forward — the `session_open` argument is silently ignored. A data source only needs to pass `session_open` once, on the first write for a ticker; passing it again later has no effect.

This is what gives the watchlist's daily-change column a value that's stable across page reloads (vs. the per-tick `change`, which resets every tick) — see `PLAN.md` Section 6, "Daily Change Baseline."

---

## 4. Abstract Interface: `MarketDataSource`

File: `backend/app/market/interface.py`

```python
from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Seed the cache and begin a background update task. Call once."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task. Safe to call multiple times / before start()."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set; no-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and the cache; no-op if absent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Currently tracked tickers."""
```

### Rules every implementation must follow

1. **Normalize tickers at the boundary** — `ticker.upper().strip()` on every `add_ticker`/`remove_ticker` call, in *both* implementations (see Section 11, gap M2 — the simulator does not currently do this and must be fixed to match `MassiveDataSource`).
2. **`start()` populates the cache synchronously.** The first price for every requested ticker must be in `PriceCache` before `start()` returns, so a caller can read immediately after `await source.start(tickers)`.
3. **`add_ticker()` is idempotent.** Adding an already-tracked ticker does nothing.
4. **`remove_ticker()` owns cache eviction.** The implementation calls `cache.remove(ticker)` itself — callers never call `cache.remove()` directly.
5. **Background loops never propagate exceptions.** Catch broadly, log at `ERROR`/`exception`, and continue to the next tick/poll.

---

## 5. Simulator: `GBMSimulator` + `SimulatorDataSource`

File: `backend/app/market/simulator.py`, params in `backend/app/market/seed_prices.py`.

### Math

```
S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)
```

- `mu` — annualized drift, `sigma` — annualized volatility, `dt` — time step as a fraction of a trading year, `Z` — correlated standard normal.
- `dt` for a 500ms tick: `0.5 / (252 * 6.5 * 3600) ≈ 8.48e-8` — sub-cent per-tick moves that accumulate into a visible trend over minutes.
- Multiplicative update keeps prices strictly positive.

### Correlated moves (Cholesky)

```python
corr = np.eye(n)
for i in range(n):
    for j in range(i + 1, n):
        rho = pairwise_correlation(tickers[i], tickers[j])
        corr[i, j] = corr[j, i] = rho
cholesky = np.linalg.cholesky(corr)

# each tick:
z_independent = np.random.standard_normal(n)
z_correlated = cholesky @ z_independent   # z_correlated[i] correlates with z_correlated[j] at rho_ij
```

Correlation rules (`seed_prices.py`):

| Pair | ρ |
|---|---|
| Tech ↔ tech (`AAPL,GOOGL,MSFT,AMZN,META,NVDA,NFLX`) | 0.6 |
| Finance ↔ finance (`JPM,V`) | 0.5 |
| `TSLA` ↔ anything | 0.3 |
| Cross-sector / unknown tickers | 0.3 |

Cholesky is rebuilt on every `add_ticker`/`remove_ticker` — O(n²), cheap for n < 50.

### Random shock events

```python
if random.random() < event_probability:   # default 0.001 (~0.1%/tick/ticker)
    magnitude = random.uniform(0.02, 0.05)
    sign = random.choice([-1, 1])
    prices[ticker] *= 1 + magnitude * sign
```

At 10 tickers / 2 ticks/sec this produces a shock roughly every 50 seconds — enough to animate the heatmap without constant noise.

### Seed prices and per-ticker params

```python
SEED_PRICES = {"AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00, "AMZN": 185.00,
                "TSLA": 250.00, "NVDA": 800.00, "META": 500.00, "JPM": 195.00,
                "V": 280.00, "NFLX": 600.00}

TICKER_PARAMS = {
    "TSLA": {"sigma": 0.50, "mu": 0.03},   # high vol
    "NVDA": {"sigma": 0.40, "mu": 0.08},   # high vol + strong drift
    "JPM":  {"sigma": 0.18, "mu": 0.04},   # low vol
    "V":    {"sigma": 0.17, "mu": 0.04},   # low vol
    # ... full table per ticker
}
DEFAULT_PARAMS = {"sigma": 0.25, "mu": 0.05}   # fallback for unknown tickers
```

**Unknown tickers** (added dynamically, e.g. via watchlist or LLM) get `DEFAULT_PARAMS` and a random seed price `uniform(50, 300)` — by design, so an arbitrary ticker symbol never crashes the simulator.

### `GBMSimulator` (pure compute, no I/O)

```python
class GBMSimulator:
    def __init__(self, tickers: list[str], dt: float = DEFAULT_DT,
                 event_probability: float = 0.001) -> None: ...

    def step(self) -> dict[str, float]:
        """Advance all tickers one tick. Hot path — called every 500ms."""

    def add_ticker(self, ticker: str) -> None: ...     # rebuilds Cholesky, idempotent
    def remove_ticker(self, ticker: str) -> None: ...  # rebuilds Cholesky
    def get_price(self, ticker: str) -> float | None: ...
    def get_tickers(self) -> list[str]: ...
```

### `SimulatorDataSource` (asyncio wrapper)

```python
class SimulatorDataSource(MarketDataSource):
    def __init__(self, price_cache: PriceCache, update_interval: float = 0.5,
                 event_probability: float = 0.001) -> None: ...

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers, event_probability=self._event_prob)
        for ticker in tickers:                      # seed cache before returning
            self._cache.update(ticker=ticker, price=self._sim.get_price(ticker))
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()              # NORMALIZE (fix for gap M2)
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    for ticker, price in self._sim.step().items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")     # never crash the loop
            await asyncio.sleep(self._interval)
```

**`GBMSimulator` does the math; `SimulatorDataSource` does the asyncio/cache plumbing.** This split keeps `GBMSimulator` testable with no event loop.

### Tuning knobs

```python
SimulatorDataSource(price_cache=cache, update_interval=0.25)        # faster ticks
SimulatorDataSource(price_cache=cache, event_probability=0.005)     # more frequent shocks
```

---

## 6. Massive (Polygon.io) Client: `MassiveDataSource`

File: `backend/app/market/massive_client.py`. Used when `MASSIVE_API_KEY` is set.

### Endpoint used

```
GET https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,...&apiKey=...
```

One call covers all watched tickers. Response includes `lastTrade.p` (price), `lastTrade.t` (Unix **nanoseconds**), `day.o` (today's open — preferred `session_open` source), `prevDay.c` (fallback baseline).

### Poll cadence

| Tier | Rate limit | Poll interval |
|---|---|---|
| Free/Starter | 5 req/min | 15s (default) |
| Advanced | higher | 5–15s |
| Business | highest | 2–5s |

### Implementation

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType


class MassiveDataSource(MarketDataSource):
    def __init__(self, api_key: str, price_cache: PriceCache,
                 poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = [t.upper().strip() for t in tickers]
        await self._poll_once()                      # immediate first poll → cache populated
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._client = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            # picked up on the next poll cycle — there is no synchronous
            # "seed immediately" path for Massive (unlike the simulator),
            # since a single-ticker fetch costs a separate rate-limited call

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers or not self._client:
            return
        try:
            # RESTClient is synchronous — offload to a thread so the
            # event loop isn't blocked during the HTTP round-trip.
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    timestamp = snap.last_trade.timestamp / 1_000_000_000.0  # ns → s (fix, see Sec. 11 gap)
                    day_open = getattr(snap.day, "open", None) if snap.day else None
                    prev_close = getattr(snap.prev_day, "close", None) if snap.prev_day else None
                    session_open = day_open or prev_close or price            # fix, see Sec. 11 gap M4

                    self._cache.update(
                        ticker=snap.ticker,
                        price=price,
                        timestamp=timestamp,
                        session_open=session_open,
                    )
                except (AttributeError, TypeError) as e:
                    logger.warning("Skipping snapshot for %s: %s",
                                    getattr(snap, "ticker", "???"), e)
        except Exception as e:
            logger.error("Massive poll failed: %s", e)   # never re-raise; retry next interval

    def _fetch_snapshots(self) -> list:
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

### Error handling

| Status / case | Action |
|---|---|
| 401 | Bad/missing key — log; poller keeps retrying (operator must fix the key and restart) |
| 403 | Endpoint not in plan — log |
| 429 | Rate limit — log; next interval naturally backs off |
| 200, empty `tickers` | Market closed or symbols unknown — previous cached prices remain (cache is not cleared on an empty response) |

### Raw HTTP alternative (no SDK)

```python
import httpx

resp = httpx.get(
    "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
    params={"tickers": ",".join(tickers), "apiKey": API_KEY},
    timeout=10.0,
)
resp.raise_for_status()
for item in resp.json().get("tickers", []):
    price = item["lastTrade"]["p"]
    ts_sec = item["lastTrade"]["t"] / 1_000_000_000.0
    session_open = item.get("day", {}).get("o") or item.get("prevDay", {}).get("c") or price
```

---

## 7. Factory: `create_market_data_source()`

File: `backend/app/market/factory.py`

```python
import os
from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    return SimulatorDataSource(price_cache=price_cache)
```

Returns an **unstarted** source — the caller must `await source.start(tickers)`.

---

## 8. SSE Streaming: `create_stream_router()`

File: `backend/app/market/stream.py`

**Payload shape is batched, not single-ticker.** This is the actual implemented contract (and what `PLAN.md` Section 6 should be read alongside, per `REVIEW.md` H1 / `CODEX_REVIEW.md` H1):

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.50, ...}, "GOOGL": {...}, ...}

```

```python
def create_stream_router(price_cache: PriceCache) -> APIRouter:
    router = APIRouter(prefix="/api/stream", tags=["streaming"])   # create per call — see Sec. 11 gap M1

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def _generate_events(price_cache: PriceCache, request: Request,
                            interval: float = 0.5):
    yield "retry: 1000\n\n"          # EventSource auto-reconnect after 1s
    last_version = -1
    try:
        while True:
            if await request.is_disconnected():
                break
            current_version = price_cache.version
            if current_version > last_version:                 # `>` not `!=` — see Sec. 11 gap L4
                last_version = current_version
                prices = price_cache.get_all()
                if prices:
                    data = {t: u.to_dict() for t, u in prices.items()}
                    yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
```

### Frontend `EventSource` consumer

```ts
const es = new EventSource("/api/stream/prices");
es.onmessage = (ev) => {
  const updates: Record<string, PriceUpdate> = JSON.parse(ev.data);
  for (const [ticker, update] of Object.entries(updates)) {
    applyPriceUpdate(ticker, update);   // flash animation keyed off update.direction/change
  }
};
```

`EventSource` reconnects automatically on disconnect using the same URL; the `retry: 1000` directive sets the reconnect delay. No `Last-Event-ID` handling is needed since each event is a full snapshot, not an incremental diff.

---

## 9. FastAPI Lifecycle Integration

The cache and source are singletons created once in the lifespan handler and exposed via `app.state`.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.market import PriceCache, create_market_data_source, create_stream_router

DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                   "NVDA", "META", "JPM", "V", "NFLX"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(DEFAULT_TICKERS)     # cache has prices before requests are served

    app.state.price_cache = cache
    app.state.market_source = source

    yield

    await source.stop()


app = FastAPI(lifespan=lifespan)
app.include_router(create_stream_router(app.state.price_cache))
```

In practice, `DEFAULT_TICKERS` should come from `db.get_watchlist()` (the seeded default watchlist on a fresh DB), not a hardcoded list — but the constant above is the fallback if the DB isn't initialized yet at lifespan time.

---

## 10. Watchlist Route Integration Contract

`POST /api/watchlist` and `DELETE /api/watchlist/{ticker}` must touch **both** the DB and the running data source — updating only the DB is a silent bug (the price stream and the watchlist diverge).

```python
async def add_watchlist_ticker(ticker: str, request: Request):
    ticker = ticker.upper().strip()
    db.add_watchlist_ticker(ticker)
    await request.app.state.market_source.add_ticker(ticker)
    return {"ticker": ticker}


async def remove_watchlist_ticker(ticker: str, request: Request):
    ticker = ticker.upper().strip()
    # Do NOT stop streaming a ticker the user still holds a position in —
    # portfolio valuation needs its price even if it leaves the watchlist.
    if db.has_open_position(ticker):
        db.remove_watchlist_ticker(ticker)
        return {"ticker": ticker}   # still streamed; just no longer "watched"

    db.remove_watchlist_ticker(ticker)
    await request.app.state.market_source.remove_ticker(ticker)
    return {"ticker": ticker}
```

This resolves the open item from `REVIEW.md` Medium #3 (watchlist DELETE must check positions before evicting from the data source).

---

## 11. Known Gaps and Fixes Adopted by This Design

These were raised across `REVIEW.md` / `CODEX_REVIEW.md` against the as-built code. This design adopts the fix shown for each — code in Sections 5/6/8 above already reflects them.

| Gap | File | Fix adopted here |
|---|---|---|
| SSE payload documented as single-ticker in `PLAN.md`, but implemented as batched dict-of-dicts | `stream.py` | This document and `PLAN.md` Section 6 treat the **batched** shape as canonical (Section 8 above) |
| `SimulatorDataSource.add_ticker`/`remove_ticker` don't normalize case/whitespace, unlike `MassiveDataSource` | `simulator.py` | Both call `ticker.upper().strip()` (Section 5) |
| `MassiveDataSource` divides `lastTrade.t` by `1000.0` (treats ns as ms) | `massive_client.py` | Divide by `1_000_000_000.0` (Section 6) |
| `MassiveDataSource._poll_once` never passes `session_open`, so day-change baseline defaults to first-polled price instead of the real day open | `massive_client.py` | Derive `session_open = day.o or prevDay.c or price` and pass it into `cache.update()` (Section 6) |
| `create_stream_router` builds `APIRouter` at module scope, breaking test isolation if called twice | `stream.py` | Build the `APIRouter` inside the factory function (Section 8) |
| SSE version check uses `!=` rather than `>` | `stream.py` | Use `>` (Section 8) — guards against any hypothetical version reset |
| `PriceCache.version` property reads `_version` without the lock | `cache.py` | Acquire `self._lock` in the `version` property |
| Watchlist removal could evict a ticker's price feed while a position is still open | (future watchlist route) | Check `db.has_open_position()` before calling `remove_ticker()` (Section 10) |
| No ticker validation at the API boundary — arbitrary strings become GBM paths / cache keys | (future watchlist route) | Validate ticker format (e.g. `^[A-Z]{1,5}$`) before calling `add_ticker()`; reject otherwise |

Items not yet adopted as code changes in `backend/app/market/` should be applied there as part of finishing the watchlist API routes, so the implementation matches this document exactly.
