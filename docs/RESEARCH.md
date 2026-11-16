# 🔬 openalgo-recorder (`oar`): research findings

Researched on 2026-11-13 against the OpenAlgo source cloned that day:
`marketcalls/openalgo` @ `f456b32`, version 2.0.3.3, in `_ref/openalgo/`.
Every finding below comes from that code. Paths are relative to `_ref/openalgo/`.
Written before anything was built.

## 💬 0. Original request (as given by the owner, 2026-11-13)

```text
My recommended Tool/Service Name is `openalgo-recorder` & shorthand name is `oar`.

Read-Only Directories for 'AutonomousTrading' Project Context:
- "C:\Users\Manoj\Desktop\Office_2016\OA_NEW"
- "C:\Users\Manoj\Desktop\Office_2016\OA"
- "C:\Users\Manoj\Desktop\Office_2016\AutonomousTradingArchitect"


My goal

I don't want this to depend on my AutonomousTrading project in any way. I want to capture and store all market data myself, so I can use it later for any purpose (for example, my AutonomousTrading project, but not only that). This is a chance to start capturing everything described below from the day it's deployed, and keep it running every day.

What I want built

A simple, direct, minimal, standalone tool or service that runs alongside OpenAlgo as an external add-on, not inside it. It should keep track of my running OpenAlgo instance and keep saving all market data every day.

It must support every way the latest OpenAlgo release can be deployed: running locally on Unix/Linux, running locally on Windows, running in Docker and other ways also. My own setup is OpenAlgo in Docker on my server (<server name / ssh host — my old one, debian-oa, is gone>), so that case must work first, but none of the others may be left out.

What data to capture (All things Must be configurable via tool/service)

For each spot (index) I request: the spot itself, plus its option strikes 20 strikes on each side of the at-the-money strike (the "20 offset" range), CE and PE both. For each of these, capture all the market data available: ticks, OHLCV bars, bid/ask (market depth), and anything more OpenAlgo can provide, such as open interest, IV and Greeks, the option chain, expiries and more.

How to store it

Store everything in a standard, well-documented, open format, so it's usable for any purpose: machine learning, reinforcement learning, and any AI or agentic trading framework. It must be easy to feed both automatically (a program reading it directly) and manually (me opening or exporting it). Every record should say clearly what it is, when it happened, when it was received, and where it came from, so it can be trusted and replayed later.

Build it from OpenAlgo's real, latest code

First, clone the latest OpenAlgo repository and use it as the baseline. Build everything against that actual code, not from memory, old docs or assumptions. Whenever you need to know how OpenAlgo gives out data, check its codebase directly: both the public ways (its documented APIs and websocket) and the internal ways it supports (its services, database, caches and download features). If OpenAlgo's code says something works a certain way, trust the code over anything else.

Research first, before building

Using that cloned code, research the best way to get all of this data. In particular:
- Whether everything can be downloaded in one shot after market close, through OpenAlgo's internal services, its database, its caches, its download services or its APIs.
- What data is only available live during the session (ticks, bid/ask) and must be captured as it happens, versus what can be fetched afterwards from history.
- Your own better proposal for capturing all the market data, if you find a better way than mine.

Come back with what you found and your recommended approach, with its trade-offs, before building anything.

Keep it simple

Don't over-engineer the implementation. Build only what's needed to capture and store this data reliably: no extra layers, frameworks or features I didn't ask for. If something is optional, leave it out and mention it as a possible later addition.
```

## 📦 1. What OpenAlgo offers, and what it keeps

| Data | Live only, or fetchable later? | How to get it |
|---|---|---|
| Ticks (LTP, last trade qty/time, volume, avg price, buy/sell totals, OI) | **Live only.** Not stored anywhere in OpenAlgo; there is no tick table in any database (`database/`, `services/market_data_service.py` keeps only the latest value in memory). | WebSocket proxy, port 8765 |
| Market depth (bid/ask, 5 levels) | **Live only.** Same as ticks. | WebSocket, Depth mode (3) |
| Option chain with IV and greeks (delta, gamma, theta, vega) | **Live only.** Computed on request from live quotes (`services/option_chain_service.py`); no history kept. | `POST /api/v1/optionchain` with `strike_count:20`, `with_greeks:true` |
| 1-minute OHLCV + OI bars | **Fetchable after close**, but only while the contract is still listed (see section 2). | `POST /api/v1/history` |
| Daily bars | Fetchable after close, years back for live contracts. | `POST /api/v1/history`, interval `D` |
| Master contract (every symbol, token, lot size, tick size, expiry, strike) | Today's list only; replaced every morning. | `GET /api/v1/instruments?exchange=NFO&format=json` |
| Expiry list | Future expiries only. | `POST /api/v1/expiry` |
| Market timings and holidays | Local calendar. | `POST /api/v1/market/timings`, `/market/holidays` |

