# Power Solar · R.E.I.G.E.L.

Sistema comercial propio para Puerto Rico: chat web, CRM y reservas automáticas en esta computadora. No necesita API de pago. La base activa está fuera de OneDrive, en `%LOCALAPPDATA%/PowerSolar/reigel.db`.

## Uso local

```powershell
.\scripts\start.ps1 -Background
```

Chat público de clientes: <http://127.0.0.1:8765/> (la conversación con IA; también en `/ia`). Página de chat anterior con reserva: <http://127.0.0.1:8765/chat>. Sitio corporativo: <http://127.0.0.1:8765/captacion>. Equipo: <http://127.0.0.1:8765/app>. El acceso existente está en `local-access.txt` dentro de la carpeta privada de datos. No se crean ni muestran contraseñas nuevas. Si se instala en una computadora nueva: instalar `requirements.txt` y ejecutar `python scripts/bootstrap.py --email correo@empresa.com --name "Power Solar"` una sola vez.

El sitio público se organiza en páginas independientes: Inicio (`/captacion`), Empresa (`/empresa`), Equipo (`/equipo`), Planes R.E.I.G.E.L. (`/precios`), Soluciones (`/soluciones`), Evaluación (`/proceso`), Contacto (`/contacto`) y Preguntas frecuentes (`/preguntas`). Equipo presenta a Team Caguas y el contacto profesional de Joniel L. Martínez Rosario. Planes muestra una propuesta de suscripción con precios preliminares y un simulador; no procesa pagos ni crea cuentas. Comparten navegación y chat; el Google Form está únicamente en Contacto, con altura compacta y enlace directo a Google. Los enlaces antiguos de captación a evaluación, proceso, preguntas y privacidad se dirigen a sus nuevas páginas conservando parámetros de campaña. Incrustar el Form no demuestra una importación de respuestas al CRM. Las páginas públicas, el chat en `/chat` y `/app` muestran un cargador solar de entrada que sigue la carga real de la página, avisa si la conexión falla y se omite con movimiento reducido o colores forzados. Una ruta inexistente devuelve una página 404 con la identidad corporativa cuando la solicita un navegador, mientras las rutas de programa conservan la respuesta JSON; el icono local del sitio se publica en `/favicon.ico` y en las tres plantillas.

El espacio `/app` integra CRM, etapas ampliadas, historial, actividades, tareas, avisos internos, agenda, calculadora energética y revisión de solicitudes de privacidad. Prospectos ofrece vista de tabla y tablero por etapa; cambiar la etapa desde una tarjeta usa el mismo límite de permisos y queda en el historial. Preparar o iniciar una cita requiere consentimiento y horarios reales; métricas y montos proceden únicamente de registros. La calculadora requiere supuestos explícitos y no cotiza ni promete ahorro. El entrenador usa reglas de simulación visibles, no puntúa conversaciones reales.

Para explorar la interfaz con una base desechable y registros marcados ficticios: `scripts/start.ps1 -Preview`; abre <http://127.0.0.1:8877/app> e inicia con la contraseña sintética que imprime ese comando. El modo demo no carga `.env`, no utiliza la base activa y bloquea webhooks y actualización de fuentes. Consultar la [transferencia Team Caguas](docs/TEAM_CAGUAS_IMPLEMENTATION.md) para arquitectura, pruebas, cambios, alcance y operación. Las nuevas migraciones reales se aplican al iniciar `Store`; esta entrega no arrancó ni migró la base operativa.

El servidor debe permanecer encendido. `127.0.0.1` es acceso desde esta computadora; aún no es una página pública para clientes en Internet. No hay hosting ni suscripciones contratadas.

## Chat y agenda

- R.E.I.G.E.L. atiende en español con un motor comercial propio: prioridades, consumo aproximado, municipio, dudas y objeciones. Orienta hacia una evaluación sin inventar ofertas, ahorro, financiación ni resultados.
- Conversaciones persistentes y aisladas mediante cookie HttpOnly, con siete días de sesión. Los contactos escritos antes de dar consentimiento se ocultan; el formulario solicita consentimiento para crear el prospecto y la cita.
- Reserva real desde el chat o formulario: horarios publicados, zona de Puerto Rico, antelación mínima de una hora, máximo sesenta días, comprobación de cruces y protección contra reintentos duplicados. Sólo muestra confirmación tras guardar la reserva.
- Atención humana y respuestas desde Conversaciones. La baja bloquea al bot y al equipo; únicamente el visitante puede reanudar con `/start`.
- Las citas aparecen en Agenda y el prospecto en CRM. La etapa `cita` no equivale a venta. Contratos, propuestas, cobros y cierres no se ejecutan por conversar.
- Horario local habilitado inicialmente para la cuenta existente: lunes a viernes, 09:00–17:00, America/Puerto_Rico, citas de treinta minutos. Ajustarlo en Equipo y ajustes a la disponibilidad real.

