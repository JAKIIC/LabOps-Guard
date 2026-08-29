#!/bin/sh
set -u

sessions_root="${1:-demo/live-sessions}"
exec python -B -m labops reviewer stop --sessions-root "$sessions_root"
