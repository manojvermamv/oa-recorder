#!/bin/bash
# Start OpenAlgo inside proot Debian on Android.
# Android blocks getifaddrs(), which ZeroMQ needs; the shim answers "loopback only".
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export LD_PRELOAD=/root/shim/libifaddrs_lo.so
cd /root/openalgo
exec .venv/bin/python app.py
