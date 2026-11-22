<#
.SYNOPSIS
  Mantiene R.E.I.G.E.L. y Ollama en marcha en esta computadora ("tu PC como servidor").

.DESCRIPTION
  - Arranca Ollama si no responde y lo vigila cada 30 segundos.
  - Arranca el servidor de R.E.I.G.E.L. en 127.0.0.1 y lo reinicia si se cae,
    esperando cada vez más (5 s, 10 s, 20 s… hasta 5 min) si falla seguido.
  - Mientras corre, pide a Windows que no se suspenda (la pantalla sí puede
    apagarse). Al terminar el proceso, Windows vuelve a su configuración normal.
    No cambia ninguna opción de energía.
  - Una sola copia a la vez (mutex con nombre).
  Lo lanza la tarea programada de scripts/install_autostart.ps1; también se puede
  correr a mano. Con -Preview usa la demo sintética y no toca la base comercial.
#>
param(
    [int]$Port = 8765,
    [switch]$Preview,
    [switch]$PermitirSuspension,
    [int]$MaxEsperaSegundos = 300
)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir

$logDir = if ($Preview) { Join-Path $env:TEMP 'reigel-preview-logs' } else { Join-Path $env:LOCALAPPDATA 'PowerSolar\logs' }
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$supervisorLog = Join-Path $logDir 'supervisor.log'
function Write-SupervisorLog([string]$message) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message" | Add-Content -LiteralPath $supervisorLog -Encoding utf8
}

$mutexName = if ($Preview) { "Local\ReigelSupervisorPreview$Port" } else { 'Local\ReigelSupervisor' }
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)
if (-not $createdNew) {
    Write-SupervisorLog 'Ya hay un supervisor en marcha; esta copia termina.'
    return
}

if (-not $PermitirSuspension) {
    Add-Type -Namespace ReigelPower -Name Native -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: el sistema no se suspende mientras este proceso viva.
    [void][ReigelPower.Native]::SetThreadExecutionState([uint32]2147483649)
    Write-SupervisorLog 'Windows no se suspenderá mientras el supervisor esté activo (la pantalla sí puede apagarse).'
}

$ollamaExe = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
function Test-Ollama {
    try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null; return $true } catch { return $false }
}
function Start-OllamaIfNeeded {
    if (Test-Ollama) { return }
    if (-not (Test-Path -LiteralPath $ollamaExe)) {
        Write-SupervisorLog 'Ollama no está instalado; el chat sigue funcionando sin IA.'
        return
    }
    Write-SupervisorLog 'Ollama no responde; se inicia.'
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 500
        if (Test-Ollama) { Write-SupervisorLog 'Ollama listo.'; return }
    }
    Write-SupervisorLog 'Ollama no respondió después de 20 s; se reintentará.'
}
function Test-Server {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3
        return $health.status -eq 'ok'
    } catch { return $false }
}

$python = Join-Path $projectDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
if (-not $env:REIGEL_CHAT_AI) { $env:REIGEL_CHAT_AI = 'ollama' }
$serverArgs = if ($Preview) {
    @('scripts/preview_team_caguas.py', '--port', "$Port", '--ia-local')
} else {
    @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', "$Port", '--no-access-log')
}

Write-SupervisorLog "Supervisor iniciado (PID $PID, puerto $Port$(if ($Preview) { ', demo sintética' }))."
$wait = 5
try {
    while ($true) {
        Start-OllamaIfNeeded
        if (Test-Server) {
            # Otro proceso (por ejemplo start.ps1) ya atiende el puerto: solo se vigila.
            Start-Sleep -Seconds 60
            continue
        }
        Write-SupervisorLog "Se inicia el servidor en 127.0.0.1:$Port."
        $server = Start-Process -FilePath $python -ArgumentList $serverArgs -WorkingDirectory $projectDir `
            -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $logDir 'server.log') -RedirectStandardError (Join-Path $logDir 'server-error.log')
        $null = $server.Handle  # conserva el código de salida
        $started = Get-Date
        while (-not $server.WaitForExit(30000)) {
            Start-OllamaIfNeeded
        }
        $ranFor = (Get-Date) - $started
        Write-SupervisorLog "El servidor se detuvo (código $($server.ExitCode)) después de $([int]$ranFor.TotalSeconds) s."
        # 5 s tras una caída aislada; si vuelve a caer en menos de 5 min, la espera se duplica.
        if ($ranFor.TotalMinutes -ge 5) { $wait = 5 }
        Write-SupervisorLog "Reinicio en $wait s."
        Start-Sleep -Seconds $wait
        $wait = [Math]::Min($wait * 2, $MaxEsperaSegundos)
    }
} finally {
    if (-not $PermitirSuspension) { [void][ReigelPower.Native]::SetThreadExecutionState([uint32]2147483648) }
    Write-SupervisorLog 'Supervisor detenido.'
    $mutex.ReleaseMutex()
}
