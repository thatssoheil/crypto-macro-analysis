import subprocess, sys
OUT = subprocess.run(
    [".venv/bin/python", "strategies/jev_matrix.py", "--smoke"],
    capture_output=True, text=True, timeout=300).stdout
assert "SCHEMA_OK" in OUT, "matrix smoke must print SCHEMA_OK"
assert "no_lookahead=PASS" in OUT, "shift(1) self-check must pass"
assert "accounting=PASS" in OUT, "equity reconciliation must pass"
print("MATRIX_TEST_PASS")
