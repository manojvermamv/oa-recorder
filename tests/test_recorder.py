import gzip
import json
from datetime import datetime, timedelta

import pyarrow.parquet as pq
import pytest

from oar.__main__ import check, is_trading_day
from oar.api import OpenAlgo, chain_expiry
from oar.config import IST, Config, Underlying
from oar.eod import eod_marker, run_eod
from oar.live import pick_expiries
from oar.__main__ import run_live
from oar.store import RawWriter, convert_day, day_dir, read_raw

from fake_openalgo import KEY, FakeOpenAlgo


@pytest.fixture
def fake():
    f = FakeOpenAlgo()
    yield f
    f.close()


def make_cfg(fake, tmp_path, **kw) -> Config:
    cfg = Config(host=fake.host, ws_url=fake.ws_url, api_key=KEY, data_dir=tmp_path,
                 underlyings=[Underlying("NIFTY", "NSE_INDEX", "NFO")], strike_count=3,
                 history_intervals=["1m", "D"])
    cfg.chain_seconds = 1
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_expiry_helpers():
    assert chain_expiry("25-NOV-26") == "25NOV26"
    assert pick_expiries(["02-DEC-26", "25-NOV-26", "09-DEC-26"], 2) == ["25-NOV-26", "02-DEC-26"]


def test_live_then_eod_end_to_end(fake, tmp_path):
    cfg = make_cfg(fake, tmp_path)
    api = OpenAlgo(cfg.host, cfg.api_key)
    today = datetime.now(IST).date()
    assert is_trading_day(cfg, api, today)

    fake.state.drop_ws_after = 1.0  # server drops the first websocket: oar must reconnect
    run_live(cfg, api, datetime.now(IST) + timedelta(seconds=4))
    assert fake.state.ws_connections >= 2

    symbols = json.loads((day_dir(tmp_path, today) / "symbols.json").read_text())
    # spot + 7 strikes x 2 at ATM 24000, then ATM 24050 adds one strike x 2
    assert len(symbols) == 1 + 14 + 2
    assert any(s["symbol"] == "NIFTY25NOV2624200CE" for s in symbols)

    assert run_eod(cfg, api, today)
    assert eod_marker(cfg, today).exists()
    d = day_dir(tmp_path, today)
    m = json.loads((d / "manifest.json").read_text())
    assert m["problems"] == {}

    ticks = pq.read_table(d / "ticks.parquet").to_pandas()
    assert len(ticks) > 50
    assert set(ticks.broker) == {"upstox"}
    opt = ticks[ticks.option_type.notna()].iloc[0]
    assert opt.underlying == "NIFTY" and opt.expiry == "25NOV26" and opt.strike > 0
    assert opt.bid_px_1 == 101.0 and opt.ask_qty_5 == 75 and opt.bid_orders_5 == 5
    assert ticks.recv_ts.dt.tz is not None
    assert (ticks.groupby("session").seq.is_monotonic_increasing).all()

    chain = pq.read_table(d / "chain.parquet").to_pandas()
    assert set(chain.option_type) == {"CE", "PE"}
    assert chain.implied_volatility.notna().all() and (chain.exchange == "NFO").all()

    bars = pq.read_table(d / "bars.parquet").to_pandas()
    assert set(bars.interval) == {"1m", "D"}
    assert bars.oi.eq(100).all()
    # every tracked symbol got bars except the one the fake refuses
    assert bars.symbol.nunique() == len(symbols) - 1

    events = pq.read_table(d / "events.parquet").to_pandas()
    names = set(events.event)
    assert {"live_start", "live_stop", "ws_connected", "ws_disconnected",
            "symbols_added", "api_error", "eod_stop"} <= names
    assert pq.read_table(d / "expiries.parquet").column("expiry_date").null_count == 0
    assert pq.read_table(d / "instruments.parquet").num_rows == 2  # NSE_INDEX + NFO


def test_eod_without_live_takes_window_itself(fake, tmp_path):
    cfg = make_cfg(fake, tmp_path)
    api = OpenAlgo(cfg.host, cfg.api_key)
    today = datetime.now(IST).date()
    assert run_eod(cfg, api, today)
    bars = pq.read_table(day_dir(tmp_path, today) / "bars.parquet").to_pandas()
    assert bars.symbol.nunique() == 1 + 14 - 1


def test_eod_gives_up_early_when_broker_is_down(fake, tmp_path):
    import time
    fake.state.history_down = True
    cfg = make_cfg(fake, tmp_path)
    today = datetime.now(IST).date()
    t = time.monotonic()
    assert not run_eod(cfg, OpenAlgo(cfg.host, cfg.api_key), today)
    assert time.monotonic() - t < 40
    assert fake.state.history_calls <= 5 * 3
    assert not eod_marker(cfg, today).exists()


def test_bad_key_is_reported(fake, tmp_path, capsys):
    cfg = make_cfg(fake, tmp_path, api_key="wrong")
    assert check(cfg, OpenAlgo(cfg.host, cfg.api_key)) == 1
    good = make_cfg(fake, tmp_path)
    assert check(good, OpenAlgo(good.host, good.api_key)) == 0


def test_truncated_raw_file_keeps_flushed_records(tmp_path):
    day = datetime.now(IST).date()
    w = RawWriter(tmp_path, day, "live", "s" * 32, "http://x")
    for i in range(10):
        w.event("e", i=i)
    w.flush()
    path = w.path
    data = path.read_bytes()  # simulate a crash: flushed but never closed
    w.close()
    path.write_bytes(data)
    from collections import Counter
    problems = Counter()
    assert len(list(read_raw(path, problems))) == 10
    m = convert_day(tmp_path, day)
    assert m["tables"]["events"]["rows"] == 10


def test_setup_saves_env_and_checks(fake, tmp_path, monkeypatch, capsys):
    import io
    import os

    from oar.__main__ import main
    from oar.config import load, read_env

    for k in ("OAR_API_KEY", "OAR_HOST", "OAR_WS_URL", "OAR_ENV", "OAR_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    cfg_path = tmp_path / "config.toml"
    env = tmp_path / ".env"
    env.write_text("# mine\nOPENALGO_NETWORK=x\n")

    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["--config", str(cfg_path), "setup", "--key-stdin"]) == 1   # cut-off key: nothing saved
    assert "OAR_API_KEY" not in read_env(env)

    monkeypatch.setattr("sys.stdin", io.StringIO(KEY + "\n"))
    rc = main(["--config", str(cfg_path), "setup", "--key-stdin",
               "--host", fake.host, "--ws-url", fake.ws_url])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert KEY not in out                                   # the key is never printed
    saved = read_env(env)
    assert saved["OAR_API_KEY"] == KEY and saved["OPENALGO_NETWORK"] == "x"
    assert env.read_text().startswith("# mine")              # other lines kept
    if os.name == "posix":
        assert env.stat().st_mode & 0o777 == 0o600

    for k in ("OAR_API_KEY", "OAR_HOST", "OAR_WS_URL"):
        monkeypatch.delenv(k, raising=False)
    assert load(cfg_path).api_key == KEY                    # .env is read by every command


def test_setup_leaves_default_address_out(tmp_path, monkeypatch):
    import io

    from oar.__main__ import main
    from oar.config import read_env

    for k in ("OAR_API_KEY", "OAR_HOST", "OAR_WS_URL", "OAR_ENV"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("k" * 32 + "\n"))
    assert main(["--config", str(tmp_path / "c.toml"), "setup", "--key-stdin", "--no-check"]) == 0
    assert set(read_env(tmp_path / ".env")) == {"OAR_API_KEY"}   # Docker keeps openalgo-web
