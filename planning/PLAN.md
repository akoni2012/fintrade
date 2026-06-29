# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

This is the capstone project for an agentic AI coding course. It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, % change
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving         │
│                      (Next.js export)            │
│                                                 │
│  SQLite database (volume-mounted)               │
│  Background task: market data polling/sim        │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, volume-mounted for persistence
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → OpenRouter (Cerebras for fast inference), with structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no docker-compose for production, no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, migration logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests + docker-compose.test.yml
├── db/                       # Volume mount target (SQLite file lives here at runtime)
│   └── .gitkeep              # Directory exists in repo; finally.db is gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── docker-compose.yml        # Optional convenience wrapper
├── .env                      # Environment variables (gitignored, .env.example committed)
└── .gitignore
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend lazily initializes the database on first request — creating tables and seeding default data if the SQLite file doesn't exist or is empty.
- **`db/`** at the top level is the runtime volume mount point. The SQLite file (`db/finally.db`) is created here by the backend and persists across container restarts via Docker volume.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests and supporting infrastructure (e.g., `docker-compose.test.yml`). Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: OpenRouter API key for LLM chat functionality
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- The backend reads `.env` from the project root (mounted into the container or read via docker `--env-file`)

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.)
- Runs as an in-process background task — no external dependencies

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- Polls for the union of all watched tickers on a configurable interval
- Free tier (5 calls/min): poll every 15 seconds
- Paid tiers: poll every 2-15 seconds depending on tier
- Parses REST response into the same format as the simulator

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache (`PriceCache`, thread-safe)
- For each ticker the cache holds a `PriceUpdate` record. Its serialized (`to_dict()`) form has these fields:
  - `ticker` — symbol (e.g. `"AAPL"`)
  - `price` — latest price (float)
  - `previous_price` — price at the prior tick (float)
  - `timestamp` — Unix time in seconds (float), e.g. `1754059930.5`
  - `change` — `price - previous_price`, rounded to 4 dp (float; per-tick change, used for the flash animation — not the daily baseline)
  - `change_percent` — percent change vs `previous_price`, rounded to 4 dp (float; `0.0` if `previous_price` is 0)
  - `direction` — `"up"`, `"down"`, or `"flat"` derived by comparing `price` to `previous_price`
  - `session_open` — the per-ticker baseline for daily change (see **Daily Change Baseline** below)
  - `day_change` — `price - session_open`, rounded to 4 dp (float)
  - `day_change_percent` — `day_change / session_open * 100`, rounded to 4 dp (float; `0.0` if `session_open` is 0)
- `change`, `change_percent`, `direction`, `day_change`, and `day_change_percent` are computed properties on `PriceUpdate`; `session_open` is a stored value set once when the ticker starts streaming
- The cache also maintains a monotonic `version` counter (increments on every update) so SSE streams can detect and push only changed tickers
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

> The implemented schema lives in `backend/app/market/models.py` (`PriceUpdate`, an immutable frozen dataclass) and is documented in `MARKET_DATA_SUMMARY.md`. That module is the source of truth for the SSE contract.

### Daily Change Baseline

The watchlist shows a "daily change %," which needs a stable per-ticker baseline. The per-tick `change_percent` is not suitable (it only compares consecutive ticks). **Resolution:** the market data source records a `session_open` price per ticker, captured once when the ticker first starts streaming:

- **Simulator:** `session_open` = the ticker's seed price at `start()`, or its first quoted price when added later via `add_ticker()`.
- **Massive (real data):** `session_open` = the day's official open (or previous close) from the Polygon response, falling back to the first observed price if unavailable.

Key properties of this approach:

- `session_open` is **stable for the lifetime of the running data source** (the container/session), so the daily-change column stays consistent across page reloads — unlike sparklines, which intentionally accumulate from page load.
- Daily change is then `day_change = price - session_open` and `day_change_percent = day_change / session_open * 100`, both carried in every SSE payload.
- It keeps both data sources behind the same interface: the simulator and Massive populate `session_open` differently, but downstream consumers read identical fields.

