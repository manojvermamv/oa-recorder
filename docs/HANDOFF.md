# 🤝 Handoff log

One entry per handoff, newest first. Times are IST. Each entry is a plain text
block so it can be copied as-is into the next session. On 2026-11-16 all
earlier entries (13 Nov main session, 13 Nov phone side session, 14 Nov
consolidated, 16 Nov live day, 16 Nov phone removal) were merged into the
single entry below. The repo was recreated on 2026-11-16 with one initial
commit, so earlier versions are not in git history.

## 🗃️ 2026-11-16 17:30 IST — consolidated

```text
HANDOFF — openalgo-recorder (oar) — 2026-11-16 17:30 IST (consolidated)

WHAT OAR IS
- Standalone add-on next to a running OpenAlgo. Uses only OpenAlgo's public
  REST API (/api/v1) and websocket with an API key. Never imports, modifies or
  reads OpenAlgo's files/databases; no dependency on the AutonomousTrading
  projects (OA, OA_NEW, AutonomousTradingArchitect are read-only context).
- Each trading day (IST):
    09:00-15:35  websocket Depth mode: spot + 20 strikes each side of ATM,
                 CE+PE, nearest expiry; strikes added as ATM moves, never dropped.
    every 60 s   /api/v1/optionchain with IV + greeks.
    15:45        /api/v1/history 1m + D bars with OI for every contract seen,
                 /expiry list, /instruments (master contract).
- Storage: raw gzip JSON lines (source of truth) -> Parquet per day in
  data/date=YYYY-MM-DD/: ticks, chain, bars, expiries, instruments, events,
  symbols.json, manifest.json, eod.done. Columns in DATA.md.
- Defaults: NIFTY (NSE_INDEX/NFO) and SENSEX (BSE_INDEX/BFO). Everything is
  in config.toml; address + API key in .env (written by `oar setup`).

STATE NOW
- No machine is recording. The phone test rig was removed on 16 Nov; the
  Docker server is not set up (SSH host not given). Capture restarts only
  when oar is deployed somewhere.
- Repo github.com/manojvermamv/oa-recorder: PUBLIC, branch main only,
  main = origin/main, working tree clean. Recreated fresh on 16 Nov: history
  starts at the "Initial commit"; no market data was ever in this repo.
- Tests: 8 pass (python -m pytest -q, ~65 s, fake OpenAlgo; last run 14 Nov,
  code unchanged since).
- Proven against real OpenAlgo 2.0.3.3 + Upstox (on the phone): oar check,
  after-close fetch (12, 13, 16 Nov) and live capture (16 Nov, 41 min).
- Recorded data lives ONLY on the office PC in <repo>/market-data/
  (27 files, ~115 MB), git-ignored (see MARKET DATA). Never push it.

HISTORY, IN ORDER
1. 13 Nov: owner asked for oar, research first. Request quoted verbatim in
   docs/RESEARCH.md section 0. OpenAlgo cloned to _ref/openalgo
   (marketcalls/openalgo @ f456b32, v2.0.3.3; the clone has since been
   deleted and is gitignored).
2. Research (code over docs): no one-shot after-close download exists.
   Ticks, depth, option-chain IV/greeks are live-only; OpenAlgo stores none.
   1m/D bars with OI fetchable after close but only while the contract is
   listed (master contract reloads ~08:00 next day; expired options vanish).
   Rejected: Historify DuckDB (browser-session only, lock risk), ZeroMQ bus
   (internal, loopback, single subscriber), reading OpenAlgo DB files.
3. Owner approved. Defaults: NIFTY + SENSEX, nearest 1 expiry, 60 s chain.
   Built oar v0.1.0 + tests against a fake OpenAlgo. Fix found in testing:
   after-close job stops after the first 5 failed history calls (broker
   logged out); scheduler retries every 15 min.
4. Git init, pushed. Docs: docs/RESEARCH.md, docs/HANDOFF.md, AGENTS.md,
   CLAUDE.md start guide.
5. 13-14 Nov side session: phone test rig (Termux + proot Debian) with
   OpenAlgo and oar; `oar setup` added (hidden API-key prompt, writes .env).
   After-close data for 12 and 13 Nov fetched. Phone identifiers were
   removed from the docs.
6. 16 Nov: first live day on the phone (14:51-15:33). Android killed Termux
   at 15:33 (memory pressure); restarted 15:50 and the after-close job ran.
   A mistaken `git pull` on the phone was fixed with
   `git reset --hard origin/main`; capture was unaffected (oar runs the
   installed copy in .venv, not the repo files).
7. 16 Nov: phone data copied to the PC (27 files, sha256-identical), then
   the phone rig was removed completely (see PHONE RIG). 2.92 GB freed.
8. 16 Nov: broker user id in the data replaced with DUMMYUSER; licensing
   research showed the data must not be public, so market-data/ is
   git-ignored and kept local only (see MARKET DATA).
9. 16 Nov: one emoji per section header in all docs; handoff consolidated.
10. 16 Nov: old GitHub repo deleted and recreated public with a single
   "Initial commit" of the same files (local .git replaced too).

MARKET DATA (office PC only: <repo>/market-data/, git-ignored)
- date=2026-11-12 (3.6 MB): after-close only. 332/332 bar calls ok, 61,853
  bars, 163 options (NIFTY 82, SENSEX 81) + 2 spots.
- date=2026-11-13 (3.8 MB): after-close only. 332/332 ok, 63,445 bars.
  For both: chain, expiries, instruments are the 14 Nov snapshot (brokers do
  not serve them for a past date); strike window = ATM at fetch time.
- date=2026-11-16 (102 MB): live 14:51:36-15:33:02, 366,478 ticks, 174
  symbols (NIFTY, SENSEX, 172 options), longest silence 0.9 s, option ticks
  100% with bid/ask and OI; 84 chain snapshots (IV on ~95% of legs);
  348/348 bar calls ok, spot 1m 375 each (09:15-15:29), 0 broken OHLC.
- Options with no trades (no bars): 12 Nov SENSEX19NOV2679600CE, 13 Nov
  SENSEX19NOV2683600PE, 16 Nov SENSEX19NOV2684100PE.
- Scrub: 16 Nov ws_connected user_id -> DUMMYUSER in events.parquet and
  raw/live-145135-3eba7e50.jsonl.gz (raw rewritten as a complete gzip, every
  byte kept; manifest still lists truncated_file=1 from the original). No
  API keys, secrets, login tokens or emails anywhere in the data.
- Licensing: NSE terms of use, NSE Data Usage & Sharing Policy, NSE
  historical data agreement, NSE non-display policy (derived data such as
  IV/greeks), BSE redistribution licence fees and Upstox terms all require
  written consent / a licence to republish, historical data included. A
  LICENSE file cannot grant that. Keep it local or in private storage.
- The data was public on the old (now deleted) repo for about 1 hour on
  16 Nov; anyone who cloned it then keeps a copy.
- A backup of the old repo's history, which includes the data (112 MB), is
  on the office PC under %TEMP%\claude\...\scratchpad\
  oa-recorder-before-unpublish.bundle; Windows may clear it, delete it when
  no longer needed.
- market-data/ is the only copy: back it up privately if it matters.

CODE
- oar/config.py   settings (config.toml + .env + env vars; env vars win;
                  OAR_ENV overrides the .env path), IST fixed offset.
- oar/api.py      stdlib REST client: quotes, expiry, optionchain, history,
                  instruments, market/timings.
- oar/store.py    RawWriter (gzip, flush each second, crash-safe),
                  convert_day -> Parquet + manifest.
- oar/live.py     websocket loop (auth, subscribe, reconnect with backoff,
                  stall watchdog), option-chain loop (adds new strikes).
- oar/eod.py      after-close bars/expiries/instruments; eod.done marker.
- oar/__main__.py CLI: run | live | eod | convert | check | setup.
  `oar setup`: asks address + API key (getpass, hidden, any OS), refuses keys
  < 20 chars, writes .env beside config.toml (mode 600 where the OS has it,
  other lines kept, default addresses left out so Docker keeps openalgo-web),
  then runs check. Script flags: --key-stdin, --host, --ws-url, --no-check.
- Run files: Dockerfile, docker-compose.yml (joins external network
  ${OPENALGO_NETWORK:-openalgo_default}, reaches openalgo-web:5000/8765),
  .env.example, config.example.toml, deploy/oar.service (systemd),
  deploy/oar-windows.ps1 + run-oar.cmd (Task Scheduler), deploy/android/.
- Docs: README.md, DATA.md, docs/RESEARCH.md, docs/HANDOFF.md, AGENTS.md.
- Tests: tests/fake_openalgo.py (REST + websocket fake), tests/test_recorder.py.

KEY FACTS (verified in OpenAlgo 2.0.3.3 code and on the live day)
- Broker is Upstox: depth is 5 levels; Upstox feed greeks are dropped by
  OpenAlgo, so IV/greeks are OpenAlgo's Black-76; Upstox throttles quote
  calls (owner's notes: ~17% refusals at ~52/min) — chain_seconds shares it.
- /api/v1/ping says "pong" even with a dead broker session: oar uses a quote.
- After the 03:00 token rollover / re-login the proxy drops the broker feed
  silently: oar's watchdog reconnects after stall_seconds of no ticks.
- The Upstox login survives an OpenAlgo restart within the same day.
- /expiry returns 30-DEC-25; /optionchain wants 30DEC25.
- OpenAlgo .env must have WEBSOCKET_HOST='0.0.0.0' for container-to-container
  websocket access (OpenAlgo's Docker installers set it).
- Raw live data grows ~100 MB/hour (2 indices, 174 symbols) => ~650 MB per
  full day; one day's ticks.parquet is ~50 MB.

NOT VERIFIED
- A full live day (09:00-15:35) end to end.
- Docker image build and the Docker setup command
  `docker compose run --rm --user root -v "$PWD/.env:/app/.env" oar setup`
  (no Docker on the office PC).
- Interactive `oar setup` prompt on Windows (getpass is stdlib).

WAITING ON OWNER
- SSH host name of the new OpenAlgo Docker server (old debian-oa is gone).
- Daily broker login (Upstox via OpenAlgo) once oar runs anywhere.

NEXT STEPS
1. Docker server, once the host is known: git clone to /opt/oar; check
   OpenAlgo's .env WEBSOCKET_HOST and Docker network name; cp .env.example
   .env; cp config.example.toml config.toml; docker compose build;
   oar setup via the Docker command above; docker compose up -d;
   docker compose run --rm oar check. After the first full day, read
   manifest.json and events.parquet; raise chain_seconds on quote refusals.
2. Keep recorded data out of git (market-data/ and data/ are ignored);
   plan disk for ~650 MB/day or set keep_raw=false.
3. Optional: delete the old-history backup bundle; back up market-data/
   privately; remove the GitHub CLI delete_repo permission
   (`gh auth refresh -h github.com -r delete_repo`).
4. Possible later additions (not built): auto-restart watchdog, README
   Android section.

PHONE RIG (Android test rig, REMOVED 2026-11-16 — notes for a rebuild)
- Was: Vivo V2437, Android 16, arm64; Termux + proot-distro Debian 13
  (trixie); OpenAlgo 2.0.3.3 at /root/openalgo and oar at /root/oa-recorder,
  each in its own tmux session. The PC reached it via adb over USB -> Termux
  sshd (port 8022) -> `proot-distro login debian -- <cmd>`.
- Removed: Debian (OpenAlgo, oar, .env, logins, data), proot-distro and
  proot, logs, the PC's SSH key (from authorized_keys and from the PC), sshd
  stopped, adb forwards removed. Kept: Termux, tmux, openssh,
  ~/downloads/script.sh (7 Nov, not ours). Phone free 10.33 -> 13.25 GB.
- Files kept in git for a rebuild: deploy/android/ (ifaddrs_lo.c shim,
  start-openalgo.sh, README with the install commands).
- Bootstrap sshd without typing on the phone:
    adb shell am start -n com.termux/.app.TermuxActivity
    adb shell "input text '<command with spaces replaced by %s>'"
    adb shell input keyevent 66
  with: pkg install -y openssh && mkdir -p ~/.ssh && echo <PUBKEY> >>
  ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && sshd
- Problems met and fixes:
  1. proot-distro install: curl 403 from the default tarball host. Fix:
     PD_OVERRIDE_TARBALL_URL=https://github.com/termux/proot-distro/releases/download/v4.29.0/debian-trixie-aarch64-pd-v4.29.0.tar.xz
     PD_OVERRIDE_TARBALL_SHA256=3834a11cbc6496935760bdc20cca7e2c25724d0cd8f5e4926da8fd5ca1857918
  2. OpenAlgo abort "Permission denied (src/ip_resolver.cpp:542)": Android 11+
     blocks getifaddrs(), ZeroMQ needs it. Fix: LD_PRELOAD shim returning
     loopback only (deploy/android/ifaddrs_lo.c):
       gcc -shared -fPIC -O2 -o /root/shim/libifaddrs_lo.so /root/shim/ifaddrs_lo.c
  3. Flask-SocketIO refuses its dev server without a TTY: run in tmux.
  4. "CANNOT LINK EXECUTABLE ... libifaddrs_lo.so": Termux bin dirs on PATH.
     Fix: Debian-only PATH in start-openalgo.sh.
  5. `pkg install tmux` can fail silently: check `command -v tmux`.
  6. Termux has no /tmp: use $TMPDIR. Debian under proot runs on UTC, so log
     times are 5:30 behind IST (oar's schedule uses IST).
  7. Android killed Termux under memory pressure despite wake lock and
     battery whitelisting: use a wall charger, close other apps, set the
     Vivo battery option to "no restrictions"; check `tmux ls` each morning.
  8. Never `pkill -f "python app.py"` over ssh (kills its own shell); use
     `tmux kill-session -t openalgo`.
  9. A clone made before the repo was recreated cannot `git pull`; clone it
     again (or `git fetch` + `git reset --hard origin/main`).
```
