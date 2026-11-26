# R.E.I.G.E.L. siempre encendido en tu computadora

Opción provisional («tu PC como servidor»). Mantiene Ollama y R.E.I.G.E.L.
funcionando sin tener que prenderlos. **No publica nada en internet:** el
servidor solo responde en esta computadora (`127.0.0.1`). Para que los clientes
lleguen desde fuera hace falta la opción de servidor en la nube o un túnel, que
es otra decisión.

## Qué hace

| Pieza | Qué hace |
|---|---|
| `scripts/run_forever.ps1` | Arranca Ollama si no responde, arranca el servidor y lo reinicia si se cae (5 s, luego 10, 20… hasta 5 min si falla seguido). Mientras corre, Windows no se suspende; la pantalla sí puede apagarse. Una sola copia a la vez. |
| `scripts/install_autostart.ps1` | Hace una copia de seguridad de la base, registra la tarea «R.E.I.G.E.L. servidor» y la inicia. |
| `scripts/uninstall_autostart.ps1` | Quita la tarea y detiene el supervisor y el servidor. No borra datos. |

Registros: `%LOCALAPPDATA%\PowerSolar\logs\` (`supervisor.log`, `server.log`,
`server-error.log`).

## Pasos (los haces tú)

1. **Cierra el servidor si lo tienes abierto** (la ventana de `start.ps1`).
2. Abre PowerShell en la carpeta del proyecto y elige una forma:

   Al iniciar sesión en Windows (no pide administrador):

   ```powershell
   .\scripts\install_autostart.ps1
   ```

   Al encender la computadora, aunque nadie inicie sesión (PowerShell **como administrador**; no guarda tu contraseña):

   ```powershell
   .\scripts\install_autostart.ps1 -SinIniciarSesion
   ```

3. El script hace la copia de seguridad, registra la tarea y confirma que
   `http://127.0.0.1:8765/app` responde.

**Antes del paso 2:** el primer arranque con el código nuevo añade a la base
comercial la marca de propietario (al administrador activo más antiguo) y los
códigos cortos de cita. El paso 1 del script guarda la copia para poder volver
atrás; confirma después en `/app` que el propietario eres tú.

## Lo que el script no puede hacer

- **Apagones y cortes de internet.** Si se va la luz, todo se apaga. Para que
  vuelva solo: activa en la BIOS/UEFI «Restore on AC power loss» (o «Power On
  after power failure»); para que no se apague: una UPS.
- **Reinicios de Windows Update.** Con `-SinIniciarSesion` vuelve solo después
  del reinicio; con la forma normal, cuando inicies sesión.
- **Suspensión cuando el supervisor no corre.** Tu configuración actual
  suspende a los 15 minutos; el supervisor lo evita solo mientras está activo.
- **Modelo de IA del servidor real.** Usa `REIGEL_CHAT_MODEL` de tu
  configuración (sin ella, `qwen2.5:3b`). La prueba con `llama3.2:3b` fue en la
  demo.

## Quitarlo

```powershell
.\scripts\uninstall_autostart.ps1
```
