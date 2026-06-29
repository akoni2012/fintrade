# Codex Review of `planning/PLAN.md`

**Date:** 2026-06-28  
**Reviewer:** Codex  
**Scope:** `planning/PLAN.md`, checked against the current repository state and the completed market data implementation.

## Summary

`PLAN.md` is a strong product and architecture brief, but it is currently doing two jobs at once: acting as the canonical implementation spec and carrying old review notes inside the same document. That makes it risky for the next agents to consume because some requirements are resolved in one section, still open in another, and not reflected in the endpoint contracts.

The highest-risk gaps are concrete contract issues: the SSE payload shape in the plan does not match the implemented stream, API response schemas are underspecified, trade execution concurrency is called out only as review commentary rather than a normative requirement, and the LLM/chat execution result format is not defined.

## Findings

### High

**H1 - SSE payload shape in Section 6 conflicts with implemented `stream.py`.**  
`PLAN.md:212-227` says each SSE event `data` is a single `PriceUpdate` object. The implemented endpoint in `backend/app/market/stream.py` sends one batched object keyed by ticker:

```json
{
  "AAPL": {"ticker": "AAPL", "price": 190.42},
  "GOOGL": {"ticker": "GOOGL", "price": 175.10}
}
```

This will break the frontend if it follows the plan literally. Either update `PLAN.md` to document batched SSE payloads, or change the stream implementation. Given the current implementation and docstring, updating the plan is the smaller fix.

**H2 - The plan lacks concrete API response contracts for the frontend/backend boundary.**  
`PLAN.md:305-327` lists endpoints but omits response schemas for `GET /api/portfolio`, `POST /api/portfolio/trade`, `GET /api/watchlist`, `POST /api/chat`, and `GET /api/portfolio/history`. Later review notes call this out at `PLAN.md:526-528`, but the endpoint table remains unresolved. This invites independent agents to implement incompatible JSON shapes.

Add short canonical examples for the core responses before frontend/API work continues. The most important are:

- `GET /api/portfolio`: cash, total value, positions array, portfolio P&L fields, and cold-start price behavior.
- `POST /api/portfolio/trade`: executed/rejected status, reason, trade record, updated position, updated cash.
- `POST /api/chat`: assistant message plus action execution results, not just the model's requested actions.

**H3 - Trade serialization is a critical architecture rule but is only documented as a review suggestion.**  
`PLAN.md:572-573` correctly identifies the race between manual trades and LLM-driven trades, and `PLAN.md:582` recommends one trade-execution path. This should be promoted into Sections 7-9 as a hard requirement: all manual and AI trades must call one `execute_trade()` function that runs inside a single SQLite transaction or process-level async lock.

Without that, two concurrent requests can both read the same cash/position state and write inconsistent balances. This is the main data-integrity risk in the planned backend.

**H4 - LLM action persistence and failure reporting are undefined.**  
`PLAN.md:354-368` defines the LLM's requested action schema, but `PLAN.md:377` says trade validation errors are included in the chat response without defining where. `PLAN.md:521` and `PLAN.md:533` call out the ambiguity, but it remains unresolved.

The stored `chat_messages.actions` should contain execution results, not only raw model intent. Recommended shape:

```json
{
  "trades": [
    {
      "ticker": "AAPL",
      "side": "buy",
      "quantity": 10,
      "status": "filled",
      "price": 190.42,
      "reason": null
    }
  ],
  "watchlist_changes": [
    {"ticker": "PYPL", "action": "add", "status": "applied", "reason": null}
  ]
}
```

This gives the chat UI, persisted history, and E2E tests one stable contract.

### Medium

**M1 - The document contains stale review sections that contradict the resolved spec.**  
`PLAN.md:516` still asks for a concrete SSE schema, while `PLAN.md:212-227` now contains one and `PLAN.md:563` says it is resolved. `PLAN.md:517` asks how new tickers reach the background task, while `PLAN.md:564` says this is resolved through `add_ticker()` / `remove_ticker()` but still not promoted into the endpoint contract.

Keep `PLAN.md` as the source of truth and move historical review notes to `planning/archive/` or mark each item with an explicit status. Right now, a later agent has to infer which section wins.

