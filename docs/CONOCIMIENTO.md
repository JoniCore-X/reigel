# Información de Power Solar en R.E.I.G.E.L.

El conocimiento específico de la compañía se obtiene de tres páginas del dominio corporativo `powersolarpr.com`: inicio, información de la empresa y tiendas. `powersolarprr.com` es otro dominio y no se mezcla con estas fuentes. El contenido de una web es evidencia de lo que publica esa web; no demuestra por sí solo disponibilidad, cumplimiento contractual ni resultados para un cliente.

## Qué se actualiza

`reigel/knowledge.py` consulta HTML directamente mediante HTTPS, sin buscador de pago, proveedor de IA ni claves externas. El trabajador `KnowledgeBase.run(stop)` revisa las fuentes cada seis horas mientras la aplicación está funcionando y tiene conexión. También se puede llamar a `await knowledge.refresh(force=True)` desde un control administrativo. No realiza tareas cuando la computadora o el servidor están apagados.

El caché guarda únicamente los identificadores de hechos reconocidos, hash del documento, cabeceras de validación y fechas; no conserva testimonios ni una copia completa del sitio. Hay límites de tiempo y tamaño, validación de tipo de contenido, lista cerrada de URLs y rechazo de redirecciones externas. Los scripts de la página no se ejecutan ni se convierten en instrucciones.

Las respuestas son paráfrasis redactadas en el código y se activan cuando la página contiene la evidencia exigida. Los temas disponibles son servicios, descripción de la empresa, respaldo condicionado con batería, proceso y enlace a localizaciones. Las direcciones y horarios concretos de tiendas no se inventan a partir de un mapa que requiere JavaScript. Un cambio de redacción puede desactivar un tema hasta revisarlo.

Precios, ofertas, descuentos, financiación, incentivos, garantías, cifras de ahorro y testimonios no se importan automáticamente para vender. Requieren condiciones verificadas por el equipo y, cuando corresponda, una propuesta para el cliente. La página inicial de Power Solar contiene una formulación general de “servicio ininterrumpido” y otra más precisa que condiciona el respaldo a batería, consumo y equipos seleccionados. El asistente usa la explicación condicionada: no promete energía indefinida ni cobertura de toda la casa.

## Fechas y fallos

Cada evidencia vence a las 24 horas desde su verificación, aunque la aplicación se reinicie. `checked_at` es la última revisión exitosa y `last_attempt_at` es el último intento; un error HTTP no renueva la vigencia. `changed_at` cambia cuando cambia la evidencia. `verification_method` distingue `direct_http` de `web_review`.

Un fallo conserva la evidencia anterior y su fecha. Si todavía está dentro de las 24 horas, la fuente aparece como `cached` y el estado general como `partial`; se puede responder usando esa revisión identificada. Cuando vence, la respuesta corporativa deja de estar disponible y el chat debe derivar al asesor o dar solamente educación general. `last_error` está disponible para el equipo; la vista pública no expone el diagnóstico técnico.

En la prueba directa del 30 de octubre de 2026, las tres páginas devolvieron HTTP 403 desde esta computadora, también mediante `www`. La herramienta web sí permitió revisar las páginas corporativas. El 403 impide afirmar que la actualización automática ya funciona contra ese servidor. El sistema deja registrado el bloqueo y vuelve a intentar en su próximo ciclo; no intenta resolver desafíos ni eludir controles del sitio.

## Registrar una revisión manual

Si una persona autorizada revisa la página mediante un navegador o una fuente accesible, puede registrar únicamente los temas que haya comprobado, con la fecha real. El comando no hace esa revisión por ella:

```powershell
python scripts/import_reviewed_knowledge.py --source home --topics services battery process --reviewed-at "FECHA-ISO-REAL-CON-ZONA"
```

Los temas permitidos son `services battery process` para `home`, `company` para `company`, y `locations` para `locations`. Una revisión antigua no reemplaza una más reciente, y una fecha futura es rechazada. El comando no borra el error de la consulta directa ni atribuye la revisión al actualizador HTTP. No debe incorporarse al arranque: hacerlo renovaría falsamente los datos. Después de 24 horas hace falta otra revisión real o una consulta automática exitosa.

## Comprobar el comportamiento

```powershell
python -m pytest tests/test_knowledge.py -q
```

Las pruebas usan transportes controlados: disponibilidad inicial, evidencia y referencias, respuestas 304, caducidad, bloqueo 403, caché sin falsa renovación, revisión manual, restricciones de URLs, redirecciones, tamaño, contenido y exclusión de scripts. No demuestran acceso continuo al sitio corporativo.