### ❓ Can everything be downloaded in one shot after close?

**No.** Only 1-minute and daily bars (with OI) can. Ticks, depth, and the
intraday evolution of the option chain, IV and greeks are never stored by
OpenAlgo, so they must be recorded as they happen.

Internal routes checked and rejected:

- **Historify (DuckDB, `db/historify.duckdb`)** stores only 1m and daily OHLCV+OI
  pulled from the same broker history API (`database/historify_db.py:231-245`,
  `services/historify_service.py:292-357`). It adds nothing the REST history call
  does not give, its scheduler downloads only a watchlist set up in the browser,
  its control routes need a browser session cookie (`blueprints/historify.py`),
  and opening the DuckDB file from another process can make OpenAlgo's own
  writes fail (`historify_db.py:121-136`).
- **ZeroMQ bus (5555)** is internal, unversioned, bound to 127.0.0.1 and cannot
  take a second subscriber (`docs/websocket-architecture.md:24`,
  `websocket_proxy/server.py:115-134`, `start.sh:262-264`).
- **Reading OpenAlgo's SQLite/DuckDB files directly** would tie the recorder to
  OpenAlgo's internal schema, which you asked to avoid.

So the recorder uses only the **public, API-key interfaces**: REST `/api/v1/*`
and the WebSocket proxy. That is also what keeps it working across every way
OpenAlgo is deployed.

## 🧱 2. Facts that shape the design

1. **Expired contracts are gone for good.** Every history call checks the symbol
   against the master contract table (`services/history_service.py:73-78`), and
   that table is wiped and reloaded each morning after 08:00 IST
   (`utils/auth_utils.py:36-137`). The Upstox adapter has no expired-instrument
   call (`broker/upstox/api/data.py:132-165`). **Option 1m bars must be pulled
   the same day, after close, every day** — including expiry day.
2. **Upstox depth is 5 levels.** OpenAlgo maps Depth to Upstox `full`; the
   30-level feed is deliberately not used (`broker/upstox/streaming/upstox_adapter.py:568-587`).
3. **Upstox greeks on the feed are dropped.** Upstox sends option greeks in its
   full feed, but OpenAlgo's adapter does not pass them on. IV/greeks come only
   from OpenAlgo's own Black-76 calculation via `/optionchain` or
   `/multioptiongreeks` (`services/option_greeks_service.py`).
4. **Ticks are not lossless.** OpenAlgo's docs say the feed is "not a lossless
   exchange-tick recorder" (`docs/websocket-quote-feed.md:108-110`). Upstox sends
   snapshots, not every exchange trade. We record exactly what arrives.
5. **No replay on reconnect.** After a broker re-login (03:00 IST token rollover,
   or a fresh login) the proxy drops the broker feed silently and tells clients
   nothing (`websocket_proxy/server.py:1766-1862`). The recorder must notice the
   silence, re-authenticate and re-subscribe.
6. **`/api/v1/ping` lies after 03:00.** It answers "pong" without contacting the
   broker (`services/ping_service.py`). The recorder checks readiness with a real
   quote call instead.
7. **Upstox throttles quotes.** Your own field notes (17 Aug 2026) measured 17%
   refusals at ~52 quote calls/minute; each OpenAlgo quote costs two Upstox
   calls. Option-chain snapshots share that budget with your trading project, so
   their interval must be modest and configurable.
8. **Capacity is fine.** ~83 symbols per index against a limit of 1000 per
   connection, 3 connections (`websocket_proxy/base_adapter.py:24-32`). The
   recorder joins OpenAlgo's shared broker connection; it does not open a new
   Upstox socket.
