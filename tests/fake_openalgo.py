"""A stand-in OpenAlgo for tests: REST + websocket, shaped like OpenAlgo 2.0.3.3's
responses (services/option_chain_service.py, websocket_proxy/server.py)."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve

KEY = "test-key-0123456789abcdef0123456789abcdef"


class State:
    def __init__(self):
        self.chain_calls = 0
        self.history_calls = 0
        self.atm_moves_after = 1  # ATM shifts up one strike after the first chain call
        self.ws_connections = 0
        self.history_down = False  # every history call fails, as when the broker is logged out
        self.drop_ws_after = None  # seconds: server closes the first connection to test reconnect


def chain(state: State, body: dict) -> dict:
    state.chain_calls += 1
    atm = 24000 if state.chain_calls <= state.atm_moves_after else 24050
    n = int(body.get("strike_count", 20))
    exp = body["expiry_date"]
    rows = []
    for k in range(-n, n + 1):
        strike = atm + 50 * k
        leg = lambda ot: {  # noqa: E731
            "symbol": f"NIFTY{exp}{strike}{ot}", "label": "ATM" if k == 0 else f"X{abs(k)}",
            "ltp": 100.5, "bid": 100.0, "ask": 101.0, "bid_qty": 75, "ask_qty": 150,
            "open": 90, "high": 110, "low": 85, "prev_close": 95, "volume": 12345,
            "oi": 67890, "lotsize": 75, "tick_size": 0.05, "implied_volatility": 12.3,
            "delta": 0.5, "gamma": 0.001, "theta": -5.1, "vega": 10.2}
        rows.append({"strike": float(strike), "ce": leg("CE"), "pe": leg("PE")})
    return {"status": "success", "underlying": "NIFTY", "underlying_ltp": atm + 3,
            "underlying_prev_close": 23900, "expiry_date": exp, "expiry_ts": 1795000000,
            "server_ts": int(time.time()), "atm_strike": float(atm), "quotes_included": True,
            "greeks_included": True, "forward_price": atm + 10.0, "chain": rows}


def make_handler(state: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("apikey") != KEY:
                return self._send(403, {"status": "error", "message": "Invalid openalgo apikey"})
            if u.path == "/api/v1/instruments":
                return self._send(200, {"status": "success", "data": [
                    {"symbol": "NIFTY25NOV2624000CE", "brsymbol": "X", "name": "NIFTY",
                     "exchange": q["exchange"], "brexchange": "NSE_FO", "token": "NSE_FO|1",
                     "expiry": "25-NOV-26", "strike": 24000.0, "lotsize": 75,
                     "instrumenttype": "CE", "tick_size": 0.05}]})
            self._send(404, {"status": "error", "message": "not found"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("apikey") != KEY:
                return self._send(403, {"status": "error", "message": "Invalid openalgo apikey"})
            p = urlparse(self.path).path
            if p == "/api/v1/quotes":
                return self._send(200, {"status": "success", "data": {"ltp": 24003}})
            if p == "/api/v1/expiry":
                return self._send(200, {"status": "success", "data": ["02-DEC-26", "25-NOV-26"]})
            if p == "/api/v1/optionchain":
                return self._send(200, chain(state, body))
            if p == "/api/v1/market/timings":
                return self._send(200, {"status": "success", "data": [
                    {"exchange": "NFO", "start_time": 0, "end_time": 0}]})
            if p == "/api/v1/history":
                state.history_calls += 1
                if state.history_down or body["symbol"].endswith("24100CE"):
                    return self._send(400, {"status": "error", "message": "symbol not found"})
                return self._send(200, {"status": "success", "data": [
                    {"timestamp": 1795000000 + 60 * i, "open": 1, "high": 2, "low": 0.5,
                     "close": 1.5, "volume": 10, "oi": 100} for i in range(2)]})
            self._send(404, {"status": "error", "message": "not found"})
    return H


async def ws_handler(ws, state: State):
    state.ws_connections += 1
    conn_no = state.ws_connections
    subs: list[dict] = []
    started = time.monotonic()

    async def pump():
        while True:
            await asyncio.sleep(0.05)
            if state.drop_ws_after and conn_no == 1 and time.monotonic() - started > state.drop_ws_after:
                await ws.close()
                return
            for s in list(subs):
                await ws.send(json.dumps({"type": "market_data", "symbol": s["symbol"],
                    "exchange": s["exchange"], "mode": 3, "broker": "upstox", "data": {
                        "ltp": 101.25, "ltq": 75, "ltt": int(time.time() * 1000),
                        "timestamp": int(time.time() * 1000), "volume": 5000, "oi": 1234.0,
                        "open": 90, "high": 110, "low": 85, "close": 95,
                        "depth": {"buy": [{"price": 101.0 - i * 0.05, "quantity": 75 * (i + 1),
                                           "orders": i + 1} for i in range(5)],
                                  "sell": [{"price": 101.5 + i * 0.05, "quantity": 75,
                                            "orders": 1} for i in range(5)]}}}))

    task = None
    try:
        async for raw in ws:
            m = json.loads(raw)
            if m.get("action") == "authenticate":
                if m.get("api_key") != KEY:
                    await ws.send(json.dumps({"status": "error", "code": "AUTHENTICATION_ERROR",
                                              "message": "Invalid API key"}))
                    continue
                await ws.send(json.dumps({"type": "auth", "status": "success", "broker": "upstox",
                                          "user_id": "u1"}))
                task = asyncio.create_task(pump())
            elif m.get("action") == "subscribe":
                subs.extend(m["symbols"])
                await ws.send(json.dumps({"type": "subscribe", "status": "success",
                    "subscriptions": [{**s, "status": "success", "mode": 3} for s in m["symbols"]]}))
    finally:
        if task:
            task.cancel()


class FakeOpenAlgo:
    def __init__(self):
        self.state = State()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.state))
        self.host = f"http://127.0.0.1:{self.http.server_address[1]}"
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self._ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run_ws, daemon=True).start()
        self._ready.wait(5)

    def _run_ws(self):
        asyncio.set_event_loop(self.loop)

        async def main():
            async with serve(lambda ws: ws_handler(ws, self.state), "127.0.0.1", 0) as srv:
                self.ws_url = f"ws://127.0.0.1:{srv.sockets[0].getsockname()[1]}"
                self._ready.set()
                await asyncio.Future()
        self.loop.run_until_complete(main())

    def close(self):
        self.http.shutdown()
