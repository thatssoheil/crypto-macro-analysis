#!/usr/bin/env bash
# ============================================================
# macro-invest refresh runner (on-demand)
#
# Fetches the latest data and re-aggregates the analysis.
# Charts are appended daily by the sources (Bitstamp, FRED, Yahoo,
# blockchain.info, alternative.me, DefiLlama, ECB) - running this
# pulls whatever is new since the last fetch.
#
# This does NOT git-pull, does NOT schedule anything, and does NOT
# push. It only refreshes local data + recomputes the verdict.
# Run it whenever the user asks for an update.
#
# Usage:  scripts/refresh.sh            # full refresh + verdict
#         scripts/refresh.sh --check    # status only (no changes)
#
# Exit codes: 0 = ok, 1 = failed (check stderr)
# ============================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

PY="${PYTHON:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
    echo "No venv at $REPO_DIR/.venv - run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
    exit 1
fi

# Load FRED_API_KEY from .env if present (keyless sources always work; FRED needs the key)
if [[ -f "$REPO_DIR/.env" ]]; then
    set -a; source "$REPO_DIR/.env"; set +a
fi

if [[ "${1:-}" == "--check" ]]; then
    echo "=== macro-invest status ==="
    git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo "not a git repo"
    echo "last data refresh: $(stat -c %y "$REPO_DIR/data/macro_dataset/manifest.json" 2>/dev/null | cut -d. -f1)"
    echo "latest regime: $(grep -E '^## SCORE' "$REPO_DIR/data/macro/latest.md" 2>/dev/null || echo 'n/a')"
    exit 0
fi

echo "=== [1/3] fetch latest data ==="
# build_macro_dataset.py appends whatever is new since the last fetch.
# Keyless sources work everywhere; FRED series run when FRED_API_KEY is set.
"$PY" "$REPO_DIR/strategies/build_macro_dataset.py" 2>&1 | tail -4 || { echo "fetch failed (network?)" >&2; exit 1; }

echo "=== [2/3] regime engine ==="
"$PY" "$REPO_DIR/strategies/macro_regime_v3.py" 2>&1 | tail -4

echo "=== [3/3] audit ==="
"$PY" "$REPO_DIR/strategies/audit_dataset.py" 2>&1 | tail -2

echo
echo "=== DONE. Latest verdict: ==="
grep -E "^## SCORE" "$REPO_DIR/data/macro/latest.md" 2>/dev/null || echo "no latest.md"
