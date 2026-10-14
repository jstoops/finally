# Massive API Reference (formerly Polygon.io)

Research notes on the Massive REST API for getting **real-time** and **end-of-day** stock prices for many tickers at once, as used by FinAlly's `MassiveDataSource`. It was verified in October 2026 against the official docs (massive.com/docs) and the source of the official Python client (`github.com/massive-com/client-python`).

> Polygon.io rebranded to **Massive** in late 2025. The API paths, JSON shapes and Python client API stayed the same. Only the host (`api.massive.com`), the package name (`massive`) and the env var (`MASSIVE_API_KEY`) changed. `api.polygon.io` still answers.

---

## 1. Essentials

| Item | Value |
|---|---|
| Base URL | `https://api.massive.com` |
| Auth | `Authorization: Bearer <KEY>` header (preferred) **or** `?apiKey=<KEY>` query param |
| Python package | `massive` (`uv add massive`), import `from massive import RESTClient` |
| Python client key | `RESTClient()` reads `MASSIVE_API_KEY` from the environment **at import time**; pass `api_key=` explicitly to be safe |
| Client defaults | `connect_timeout=10.0`, `read_timeout=10.0`, `retries=3`, `num_pools=10`, `pagination=True` |
| Auto-retried statuses | 413, 429, 499, 500, 502, 503, 504 (urllib3 `Retry`, backoff factor 0.1) |
| Errors | Any non-200 raises `massive.exceptions.BadResponse` (message = response body); `AuthError` if no key |
| Client is | **Synchronous** (urllib3). In asyncio code, call it with `asyncio.to_thread(...)` |

### Plans, rate limits and data freshness (Stocks, individual plans)

| Plan | Price/mo | Rate limit | Freshness | History | Snapshot endpoints |
|---|---|---|---|---|---|
| **Basic** (free) | $0 | **5 calls/min** | **End of day** | 2 yrs | **Not included** |
| Starter | $29 | Unlimited* | 15-min delayed | 5 yrs | Included |
| Developer | $79 | Unlimited* | 15-min delayed | 10 yrs | Included |
| Advanced | $199 | Unlimited* | Real-time | 20+ yrs | Included |

\* Massive asks paid users to stay under ~100 req/s. Going over the free-tier limit returns **HTTP 429**.

**Key implication for FinAlly:** the multi-ticker snapshot endpoint, which is the natural "live prices" call, is **not available on the free Basic plan**. It returns a non-200 that the client raises as `BadResponse`. A free key can only get **end-of-day** data, and the best way to do that is the *grouped daily* endpoint (§3.1): one call returns every US stock for a date. See §5 for the strategy.

---

## 2. Real-time / delayed prices for many tickers

### 2.1 Full Market Snapshot, filtered to our tickers (primary endpoint)

One call returns the latest trade, quote, minute bar, today's bar and previous day's bar for **every ticker in the list**.

```
GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT,NVDA
```

| Query param | Notes |
|---|---|
| `tickers` | Comma-separated and **case-sensitive** (send uppercase). Omit it to get the whole market (~10k tickers, so don't). |
| `include_otc` | Default `false` |

- Plans: Starter and Developer (15-min delayed), Advanced (real-time). **Not on Basic.**
- Snapshot data is **cleared at 3:30 AM ET** every day and refills from ~4:00 AM ET as pre-market trades arrive. Expect missing or empty `day` fields overnight.
- `lastTrade` / `lastQuote` are only present if the plan includes trades or quotes. Code must handle them being absent.

**Raw response** (one element shown):

```json
{
  "status": "OK",
  "count": 1,
  "tickers": [
    {
      "ticker": "AAPL",
      "todaysChange": -0.124,
      "todaysChangePerc": -0.601,
      "updated": 1605192894630916600,
      "day":     {"o": 20.64, "h": 20.64, "l": 20.506, "c": 20.506, "v": 37216, "vw": 20.616},
      "prevDay": {"o": 20.79, "h": 21.0,  "l": 20.5,   "c": 20.63,  "v": 292738, "vw": 20.6939},
      "min":     {"av": 37216, "o": 20.506, "h": 20.506, "l": 20.506, "c": 20.506, "v": 5000, "vw": 20.5105, "n": 1, "t": 1684428600000},
      "lastTrade": {"p": 20.506, "s": 2416, "x": 4, "c": [14, 41], "i": "71675577320245", "t": 1605192894630916600},
      "lastQuote": {"P": 20.6, "S": 22, "p": 20.5, "s": 13, "t": 1605192959994246100}
    }
  ]
}
```

**Python client:**

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key=api_key)

snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,      # or "stocks"
    tickers=["AAPL", "MSFT", "NVDA"],            # list is joined with "," by the client
)

for snap in snapshots:                            # list[TickerSnapshot]
    lt = snap.last_trade
    print(snap.ticker,
          lt.price if lt else None,               # last trade price
          lt.sip_timestamp if lt else None,       # NANOseconds since epoch
          snap.prev_day.close if snap.prev_day else None,
          snap.todays_change_percent)
```

**Client model field mapping** (`massive.rest.models.snapshot.TickerSnapshot`). Get these names right, because the JSON keys are abbreviated:

| Python attribute | JSON key | Type / units |
|---|---|---|
| `ticker` | `ticker` | str |
| `last_trade.price` | `lastTrade.p` | float |
| `last_trade.size` | `lastTrade.s` | float |
| `last_trade.sip_timestamp` | `lastTrade.t` | int, **nanoseconds** |
| `last_trade.participant_timestamp` | `lastTrade.y` | int, nanoseconds |
| `last_quote.bid_price` / `ask_price` | `lastQuote.p` / `P` | float |
| `last_quote.bid_size` / `ask_size` | `lastQuote.s` / `S` | int |
| `last_quote.sip_timestamp` | `lastQuote.t` | int, nanoseconds |
| `min.close` (`open/high/low/volume/vwap`) | `min.c` … | float; `min.timestamp` is **milliseconds** |
| `min.accumulated_volume` | `min.av` | int |
| `day.open/high/low/close/volume/vwap` | `day.o` … | float (an `Agg`) |
| `prev_day.close` (etc.) | `prevDay.c` … | float (an `Agg`) |
| `todays_change` / `todays_change_percent` | `todaysChange` / `todaysChangePerc` | float, vs previous close |
| `updated` | `updated` | int, **nanoseconds** |

> ⚠️ **Common mistakes.** There is **no** `last_trade.timestamp` attribute; it is `sip_timestamp`, in **nanoseconds**, not milliseconds. There is **no** `day.previous_close` or `day.change_percent`; use `prev_day.close` and the top-level `todays_change_percent`. Because the models are dataclasses with `Optional` fields, a missing block is `None` and raises no error, so a `MagicMock` in unit tests will happily "find" attributes that don't exist. Build test fixtures with the real model classes (`TickerSnapshot.from_dict({...})`).

**Choosing "the price"** from a snapshot, best first:
1. `last_trade.price`: the actual last print (needs trades entitlement)
2. `min.close`: close of the latest minute bar
3. `day.close`: today's running close
4. `prev_day.close`: yesterday's close (overnight, after the 3:30 AM reset)

### 2.2 Single-ticker snapshot

```
GET /v2/snapshot/locale/us/markets/stocks/tickers/{ticker}
```
```python
snap = client.get_snapshot_ticker(SnapshotMarketType.STOCKS, "AAPL")   # TickerSnapshot
```
It has the same shape as one element above. FinAlly doesn't need it, because the multi-ticker call is strictly better under rate limits.

### 2.3 Universal snapshot (v3, cross-asset)

```
GET /v3/snapshot?ticker.any_of=AAPL,MSFT&limit=250
```
```python
for s in client.list_universal_snapshots(ticker_any_of=["AAPL", "MSFT"], limit=250):
    print(s.ticker, s.session.close if s.session else None)
