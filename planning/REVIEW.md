# FinAlly — Comprehensive Codebase Review

**Date:** 2026-06-28
**Reviewer:** Claude Sonnet 4.6
**Scope:** Full repository at `/finally-main`
**Spec reference:** `planning/PLAN.md`, `planning/MARKET_DATA_SUMMARY.md`

---

## Executive Summary

The repository contains a well-implemented market data subsystem (`backend/app/market/`, 8 modules, 73 passing tests, 84% coverage). Everything else specified in PLAN.md — the FastAPI application entry point, all REST API routes, database layer, LLM integration, the entire Next.js frontend, Dockerfile, start/stop scripts, and Playwright E2E tests — is absent. Approximately 85% of the spec is unbuilt.

The market data layer that exists is production-quality. The issues found in it are mostly low severity. The critical concern for the project is the scope of unbuilt components.

---

## 1. Project Completeness

### What is built
- `backend/app/market/` — full market data subsystem: models, cache, interface, simulator, Massive client, factory, SSE streaming
- `backend/tests/market/` — 73 unit and integration tests
- `backend/pyproject.toml` — project configuration and dependencies
- `backend/market_data_demo.py` — Rich terminal demo script
- Planning documents in `planning/`
- Top-level and backend READMEs

### What is missing (per PLAN.md spec)
- `backend/app/main.py` — FastAPI application entry point and lifespan manager
- `backend/app/` API route modules — portfolio (`/api/portfolio`, `/api/portfolio/trade`, `/api/portfolio/history`), watchlist (`/api/watchlist`), chat (`/api/chat`), health (`/api/health`)
- `backend/app/` database layer — schema SQL, lazy initialization, seed data logic, SQLite connection management
- `backend/app/` LLM integration — LiteLLM/OpenRouter/Cerebras client, structured output parsing, mock mode
- `frontend/` — entire Next.js TypeScript application
- `Dockerfile` — multi-stage build
- `docker-compose.yml`
- `scripts/start_mac.sh`, `scripts/stop_mac.sh`, `scripts/start_windows.ps1`, `scripts/stop_windows.ps1`
- `test/` — Playwright E2E tests and `docker-compose.test.yml`
- `.env.example` — referenced in `README.md:31` (`cp .env.example .env`) but not present
- `db/.gitkeep` — directory marker specified in PLAN.md Section 4

---

## 2. Findings by Severity

### Critical

No critical bugs found in the implemented code.

---

### High

**H1 — SSE payload format diverges from PLAN.md spec**
File: `backend/app/market/stream.py:81-83`

PLAN.md Section 6 shows the SSE event payload as a single-ticker JSON object:
```json
{"ticker": "AAPL", "price": 190.42, ...}
```

The actual implementation sends all tickers in a single batched event as a dict-of-dicts:
```json
{"AAPL": {"ticker": "AAPL", "price": 190.42, ...}, "GOOGL": {...}}
```

The `create_stream_router` docstring documents the real format correctly, but PLAN.md Section 6 will mislead the frontend agent into writing the wrong `EventSource` handler. This is a specification-to-implementation mismatch that will cause an integration failure the moment the frontend is built. The fix is to update PLAN.md Section 6's JSON example to match what stream.py actually emits, or update the MARKET_DATA_SUMMARY.md SSE section.

**H2 — `litellm` missing from `pyproject.toml` dependencies**
File: `backend/pyproject.toml`

The LLM integration (PLAN.md Section 9) requires LiteLLM. `pyproject.toml` does not list it as a dependency. When the LLM agent builds that layer, `uv sync` will not install it and `import litellm` will fail at runtime. The dependency should be added now so the lockfile is committed before implementation begins.

---

### Medium

**M1 — `create_stream_router` registers routes on a module-level singleton router**
File: `backend/app/market/stream.py:17, 26`

`router = APIRouter(...)` is instantiated once at module level. `create_stream_router()` registers a `GET /prices` route on this same object via closure and returns it. If `create_stream_router` is called more than once (as it would be in test setups that need an isolated router), the route is registered twice on the same router object. FastAPI silently accepts duplicate routes and serves the first registered handler, making test isolation impossible without module reloading.

