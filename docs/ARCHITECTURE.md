# Arquitectura de Power Solar

`main.py` compone FastAPI. `reigel/core.py` concentra autenticación, autorización, CRM y agenda; `api.py` expone HTTP; `channels.py` normaliza webhooks y envía mensajes; `assistant.py` usa OpenAI Responses con contexto acotado; `seo.py` genera metadatos públicos. La presentación continúa en HTML/CSS/JavaScript sin compilación. PHP y PostgreSQL eran opciones iniciales; no se necesitan para ejecutar esta versión.

SQLite usa WAL y conexiones cortas con claves foráneas. La base está fuera de OneDrive. Las reservas usan `BEGIN IMMEDIATE` para comprobar disponibilidad e insertar cita/prospecto en una transacción; un conflicto no deja registros parciales. Las horas se normalizan a UTC y los intervalos se calculan en la zona IANA del asesor, por defecto America/Puerto_Rico.

## Acceso y datos

Un administrador gestiona equipo, negocio y asignaciones. Cada asesor accede a los prospectos y conversaciones asignados y a su propia agenda. La autorización se aplica en servidor por operación. Las respuestas públicas de reservas no incluyen correos, teléfonos, notas ni registros de otras personas.

Contraseñas scrypt con sal aleatoria; tokens de sesión guardados como hashes; cookies HttpOnly, SameSite Strict y Secure en producción. Cambiar contraseña revoca sesiones. Se validan origen y host, se limitan solicitudes de acceso/captación/IA y se acotan cuerpos. Producción exige HTTPS; el proxy mantiene el servidor de aplicación en una red interna. Un único proceso/instancia mantiene coherentes los límites y la coordinación.

Meta requiere HMAC SHA-256 del cuerpo original; Telegram requiere el secreto del encabezado. Se filtran las cuentas destinatarias configuradas, grupos/tipos no compatibles y eventos duplicados. Los mensajes nuevos se asignan al asesor activo con agenda publicada menos cargado; si no existe, quedan en la cola de administración. Las conversaciones nuevas comienzan en modo humano.

## IA y automatización

El modelo no accede directamente a SQL ni tiene herramientas para reservar, modificar precios o enviar por su cuenta. La aplicación entrega el texto al adaptador solo para conversaciones expresamente activadas, al recibir un mensaje y mientras esté permitido responder. Una baja persiste y bloquea mensajes; pedir un humano pausa la IA. En Meta se verifica la ventana estándar de 24 horas. El agente dirige al formulario y no confirma citas desde el chat.

Los envíos no se reintentan ante un timeout ambiguo. `sent` significa aceptación con identificador del proveedor, no entrega/lectura. `uncertain` requiere revisión humana. Los fallos devuelven la conversación a modo humano.

Las respuestas automáticas se ejecutan en tareas de fondo, sin cola duradera. Una caída puede dejar un mensaje recibido sin respuesta; el equipo debe revisarlo. Antes de exigir SLA o ampliar volumen, incorporar cola duradera, monitorización y pruebas de recuperación.

## Operación

`scripts/backup.py` usa la API de backup de SQLite y verifica integridad. La copia contiene datos privados. Docker Compose prepara un servidor único con volumen persistente y HTTPS; no demuestra un despliegue realizado. El estado anterior se conserva en `backups/before-power-solar-20261028.zip`. No hay commits automáticos, datos comerciales inventados ni credenciales en el código.

Referencias: [FastAPI en contenedores](https://fastapi.tiangolo.com/deployment/docker/) y [SQLite WAL](https://www.sqlite.org/wal.html).
