"""Settings: a TOML file, with environment variables overriding connection values."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from datetime import time, timedelta, timezone
from pathlib import Path

# India has no daylight saving, so a fixed offset is exact and needs no tz database.
IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass
class Underlying:
    name: str  # e.g. NIFTY
    spot_exchange: str  # e.g. NSE_INDEX
    option_exchange: str  # e.g. NFO


@dataclass
class Config:
    host: str = "http://127.0.0.1:5000"
    ws_url: str = "ws://127.0.0.1:8765"
    api_key: str = ""
    data_dir: Path = Path("./data")
    underlyings: list[Underlying] = field(default_factory=list)
    strike_count: int = 20
    expiries: int = 1
    chain_seconds: int = 60
    with_greeks: bool = True
    interest_rate: float = 0.0
    ws_mode: str = "Depth"
    depth_levels: int = 5
    history_intervals: list[str] = field(default_factory=lambda: ["1m", "D"])
    save_instruments: bool = True
    keep_raw: bool = True
    session_start: time = time(9, 0)
    market_open: time = time(9, 15)
    session_end: time = time(15, 35)
    eod_time: time = time(15, 45)
    stall_seconds: int = 60
    http_timeout: int = 30

    @property
    def source_exchanges(self) -> list[str]:
        out: list[str] = []
        for u in self.underlyings:
            for ex in (u.spot_exchange, u.option_exchange):
                if ex not in out:
                    out.append(ex)
        return out


def _t(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def env_file(config_path: str | Path | None = None) -> Path:
    """The .env beside the config file ($OAR_ENV wins). Same file Docker Compose reads."""
    if os.environ.get("OAR_ENV"):
        return Path(os.environ["OAR_ENV"])
    cfg = Path(config_path or os.environ.get("OAR_CONFIG", "config.toml"))
    return cfg.parent / ".env"


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines, # comments and surrounding quotes are ignored."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def write_env(path: Path, values: dict[str, str]) -> None:
    """Update or add keys, keep every other line, owner-only permissions where the OS has them."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    left = dict(values)
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in left:
            lines[i] = f"{k}={left.pop(k)}"
    lines += [f"{k}={v}" for k, v in left.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)  # also tightens a file that existed before; no-op on Windows
    except OSError:
        pass


def load(path: str | Path | None = None) -> Config:
    # Values from .env fill in only what the real environment does not already set.
    for k, v in read_env(env_file(path)).items():
        if k.startswith("OAR_"):
            os.environ.setdefault(k, v)
    path = Path(path or os.environ.get("OAR_CONFIG", "config.toml"))
    raw: dict = {}
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    oa = raw.get("openalgo", {})
    cap = raw.get("capture", {})
    ses = raw.get("session", {})

    cfg = Config(
        host=oa.get("host", Config.host),
        ws_url=oa.get("ws_url", Config.ws_url),
        api_key=oa.get("api_key", ""),
        data_dir=Path(cap.get("data_dir", "./data")),
        strike_count=int(cap.get("strike_count", 20)),
        expiries=int(cap.get("expiries", 1)),
        chain_seconds=int(cap.get("chain_seconds", 60)),
        with_greeks=bool(cap.get("with_greeks", True)),
        interest_rate=float(cap.get("interest_rate", 0.0)),
        ws_mode=str(cap.get("ws_mode", "Depth")),
        depth_levels=int(cap.get("depth_levels", 5)),
        history_intervals=list(cap.get("history_intervals", ["1m", "D"])),
        save_instruments=bool(cap.get("save_instruments", True)),
        keep_raw=bool(cap.get("keep_raw", True)),
        session_start=_t(ses.get("start", "09:00")),
        market_open=_t(ses.get("market_open", "09:15")),
        session_end=_t(ses.get("end", "15:35")),
        eod_time=_t(ses.get("eod", "15:45")),
        stall_seconds=int(ses.get("stall_seconds", 60)),
        http_timeout=int(oa.get("timeout", 30)),
    )
    unds = raw.get("underlying") or [
        {"name": "NIFTY", "spot_exchange": "NSE_INDEX", "option_exchange": "NFO"},
        {"name": "SENSEX", "spot_exchange": "BSE_INDEX", "option_exchange": "BFO"},
    ]
    cfg.underlyings = [Underlying(**u) for u in unds]

    # Environment wins, so secrets and per-deployment addresses stay out of the file.
    cfg.host = os.environ.get("OAR_HOST", cfg.host).rstrip("/")
    cfg.ws_url = os.environ.get("OAR_WS_URL", cfg.ws_url)
    cfg.api_key = os.environ.get("OAR_API_KEY", cfg.api_key)
    cfg.data_dir = Path(os.environ.get("OAR_DATA_DIR", cfg.data_dir))
    if cfg.chain_seconds < 5:
        raise ValueError("capture.chain_seconds must be at least 5")
    return cfg