Recommended fix: create the `APIRouter` inside `create_stream_router()` rather than at module level.

**M2 — `SimulatorDataSource.add_ticker` does not normalize input**
Files: `backend/app/market/simulator.py:242-249`, `backend/app/market/massive_client.py:66-70`

`MassiveDataSource.add_ticker` normalizes the ticker with `ticker.upper().strip()` before use. `SimulatorDataSource.add_ticker` does not. If the API route passes an unnormalized string (e.g., `"aapl"` or `" AAPL "`), the simulator would track it as a separate symbol from `"AAPL"`, producing a duplicate GBM path and a duplicate cache entry with a lowercase key that will never match a watchlist DB row. PLAN.md Section 14 identifies ticker normalization as a known gap that should be resolved at the API boundary, but the inconsistency between the two data sources means the risk exists regardless of what the API route does.

**M3 — `conftest.py` `event_loop_policy` fixture has no effect**
File: `backend/tests/conftest.py:6-11`

The fixture is defined but has no `@pytest.fixture` decorator marker for scope, and there is no reference to it in any test. In pytest-asyncio 0.24+ (which `pyproject.toml` specifies), `event_loop_policy` is a recognized fixture name but must be decorated with `@pytest.fixture` to be picked up. Without the decorator, it is just a plain function that nothing calls. Since `asyncio_mode = "auto"` is set in `pyproject.toml` and all async tests pass, this fixture is dead code. It should either be removed or decorated and scoped appropriately.

**M4 — No `session_open` passed to `MassiveDataSource` cache updates**
File: `backend/app/market/massive_client.py:104-109`

`_poll_once()` calls `self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)` with no `session_open` argument. `PriceCache.update` then falls back to using the first observed price as the session open baseline. For the Massive client, the spec (PLAN.md Section 6, Daily Change Baseline) says `session_open` should be "the day's official open (or previous close) from the Polygon response, falling back to the first observed price if unavailable." The Polygon snapshot response typically includes `day.o` (day open) in the ticker snapshot. The current implementation silently uses the first-polled price as the baseline regardless, which means day change % in real-data mode is less accurate than specified. This is a missing feature in the completed Massive client, not in the not-yet-built layers.

---

### Low

**L1 — `PriceCache.version` property reads without the lock**
File: `backend/app/market/cache.py:83-85`

All other `PriceCache` methods acquire `self._lock` before reading or writing `_prices` and `_version`. The `version` property reads `_version` without the lock. On CPython with the GIL, reading a Python `int` is atomic and safe. On no-GIL Python builds (PEP 703, Python 3.13t+), this is a data race. The fix is a one-liner: acquire the lock in the property. This was noted in `planning/archive/MARKET_DATA_REVIEW.md` (issue 3.4) but was not included in the 7 resolved issues listed in MARKET_DATA_SUMMARY.md.

**L2 — `backend/README.md` uses incorrect `uv sync` flag**
File: `backend/README.md:10, 16`

Both install instructions use `uv sync --dev`. The correct flag for installing optional dependency groups defined as `[project.optional-dependencies]` in `pyproject.toml` is `uv sync --extra dev` (as stated in `backend/CLAUDE.md:4`). `--dev` is not a valid `uv sync` flag and will error.

**L3 — `PriceUpdate.__post_init__` `session_open` default creates an inconsistency**
File: `backend/app/market/models.py:22-26`

`PriceUpdate` has `session_open: float | None = None` and `__post_init__` sets it to `self.price` if `None`. This means a `PriceUpdate` constructed directly always has a non-`None` session_open, but the type annotation still says `float | None`. The `day_change` and `day_change_percent` properties then guard against `None` with `if self.session_open is not None` (lines 52, 58), which will always be true after construction. The `None` guard is dead code and the type annotation is misleading. Changing the annotation to `float` and removing the `None` guards would be more accurate.

