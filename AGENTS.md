# R.E.I.G.E.L. — Team Caguas

Trabajar sobre este checkout existente. Responder con hechos comprobados, señalar
contradicciones y distinguir pruebas locales de publicación o entrega externa.

- Python/FastAPI, SQLite/WAL, HTML/CSS/JavaScript sin compilación obligatoria.
- `reigel/core.py`: autenticación, permisos y reservas transaccionales.
- `reigel/operations.py`: migraciones aditivas, CRM, actividades, tareas, avisos e indicadores.
- `reigel/api.py`: composición HTTP; reutilizar `actor`, `payload` y `DomainError`.
- `conversation.py` y `webchat.py`: decisiones deterministas, sesiones y reservas públicas.
  Rechazar llamadas y darse de baja son cosas distintas: «no me llamen» es
  `call_opt_out` —sigue el chat y queda una constancia `do_not_call` sin actor, que solo
  restringe—, y «no me escriban» o «dejen de escribirme» son `opt_out` y apagan la
  asistencia. Si el mensaje rechaza las dos cosas, manda la baja completa.
- Ollama local tiene tres rutas; no todas pasan por revisión humana:
  - `assistant.py`: borradores para revisión en `/api/assistant/draft`. También
    genera la respuesta que `channels.py` envía sin revisión previa cuando el
    equipo activa el modo `ai` en una conversación de un canal permitido (Meta
    bloqueado; Telegram solo si se configura).
  - `ai_chat.reply`: en `/chat`, sustituye la respuesta de respaldo de mensajes
    no clasificados ni técnicos y se publica al visitante tras validarse.
  - `ai_chat.stream_workspace` + `ia_workspace.py`: `/` y `/ia`, respuesta
    directa por SSE, emitida por frases ya validadas; historial propio (`ai_*`),
    separado del buzón comercial.
  Los validadores son de patrones (sin cifras, precios, promesas ni contactos),
  no una revisión semántica.
- `agent/`: motor comercial autónomo. `planner.py` decide por registro (función pura,
  determinista, sin base ni modelo); `runtime.py` ejecuta el ciclo y el bucle de fondo;
  `policy.py` fija la autorización de cada acción. Arranca apagado, solo crea tareas y
  avisos internos, y rechaza toda acción marcada como saliente: no envía mensajes, no
  marca llamadas y no cambia la etapa de un registro.
- `agent/calls.py`: preparación y cierre de llamadas. El sistema **no marca**: no hay
  centralita ni voz saliente, y una llamada comercial con voz de IA sin consentimiento
  escrito es ilegal bajo la TCPA. Registro de constancias de solo inserción donde «no
  llamar» es una más y la última manda. El plan se arma con reglas (ficha + memoria +
  informes abiertos) y lleva siempre lo que nunca se dice. El cierre entra por
  `store.create_activity`.
- `agent/needs.py`: informe de necesidad. Cuando el chat no puede responder (sin evidencia,
  validador que bloquea, modelo caído o petición de atención humana), la cola humana recibe
  qué necesita esa persona, qué contestó ya y qué falta por preguntar. Se arma con reglas,
  nunca con el modelo, porque hace falta justo cuando el modelo falló. La pregunta se guarda
  enmascarada. Se engancha en `webchat.message` (parámetro `needs`) y en `channels.py`.
- `agent/extract.py`: la conversación llena la memoria. Se extrae con patrones, nunca con
  el modelo, y se guarda una frase fija escrita de antemano: el texto del visitante no
  viaja a la memoria, que vuelve al modelo en la respuesta siguiente. Lo contestado a una
  pregunta directa entra como `lead_said`; una negativa literal también; el resto como
  `pattern`, que no se usa al hablar hasta que alguien lo aprueba en la cola de revisión
  (`/api/memory/pending`). Una lectura no sustituye lo que la persona contestó
  (`AUTHORITY`). No se extrae de una baja, de una solicitud de privacidad ni sin ficha.
- `agent/memory.py`: memoria del agente sobre cada cliente. Solo se inserta: una revisión
  enlaza la anterior y nada se sobrescribe. Cada creencia lleva procedencia, confianza y
  vencimiento; una deducción del modelo no se usa al hablar hasta que una persona la
  aprueba. `speaking_context` es la única puerta hacia un texto dirigido a un cliente.
  Retirar una creencia no la borra y no es una solicitud de eliminación de datos.
- `voice.py`: la voz comercial, una sola fuente para las tres rutas del modelo. Antes de
  añadir una instrucción nueva al prompt, medirla: el 26 nov 2026 una guía de criterio
  comercial no cambió nada medible y sí produjo la palabra prohibida «ahorrar», porque
  `STYLE` ya imponía lo que pedía. El prompt ronda los 8 000 caracteres sobre un modelo
  de 3B; cada añadido compite con lo que ya está.
