"""Run the public booking-step regressions (chat.js on a synthetic DOM) when Node is available."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the public chat controller tests")
def test_chat_booking_steps_validate_and_recover_from_a_taken_slot():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [shutil.which("node"), "--test", "tests/frontend_chat.test.cjs"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
