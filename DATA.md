# 🗂️ Data format (schema version 1)

```
data/
  date=2026-11-16/              one folder per trading day (IST date), Hive-style
    raw/                        source of truth: gzip JSON lines, exactly as received
      live-091502-1a2b3c4d.jsonl.gz
      eod-154500-5e6f7a8b.jsonl.gz
    ticks.parquet               websocket frames, one row per frame
    chain.parquet               option-chain snapshots, one row per strike and side
    bars.parquet                1m and daily bars with OI
    expiries.parquet            expiry lists
    instruments.parquet         the day's master contract (symbol, token, lot size...)
    events.parquet              connects, disconnects, stalls, API errors, start/stop
    symbols.json                every instrument tracked that day, with its identity
    manifest.json               row counts, first/last receive times, event and problem counts
    eod.done                    present when the after-close bars were captured
```

All Parquet files are zstd-compressed and can be rebuilt from `raw/` with
`oar convert --date YYYY-MM-DD`.

## 🧾 Raw record (one JSON object per line)

| Field | Meaning |
|---|---|
| `v` | schema version (1) |
| `kind` | `tick`, `chain`, `bar`, `expiries`, `instruments` or `event` |
| `recv_ns` | when oar received it: Unix epoch nanoseconds, UTC |
| `seq` | 1, 2, 3… within one raw file; a gap means lost lines |
| `session` | id of the oar run that wrote it |
| `recorder` | `oar/<version>` |
| `source.openalgo` | OpenAlgo base URL it came from |
| `source.channel` | `ws` or `rest:/api/v1/<endpoint>` or `oar` (events) |
| `source.broker` | broker reported by OpenAlgo (ticks) |
| `meta` | what the record is about: symbol, exchange, underlying, expiry, strike, option_type, interval |
| `payload` | the frame or response body, unchanged |

## 🔗 Columns common to every table

`recv_ts` (timestamp ns, UTC), `seq`, `session`, `source`, `channel`, `broker`, `recorder`.

Instrument identity, where it applies: `symbol` (OpenAlgo format, e.g.
`NIFTY25NOV2524000CE`), `exchange` (`NFO`, `NSE_INDEX`…), `underlying`,
`expiry` (as OpenAlgo wrote it), `strike`, `option_type` (`CE`/`PE`, empty for the spot).

## ⚡ ticks

| Column | Meaning |
|---|---|
| `mode` | 1 LTP, 2 Quote, 3 Depth |
| `ltp`, `ltq` | last price, last quantity |
| `ltt` | last trade time **as the broker sent it** (seconds or ms depends on broker) |
| `src_ts` | the frame's own `timestamp` as sent (usually OpenAlgo/broker ms) |
| `volume`, `oi`, `open`, `high`, `low`, `close`, `average_price` | as sent; `close` is usually previous close |
| `total_buy_quantity`, `total_sell_quantity` | as sent |
| `bid_px_1..5`, `bid_qty_1..5`, `bid_orders_1..5`, `ask_*` | depth levels, best first |
| `raw` | the full `data` object as JSON, so nothing the broker adds is lost |

Use `recv_ts` as the reliable clock for ordering and replay; `ltt`/`src_ts`
keep the source's own times.

## ⛓️ chain

Per snapshot and leg: `underlying_ltp`, `underlying_prev_close`, `atm_strike`,
`forward_price` (used for greeks), `expiry_ts` (expiry instant, epoch s),
`server_ts` (OpenAlgo's clock, epoch s), `label` (ATM / ITMn / OTMn), `ltp`,
`bid`, `ask`, `bid_qty`, `ask_qty`, `open`, `high`, `low`, `prev_close`,
`volume`, `oi`, `lotsize`, `tick_size`, `implied_volatility` (%), `delta`,
`gamma`, `theta` (per day), `vega` (per 1% vol). Greeks are OpenAlgo's Black-76.

## 📊 bars

`interval` (`1m`, `D`), `ts` (bar start, epoch seconds as OpenAlgo returns it),
`bar_time` (same as a timestamp), `open`, `high`, `low`, `close`, `volume`, `oi`.

## 📅 expiries

`underlying`, `exchange`, `expiry` (as returned, e.g. `25-NOV-25`), `expiry_date` (date).

## 📇 instruments

`symbol`, `brsymbol`, `name`, `exchange`, `brexchange`, `token`, `expiry`,
`strike`, `lotsize`, `instrumenttype`, `tick_size`.

## 📝 events

`event` and `detail` (JSON). Events: `live_start`, `live_stop`, `ws_connected`,
`ws_disconnected`, `ws_stall`, `ws_subscribe`, `ws_error`, `ws_message`,
`symbols_added`, `api_error`, `eod_start`, `eod_stop`, `eod_aborted`.
