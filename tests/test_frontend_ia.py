"""Run the /ia controller regressions (ia.js on a synthetic DOM) when Node is available."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for the /ia controller tests")
def test_ia_controller_keeps_each_reply_in_its_conversation():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [shutil.which("node"), "--test", "tests/frontend_ia.test.cjs"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