## IA local y fuentes

Ollama en `127.0.0.1:11434` utiliza el modelo instalado `qwen2.5:3b`. Se comprueba el modelo local, se rechazan alias cloud, no se descargan modelos ni se envían prompts a OpenAI. El motor del chat sigue funcionando si Ollama no está disponible.

- Borradores del equipo (`/api/assistant/draft`): requieren revisión humana. Excepción: si el equipo activa el modo IA en una conversación de un canal externo permitido, `channels.py` envía la respuesta generada sin revisión previa y vuelve a modo humano ante un fallo. Meta está bloqueado; Telegram solo podría hacerlo si se configura.
- Chat de coordinación (`/chat`): la IA solo redacta respuestas a mensajes nuevos que el motor determinista no clasifica y que no son técnicos. Reservas, bajas, privacidad, precios, garantías, financiación y preguntas técnicas siguen bajo el motor propio. Una respuesta del modelo se descarta si incluye cifras, enlaces, datos de contacto, promesas comerciales, detalles técnicos sin fuente verificada o una gestión no realizada; en ese caso se muestra la respuesta determinista. La respuesta aceptada se publica al visitante sin revisión humana. El modelo no ejecuta SQL, reservas ni herramientas.
- Activación: `REIGEL_CHAT_AI=ollama` (también `1`, `on`, `yes` o `local`). Sin esa variable, `REIGEL_CHAT_AI=off`, o si Ollama no responde en 45 segundos, el chat usa solo el motor determinista. `REIGEL_CHAT_MODEL` permite otro modelo local instalado; los nombres con `cloud` se rechazan.
- Límites: 20 intentos de IA por minuto y cliente, 8 mensajes de historial saneado y salida de 220 tokens. `scripts/start.ps1` activa `REIGEL_CHAT_AI=ollama` al iniciar el servidor.

### Conversación pública: `/` y `/ia`

`/` es la conversación a pantalla completa con R.E.I.G.E.L. y la primera página que recibe a un visitante; `/ia` muestra la misma interfaz para enlaces directos. Los botones generales de conversación en las páginas públicas abren esta conversación solo si `GET /api/ia/status` confirma que el modelo local puede responder; si está desactivado, no responde o el servidor falla, abren el chat determinista en la misma página. En ambos casos conservan el mensaje preparado cuando el botón lo tiene; `/ia` ofrece «Volver» al sitio de origen.

`/ia` no registra reservas, atención humana, bajas ni solicitudes de privacidad. Esas acciones existen solo en el chat de coordinación `/chat` (motor determinista, consentimiento y reserva transaccional). Por eso `/ia` muestra «Citas y equipo» en la barra superior, en el menú «+» y en la bienvenida, y los textos y botones de las páginas corporativas que ofrecen reservar o hablar con el equipo enlazan a `/chat`. Pasar de `/ia` a `/chat` empieza otra conversación: el historial de `/ia` no se transfiere.

