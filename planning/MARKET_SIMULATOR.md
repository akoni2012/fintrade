# Market Simulator — Approach and Code Structure

The simulator generates realistic-looking stock prices without any external API. It is the default data source when `MASSIVE_API_KEY` is not set, and is used in all tests and local development.

Implementation: `backend/app/market/simulator.py` and `backend/app/market/seed_prices.py`.

---

## Why GBM?

Geometric Brownian Motion is the standard model underlying Black-Scholes option pricing. It has two useful properties for a demo:

1. **Prices stay positive** — because each step is multiplicative (`S * exp(...)`) rather than additive, the price can never go negative.
2. **Returns are normally distributed** — the log-returns accumulate into realistic-looking random walks with volatility that scales naturally over time.

For a trading terminal demo we want prices that look plausible: gradual drift, occasional spikes, and sector-correlated moves that make the heatmap interesting. GBM with correlated noise and random shock events delivers this with ~100 lines of code.

---

## Math

Each tick advances every ticker by one time step `dt`:

```
S(t + dt) = S(t) × exp((μ - σ²/2) × dt + σ × √dt × Z)
```

Where:
- `S(t)` — current price
- `μ` (mu) — annualized drift (expected return). Positive = upward bias over time.
- `σ` (sigma) — annualized volatility. Higher = more erratic price movement.
- `dt` — time step as a fraction of a trading year
- `Z` — standard normal random variable (correlated across tickers — see below)

### Time step

```python
TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800 seconds
DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR   # ~8.48e-8
```

At 500ms ticks, `dt` is tiny, so per-tick moves are sub-cent. This is realistic: a 25% annualized volatility on a $190 stock produces ~$0.003 per 500ms tick on average. Prices accumulate a visible trend over minutes and hours.

---

## Correlated Moves (Cholesky Decomposition)

Real stocks in the same sector move together. AAPL and MSFT often rise and fall on the same day. The simulator replicates this using a **correlation matrix** and **Cholesky decomposition**.

### Correlation structure

```
Tech stocks (AAPL, GOOGL, MSFT, AMZN, META, NVDA, NFLX): intra-group ρ = 0.6
Finance stocks (JPM, V):                                    intra-group ρ = 0.5
TSLA with anything:                                         ρ = 0.3  (does its own thing)
Cross-sector (tech ↔ finance, unknown tickers):             ρ = 0.3
```

### How Cholesky is applied

1. Build an `n × n` correlation matrix `Σ` from pairwise correlations.
2. Compute the Cholesky factor `L` such that `L @ L.T = Σ`.
3. On each tick, draw `n` independent standard normals `z_ind`.
4. Compute `z_corr = L @ z_ind` — this gives `n` correlated normals.
5. Use `z_corr[i]` as the `Z` in the GBM formula for ticker `i`.

```python
z_independent = np.random.standard_normal(n)
z_correlated = self._cholesky @ z_independent
# Now z_correlated[i] and z_correlated[j] have correlation ρ_ij
```

When tickers are added or removed, the Cholesky matrix is rebuilt. This is O(n²) but n is always small (< 50 tickers).

---

## Random Shock Events

To make the terminal visually interesting, the simulator fires occasional large moves:

```python
# ~0.1% chance per tick per ticker
if random.random() < 0.001:
    shock_magnitude = random.uniform(0.02, 0.05)   # 2–5% move
    shock_sign = random.choice([-1, 1])
    self._prices[ticker] *= 1 + shock_magnitude * shock_sign
```

With 10 tickers at 2 ticks/sec, this produces an event roughly **every 50 seconds** — enough to keep the heatmap and flash animations active without being overwhelming.

---

## Seed Prices and Parameters

Defined in `backend/app/market/seed_prices.py`. These are the starting prices and per-ticker GBM parameters used when the simulator boots.

```python
SEED_PRICES = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
}

TICKER_PARAMS = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # high vol
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # high vol + strong drift
    "JPM":  {"sigma": 0.18, "mu": 0.04},  # low vol (bank)
    "V":    {"sigma": 0.17, "mu": 0.04},  # low vol (payments)
    # ... etc
}

DEFAULT_PARAMS = {"sigma": 0.25, "mu": 0.05}
```

**For unknown tickers** (dynamically added via the watchlist), the simulator uses `DEFAULT_PARAMS` and a random seed price between $50 and $300. This is intentional — unknown tickers shouldn't crash the simulator.

---

## Code Structure

### `GBMSimulator` (pure math, no I/O)

Owns the price state and the step computation. No asyncio, no cache, no FastAPI — it is a pure in-memory computation engine.

