# 📱 OpenAlgo + oar on an Android phone (Termux, proot Debian)

A test rig, not the main deployment (removed from the phone on 2026-11-16).
The full story and every problem met is in [docs/HANDOFF.md](../../docs/HANDOFF.md) (section "PHONE RIG").

Files here, copied into Debian's `/root`:

| File | Goes to | Why |
|---|---|---|
| `ifaddrs_lo.c` | `/root/shim/` | Android blocks `getifaddrs()`; ZeroMQ (inside OpenAlgo) aborts without it. Build: `gcc -shared -fPIC -O2 -o /root/shim/libifaddrs_lo.so /root/shim/ifaddrs_lo.c` |
| `start-openalgo.sh` | `/root/` | Starts OpenAlgo with the shim and a Debian-only PATH. Run it inside tmux (Flask-SocketIO needs a terminal). |

Setup in short (in Termux):

```bash
pkg install -y proot-distro tmux openssh
PD_OVERRIDE_TARBALL_URL=https://github.com/termux/proot-distro/releases/download/v4.29.0/debian-trixie-aarch64-pd-v4.29.0.tar.xz PD_OVERRIDE_TARBALL_SHA256=3834a11cbc6496935760bdc20cca7e2c25724d0cd8f5e4926da8fd5ca1857918 proot-distro install debian
proot-distro login debian -- bash -c "apt-get update && apt-get install -y python3 python3-venv python3-dev git curl build-essential"
proot-distro login debian -- bash -c "cd /root && git clone --depth 1 https://github.com/marketcalls/openalgo.git && cd openalgo && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
```

Then copy the two files above into Debian, build the shim, and start:

```bash
tmux new-session -d -s openalgo "proot-distro login debian -- /root/start-openalgo.sh 2>&1 | tee ~/openalgo.log"
```

Install oar in Debian and save the key (typing is hidden; same command as on any OS):

```bash
proot-distro login debian -- bash -c "cd /root && git clone https://github.com/manojvermamv/oa-recorder.git && cd oa-recorder && python3 -m venv .venv && .venv/bin/pip install ."
proot-distro login debian -- bash -c "cd /root/oa-recorder && .venv/bin/oar setup"
```
