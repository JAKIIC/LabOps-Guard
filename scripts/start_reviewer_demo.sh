#!/bin/sh
set -u

mode="${1:-quick}"
if [ "$#" -gt 0 ]; then
  shift
fi

case "$mode" in
  quick|live) ;;
  *)
    printf '%s\n' 'mode must be quick or live' >&2
    exit 2
    ;;
esac

python -B -m labops reviewer pack-check --mode "$mode"
pack_status=$?
if [ "$pack_status" -ne 0 ]; then
  exit "$pack_status"
fi

python -B -m labops reviewer preflight --mode "$mode"
preflight_status=$?
if [ "$preflight_status" -ne 0 ]; then
  exit "$preflight_status"
fi

exec python -B -m labops reviewer start --mode "$mode" "$@"
