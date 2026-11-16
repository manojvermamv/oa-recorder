"""Command line.

  oar run                 run forever: live capture in session, after-close jobs, every trading day
  oar live [--until HH:MM] live capture now, until the session end (or --until)
  oar eod  [--date D]      after-close jobs now (options only work for today)
  oar convert [--date D]   rebuild a day's Parquet tables from its raw files
  oar check                test the connection to OpenAlgo (REST, option chain, websocket)
  oar setup                save the OpenAlgo address and API key to .env (key typed hidden), then check
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta

from . import RECORDER
from .api import ApiError, OpenAlgo
from .config import IST, Config, env_file, load, read_env, write_env
from .eod import eod_marker, run_eod
from .live import Live
from .store import RawWriter, convert_day

log = logging.getLogger("oar")


def _today() -> date:
    return datetime.now(IST).date()


def is_trading_day(cfg: Config, api: OpenAlgo, day: date) -> bool:
    """OpenAlgo's own calendar decides; weekdays are assumed if it cannot be reached."""
    try:
        open_ex = {x.get("exchange") for x in api.timings(day.isoformat()).get("data") or []}
    except ApiError as e:
        log.warning("market calendar unavailable (%s); assuming weekdays trade", e)
        return day.weekday() < 5
    return any(u.option_exchange in open_ex for u in cfg.underlyings)


def run_live(cfg: Config, api: OpenAlgo, until: datetime) -> None:
    session = uuid.uuid4().hex
    w = RawWriter(cfg.data_dir, until.date(), "live", session, cfg.host)
    try:
        asyncio.run(Live(cfg, api, w, until).run())
    except KeyboardInterrupt:
        pass
    finally:
        w.close()


def _sleep_until(target: datetime) -> None:
    while (left := (target - datetime.now(IST)).total_seconds()) > 0:
        time.sleep(min(left, 60))  # short naps survive clock jumps and host suspend


def run_forever(cfg: Config, api: OpenAlgo) -> None:
    log.info("%s started; OpenAlgo %s, data in %s", RECORDER, cfg.host, cfg.data_dir.resolve())
    trading: dict[date, bool] = {}
    live_done: set[date] = set()
    while True:
        now = datetime.now(IST)
        today = now.date()
        if today not in trading:
            trading[today] = is_trading_day(cfg, api, today)
            log.info("%s: %s", today, "trading day" if trading[today] else "no trading")
        tomorrow = datetime.combine(today + timedelta(days=1), cfg.session_start, IST) - timedelta(minutes=30)
        if not trading[today]:
            _sleep_until(tomorrow)
            continue
        start = datetime.combine(today, cfg.session_start, IST)
        end = datetime.combine(today, cfg.session_end, IST)
        eod_at = datetime.combine(today, cfg.eod_time, IST)
        if now < start:
            _sleep_until(start)
        elif now < end and today not in live_done:
            try:
                run_live(cfg, api, end)
                live_done.add(today)
            except Exception:  # noqa: BLE001 - keep the service alive
                log.exception("live capture failed; restarting in 10s")
                time.sleep(10)
        elif now < eod_at:
            _sleep_until(eod_at)
        elif not eod_marker(cfg, today).exists():
            try:
                if not run_eod(cfg, api, today):
                    log.warning("after-close bars not captured; retrying in 15 minutes")
                    _sleep_until(min(now + timedelta(minutes=15), tomorrow))
            except Exception:  # noqa: BLE001
                log.exception("after-close jobs failed; retrying in 15 minutes")
                _sleep_until(min(now + timedelta(minutes=15), tomorrow))
        else:
            _sleep_until(tomorrow)


def check(cfg: Config, api: OpenAlgo) -> int:
    """Connectivity test. Prints what works; exit code 0 only if all of it does."""
    from websockets.sync.client import connect

    good = True
    u = cfg.underlyings[0]
    steps = [
        ("quote", lambda: api.quotes(u.name, u.spot_exchange)["data"].get("ltp")),
        ("expiry", lambda: api.expiries(u.name, u.option_exchange)[:3]),
    ]
    for name, fn in steps:
        try:
            print(f"ok   {name}: {fn()}")
        except (ApiError, KeyError) as e:
            good = False
            print(f"FAIL {name}: {e}")
    try:
        with connect(cfg.ws_url, open_timeout=10) as ws:
            ws.send(json.dumps({"action": "authenticate", "api_key": cfg.api_key}))
            reply = json.loads(ws.recv(timeout=15))
            ok = reply.get("status") == "success"
            good &= ok
            print(f"{'ok  ' if ok else 'FAIL'} websocket: {reply.get('status')} broker={reply.get('broker')} {reply.get('message', '')}")
    except Exception as e:  # noqa: BLE001
        good = False
        print(f"FAIL websocket {cfg.ws_url}: {e}")
    return 0 if good else 1