```
It covers stocks, options, FX and crypto in one call and paginates (`limit` max 250). It has the same plan restrictions as 2.1. FinAlly only trades US stocks, so 2.1 is simpler.

### 2.4 Last trade / last quote (one ticker per call)

```python
t = client.get_last_trade("AAPL")    # /v2/last/trade/AAPL  → .price, .size, .sip_timestamp (ns)
q = client.get_last_quote("AAPL")    # /v2/last/nbbo/AAPL   → .bid_price, .ask_price, ...
```
One call per ticker would burn the free tier's 5 calls/min on just 5 tickers, so FinAlly doesn't use these.

### 2.5 WebSockets (not used)

`wss://socket.massive.com/stocks` (real-time, Advanced) or `wss://delayed.massive.com/stocks` (15-min, Starter/Developer) push trades (`T.*`), quotes (`Q.*`), and per-second (`A.*`) or per-minute (`AM.*`) aggregates. The client exposes `massive.WebSocketClient(subscriptions=["AM.AAPL"])`. FinAlly polls REST instead (PLAN §6): it works on every paid tier, has no connection state, and fits the "one background task writes to the cache" model. WebSockets are **not available on Basic**.

---

## 3. End-of-day prices

All of these are **available on the free Basic plan** (EOD freshness, 2 years of history).

### 3.1 Grouped Daily, the whole market for one date (best for many tickers)

```
GET /v2/aggs/grouped/locale/us/market/stocks/{YYYY-MM-DD}?adjusted=true
```

One call returns the daily OHLCV of **every** US stock for that date (~10k rows, ~1 MB). There is no ticker filter, so filter client-side. That is one call, versus N calls for `/prev`.

```json
{
  "status": "OK", "adjusted": true, "queryCount": 10423, "resultsCount": 10423,
  "results": [
    {"T": "AAPL", "o": 189.1, "h": 191.0, "l": 188.4, "c": 190.52, "v": 51234567, "vw": 190.02, "n": 612345, "t": 1760040000000}
  ]
}
```

```python
aggs = client.get_grouped_daily_aggs("2026-10-09", adjusted=True)   # list[GroupedDailyAgg]
wanted = {"AAPL", "MSFT", "NVDA"}
closes = {a.ticker: a.close for a in aggs if a.ticker in wanted}
```

`GroupedDailyAgg` fields are `ticker` (`T`), `open`, `high`, `low`, `close`, `volume`, `vwap`, `transactions` (`n`) and `timestamp` (`t`, **milliseconds**, end of window).

**Weekends and holidays** return `resultsCount: 0` / an empty list, and **today** is empty until the EOD data is published after the close. To get the latest EOD bar, walk back from today until you get results:

```python
from datetime import date, timedelta

def latest_eod_closes(client, tickers: set[str], max_lookback: int = 7) -> dict[str, float]:
    day = date.today()
    for _ in range(max_lookback):
        aggs = client.get_grouped_daily_aggs(day.isoformat(), adjusted=True)
        if aggs:
            return {a.ticker: a.close for a in aggs if a.ticker in tickers}
        day -= timedelta(days=1)
    return {}
```

On the free tier, each probe costs one of the 5 calls/min. In the worst case (Monday morning plus a holiday), finding the bar takes 3–4 calls.

### 3.2 Previous Close (one ticker)

```
GET /v2/aggs/ticker/{ticker}/prev
```
```json
{"status": "OK", "ticker": "AAPL", "resultsCount": 1,
 "results": [{"T": "AAPL", "o": 115.55, "h": 117.59, "l": 114.13, "c": 115.97, "v": 131704427, "vw": 116.3058, "t": 1605042000000}]}
```
```python
prev = client.get_previous_close_agg("AAPL")       # list[PreviousCloseAgg]
print(prev[0].close, prev[0].timestamp)            # timestamp: ms
```
This is the simplest call and handles weekends and holidays itself, but it costs **one call per ticker**. It is fine for a single newly added ticker, too slow for the whole watchlist on Basic.

### 3.3 Daily Open/Close (one ticker, one date)

```
GET /v1/open-close/{ticker}/{date}
```
```python
oc = client.get_daily_open_close_agg("AAPL", "2026-10-09")
print(oc.open, oc.close, oc.pre_market, oc.after_hours)
```
It adds the pre-market and after-hours prices. FinAlly doesn't need it.

### 3.4 Aggregate bars (history, one ticker)