**Field usage for consumers:**
- Watchlist "change %" column and any "today" display → use **`day_change_percent`** (stable baseline).
- Price flash animation (uptick/downtick) → use the per-tick **`change` / `direction`**.

This is a small additive change to the completed market data layer (one stored `session_open` field on `PriceUpdate` plus two computed properties); existing consumers reading `price`/`change`/`direction` are unaffected.

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API
- Server pushes price updates for all tickers known to the system at a regular cadence (~500ms) — in the single-user model this is equivalent to the user's watchlist
- Each SSE event's `data` is a JSON object matching the `PriceUpdate` schema above:

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

- Client handles reconnection automatically (EventSource has built-in retry)

---

## 7. Database

### SQLite with Lazy Initialization

The backend checks for the SQLite database on startup (or first request). If the file doesn't exist or tables are missing, it creates the schema and seeds default data. This means:

- No separate migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically

### Schema

All tables include a `user_id` column defaulting to `"default"`. This is hardcoded for now (single-user) but enables future multi-user support without schema migration.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)
- `created_at` TEXT (ISO timestamp)

**watchlist** — Tickers the user is watching
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT (ISO timestamp)
- UNIQUE constraint on `(user_id, ticker)`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT (ISO timestamp)

**portfolio_snapshots** — Portfolio value over time (for P&L chart). Recorded every 30 seconds by a background task, and immediately after each trade execution.
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT (ISO timestamp)

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — trades executed, watchlist changes made; null for user messages)
- `created_at` TEXT (ISO timestamp)

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## 8. API Endpoints

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send a message, receive complete JSON response (message + executed actions) |

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment) |

---

## 9. LLM Integration

When writing code to make calls to LLMs, use cerebras-inference skill to use LiteLLM via OpenRouter to the `openrouter/openai/gpt-oss-120b` model with Cerebras as the inference provider. Structured Outputs should be used to interpret the results.

There is an OPENROUTER_API_KEY in the .env file in the project root.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads recent conversation history from the `chat_messages` table
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → OpenRouter, requesting structured output, using the cerebras-inference skill
5. Parses the complete structured JSON response
6. Auto-executes any trades or watchlist changes specified in the response
7. Stores the message and executed actions in `chat_messages`
8. Returns the complete JSON response to the frontend (no token-by-token streaming — Cerebras inference is fast enough that a loading indicator is sufficient)

### Structured Output Schema

The LLM is instructed to respond with JSON matching this schema:

```json
{
  "message": "Your conversational response to the user",
  "trades": [
    {"ticker": "AAPL", "side": "buy", "quantity": 10}
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add"}
  ]
}
```

- `message` (required): The conversational text shown to the user
- `trades` (optional): Array of trades to auto-execute. Each trade goes through the same validation as manual trades (sufficient cash for buys, sufficient shares for sells)
- `watchlist_changes` (optional): Array of watchlist modifications

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities — the core theme of the course

If a trade fails validation (e.g., insufficient cash), the error is included in the chat response so the LLM can inform the user.

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling OpenRouter. This enables:
- Fast, free, reproducible E2E tests
- Development without an API key
- CI/CD pipelines

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), daily change % (from `day_change_percent` — the session-open baseline, see Section 6), and a sparkline mini-chart (accumulated from SSE since page load)
- **Main chart area** — larger chart for the currently selected ticker, with at minimum price over time. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, using data from `portfolio_snapshots`
- **Positions table** — tabular view of all positions: ticker, quantity, avg cost, current price, unrealized P&L, % change
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history, loading indicator while waiting for LLM response. Trade executions and watchlist changes shown inline as confirmations.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Canvas-based charting library preferred (Lightweight Charts or Recharts) for performance
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 20 slim
  - Copy frontend/
  - npm install && npm run build (produces static export)

Stage 2: Python 3.12 slim
  - Install uv
  - Copy backend/
  - uv sync (install Python dependencies from lockfile)
  - Copy frontend build output into a static/ directory
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves the static frontend files and all API routes on port 8000.

### Docker Volume

