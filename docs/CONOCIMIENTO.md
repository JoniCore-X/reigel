# Información de Power Solar en R.E.I.G.E.L.

El conocimiento específico de la compañía se obtiene de tres páginas del dominio corporativo `powersolarpr.com`: inicio, información de la empresa y tiendas. `powersolarprr.com` es otro dominio y no se mezcla con estas fuentes. El contenido de una web es evidencia de lo que publica esa web; no demuestra por sí solo disponibilidad, cumplimiento contractual ni resultados para un cliente.

## Qué se actualiza

`reigel/knowledge.py` consulta HTML directamente mediante HTTPS, sin buscador de pago, proveedor de IA ni claves externas. El trabajador `KnowledgeBase.run(stop)` revisa las fuentes cada seis horas mientras la aplicación está funcionando y tiene conexión. También se puede llamar a `await knowledge.refresh(force=True)` desde un control administrativo. No realiza tareas cuando la computadora o el servidor están apagados.

El caché guarda únicamente los identificadores de hechos reconocidos, hash del documento, cabeceras de validación y fechas; no conserva testimonios ni una copia completa del sitio. Hay límites de tiempo y tamaño, validación de tipo de contenido, lista cerrada de URLs y rechazo de redirecciones externas. Los scripts de la página no se ejecutan ni se convierten en instrucciones.

Las respuestas son paráfrasis redactadas en el código y se activan cuando la página contiene la evidencia exigida. Los temas disponibles son servicios, descripción de la empresa, respaldo condicionado con batería, proceso y enlace a localizaciones. Las direcciones y horarios concretos de tiendas no se inventan a partir de un mapa que requiere JavaScript. Un cambio de redacción puede desactivar un tema hasta revisarlo.

Precios, ofertas, descuentos, financiación, incentivos, garantías, cifras de ahorro y testimonios no se importan automáticamente para vender. Requieren condiciones verificadas por el equipo y, cuando corresponda, una propuesta para el cliente. La página inicial de Power Solar contiene una formulación general de “servicio ininterrumpido” y otra más precisa que condiciona el respaldo a batería, consumo y equipos seleccionados. El asistente usa la explicación condicionada: no promete energía indefinida ni cobertura de toda la casa.

## Conocimiento técnico general

El catálogo técnico es independiente de las fuentes corporativas y no las reemplaza. Está definido de forma estructurada en `TECHNICAL_TOPICS` y `TECHNICAL_SOURCES` dentro de `reigel/knowledge.py`. La recuperación usa patrones temáticos deterministas; sólo devuelve paráfrasis redactadas en el código y enlaces HTTPS de fuentes oficiales. No descarga documentos técnicos ni incorpora su texto como instrucciones. Las páginas corporativas existentes conservan su propio proceso de extracción y caché.

Referencias verificadas para el catálogo inicial:

