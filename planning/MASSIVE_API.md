# Massive API (formerly Polygon.io) — Stock Price Reference

Massive (rebranded from Polygon.io in October 2025) provides REST, WebSocket, and flat-file access to US equity market data. This document covers only the REST endpoints needed by FinAlly: multi-ticker snapshots (live prices), previous-day bars (session-open baseline), and last-trade (single-ticker fallback).

Base URL for all REST calls: `https://api.polygon.io`  
Authentication: pass `apiKey=<MASSIVE_API_KEY>` as a query parameter, **or** set the `Authorization: Bearer <key>` header.

---

## Tier Summary

| Plan | Delay | Rate Limit | Best poll interval |
|------|-------|------------|--------------------|
| Starter / Developer | 15 min delayed | 5 req/min | — (not useful for live prices) |
| Advanced | Real-time | Higher (undisclosed) | 5–15 s |
| Business | Real-time | Highest | 2–5 s |

The FinAlly `PLAN.md` specifies a **15-second default poll interval** for the free tier and **2–15 seconds** for paid tiers.

---

## Endpoint 1 — Multi-Ticker Snapshot (primary)

The main endpoint used by `MassiveDataSource`. Retrieves the latest trade, quote, and OHLC day-bar for a comma-separated list of tickers in one API call.

```
GET /v2/snapshot/locale/us/markets/stocks/tickers
```

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tickers` | string | No | Comma-separated ticker symbols (e.g. `AAPL,MSFT,TSLA`). Omit or leave empty to return all tickers. Case-sensitive — always uppercase. |
| `include_otc` | boolean | No | Include OTC securities. Default `false`. |
| `apiKey` | string | Yes* | API key (*or use Authorization header). |

### Response Schema

```json
{
  "count": 2,
  "status": "OK",
  "tickers": [
    {
      "ticker": "AAPL",
      "updated": 1617901342969834000,
      "todaysChange": 1.23,
      "todaysChangePerc": 0.65,
      "day": {
        "o": 128.50,
        "h": 130.20,
        "l": 127.80,
        "c": 129.84,
        "v": 95123456,
        "vw": 129.10
      },
      "min": {
        "o": 129.60,
        "h": 129.90,
        "l": 129.55,
        "c": 129.84,
        "v": 234567,
        "vw": 129.72,
        "t": 1617900000000
      },
      "prevDay": {
        "o": 127.00,
        "h": 128.95,
        "l": 126.50,
        "c": 128.61,
        "v": 110234567,
        "vw": 127.90
      },
      "lastTrade": {
        "p": 129.8473,
        "s": 25,
        "t": 1617901342969834000,
        "x": 4
      },
      "lastQuote": {
        "P": 129.85,
        "S": 2,
        "p": 129.84,
        "s": 3,
        "t": 1617901342970000000
      }
    }
  ]
}
```

### Key Fields Used by FinAlly

| Field | Used for |
|-------|----------|
| `tickers[].ticker` | Ticker symbol |
| `tickers[].lastTrade.p` | Latest price (written to `PriceCache`) |
| `tickers[].lastTrade.t` | Trade timestamp (Unix nanoseconds → divide by 1e9 for seconds) |
| `tickers[].day.o` | Day's official open → `session_open` baseline |
| `tickers[].prevDay.c` | Previous close → fallback `session_open` if `day.o` is 0 |
| `tickers[].todaysChangePerc` | Cross-check (not used directly — we compute from `session_open`) |

> **Timestamp note:** `lastTrade.t` is in **Unix nanoseconds**. The existing `massive_client.py` divides by `1000.0` (treating it as milliseconds) — this is a bug; it should divide by `1_000_000_000.0` or use the `massive` SDK which normalises the value.

### Python Client Example

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key="YOUR_API_KEY")

# Fetch snapshots for specific tickers (one API call)
snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "MSFT", "TSLA"],
)

for snap in snapshots:
    price = snap.last_trade.price
    # Timestamps from the SDK are already in seconds (the SDK normalises them)
    ts = snap.last_trade.timestamp
    day_open = snap.day.open if snap.day else None
    prev_close = snap.prev_day.close if snap.prev_day else None
    session_open = day_open or prev_close or price
    print(f"{snap.ticker}: ${price:.2f}  open={session_open:.2f}")
```