The SQLite database persists via a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The `db/` directory in the project root maps to `/app/db` in the container. The backend writes `finally.db` to this path.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume mount, port mapping, and `.env` file
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

### Optional Cloud Deployment

The container is designed to deploy to AWS App Runner, Render, or any container platform. A Terraform configuration for App Runner may be provided in a `deploy/` directory as a stretch goal, but is not part of the core build.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Massive API response parsing works, both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow
- API routes: correct status codes, response shapes, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: A separate `docker-compose.test.yml` in `test/` that spins up the app container plus a Playwright container. This keeps browser dependencies out of the production image.

**Environment**: Tests run with `LLM_MOCK=true` by default for speed and determinism.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message, receive a response, trade execution appears inline
- SSE resilience: disconnect and verify reconnection

---

## 13. Review: Questions, Clarifications & Simplification Opportunities

### Questions & Clarifications

**Market Data / SSE**

- **"Daily change %"** is listed in the watchlist panel (Section 10) but the price cache only stores latest price, previous price, and timestamp (Section 6). "Daily change" requires a previous-close or session-open baseline. Is this "change since simulator start / page load", or does the simulator need to seed a baseline "open" price per ticker? Agents need a clear answer before building the watchlist component. — **RESOLVED:** see **Daily Change Baseline** in Section 6. A per-ticker `session_open` baseline is captured when the ticker starts streaming (seed price for the simulator; day open/previous close for Massive); the payload carries `day_change` / `day_change_percent`, which the watchlist column uses.
- **SSE event payload schema** is described in prose ("ticker, price, previous price, timestamp, and change direction") but no concrete JSON structure is shown. Agents building both the SSE emitter and the frontend consumer should agree on an exact schema (e.g., `{ticker, price, prev_price, change, timestamp}`). Recommend adding a one-line JSON example.
- **New ticker discovery by the background task**: when the user adds a ticker to the watchlist, how does the market data background task learn to include it? Does it re-read the watchlist from the database on each poll cycle, or does the API route notify the task some other way? This is a concrete implementation gap.

**Database**

- **`chat_messages.actions` storage format**: the LLM response schema defines `trades` and `watchlist_changes`, but what gets persisted in `actions`? The raw LLM arrays, the execution results (including success/failure per trade), or both? The frontend shows "trade executions and watchlist changes inline as confirmations" — knowing whether the stored `actions` include execution status matters for building that confirmation display.
- **Lazy initialization timing**: the spec says "on startup (or first request)." These are meaningfully different. On-startup initialization means the first HTTP request is never slow; deferred means it is. Recommend: always initialize on startup inside the FastAPI lifespan event.

**API**

- **`POST /api/portfolio/trade` response shape**: not defined. Does it return the updated portfolio state, just the executed trade, or a simple `{ok: true}`? The frontend needs to know whether to re-fetch portfolio after trading or update from the response.
- **Chat history on page load**: there is no `GET /api/chat` endpoint defined. How does the frontend display prior conversation messages when the user refreshes the page? Either add a history endpoint or explicitly state that chat history is intentionally session-scoped (not persisted across page loads on the frontend).
- **`GET /api/portfolio` response shape**: described only as "Current positions, cash balance, total value, unrealized P&L" — no concrete schema. Agents building the frontend and the backend endpoint independently will likely diverge. Recommend adding a short JSON example.

**LLM Integration**

- **`watchlist_changes[].action` values**: "add" is shown but "remove" is never explicitly listed as valid. Confirm the allowed values are `"add"` and `"remove"` so agents implement the schema correctly.
- **Trade failure reporting**: the spec says "the error is included in the chat response" but the structured output schema has no `errors` field. Is the error woven into the `message` string, or should the schema be extended with an optional `errors` array? The former is simpler; the latter is more structured.
- **Conversation history limit**: "loads recent conversation history" — how many messages? Without a cap, a long session will eventually exceed the model's context window. Recommend specifying a concrete limit (e.g., last 20 messages).

**Testing**