**M2 - Watchlist add/remove behavior is under-specified for positions and market data.**  
`PLAN.md:315-317` lists watchlist CRUD endpoints, and `PLAN.md:564` says routes should call the market data source. The plan still needs normative rules:

- Normalize ticker input with `strip().upper()` before DB writes and market-data calls.
- Validate ticker format before accepting it.
- Decide what happens for unknown simulator tickers and invalid Massive symbols.
- Do not stop streaming a ticker on watchlist removal if there is still an open position requiring valuation.

Several of these are mentioned later at `PLAN.md:569-570`, but they should live in the Watchlist/API section.

**M3 - SQLite operational settings should be specified, not left to implementers.**  
`PLAN.md:572` notes concurrent SQLite writers. Section 7 should require `PRAGMA journal_mode=WAL` and a `busy_timeout`, and should state whether the app uses one shared connection, short-lived connections, or a small helper that applies these pragmas every time.

This is especially important because the plan includes request-time trades, LLM auto-trades, and a portfolio snapshot background task.

**M4 - Initialization timing is ambiguous.**  
`PLAN.md:235-237` says initialization happens "on startup (or first request)", and `PLAN.md:522` correctly says these are different. Pick startup initialization in FastAPI lifespan. That gives the first request predictable latency and creates a natural place to create the singleton `PriceCache` and market data source.

**M5 - Chart history expectations are unclear.**  
`PLAN.md:25` explicitly says sparklines accumulate from SSE since page load, but `PLAN.md:405` describes a main chart with price over time without saying whether it has the same limitation. `PLAN.md:576` flags this. Decide whether all price charts are session-only frontend buffers, or whether the backend maintains rolling in-memory history for the selected ticker.

For the capstone scope, session-only frontend buffers are simpler and consistent.

**M6 - LLM dependencies are specified in prose but absent from backend dependencies.**  
`PLAN.md:331-335` requires LiteLLM/OpenRouter. The local `cerebras-inference` skill also says to add `litellm` and `pydantic`, but `backend/pyproject.toml` currently has neither `litellm` nor an explicit `pydantic` dependency. Pydantic is pulled indirectly by FastAPI, but LiteLLM is not. Add `litellm` before the LLM implementation starts.

### Low

**L1 - `.env.example` is promised but missing from the plan's current repository shape.**  
`PLAN.md:105` says `.env.example` is committed. The current repo does not have one. Add it with `OPENROUTER_API_KEY=`, `MASSIVE_API_KEY=`, and `LLM_MOCK=false`.

**L2 - The directory structure is aspirational but not status-labeled.**  
`PLAN.md:85-106` lists `frontend/`, `scripts/`, `test/`, `db/`, `Dockerfile`, and `docker-compose.yml`, but most are absent or empty in the current checkout. That is acceptable for a plan, but add a short "Current implementation status" section so agents do not assume scaffolding exists.

**L3 - Portfolio snapshot growth needs a retention policy or simplification.**  
`PLAN.md:277` records snapshots every 30 seconds indefinitely, and `PLAN.md:545` suggests simplifying this. Either snapshot only on trades plus startup, or define retention/downsampling. Otherwise a long-running demo accumulates low-value rows forever.

**L4 - Money precision is acknowledged but not decided.**  
`PLAN.md:575` notes `REAL` drift. Make the rule explicit: either store integer cents for cash/trade prices or use floats internally and round to two decimals for all API responses/display. For a demo, rounded API/display values are probably enough.

## Recommended Edits to `PLAN.md`

1. Replace the Section 6 SSE example with the implemented batched payload format.
2. Add JSON response examples under Section 8 for all non-stream endpoints.
3. Move resolved/stale review notes from Sections 13-14 into `planning/archive/`, or convert them into a checklist with `OPEN` / `RESOLVED` statuses.
4. Promote one serialized `execute_trade()` path into Sections 7-9 as a required backend invariant.
5. Define `chat_messages.actions` as execution results, including failed actions and reasons.
6. Specify startup initialization in FastAPI lifespan, including DB setup, WAL/busy timeout, `PriceCache`, and market data source startup.
7. Add watchlist normalization/validation rules and unknown ticker behavior.
8. Decide that price charts are session-only frontend buffers unless rolling backend history is intentionally added.
