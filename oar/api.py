"""Minimal client for OpenAlgo's public REST API (/api/v1). Standard library only."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class ApiError(RuntimeError):
    pass


class OpenAlgo:
    def __init__(self, host: str, api_key: str, timeout: int = 30):
        self.host = host.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None):
        url = f"{self.host}/api/v1/{path}"
        data = None
        headers = {"Accept": "application/json", "User-Agent": "openalgo-recorder"}
        if method == "GET":
            url += "?" + urllib.parse.urlencode({"apikey": self.api_key, **(query or {})})
        else:
            data = json.dumps({"apikey": self.api_key, **(body or {})}).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            text = e.read().decode(errors="replace")[:500]
            raise ApiError(f"{path}: HTTP {e.code}: {text}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise ApiError(f"{path}: {e}") from None
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise ApiError(f"{path}: {payload.get('message')}")
        return payload

    def post(self, path: str, **body):
        return self._call("POST", path, body=body)

    # Endpoints the recorder uses -------------------------------------------------

    def quotes(self, symbol: str, exchange: str) -> dict:
        return self.post("quotes", symbol=symbol, exchange=exchange)

    def expiries(self, symbol: str, exchange: str) -> list[str]:
        return self.post("expiry", symbol=symbol, exchange=exchange, instrumenttype="options")["data"]

    def option_chain(self, underlying: str, exchange: str, expiry: str, strike_count: int,
                     with_greeks: bool, interest_rate: float) -> dict:
        body = dict(underlying=underlying, exchange=exchange, expiry_date=expiry,
                    strike_count=strike_count, with_greeks=with_greeks)
        if with_greeks and interest_rate:
            body["interest_rate"] = interest_rate
        return self.post("optionchain", **body)

    def history(self, symbol: str, exchange: str, interval: str, start: str, end: str) -> dict:
        return self.post("history", symbol=symbol, exchange=exchange, interval=interval,
                         start_date=start, end_date=end)

    def instruments(self, exchange: str) -> dict:
        return self._call("GET", "instruments", query={"exchange": exchange, "format": "json"})

    def timings(self, date: str) -> dict:
        return self.post("market/timings", date=date)


def chain_expiry(expiry: str) -> str:
    """/expiry returns '30-DEC-25'; /optionchain wants '30DEC25'."""
    return expiry.replace("-", "").upper()