- `knowledge.py`: evidencia con fuentes y vencimiento; un fallo no renueva su vigencia.
- `energy.py`: aritmética con parámetros explícitos, sin tarifas ni ahorros inventados.
- `privacy.py`: solicitudes administrativas con revisión humana; no elimina registros.
- `advisor_tools.py`: preparación autorizada y práctica comercial expresamente simulada.
- `frontend/index.html` y `frontend/js/app.js`: espacio privado `/app`.
- `/` y `/ia`: conversación generativa; no reserva, no deriva a humanos, no
  registra bajas ni solicitudes de privacidad, y lo remite a `/chat` («Citas y
  equipo»). `/chat`: chat de coordinación con reserva, atención humana, baja y
  privacidad. `/captacion`: landing existente. Conservar sus enlaces configurados.
  `/soluciones/certificaciones`: documentos de certificación del fabricante, transcritos
  con su referencia y enlazados a `energylibrary.tesla.com`. Solo equipos que Team Caguas
  instala, y cada norma dice también lo que **no** significa.

## Datos y seguridad

Preservar cambios locales sin commit. No leer, imprimir ni copiar `.env`, tokens,
credenciales, bases comerciales o datos de clientes para desarrollar. La base activa
pertenece a `%LOCALAPPDATA%/PowerSolar`, fuera de OneDrive. No abrir `main.py` como
aplicación para pruebas: `create_app(ruta_temporal)` aísla datos, no lee `.env`
y evita el refresco periódico externo. Solo `create_app()` sin ruta (main.py) o
`load_env=True` cargan `.env`. Las variables del proceso sí se leen: fijar
explícitamente `REIGEL_ENV`, `SITE_URL` y lo que necesite cada prueba.
No migrar la base comercial durante una tarea de desarrollo.

Todo acceso privado se autoriza en servidor. Asesor: solamente registros asignados;
administrador: permisos globales. Las reasignaciones deben revocar visibilidad
anterior, incluidos tareas, conversaciones y avisos. SQL parametrizado; escapar
texto en HTML. Conservar cookies HttpOnly/SameSite, controles de origen, límites de
solicitud y auditoría. Zona comercial: `America/Puerto_Rico`; persistir instantes UTC.

No enviar mensajes, ejecutar campañas, descargar modelos, activar servicios de pago,
publicar, hacer commits o push sin autorización explícita. El modelo no ejecuta SQL,
reservas ni herramientas. No prometer precios, ahorro, garantías o financiación.
Una baja comercial y una solicitud de eliminación son operaciones distintas.

## Verificación

Usar el entorno virtual existente:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Get-ChildItem frontend/js -Filter *.js | ForEach-Object { node --check $_.FullName }
node --test (Get-ChildItem tests -Filter *.test.cjs).FullName
```

Los comodines cubren los archivos nuevos sin editar este bloque. El 26 de
noviembre de 2026, en `main` tras la fase F: 1152 pruebas de Python, 20 archivos
JavaScript sin errores de sintaxis y 34 pruebas de Node en cuatro archivos
(`frontend_chat`, `frontend_ia`, `frontend_learning`, `frontend_operations`).
Pasar `tests` como carpeta a `node --test` falla: hay que expandir los archivos.
Una ejecución de Python deja un aviso de obsolescencia de `starlette.testclient`
originado en FastAPI, no en este código.

`budget.py` decide qué entra en el prompt antes de enviarlo: lo crítico —las reglas y
el mensaje de la persona— nunca se recorta, el historial se suelta por el turno más
viejo y queda en el registro, y si ni así cabe la ruta se niega en vez de mandar un
prompt sin reglas. `evaluacion/casos_ia.json` es la batería de 119 casos en dos
particiones; lo determinista corre en `tests/test_eval_battery.py` y lo que necesita el
modelo, en `scripts/evaluar_ia.py`. No afinar nunca contra la partición `final`: se gasta.

El prompt tiene que caber en la ventana del modelo. Cuando no cabe, Ollama no avisa:
recorta y responde igual, con la mitad de sus instrucciones. Así estuvieron los
borradores de `assistant.py` hasta el 26 de noviembre de 2026, rechazados uno a uno por
pasarse de largo. `tests/test_prompt_fits.py` compara el tamaño real de los tres prompts
con su ventana; si crece el prompt, falla esa prueba antes que el modelo.

Antes de añadir o quitar una instrucción del prompt, medirla contra el modelo:

```powershell
.\.venv\Scripts\python.exe scripts\medir_prompt.py
.\.venv\Scripts\python.exe scripts\medir_prompt.py --quitar STYLE --historial --muestras 3
```

Sin `--quitar` cuenta cuántas respuestas tira el validador y por qué; con `--quitar`
compara el prompt completo contra el mismo prompt sin esa constante de `voice.py`. No
abre la base ni lee `.env`, y necesita Ollama con el modelo instalado. Con pocas muestras
una diferencia pequeña es ruido: subir `--muestras` antes de concluir nada.

Para una demostración con cuentas ficticias y una base temporal nueva:

```powershell
.\scripts\start.ps1 -Preview
```

Abrir `http://127.0.0.1:8877/app`. El script imprime únicamente credenciales
del entorno sintético. No demuestra que la base comercial esté migrada,
que exista hosting ni que funcionen canales externos. Registrar el alcance y
limitaciones en `docs/TEAM_CAGUAS_IMPLEMENTATION.md`.
