<#
.SYNOPSIS
  Quita la tarea «R.E.I.G.E.L. servidor» y detiene el supervisor y el servidor que lanzó.
  No borra la base, las copias ni los registros. Ollama se deja como esté.
#>
param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskName = 'R.E.I.G.E.L. servidor'

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Tarea «$taskName» eliminada."
} else {
    Write-Output "No había una tarea «$taskName»."
}

# Supervisor: el PowerShell que ejecuta run_forever.ps1 (sin -Preview).
Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe'" |
    Where-Object { $_.CommandLine -match 'run_forever\.ps1' -and $_.CommandLine -notmatch '-Preview' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false; Write-Output "Supervisor detenido (PID $($_.ProcessId))." }

# Servidor: el proceso que escucha en el puerto, solo si es el uvicorn de este proyecto.
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    if ($process.CommandLine -match 'uvicorn' -and $process.CommandLine -match 'main:app') {
        Stop-Process -Id $process.ProcessId -Force -Confirm:$false
        Write-Output "Servidor detenido (PID $($process.ProcessId))."
    }
}
