# Operación local · R.E.I.G.E.L.

Abrir `http://127.0.0.1:8765/` para chat/reservas y `/app` para el equipo. Iniciar con `scripts/start.ps1 -Background`. El servicio debe seguir encendido; el equipo apagado o suspendido no atiende ni actualiza fuentes.

La agenda local de la cuenta existente está habilitada de lunes a viernes de 09:00 a 17:00, hora de Puerto Rico, con intervalos de treinta minutos. Cambiar horarios, días y duración en Equipo y ajustes según disponibilidad real. La agenda no consulta compromisos de otros calendarios.

Las conversaciones web comienzan en modo automático. El botón Hablar con el equipo o una petición explícita pausa al asistente; el equipo responde desde Conversaciones y el cliente ve los mensajes mientras conserva su sesión. Una baja bloquea respuestas comerciales incluso manuales. Solamente el visitante reanuda escribiendo `/start`. Nunca se confirma una cita por haber escrito una intención: debe seleccionarse horario, dar contacto y consentimiento y pulsar Confirmar mi cita.

El panel R.E.I.G.E.L. muestra la disponibilidad real del modelo local y las fuentes, incluidas revisiones vencidas y errores. Actualizar fuentes es exclusivo del administrador. Las revisiones directas se intentan cada seis horas, con vencimiento a las veinticuatro horas. Un HTTP 403 se registra y no renueva la copia anterior. Si el sitio sigue bloqueando consultas, una persona debe revisar e importar evidencia usando `scripts/import_reviewed_knowledge.py`; leer primero `docs/CONOCIMIENTO.md`. No volver a fechar una revisión sin comprobar la fuente.

Ollama local genera borradores para revisar. El chat público usa reglas propias y hechos autorizados, nunca delega reservas ni decisiones financieras al modelo. Los servicios externos de costo no garantizado están bloqueados; Telegram es opcional y no está conectado. No se envían confirmaciones por SMS/email, ni campañas o recordatorios. Guardar referencia de cita o usar la exportación ICS desde Agenda.

El acceso administrador existente sigue vigente. El archivo temporal de acceso está en la carpeta privada de la base; cambiar contraseña desde el panel invalida las sesiones y permite eliminar ese archivo cuando ya no se necesite. No compartirlo ni subirlo al repositorio.

Copias consistentes: `python scripts/backup.py`. Para recuperar, detener el servicio, conservar base/auxiliares, elegir una copia en una ubicación nueva y configurar REIGEL_DB_PATH. No restaurar sobre SQLite abierto ni compartirlo con OneDrive. Las copias no se suben a ningún servicio.

Esta instalación escucha sólo en la computadora local. Atender clientes externos requiere un servidor accesible y HTTPS; no hay publicación ni hosting verificados. Docker/Compose son preparación y no prueban despliegue ni que Ollama esté disponible dentro del contenedor. El modelo no está incluido en Docker.
