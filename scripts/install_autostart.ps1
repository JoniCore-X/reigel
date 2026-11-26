<#
.SYNOPSIS
  Registra la tarea programada «R.E.I.G.E.L. servidor», que lanza scripts/run_forever.ps1
  con Windows para que Ollama y R.E.I.G.E.L. queden siempre encendidos en esta computadora.

.DESCRIPTION
  Lo corre el titular, en su propia terminal. Pasos:
    1. Copia de seguridad de la base comercial con scripts/backup.py (salvo -SinCopia).
       El primer arranque con el código nuevo añade columnas (propietario, código
       de cita); la copia permite volver atrás.
    2. Registra la tarea:
       - por defecto, al iniciar sesión en Windows (no pide permisos de administrador);
       - con -SinIniciarSesion, al encender la computadora aunque nadie inicie sesión
         (tipo S4U, sin guardar contraseña). Requiere abrir PowerShell como administrador.
       Se reinicia sola si falla, sin límite de tiempo y también con batería.
    3. La inicia ahora (salvo -NoIniciar).
  Para quitarla: scripts/uninstall_autostart.ps1
#>
param(
    [int]$Port = 8765,
    [switch]$SinIniciarSesion,
    [switch]$SinCopia,
    [switch]$NoIniciar
)
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$taskName = 'R.E.I.G.E.L. servidor'
$supervisor = Join-Path $projectDir 'scripts\run_forever.ps1'
$python = Join-Path $projectDir '.venv\Scripts\python.exe'

if ($SinIniciarSesion) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { throw 'Con -SinIniciarSesion abre PowerShell como administrador y vuelve a correr este script.' }
}

if (-not $SinCopia) {
    $dbPath = if ($env:REIGEL_DB_PATH) { $env:REIGEL_DB_PATH } else { Join-Path $env:LOCALAPPDATA 'PowerSolar\reigel.db' }
    if (Test-Path -LiteralPath $dbPath) {
        Write-Output 'Paso 1: copia de seguridad de la base comercial…'
        & $python (Join-Path $projectDir 'scripts\backup.py')
        if ($LASTEXITCODE -ne 0) { throw 'La copia de seguridad falló; no se registró la tarea.' }
    } else {
        Write-Output "Paso 1: no hay base en $dbPath todavía; no hace falta copia."
    }
} else {
    Write-Output 'Paso 1: copia de seguridad omitida (-SinCopia).'
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $projectDir `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisor`" -Port $Port"
$user = "$env:USERDOMAIN\$env:USERNAME"
if ($SinIniciarSesion) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Mantiene Ollama y R.E.I.G.E.L. encendidos en 127.0.0.1 (scripts/run_forever.ps1).' -Force | Out-Null
Write-Output "Paso 2: tarea «$taskName» registrada ($(if ($SinIniciarSesion) { 'al encender la computadora' } else { 'al iniciar sesión' }))."

if (-not $NoIniciar) {
    Start-ScheduledTask -TaskName $taskName
    $ready = $false
    foreach ($attempt in 1..40) {
        Start-Sleep -Milliseconds 750
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.status -eq 'ok') { $ready = $true; break }
        } catch { }
    }
    if ($ready) {
        Write-Output "Paso 3: R.E.I.G.E.L. responde en http://127.0.0.1:$Port/ · Equipo: /app"
    } else {
        Write-Output "Paso 3: la tarea arrancó pero el servidor aún no responde. Revisa $env:LOCALAPPDATA\PowerSolar\logs\"
    }
}
