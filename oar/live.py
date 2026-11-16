"""Live capture during the session.

Two loops share one raw file:
  * websocket loop: authenticates with OpenAlgo's proxy, subscribes every known
    symbol (Depth mode by default) and writes every frame as received;
  * chain loop: every `chain_seconds` calls /optionchain (with IV and greeks)
    for each underlying and expiry, writes the response, and adds any strike
    that has come into the +/- strike_count window to the subscription.
Strikes are never dropped during the day, so the set only grows as ATM moves.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.client import connect

from .api import ApiError, OpenAlgo, chain_expiry
from .config import IST, Config
from .store import RawWriter, day_dir

log = logging.getLogger("oar.live")
SUB_CHUNK = 100


def pick_expiries(raw: list[str], n: int) -> list[str]:
    def key(e: str):
        try:
            return datetime.strptime(e.title(), "%d-%b-%y")
        except ValueError:
            return datetime.max
    return sorted(raw, key=key)[:n]


def symbols_file(cfg: Config, day) -> Path:
    return day_dir(cfg.data_dir, day) / "symbols.json"


class Live:
    def __init__(self, cfg: Config, api: OpenAlgo, writer: RawWriter, end: datetime):
        self.cfg = cfg
        self.api = api
        self.w = writer
        self.end = end
        self.day = end.date()
        # (symbol, exchange) -> identity written next to every tick
        self.symbols: dict[tuple[str, str], dict] = {}
        self.expiries: dict[str, list[str]] = {}
        self.ws = None
        self.last_tick = time.monotonic()
        self.ticks = 0
        f = symbols_file(cfg, self.day)
        if f.exists():  # a restart during the day keeps the morning's strikes
            for m in json.loads(f.read_text(encoding="utf-8")):
                self.symbols[(m["symbol"], m["exchange"])] = m
        for u in cfg.underlyings:
            self._add(u.name, u.spot_exchange, {"underlying": u.name, "role": "spot"})

    # -- symbol set ----------------------------------------------------------------

    def _add(self, symbol: str, exchange: str, meta: dict) -> bool:
        key = (symbol, exchange)
        if key in self.symbols:
            return False
        self.symbols[key] = {"symbol": symbol, "exchange": exchange, **meta}
        return True

    def _save_symbols(self) -> None:
        f = symbols_file(self.cfg, self.day)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self.symbols.values()), indent=1), encoding="utf-8")
        tmp.replace(f)

    async def _subscribe(self, keys) -> None:
        ws = self.ws
        keys = list(keys)
        if ws is None or not keys:
            return
        for i in range(0, len(keys), SUB_CHUNK):
            msg = {"action": "subscribe", "mode": self.cfg.ws_mode, "depth": self.cfg.depth_levels,
                   "symbols": [{"symbol": s, "exchange": e} for s, e in keys[i:i + SUB_CHUNK]]}
            await ws.send(json.dumps(msg))

    # -- loops ----------------------------------------------------------------------

    async def run(self) -> None:
        self._save_symbols()
        self.w.event("live_start", end=self.end.isoformat(), symbols=len(self.symbols))
        log.info("live capture until %s", self.end.strftime("%H:%M"))
        tasks = [asyncio.create_task(c) for c in
                 (self._ws_loop(), self._chain_loop(), self._watchdog())]
        try:
            await asyncio.sleep(max(0.0, (self.end - datetime.now(IST)).total_seconds()))
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.w.event("live_stop", ticks=self.ticks, symbols=len(self.symbols))
            self.w.flush()
            log.info("live capture stopped: %d ticks, %d symbols", self.ticks, len(self.symbols))

    async def _ws_loop(self) -> None:
        backoff = 1
        while True:
            try:
                async with connect(self.cfg.ws_url, ping_interval=20, ping_timeout=20,
                                   max_size=None, open_timeout=15) as ws:
                    await ws.send(json.dumps({"action": "authenticate", "api_key": self.cfg.api_key}))
                    reply = await self._auth_reply(ws)
                    if reply.get("status") != "success":
                        raise ConnectionError(f"auth failed: {reply}")
                    broker = reply.get("broker")
                    self.ws = ws
                    self.last_tick = time.monotonic()
                    self.w.event("ws_connected", broker=broker, user_id=reply.get("user_id"),
                                 symbols=len(self.symbols))
                    log.info("websocket connected (broker=%s), subscribing %d symbols",
                             broker, len(self.symbols))
                    await self._subscribe(self.symbols.keys())
                    backoff = 1
                    async for raw in ws:
                        recv = time.time_ns()
                        try:
                            msg = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            self.w.event("ws_bad_frame", frame=str(raw)[:500])
                            continue
                        if msg.get("type") == "market_data":
                            meta = self.symbols.get((msg.get("symbol"), msg.get("exchange")), {})
                            self.w.write("tick", msg, channel="ws", meta=meta,
                                         broker=msg.get("broker") or broker, recv_ns=recv)
                            self.ticks += 1
                            self.last_tick = time.monotonic()
                        else:
                            self._control(msg)
                    raise ConnectionError("websocket closed by server")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - every failure means reconnect
                self.ws = None
                self.w.event("ws_disconnected", error=str(e)[:500], retry_in=backoff)
                log.warning("websocket: %s (retry in %ss)", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _auth_reply(self, ws) -> dict:
        async with asyncio.timeout(15):
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("type") == "auth" or msg.get("status") == "error":
                    return msg

    def _control(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "subscribe":
            bad = [s for s in msg.get("subscriptions", []) if s.get("status") != "success"]
            self.w.event("ws_subscribe", status=msg.get("status"), failed=bad[:50],
                         failed_count=len(bad))
            if bad:
                log.warning("subscribe: %d symbol(s) refused, e.g. %s", len(bad), bad[0])
        elif msg.get("status") == "error":
            self.w.event("ws_error", message=msg)
            log.warning("websocket error: %s", msg)
        else:
            self.w.event("ws_message", message=msg)

    async def _watchdog(self) -> None:
        """No ticks for `stall_seconds` during market hours means the proxy lost the
        broker feed (e.g. after a re-login); reconnecting re-authenticates, which
        rebuilds the broker adapter, and re-subscribes."""
        while True:
            await asyncio.sleep(5)
            now = datetime.now(IST)
            if now.time() < self.cfg.market_open or self.ws is None:
                continue
            idle = time.monotonic() - self.last_tick
            if idle > self.cfg.stall_seconds:
                self.w.event("ws_stall", idle_seconds=round(idle))
                log.warning("no ticks for %ds, reconnecting", idle)
                self.last_tick = time.monotonic()
                try:
                    await self.ws.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _chain_loop(self) -> None:
        while True:
            await self._chain_round()
            self.w.flush()
            period = self.cfg.chain_seconds
            await asyncio.sleep(period - (time.time() % period))  # align to the clock

    async def _chain_round(self) -> None:
        new: list[tuple[str, str]] = []
        for u in self.cfg.underlyings:
            if not self.expiries.get(u.name):
                try:
                    raw = await asyncio.to_thread(self.api.expiries, u.name, u.option_exchange)
                    self.expiries[u.name] = pick_expiries(raw, self.cfg.expiries)
                    self.w.write("expiries", raw, channel="rest:/api/v1/expiry",
                                 meta={"underlying": u.name, "exchange": u.option_exchange})
                except ApiError as e:
                    self.w.event("api_error", endpoint="expiry", underlying=u.name, error=str(e))
                    log.warning("expiry %s: %s", u.name, e)
                    continue
            for exp in self.expiries[u.name]:
                try:
                    resp = await asyncio.to_thread(
                        self.api.option_chain, u.name, u.spot_exchange, chain_expiry(exp),
                        self.cfg.strike_count, self.cfg.with_greeks, self.cfg.interest_rate)
                except ApiError as e:
                    self.w.event("api_error", endpoint="optionchain", underlying=u.name,
                                 expiry=exp, error=str(e))
                    log.warning("optionchain %s %s: %s", u.name, exp, e)
                    continue
                self.w.write("chain", resp, channel="rest:/api/v1/optionchain",
                             meta={"underlying": u.name, "expiry": resp.get("expiry_date"),
                                   "option_exchange": u.option_exchange,
                                   "spot_exchange": u.spot_exchange})
                for item in resp.get("chain") or []:
                    for ot in ("ce", "pe"):
                        leg = item.get(ot)
                        if leg and self._add(leg["symbol"], u.option_exchange, {
                                "underlying": u.name, "expiry": resp.get("expiry_date"),
                                "strike": item.get("strike"), "option_type": ot.upper()}):
                            new.append((leg["symbol"], u.option_exchange))
        if new:
            self._save_symbols()
            self.w.event("symbols_added", count=len(new), total=len(self.symbols))
            log.info("tracking %d new strike(s), %d symbols in total", len(new), len(self.symbols))
            await self._subscribe(new)