**L4 — `stream.py` SSE generator version comparison uses `!=` instead of `<`**
File: `backend/app/market/stream.py:75`

`if current_version != last_version:` is correct in practice because version is monotonically increasing. However, `current_version > last_version` is more semantically precise and guards against any hypothetical version reset (e.g., if PriceCache were replaced). Minor, but a convention that matches the pattern shown in the design doc.

**L5 — `_generate_events` version/snapshot TOCTOU sends a slightly stale version marker**
File: `backend/app/market/stream.py:75-83`

The code reads `current_version`, then calls `price_cache.get_all()`. Between these two calls, more updates can arrive, meaning `get_all()` may return a snapshot at version N+k while `last_version` is set to N. On the next iteration, version is N+k+j which is != N, so the loop sends another batch that may be identical to the previous one. This produces at most one redundant identical SSE send, not a missed update. It is harmless but worth noting.

---

### Security

**S1 — No `.env.example` present; API key setup undocumented in repo**
`README.md:31` instructs users to run `cp .env.example .env` but `.env.example` does not exist. Users have no reference for which variables to set or their format. When `OPENROUTER_API_KEY` is missing, the LLM endpoint will 401 at runtime with no clear error message. The file should be created with placeholder values and comments before the LLM agent builds that layer.

**S2 — PLAN.md Section 11 public cloud deployment note is advisory-only**
The spec acknowledges (PLAN.md Section 14, "New Questions") that cloud deployment exposes trade-executing endpoints without auth. The plan calls for a note but no enforcement mechanism. When Dockerfile and deployment configs are built, this should be enforced: either basic secret-header validation or an explicit CI gate that prevents accidental public deployment without acknowledgment.

