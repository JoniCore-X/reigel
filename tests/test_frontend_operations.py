"""Run synthetic form regressions without opening a browser or commercial data."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from reigel.core import STAGES


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed for form-controller tests")
def test_operations_form_controllers():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [shutil.which("node"), "--test", "tests/frontend_operations.test.cjs"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_pipeline_board_uses_every_server_stage_in_order():
    root = Path(__file__).resolve().parents[1]
    source = (root / "frontend/js/operations.js").read_text(encoding="utf-8")
    match = re.search(r"const pipelineStages = \[([^\]]*)\]", source)
    assert match, "operations.js must define the ordered pipeline stages"
    listed = tuple(re.findall(r"'([^']+)'", match.group(1)))
    assert listed == STAGES
