# Power Solar · R.E.I.G.E.L.

Sistema comercial propio para Puerto Rico: chat web, CRM y reservas automáticas en esta computadora. No necesita API de pago. La base activa está fuera de OneDrive, en `%LOCALAPPDATA%/PowerSolar/reigel.db`.

## Uso local

```powershell
.\scripts\start.ps1 -Background
```

Clientes: <http://127.0.0.1:8765/>. Equipo: <http://127.0.0.1:8765/app>. El acceso existente está en `local-access.txt` dentro de la carpeta privada de datos. No se crean ni muestran contraseñas nuevas. Si se instala en una computadora nueva: instalar `requirements.txt` y ejecutar `python scripts/bootstrap.py --email correo@empresa.com --name "Power Solar"` una sola vez.

El servidor debe permanecer encendido. `127.0.0.1` es acceso desde esta computadora; aún no es una página pública para clientes en Internet. No hay hosting ni suscripciones contratadas.

## Chat y agenda

- R.E.I.G.E.L. atiende en español con un motor comercial propio: prioridades, consumo aproximado, municipio, dudas y objeciones. Orienta hacia una evaluación sin inventar ofertas, ahorro, financiación ni resultados.
- Conversaciones persistentes y aisladas mediante cookie HttpOnly, con siete días de sesión. Los contactos escritos antes de dar consentimiento se ocultan; el formulario solicita consentimiento para crear el prospecto y la cita.
- Reserva real desde el chat o formulario: horarios publicados, zona de Puerto Rico, antelación mínima de una hora, máximo sesenta días, comprobación de cruces y protección contra reintentos duplicados. Sólo muestra confirmación tras guardar la reserva.
- Atención humana y respuestas desde Conversaciones. La baja bloquea al bot y al equipo; únicamente el visitante puede reanudar con `/start`.
- Las citas aparecen en Agenda y el prospecto en CRM. La etapa `cita` no equivale a venta. Contratos, propuestas, cobros y cierres no se ejecutan por conversar.
- Horario local habilitado inicialmente para la cuenta existente: lunes a viernes, 09:00–17:00, America/Puerto_Rico, citas de treinta minutos. Ajustarlo en Equipo y ajustes a la disponibilidad real.

## IA local y fuentes

Ollama en `127.0.0.1:11434` utiliza el modelo instalado `qwen2.5:3b` para borradores del equipo. Se comprueba el modelo local, se rechazan alias cloud, no se descargan modelos ni se envían prompts a OpenAI. Los borradores requieren revisión humana. El motor del chat sigue funcionando si Ollama no está disponible.

La vista R.E.I.G.E.L. del panel muestra modelo, agenda, última verificación y errores de fuentes. El servidor intenta consultar tres páginas corporativas cada seis horas; la evidencia vence a las veinticuatro horas. Un error nunca renueva la vigencia. El 30 de octubre de 2026 se revisó la portada mediante lectura web y se incorporaron servicios, respaldo condicionado y proceso; las consultas directas desde la PC devolvieron HTTP 403. Esa revisión no demuestra que el actualizador directo haya funcionado. Consultar [conocimiento](docs/CONOCIMIENTO.md).

WhatsApp, Instagram y Messenger tienen envíos bloqueados porque no se garantiza gratuidad total. Telegram queda opcional, sin configurar ni verificar; no es necesario para el chat. No hay envíos externos, campañas ni canales sociales conectados por esta instalación.

## Operación y comprobaciones

```powershell
python scripts/backup.py
python -m pytest -q
node --check frontend/js/app.js
node --check frontend/js/public.js
node --check frontend/js/chat.js
```

Las pruebas crean bases temporales y transportes controlados. No son evidencia de ventas, mensajes externos o publicación. Hay copias consistentes verificadas mediante SQLite y SHA256 antes y después de la configuración.

No se implementan recordatorios externos, sincronización bidireccional con calendarios, pagos, firma de contratos ni financiación. La exportación ICS no consulta Google Calendar u Outlook. La electricidad, conexión y equipo siguen siendo recursos propios necesarios; no se prometen costos operativos absolutamente nulos.