**S3 — No ticker symbol validation in the data layer**
`SimulatorDataSource.add_ticker` and `GBMSimulator._add_ticker_internal` accept arbitrary strings as ticker symbols. An attacker-supplied ticker like `"; DROP TABLE watchlist; --"` would not cause SQL injection at this layer (it's just a dict key), but would create a cache entry and a GBM price path for an arbitrary string. Once database routes are built, ticker validation must happen at the API boundary. PLAN.md Section 14 flags this under "Ticker normalization and validation" but leaves it unresolved.

---

## 3. Test Coverage Assessment

| Module | Coverage | Assessment |
|--------|----------|------------|
| `models.py` | 100% | Good. All properties and edge cases tested. |
| `cache.py` | 100% | Good. `session_open` carry-forward tests are thorough. |
| `interface.py` | 100% | Trivial — abstract methods only. |
| `seed_prices.py` | 100% | Trivial — constants only. |
| `factory.py` | 100% | Good. Whitespace-trimming of key tested. |
| `simulator.py` | 98% | Good. Missing: concurrent ticker-add race, full 10-ticker Cholesky. |
| `massive_client.py` | 56% | Acceptable. API calls mocked; `_fetch_snapshots` real path untested. |
| `stream.py` | 31% | Weak. No integration test for the SSE endpoint. |

**Missing tests of note:**

1. SSE endpoint integration test — `stream.py` is the primary consumer of `PriceCache` and has no test. An `httpx.AsyncClient` with `app` could test the endpoint with a minimal FastAPI app wrapping the stream router.

2. Concurrent write test for `PriceCache` — the lock is correct from inspection but no test exercises concurrent writers. A test with two threads simultaneously calling `cache.update` would empirically verify thread safety.

3. Full 10-ticker Cholesky decomposition test — tests use 1-2 tickers. The correlation matrix for all 10 default tickers (with TSLA's special correlation, mixed tech/finance) should be exercised to verify `np.linalg.cholesky` succeeds on the real default input.

4. `SimulatorDataSource.add_ticker` with lowercase ticker — not tested. Given the normalization gap (M2 above), a test demonstrating the inconsistency would make the gap visible.

---

## 4. Architecture Observations

### What the completed layer does well

- **Strategy pattern is clean.** Both `SimulatorDataSource` and `MassiveDataSource` fully implement `MarketDataSource`. Downstream code (SSE, portfolio valuation, trade execution) can be written without knowing which data source is active.

- **PriceCache as single point of truth.** The push model (producers write, consumers read) fully decouples the data source tick rate from the SSE push rate. The version counter eliminates redundant SSE sends efficiently.

- **GBM implementation is correct.** Log-normal price paths (`exp(drift + diffusion)`), proper Cholesky decomposition for correlated moves, and the per-ticker volatility/drift parameters are all mathematically sound. Prices cannot go negative.

- **Exception resilience in background loops.** Both `_run_loop` (simulator) and `_poll_once` (Massive) catch all exceptions and continue. A single bad tick or API error will not kill the data feed.

- **SSE implementation handles the edge cases.** `retry: 1000` directive, `X-Accel-Buffering: no` for nginx, version-based deduplication, and disconnect detection are all correct.

### Design guidance for unbuilt layers

The following points from PLAN.md Sections 13 and 14 remain open and need resolution before the agents building the next layers begin:

1. **Single `execute_trade()` function** (PLAN.md Section 14, simplification 1). Both the REST route and the LLM chat handler must call the same atomic trade-execution function with a single SQLite transaction. Without this, concurrent manual + LLM trades can corrupt cash balances. This must be a named architectural constraint, not an emergent behavior.

2. **SQLite WAL mode** (PLAN.md Section 14). Three concurrent writers (trade handler, snapshot task, LLM auto-execute path) will deadlock on SQLite's default journal mode. WAL mode plus a `busy_timeout` must be set in the database initialization code. This should be specified in the DB agent's design doc before implementation.

3. **Watchlist DELETE must check positions** (PLAN.md archive, MARKET_DATA_DESIGN.md Section 11). Removing a ticker from the watchlist must NOT call `source.remove_ticker()` if the user holds an open position in that ticker, or portfolio valuation will lose its price feed. The route must query positions before calling `await source.remove_ticker()`.

4. **Cold-start portfolio valuation** (PLAN.md Section 14). On a fresh container, `GET /api/portfolio` may run before the cache has any prices (Massive mode, before first poll). The response contract for `current_price`/`total_value` when the cache is empty must be defined: return `null`, last `avg_cost`, or `0`? This affects the frontend's loading state.

5. **`POST /api/portfolio/trade` response shape** (PLAN.md Section 13). Not defined. The frontend agent needs to know whether to refetch the full portfolio or update from the response. Recommendation: return the updated cash balance, the executed trade record, and the new position state.

---

## 5. .gitignore Gaps

The current `.gitignore` is a standard Python template. It will miss these project-specific files:

| Pattern missing | Why it matters |
|-----------------|----------------|
| `db/finally.db` or `db/*.db` | Only `db.sqlite3` (Django pattern) is ignored; the project's runtime file is `db/finally.db` |
| `frontend/.next/` | Next.js build output |
| `frontend/out/` | Next.js static export directory |
| `frontend/node_modules/` | npm dependencies |
| `.env` is correctly ignored | Confirmed present |

---

## 6. Spec Questions Not Yet Answered (Inherited from PLAN.md Sections 13-14)

These were raised in PLAN.md and remain open. They must be answered in the relevant agent design docs before the corresponding components are built.

| Question | Where it blocks |
|----------|-----------------|
| `POST /api/portfolio/trade` response shape | Frontend portfolio update logic |
| `GET /api/chat` history endpoint (or session-only design decision) | Frontend chat history on page load |
| `watchlist_changes[].action` valid values (`"add"` and `"remove"` confirmed?) | LLM structured output schema |
| LLM trade failure reporting (`errors` field vs woven into `message`) | LLM structured output schema; chat confirmation UI |
| Conversation history limit (how many messages?) | LLM prompt construction; context window management |
| Canonical mock LLM response for `LLM_MOCK=true` | E2E test agent |
| Position closure semantics (delete row at quantity=0, or keep with 0?) | Portfolio heatmap; positions table |
| `GET /api/portfolio` response schema (concrete JSON example) | Frontend/backend divergence |