### Raw HTTP Example (without SDK)

```python
import httpx

API_KEY = "YOUR_API_KEY"
TICKERS = ["AAPL", "MSFT", "TSLA", "NVDA"]

resp = httpx.get(
    "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
    params={
        "tickers": ",".join(TICKERS),
        "apiKey": API_KEY,
    },
    timeout=10.0,
)
resp.raise_for_status()
data = resp.json()

for item in data.get("tickers", []):
    ticker = item["ticker"]
    price = item["lastTrade"]["p"]
    day_open = item.get("day", {}).get("o") or 0
    prev_close = item.get("prevDay", {}).get("c") or 0
    session_open = day_open or prev_close or price
    ts_ns = item["lastTrade"]["t"]
    ts_sec = ts_ns / 1_000_000_000.0
    print(f"{ticker}: ${price:.2f}  session_open={session_open:.2f}")
```

---

## Endpoint 2 — Previous Day Bar (session-open fallback)

Fetches the prior trading day's OHLCV for a single ticker. Useful as a cold-start fallback when the snapshot's `day.o` is not yet available (pre-market, first minutes of session).

```
GET /v2/aggs/ticker/{stocksTicker}/prev
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `stocksTicker` | string | Ticker symbol (e.g. `AAPL`). Case-sensitive. |

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `adjusted` | boolean | `true` | Apply split/dividend adjustments. |
| `apiKey` | string | — | API key. |

### Response Schema

```json
{
  "ticker": "AAPL",
  "adjusted": true,
  "resultsCount": 1,
  "status": "OK",
  "results": [
    {
      "T": "AAPL",
      "o": 115.55,
      "h": 117.59,
      "l": 114.13,
      "c": 115.97,
      "v": 131704427,
      "vw": 116.3058,
      "t": 1605042000000,
      "n": 1234
    }
  ]
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `results[0].o` | Previous day open |
| `results[0].c` | Previous day close → use as `session_open` fallback |
| `results[0].t` | Unix milliseconds timestamp of the bar |

### Python Example

```python
result = client.get_previous_close(ticker="AAPL", adjusted=True)
prev_close = result[0].close if result else None
```

---

## Endpoint 3 — Last Trade (single-ticker fallback)

Fetches the most recent trade for a single ticker. Use this only when a specific ticker is missing from the multi-ticker snapshot response.

```
GET /v2/last/trade/{stocksTicker}
```

### Response Schema

```json
{
  "status": "OK",
  "results": {
    "T": "AAPL",
    "p": 129.8473,
    "s": 25,
    "t": 1617901342969834000,
    "x": 4
  }
}
```

### Key Fields

| Field | Description |
|-------|-------------|
| `results.p` | Last trade price |
| `results.s` | Trade size (shares) |
| `results.t` | Timestamp (Unix nanoseconds) |
| `results.T` | Ticker symbol |

### Python Example

```python
trade = client.get_last_trade(ticker="AAPL")
price = trade.price
ts = trade.timestamp  # SDK normalises to seconds
```

---

## Installation

```bash
# The massive package is the official Python client (successor to polygon-api-client)
pip install massive
# or via uv:
uv add massive
```

```toml
# pyproject.toml
[project]
dependencies = [
    "massive>=1.0.0",
]
```

---

## Error Handling

The API returns HTTP 4xx/5xx for errors. Common cases:

| Status | Cause | Action |
|--------|-------|--------|
| 401 | Bad or missing API key | Log and stop polling |
| 403 | Endpoint not in your plan | Log and fall back to simulator |
| 429 | Rate limit exceeded | Log; the next poll interval should back off |
| 200 + empty `tickers` | Market closed or tickers not found | Keep previous cached prices |

The `MassiveDataSource._poll_once` method catches all exceptions and logs them without re-raising, so the poll loop continues on transient failures.

---

## Market Hours Note

The snapshot endpoint returns the `lastTrade` from the most recent session. Outside of trading hours (4 AM – 8 PM ET) prices are stale. The simulator is the better default for a 24/7 demo. When using Massive, the frontend should display the data timestamp so users know when the last trade occurred.
