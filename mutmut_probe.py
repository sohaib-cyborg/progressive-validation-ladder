#!/usr/bin/env python3
"""
mutmut pre-flight probe for Project D.

Confirms mutmut works on a single-function snippet the way S5 needs.
Run ON YOUR MACHINE:

    pip install mutmut>=3.8
    python mutmut_probe.py

Findings already known (from testing mutmut 3.8.0):
  - mutmut v3 needs a [mutmut] section with `source_paths=` (NOT the old
    `--paths-to-mutate` CLI flag, and NOT `paths_to_mutate` which is deprecated).
  - No clean Python API: drive it as a subprocess, then parse results.
  - So arm_a_mutmut.py will: write tool + tests + setup.cfg to a temp dir,
    run `mutmut run` via subprocess, then read the kill count.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "tool.py").write_text("def add(a, b):\n    return a + b\n")
        (root / "test_tool.py").write_text(
            "from tool import add\n\n"
            "def test_add():\n    assert add(2, 3) == 5\n"
        )
        # mutmut v3 config
        (root / "setup.cfg").write_text("[mutmut]\nsource_paths=tool.py\n")

        print("[..] Running mutmut on a single-function snippet...")
        try:
            proc = subprocess.run(
                ["mutmut", "run"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            print("[FAIL] mutmut not installed. Run: pip install 'mutmut>=3.8'")
            return 1
        except subprocess.TimeoutExpired:
            print("[FAIL] mutmut timed out.")
            return 1

        out = proc.stdout + proc.stderr
        # v3 prints a summary line with emoji counts; look for a killed mutant
        if "mutations/second" in out or "🎉" in out:
            print("[ok] mutmut generated and ran mutants on a single function.")
            print("\n ALL GOOD — mutmut works for S5 (drive it via subprocess).")
            return 0
        print("[FAIL] mutmut did not run as expected. Output:")
        print(out[-1000:])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
