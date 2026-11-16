# 🤖 AGENTS.md — start here (any AI agent, any machine)

## 📌 What this is

`openalgo-recorder` (`oar`): a small standalone add-on that runs next to a
running OpenAlgo and records market data every trading day (live ticks + 5-level
depth over the websocket, option chain with IV/greeks every 60 s, after-close
1m/D bars with OI, expiries, master contract) into Parquet. It uses only
OpenAlgo's public REST API and websocket with an API key. It must never depend
on, import from, or modify OpenAlgo or the owner's AutonomousTrading projects.

## 📚 Read first, in this order

1. `docs/HANDOFF.md` — newest entry first; current state and next steps.
2. `docs/RESEARCH.md` — the owner's original request (section 0) and why the
   design is what it is, with OpenAlgo file:line evidence.
3. `README.md` (run it), `DATA.md` (what the files contain).
4. `deploy/android/README.md` — the phone test rig (Termux + proot Debian).

## 🛠️ Set up on a fresh machine

```bash
git clone https://github.com/manojvermamv/oa-recorder.git && cd oa-recorder
python -m venv .venv && .venv/bin/pip install -e ".[test]"   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q                               # 8 tests, ~1 min, fake OpenAlgo
# OpenAlgo reference source (gitignored, needed for research only):
git clone --depth 1 https://github.com/marketcalls/openalgo.git _ref/openalgo
```

Not in git on purpose: `_ref/`, `data/`, `.env`, `config.toml` (secrets and
recorded data). Never commit API keys, broker keys or recorded data.

## 📏 Rules the owner set

- Build against OpenAlgo's real current code (`_ref/openalgo`); trust code over docs.
- Keep it minimal: no extra layers or features; optional things go to
  "possible later additions" in README.
- Read-only for context, never edit: `C:\Users\Manoj\Desktop\Office_2016\OA_NEW`,
  `...\OA`, `...\AutonomousTradingArchitect` (exist only on the office machine).
- Commit or push only when the owner asks.
- Add a dated entry to `docs/HANDOFF.md` (text block, newest first) when
  handing off.

## 🔑 Key facts (verified in OpenAlgo 2.0.3.3 code)

- Ticks, depth and option-chain IV/greeks exist only live; OpenAlgo stores none.
- Option bars must be fetched the same day; expired contracts vanish when the
  master contract reloads the next morning.
- Owner's broker is Upstox: 5-level depth, greeks are OpenAlgo's Black-76,
  Upstox throttles quote calls.
- `/api/v1/ping` says "pong" even when the broker session is dead; use a quote.

## 📋 Open items

- Deploy to the owner's Docker server (SSH host not yet given).
- Phone rig: waiting on owner's OpenAlgo admin + Upstox login + API key, then
  `oar check`, `oar eod`, and a live day.
