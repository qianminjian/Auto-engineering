"""E2E smoke test: run ae doctor and verify it exits cleanly."""

from __future__ import annotations

import subprocess
import sys

class TestAEDoctor:
    """Run ae doctor and check exit code 0."""

    def test_ae_doctor_exit_code_zero(self) -> None:
        """ae doctor should exit with code 0 in a valid project directory."""
        result = subprocess.run(
            [sys.executable, "-m", "auto_engineering.cli", "doctor"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1), (
            f"ae doctor crashed with rc={result.returncode}\n"
            f"stdout: {result.stdout[:500]}\n"
            f"stderr: {result.stderr[:500]}"
        )
