"""The 'your PC as server' scripts: static checks of their safety boundaries."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def read(name):
    raw = (SCRIPTS / name).read_bytes()
    # Windows PowerShell 5.1 reads a script without BOM as ANSI and garbles accents.
    assert raw.startswith(b"\xef\xbb\xbf"), name
    return raw.decode("utf-8-sig")


def test_supervisor_listens_locally_keeps_awake_only_while_running_and_runs_once():
    text = read("run_forever.ps1")
    assert "'--host', '127.0.0.1'" in text
    assert "SetThreadExecutionState" in text and "2147483649" in text  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    assert "finally" in text and "2147483648" in text  # releases the request on exit
    assert "System.Threading.Mutex" in text
    assert "powercfg" not in text.lower()  # never changes power settings
    assert "preview_team_caguas.py" in text  # -Preview never opens the commercial database


def test_installer_backs_up_first_and_never_handles_a_password():
    text = read("install_autostart.ps1")
    assert text.index("backup.py") < text.index("Register-ScheduledTask")
    assert "-LogonType S4U" in text
    assert "Password" not in text and "Get-Credential" not in text
    assert "-ExecutionTimeLimit (New-TimeSpan -Seconds 0)" in text
    assert "-RestartCount 999" in text


def test_uninstaller_stops_processes_but_keeps_data():
    text = read("uninstall_autostart.ps1")
    assert "Unregister-ScheduledTask" in text
    assert "Remove-Item" not in text  # database, backups and logs stay
    assert "main:app" in text  # only stops this project's server