- **SSE disconnect simulation**: Playwright's network interception can abort SSE connections, but the exact approach depends on whether `EventSource` reconnects use the same URL or add a `Last-Event-ID` header. Confirm the expected reconnection mechanism so the E2E test can assert on it correctly.
- **Mock LLM response format**: the mock must return a valid structured response, but its exact content is not specified. Agents writing the mock and agents writing the E2E tests need to agree on a canonical mock response (e.g., what message text, whether it includes a sample trade).

---

### Simplification Opportunities

1. **Portfolio snapshot background task**: snapshotting every 30 seconds adds a background loop and table rows at a fixed cadence indefinitely. A simpler approach: snapshot only on trade execution (already specified as one of the triggers), and on page load compute "current" portfolio value on-demand from positions + live prices. This keeps the `portfolio_snapshots` table meaningful (trade events) rather than a time-series that grows unboundedly.

2. **`GET /api/watchlist` including live prices**: coupling the watchlist endpoint to the price cache means it can return stale or empty prices before the background task has populated the cache. Simpler: return only tickers from `/api/watchlist`, and let the SSE stream supply prices. The frontend already receives all prices via SSE; the initial state before the first SSE event can show a loading/dash state. This removes a cross-concern dependency.

3. **UUID primary keys on internal tables**: `watchlist`, `positions`, `trades`, `portfolio_snapshots`, and `chat_messages` all use UUID PKs, but none of these IDs appear in any API response defined in the spec. SQLite's implicit `ROWID` (or `INTEGER PRIMARY KEY`) would be simpler, smaller, and faster. UUIDs are valuable when IDs cross system boundaries (e.g., shared via URL or API) — that doesn't apply here. Consider reserving UUIDs only for `users_profile.id` where the value `"default"` is already meaningful.

4. **Charting library choice**: the spec hedges between "Lightweight Charts or Recharts" but then states "Canvas-based charting library preferred." These have meaningfully different APIs and bundle sizes. Pick one — Lightweight Charts is the right call for a trading terminal aesthetic and is canvas-based. Leaving this open invites agents to choose differently and produce an inconsistent UI.

