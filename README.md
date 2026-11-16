# 📼 openalgo-recorder (`oar`)

A small standalone add-on that runs next to [OpenAlgo](https://github.com/marketcalls/openalgo)
and records its market data every trading day, to open Parquet files you own.
It talks to OpenAlgo only through its public API and websocket, with your API
key. It never touches OpenAlgo's code, files or databases.

Built and checked against OpenAlgo 2.0.3.3 (`f456b32`, 2026-11-13). Why it works
the way it does: [docs/RESEARCH.md](docs/RESEARCH.md). What the files contain: [DATA.md](DATA.md).

## 🎯 What it records

For each configured index (default NIFTY and SENSEX), for the nearest expiry
(configurable), the spot plus 20 strikes each side of ATM, CE and PE:

| When | What | From |
|---|---|---|
| 09:00–15:35 IST, live | every tick and 5-level bid/ask as OpenAlgo streams it (LTP, volume, OI, OHLC, buy/sell totals) | websocket, Depth mode |
| every 60 s | the option chain with bid/ask, OI, volume, IV, delta, gamma, theta, vega | `/api/v1/optionchain` |
| 15:45 IST | 1-minute and daily bars with OI for every contract seen that day, the expiry list, the day's master contract | `/api/v1/history`, `/expiry`, `/instruments` |

As ATM moves, new strikes are added to the live subscription; none are dropped
during the day. Holidays and weekends are skipped using OpenAlgo's own market
calendar.

## 🧰 Needs

- A running OpenAlgo, logged in to your broker for the day (that stays your job).
- Its API key.
- Python 3.11+ or Docker.

## 🐳 Run with Docker, next to OpenAlgo in Docker (most common)

On the OpenAlgo server:

```bash
git clone <this repo> /opt/oar && cd /opt/oar
cp .env.example .env                # keeps OPENALGO_NETWORK; the key goes in next
cp config.example.toml config.toml  # pick indices, strikes, expiries
docker compose build
docker compose run --rm --user root -v "$PWD/.env:/app/.env" oar setup   # asks for the API key (hidden), then checks
docker compose up -d
docker compose logs -f
```

oar joins OpenAlgo's Docker network (`openalgo_default` by default; set
`OPENALGO_NETWORK` in `.env` if yours differs) and reaches it as
`openalgo-web:5000` and `openalgo-web:8765`. OpenAlgo's `.env` must have
`WEBSOCKET_HOST='0.0.0.0'` (OpenAlgo's Docker installers set this) or the
websocket is unreachable from other containers.

## 💻 Run without Docker (Linux, macOS, Windows)

```bash
python -m venv .venv
.venv/bin/pip install .            # Windows: .venv\Scripts\pip install .
cp config.example.toml config.toml  # optional; built-in defaults record NIFTY + SENSEX
.venv/bin/oar setup                # asks address + API key (typing hidden), saves .env, then checks
.venv/bin/oar run
```

`oar setup` is the same on every OS. It writes `.env` next to `config.toml`
(owner-only permissions on Linux/macOS/Android), keeps any other lines in it,
never prints the key, and refuses a key that looks cut off. Every `oar`
command reads that `.env` itself; a real environment variable still wins.
Run it again to change the key (Enter keeps the saved value). For scripts:
`oar setup --key-stdin --host URL --ws-url URL [--no-check]`.

Keep it running:
- **Linux:** `deploy/oar.service` (systemd; expects `/opt/oar` and a `.venv` there).
- **Windows:** `deploy/oar-windows.ps1` registers a scheduled task that starts at
  boot and restarts on failure; output goes to `data/oar.log`.

### 🧭 Where OpenAlgo is, by deployment

| OpenAlgo runs as | `OAR_HOST` | `OAR_WS_URL` |
|---|---|---|
| Docker, oar in Docker on the same host | `http://openalgo-web:5000` | `ws://openalgo-web:8765` |
| Docker (ports on 127.0.0.1), oar native on the same host | `http://127.0.0.1:5000` | `ws://127.0.0.1:8765` |
| Local `uv run app.py` (Linux/macOS/Windows) | `http://127.0.0.1:5000` | `ws://127.0.0.1:8765` |
| Native Linux install or any server behind nginx | `https://<domain>` | `wss://<domain>/ws` |

## ⌨️ Commands

| Command | Does |
|---|---|
| `oar run` | runs forever: live capture in session, after-close jobs, every trading day |
| `oar check` | tests REST, expiry list and websocket login |
| `oar live [--until HH:MM]` | live capture now |
| `oar eod` | after-close jobs now (options only for today) |
| `oar convert [--date YYYY-MM-DD]` | rebuild a day's Parquet files from its raw files |

## 📖 Reading the data

```python
import duckdb
duckdb.sql("SELECT * FROM read_parquet('data/*/ticks.parquet', hive_partitioning=1) LIMIT 5")
```
```python
import pandas as pd
pd.read_parquet("data/date=2026-11-16/chain.parquet")
```
To CSV for Excel:
`duckdb -c "COPY (SELECT * FROM 'data/date=2026-11-16/bars.parquet') TO 'bars.csv'"`

## ⚠️ Limits to know

- Ticks and bid/ask exist only live. A day oar or OpenAlgo was down, or the
  broker was not logged in, cannot be filled in later. `manifest.json` and
  `events.parquet` show every gap, reconnect and error.
- Option bars must be fetched the same day; OpenAlgo forgets expired contracts
  the next morning.
- Ticks are what the broker streams, not every exchange trade. With Upstox, depth
  is 5 levels and IV/greeks are OpenAlgo's own Black-76 values.
- Option-chain snapshots use the broker's quote allowance, shared with anything
  else using the same OpenAlgo. Raise `chain_seconds` if you see refusals.
- Disk: roughly 0.5–1.5 GB of raw files per index per day; Parquet is several
  times smaller. Set `keep_raw = false` to delete raw files after a clean conversion.

## 🔮 Possible later additions (not built)

Index futures, 30-level depth (Upstox Plus), stock options, off-site backup,
alerts on gaps, offline IV/greeks recomputation.
