# Operación local · R.E.I.G.E.L.

Abrir `http://127.0.0.1:8765/` para la conversación con IA, `/chat` para reservas y atención humana, `/captacion` para el sitio y `/app` para el equipo. Iniciar con `scripts/start.ps1 -Background`. El servicio debe seguir encendido; el equipo apagado o suspendido no atiende ni actualiza fuentes.

Para verificar la estructura, dependencias, zona horaria, privacidad del índice Git y sintaxis JavaScript sin ejecutar las pruebas: `python scripts/doctor.py --sin-pruebas`. El diagnóstico completo ejecuta `python scripts/doctor.py` y `--json` produce salida estructurada. Pytest usa las bases temporales de sus fixtures; el diagnóstico no consulta ni modifica la base comercial y no envía datos.

El CRM incluye búsqueda y filtro de prospectos, fichas con historial, actividades registradas por el equipo, tareas y resultados. La agenda valida disponibilidad al guardar; los avisos internos persisten y no envían notificaciones al cliente. La calculadora energética necesita hipótesis explícitas. Privacidad distingue baja de comunicación y solicitudes de acceso, corrección y eliminación; su bandeja registra la revisión, pero no ejecuta borrados ni exportaciones. Ver [entrega de implementación Team Caguas](TEAM_CAGUAS_IMPLEMENTATION.md).

Para una demostración con una base SQLite temporal y cuentas ficticias separadas del acceso del equipo, iniciar `scripts/start.ps1 -Preview` y entrar en `http://127.0.0.1:8877/app`. La contraseña del administrador sintético aparece en la salida del comando; solo sirve para esa demostración. No usar la URL ni los datos de la demo para clientes.

La agenda local de la cuenta existente está habilitada de lunes a viernes de 09:00 a 17:00, hora de Puerto Rico, con intervalos de treinta minutos. Cambiar horarios, días y duración en Equipo y ajustes según disponibilidad real. La agenda no consulta compromisos de otros calendarios.

Las conversaciones web comienzan en modo automático. El botón Hablar con el equipo o una petición explícita pausa al asistente; el equipo responde desde Conversaciones y el cliente ve los mensajes mientras conserva su sesión. Una baja bloquea respuestas comerciales incluso manuales. Solamente el visitante reanuda escribiendo `/start`. Nunca se confirma una cita por haber escrito una intención: debe seleccionarse horario, dar contacto y consentimiento y pulsar Confirmar mi cita.

El panel R.E.I.G.E.L. muestra la disponibilidad real del modelo local y las fuentes, incluidas revisiones vencidas y errores. Actualizar fuentes es exclusivo del administrador. Las revisiones directas se intentan cada seis horas, con vencimiento a las veinticuatro horas. Un HTTP 403 se registra y no renueva la copia anterior. Si el sitio sigue bloqueando consultas, una persona debe revisar e importar evidencia usando `scripts/import_reviewed_knowledge.py`; leer primero `docs/CONOCIMIENTO.md`. No volver a fechar una revisión sin comprobar la fuente.

Ollama local genera borradores para revisar en `/app`, responde directamente en `/` e `/ia` y redacta el respaldo de mensajes no clasificados en `/chat`; esas respuestas públicas no pasan por revisión humana, solo por validadores de patrones. `/chat` usa reglas propias y hechos autorizados, nunca delega reservas ni decisiones financieras al modelo. Los servicios externos de costo no garantizado están bloqueados; Telegram es opcional y no está conectado. No se envían confirmaciones por SMS/email, ni campañas o recordatorios. Guardar referencia de cita o usar la exportación ICS desde Agenda.

El acceso administrador existente sigue vigente. El archivo temporal de acceso está en la carpeta privada de la base; cambiar contraseña desde el panel invalida las sesiones y permite eliminar ese archivo cuando ya no se necesite. No compartirlo ni subirlo al repositorio.

Los cambios de CRM y privacidad incluyen migraciones aditivas ejecutadas por `Store` al abrir SQLite. El servicio de producción no se reinició como parte de la implementación. Antes de habilitar estos cambios en la base activa, mantener el servicio detenido durante una copia consistente con `scripts/backup.py`, conservar la copia protegida y verificar integridad/espacio. No usar `/Preview` para cambiar la base del negocio.

Copias consistentes: `python scripts/backup.py` (o `--db RUTA` para una base concreta). El script abre la base en solo lectura y no construye `Store`, así que la copia refleja la base tal como estaba, antes de cualquier migración; si la base no existe, falla sin crear nada. Para recuperar, detener el servicio, conservar base/auxiliares, elegir una copia en una ubicación nueva y configurar REIGEL_DB_PATH. No restaurar sobre SQLite abierto ni compartirlo con OneDrive. Las copias no se suben a ningún servicio.

Clave de Google Authenticator: los secretos TOTP del equipo se cifran con `REIGEL_TOTP_KEY` o, si no existe, con el archivo `<base>.totp.key` junto a la base. `scripts/backup.py` copia ese archivo junto a la copia como `<copia>.totp.key` y avisa de guardarlo aparte y en un lugar seguro; si la clave viene de `REIGEL_TOTP_KEY`, recuerda que no está en la copia. Quien tenga la base y la clave puede leer los secretos, así que no se guardan juntas ni en OneDrive ni en una carpeta compartida.

Restaurar en una ruta nueva sin perder Google Authenticator:

1. Detener el servicio.
2. Copiar la base a la ruta nueva (por ejemplo `D:\PowerSolar\reigel.db`) y copiar la clave con el mismo nombre más `.totp.key` (`D:\PowerSolar\reigel.db.totp.key`). Si la clave está en `REIGEL_TOTP_KEY`, mantener esa variable con el mismo valor y no hace falta archivo.
3. Definir `REIGEL_DB_PATH` con la ruta nueva.
4. Comprobar antes de arrancar: `.\.venv\Scripts\python.exe scripts\doctor.py --sin-pruebas --base D:\PowerSolar\reigel.db`. Debe decir `[OK] Clave de Google Authenticator`.
5. Arrancar y entrar con contraseña y código.

Si falta la clave y hay cuentas registradas, el servidor no genera una clave nueva: las operaciones de Google Authenticator responden 503 y el registro del servidor y `doctor.py` indican qué restaurar. Solo cuando no existe ningún autenticador registrado se crea una clave nueva. Sin la clave original, la única salida es emitir un código de recuperación para cada persona.

Esta instalación escucha sólo en la computadora local. Atender clientes externos requiere un servidor accesible y HTTPS; no hay publicación ni hosting verificados. Docker/Compose son preparación y no prueban despliegue ni que Ollama esté disponible dentro del contenedor. El modelo no está incluido en Docker.