5. **`users_profile` table**: for a single-user app, the table adds schema and join complexity for one row with two useful columns (`cash_balance`, `created_at`). Consider whether `cash_balance` could live in a `settings` key-value table or simply be an application constant that is initialized on startup, reducing the number of tables that agent-written code must manage. (Keep it if the multi-user scaffolding rationale is genuinely important to the course's teaching goals.)

---

## 14. Second-Pass Review (post Market Data completion)

This section is an additional review pass. It deliberately avoids repeating Section 13 and instead focuses on (a) gaps not yet raised and (b) reconciling the plan with the **now-completed market data layer** described in `MARKET_DATA_SUMMARY.md`.

### Reconciliation with the Completed Market Data Layer

- **SSE payload schema is effectively resolved — update the plan to match.** Section 13 asks for a concrete SSE schema, but the implemented `PriceUpdate` dataclass already defines the canonical fields: `ticker, price, previous_price, timestamp, change, change_percent, direction`. (Section 6 has now been updated to match, with a concrete JSON example.) Two gotchas for the Frontend Engineer: the field is `previous_price` (not `prev_price`), and `timestamp` is **Unix seconds as a float**, not an ISO string.
- **New-ticker discovery is resolved — make the contract explicit.** The interface already exposes `add_ticker()` / `remove_ticker()`. Section 8's `POST /api/watchlist` and `DELETE /api/watchlist/{ticker}` should explicitly state that these routes must call `source.add_ticker()` / `source.remove_ticker()` (in addition to the DB write), and that the singleton `source` + `cache` are created once in the FastAPI lifespan and shared via app state. Without this stated, an agent building the watchlist routes may update the DB but never tell the running data source.
- **`change` is per-tick, not "daily." — RESOLVED.** The implemented `change`/`direction` reflect the move since the *previous tick*, not a session baseline. Resolution adopts option (b): Section 6's **Daily Change Baseline** defines a per-ticker `session_open` captured when the ticker starts streaming, and the SSE payload now carries `session_open`, `day_change`, and `day_change_percent`. The watchlist's daily-change column uses `day_change_percent`; the per-tick `change`/`direction` remain for the flash animation only.

### New Questions & Clarifications

- **Adding an unknown ticker.** `seed_prices.py` has params only for the 10 seed tickers. What happens when a user (or the LLM) adds an arbitrary ticker like `PYPL` or a typo like `ZZZZ`? In simulator mode, is there a default seed price + GBM param fallback, or is the ticker rejected? In Massive mode, an invalid symbol returns no data. The watchlist `POST` needs a defined validation/fallback path, or new tickers will silently never stream.
- **Ticker normalization & validation.** Is the ticker uppercased/trimmed before insert? The DB has a `UNIQUE(user_id, ticker)` constraint, so `aapl` vs `AAPL` would create duplicates that the simulator treats as distinct symbols. Specify normalization at the API boundary.
- **Position closure semantics.** When a sell reduces quantity to exactly 0, is the `positions` row deleted or kept with `quantity=0`? This directly affects the heatmap (zero-weight rectangle) and the positions table (phantom rows). Recommend: delete the row on full close.
- **Concurrent writers to SQLite.** Three things write concurrently: request-handler trades, the 30s snapshot background task, and (per the plan) the LLM auto-execute path. SQLite's default journal mode will throw `database is locked` under concurrent writes. Recommend specifying WAL mode + a single shared connection (or a short busy_timeout) so agents don't each invent their own approach.
- **Manual + AI trade race.** A manual trade and an LLM-driven trade can both read cash/positions, then both write. Without a single serialized trade-execution function (one lock/transaction that both the REST route and the chat handler call), balances can corrupt. Recommend stating that *all* trades — manual and LLM — funnel through one `execute_trade()` function.
- **Valuation before the first tick (cold start).** On a fresh container, `GET /api/portfolio` may run before the cache has any prices. What does `current_price`/`total_value`/`unrealized P&L` return then — `null`, last avg_cost, or 0? Define the cold-start contract so the frontend renders a sane loading state rather than `NaN%`.
- **Money as `REAL` (float).** `cash_balance`, `price`, and `avg_cost` are floats. Repeated buy/sell cycles will accumulate floating-point drift (e.g., cash showing `9999.9999998`). For a demo this is acceptable, but worth a one-line decision: round on display, or store cents as integers. Flag it so it's a choice, not an accident.
- **No historical price persistence affects the main chart, not just sparklines.** The plan accepts that sparklines build up from SSE since page load. But the "Main chart area — price over time" (Section 10) has the *same* limitation: with no stored price history, the detailed chart is also empty on load and fills in live. Either state this explicitly (both are session-accumulated) or decide whether the backend should retain a rolling in-memory price history per ticker to back the detailed chart.
- **LLM JSON robustness.** Even with structured outputs, the model can occasionally return malformed/partial JSON or omit the required `message`. Define the fallback (e.g., return a safe "I couldn't process that" message, execute no trades) so a bad LLM response can't 500 the chat endpoint or auto-execute garbage.
- **Public exposure on cloud deploy.** "No auth" is fine for `localhost`, but the optional App Runner/Render deployment (Section 11) would put an unauthenticated trade-executing endpoint on the public internet. Worth one sentence noting the cloud path should stay private/demo-only, or add a simple shared-secret header.

### New Simplification Opportunities

1. **One trade-execution path.** Beyond preventing races (above), funneling manual and LLM trades through a single `execute_trade()` that returns a structured result (filled / rejected + reason) lets *both* the REST response and the chat `actions` field reuse the exact same shape — eliminating the Section 13 ambiguity about what gets stored in `chat_messages.actions` and what `POST /api/portfolio/trade` returns.
2. **Single price-history buffer on the frontend.** Rather than separately accumulating SSE data for sparklines and for the detailed chart, keep one rolling per-ticker buffer in frontend state and let both components read from it. Less code, guaranteed-consistent charts.
3. **Reconcile docs to code now.** The market data layer is built and tested; updating Section 6 to match `PriceUpdate` (and pointing to `MARKET_DATA_SUMMARY.md` as the source of truth for the SSE contract) removes the single largest source of frontend/backend divergence before the next agents start.
