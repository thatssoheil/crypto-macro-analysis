#!/usr/bin/env bash
# ============================================================
# macro-invest self-update runner
#
# Refreshes the repo to the latest analysis state on ANY system:
#   1. git pull origin main (fast-forward only; abort on conflict)
#   2. if the local BTC dataset is older than 7 days, re-fetch it
#      (build_macro_dataset.py - keyless; FRED runs when FRED_API_KEY set)
#   3. re-run the regime engine (macro_regime_v3.py) -> fresh latest.md
#   4. re-run the audit (audit_dataset.py) -> 12/12 signal check
#   5. print a one-line verdict
#
# Usage:  scripts/self_update.sh          # full refresh
#         scripts/self_update.sh --check  # report status without updating
#
# Exit codes: 0 = ok, 1 = update skipped/failed (check stderr)
# ============================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PY="${PYTHON:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
    echo "No venv at $REPO_DIR/.venv - run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
    echo "=== macro-invest status ==="
    git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "not a git repo"
    echo "last data refresh: $(stat -c %y "$REPO_DIR/data/macro_dataset/manifest.json" 2>/dev/null | cut -d. -f1)"
    echo "latest regime: $("$PY" -c "import json; d=json.load(open('$REPO_DIR/data/macro/latest.md')); print('HOLD' if 'HOLD' in open('$REPO_DIR/data/macro/latest.md').read() else '?')" 2>/dev/null || echo 'n/a')"
    exit 0
fi

echo "=== [1/4] git pull ==="
# Fast-forward only: never create a merge commit, never overwrite local changes
if ! git -C "$REPO_DIR" pull --ff-only origin main 2>&1; then
    echo "git pull failed (local changes or conflict?). Run manually." >&2
    exit 1
fi

echo "=== [2/4] dataset freshness ==="
# Re-fetch if manifest.json is missing or older than 7 days
if [[ -f "$REPO_DIR/data/macro_dataset/manifest.json" ]] && [[ -n $(find "$REPO_DIR/data/macro_dataset/manifest.json" -mtime -7 2>/dev/null) ]]; then
    echo "dataset fresh (<7d), skipping fetch"
else
    echo "dataset stale - re-fetching (keyless; FRED needs FRED_API_KEY)"
    "$PY" "$REPO_DIR/strategies/build_macro_dataset.py" 2>&1 | tail -3 || echo "build_macro_dataset failed (network?) - continuing with stale data" >&2
fi

echo "=== [3/4] regime engine ==="
"$PY" "$REPO_DIR/strategies/macro_regime_v3.py" 2>&1 | tail -4

echo "=== [4/4] audit ==="
"$PY" "$REPO_DIR/strategies/audit_dataset.py" 2>&1 | tail -2

echo
echo "=== DONE. Latest verdict: ==="
grep -E "^## SCORE" "$REPO_DIR/data/macro/latest.md" 2>/dev/null || echo "no latest.md"
