param([switch]$Background, [int]$Port = 8765, [switch]$Preview)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
# Local Ollama is optional. Without the service, the deterministic chat keeps working.
if (-not $env:REIGEL_CHAT_AI) { $env:REIGEL_CHAT_AI = 'ollama' }
if ($Preview -and -not $PSBoundParameters.ContainsKey('Port')) { $Port = 8877 }
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Puerto fuera de rango.' }
try {
    $runningHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($runningHealth.status -eq 'ok' -and $runningHealth.database -eq $true) {
        Write-Output "R.E.I.G.E.L. ya está en ejecución: http://127.0.0.1:$Port/"
        return
    }
} catch { }
$projectPython = Join-Path $projectDir '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path -LiteralPath $projectPython) { $projectPython } else { (Get-Command python -ErrorAction Stop).Source }
& $pythonExe -c 'import fastapi, uvicorn, httpx, tzdata'
if ($LASTEXITCODE -ne 0) { throw 'Instala las dependencias: python -m pip install -r requirements.txt' }
$launchArgs = @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', "$Port", '--no-access-log')
if ($Preview) { $launchArgs = @('scripts/preview_team_caguas.py', '--port', "$Port") }
if ($Background) {
    $runtimeDir = if ($Preview) { Join-Path $env:TEMP 'reigel-preview-logs' } else { Join-Path $env:LOCALAPPDATA 'PowerSolar' }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $serverProcess = Start-Process -FilePath $pythonExe -ArgumentList $launchArgs -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir 'server.log') -RedirectStandardError (Join-Path $runtimeDir 'server-error.log')
    $serverReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ($serverProcess.HasExited) { throw 'El servidor no inició. Revisa server-error.log en la carpeta privada de PowerSolar.' }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1
            if ($health.status -eq 'ok' -and $health.database -eq $true) { $serverReady = $true; break }
        } catch { }
    }
    if (-not $serverReady) { throw 'El servidor aún no responde. Revisa el registro antes de volver a iniciarlo.' }
    Write-Output "R.E.I.G.E.L. iniciado (PID $($serverProcess.Id)): http://127.0.0.1:$Port/ · Equipo: /app"
} else {
    Write-Output "Power Solar: http://127.0.0.1:$Port/app (Ctrl+C para detener)"
    & $pythonExe @launchArgs
}
