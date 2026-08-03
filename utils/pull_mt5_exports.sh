#!/usr/bin/env bash
# Copy latest MT5 Common/Files exports into forex-bot/data/ftmo/
set -euo pipefail
DEST="/home/thatssoheil/hermes-dump/forex-bot/data/ftmo"
mkdir -p "$DEST"
n=0
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f")
  case "$base" in
    *US30*|*US500*|*US100*|*XAU*|*EURUSD*|*GBPUSD*|*ftmo_symbols*)
      cp -v "$f" "$DEST/"
      n=$((n+1))
      ;;
  esac
done < <(find "${HOME}/.mt5/drive_c/users" -type f -name "*.csv" 2>/dev/null)

echo "copied=$n -> $DEST"
ls -la "$DEST" 2>/dev/null || true
