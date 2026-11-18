#!/usr/bin/env python3
"""SOL tape - kept as a named entry point; the implementation is shared.

The tape is generic now (strategies/asset_tape.py) because ZEC needed the same
sections. This shim exists so the documented command keeps working:
    ./.venv/bin/python strategies/sol_macro_report.py
is exactly
    ./.venv/bin/python strategies/asset_tape.py --asset SOL
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import asset_tape

if __name__ == "__main__":
    sys.exit(asset_tape.main(["--asset", "SOL"]))
