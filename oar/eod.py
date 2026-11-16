"""After-close capture: bars with OI for every contract touched today, the expiry
lists and today's master contract. Must run the same day: OpenAlgo forgets
expired contracts when it reloads the master contract the next morning."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date

from .api import ApiError, OpenAlgo, chain_expiry
from .config import Config
from .live import pick_expiries, symbols_file
from .store import RawWriter, convert_day, day_dir

log = logging.getLogger("oar.eod")


def eod_marker(cfg: Config, day: date):
    return day_dir(cfg.data_dir, day) / "eod.done"


def _retry(fn, *args, tries: int = 3):
    for n in range(tries):
        try:
            return fn(*args)
        except ApiError:
            if n == tries - 1:
                raise
            time.sleep(2 * (n + 1))


def run_eod(cfg: Config, api: OpenAlgo, day: date) -> bool:
    """Returns True when the day's bars were captured (marker written)."""
    w = RawWriter(cfg.data_dir, day, "eod", uuid.uuid4().hex, cfg.host)
    w.event("eod_start")
    ok = fail = 0
    try:
        symbols: dict[tuple[str, str], dict] = {}
        f = symbols_file(cfg, day)
        if f.exists():
            for m in json.loads(f.read_text(encoding="utf-8")):
                symbols[(m["symbol"], m["exchange"])] = m

        for u in cfg.underlyings:
            symbols.setdefault((u.name, u.spot_exchange),
                               {"symbol": u.name, "exchange": u.spot_exchange,
                                "underlying": u.name, "role": "spot"})
            try:
                raw = _retry(api.expiries, u.name, u.option_exchange)
                w.write("expiries", raw, channel="rest:/api/v1/expiry",
                        meta={"underlying": u.name, "exchange": u.option_exchange})
            except ApiError as e:
                w.event("api_error", endpoint="expiry", underlying=u.name, error=str(e))
                continue
            if any(m.get("underlying") == u.name and m.get("option_type") for m in symbols.values()):
                continue
            # Live capture did not run for this underlying today: take the window now.
            for exp in pick_expiries(raw, cfg.expiries):
                try:
                    resp = _retry(api.option_chain, u.name, u.spot_exchange, chain_expiry(exp),
                                  cfg.strike_count, cfg.with_greeks, cfg.interest_rate)
                except ApiError as e:
                    w.event("api_error", endpoint="optionchain", underlying=u.name, error=str(e))
                    continue
                w.write("chain", resp, channel="rest:/api/v1/optionchain",
                        meta={"underlying": u.name, "expiry": resp.get("expiry_date"),
                              "option_exchange": u.option_exchange,
                              "spot_exchange": u.spot_exchange})
                for item in resp.get("chain") or []:
                    for ot in ("ce", "pe"):
                        leg = item.get(ot)
                        if leg:
                            symbols.setdefault((leg["symbol"], u.option_exchange), {
                                "symbol": leg["symbol"], "exchange": u.option_exchange,
                                "underlying": u.name, "expiry": resp.get("expiry_date"),
                                "strike": item.get("strike"), "option_type": ot.upper()})

        d = day.isoformat()
        log.info("fetching %s bars for %d symbols", "/".join(cfg.history_intervals), len(symbols))
        jobs = [(sym, ex, meta, iv) for (sym, ex), meta in sorted(symbols.items())
                for iv in cfg.history_intervals]
        for sym, ex, meta, interval in jobs:
            try:
                resp = _retry(api.history, sym, ex, interval, d, d)
                w.write("bar", resp, channel="rest:/api/v1/history",
                        meta={**meta, "interval": interval})
                ok += 1
            except ApiError as e:
                fail += 1
                w.event("api_error", endpoint="history", symbol=sym, exchange=ex,
                        interval=interval, error=str(e))
                log.warning("history %s %s %s: %s", sym, ex, interval, e)
                if fail >= 5 and ok == 0:  # broker most likely logged out; try again later
                    w.event("eod_aborted", reason="first history calls all failed")
                    log.warning("first history calls all failed; giving up for now")
                    break

        if cfg.save_instruments:
            for ex in cfg.source_exchanges:
                try:
                    w.write("instruments", _retry(api.instruments, ex),
                            channel="rest:/api/v1/instruments", meta={"exchange": ex})
                except ApiError as e:
                    w.event("api_error", endpoint="instruments", exchange=ex, error=str(e))
        w.event("eod_stop", history_ok=ok, history_failed=fail)
    finally:
        w.close()

    manifest = convert_day(cfg.data_dir, day, cfg.depth_levels, cfg.keep_raw)
    log.info("bars ok=%d failed=%d; tables: %s", ok, fail,
             {t: v["rows"] for t, v in manifest["tables"].items()})
    if ok:
        eod_marker(cfg, day).write_text(f"history_ok={ok} history_failed={fail}\n")
        return True
    return False