9. **Timestamps differ by broker.** `timestamp` is usually the local receive time
   in ms; `ltt` may be seconds or ms depending on broker and mode. The recorder
   keeps every field as received and adds its own UTC receive time.
10. **Expiry formats differ between endpoints.** `/expiry` returns `30-DEC-25`;
    `/optionchain` wants `30DEC25`.
11. **History timestamps** are epoch seconds (`services/history_service.py`).
12. **History pacing.** OpenAlgo spaces broker history calls ~0.35 s apart, so
    ~83 contracts take about 30 s per index.

## 🌐 3. Reaching OpenAlgo in each deployment

| Deployment | REST | WebSocket |
|---|---|---|
| Docker, repo `docker-compose.yaml` (container `openalgo-web`) | `http://openalgo-web:5000` on the same Docker network | `ws://openalgo-web:8765` (needs `WEBSOCKET_HOST=0.0.0.0`, which `start.sh` sets) |
| Docker via `install/install-docker.sh` (ports on 127.0.0.1 only, nginx in front) | join its Docker network, or host networking `http://127.0.0.1:5000`, or `https://<domain>/api/v1` | `ws://127.0.0.1:8765` or `wss://<domain>/ws` |
| Docker Desktop `docker-run.sh/.bat` | `http://host.docker.internal:5000` or `http://localhost:5000` | `ws://…:8765` |
| Native Linux `install/install.sh` (gunicorn on a unix socket, nginx) | `https://<domain>/api/v1` | `wss://<domain>/ws` |
| Local Linux / macOS / Windows `uv run app.py` | `http://127.0.0.1:5000` | `ws://127.0.0.1:8765` |

Two settings cover every case: `OAR_HOST` (REST base URL) and `OAR_WS_URL`.

## ✅ 4. Recommended approach

One small Python process, three jobs, all through the public API:

1. **Live recorder (09:00–15:35 IST on trading days).** WebSocket, Depth mode,
   for each configured index: the spot plus 20 strikes each side of ATM, CE and
   PE, for each configured expiry. When ATM moves, new strikes are added; strikes
   are never dropped during the day. Every frame is written as received.
2. **Option-chain snapshots (every N seconds, default 60).** `/optionchain` with
   `strike_count:20, with_greeks:true`. Gives bid/ask, OI, volume, IV and greeks
   for the whole window in one call per index and expiry.
3. **After close (about 15:45 IST).** 1m and daily bars with OI for every
   contract touched that day, the day's master contract for the relevant
   exchanges, and the expiry list. Then a per-day manifest (counts, gaps,
   reconnects, errors).

**Storage:** one folder per day, Parquet files (Apache Parquet: open, typed,
compressed; read by pandas, polars, DuckDB, Spark, PyTorch/HF datasets; opens in
Excel via a one-line DuckDB/CSV export). Live data is first appended to
compressed JSON-lines (crash-safe, human readable), then converted to Parquet at
end of day. Every row carries: `kind`, `symbol`, `exchange`, `underlying`,
`expiry`, `strike`, `option_type`, the event time as the source gave it, the
recorder's UTC receive time (ns), the source (OpenAlgo URL, broker, channel or
endpoint), recorder version and a per-session sequence number. A `DATA.md` will
document every column.

**Runs on:** Docker (a compose file that sits next to OpenAlgo's), and plain
`python -m oar` on Linux/macOS/Windows, with a systemd unit and a Windows Task
Scheduler example. Market hours and holidays come from OpenAlgo's own calendar.

### ⚖️ Trade-offs

- Ticks and depth before the recorder's first deployment can never be recovered.
- If OpenAlgo is not logged in to the broker, nothing live is captured that
  day; the manifest records the gap. Daily broker login stays your job.
- Snapshots spend Upstox quote budget shared with your trading project.
- IV/greeks are OpenAlgo's Black-76 values, not the broker's.

### 🔮 Left out (possible later additions)

- Index futures contracts, 30-level depth (Upstox Plus only), stock options.
- Off-site backup/sync of the data folder.
- Recomputing IV/greeks offline from recorded prices instead of snapshots.
- Alerts (Telegram/email) when a day's capture has gaps.