```
GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
```
```python
bars = list(client.list_aggs("AAPL", 1, "day", "2026-09-01", "2026-10-09", limit=50000))
for b in bars:
    print(b.timestamp, b.open, b.high, b.low, b.close, b.volume)   # timestamp: ms (window start)
```
`list_aggs` paginates automatically, and `get_aggs` returns a single page. FinAlly's chart history comes from the in-memory ring buffer (PLAN §6), so this endpoint is out of scope. It is noted here in case a "1M/1Y chart" is added later.

---

## 4. Timestamps

| Source | Units | To Unix seconds |
|---|---|---|
| `lastTrade.t`, `lastQuote.t`, `updated` (snapshot) | **nanoseconds** | `ns / 1e9` |
| `min.t`, aggregate/grouped/prev `t` | **milliseconds** | `ms / 1e3` |

FinAlly stamps cache entries with the **time the poll was received** (`time.time()`) rather than the exchange timestamp (see MARKET_INTERFACE.md §5). This keeps chart points monotonic and in the same clock as the simulator.

---

## 5. Strategy for FinAlly

```
           ┌─ snapshot works ─────────► LIVE mode: get_snapshot_all(tickers) every MASSIVE_POLL_INTERVAL s
start() ───┤                             (1 call per poll for all tracked tickers)
           └─ BadResponse 401/403 ────► EOD mode: get_grouped_daily_aggs(latest trading day)
                                         filtered to tracked tickers; refreshed rarely
                                         (prices don't change intraday on Basic anyway)
```

- **One call per poll** no matter how many tickers. That's what keeps the free 5/min budget workable.
- **Default poll 15 s** (`MASSIVE_POLL_INTERVAL`, PLAN §5) is 4 calls/min, under the free limit with headroom. Paid plans can go down to 2 s.
- **Uppercase** tickers before sending, because `tickers=` is case-sensitive.
- A ticker Massive doesn't know is **simply absent** from the response. That isn't an error, but the cache never gets a price, so trades are rejected with "No price available" (PLAN §7).
- **Never let one bad snapshot or one failed poll kill the loop.** Log it and retry next interval. The client already retries 429 and 5xx three times with backoff.
- Run the synchronous client in `asyncio.to_thread` so the event loop (SSE, API) never blocks for up to the 10 s timeout.

### Minimal working poller

```python
import asyncio, logging, time
from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import SnapshotMarketType

log = logging.getLogger(__name__)

def pick_price(snap) -> float | None:
    for value in (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    ):
        if value:              # skips None and 0 (the day bar is zeroed right after reset)
            return float(value)
    return None

async def poll_forever(api_key: str, get_tickers, on_price, interval: float = 15.0) -> None:
    client = RESTClient(api_key=api_key)
    while True:
        tickers = [t.upper() for t in get_tickers()]
        if tickers:
            try:
                snaps = await asyncio.to_thread(
                    client.get_snapshot_all, SnapshotMarketType.STOCKS, tickers
                )
                now = time.time()
                for snap in snaps:
                    price = pick_price(snap)
                    if price is not None:
                        on_price(snap.ticker, price, now)
            except BadResponse as e:          # 401 bad key, 403 not entitled, 429 after retries
                log.error("Massive poll failed: %s", e)
            except Exception:
                log.exception("Massive poll failed")
        await asyncio.sleep(interval)
```

### Quick manual check of a key

```bash
curl -s -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,MSFT" | head -c 600
# A paid key gives "status":"OK". A Basic key gives a NOT_AUTHORIZED / entitlement error, so use grouped daily:
curl -s -H "Authorization: Bearer $MASSIVE_API_KEY" \
  "https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/2026-10-09?adjusted=true" | head -c 600
```

---

## 6. Sources

- Massive REST quickstart (auth, base URL): https://massive.com/docs/rest/quickstart
- Full Market Snapshot: https://massive.com/docs/rest/stocks/snapshots/full-market-snapshot
- Daily Market Summary (grouped daily): https://massive.com/docs/rest/stocks/aggregates/daily-market-summary
- Previous Day Bar: https://massive.com/docs/rest/stocks/aggregates/previous-day-bar
- Pricing and plan limits: https://massive.com/pricing
- Python client: https://github.com/massive-com/client-python (`massive/rest/snapshot.py`, `massive/rest/aggs.py`, `massive/rest/models/{snapshot,trades,aggs}.py`, `massive/rest/base.py`)
