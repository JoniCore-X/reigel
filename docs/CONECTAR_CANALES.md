# Conectar los canales del equipo

Configurar claves en `.env` del servidor y reiniciarlo. Nunca pegarlas en frontend, chats o repositorio. Ajustes muestra nombres de variables faltantes, no valores.

## Meta

Se necesitan activos empresariales autorizados, permisos vigentes y una aplicación de las cuentas Power Solar. Establecer `META_APP_SECRET`, `META_VERIFY_TOKEN` aleatorio y `META_GRAPH_VERSION` habilitada para la app, con formato `vNN.0`; no copiar una versión inventada.

- WhatsApp: `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN` con permiso para el número.
- Messenger: `MESSENGER_PAGE_ID`, `MESSENGER_PAGE_ACCESS_TOKEN` de la página.
- Instagram: cuenta profesional mediante **Instagram Login**, `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_ACCESS_TOKEN`. El adaptador usa `graph.instagram.com`; los tokens de otros flujos no son intercambiables.

Registrar callback `https://DOMINIO-REAL/webhooks/meta` con el mismo verify token, suscribir mensajes y completar permisos/revisiones de la cuenta. La app valida challenge, firma y destinatario. Probar cada canal desde una cuenta autorizada; verificar entrada, aceptación y recepción en dispositivo.

Se implementan respuestas de texto dentro de la ventana estándar. No se implementan plantillas WhatsApp, adjuntos, llamadas ni campañas masivas. El transporte controlado de tests no valida permisos de la cuenta.

Referencias: [WhatsApp oficial Meta](https://www.postman.com/meta/whatsapp-business-platform/request/8gvd47s/send-text-message), [Messenger](https://www.postman.com/meta/messenger-platform-api/documentation/iyp204x/messenger-platform-api), [Instagram](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

## Telegram

Crear el bot de empresa y guardar `TELEGRAM_BOT_TOKEN`. Generar un secreto fuerte e independiente para `TELEGRAM_WEBHOOK_SECRET`. Registrar mediante `setWebhook` la URL `https://DOMINIO-REAL/webhooks/telegram` y `secret_token`, usando una herramienta que no retenga el token en historial/logs. Este trabajo no registra el webhook sin la cuenta.

Solo chats privados y texto; grupos y otros tipos se omiten. El visitante debe iniciar el chat. [Referencia oficial Telegram](https://core.telegram.org/bots/api#setwebhook).

## IA

Configurar `OPENAI_API_KEY` de empresa y `OPENAI_MODEL` accesible en esa cuenta, con presupuesto autorizado. No hay modelo ficticio ni respuestas simuladas. Se utiliza `/v1/responses` y `store: false`; esto desactiva el almacenamiento del recurso de respuesta, no promete ausencia total de registros del proveedor.

Primero generar/revisar un borrador; después activar IA en una conversación de prueba y escribir desde el canal real. El asistente dirige a la reserva web, sin reservar desde el chat ni prometer financiación. [Documentación oficial OpenAI](https://developers.openai.com/api/docs/guides/text).

## Estados

`not_configured`: faltan variables. `configured_unverified`: hay valores, sin prueba de validez. `sent`: el proveedor aceptó con identificador. `uncertain`: fallo ambiguo sin reintento. Ninguno prueba automáticamente entrega o lectura.