```python
class GBMSimulator:
    def __init__(self, tickers: list[str], dt: float, event_probability: float): ...

    def step(self) -> dict[str, float]:
        """Advance all tickers one time step. Returns {ticker: new_price}.
        This is the hot path — called every 500ms. Keep it fast."""

    def add_ticker(self, ticker: str) -> None:
        """Add ticker; rebuilds Cholesky. Idempotent."""

    def remove_ticker(self, ticker: str) -> None:
        """Remove ticker; rebuilds Cholesky."""

    def get_price(self, ticker: str) -> float | None: ...
    def get_tickers(self) -> list[str]: ...
```

### `SimulatorDataSource` (async wrapper, implements `MarketDataSource`)

Owns the asyncio background task and writes to the `PriceCache`. Delegates all price computation to `GBMSimulator`.

```python
class SimulatorDataSource(MarketDataSource):
    def __init__(self, price_cache: PriceCache, update_interval: float = 0.5): ...

    async def start(self, tickers: list[str]) -> None:
        # 1. Create GBMSimulator with initial tickers
        # 2. Seed the cache with starting prices (so cache is populated before returning)
        # 3. Start background asyncio task (_run_loop)

    async def stop(self) -> None:
        # Cancel and await the background task

    async def add_ticker(self, ticker: str) -> None:
        # Delegate to GBMSimulator.add_ticker()
        # Immediately seed cache with the new ticker's starting price

    async def remove_ticker(self, ticker: str) -> None:
        # Delegate to GBMSimulator.remove_ticker()
        # Also remove from cache

    async def _run_loop(self) -> None:
        # Loop: step simulator → write prices to cache → sleep(interval)
```

### Separation of concerns

```
GBMSimulator          SimulatorDataSource
─────────────         ───────────────────
Owns prices dict      Owns asyncio task
Computes moves        Owns PriceCache reference
Pure Python/numpy     Bridges GBM → PriceCache
No I/O                Implements MarketDataSource ABC
```

This separation makes `GBMSimulator` independently testable (no event loop needed) while keeping `SimulatorDataSource` thin.

---

## Session-Open Baseline

The simulator sets `session_open` once per ticker — it is the seed price at the time the ticker starts being simulated:

- **Startup tickers:** seed price from `SEED_PRICES` (or the randomly chosen price for unknown tickers).
- **Dynamically added tickers:** whatever price `GBMSimulator._add_ticker_internal()` assigns, which is immediately written to the cache via `cache.update(ticker, price)` — the first `update()` call with no prior cache entry causes `PriceCache` to use that price as `session_open`.

This gives a stable daily-change baseline that persists for the lifetime of the running container, which is consistent with how `MARKET_INTERFACE.md` specifies the contract.

---

## Background Task Loop

```python
async def _run_loop(self) -> None:
    while True:
        try:
            if self._sim:
                prices = self._sim.step()          # dict[str, float]
                for ticker, price in prices.items():
                    self._cache.update(ticker=ticker, price=price)
        except Exception:
            logger.exception("Simulator step failed")  # Never crash the loop
        await asyncio.sleep(self._interval)        # 500ms by default
```

Key points:
- Exceptions are caught and logged — a NumPy error or dict mutation during iteration won't kill the loop.
- `asyncio.sleep` yields control back to the event loop so SSE connections and HTTP handlers aren't starved.
- The cache's `version` counter is incremented on every `update()` call, which the SSE endpoint uses to detect changes and push only when there's new data.

---

## Test Coverage

Six test modules cover the simulator:

| Module | What it tests |
|--------|---------------|
| `test_simulator.py` | GBM math, step correctness, Cholesky rebuild on add/remove, shock events |
| `test_simulator_source.py` | Async lifecycle (start/stop/add/remove), cache seeding |
| `test_models.py` | `PriceUpdate` fields, computed properties, `to_dict()` |
| `test_cache.py` | Thread-safety, version counter, session_open preservation |
| `test_factory.py` | Correct source selected based on env var |

Run with:

```bash
cd backend
uv run --extra dev pytest tests/market/ -v
```

---

## Extending the Simulator

### Adding a new default ticker

1. Add the seed price to `SEED_PRICES` in `seed_prices.py`.
2. Add per-ticker params to `TICKER_PARAMS` (or let it fall back to `DEFAULT_PARAMS`).
3. Assign it to a correlation group in `CORRELATION_GROUPS` if applicable.
4. Add it to the default watchlist seed data in the database schema.

### Changing update frequency

Pass a different `update_interval` to `SimulatorDataSource`:

```python
# Slower (1 tick/sec) — lighter on CPU
SimulatorDataSource(price_cache=cache, update_interval=1.0)

# Faster (250ms) — more animated UI
SimulatorDataSource(price_cache=cache, update_interval=0.25)
```

### Adjusting shock frequency or magnitude

```python
SimulatorDataSource(
    price_cache=cache,
    event_probability=0.005,  # 5x more frequent shocks
)
```

The `event_probability` is passed through to `GBMSimulator.__init__`.