| Fuente | Temas respaldados |
|---|---|
| [U.S. Department of Energy · Solar Integration: Inverters and Grid Services Basics](https://www.energy.gov/cmei/systems/solar-integration-inverters-and-grid-services-basics) | Conversión CC/CA, propósito del inversor, microinversores, desconexión del inversor ante interrupciones fuera de límites y sistemas solares con almacenamiento diseñados para operar sin red. |
| [U.S. Energy Information Administration · Measuring Electricity](https://www.eia.gov/energyexplained/electricity/measuring-electricity.php) | Diferencia entre potencia (kW) y energía acumulada (kWh), y lectura general del consumo eléctrico medido. |

Las referencias fueron revisadas el 5 de noviembre de 2026 y el código deja de usarlas después de 180 días sin nueva revisión. No existe una actualización automática para este catálogo estático: una persona debe volver a comprobar la fuente y actualizar la fecha y paráfrasis al revisar el tema. La fecha es revisión editorial de esas páginas, no una garantía de que una norma, tarifa o instalación particular siga vigente.

Los temas que el catálogo deja expresamente pendientes de revisión incluyen producción estimada, dimensionamiento, eficiencia, sistemas híbridos, medición neta en Puerto Rico, cargos o interpretación de facturas de LUMA, mantenimiento preventivo, seguridad eléctrica y vida útil de componentes. Ante esos temas o referencias vencidas, R.E.I.G.E.L. informa que no tiene una fuente vigente suficiente y ofrece atención humana; no estima ni deriva especificaciones comerciales.

El chat público sigue siendo determinista. `conversation.py` identifica las preguntas técnicas y `webchat.py` usa `KnowledgeBase.answer_technical`; ni Ollama ni el envío de canales externos participan en esta ruta. Las respuestas incluyen referencias que el chat presenta como enlaces. La información técnica general no confirma que Power Solar venda, instale o incluya un equipo específico.

## Fechas y fallos

Cada evidencia vence a las 24 horas desde su verificación, aunque la aplicación se reinicie. `checked_at` es la última revisión exitosa y `last_attempt_at` es el último intento; un error HTTP no renueva la vigencia. `changed_at` cambia cuando cambia la evidencia. `verification_method` distingue `direct_http` de `web_review`.

Un fallo conserva la evidencia anterior y su fecha. Si todavía está dentro de las 24 horas, la fuente aparece como `cached` y el estado general como `partial`; se puede responder usando esa revisión identificada. Cuando vence, la respuesta corporativa deja de estar disponible y el chat debe derivar al asesor o dar solamente educación general. `last_error` está disponible para el equipo; la vista pública no expone el diagnóstico técnico.

En la prueba directa del 30 de octubre de 2026, las tres páginas devolvieron HTTP 403 desde esta computadora, también mediante `www`. La herramienta web sí permitió revisar las páginas corporativas. El 403 impide afirmar que la actualización automática ya funciona contra ese servidor. El sistema deja registrado el bloqueo y vuelve a intentar en su próximo ciclo; no intenta resolver desafíos ni eludir controles del sitio.

El 11 de noviembre de 2026 se comprobó con `curl` que las tres rutas corporativas respondían HTTP 200 desde esta computadora. No se ejecutó el actualizador ni se renovó evidencia con esa comprobación; sigue siendo una observación de acceso, no una prueba de que el ciclo automático incorpore los cambios. La página de tiendas continúa dependiendo de JavaScript para mostrar ubicaciones y horarios.

## Registrar una revisión manual

Si una persona autorizada revisa la página mediante un navegador o una fuente accesible, puede registrar únicamente los temas que haya comprobado, con la fecha real. El comando no hace esa revisión por ella:

```powershell
python scripts/import_reviewed_knowledge.py --source home --topics services battery process --reviewed-at "FECHA-ISO-REAL-CON-ZONA"
```

Los temas permitidos son `services battery process` para `home`, `company` para `company`, y `locations` para `locations`. Una revisión antigua no reemplaza una más reciente, y una fecha futura es rechazada. El comando no borra el error de la consulta directa ni atribuye la revisión al actualizador HTTP. No debe incorporarse al arranque: hacerlo renovaría falsamente los datos. Después de 24 horas hace falta otra revisión real o una consulta automática exitosa.

## Comprobar el comportamiento

```powershell
python -m pytest tests/test_knowledge.py -q
python -m pytest tests/test_conversation_eval.py tests/test_webchat.py -q
```

Las pruebas usan transportes controlados: disponibilidad inicial, evidencia y referencias, respuestas 304, caducidad, bloqueo 403, caché sin falsa renovación, revisión manual, restricciones de URLs, redirecciones, tamaño, contenido y exclusión de scripts. También cubren recuperación técnica con referencias, caducidad, temas pendientes, separación de afirmaciones corporativas, contradicciones factuales, inyección en la consulta y entrega de enlaces desde el chat. No demuestran acceso continuo a páginas externas ni sustituyen la revisión de un profesional eléctrico.