def setup(a: argparse.Namespace) -> int:
    """Asks for what oar needs to reach OpenAlgo and saves it to .env. Works the same on every OS."""
    import getpass

    path = env_file(a.config)
    old = read_env(path)
    interactive = sys.stdin.isatty() and not a.key_stdin

    def ask(label: str, key: str, default: str, given: str | None) -> str:
        if given:
            return given
        current = old.get(key) or os.environ.get(key) or default
        if not interactive:
            return current
        return input(f"{label} [{current}]: ").strip() or current

    host = ask("OpenAlgo address", "OAR_HOST", Config.host, a.host).rstrip("/")
    ws = ask("OpenAlgo websocket", "OAR_WS_URL", Config.ws_url, a.ws_url)
    if a.key_stdin:
        key = sys.stdin.readline().strip()
    elif interactive:
        hint = " (Enter keeps the saved one)" if old.get("OAR_API_KEY") else ""
        key = getpass.getpass(f"OpenAlgo API key, typing is hidden{hint}: ").strip()
        key = key or old.get("OAR_API_KEY", "")
    else:
        key = old.get("OAR_API_KEY", "")
    if len(key) < 20:
        print(f"API key has {len(key)} characters; that looks cut off or empty. Nothing saved.")
        print("Get it from the OpenAlgo web page -> API Key.")
        return 1
    values = {"OAR_API_KEY": key}
    # Default addresses are left out of the file, so Docker Compose keeps its own (openalgo-web).
    for k, v, d in (("OAR_HOST", host, Config.host), ("OAR_WS_URL", ws, Config.ws_url)):
        if v != d or k in old:
            values[k] = v
    write_env(path, values)
    print(f"Saved to {path.resolve()} ({path.stat().st_size} bytes). The key is not shown.")
    if a.no_check:
        return 0
    for k, v in (("OAR_HOST", host), ("OAR_WS_URL", ws), ("OAR_API_KEY", key)):
        os.environ[k] = v  # the file was just written; use these values, not older ones in the environment
    cfg = load(a.config)
    print("Testing the connection to OpenAlgo...")
    return check(cfg, OpenAlgo(cfg.host, cfg.api_key, cfg.http_timeout))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="oar", description="openalgo-recorder")
    p.add_argument("--config", help="path to config.toml (default: $OAR_CONFIG or ./config.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    lp = sub.add_parser("live")
    lp.add_argument("--until", help="HH:MM IST (default: session end)")
    for name in ("eod", "convert"):
        sp = sub.add_parser(name)
        sp.add_argument("--date", type=date.fromisoformat, default=None)
    sub.add_parser("check")
    sp = sub.add_parser("setup", help="save OpenAlgo address and API key to .env")
    sp.add_argument("--host", help=f"OpenAlgo REST address (default {Config.host})")
    sp.add_argument("--ws-url", help=f"OpenAlgo websocket (default {Config.ws_url})")
    sp.add_argument("--key-stdin", action="store_true", help="read the API key from standard input (scripts)")
    sp.add_argument("--no-check", action="store_true", help="save only, do not test the connection")
    a = p.parse_args(argv)
    if a.cmd == "setup":
        return setup(a)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load(a.config)
    if not cfg.api_key and a.cmd != "convert":
        p.error("no OpenAlgo API key: run 'oar setup' (or set OAR_API_KEY)")
    api = OpenAlgo(cfg.host, cfg.api_key, cfg.http_timeout)

    if a.cmd == "run":
        run_forever(cfg, api)
    elif a.cmd == "live":
        t = cfg.session_end if not a.until else datetime.strptime(a.until, "%H:%M").time()
        run_live(cfg, api, datetime.combine(_today(), t, IST))
        convert_day(cfg.data_dir, _today(), cfg.depth_levels, keep_raw=True)
    elif a.cmd == "eod":
        return 0 if run_eod(cfg, api, a.date or _today()) else 1
    elif a.cmd == "convert":
        m = convert_day(cfg.data_dir, a.date or _today(), cfg.depth_levels, keep_raw=True)
        print(json.dumps(m, indent=2))
    elif a.cmd == "check":
        return check(cfg, api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
