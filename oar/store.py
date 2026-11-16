"""Storage.

During capture every record is appended, as received, to a gzip JSON-lines file
under  <data_dir>/date=YYYY-MM-DD/raw/ . Those files are the source of truth:
crash-safe (flushed every second), human readable, and replayable.

`convert_day` turns a day's raw files into typed Parquet tables next to them and
writes manifest.json. It can be re-run at any time; it always rebuilds from raw.
"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from . import RECORDER
from .config import IST

SCHEMA_VERSION = 1


def day_dir(data_dir: Path, day: date) -> Path:
    return Path(data_dir) / f"date={day.isoformat()}"


def now_ns() -> int:
    return time.time_ns()


class RawWriter:
    """Append-only gzip JSON-lines writer. One file per process run, so a crash
    can only damage the unflushed tail of that one file."""

    def __init__(self, data_dir: Path, day: date, group: str, session: str, source: str):
        self.dir = day_dir(data_dir, day) / "raw"
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(IST).strftime("%H%M%S")
        self.path = self.dir / f"{group}-{stamp}-{session[:8]}.jsonl.gz"
        self._f = gzip.open(self.path, "ab", compresslevel=6)
        self.session = session
        self.source = source
        self.seq = 0
        self._last_flush = time.monotonic()
        self.counts: Counter = Counter()

    def write(self, kind: str, payload, channel: str, meta: dict | None = None,
              broker: str | None = None, recv_ns: int | None = None) -> None:
        self.seq += 1
        rec = {
            "v": SCHEMA_VERSION,
            "kind": kind,
            "recv_ns": recv_ns or now_ns(),
            "seq": self.seq,
            "session": self.session,
            "recorder": RECORDER,
            "source": {"openalgo": self.source, "channel": channel, "broker": broker},
            "meta": meta or {},
            "payload": payload,
        }
        self._f.write(json.dumps(rec, separators=(",", ":"), default=str).encode() + b"\n")
        self.counts[kind] += 1
        if time.monotonic() - self._last_flush >= 1.0:
            self.flush()

    def event(self, name: str, **detail) -> None:
        self.write("event", {"event": name, **detail}, channel="oar")

    def flush(self) -> None:
        self._f.flush()  # gzip sync flush: everything so far is readable after a crash
        self._last_flush = time.monotonic()

    def close(self) -> None:
        self._f.close()


def read_raw(path: Path, problems: Counter | None = None):
    """Yield records from one raw file, tolerating a truncated tail."""
    try:
        with gzip.open(path, "rb") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    if problems is not None:
                        problems["bad_line"] += 1
    except (EOFError, gzip.BadGzipFile, zlib.error):
        if problems is not None:
            problems["truncated_file"] += 1


# --- flattening -----------------------------------------------------------------

def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return None if v is None or v == "" else int(float(v))
    except (TypeError, ValueError):
        return None


def _s(v):
    return None if v is None else str(v)


TS = pa.timestamp("ns", tz="UTC")
COMMON = [
    ("recv_ts", TS), ("seq", pa.int64()), ("session", pa.string()),
    ("source", pa.string()), ("channel", pa.string()), ("broker", pa.string()),
    ("recorder", pa.string()),
]
IDENT = [
    ("symbol", pa.string()), ("exchange", pa.string()), ("underlying", pa.string()),
    ("expiry", pa.string()), ("strike", pa.float64()), ("option_type", pa.string()),
]


def _common(r: dict) -> dict:
    src = r.get("source") or {}
    return {
        "recv_ts": r["recv_ns"], "seq": r.get("seq"), "session": r.get("session"),
        "source": src.get("openalgo"), "channel": src.get("channel"),
        "broker": src.get("broker"), "recorder": r.get("recorder"),
    }


def _ident(meta: dict, symbol=None, exchange=None) -> dict:
    return {
        "symbol": symbol or meta.get("symbol"), "exchange": exchange or meta.get("exchange"),
        "underlying": meta.get("underlying"), "expiry": meta.get("expiry"),
        "strike": _f(meta.get("strike")), "option_type": meta.get("option_type"),
    }


def tick_schema(levels: int) -> pa.Schema:
    cols = COMMON + IDENT + [
        ("mode", pa.int8()), ("ltp", pa.float64()), ("ltq", pa.int64()),
        ("ltt", pa.int64()), ("src_ts", pa.int64()), ("volume", pa.int64()),
        ("oi", pa.float64()), ("open", pa.float64()), ("high", pa.float64()),
        ("low", pa.float64()), ("close", pa.float64()), ("average_price", pa.float64()),
        ("total_buy_quantity", pa.int64()), ("total_sell_quantity", pa.int64()),
    ]
    for side in ("bid", "ask"):
        for n in range(1, levels + 1):
            cols += [(f"{side}_px_{n}", pa.float64()), (f"{side}_qty_{n}", pa.int64()),
                     (f"{side}_orders_{n}", pa.int64())]
    cols.append(("raw", pa.string()))
    return pa.schema(cols)


def tick_rows(r: dict, levels: int):
    frame = r["payload"]
    d = frame.get("data") or {}
    row = _common(r) | _ident(r.get("meta") or {}, frame.get("symbol"), frame.get("exchange"))
    row["broker"] = row["broker"] or frame.get("broker")
    row |= {
        "mode": _i(frame.get("mode")), "ltp": _f(d.get("ltp")),
        "ltq": _i(d.get("ltq", d.get("last_quantity", d.get("last_trade_quantity")))),
        "ltt": _i(d.get("ltt")), "src_ts": _i(d.get("timestamp")),
        "volume": _i(d.get("volume")), "oi": _f(d.get("oi", d.get("open_interest"))),
        "open": _f(d.get("open")), "high": _f(d.get("high")), "low": _f(d.get("low")),
        "close": _f(d.get("close")), "average_price": _f(d.get("average_price")),
        "total_buy_quantity": _i(d.get("total_buy_quantity")),
        "total_sell_quantity": _i(d.get("total_sell_quantity")),
        "raw": json.dumps(d, separators=(",", ":")),
    }
    depth = d.get("depth") or {}
    for side, key in (("bid", "buy"), ("ask", "sell")):
        lv = depth.get(key) or []
        for n in range(1, levels + 1):
            x = lv[n - 1] if n <= len(lv) and isinstance(lv[n - 1], dict) else {}
            row[f"{side}_px_{n}"] = _f(x.get("price"))
            row[f"{side}_qty_{n}"] = _i(x.get("quantity"))
            row[f"{side}_orders_{n}"] = _i(x.get("orders"))
    yield row


CHAIN_SCHEMA = pa.schema(COMMON + IDENT + [
    ("underlying_ltp", pa.float64()), ("underlying_prev_close", pa.float64()),
    ("atm_strike", pa.float64()), ("forward_price", pa.float64()),
    ("expiry_ts", pa.int64()), ("server_ts", pa.int64()), ("label", pa.string()),
    ("ltp", pa.float64()), ("bid", pa.float64()), ("ask", pa.float64()),
    ("bid_qty", pa.int64()), ("ask_qty", pa.int64()), ("open", pa.float64()),
    ("high", pa.float64()), ("low", pa.float64()), ("prev_close", pa.float64()),
    ("volume", pa.int64()), ("oi", pa.float64()), ("lotsize", pa.int64()),
    ("tick_size", pa.float64()), ("implied_volatility", pa.float64()),
    ("delta", pa.float64()), ("gamma", pa.float64()), ("theta", pa.float64()),
    ("vega", pa.float64()),
])


def chain_rows(r: dict, levels: int = 0):
    p = r["payload"]
    meta = r.get("meta") or {}
    base = _common(r) | {
        "underlying": p.get("underlying") or meta.get("underlying"),
        "expiry": p.get("expiry_date") or meta.get("expiry"),
        "exchange": meta.get("option_exchange"),
        "underlying_ltp": _f(p.get("underlying_ltp")),
        "underlying_prev_close": _f(p.get("underlying_prev_close")),
        "atm_strike": _f(p.get("atm_strike")), "forward_price": _f(p.get("forward_price")),
        "expiry_ts": _i(p.get("expiry_ts")), "server_ts": _i(p.get("server_ts")),
    }
    for item in p.get("chain") or []:
        for ot in ("ce", "pe"):
            leg = item.get(ot)
            if not leg:
                continue
            yield base | {
                "symbol": leg.get("symbol"), "strike": _f(item.get("strike")),
                "option_type": ot.upper(), "label": leg.get("label"),
                "ltp": _f(leg.get("ltp")), "bid": _f(leg.get("bid")), "ask": _f(leg.get("ask")),
                "bid_qty": _i(leg.get("bid_qty")), "ask_qty": _i(leg.get("ask_qty")),
                "open": _f(leg.get("open")), "high": _f(leg.get("high")),
                "low": _f(leg.get("low")), "prev_close": _f(leg.get("prev_close")),
                "volume": _i(leg.get("volume")), "oi": _f(leg.get("oi")),
                "lotsize": _i(leg.get("lotsize")), "tick_size": _f(leg.get("tick_size")),
                "implied_volatility": _f(leg.get("implied_volatility")),
                "delta": _f(leg.get("delta")), "gamma": _f(leg.get("gamma")),
                "theta": _f(leg.get("theta")), "vega": _f(leg.get("vega")),
            }


BAR_SCHEMA = pa.schema(COMMON + IDENT + [
    ("interval", pa.string()), ("ts", pa.int64()), ("bar_time", pa.timestamp("s", tz="UTC")),
    ("open", pa.float64()), ("high", pa.float64()), ("low", pa.float64()),
    ("close", pa.float64()), ("volume", pa.int64()), ("oi", pa.float64()),
])


def bar_rows(r: dict, levels: int = 0):
    meta = r.get("meta") or {}
    base = _common(r) | _ident(meta) | {"interval": meta.get("interval")}
    for c in (r["payload"] or {}).get("data") or []:
        ts = _i(c.get("timestamp"))
        yield base | {
            "ts": ts, "bar_time": ts, "open": _f(c.get("open")), "high": _f(c.get("high")),
            "low": _f(c.get("low")), "close": _f(c.get("close")),
            "volume": _i(c.get("volume")), "oi": _f(c.get("oi")),
        }


INSTRUMENT_SCHEMA = pa.schema(COMMON + [
    ("symbol", pa.string()), ("brsymbol", pa.string()), ("name", pa.string()),
    ("exchange", pa.string()), ("brexchange", pa.string()), ("token", pa.string()),
    ("expiry", pa.string()), ("strike", pa.float64()), ("lotsize", pa.int64()),
    ("instrumenttype", pa.string()), ("tick_size", pa.float64()),
])


def instrument_rows(r: dict, levels: int = 0):
    base = _common(r)
    for x in (r["payload"] or {}).get("data") or []:
        yield base | {
            "symbol": _s(x.get("symbol")), "brsymbol": _s(x.get("brsymbol")),
            "name": _s(x.get("name")), "exchange": _s(x.get("exchange")),
            "brexchange": _s(x.get("brexchange")), "token": _s(x.get("token")),
            "expiry": _s(x.get("expiry")), "strike": _f(x.get("strike")),
            "lotsize": _i(x.get("lotsize")), "instrumenttype": _s(x.get("instrumenttype")),
            "tick_size": _f(x.get("tick_size")),
        }


EXPIRY_SCHEMA = pa.schema(COMMON + [
    ("underlying", pa.string()), ("exchange", pa.string()), ("expiry", pa.string()),
    ("expiry_date", pa.date32()),
])


def expiry_rows(r: dict, levels: int = 0):
    meta = r.get("meta") or {}
    for e in r["payload"] or []:
        try:
            d = datetime.strptime(e.title(), "%d-%b-%y").date()
        except ValueError:
            d = None
        yield _common(r) | {"underlying": meta.get("underlying"),
                            "exchange": meta.get("exchange"), "expiry": e, "expiry_date": d}


EVENT_SCHEMA = pa.schema(COMMON + [("event", pa.string()), ("detail", pa.string())])


def event_rows(r: dict, levels: int = 0):
    p = dict(r["payload"] or {})
    name = p.pop("event", None)
    yield _common(r) | {"event": name, "detail": json.dumps(p, default=str)}


# kind -> (output table, schema factory, row function)
TABLES = {
    "tick": ("ticks", tick_schema, tick_rows),
    "chain": ("chain", lambda lv: CHAIN_SCHEMA, chain_rows),
    "bar": ("bars", lambda lv: BAR_SCHEMA, bar_rows),
    "instruments": ("instruments", lambda lv: INSTRUMENT_SCHEMA, instrument_rows),
    "expiries": ("expiries", lambda lv: EXPIRY_SCHEMA, expiry_rows),
    "event": ("events", lambda lv: EVENT_SCHEMA, event_rows),
}


def convert_day(data_dir: Path, day: date, levels: int = 5, keep_raw: bool = True) -> dict:
    """Rebuild all Parquet tables for one day from its raw files. Returns the manifest."""
    ddir = day_dir(data_dir, day)
    raw_files = sorted((ddir / "raw").glob("*.jsonl.gz"))
    problems: Counter = Counter()
    writers: dict[str, pq.ParquetWriter] = {}
    buffers: dict[str, list] = {}
    stats: dict[str, dict] = {}
    events: Counter = Counter()
    sources: set = set()

    def flush(table: str, schema: pa.Schema):
        rows = buffers.get(table)
        if not rows:
            return
        if table not in writers:
            writers[table] = pq.ParquetWriter(ddir / f"{table}.parquet.tmp", schema,
                                              compression="zstd")
        writers[table].write_table(pa.Table.from_pylist(rows, schema=schema))
        buffers[table] = []

    schemas = {kind: (t, make(levels), fn) for kind, (t, make, fn) in TABLES.items()}
    try:
        for path in raw_files:
            for r in read_raw(path, problems):
                spec = schemas.get(r.get("kind"))
                if spec is None:
                    problems["unknown_kind"] += 1
                    continue
                table, schema, fn = spec
                sources.add((r.get("source") or {}).get("openalgo"))
                if r["kind"] == "event":
                    events[(r.get("payload") or {}).get("event")] += 1
                st = stats.setdefault(table, {"rows": 0, "records": 0,
                                              "first_recv": r["recv_ns"], "last_recv": r["recv_ns"]})
                st["records"] += 1
                st["first_recv"] = min(st["first_recv"], r["recv_ns"])
                st["last_recv"] = max(st["last_recv"], r["recv_ns"])
                for row in fn(r, levels):
                    buffers.setdefault(table, []).append(row)
                    st["rows"] += 1
                if len(buffers.get(table, ())) >= 50_000:
                    flush(table, schema)
        for kind, (table, schema, _) in schemas.items():
            flush(table, schema)
    finally:
        for w in writers.values():
            w.close()
    for table in writers:
        (ddir / f"{table}.parquet.tmp").replace(ddir / f"{table}.parquet")

    def iso(ns):
        return datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat()

    manifest = {
        "date": day.isoformat(),
        "recorder": RECORDER,
        "schema_version": SCHEMA_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sources": sorted(s for s in sources if s),
        "raw_files": [p.name for p in raw_files],
        "tables": {t: {"rows": s["rows"], "records": s["records"],
                       "first_recv": iso(s["first_recv"]), "last_recv": iso(s["last_recv"])}
                   for t, s in sorted(stats.items())},
        "events": dict(events),
        "problems": dict(problems),
    }
    (ddir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not keep_raw and not problems:
        for p in raw_files:
            p.unlink()
    return manifest
