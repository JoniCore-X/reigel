"""Pruebas del diagnóstico sin acceder a datos comerciales."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "reigel_doctor",
    Path(__file__).resolve().parents[1] / "scripts" / "doctor.py",
)

assert SPEC is not None
assert SPEC.loader is not None
doctor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = doctor
SPEC.loader.exec_module(doctor)


def test_doctor_structure_identifies_missing_files(tmp_path):
    result = doctor.check_structure(tmp_path)

    assert result.status == "ERROR"
    assert "main.py" in result.detail


def test_doctor_structure_accepts_expected_layout(tmp_path):
    for name in doctor.REQUIRED_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    result = doctor.check_structure(tmp_path)

    assert result.status == "OK"


def test_doctor_json_exit_code_and_schema(monkeypatch, capsys):
    monkeypatch.setattr(
        doctor,
        "diagnose",
        lambda run_tests=True: [
            doctor.Result("Python", "OK", "3.14")
        ],
    )

    assert doctor.main(["--json"]) == 0

    body = json.loads(capsys.readouterr().out)

    assert body == {
        "ok": True,
        "checks": [
            {
                "check": "Python",
                "status": "OK",
                "detail": "3.14",
            }
        ],
    }


def test_doctor_returns_failure_when_any_check_fails(monkeypatch):
    monkeypatch.setattr(
        doctor,
        "diagnose",
        lambda run_tests=True: [
            doctor.Result("Seguridad", "ERROR", "falló")
        ],
    )

    assert doctor.main(["--sin-pruebas"]) == 1


def test_doctor_warnings_do_not_fail_json_result(monkeypatch, capsys):
    def diagnose_without_tests(*, run_tests):
        assert run_tests is False
        return [
            doctor.Result("JavaScript", "AVISO", "Node no disponible"),
            doctor.Result("Pytest", "AVISO", "Omitido"),
        ]

    monkeypatch.setattr(doctor, "diagnose", diagnose_without_tests)

    assert doctor.main(["--sin-pruebas", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)

    assert body["ok"] is True
    assert body["checks"][0] == {
        "check": "JavaScript",
        "status": "AVISO",
        "detail": "Node no disponible",
    }


def test_doctor_git_does_not_print_sensitive_filenames(
    monkeypatch,
    tmp_path,
):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(doctor, "ROOT", tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(
        doctor,
        "run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            stdout=".env\n",
            stderr="",
        ),
    )

    result = doctor.check_git_privacy()

    assert result.status == "ERROR"
    assert ".env" not in result.detail
    assert "1 archivo(s)" in result.detail
