#!/bin/sh
# Linux/Mac equivalent: scripts/run.sh [mock|scan|watch|live]
cd "$(dirname "$0")/.."
case "$1" in
  mock) python3 -m eve_profit mock && python3 -m eve_profit scan ;;
  live) python3 -m eve_profit sde && python3 -m eve_profit watch --live ;;
  *)    python3 -m eve_profit "${1:-scan}" ;;
esac