- Interfaz: barra lateral contraíble con historial, área de mensajes con desplazamiento propio, campo fijo abajo, mensajes conversacionales, estados de respuesta y detener. El logo de R.E.I.G.E.L. (entregado por el titular) aparece en la barra superior, en la pantalla inicial y como avatar de cada respuesta. En móvil el historial entra como panel lateral y el mismo campo queda fijo sobre el borde inferior.
- Historial: búsqueda en títulos y mensajes, y menú «⋯» por conversación para renombrar o eliminarla definitivamente (con confirmación). Solo el dueño puede hacerlo; eliminar se rechaza mientras se genera una respuesta.
- Bienvenida: seis temas con las ilustraciones oficiales del sistema residencial de Power Solar (placas, microinversores, batería, medición neta, red eléctrica y equipos) que llevan una pregunta al campo de mensaje.
- Menú «+» del campo de mensaje: Nueva conversación, Detener respuesta (solo mientras responde), Copiar última respuesta y Volver al sitio. Adjuntar archivos, Búsqueda web, Documentos y PDF y Crear imágenes aparecen deshabilitados bajo «Aún no disponible»; no existen en el servidor y no se simulan.
- Motor de IA: el servidor transmite por partes (`text/event-stream`) desde Ollama local. Solo envía al navegador frases completas después de que la validación de salida acepte todo el texto recibido hasta ese punto; si una frase no pasa, corta la generación y muestra un mensaje alternativo. Una transmisión que termina sin la señal final de Ollama se trata como error, no como respuesta completa. El navegador nunca recibe credenciales ni llama al modelo directamente. Si Ollama no responde, la interfaz lo informa y deshabilita el envío sin borrar el historial.
- Contexto: cada envío incluye hasta 20 mensajes previos de esa conversación, cada uno recortado a 2.000 caracteres; las respuestas guardadas que hoy no pasarían la validación no se reenvían al modelo. La validación de salida retira enlaces, precios, garantías, confirmaciones de citas, diagnósticos, promesas de financiamiento, atribuciones no verificadas a Power Solar y cualquier cantidad: dígitos, porcentajes, números escritos con palabras junto a unidades o a términos de ahorro, factura, respaldo o rendimiento, y promesas absolutas como factura en cero o independencia total.
- Privacidad: `/ia` no pide consentimiento, así que oculta correos y números de teléfono (7 a 15 dígitos) antes de guardar el mensaje; título, vista previa, historial y modelo reciben ya el texto oculto. Es un filtro de patrones: no detecta nombres, direcciones ni otros datos.
- Persistencia: tablas aditivas `ai_conversations`, `ai_messages` y `ai_visitors`. Cada mensaje y conversación tiene identificador único, dueño, estado y fechas UTC. Un usuario autenticado recupera sus conversaciones desde cualquier navegador al iniciar sesión; el visitante anónimo usa una cookie HttpOnly (`reigel_ia`) limitada a `/api/ia`.
- Conservación de visitantes: siete días desde la última actividad. Cuenta como actividad abrir `/ia` o enviar un mensaje; leer el historial no la renueva. El vencimiento en la base y la cookie del navegador se renuevan juntos. La purga de conversaciones vencidas ocurre al abrir `/ia`, como máximo una vez por hora y proceso, no exactamente al vencer. Las conversaciones autenticadas no se purgan por inactividad.
- Límites: 10 generaciones y 10 regeneraciones por minuto y cliente; conversaciones de hasta 200 mensajes, contando la pregunta y su respuesta como un turno que entra entero o se rechaza; respuesta de hasta 6.000 caracteres; mensaje de hasta 4.000 caracteres. Un cierre o error conserva solo la parte ya validada y emitida, marcada como detenida; si no había ninguna frase validada, la respuesta se descarta y se conserva el mensaje de la persona.
- Aislamiento: el identificador de conversación de otro dueño devuelve 404. Las respuestas de error no revelan si la conversación existe.


La vista R.E.I.G.E.L. del panel muestra modelo, agenda, última verificación y errores de fuentes. El servidor intenta consultar tres páginas corporativas cada seis horas; la evidencia vence a las veinticuatro horas. Un error nunca renueva la vigencia. El 30 de octubre de 2026 se revisó la portada mediante lectura web y se incorporaron servicios, respaldo condicionado y proceso; las consultas directas desde la PC devolvieron HTTP 403. Esa revisión no demuestra que el actualizador directo haya funcionado. Consultar [conocimiento](docs/CONOCIMIENTO.md).

WhatsApp, Instagram y Messenger tienen envíos bloqueados porque no se garantiza gratuidad total. Telegram queda opcional, sin configurar ni verificar; no es necesario para el chat. No hay envíos externos, campañas ni canales sociales conectados por esta instalación.

## Operación y comprobaciones

```powershell
python scripts/doctor.py
python scripts/doctor.py --sin-pruebas
python scripts/doctor.py --json
python scripts/backup.py
python -m pytest -q
node --check frontend/js/app.js
node --check frontend/js/operations.js
node --check frontend/js/public.js
node --check frontend/js/chat.js
node --check frontend/js/ia.js
```

Las pruebas crean bases temporales y transportes controlados. No son evidencia de ventas, mensajes externos o publicación. Hay copias consistentes verificadas mediante SQLite y SHA256 antes y después de la configuración.

El motor de `/chat` clasifica intenciones sin depender del modelo generativo. Ollama no decide reservas, precios ni financiación, pero no todas sus salidas son borradores: `/` y `/ia` y el respaldo de `/chat` publican texto validado por patrones sin revisión humana, como se describe arriba. Los escenarios reproducibles y los límites de esta evaluación están en [docs/CONVERSATION_EVALUATION.md](docs/CONVERSATION_EVALUATION.md).

Las notificaciones y recordatorios son internos y persistentes; no hay conexión bidireccional con calendarios. La exportación ICS no consulta Google Calendar u Outlook. No se implementan pagos, firma de contratos ni financiación. La electricidad, conexión y equipo siguen siendo recursos propios necesarios; no se prometen costos operativos absolutamente nulos. Las solicitudes de privacidad requieren decisión humana y no ejecutan borrado, exportación o corrección automática.
