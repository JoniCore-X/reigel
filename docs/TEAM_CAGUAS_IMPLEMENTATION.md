# R.E.I.G.E.L. — entrega Team Caguas

## Resultado

Se extendió el checkout existente con un centro privado de operaciones para CRM,
seguimientos, agenda, notificaciones y orientación preliminar. La implementación
conserva FastAPI, SQLite/WAL y el frontend HTML/CSS/JavaScript sin compilación.
El servidor no ejecuta ni realiza envíos externos por esta entrega.

## Funciones disponibles en el código

- Dashboard con filtros de periodo y métricas derivadas de los registros. Las etapas
  describen el estado actual; un importe aparece solo si se registró explícitamente.
- CRM con búsqueda, filtros, orden, paginación, edición, asignación administrativa,
  detección de duplicados dentro del ámbito autorizado, actividades y auditoría.
- Pipeline ampliado que conserva etapas antiguas y añade contacto pendiente, cita
  realizada, propuesta, negociación y demás fases. No reescribe etapas existentes.
- Tareas con tipo, responsable, prioridad, vencimiento, estado, resultado y aviso
  interno. Una tarea documenta actividad humana; no realiza llamadas ni envíos.
- Agenda con vista diaria/semanal, búsqueda de prospectos, reserva transaccional,
  cancelación, resultado tras terminar la cita, recordatorios internos e ICS.
- Notificaciones persistentes con lectura, deduplicación y permisos que se actualizan
  al reasignar prospectos.
- Calculadora matemática de energía con entradas declaradas y parámetros explícitos.
  Informa datos faltantes, hipótesis y límites. No deduce tarifas, ahorro ni precio.
- Solicitudes de acceso, corrección o eliminación desde el chat, con revisión
  administrativa y trazabilidad. Una solicitud de eliminación no borra registros.
- Preparador autorizado de orientaciones sin datos de contacto innecesarios y
  simulador de ventas con criterios visibles; la puntuación usa reglas textuales,
  no mide el desempeño real de una persona.
- Se mantienen el chat público, la landing, la agenda transaccional, el asistente
  local y el conocimiento con vigencia. Los borradores de Qwen pasan por revisión y
  el validador rechaza cifras, promesas y marcadores como `[Nombre del Cliente]`.

## Arquitectura y rutas nuevas

`reigel/operations.py` añade la migración aditiva `team_caguas_operations_v1` y
reglas de servidor para búsqueda CRM, historial, actividades, tareas, avisos, agenda
y dashboard. `reigel/energy.py` calcula orientación; `reigel/privacy.py` administra
solicitudes y eventos append-only; `reigel/advisor_tools.py` prepara fichas y ejecuta
una rúbrica simulada. `reigel/api.py` conecta rutas con la dependencia de sesión.
El modelo de lenguaje no recibe acceso SQL ni herramientas comerciales.

La API añade:

- `GET /api/leads` con búsqueda, etapa, asesor, orden y paginación.
- `PATCH /api/leads/{id}` para editar información y campos comerciales permitidos.
- `GET /api/leads/{id}` incluye historial, actividades, tareas, citas y duplicados.
- `POST /api/leads/{id}/activities`; CRUD limitado por permisos en `/api/tasks`.
- `GET /api/notifications` y `PATCH /api/notifications/{id}`.
- `GET /api/dashboard?period=...` y fechas personalizadas.
- `PATCH /api/appointments/{id}` admite cancelación y resultados de cita válidos.
- `POST /api/energy/calculate` recibe supuestos numéricos explícitos.
- `GET/PATCH /api/privacy/requests/{id}` expone revisión solo a administración.
- `GET /api/assistant/scenarios`, `POST /api/assistant/train` y
  `GET /api/leads/{id}/brief`.

La migración de operaciones crea tablas de actividad, historial, tareas,
notificaciones y recordatorios; agrega columnas opcionales al prospecto e índices.
La migración independiente de privacidad registra versiones 1 y 2, solicitudes y
un historial de revisión. Las pruebas repiten migraciones en bases temporales y
verifican integridad; ningún registro histórico recibe una etapa nueva en silencio.

## Interfaz y comprobaciones

`frontend/index.html`, `frontend/js/app.js`, `frontend/js/operations.js` y
`frontend/css/operations.css` integran las vistas privadas con las rutas reales.
Se mantienen las páginas públicas y sus assets. Chromium probó acceso, dashboard,
CRM y carga de tareas, agenda, notificaciones, calculadora, privacidad, entrenador y
ajustes. En un viewport de 360 px no se observó desbordamiento horizontal; menú
móvil y restitución de foco funcionaron. Las capturas locales de QA están en
`artifacts/team-caguas/`; no contienen datos comerciales.

Verificación ejecutada con `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check frontend/js/app.js
node --check frontend/js/operations.js
node --check frontend/js/chat.js
node --check frontend/js/public.js
.\.venv\Scripts\python.exe scripts/doctor.py --sin-pruebas
```

Resultado de la suite: **259 aprobadas, 0 fallidas**. Permanece una advertencia de
Starlette sobre el uso de `httpx` en `TestClient`; no afecta la ejecución actual.
El doctor local quedó `APROBADO` y confirmó estructura, dependencias, zona horaria,
privacidad del índice Git y sintaxis de seis scripts JavaScript. Ollama respondió
como disponible con `qwen2.5:3b` y completó una generación local para revisión.
El validador de borradores también rechazó marcadores sin completar en pruebas y la
generación comprobada no incluyó marcadores; toda salida sigue requiriendo revisión
humana antes de usarse.
El servicio directo de las fuentes corporativas aún puede devolver 403; una
generación de texto no verifica datos comerciales.

## Demostración reproducible

La demo utiliza una SQLite temporal nueva, cuentas y registros ficticios, bloquea
webhooks y actualizaciones de fuentes, y nunca carga `.env`. El script imprime la
contraseña y, desde el 25 de noviembre de 2026, la clave sintética de Google
Authenticator de las cuentas de demostración, solo para el entorno sintético:

```powershell
.\scripts\start.ps1 -Preview
```

Abre `http://127.0.0.1:8877/app`. La vista de operaciones se etiqueta
`DEMO SINTÉTICA`. La demostración confirma código local con datos simulados; no
certifica una migración de la base operativa, hosting, ventas ni entregas externas.

## Límite operativo actual

El archivo local existente tenía cambios sin commit al iniciar. Se conservaron,
se creó una copia de recuperación solo del código fuente en la carpeta temporal y
no se hizo commit, push ni despliegue. Tampoco se abrió, respaldó ni migró la base
privada comercial. El servicio de producción local no se reinició durante esta
entrega. Para utilizar las vistas nuevas allí hay que reiniciar la instalación con
el checkout actualizado; `Store` aplicará migraciones DDL aditivas al arrancar. La
base comercial permanece sin cambio en esta tarea. `scripts/preview_team_caguas.py`
es la ruta de comprobación segura antes de planificar por separado un reinicio del
servicio operativo.

Pendientes por decisión y verificación independiente: política de retención,
procedimiento de validación de identidad, y cumplimiento operativo de solicitudes
de acceso/corrección/eliminación. El CRM únicamente registra y revisa solicitudes;
no exporta ni elimina datos, no sustituye asesoría legal y no inventa plazos. Los
objetivos comerciales configurables no se añadieron; las métricas muestran solo
lo que el modelo de registros permite sostener.

## Arranque local del 7 de noviembre de 2026

Se ejecutó `scripts/start.ps1 -Preview -Background` y se confirmó que el proceso
del puerto 8877 utiliza `scripts/preview_team_caguas.py`. `/health` devolvió
`{"status":"ok","database":true}`; `/`, `/app`, `/captacion` y los scripts
`/static/js/app.js` y `/static/js/chat.js` respondieron HTTP 200.

Ollama se inició en segundo plano en `127.0.0.1:11434`; `/api/version` informó
`0.40.13` y `/api/tags` confirmó que `qwen2.5:3b` ya estaba instalado. No se
descargaron modelos ni se probó una generación durante este arranque.

Ambos servicios escuchan únicamente en `127.0.0.1`. La aplicación utiliza una
base temporal sintética: este arranque no abrió ni migró la base comercial,
no publicó un sitio y no verificó entregas por canales externos. Las respuestas
HTTP comprueban disponibilidad local; no sustituyen una prueba funcional completa.

## Google Forms: incorporación y dimensiones, 7 de noviembre de 2026

Se conservó el iframe existente con el URL aportado por el usuario y se añadieron
sus dimensiones HTML iniciales de 640 × 2682. La sección `/captacion#evaluacion`
ahora coloca el texto encima de una tarjeta centrada de hasta 780 px, con iframe
al 100 % del ancho y altura de 2682 px. Se eliminó la altura móvil arbitraria de
3200 px, se redujo el padding móvil y se añadió un enlace directo al mismo Form.
El contenido de Google puede necesitar desplazamiento dentro del iframe;
su altura no puede medirse automáticamente desde este origen.

La CSP permitía Google Forms en `/`, pero bloqueaba el iframe de `/captacion`.
Se corrigió la excepción únicamente para `/captacion`; `/`, `/app` y las API
conservan `frame-src 'self'`. Una prueba de regresión comprueba esta separación
y las demás cabeceras de seguridad. La demo sintética se reinició y las respuestas
HTTP confirmaron el nuevo HTML, CSS y CSP; el Form público respondió HTTP 200.

Verificación: **260 pruebas aprobadas**, dos advertencias (Starlette/httpx y
reescritura de aserciones de anyio); sintaxis de `app.js`, `chat.js` y `public.js`
correcta. La suite se ejecutó con `.venv` y `pytest.main(["-q"])`, sustituyendo
`reigel.api.load_environment` por una función vacía para impedir la lectura de
`.env`. La evaluación estática pasó. No se obtuvieron capturas ni comprobación
visual responsive: IAB no estaba disponible y el control nativo de Chrome se
detuvo al no identificar la URL con suficiente confianza. No se enviaron
respuestas al Form ni se verificó una importación de Google Forms al CRM.

### Corrección posterior del espacio vacío

La captura del usuario mostró que la altura fija de 2682 px dejaba un gran vacío
después del pie de Google en un paso corto del formulario. Se sustituyó por
`clamp(480px, 80vh, 760px)`, con altura HTML inicial de 720 px y CSS `?v=3`.
Se conserva el desplazamiento nativo dentro del iframe para los pasos más largos,
el ancho adaptable y el enlace directo a Google. Esta corrección sustituye la
altura fija descrita arriba; no intenta medir contenido de otro origen.

La demo existente sirvió HTML y CSS actualizados con HTTP 200 sin reiniciar ni
recrear su base. Se comprobó que solo hay un iframe, que no se bloquea su scroll,
que no quedan alturas CSS de 2682/3200 px y que la CSP sigue permitiendo Google
solamente en captación. `git diff --check` pasó para los dos archivos modificados.
La validación fue estática y HTTP; no se repitió la suite del backend por este
cambio de presentación ni se obtuvo una captura nueva del navegador.

## Revisión de producción y servidores, 7 de noviembre de 2026

**Veredicto: comprobado para demostración local; la preparación para producción
externa sigue pendiente.** Las verificaciones siguientes corresponden al checkout
actual con sus cambios sin commit y a una nueva base sintética temporal. No
acreditan publicación, migración de la base comercial ni entregas externas.

### Correcciones aplicadas en esta revisión

- El aviso de privacidad de la reserva en el chat apuntaba a un ancla inexistente.
  Ahora abre `/contacto#privacidad` con `noopener` y conserva la conversación.
- El chat trataba citas `completed` y `no_show` como confirmadas y bloqueaba una
  reserva posterior, aunque el servidor la permitía. Ahora muestra cada estado
  real y solamente `confirmed` bloquea otra reserva.
- Marketing generaba parámetros UTM pero el flujo actual de chat no registraba
  esa atribución. La interfaz describe el generador y declara que el seguimiento
  todavía no está integrado.
- El límite de 64 KiB de las solicitudes normales se comprobaba después de cargar
  todo el cuerpo. Ahora se consume por fragmentos y se rechaza al superar el
  máximo. Las regresiones prueban el corte temprano y la conservación del JSON
  válido en el límite. Los webhooks ya tenían su propio lector incremental con
  límite efectivo de 256 KiB; se conserva su verificación de firma.
- `tests/conftest.py` desactiva la lectura de `.env` para toda la suite. Una primera
  ejecución se detuvo al detectar que varios fixtures todavía podían cargar ese
  archivo; esa ejecución no se considera completamente aislada. La ejecución
  final normal de pytest ya utiliza el fixture nuevo y bases temporales.

### Evidencia actual

`python -m pytest -q` con el Python de `.venv`: **267 aprobadas, 0 fallidas**
en 37,60 s. Permanece una advertencia de deprecación Starlette/httpx.
Los comandos `node --check` solicitados, el doctor `--sin-pruebas` (siete archivos
JavaScript), `pip check` y `git diff --check` sobre los archivos de código
modificados en esta revisión pasaron.

Tras reiniciar únicamente la demo sintética, `/health` devolvió
`{"status":"ok","database":true}`. Ocho páginas (`/`, `/captacion`, `/app`,
`/contacto`, `/soluciones`, `/preguntas`, `/proceso`, `/empresa`) y sus 21 recursos
locales referenciados respondieron 200. El acceso administrativo ficticio y ocho
consultas privadas de operaciones respondieron 200. Sin sesión, los prospectos
devolvieron 401; un origen ajeno devolvió 403, un host ajeno 400 y un cuerpo
fragmentado sobredimensionado 413. Se comprobaron cookies HttpOnly/SameSite Strict,
`Cache-Control: no-store` y la excepción CSP para Google solamente en `/contacto`.
El formulario de evaluación está actualmente en esa ruta; las descripciones
anteriores de su iframe en `/captacion` corresponden a estados previos del sitio.

Una instancia adicional con base temporal y configuración de producción simulada
comprobó cookie Secure, HSTS y sesión autenticada. `TestClient` con origen HTTPS
simulado no demuestra un certificado ni TLS desplegado.

El resumen HTTP sin cookies, contraseñas ni registros de clientes está en
`artifacts/team-caguas/production-check-2026-11-07.json`.

La revisión visual no pudo completarse: `agent-browser` no estaba instalado y su
invocación mediante npx no produjo una sesión utilizable. El acceso de navegador
de Computer Use informó que su host no estaba disponible; el control nativo de
Chrome terminó al no identificar la URL con suficiente confianza. Se detuvo esa
vía sin insistir. No hay capturas nuevas ni aprobación visual de escritorio/móvil.
Un harness DOM temporal sí comprobó los cuatro estados de cita corregidos.

### Servicios dejados activos

- Demo: `http://127.0.0.1:8877/`; sitio en `/captacion`, evaluación en `/contacto`
  y equipo en `/app`. Se inició con `scripts/start.ps1 -Preview -Background` y se
  reinició después de las correcciones del servidor. Usa una base sintética nueva.
- Ollama: `http://127.0.0.1:11434`; versión reportada `0.40.13` y
  `qwen2.5:3b` presente en `/api/tags`. No se descargaron modelos ni se ejecutó
  generación para esta revisión.

Ambos escuchan solamente en `127.0.0.1`. No se inició `main:app`, no se abrió ni
migró la base comercial y no se hizo commit, push ni publicación.

### Pendientes antes de exposición a clientes

1. Comprobar escritorio y móvil en navegador real, incluido el formulario externo,
   teclado, desplazamiento y legibilidad. El CSS del chat todavía declara textos
   y controles de 6–10 px en anchos pequeños; requiere revisión visual.
2. Verificar dominio, HTTPS, proxy y operación del servidor de destino. Los archivos
   Docker/Compose/Caddy existentes son preparación; no prueban despliegue.
3. Probar restauración desde una copia consistente en un entorno aislado y definir
   vigilancia operativa. No se accedió a copias ni a datos comerciales aquí.
4. Resolver las decisiones operativas de retención, identidad y atención de
   solicitudes de privacidad ya pendientes, y comprobar por separado cualquier
   canal externo que se pretenda anunciar como disponible.
5. Fijar y verificar versiones para un despliegue reproducible: actualmente
   `requirements.txt` usa rangos y la imagen Caddy una etiqueta mutable. `pip check`
   confirma compatibilidad instalada; no equivale a una auditoría de vulnerabilidades.

## Continuación de CRM, agenda y tareas, 9 de noviembre de 2026

Se priorizó el recorrido del equipo sobre el checkout existente. Las correcciones
son de consistencia de formularios y registros; se conservaron los cambios locales
anteriores y no se abrió ni migró la base comercial.

- La agenda y las citas incluidas en la ficha CRM devuelven `reminder_hours` con el
  valor guardado, incluido cero. Antes, recargar la agenda eliminaba el campo de
  la respuesta y el formulario volvía a mostrar 24 horas.
- Mover una tarea a otro prospecto, o convertirla en tarea interna, actualiza la
  relación de su aviso. Se conservan identificación, fecha y lectura. Los avisos
  anteriores que todavía no coinciden con la tarea quedan fuera de alcance hasta
  regenerarse; no permiten abrir ni marcar un enlace obsoleto.
- Buscar prospectos en los formularios conserva la selección y sus datos aunque
  no aparezca entre las coincidencias. El reemplazo o la desvinculación requieren
  una selección explícita. Un error de búsqueda antiguo no sobrescribe el estado
  de una consulta más reciente.
- Agendar desde una ficha selecciona al asesor asignado y carga su disponibilidad.
  Un asesor solo recibe su propia agenda en el formulario. Si el responsable no
  tiene disponibilidad habilitada, administración debe elegir otro expresamente.
  Antes de confirmar, el formulario explica que cambiar el asesor reasigna el
  prospecto y sus tareas pendientes. Buscar sin cambiar de prospecto tampoco
  reinicia una elección manual de asesor.

### Verificación de esta iteración

La suite completa del entorno `.venv` terminó con **274 aprobadas, 0 fallidas**
en 37,31 s y la advertencia previa de Starlette/HTTPX. Incluye el ejecutor
`tests/test_frontend_operations.py`, que comprueba **10 casos Node** sobre los
controladores reales con elementos sintéticos. Estos casos prueban selección,
disponibilidad inicial, avisos y respuestas asíncronas; no son una prueba de
renderizado ni de accesibilidad de un navegador real.

Se añadieron regresiones HTTP de recordatorios con cero y tres horas, persistencia
al reabrir el almacén y aislamiento entre asesores, además de cuatro regresiones
de relación y alcance de avisos de tareas. Doctor, sintaxis de los siete JavaScript,
`pip check` y la comprobación de espacios del diff de los archivos rastreados
modificados en esta iteración pasaron.

Se reinició únicamente la demo sintética creada para esta revisión. **29 peticiones
HTTP** comprobaron login ficticio, alta de prospectos, cambio de relación de tarea,
aviso actualizado, acceso ajeno denegado, reserva, recordatorio persistente,
cancelación que libera el horario y tarea completada sin aviso pendiente.
El resumen sin cookies ni contraseñas está en
`artifacts/team-caguas/operations-check-2026-11-09.json`.

La demo permanece en `http://127.0.0.1:8877/app`, con una base temporal nueva y
cuentas ficticias. El host del navegador integrado informó que no estaba
disponible: no se realizó una nueva revisión visual ni se generaron capturas.
No se hizo commit, push, publicación, generación de mensajes ni envío externo.

### Otros pendientes confirmados

- Al reasignar un prospecto, las tareas realizadas o canceladas conservan su
  responsable anterior y dejan de aparecer para ambos asesores por la combinación
  de filtros actual. Administración aún ve los registros. Falta resolver el acceso
  al historial y su edición sin atribuir el trabajo pasado al asesor nuevo.
- Un prospecto sin asignar puede figurar con seguimiento vencido en el dashboard
  administrativo sin generar el aviso correspondiente, porque la derivación de
  avisos filtra prospectos sin asesor. No se modificó esa regla en esta iteración.

## Página pública de equipo, 11 de noviembre de 2026

Se añadió la ruta `/equipo` como séptima página corporativa. Presenta a Team Caguas
con el copy conservador del sitio: orientación sobre consumo, propiedad y respaldo,
sin precios, ahorros, garantías, financiación ni cifras corporativas no evaluadas.
La ficha de contacto usa únicamente los datos de la tarjeta de presentación aportada
por el usuario: Joniel L. Martínez Rosario, Consultor Profesional, teléfono
+1 (939) 210-4722, joniel.powersolar@gmail.com y www.powersolarpr.com. No se
inventaron biografías, fotografías ni otros integrantes.

La ruta se registró en `reigel/seo.py`, se enlazó en el menú móvil, la navegación
de escritorio, el directorio de Inicio y el pie de página, y se añadió una ficha y
tres principios con clases existentes. También se corrigió el ancho de la rejilla
del menú móvil corporativo, que reservaba una columna de 42 px para un icono ausente
y truncaba los nombres de todas las páginas. La corrección está limitada a
`.corporate-body` y al breakpoint de 1240 px.

Verificación:

- `pytest -q`: **275 aprobadas, 0 fallidas**, 36,79 s, una advertencia de
  Starlette/HTTPX ya conocida.
- `pytest` selectivo de páginas corporativas, núcleo y límite de cuerpo: **31
  aprobadas**.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**; siete archivos JavaScript sin
  errores de sintaxis.
- Preview sintético en `127.0.0.1:8877`: `/equipo` respondió 200; cabeceras
  `x-robots-tag: noindex, nofollow` y CSP con `frame-src 'self'`; enlaces `tel:`,
  `mailto:` y del sitio web presentes; navegación hacia `/equipo` presente en
  `/captacion` y `aria-current` aplicado solo a la página activa.
- Revisión visual con navegador: escritorio a 1440 px y vista móvil del navegador
  integrado. El menú móvil muestra Inicio, Empresa, Equipo, Soluciones, Evaluación,
  Contacto y Preguntas completos; el botón de respaldo abrió el chat con el mensaje
  preparado. No se probaron envíos externos ni se envió ningún mensaje. Capturas:
  `artifacts/team-caguas/equipo-desktop-1440.png`,
  `equipo-mobile-596.png` y `equipo-mobile-menu-open.png`.

Límites: el preview usa una base temporal y datos ficticios; la página no demuestra
publicación, dominio, hosting ni aprobación corporativa. La tarjeta del usuario es
la fuente de los datos de contacto y debe actualizarse si cambia. No se hizo commit,
push ni publicación.

## Imágenes y categorías oficiales en `/equipo`, 11 de noviembre de 2026

Se sustituyó el selector de tres temas por una sección de tres tarjetas con las
categorías que Power Solar publica en su sitio: Solar para tu hogar, Baterías para
apartamentos y Soluciones comerciales. Cada tarjeta usa fotografía local, copy
descriptivo y el mismo mensaje preparado del chat; no se publican precios, ahorros,
garantías, financiación, disponibilidad ni cifras corporativas. La nota al pie
identifica la fuente y la fecha de consulta.

Se añadió `paneles-solares-edificio-comercial-puerto-rico.jpg` desde
`powersolarpr.com` y se documentó en `frontend/assets/power-solar/SOURCES.md`. La
sección oscura usa un campo de puntos adaptado de Uiverse / kennyotsu
(`short-warthog-33`), registrado en `docs/UIVERSE_COMPONENTS.md` y en el aviso MIT.
La adaptación es estática, no oculta contenido y conserva el contraste del texto.
Las tarjetas mantienen el texto visible sin hover, foco visible en el botón y una
alternativa sin transición para movimiento reducido.

Verificación de esta ampliación:

- `pytest -q`: **275 aprobadas, 0 fallidas**.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**.
- `/equipo` en el preview: las tres imágenes responden 200, las tres categorías
  aparecen una sola vez y la página conserva `x-robots-tag: noindex, nofollow`.
- Revisión visual con capturas `artifacts/team-caguas/equipo-soluciones-desktop-1440.png`
  y `equipo-soluciones-mobile-596.png`: sin desbordamiento horizontal. La tercera
  imagen se verificó después de desplazarse hasta la tarjeta, porque usa carga
  diferida. Los tres botones abren el chat y colocan su mensaje preparado; no se
  envió ningún mensaje.

Límites: la sección describe categorías publicadas por Power Solar; no confirma que
el equipo las venda, instale o incluya en una propuesta. La inclusión de imágenes no
indica aprobación corporativa del software. No se hizo commit, push ni publicación.

## Rediseño visual de `/equipo`, 11 de noviembre de 2026

Se elevó el tratamiento editorial de la página sin cambiar rutas, textos verificados,
mensajes preparados del chat ni datos de contacto:

- Hero a dos columnas con titular de dos líneas, fotografía residencial local en un
  marco desplazado (plato azul marino, regla naranja, sombra y pie de foto) y fondo
  con degradado, textura de puntos y entrada breve. La imagen se reutiliza en la
  primera tarjeta por ser la única fotografía residencial oficial disponible.
- Perfil con monograma `JM`, anillo de acento, cita en serif itálica, tarjeta de
  contacto elevada y enlaces con subrayado y flecha en el mismo tono corporativo.
- Tarjetas de soluciones con etiqueta sobre la fotografía, degradado inferior, zoom
  y saturación al hover/foco, elevación de 5 px, regla naranja progresiva y flecha
  circular que cambia a azul marino. Las tarjetas pasan a disposición horizontal
  entre 601 y 900 px y vuelven a columna en móvil.
- La franja oscura de principios añade dos resplandores radiales (cálido y frío)
  sobre el campo de puntos ya adaptado de Uiverse / kennyotsu.
- Los efectos se desactivan con `prefers-reduced-motion: reduce` y no dependen de
  JavaScript ni de animaciones ligadas al desplazamiento: el contenido permanece
  visible si no hay soporte de animación o el usuario imprime la página.
- `frontend/landing.html` actualiza las hojas de estilo a `?v=2` para invalidar la
  caché del navegador; la integración posterior del botón luminoso las eleva a
  `?v=3`.

Verificación del rediseño:

- `pytest -q`: **275 aprobadas, 0 fallidas**.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**; siete archivos JavaScript sin
  errores de sintaxis.
- Capturas actualizadas `artifacts/team-caguas/equipo-soluciones-desktop-1440.png`
  (1440 × 3357) y `equipo-soluciones-mobile-596.png` (596 × 5538), sin desbordamiento
  horizontal.
- Estados de interacción comprobados con Chrome DevTools forzando `:hover` y
  `:focus-within`: tarjeta elevada (`translateY(-5px)`), imagen a `scale(1.055)`,
  flecha con fondo `rgb(7, 29, 67)` y regla naranja completa; `scrollWidth` igual a
  `clientWidth`.
- No se añadió JavaScript nuevo ni se envió ningún mensaje del chat.

Límites: la revisión es local y sintética; las capturas no demuestran publicación,
dominio, hosting, aprobación corporativa ni entrega de mensajes. No se hizo commit,
push ni publicación.

## Botón de conversión y psicología del color, 11 de noviembre de 2026

Se adaptó un botón de borde luminoso de Uiverse / SelfMadeSystem como
`.ui-psy-button` y se aplicó en tres puntos de decisión de `/equipo`:

- **Hero:** acción principal «Conversar con el equipo». Es el primer punto de
  contacto y concentra la decisión de iniciar la conversación.
- **Tarjeta de contacto del perfil:** «Conversar por el chat», junto al correo y el
  teléfono verificados. El botón ocupa el ancho de la tarjeta en móvil.
- **Cierre de página:** «Ir a Contacto» como enlace, no como botón de chat, porque
  el siguiente paso esperado es el formulario y no una conversación.

Las tres tarjetas de soluciones conservan su acción secundaria de texto con flecha.
Así la página mantiene una sola jerarquía principal por bloque y el botón luminoso
no compite consigo mismo.

Lectura de color aplicada al cliente:

- **Naranja (`#e96100` y `#f58a3c`):** energía, acción y urgencia moderada. Se usa
  en el borde y la flecha para señalar el siguiente paso sin prometer resultados.
- **Azul marino (`#071d43`, `#164494`, `#4a7fd1`):** confianza, estabilidad y
  respaldo corporativo. Es la superficie del botón y el color dominante del sitio.
- El degradado naranja→azul presenta la acción como un puente entre la energía del
  cliente y la seguridad de la marca. El giro y el pulso solo se activan en hover o
  foco, de modo que el movimiento aparece cuando hay intención y no distrae en reposo.
- El halo exterior se reconstruyó con tres radios estáticos (naranja a la izquierda,
  azul a la derecha y una luz central cálida), desenfoque de 17 px y una capa
  animada atenuada al 18 %. Sustituye el umbral de alfa sobre un degradado diagonal
  que producía dos manchas con caída irregular. Con hover o foco la capa animada
  sube a 45 % y el borde conserva su brillo.

Implementación y accesibilidad:

- Se conservan los filtros SVG en línea (`psy-unopaq`, `psy-unopaq-2`,
  `psy-unopaq-3`) dentro del fragmento, compatibles con la CSP estricta: no hay
  fuentes, CDN ni JavaScript externo.
- El `div` original sin nombre accesible se sustituyó por `<button>` nativo (chat) y
  `<a>` (contacto). Ambos tienen etiqueta visible, `aria-controls="reigel-chat"` y
  `aria-expanded` cuando abren el chat; el foco visible usa el anillo del sitio.
- Se corrigió el keyframe inválido del original y se limitó el giro a hover/foco con
  `animation-play-state`. Con `prefers-reduced-motion: reduce` se anulan animación y
  transición; con `forced-colors` se ocultan los brillos y se conserva un borde
  `ButtonText`.
- El ancho es automático y la altura mínima de 54 px; no se usan los `clip-path`
  fijos de 120 × 60 del original, que cortaban etiquetas en español y en móvil.
- `frontend/landing.html` mantiene `corporate.css` en `?v=3` y eleva
  `uiverse-components.css` a `?v=4` para invalidar la caché tras el ajuste del
  halo; se conservan los ajustes móviles y de accesibilidad anteriores.

Verificación:

- `pytest -q`: **276 aprobadas, 0 fallidas**; `scripts/doctor.py --sin-pruebas`:
  **APROBADO**.
- Con Chrome DevTools se forzó `:hover`: el botón mide 258 × 60 px, el halo animado
  pasa de 0.18 a 0.45, el borde intensifica su brillo y la animación a `running`
  (rotación observada ≈ 79.9°); el chat abre con `dialog.open`, el foco entra en el
  diálogo y los ocho disparadores quedan en `aria-expanded="true"`. No se envió
  ningún mensaje.
- Con movimiento reducido emulado, el brillo y la flecha quedan en `animation: none`
  y `transition: 0s`. En `forced-colors` se ocultan el halo y los giros, y se
  conserva el borde `ButtonText`.
- `scrollWidth` igual a `clientWidth` en 1440, 820, 596 y 390 px; las capturas
  `equipo-soluciones-desktop-1440.png` (1440 × 3395) y
  `equipo-soluciones-mobile-596.png` (596 × 5582) incluyen el halo actualizado.

Límites: el botón es una adaptación local con fines de presentación; no demuestra
conversión, publicación, hosting ni entrega de mensajes. Los textos no prometen
ahorros, precios, garantías ni citas. No se hizo commit, push ni publicación.

## Página de planes R.E.I.G.E.L., 11 de noviembre de 2026

Se añadió `/precios` como una página editorial dentro del shell corporativo. No
activa cobros, no crea cuentas y no presenta los montos como tarifas publicadas:

- Hero oscuro con la etiqueta «VISTA PRELIMINAR · SIN COBROS», escenario base de
  $149/mes y navegación a los planes y al simulador.
- Cuatro planes propuestos: Consultor ($29), Team Caguas ($149, recomendado),
  Team Pro ($299) y Corporativo (cotización). Cada tarjeta incluye su alcance,
  una nota de «Precio propuesto» y un enlace `mailto` para conversar; no hay
  botones de compra ni formularios de pago.
- Once módulos agrupados en «Primera versión» (CRM, agenda, IA comercial, panel
  del líder y suscripciones) y «Fases siguientes». La página aclara que describe
  un alcance propuesto y no disponibilidad actual.
- Jerarquía de propietario, administrador, vendedor y supervisor, con la regla de
  que cada cuenta tiene sesión y espacio propios y que una reasignación debe
  revocar la visibilidad anterior. El aislamiento multiempresa se presenta como
  requisito de diseño, no como una función ya demostrada.
- Simulador con dos controles: vendedores por equipo (1–15) y equipos (1–10).
  Usa $149 de base, $20 por vendedor adicional desde el sexto y aplica Team Pro
  ($299) desde 13 vendedores, cuando resulta más económico. Para 8 vendedores y
  1 equipo muestra $209/mes y $2,508/año, las mismas cifras del escenario base.
  Más de 15 vendedores por equipo no se simula: requiere cotización.
- El HTML entrega los valores del escenario base sin JavaScript. El archivo
  `pricing.js` actualiza los totales, expone etiquetas `aria-valuetext` y anuncia
  los resultados en una región `aria-live="polite"`. El botón «Restablecer
  ejemplo» devuelve 8 vendedores y 1 equipo.
- Sección de piloto propuesto de 14 días con condiciones por confirmar, lista de
  autorizaciones previas (marca, datos, documentos LUMA, integraciones y cobro) y
  preguntas frecuentes. Los límites de pago, exportación y cancelación quedan
  explícitos.
- `reigel/seo.py` registra `/precios` en el conjunto cerrado de páginas públicas;
  por tanto recibe metadatos, canonical cuando existe un origen HTTPS, sitemap y
  `aria-current`. El enlace «Planes» se añadió a la navegación de escritorio,
  móvil y al pie compartido.
- `frontend/landing.html` carga `pricing.css?v=2` y `pricing.js?v=1` con `defer`.
  Los estilos viven en `frontend/css/pricing.css` y se limitan a `.corporate-body`.
  La CSP no cambió: no hay CDN, fuentes externas, analítica ni pasarela de pago.

Verificación:

- `pytest -q`: **276 aprobadas, 0 fallidas**.
- La prueba corporativa exige que `/precios` comparta navegación, tenga un solo
  `h1`, no duplique IDs, incluya los cuatro precios y los once módulos, sirva los
  recursos locales y no contenga botones de compra, formularios de pago ni marcas
  de procesadores como Stripe o PayPal.
- Los valores del simulador se comprobaron en navegador para 8/1, 13/1 y 2
  equipos; también se verificaron teclado, reinicio y ausencia de desbordamiento
  horizontal en 1440 y 596 px. Las capturas quedan en
  `artifacts/team-caguas/precios-desktop-1440.png` y
  `precios-mobile-596.png`.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**.

Límites: la página es una propuesta local. Los precios no son tarifas de mercado
verificadas, no hay suscripciones activas, cobros, facturación ni cuentas de
R.E.I.G.E.L. La navegación y el simulador no demuestran hosting, aprobación de
Power Solar ni disponibilidad de los módulos. No se hizo commit, push ni
publicación.



## Cargador solar de entrada, 12 de noviembre de 2026

Se adaptó el cargador de 9 esferas de Uiverse / 20essentials como capa de entrada
de página en los tres shells: páginas públicas, chat de `/` y espacio `/app`. El
contenido sigue renderizado en el servidor; el cargador es una presentación de
marca que se retira sola y no sustituye rutas, datos ni mensajes.

Anatomía y color:

- **Rejilla orbital:** 9 `.ps-sphere` con 9 `.ps-item` cada una (81 discos). Cada
  esfera gira `--ps-rot * 20deg` y cada ítem `--ps-rot-y * 40deg`; el giroscopio
  rota en X e Y 360° cada 8 s con `perspective: 10000px` y `preserve-3d`.
- **Paleta solar:** los discos recorren rojo profundo (`#ff3d00`), naranja
  (`#ff5f00`, `#ff7a00`), ámbar (`#ff9d00`), oro (`#ffb703`), amarillo
  (`#ffd60a`, `#ffe066`), coral (`#ff7a45`) y pálido (`#fff1a0`), con alfa entre
  0.61 y 0.66 como los discos translúcidos del componente original.
- **Luz:** aura cálida, doble capa de rayos cónicos, corona cónica, dos capas de
  polvo punteado, dos destellos con ángulos propios, anillo de corona y núcleo
  blanco-amarillo con pulso.
- **Fondo:** transparente con difuminación (`backdrop-filter: blur(13px)
  saturate(118%)`, 10 px en móvil), sin retícula, viñeta ni tinte; la página se
  intuye detrás del cristal esmerilado. No se muestra marca, texto ni línea de
  progreso, solo el giroscopio solar y su corona, con un diámetro máximo de
  300 px (260 px en móvil).
- **Entrada y salida:** la etapa escala desde 0.82 en 1.05 s; la salida combina
  opacidad a 0, escala 1.045 y desenfoque de 7 px durante 520 ms.

Comportamiento:

- Un script externo y bloqueante en el `<head>` añade `html.ps-booting` antes del
  primer pintado. El marcado del cargador está `hidden` por defecto, de modo que
  sin JavaScript nunca aparece ni bloquea la lectura.
- El mínimo se cuenta desde que la capa se muestra, no desde el `<head>`: 1600 ms
  en la primera visita y 650 ms en las siguientes (clave de sesión
  `ps-loader-seen`). Ya no existe un tope fijo que oculte la capa mientras la
  página sigue cargando: la salida espera al evento `load` real.
- Se omite con puntero o `Escape`. Durante la entrada y el desvanecimiento, el
  `Escape` se captura y no cierra el `<dialog>` modal del chat que queda debajo.
- La retirada elimina `ps-booting`, `aria-busy` y la capa del top layer, y guarda
  la marca de sesión con tolerancia a almacenamiento no disponible. En una
  restauración desde bfcache se limpia de inmediato.
- El cargador es un popover manual (`popover="manual"` + `showPopover()`), por lo
  que se pinta por encima de cualquier `<dialog>` modal. `@supports
  selector(:popover-open)` lo mantiene oculto hasta mostrarlo; los navegadores sin
  esa API conservan la capa fija con `z-index: 9999` como respaldo.

Sincronía con la red y estado de error:

- La capa permanece mientras `document.readyState` no sea `complete`; si la red es
  lenta, sigue visible más allá de los antiguos 4.2 s en vez de descubrir una
  página a medio cargar.
- Si el navegador queda sin conexión durante la carga, tras 2.2 s aparece el aviso
  «Sin conexión a internet. Revisa tu red y vuelve a intentarlo.».
- Tres recursos que fallen (imagen, hoja de estilos, script o `source`) muestran
  «No pudimos cargar todo el contenido. Revisa tu conexión y vuelve a
  intentarlo.».
- Si la carga no termina en 15 s, el aviso es «La conexión está tardando más de lo
  normal.».
- El mensaje se presenta en una tarjeta de cristal bajo el sol, que se atenúa y
  detiene su giro. Ofrece «Reintentar» (`window.location.reload()`) y «Continuar al
  sitio»; `Escape` también cierra. El puntero sobre el fondo no descarta el aviso,
  para que los botones manden.
- Si el navegador vuelve a estar en línea, se limpia el aviso y se reanuda la
  espera o la salida. Un error mostrado no se borra solo porque `load` termine:
  la decisión queda en manos de la persona.

Accesibilidad y seguridad:

- `role="status"`, `aria-live="polite"` y un texto visualmente oculto: «Cargando
  Power Solar. La página estará lista en un momento.» El aviso de error usa
  `role="alert"` y recibe foco en «Reintentar» para que el teclado actúe de
  inmediato. Las capas decorativas son `aria-hidden`.
- `prefers-reduced-motion: reduce` y `forced-colors: active` omiten la capa por
  completo, tanto en JavaScript como en CSS; por tanto tampoco muestran el aviso.
- No se añadió JavaScript en línea; la CSP estricta no cambió y todos los recursos
  son locales (`site-loader.css?v=7`, `site-loader.js?v=5`).

Verificación local:

- `pytest -q`: **280 aprobadas, 0 fallidas**. La nueva prueba corporativa exige el
  cargador en `/captacion`, `/` y `/app`, 9 esferas y 81 ítems, `hidden` por
  defecto, popover manual, recursos locales sin `<script>` en línea, las reglas
  de movimiento reducido, colores forzados y top layer, y el bloque de error con
  `role="alert"`, «Reintentar» y «Continuar al sitio».
- Chrome DevTools confirmó 9 esferas y 81 discos, `display: flex`, popover
  abierto, `aria-busy="true"` y `scrollWidth === clientWidth` en 1440 y 390 px; la
  etapa móvil mide 264 px y el sol queda visible cerca de 1 s.
- El fondo calculado es `rgba(0, 0, 0, 0)` con `backdrop-filter: blur(13px)
  saturate(118%)` en escritorio y `blur(10px) saturate(112%)` en móvil; las
  capturas de `/captacion` y de `/` muestran la página difuminada detrás del sol.
- La salida natural limpia `hidden`, la clase, `aria-busy` y el popover, y escribe
  `ps-loader-seen=1`. La omisión por puntero y por `Escape` funciona; en el chat,
  `Escape` cierra el cargador, deja `dialog.open` en verdadero y mantiene la ruta
  `/`. Movimiento reducido, colores forzados y bfcache no muestran la capa.
- Chrome DevTools con una petición de imagen retenida confirmó que a los 5 s la
  capa sigue visible (antes se ocultaba a los 4.2 s). Un evento `offline` mostró
  el aviso de conexión y puso el foco en «Reintentar»; tres scripts fallidos
  mostraron el aviso de contenido; a los 15 s sin completar la carga apareció el
  aviso de conexión lenta. «Reintentar» produjo una recarga
  (`performance navigation type: reload`), «Continuar al sitio» y `Escape`
  retiraron la capa.
- Sin excepciones de JavaScript. Capturas:
  `artifacts/team-caguas/loader-desktop-1440.png`,
  `loader-mobile-390.png`, `loader-chat-1280.png`,
  `loader-waiting-1440.png`, `loader-error-offline-1440.png`,
  `loader-error-network-1440.png`, `loader-error-slow-1280.png` y
  `loader-error-offline-390.png`.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**; nueve archivos JavaScript sin
  errores de sintaxis.

Límites: el cargador es una adaptación local de presentación. Las capturas y
pruebas no demuestran publicación, dominio, hosting ni aprobación de Power Solar.
No se hizo commit, push ni publicación.

## Página 404 e icono del sitio, 12 de noviembre de 2026

La auditoría de las rutas públicas encontró dos carencias de producción: una ruta
inexistente devolvía JSON incluso al navegar, y ninguna plantilla declaraba icono.
Ambas se corrigieron sin añadir JavaScript ni servicios externos.

Página 404:

- `frontend/pages/404.html` reutiliza el shell corporativo, el encabezado, el pie y
  el chat. Presenta «Esta página no está aquí», enlaces a Inicio, Equipo,
  Soluciones, Planes, Preguntas frecuentes y Contacto, y ningún elemento de
  navegación marcado con `aria-current`.
- `reigel/seo.py` separa `render_shell(...)` del contenido de cada ruta. El
  manejador de `StarletteHTTPException` responde 404 con HTML solo cuando la
  solicitud acepta `text/html` y la ruta no pertenece a `/api/` ni `/webhooks/`.
  Las rutas de programa conservan `application/json` con `{"detail": "Not Found"}`.
- La respuesta 404 no refleja la ruta solicitada, envía
  `X-Robots-Tag: noindex, nofollow` y `Cache-Control: no-store`, y no publica
  canonical aun cuando exista un origen HTTPS configurado.
- Las páginas públicas conservan su contrato: canonical y `Link` con origen
  válido; `noindex` local cuando no lo hay. `robots.txt` y `sitemap.xml` no
  incluyen la ruta 404.

Icono:

- Se generaron recursos locales del sol solar sobre el azul corporativo:
  `frontend/assets/power-solar/favicon.svg` y `favicon-32.png`; `favicon-180.png`
  (opaco, 180 × 180) para `apple-touch-icon`.
- Las tres plantillas declaran los iconos y `/favicon.ico` sirve el PNG local con
  `Cache-Control: public, max-age=86400`. No se inventó un dominio ni se usó un
  servicio de iconos.

Verificación local:

- `pytest -q`: **280 aprobadas, 0 fallidas**. Las nuevas pruebas cubren el HTML
  404 con enlaces, encabezados y ausencia de canonical; la respuesta JSON en
  `/api/`, `/webhooks/`, rutas sin `Accept` HTML y archivos estáticos ausentes; y
  el icono declarado y servido en `/captacion`, `/` y `/app`.
- Chrome DevTools confirmó en 1440 y 390 px: estado 404, título correcto, un solo
  `h1`, `aria-current` ausente, `scrollWidth === clientWidth`, cero fallos de red
  y cero excepciones. Sin origen configurado el encabezado es `noindex`; con
  origen HTTPS la 404 sigue sin canonical.
- Capturas: `artifacts/team-caguas/not-found-desktop-1440.png` y
  `not-found-mobile-390.png`.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**; nueve archivos JavaScript sin
  errores de sintaxis.

Límites: las pruebas locales no demuestran publicación, indexación, entrega del
icono por un CDN ni aprobación de Power Solar. No se hizo commit, push ni
publicación.

## Navegación superior en píldoras, 12 de noviembre de 2026

La navegación de escritorio del shell corporativo se rediseñó en
`frontend/css/corporate.css` sin tocar el HTML ni JavaScript:

- Los enlaces pasan a píldoras (`border-radius: 999px`, `padding: 10px 14px`)
  con una capa `::before` de brillo degradado, borde translúcido y sombra suave
  al pasar el puntero o recibir foco; la píldora activa usa un tinte naranja
  cálido y conserva `aria-current="page"`.
- El indicador inferior es un degradado naranja con brillo que crece a 18 px en
  hover/foco y en la sección activa.
- El acceso a R.E.I.G.E.L. adopta la misma forma de píldora, con borde más
  claro, brillo cálido al interactuar y desplazamiento diagonal de la flecha.
- El foco de teclado conserva el contorno de 3 px; `prefers-reduced-motion`
  desactiva transiciones, elevación y desplazamiento. En el menú móvil el
  botón y las filas usan 12 px de radio y el elemento activo mantiene el tinte
  naranja existente.
- Se actualizó la versión a `corporate.css?v=4` en `frontend/landing.html`.

Verificación local:

- `pytest -q`: **280 aprobadas, 0 fallidas**; `scripts/doctor.py --sin-pruebas`:
  **APROBADO**.
- Chrome DevTools en `/precios` a 1440 px: píldoras con radio 999 px, «Planes»
  activo, hover y foco visibles, `scrollWidth === clientWidth`, cero
  excepciones. A 1241 px la navegación sigue visible; a 1240 px colapsa al
  botón sin desbordamiento. A 390 px el menú móvil abre con `aria-expanded` y
  sin excepciones.
- Capturas: `artifacts/team-caguas/header-nav-desktop-1440.png`,
  `header-nav-hover-1440.png`, `header-nav-focus-1440.png` y
  `header-nav-mobile-390.png`.

Límites: la verificación es local y sintética; no demuestra publicación ni
aprobación de marca. No se hizo commit, push ni publicación.

## Pipeline comercial en tablero, 12 de noviembre de 2026

Se recibió la Parte 1 de la especificación «R.E.I.G.E.L. Diseño del sistema ·
CRM Comercial · Versión 1.0» como documento de referencia. Esta entrega no
rediseña el sistema ni migra datos: implementa un corte acotado de la vista
comercial sobre el modelo existente, sin tocar la base operativa.

Alcance implementado:

- `/app` → Prospectos conserva la vista de tabla y añade un conmutador
  Tabla/Pipeline. Ambas vistas comparten búsqueda, filtro de etapa, asesor y
  orden, y el estado de la vista vive solo en memoria de la página.
- El tablero genera una columna por cada etapa del servidor
  (`reigel.core.STAGES`, once etapas, en su orden). Una prueba compara la lista
  de `frontend/js/operations.js` con `STAGES` para impedir que se desincronicen.
- Cada tarjeta muestra nombre, municipio, responsable, permiso, valor declarado
  cuando existe y el próximo seguimiento; los seguimientos vencidos usan el
  texto de alerta ya existente.
- La etapa se cambia con un `<select>` nativo por tarjeta (sin arrastrar y
  soltar) que llama al `PATCH /api/leads/{id}` existente. El servidor valida la
  etapa, aplica el alcance por rol y escribe `lead_history` y auditoría. Tras el
  cambio se recarga la consulta y el foco vuelve a la tarjeta movida; si falla,
  el selector recupera la etapa anterior y se informa el error.
- El tablero solicita hasta 500 prospectos, el máximo que admite
  `query_leads`; si hay más, la barra de estado avisa que se muestran los
  primeros 500 y sugiere acotar con los filtros. La tabla mantiene su
  paginación de 50.
- Un filtro de etapa activo reduce el tablero a esa columna y lo indica; la
  nota del tablero aclara que mover una tarjeta registra un estado comercial y
  no confirma cobro, firma ni venta.

Seguridad y privacidad:

- No se añadió ningún endpoint ni campo. El cambio de etapa reutiliza la ruta
  existente, por lo que conserva la autenticación, el control de origen, el
  límite de solicitudes y el alcance del servidor: el asesor solo ve y mueve
  registros asignados; el administrador conserva el alcance global.
- El texto se escapa en HTML y no se introdujo SQL nuevo. La prueba en navegador
  usó una base sintética de vista previa; no se leyó ni migró la base comercial.

Verificación local:

- `pytest -q`: **281 aprobadas, 0 fallidas**; incluye la prueba Node del
  agrupamiento por etapa y la paridad con `STAGES`.
- `node --check` sobre `app.js` y `operations.js`; `scripts/doctor.py
  --sin-pruebas`: **APROBADO**.
- Chrome DevTools a 1440 px: once columnas, ocho tarjetas y ocho selectores,
  conteos sumados, `Tabla/Pipeline` con `aria-pressed` correcto, movimiento
  `contactado → calificado` persistido en el servidor y en el historial con el
  usuario de la sesión, foco devuelto a la tarjeta, ocho filas al volver a la
  tabla, `scrollWidth === clientWidth`, cero excepciones.
- A 390 px: sin desbordamiento de página, columna de 304 px, tablero con
  desplazamiento horizontal, conmutador visible y controles táctiles de 36 px.
- Con sesión de asesor: cuatro tarjetas, solo los registros asignados, sin
  registros de otros asesores ni sin asignar.
- Capturas: `artifacts/team-caguas/crm-pipeline-1440.png`,
  `crm-pipeline-move-1440.png`, `crm-pipeline-390.png` y
  `crm-pipeline-advisor-1440.png`.

Límites: se conservan los nombres y campos actuales de las etapas; no hay campo
de motivo de cierre, arrastrar y soltar, ni columnas configurables. El tablero
no demuestra venta, cobro ni firma. La Parte 1 completa (multiempresa,
PostgreSQL, archivos privados, consentimientos y documentos versionados) no está
implementada y requeriría una migración autorizada. No se hizo commit, push ni
publicación.

## Asistente local en el chat público, 12 de noviembre de 2026

Primera rebanada acotada del Plan Maestro (fase de inteligencia artificial),
sobre el chat existente y sin cambiar su apariencia. El motor determinista
conserva el control comercial; el modelo local solo redacta respuestas a
mensajes nuevos que ese motor no puede clasificar.

Alcance implementado:

- `reigel/ai_chat.py` llama únicamente a Ollama en `127.0.0.1:11434`, sin
  `Authorization`, sin herramientas y con `stream: false`. Antes de responder
  consulta `/api/show` y descarta modelos o alias remotos (`remote_host`,
  `remote_model`); también descarta nombres con `cloud`.
- La IA está desactivada por defecto. Se habilita con `REIGEL_CHAT_AI=ollama`
  (o `1`, `on`, `yes`, `local`) y `scripts/start.ps1` la activa al iniciar el
  servidor. `REIGEL_CHAT_MODEL` acepta otro modelo local instalado.
- `reigel/webchat.py` expone `ai_brief`, que no escribe estado: valida el
  mensaje, evita duplicados y bajas, exige modo `ai`, clasifica el texto y solo
  devuelve contexto cuando la intención es `unsupported_or_ambiguous`. Incluye
  hasta ocho mensajes previos saneados, el perfil declarado y la respuesta
  verificada disponible.
- La ruta `POST /api/public/chat` solicita el borrador antes de guardar el
  mensaje. `webchat.message` solo lo usa si la huella de la conversación
  (identificador, cantidad de mensajes y perfil) sigue coincidiendo; si cambió,
  se descarta. Un fallo, tiempo de espera o borrador rechazado devuelve la
  respuesta determinista existente.
- El indicador de escritura, el reintento con la misma referencia y el tiempo
  máximo de 65 segundos del navegador ya existían; no se requirió JavaScript
  nuevo.

Seguridad y límites de contenido:

- Los mensajes técnicos (paneles, baterías, inversores, factura, consumo, LUMA,
  instalación, apagones y términos afines) nunca llegan al modelo. Reservas,
  bajas, solicitudes de privacidad, atención humana, precios, garantías,
  financiación y objeciones conservan su ruta determinista.
- Toda salida se normaliza y se rechaza si contiene cifras, enlaces, correos o
  teléfonos, marcadores sin completar, intentos de exponer instrucciones,
  confirmaciones de citas, garantías, condiciones comerciales o detalles
  técnicos sin fuente verificada. Las menciones temáticas (por ejemplo,
  "energía solar") sí se permiten; las afirmaciones técnicas no.
- El historial y el mensaje del visitante se etiquetan como datos no confiables;
  el modelo no recibe herramientas, no ejecuta SQL ni reservas y no puede
  cambiar reglas. Límite de 20 intentos de IA por minuto y cliente, salida de
  220 tokens, contexto de 3072 y tiempo máximo de 45 segundos.
- No se usan claves, servicios de pago ni proveedores en la nube. No se
  descargaron modelos.

Verificación local:

- `pytest -q`: **300 aprobadas, 0 fallidas**, incluidas 19 pruebas de la
  integración con transportes simulados (sin inferencia real): endpoint local,
  ausencia de credenciales y herramientas, rechazo de alias remoto, caída sin
  respaldo remoto, mensajes técnicos sin llamada, salida insegura rechazada,
  huella obsoleta y respaldo determinista en la ruta HTTP.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**.
- Vista previa sintética en `127.0.0.1:8877` con Ollama real: `/api/automation`
  informa `chat_ai: {enabled: true, status: available, local: true, model:
  qwen2.5:3b}`; mensajes abiertos ("Me preocupa el ruido de los equipos", "No
  sé si esto es para mí") reciben redacción del modelo, mientras reservas y
  atención humana siguen respondiendo de forma determinista. La base comercial
  no se leyó ni se migró.
- Navegador integrado en esa vista previa: el mensaje del visitante y la
  respuesta del modelo aparecen en las burbujas existentes, sin cambios de
  HTML, CSS ni JavaScript; también se confirmó la respuesta determinista para
  reserva y atención humana.

Límites: el modelo es pequeño (3B) y puede responder de forma genérica; solo
cubre mensajes abiertos no técnicos. No hay transmisión por partes, ingestión
de la base de conocimiento ni proveedor en la nube; no es una puesta en
producción. No se hizo commit, push ni publicación.

## Espacio de conversación `/ia`, 12 de noviembre de 2026

Segunda rebanada acotada del Plan Maestro (fase de inteligencia artificial).
Convierte el chat lateral existente en un espacio de conversación a pantalla
completa, sin sustituir el diálogo de `/` ni la reserva pública.

Alcance implementado:

- `frontend/ia.html`, `frontend/css/ia.css` y `frontend/js/ia.js`: interfaz
  propia con la identidad corporativa, barra lateral contraíble con historial,
  área central con desplazamiento independiente, campo fijo en la parte
  inferior y diseño adaptable. En anchos de hasta 900 px el historial se abre
  como panel superpuesto y el campo permanece visible.
- Los mensajes se insertan con `textContent`; el script se sirve localmente y
  la CSP existente (`script-src 'self'`) sigue aplicándose. La página envía
  `X-Robots-Tag: noindex, nofollow` y `Cache-Control: no-store` en las rutas
  `/api/ia/*`.
- El botón del chat de las páginas públicas navega a `/ia` y conserva el texto
  preparado de los botones de intención mediante `?q=`. «Volver» usa la página
  de origen cuando pertenece al mismo sitio. El diálogo anterior sigue
  disponible en `/`, incluidas reserva y atención humana.
- Motor: `reigel/ai_chat.py` añade `stream_workspace`, que consulta
  `/api/show` una vez, rechaza alias remotos y luego consume la respuesta en
  partes (`stream: true`) de Ollama en `127.0.0.1:11434`, sin cabeceras,
  herramientas ni claves. `validate_workspace_reply` sustituye salidas que
  contengan enlaces, precios, garantías, financiamiento, diagnósticos,
  confirmaciones de acciones o atribuciones de servicio no verificadas.
- Contexto: hasta 20 mensajes previos de la misma conversación, etiquetados
  como historial no confiable. El mensaje actual también se etiqueta y las
  reglas del sistema no dependen de él. Sin fuente verificada, el prompt
  prohíbe afirmar datos concretos de Power Solar.
- Persistencia: tablas aditivas `ai_conversations` (dueño, título, estado,
  fechas), `ai_messages` (rol, contenido, estado, fecha) y `ai_visitors`
  (hash del token, vencimiento deslizante). No se modifican tablas existentes
  del CRM ni el buzón de Conversaciones del equipo.
- Propiedad: un usuario con sesión inicia sesión y recupera sus conversaciones
  desde cualquier navegador. Un visitante anónimo recibe una cookie HttpOnly
  `reigel_ia` con `Path=/api/ia`, `SameSite=strict` y siete días; sus
  conversaciones se eliminan al vencer el plazo. Otro dueño recibe 404.
- Rutas: `GET /ia` y `GET|POST /api/ia/bootstrap`,
  `/api/ia/conversations`, `/api/ia/conversations/{id}`,
  `POST .../messages`, `POST .../regenerate`. Los eventos SSE son `meta`,
  `delta`, `done`, `replace` y `error`.
- Interrupción: el navegador usa `AbortController`; el servidor conserva la
  parte emitida como `stopped` al desconectarse. La API mantiene
  `POST .../regenerate` (solo la última respuesta, reutilizando su
  identificador), pero la interfaz ya no muestra el botón de regeneración: se
  retiró a pedido del titular el 12 de noviembre de 2026; para volver a
  preguntar basta enviar un mensaje nuevo.
- Límites: 60 s de modelo (10–120 configurables con
  `REIGEL_IA_TIMEOUT_SECONDS`), salida de 320 tokens (64–600 con
  `REIGEL_IA_NUM_PREDICT`, techo 6000 caracteres), hasta 200 mensajes por
  conversación, 100 conversaciones en el historial, 10 generaciones y 10
  regeneraciones por minuto y cliente. Los errores distinguen tiempo de espera,
  modelo ausente y Ollama apagado.

Verificación local:

- `pytest -q`: **314 aprobadas, 0 fallidas**, incluidas 14 pruebas nuevas en
  `tests/test_ia.py` con `stream_workspace` simulado: creación y cookie de
  visitante, persistencia y recuperación, título y orden del historial,
  contexto enviado al modelo, aislamiento entre visitantes (404), historial
  autenticado entre sesiones, regeneración en el mismo mensaje, rechazo de
  regeneración no última, salida insegura sustituida, error de conexión,
  tiempo de espera, modelo desactivado (503), límite de mensajes, validación
  de texto y rutas sin sesión.
- `scripts/doctor.py --sin-pruebas`: **APROBADO**, 10 archivos JavaScript sin
  errores de sintaxis.
- Vista previa sintética en `127.0.0.1:8877` con Ollama real:
  `/api/ia/bootstrap` informó `visitor`, retención de 7 días y
  `qwen2.5:3b` disponible; una pregunta abierta transmitió eventos `delta` y
  guardó la respuesta como `complete`.
- Navegador: el botón del chat de `/captacion`, `/soluciones` y el lanzador
  móvil abren `/ia`; el texto preparado llega al campo y se limpia de la URL;
  «Volver» regresa al origen. Se comprobó historial, cambio de conversación,
  nueva conversación, regeneración en el mismo mensaje, detener con parte
  conservada y el panel de historial en móvil.
- Raíz pública, 12 de noviembre de 2026: `/` sirve ahora la misma conversación
  a pantalla completa, porque es el enlace que reciben los visitantes;
  `/ia` se conserva para enlaces directos y la página de chat anterior sigue en
  `/chat` con su reserva. «Volver» no apunta a `/`, `/ia` ni `/chat` cuando el
  origen es una de esas rutas, para no recargar la misma página.
- Capturas con Chrome sin interfaz y emulación de dispositivo: 1440×900
  (barra lateral abierta, columna de 840 px, compositor fijo, sin desborde) y
  390×844 (panel cerrado, botón de menú visible, compositor fijo, sin
  desborde horizontal). La captura inicial a 390 px era un recorte de una
  ventana mínima de 518 px, no un defecto del diseño; la corrección de
  `min-height` del campo quedó incluida.

Límites: el modelo es local y pequeño; puede equivocarse en detalles
educativos y el aviso en pantalla lo indica. No hay base de conocimiento
conectada a `/ia` (corrección del 19 de noviembre: falso en el código actual;
`ia_events` pasa a `stream_workspace` la paráfrasis de
`KnowledgeBase.answer`, sin RAG ni búsqueda documental), ni adjuntos, ni voz, ni búsqueda web, ni herramientas. El
historial autenticado depende de la sesión del equipo; no se creó un sistema
de cuentas nuevo ni contraseñas adicionales. No se migró la base comercial, no
se enviaron mensajes externos y no se hizo commit, push ni publicación. El
servidor activo en `127.0.0.1:8765` debe reiniciarse para aplicar las tablas
aditivas de `/ia` y para que `/` sirva la conversación; reiniciarlo es una
acción del titular. Mientras ese proceso
siga con el código anterior, `chat.js` consulta `/api/ia/conversations` antes de
abrir `/ia`: si la ruta responde 404, abre el diálogo existente en vez de dejar
el botón en una página inexistente. Comprobado en vista previa con la respuesta
404 simulada, sin tocar el servidor comercial.

Menú «+» del campo de `/ia`: Nueva conversación, Detener respuesta (activo solo
durante el streaming), Copiar última respuesta (portapapeles del navegador, con
aviso si el navegador lo bloquea) y Volver al sitio. Adjuntar archivos,
Búsqueda web, Documentos y PDF y Crear imágenes se muestran deshabilitados
bajo «Aún no disponible» porque no existen en el servidor. El menú se cierra con
Escape o al pulsar fuera, usa `role="menu"` y `aria-expanded`, y cabe en 390 px.

## Frontera de salida de `/ia`, 19 de noviembre de 2026

Corrige tres defectos reproducidos con `audit_ia_evidence.py` sobre una base
temporal y modelo simulado:

1. Cada fragmento del modelo se enviaba como `delta` antes de validar; un
   precio o una garantía llegaban al navegador y solo después se reemplazaban.
2. Tras un error o una desconexión se guardaba el texto parcial sin validar,
   con estado `stopped`, y `history()` lo devolvía al modelo en el turno
   siguiente.
3. `stream_workspace` daba por completa una transmisión cerrada sin
   `done:true` de Ollama.

Cambio (`reigel/api.py`, `ia_events`; `reigel/ai_chat.py`):

- El servidor acumula el texto y solo emite frases completas (terminadas en
  `.`, `!`, `?` o `…` seguidos de espacio, o salto de línea) después de validar
  todo el prefijo acumulado con `validate_workspace_reply`. Si falla, cierra la
  generación (`aclose`), guarda `SAFE_REPLACEMENT` como `rejected` y emite
  `replace`. Al terminar se valida el texto completo antes de emitir el resto
  y `done`.
- Parada, error o desconexión guardan solo el prefijo ya validado y emitido.
  Sin prefijo validado se aplica el comportamiento anterior: se descarta la
  respuesta, o se restaura la previa en una regeneración.
- `ai_chat.safe_history` excluye del contexto las respuestas guardadas que hoy
  no pasarían el validador, incluidas filas antiguas `stopped` sin validar. No
  modifica ni borra esas filas: siguen visibles en el historial del dueño.
- EOF sin `done:true` lanza `RuntimeError` y sigue el camino de error.
- Sin cambios en `ia.js`, en el esquema ni en el contrato de eventos SSE: los
  `delta` llegan por frases en lugar de por fragmentos.

Pruebas nuevas en `tests/test_ia.py`: un único fragmento inseguro no produce
ningún `delta`; las frases seguras se emiten y la cola insegura no; un error a
mitad conserva solo lo validado en el evento, la base y el historial que vuelve
al modelo; un error sin frase validada descarta la respuesta; una fila antigua
insegura no vuelve al modelo; EOF sin `done` se rechaza y con `done` se acepta
(transporte HTTP simulado).

Límites que siguen: la seguridad depende de `validate_workspace_reply`, que es
de expresiones regulares (la política de cantidades se añadió después; ver
sección siguiente). Un patrón que solo resulte prohibido al unir
dos frases puede mostrar la primera antes de retirar la respuesta. La
respuesta tarda más en empezar a verse, porque espera la primera frase
completa. La ruta de desconexión del cliente no tiene prueba automática propia;
comparte `preserve_partial` con la de error. No se probó con Ollama real, ni en
navegador, ni sobre la base comercial; el servidor activo necesitaría
reiniciarse para aplicar el cambio, y eso es una acción del titular.

## Política de cantidades en `/ia`, 19 de noviembre de 2026

Problema reproducido: `validate_workspace_reply` aceptaba «Con un sistema solar
puedes ahorrar 80% en tu factura.» y «La bateria te da 24 horas de respaldo.»,
afirmaciones que el prompt de `/ia` prohíbe. Las 15 variantes de
`QUANTITATIVE_CLAIMS` en `tests/test_ia.py` pasaban todas antes del cambio.

Política verificable: una respuesta de `/ia` no expresa cantidades. La
evidencia verificada que recibe `/ia` (`KnowledgeBase.ANSWERS`) no contiene
ninguna cifra, así que ninguna cantidad tiene fuente. `ai_chat._expresses_quantity`
rechaza, sobre el texto sin tildes y en minúsculas:

- cualquier dígito, `%` o «por ciento»;
- un número escrito con palabras (de «dos» en adelante, «mil», «mitad»,
  «doble», «triple», «tercios», «cero») seguido, a dos palabras como máximo,
  de una unidad: tiempo, energía o potencia, paneles, baterías, equipos,
  electrodomésticos, cargas, circuitos, veces;
- un número escrito con palabras en la misma frase (hasta 60 caracteres, sin
  cruzar `.`, `!`, `?`, `;` o `:`) que un término de ahorro, factura, pago,
  reducción, respaldo, autonomía, duración, rendimiento, producción,
  recuperación, inversión, consumo o costo;
- promesas absolutas: factura en cero, eliminar la factura, nunca más pagar,
  independencia total, autonomía o respaldo ilimitado o total, «se paga solo».

Se aplica tanto si hay evidencia verificada como si no. El prompt de `/ia`
ahora pide no escribir números ni cantidades, ni en cifras ni en palabras, para
que el modelo no produzca respuestas que luego se retiran.
`validate_reply` de `/chat` no cambió: ya rechazaba cualquier dígito.

Pruebas: 16 afirmaciones rechazadas (con y sin evidencia), 10 explicaciones
cualitativas aceptadas para controlar falsos positivos (incluidas las cinco
respuestas de `ANSWERS` comprobadas aparte), un stream en el que la frase con
«80%» no llega al cliente, y la frase del prompt.

Límites: es una lista cerrada de expresiones, no una comprensión semántica.
Quedan sin cubrir, por ejemplo, números en inglés u otros idiomas, unidades no
listadas o promesas sin número («ahorrarás muchísimo»). Hay falsos positivos
deliberados: una explicación educativa con cifras («1 kWh equivale a 1000
vatios durante una hora») se sustituye por el mensaje alternativo.
`safe_history` usa el mismo validador, así que respuestas antiguas con cifras
dejan de volver al modelo como contexto. El mensaje alternativo
(`SAFE_REPLACEMENT`) ofrece que el equipo revise la consulta, pero `/ia` no
registra ninguna derivación; eso pertenece al hallazgo de CTA y queda
pendiente. No se probó con Ollama real: se desconoce cuántas respuestas reales
de `qwen2.5:3b` acabarán sustituidas.

## Reserva y atención humana: dirigir a `/chat`, 19 de noviembre de 2026

Problema: `/` y `/ia` no tienen reserva, atención humana, baja ni solicitudes
de privacidad; esas acciones solo existen en `/chat`. Sin embargo, el botón de
Contacto («Chat y coordinación de citas»), los dos botones de `/equipo`
(«Conversar con el equipo» y el de la tarjeta de contacto) y los textos de
Preguntas y Proceso que dicen «reserva desde el chat» o «elige Hablar con el
equipo» llevaban a `/ia` a través de `iaAvailable()`. Además, el mensaje
alternativo de `/ia` ofrecía «¿Quieres que el equipo lo revise?» sin registrar
nada.

Cambio:

- `pages/contacto.html`: el botón `data-open-chat` pasa a ser un enlace
  «Abrir chat de coordinación» a `/chat`; la descripción y el encabezado
  enlazan al chat de coordinación para ver horarios y reservar.
- `pages/equipo.html`: «Conversar con el equipo» y «Coordinar por el chat»
  (antes «Conversar por el chat») son enlaces a `/chat`. Los tres «Conversar
  este tema», las cuatro opciones de `/soluciones` y los botones generales del
  shell siguen abriendo `/ia`: no prometen ni equipo ni cita.
- `pages/preguntas.html` y `pages/proceso.html`: «el chat» pasa a ser un enlace
  al chat de coordinación en las frases de reserva y de «Hablar con el equipo».
  Se conservó CRLF, el final de línea original de esos archivos.
- `ia.html`: enlace «Citas y equipo» a `/chat` en la barra superior, en el
  menú «+» y en la bienvenida, con el aviso de que esta conversación no registra
  esas solicitudes. `ia.css` (v=11) le da estilo y, a 360 px o menos, oculta el
  texto «R.E.I.G.E.L.» de la barra para que no se corte; el logo y el h1 para
  lectores de pantalla siguen.
- `ai_chat.SAFE_REPLACEMENT` remite a «Citas y equipo» en lugar de ofrecer una
  revisión que `/ia` no registra. El prompt de `/ia` indica al modelo que remita
  ahí las reservas, la atención humana, las bajas y las solicitudes de datos, y
  que no diga que las hará.

Pruebas: `tests/test_commercial_actions.py` (todo párrafo que ofrece reservar o
pedir al equipo enlaza a `/chat`; ningún botón que abre `/ia` promete equipo,
cita ni coordinación; la sección de Contacto solo enlaza a `/chat`; `/chat`
conserva sus acciones; `/` y `/ia` muestran «Citas y equipo»; el mensaje
alternativo y el prompt coinciden con esa etiqueta). Navegador, vista previa
sintética en 8877: `/ia` en escritorio, 375 y 320 px sin desborde horizontal; menú «+»
con la nueva entrada; el enlace abre `/chat` con «Coordinar evaluación» y
«Hablar con el equipo»; Contacto y Equipo muestran los nuevos enlaces con el
mismo estilo. Se añadió `.claude/launch.json` para arrancar esa vista previa.

Límites: `/ia` y `/chat` siguen siendo conversaciones separadas: el visitante
repite su consulta en `/chat`. Escribir «/stop», pedir una persona o pedir que
borren sus datos dentro de `/ia` solo obtiene, como mucho, la indicación del
modelo; ninguna regla determinista lo intercepta. El lanzador flotante del
shell dice «Tu evaluación» y abre `/ia`; no promete reservar, pero puede
sugerirlo. `iaAvailable()` sigue considerando disponible cualquier respuesta
distinta de 404, incluido un 500. El aviso de posibles errores del modelo sigue
oculto hasta 900 px. No se probó con lector de pantalla ni con Ollama real.

## Retención deslizante de visitantes en `/ia`, 19 de noviembre de 2026

Problema reproducido: la interfaz, el README y el docstring de `ia_workspace`
anuncian «siete días desde la última actividad», pero `ia_owner` devolvía al
visitante sin renovar nada. `expires_at` quedaba fijado al crear la sesión y la
cookie no se reemitía, así que el historial podía vencer en pleno uso.

Cambio:

- `AIWorkspace.touch_visitor(token)` actualiza `last_seen_at` y
  `expires_at = ahora + 7 días` solo si el visitante sigue vigente (un único
  `UPDATE ... WHERE expires_at > ahora`). Un visitante vencido no se revive: sus
  conversaciones pueden estar ya purgadas, y recibe una sesión nueva como antes.
- `api.renew_visitor` llama a `touch_visitor` y reemite la misma cookie
  `reigel_ia` con `Max-Age` de siete días y los mismos atributos (HttpOnly,
  SameSite Strict, `Path=/api/ia`, Secure en producción). Base y navegador
  vencen a la vez.
- Cuenta como actividad: `GET /api/ia/bootstrap` (abrir `/` o `/ia`) y
  `POST .../messages` o `.../regenerate`. Leer el listado o una conversación no
  renueva. Las cuentas autenticadas no reciben cookie de visitante.

Pruebas (`tests/test_ia.py`): bootstrap y envío renuevan vencimiento,
`last_seen_at` y cookie con el mismo token; leer historial no renueva; un
visitante vencido no se revive y no ve sus conversaciones; una cuenta
autenticada no recibe `reigel_ia`. La auditoría ya no reporta la retención
fija ni la cookie sin renovar.

Límites: la purga sigue siendo oportunista (al abrir `/ia`, como máximo una vez
por hora y proceso); no hay un trabajador que borre exactamente al vencer.
Cada apertura o envío escribe en `ai_visitors`, limitado por las cuotas de esas
rutas. Un visitante cuya fecha antigua quedara más lejos de siete días, por
ejemplo un `expires_at` editado a mano, se acorta a siete días con la siguiente
actividad. No se probó en navegador real.

## Límite de 200 mensajes por turno completo, 19 de noviembre de 2026

Problema reproducido: `append_user` comprobaba `count < 200` y después
`begin_assistant` insertaba el marcador de respuesta en otra transacción sin
comprobar nada. Con 199 mensajes, un envío se aceptaba y dejaba 201. Dos
pestañas a la vez podían superar el límite por la misma separación.

Cambio (`reigel/ia_workspace.py`, `reigel/api.py`):

- `AIWorkspace.begin_turn` inserta el mensaje de la persona y el marcador de
  respuesta en una sola transacción `BEGIN IMMEDIATE`, después de comprobar que
  caben los dos (`count + 2 <= 200`). Si no caben, responde 409 sin escribir
  nada. La ruta `POST .../messages` usa `begin_turn`; `begin_assistant` se
  eliminó porque no tenía otros usos.
- `append_user` se conserva para usos internos o de auditoría (inserta solo el
  mensaje, con `count + 1 <= 200`).
- La regeneración no cambia: reutiliza el ID de la respuesta y no añade filas.

Pruebas (`tests/test_ia.py`): con 199 mensajes, el envío recibe 409 y la base
sigue en 199; con 198, el turno completa en 200 y el siguiente recibe 409;
cuatro hilos simultáneos sobre 198 dejan exactamente uno aceptado y 200
filas. La auditoría informa 409 y 199.

Límites: si una respuesta falla sin texto validado, se descarta su marcador y
queda solo la pregunta, así que una conversación puede cerrarse con 199. El
mensaje de límite indica iniciar una conversación nueva. Sigue sin haber
idempotencia: reintentar el mismo envío desde dos pestañas crea dos turnos
mientras haya cupo.

## Datos de contacto ocultos al guardar en `/ia`, 19 de noviembre de 2026

Decisión del titular: `/ia` oculta el correo y el teléfono antes de guardar,
igual que `/chat` hace con los mensajes anteriores al consentimiento. `/ia` no
tiene paso de consentimiento.

Problema reproducido: `/ia` guardaba el texto original en `ai_messages` y lo
reflejaba en el título y en la vista previa del historial; solo lo ocultaba al
enviarlo a Ollama.

Cambio:

- `ia_workspace.hide_contacts` sustituye correos por `[correo omitido]` y
  teléfonos (de 7 a 15 dígitos con separadores habituales, empezando y
  terminando en dígito para conservar la puntuación) por `[teléfono omitido]`.
  Recorta a 4.000 caracteres, porque un marcador puede ser más largo que lo que
  sustituye y el modelo no acepta más.
- `_insert_turn` aplica el filtro antes de insertar, así que el título y la
  vista previa, que salen del texto guardado, tampoco contienen el dato. Se
  aplica a visitantes y a cuentas autenticadas.
- `ia_message` pasa al modelo y a la consulta de conocimiento el texto guardado,
  no el cuerpo original: lo guardado es lo que ve el modelo.
- `ia.html`: la bienvenida pide no escribir correo ni teléfono y avisa de que
  se ocultan al guardar.

Pruebas (`tests/test_ia.py`): ni el SSE, ni el detalle, ni el listado, ni las
tablas, ni el texto que recibe el modelo contienen el correo o el teléfono;
«factura ronda 150» se conserva; una cuenta autenticada también queda oculta;
un mensaje lleno de correos no supera 4.000 caracteres; la página muestra el
aviso. Comprobado a 375 px en vista previa sintética. La auditoría informa
`workspace_stores_contact_text_before_model_sanitizing: false`.

Límites: es un filtro de patrones, no un detector de datos personales; no
reconoce nombres, direcciones, números de cuenta escritos de otra forma ni
teléfonos con menos de siete dígitos. Una secuencia larga que no sea teléfono
(por ejemplo, un número de referencia) también se oculta. Hasta recargar, la
burbuja del navegador muestra el texto tal como se escribió; lo guardado y lo
que ve el modelo ya están ocultos. Las filas guardadas antes de este cambio no
se modificaron: limpiarlas exige una operación revisada sobre la base
comercial, que no forma parte de esta tarea.

## Documentación alineada con las rutas reales de la IA, 19 de noviembre de 2026

Varios documentos decían que toda salida de Ollama es un borrador revisado. El
código tiene tres rutas y solo una cumple eso:

| Ruta | Código | ¿Revisión humana antes de llegar al cliente? |
| --- | --- | --- |
| Borrador del equipo | `assistant.draft` vía `/api/assistant/draft` | Sí |
| Modo IA de canales | `assistant.draft` vía `channels._respond_locked` | No; solo si el equipo activa el modo `ai` y el canal lo permite (Meta bloqueado) |
| Respaldo de `/chat` | `ai_chat.reply` | No; validador de patrones |
| `/` y `/ia` | `ai_chat.stream_workspace` | No; validador de patrones por frase |

Corregidos: `AGENTS.md` (rutas de IA, papel de `/`, `/ia` y `/chat`, y que
`create_app(ruta)` sigue leyendo `.env` sin parche; la verificación incluye ahora
todos los scripts JS y las pruebas Node), `README.md`,
`docs/ARCHITECTURE.md`, `docs/CONVERSATION_EVALUATION.md`, `docs/OPERACION.md`,
`docs/CONECTAR_CANALES.md`, los docstrings de `assistant.py` y `ai_chat.py`, y
el texto de estado de la integración IA en `channels.py`.
`docs/IMPLEMENTATION_CONTRACT.md` queda marcado como histórico. En este archivo
se anotó la afirmación de que `/ia` no tiene conocimiento conectado. Las
secciones anteriores de este registro se conservan como bitácora: describen el
estado de su fecha.

No hubo cambios de comportamiento, salvo ese texto de estado de la integración.

## Respaldo previo a migración real, 19 de noviembre de 2026

Problema reproducido (`tests/test_backup.py`, base sintética con el esquema
anterior a `team_caguas_operations_v1`): `scripts/backup.py` construía
`Store()` antes de copiar. Ese constructor ejecuta `SCHEMA`,
`migrate_operations` y los ajustes por defecto, así que la «copia previa»
añadía 19 objetos de esquema a la base de origen y capturaba la base ya
migrada. Si la base no existía, el script creaba una vacía y la respaldaba
como si nada.

Cambio:

- `reigel.core.default_db_path` resuelve la ruta (argumento,
  `REIGEL_DB_PATH` o `%LOCALAPPDATA%\PowerSolar\reigel.db`) sin abrir ni crear
  nada; `Store` la reutiliza.
- `scripts/backup.py` abre el origen con `mode=ro`, copia con la API de backup
  de SQLite, comprueba `integrity_check` en la copia, borra la copia si algo
  falla, y cierra el archivo al calcular el SHA256. Nuevo `--db` para indicar la
  base; sin él, carga `.env` solo para resolver `REIGEL_DB_PATH`. Falla sin
  crear nada si el origen no existe, y rechaza un destino que ya existe o que
  coincide con el origen.

Pruebas: el origen antiguo conserva exactamente su esquema y ajustes, y la
copia es idéntica; `--db` sobre una base actual produce una copia que abre con
`Store` (restauración apuntando a la copia); los cambios aún en el WAL de un
escritor abierto aparecen en la copia; origen inexistente, destino ocupado y
destino igual al origen se rechazan sin escribir.

Límites: no se ejecutó sobre la base comercial ni se comprobó su existencia.
`chmod(0o600)` no equivale a ACL de Windows: la carpeta de copias hereda los
permisos de la carpeta privada. La migración real sigue pendiente de una
decisión del titular: detener el servicio, ejecutar este respaldo, conservar
el SHA256 y solo entonces arrancar el código nuevo.

## `create_app` con ruta explícita ya no lee `.env`, 19 de noviembre de 2026

Problema reproducido (`tests/test_environment_isolation.py`): `create_app`
llamaba siempre a `load_environment()`, también con una ruta temporal. Una
prueba, la vista previa o una herramienta nueva que olvidara el parche cargaba
en su proceso la configuración y las credenciales de `.env`. Las pruebas
existentes estaban protegidas solo por el parche de `tests/conftest.py`.

Cambio (`reigel/api.py`): `create_app(db_path=None, *, load_env=None)`. Por
defecto carga `.env` solo si no se indica ruta, que es el caso de `main.py`.
Con ruta explícita no la carga, salvo `load_env=True`. Las variables del proceso
se siguen leyendo; Docker y `start.ps1` no cambian porque usan `main:app`.
El parche de `conftest.py` y el de la vista previa se mantienen como segunda
barrera. Esto corrige la nota anterior de esta bitácora («`create_app(ruta)`
sigue leyendo `.env` sin parche») y `AGENTS.md`.

Pruebas: un espía sobre `load_environment` confirma que no se llama con ruta
explícita y sí con `load_env=True`. Ninguna prueba construye la app sin ruta,
porque eso abriría la base comercial.

Límite: quien construya la app con una ruta explícita para producción tiene
que pasar `load_env=True` o definir las variables en el proceso.

## Aviso de errores del modelo visible en móvil, 19 de noviembre de 2026

Problema: `ia.css` ocultaba `.ia-disclaimer` («R.E.I.G.E.L. usa un modelo de
lenguaje local y puede equivocarse…») hasta 900 px, justo en móvil, y en
escritorio lo mostraba a 10 px.

Cambio: el aviso ya no se oculta en ningún ancho; pasa a 11 px y en móvil usa
un margen y un interlineado más compactos (`ia.css?v=12`). Prueba estática en
`tests/test_ia.py`: ninguna regla de `.ia-disclaimer` usa `display: none` ni
`visibility: hidden`, ni un tamaño menor de 11 px; la página contiene el aviso.

Comprobado en vista previa sintética: visible en escritorio (una línea), a 375
y a 320 px (dos líneas, unos 30 px, dentro de la pantalla y sin desborde
horizontal). No se probó con teclado virtual abierto ni con lector de
pantalla.

## `/ia`: cada respuesta se queda en su conversación, 19 de noviembre de 2026

Problema reproducido con el `ia.js` real sobre un DOM sintético
(`tests/frontend_ia.test.cjs`) y en el navegador con `fetch` interceptado:

1. Al pulsar A y luego B en el historial, si la respuesta de A llegaba después
   que la de B, la pantalla quedaba en A aunque B estuviera seleccionada.
2. Al cambiar de conversación durante una respuesta, la cancelación de A
   terminaba después de cargar B: añadía la respuesta de A a los mensajes de B
   (y «Copiar última respuesta» copiaba ese texto) y mostraba «Respuesta
   detenida» sobre B.

Cambio (`frontend/js/ia.js`, `ia.js?v=9`): un contador de vista
(`state.view`) que aumentan seleccionar una conversación, crear una nueva y
crear la primera al enviar. Una respuesta de selección o de creación que llega
tarde se ignora. Una respuesta en curso guarda la vista en la que empezó; si
ya no es la visible, no escribe en el hilo, en `state.messages` ni en los avisos,
aunque sí actualiza el listado del historial. El servidor guarda esa respuesta
como antes y aparece al volver a esa conversación.

Pruebas: `tests/frontend_ia.test.cjs` (dos casos; antes fallaban ambos),
ejecutado desde pytest por `tests/test_frontend_ia.py`. Navegador, vista previa
sintética con `fetch` simulado en la página: selección rápida A→B con A lenta
deja B visible y marcada; cambiar a B durante un stream de A deja B sin texto de
A, sin aviso ajeno y con el botón de nuevo en «Enviar»; detener dentro de la
misma conversación conserva «Respuesta detenida».

Límites: sigue sin haber exclusión en servidor ni idempotencia: dos pestañas
pueden generar a la vez en la misma conversación. El DOM sintético cubre solo
las APIs que usa `ia.js`; no sustituye una prueba con lector de pantalla.

## Botones de conversación: `/ia` solo si el modelo responde, 19 de noviembre de 2026

Problema reproducido en la vista previa sintética, sin simulaciones: con el
modelo desactivado, «Reducir costos de energía» en `/soluciones` llevaba a `/ia`,
donde el campo de mensaje queda deshabilitado. `iaAvailable()` en `chat.js`
consultaba `/api/ia/conversations` y trataba cualquier estado distinto de 404
como disponible, incluidos 401, 500 o un modelo caído.

Cambio:

- `GET /api/ia/status` devuelve solo `{"available": bool}`: modelo activado y
  con estado `available`, según `ai_chat.status()`. No crea sesión de visitante,
  no envía cookie, no devuelve el nombre del modelo y está limitado a 60 por
  minuto y cliente.
- `chat.js` (`?v=6`): los botones `data-open-chat` van a `/ia` solo con
  `available: true`. Un modelo desactivado o caído, un error del servidor, un
  tiempo de espera de 4 s o un proceso antiguo sin la ruta (404) abren el chat
  determinista en la página, que responde sin modelo y ofrece reserva y atención
  humana. El texto preparado se conserva en ambos casos. El resultado se guarda
  para el resto de la visita a esa página.

Pruebas: `tests/test_ia.py` (cuatro estados del modelo; la consulta no crea
visitante ni cookie y no expone el nombre del modelo). Navegador: sin modelo, el
botón abre el diálogo con el texto preparado; con la respuesta de estado
simulada en la página, un 500 abre el diálogo y `available: true` lleva a `/ia`
con el texto en el campo.

Límites: la consulta llama a Ollama (`/api/tags`, 3 s) en el primer clic, así
que con Ollama colgado el botón puede tardar hasta 4 s. Un modelo que se cae
después de la consulta sigue llevando a `/ia`, que lo informa y ofrece «Citas y
equipo». No se probó con Ollama real.

## Rediseño fase 1: gestión de conversaciones y contenido oficial, 19 de noviembre de 2026

Autorización del titular: control completo del repositorio, funciones
avanzadas, diseño en toda la app, Uiverse.io y material oficial de Power
Solar. Plan por fases en `docs/HOJA_DE_RUTA.md`. Trabajo en la rama
`rediseno-reigel`; el commit `a66a51d` es el punto de control previo.

Backend (`ia_workspace.py`, `api.py`):

- `PATCH /api/ia/conversations/{id}` renombra (1–80 caracteres; oculta
  contactos en el título). `DELETE` elimina la conversación y sus mensajes;
  responde 409 si hay una respuesta generándose (marcador `streaming` de menos
  de 10 minutos). `GET /api/ia/conversations?q=` busca en títulos y mensajes
  del dueño, con `LIKE` escapado. Todo con alcance de dueño (404 para otros),
  cuota `ia_manage` de 60 por minuto y control de origen de escritura.

Frontend (`ia.html`, `ia.js?v=10`, `ia.css?v=13`):

- Buscador en el historial (250 ms, gana la última respuesta), menú «⋯» por
  conversación con Renombrar (campo en línea: Enter guarda, Escape cancela) y
  Eliminar → «Eliminar definitivamente» / Cancelar. Eliminar la conversación
  abierta limpia la vista.
- Bienvenida con las seis ilustraciones oficiales del sistema residencial como
  tarjetas que llevan una pregunta sin cifras al campo. Se sustituyó la
  sugerencia «kW frente a kWh con un ejemplo», que la política de cantidades
  habría retirado.

Sitio (`pages/contacto.html`, `corporate.css?v=5`): sección «Centros de
servicio» con el mapa oficial y la lista equivalente en texto de las 13
ubicaciones que muestra, con fuente, fecha y aviso de confirmar horario.

Material oficial: nueve PNG descargados de powersolarpr.com (verificados por
cabecera) y registrados en `SOURCES.md`. No se tomaron fotos de clientes ni de
representantes con nombre, ni precios, promociones o cifras de esas páginas.

Pruebas: 7 de backend en `tests/test_ia.py`; 2 nuevas de `ia.js` en
`tests/frontend_ia.test.cjs` (renombrar, eliminar con confirmación);
`tests/test_official_content.py` (lista de centros, imágenes locales,
preguntas sin cifras, fuentes registradas). Navegador: `/ia` a 1280 y 375 px y
`/contacto` a 1280 y 375 px, sin desborde.

Límites: la búsqueda usa `LIKE`, sin acentos insensibles ni ranking. Eliminar
es definitivo y no pasa por el flujo de privacidad comercial (son
conversaciones de `/ia` del propio dueño). No se probó con lector de pantalla.

## Chat de coordinación: rediseño visual y reserva por pasos, 19 de noviembre de 2026

Diálogo `#reigel-chat` de `/chat` y del shell corporativo (`landing.html`),
mismo marcado e IDs en ambos. Estilo nuevo en `frontend/css/coordination-chat.css?v=1`,
cargado el último y limitado a `.reigel-chat`; `chat.js?v=7`.

- Cabecera con el logo real, píldora de modo («Asistente automático · el equipo
  puede intervenir», «Atención del equipo solicitada», «Asistencia comercial
  detenida») y arco solar decorativo en CSS.
- Bienvenida con tres tarjetas fotográficas locales que envían una pregunta sin
  cifras ni promesas; se oculta cuando existe un mensaje del visitante. Los tres
  chips anteriores se conservan.
- Burbujas con avatar, fuentes como chips, puntos de «preparando respuesta»,
  dock con «Coordinar evaluación» y «Hablar con el equipo» (`data-chat-book`,
  `data-chat-human`), compositor en cápsula con autoajuste hasta 140 px y alertas
  compactas que siguen siendo `role="alert"`.
- Reserva en tres pasos (Horario, Tus datos, Confirmar) sobre el formulario
  existente: sin JavaScript todo queda visible como un solo formulario. Validación
  por paso con `noValidate`, Enter avanza en los pasos 1 y 2, resumen generado con
  `textContent`, consentimiento sin marcar y obligatorio; un 409 vuelve al paso 1
  con horarios refrescados. La confirmación solo aparece con la cita del servidor.
- Uiverse (MIT): andrew-demchenk0/spicy-fish-10 en las píldoras de horario y
  AqFox/tasty-robin-91 solo en el botón de enviar; avisos en
  `docs/UIVERSE_COMPONENTS.md` y `frontend/assets/licenses/uiverse-components.txt`.

Pruebas: `tests/frontend_chat.test.cjs` (chat.js real sobre el marcado real de
`chat.html` en un DOM sintético: validación de cada paso, Enter, 409, nuevo
`request_id`, confirmación) y su envoltura `tests/test_frontend_chat.py`;
`tests/test_core.py` comprueba `chat.js?v=7` y el orden de la hoja nueva.
Navegador (vista previa sintética): `/chat` a 1280, 375 y 320 px y `/soluciones`
a 1280, 768 y 375 px, sin desplazamiento horizontal ni objetivos menores de 44 px;
reserva completa de prueba con el asesor ficticio.

Límites: no se probó con lector de pantalla, ni `forced-colors` o
`prefers-reduced-motion` emulados (las reglas existen pero no se observaron). El
409 se verificó en la prueba Node, no contra el servidor. Las rutas de los dos
componentes de Uiverse proceden del encargo y no se volvieron a consultar.

Ajustes tras la revisión de diseño (mismo día): espacio vertical recuperado
(cabecera de una línea, avisos compactos, fotos con altura según la ventana);
mientras la reserva está abierta (`data-booking="open"`) el dock se reduce al
enlace con el equipo, se oculta el aviso de historial y Atrás/Continuar quedan
fijos al pie del panel; con una cita confirmada (`data-appointment="confirmed"`)
el botón principal pasa a «Ver mi cita» y se destaca «Hablar con el equipo»; la
confirmación muestra el sol completo sobre el horizonte; las fuentes se presentan
como «Fuente: <título publicado>» sin alterar el dato; los textos de interfaz
quedan en 13 px o más. Medido en vista previa sintética: a 1280×800 las tres
tarjetas caben completas en la primera vista; a 320×640 el área de conversación
pasa de 235 a 329 px y muestra dos tarjetas completas.

## Rediseño fase 3: `/soluciones` y `/empresa`, 21 de noviembre de 2026

Contenido oficial atribuido, sin cambios de servidor. `corporate.css?v=7`.

- `/soluciones`: sección `#como-funciona`, «Un sistema con batería, paso a paso»,
  con las seis ilustraciones oficiales (`sistema/*.png`) en orden placas →
  microinversores → batería → medición neta → red → hogar. Textos propios, sin
  cifras, ahorro ni garantías; aclara que el respaldo depende de capacidad,
  diseño y cargas conectadas y que los créditos de medición neta dependen de las
  reglas vigentes. Botón que abre el chat con una pregunta preparada.
- `/empresa`: «Lo que Power Solar publica de sí misma»: empresa netamente
  puertorriqueña establecida en 2018, parte de Power Group, misión publicada
  (cita corta), líneas Hogar/Apartamentos/Comercial/Techos y socios tecnológicos
  (Tesla como placas e instalador certificado, Enphase, UNIRAC, Fortress Power,
  EcoFlow; ver la nota de Canadian Solar más abajo). Aviso de que la página es de Team
  Caguas y no un sitio oficial. Mapa de proyectos comerciales y municipales
  (antes sin uso) con la lista en texto de sus 23 municipios.
- Omitido a propósito: empleados, clientes, años de experiencia del grupo,
  vientos de diseño de UNIRAC y socios de financiación (Power Financial,
  Oriental). Fuentes y fecha en `frontend/assets/power-solar/SOURCES.md`.

Pruebas: dos nuevas en `tests/test_official_content.py` (seis pasos con imagen
local, sin cifras; hechos atribuidos, sin cifras de clientes o empleados,
23 municipios). `test_public_intent_selector_…` contaba todos los botones con
`data-chat-prefill` y falló con el botón nuevo; ahora cuenta las cuatro
`.intent-option` y exige el botón del recorrido, con las mismas invariantes
(abre el chat, no envía, sin campos de contacto).

Revisión visual en la vista previa sintética (21 nov): `/soluciones` en 3/2/1
columnas a 1280/768/375 px y `/empresa`, sin desplazamiento horizontal ni
imágenes rotas. Corregido: el ancla `#como-funciona` dejaba el título bajo la
cabecera fija (99 px); ahora usa el mismo `scroll-margin-top: 110px` que
`#preguntas`. Sin cambiar: la cejilla `.corp-eyebrow` mide 12 px en todo el
sitio, anterior a esta fase. Pendiente: componentes Uiverse nuevos.

## Placas: Canadian Solar retirada, Tesla vigente, 21 de noviembre de 2026

Instrucción del titular: Canadian Solar ya no se trabaja; se venden placas Tesla.
Comprobado en las tres listas internas del 16 nov 2026 (Solo Placas, FlexiPay,
PF Loans y Lease), leídas solo para identificar marcas: las ofertas indican
«Panel Tesla», «Tesla Inverters» y baterías «PW»; ninguna menciona Canadian
Solar. No se copió ningún precio, pago mensual ni nivel de crédito.

- `/empresa`: se quitó Canadian Solar; Tesla figura como «Placas solares ·
  Power Solar es instalador certificado» (se quitó «según», que restaba
  confianza), con la aclaración de que las
  placas Tesla son la oferta actual de Team Caguas y el resto de marcas lo que
  muestra el sitio de Power Solar.
- Prueba nueva: ningún archivo de `frontend/` ni `reigel/` menciona Canadian.
- Fuera del alcance de este cambio: evidencias de conocimiento o notas guardadas
  en la base comercial (`%LOCALAPPDATA%/PowerSolar`), que no se leyeron ni se
  migraron. Si alguna menciona Canadian Solar, debe retirarla un administrador.
- Inversores y baterías: el titular confirmó «todo Tesla» el mismo día.
  `/empresa` quita Enphase y Fortress Power; Tesla figura como «Placas solares,
  inversores y baterías Powerwall · Power Solar es instalador certificado».
  UNIRAC (anclaje) y EcoFlow (baterías portátiles para apartamentos) se
  mantienen: no forman parte de la pregunta y las listas no los mencionan.
  `/soluciones` y la bienvenida de `/ia` dicen «Inversor» en lugar de
  «Microinversores» (la ilustración oficial es una caja genérica; la de batería
  ya muestra «TESLA»). La prueba de marcas retiradas cubre también Enphase y
  Fortress. Se conserva en `knowledge.py` la explicación general del
  microinversor (Departamento de Energía): es educativa y no dice qué se vende.

## `/ia` con IA local en la vista previa y promesas de beneficio, 21 de noviembre de 2026

Aviso reportado: «La IA local no está activada en este servidor». Causa: el único
servidor activo era la vista previa sintética, que no lee `.env` y por tanto no
tiene `REIGEL_CHAT_AI`; además Ollama estaba instalado pero apagado. No era un
fallo de código.

- `scripts/preview_team_caguas.py --ia-local` fija `REIGEL_CHAT_AI=ollama` solo
  en ese proceso (no lee `.env`, no descarga modelos); configuración
  `reigel-preview-ia` en `.claude/launch.json`. La vista previa normal sigue sin IA.
- Ollama se encendió con autorización del titular; `qwen2.5:3b` ya estaba instalado.

Prueba real con `qwen2.5:3b` en la vista previa: la tarjeta «Inversor»
(«¿Qué hace el inversor en un sistema solar?», cambiada hoy desde
«microinversor») produjo una respuesta que entendía «inversor» como quien
invierte dinero y decía que «puede recibir una rebaja en sus facturas… recibir
dinero de la compañía eléctrica» y «obtener un ahorro en sus facturas». Las tres
frases pasaban el validador, que solo bloqueaba cifras y «garantiz…».

- Validadores de `/ia` y `/chat` (`ai_chat._BENEFIT_PROMISES`): rechazan obtener,
  recibir, lograr o ganar ahorro, rebaja, descuento, dinero o reembolso, los
  futuros/condicionales de «ahorrar» y «rebaja en tu factura». Explicar de qué
  depende un ahorro sigue permitido.
- Instrucciones de `/ia`: «inversor» es el equipo que convierte corriente
  continua en alterna, no una persona que invierte dinero.
- Tarjeta: «¿Qué hace el inversor de corriente en un sistema solar?». Con el
  modelo real la respuesta pasó a explicar la conversión CC→CA, sin beneficios.
- Pruebas: las frases observadas y dos variantes en `QUANTITATIVE_CLAIMS`; dos
  explicaciones permitidas; la instrucción del glosario.

Límite: el validador sigue siendo de patrones, no semántico. Una sola respuesta
correcta del modelo no demuestra que no vuelva a equivocarse.

## `/precios`: simulador de mensualidad retirado, 21 de noviembre de 2026

Por instrucción del titular («no es necesario») se retiró el simulador
«Calcula la mensualidad del equipo» de `/precios`: sección `#simulador`,
`frontend/js/pricing.js` (eliminado; ya no se carga en ninguna página) y sus
reglas en `pricing.css` (`?v=3`). El botón principal del encabezado ahora lleva
a `#planes` («Ver los planes») y se quitó el enlace secundario duplicado. La
nota de planes y la pregunta frecuente sobre más de 15 vendedores ya no
mencionan el simulador. Se conservan los planes, módulos, roles, piloto,
condiciones y preguntas. La prueba de `/precios` exige ahora que no aparezcan
el simulador, sus importes de ejemplo ni `pricing.js`.

## Fase 1 de acceso: propietario, bajas y planes privados, 21 de noviembre de 2026

Objetivo del titular: el equipo paga por usar R.E.I.G.E.L., los clientes no ven
esa parte y el titular controla el sistema y puede cortar el acceso a quien
renuncie. Ya existía: autenticación propia (scrypt, cookie HttpOnly/SameSite,
sesiones en servidor) y desactivación que borra las sesiones.

- **Propietario.** Columna aditiva `users.is_owner` (`core.migrate_owner`). La
  cuenta creada con `bootstrap` es propietaria; en una base existente sin
  propietario activo lo es el administrador activo más antiguo. Solo el
  propietario crea, desactiva o da de baja administradores y ve la suscripción.
  Su cuenta no se puede desactivar ni dar de baja.
- **Baja en un paso** (`POST /api/team/{id}/offboard`, `OperationsMixin.offboard_user`):
  en una sola transacción pasa a la cuenta elegida las citas confirmadas
  futuras, los prospectos, las tareas pendientes y las conversaciones (en modo
  humano); deja `active=0` y `public_booking=0`, borra sus sesiones, anota el
  cambio de asesor en `lead_history` y audita `user.offboard`. Si una cita
  choca con la agenda de quien recibe, no cambia nada (409). Un administrador
  puede dar de baja asesores; nadie se da de baja a sí mismo. No se borra
  ningún registro. Las conversaciones privadas de `/ia` de esa cuenta quedan
  guardadas, sin acceso. En `/app`, la casilla «Cuenta activa» solo reactiva;
  desactivar se hace con «Dar de baja».
- **Planes fuera del sitio público.** Se retiraron `/precios`, sus enlaces
  (menú, móvil, pie y página 404), el sitemap, `frontend/pages/precios.html` y
  `pricing.css`. Como `/static` sirve todo `frontend/`, los planes ahora viven
  en `reigel/plans.py` y se entregan por `GET /api/owner/plans` solo al
  propietario; `/app` → «Suscripción» los muestra con las licencias en uso.
  No hay pasarela de pago: no cobra, no factura ni suspende.

Pruebas: `tests/test_owner_access.py` (8) y ajustes en
`tests/test_corporate_pages.py`. Vista previa sintética: el propietario ve
«Suscripción»; la baja de «Asesor · DEMO» transfirió 1 prospecto y 1 cita y su
cuenta quedó «Dado de baja».

Importante para la base comercial: al arrancar el servidor real con este código
se añadirá la columna `is_owner` y se marcará como propietario al administrador
activo más antiguo. No se probó contra la base comercial. Antes de reiniciar:
copia con `scripts/backup.py`, SHA256 guardado y confirmar quién debe ser el
propietario.

## Tema solar: paleta con color en todas las superficies, 21 de noviembre de 2026

Pedido del titular: más color y relación con los temas de Power Solar, a partir
de dos paletas: «Solar Power» (FFC100, FFDD02, 68A9F4, 3785EA, 2266DE) y
«Agencia Snappy» (CBF3F0, FFBF69, 2EC4B6, FF9F1C, FFFFFF).

- `frontend/css/solar-theme.css?v=2`, cargada la última en `/captacion` y las
  páginas corporativas, `/app`, `/ia` y `/chat`. Reasigna las variables de cada
  módulo (`--corp-*`, `--ui-*`, `--rc-*`, `--blue` de `/app`) y añade acentos;
  no reescribe las hojas existentes.
- Sitio: cabecera y pie con degradado nocturno y franja de amanecer
  (amarillo → dorado → naranja); portada con cielo claro y sol; encabezados de
  página con el mismo lavado; botones principales azul con flecha dorada;
  tarjetas, pasos del sistema, temas y socios con acentos alternos
  dorado/turquesa/azul/naranja; secciones de empresa y sistema con fondos
  menta y cielo.
- `/app` e `/ia`: barra lateral con degradado y franja de amanecer, elemento
  activo con marca dorada, paneles con acento superior, insignias en turquesa,
  azul y naranja; burbuja del usuario y botón de envío en azul.
- Contraste (WCAG AA, calculado): amarillos, naranja, turquesa, menta y cielo
  solo como fondo o decoración (texto navy encima: 7,6–14:1). Texto y enlaces de
  color en `#1b55c4` (6,0–6,7:1 sobre los lavados). Los degradados oscuros
  terminan en `#1747a8` para que el texto claro quede ≥ 7:1; con `#2266DE`
  daba 4,49:1 en la zona de la navegación. En `forced-colors` se retiran los
  degradados.
- Revisado en la vista previa sintética a 1280 y 375 px: sin desplazamiento
  horizontal; corregida la posición del sol sobre la foto, que heredaba `left`
  de la decoración anterior.
- Prueba: el tema es la última hoja en las cuatro superficies, contiene la
  paleta y no usa los colores claros como color de texto.

Límite: unas 650 declaraciones de color fijas en las hojas existentes no pasan
por variables; se ajustaron las piezas más visibles, no todas.

## `/chat` sin horarios en la demo, 21 de noviembre de 2026

Reporte: «Aún no hay horarios publicados» en `/chat`. Causa reproducida: el
servidor era la vista previa sintética y su único asesor con «Recibir reservas»
había sido dado de baja en la prueba de la fase de acceso (la baja desactiva
sus reservas públicas, como corresponde). `/api/public/config` devolvía
`advisors: []`. No era un fallo de reservas.

- La baja devuelve `public_booking_accounts`; si queda en 0, `/app` avisa que ya
  nadie recibe reservas desde el chat público y cómo activarlas. Prueba nueva.
- Demo reiniciada: reserva completa en `/chat` con datos ficticios (asesor →
  día → hora → datos → confirmación); la cita aparece en `/api/appointments`
  con instante UTC correcto y la conversación en la bandeja del equipo.

Para el servidor real: `/chat` solo ofrece horarios de cuentas activas con
«Recibir reservas» activado en «Equipo y ajustes → Horario». La solicitud de
atención humana queda en «Conversaciones» de `/app`; no hay aviso externo
(correo o WhatsApp) mientras esos canales no estén configurados.

## Código corto de cita, 21 de noviembre de 2026

Pedido del titular: la «Referencia» era el identificador interno de 32
caracteres hexadecimales, difícil de leer o escribir para personas mayores.

- Columna aditiva `appointments.reference` con índice único
  (`core.migrate_appointment_reference`); las citas existentes reciben código
  al arrancar. Seis caracteres de `ACDEFGHJKMNPQRTUVWXY34679` (sin 0/O, 1/I/L,
  2/Z, 5/S, 8/B), mostrados como `ABC-DEF`. Se generan con `secrets` y se
  reintenta ante colisión. El identificador interno no cambia ni se muestra.
- Las dos inserciones de citas (`core.book` y `webchat.book`) nombran ahora sus
  columnas: con la columna nueva, `VALUES(8 valores)` habría fallado.
- `/chat`: la tarjeta muestra «Código de tu cita» en grande y la frase «Si
  llamas o escribes al equipo, dales este código»; el mensaje dice la fecha
  como «domingo 22 de noviembre a las 10:00 a. m. (hora de Puerto Rico)» en
  lugar de `22/11/2026 a las 10:00 (America/Puerto_Rico)`.
- `/app`: la agenda muestra el código y la búsqueda de prospectos lo acepta en
  mayúsculas o minúsculas, con o sin guion o espacio.
- Pruebas: `tests/test_appointment_codes.py` (6) y ajustes en `test_core.py` y
  `frontend_chat.test.cjs`. Demo: reserva con código `6W3-K6R`, encontrado por
  «6W3-K6R», «6w3 k6r» y «6w3k6r».

En la base comercial, el próximo arranque con este código añadirá la columna y
asignará código a las citas existentes (incluidas en la copia previa exigida).

## Voz de asesor, cabecera del chat y doble alternativa, 21 de noviembre de 2026

**Voz.** El titular compartió una conversación real de Messenger como modelo de
trato. Solo se tomó el estilo: el nombre y los datos de la persona no están en
el código, las pruebas ni la documentación. `reigel/voice.py` define la guía
(mensajes cortos, de tú, cálidos; reconocer cada respuesta; una pregunta a la
vez con dos opciones; orden casa/apartamento → interrupciones o factura →
estudio de consumo previo), un ejemplo anónimo adaptado («hay diferentes
opciones…» en lugar de «trabajo con…», sin promesas) y el saludo según la hora
de Puerto Rico. Se añade a las instrucciones de `/ia`, al respaldo de IA de
`/chat` y a los borradores del equipo. «Entrenar» aquí es instrucción y
ejemplo: Ollama no se reentrena. Las tres respuestas del ejemplo pasan los tres
validadores. Prueba real con `qwen2.5:3b` en `/ia`: con «Buenas! Quisiera
información» → «Casa» → «Las alzas en la factura» respondió «¡Hola! ¿Es para
casa o apartamento?», «¡Perfecto! ¿Qué buscas solucionar…?» y «¡Súper! Hay
diferentes opciones… ¿anteriormente te han hecho un estudio de consumo?» (muy
cerca del ejemplo, porque las entradas eran las mismas). Límite: las
respuestas fijas del motor determinista de `/chat` no usan esta voz.

**Cabecera de `/chat`.** Azul plano `#0b2858`, sin degradado, anillos, sol ni
raya naranja inferior (`coordination-chat.css?v=3`).

**Doble alternativa.** «Coordinar evaluación» y «Hablar con el equipo» quedan
ocultos hasta que el servidor marca `next_step`: se conoce la necesidad
(factura y/o respaldo) y otro dato (municipio, factura o equipos a respaldar),
o la persona pidió cita, atención humana o un cambio de cita, o ya hay cita,
atención humana o baja. Una vez ofrecida no desaparece; entra con una
animación suave (sin animación con `prefers-reduced-motion`). Sin JavaScript
la barra sigue visible. Demo: «Las alzas en la factura» → oculta; «Vivo en
Caguas» → visible. Pruebas: `tests/test_voice.py`, `tests/test_chat_next_step.py`.

## Respuestas fijas de `/chat` con la voz de asesor, 21 de noviembre de 2026

Se reescribieron 43 textos del motor determinista (`webchat.py`): bienvenida,
preguntas de calificación, reserva, objeciones, mantenimiento, respaldo,
consumo, correcciones, baja comercial y atención humana. Tono de asesor de
Team Caguas (de tú, breve, «¡Perfecto!», «¡Súper!», una pregunta con dos
opciones), conservando cada límite: no prometer precios, aprobación, ahorros ni
garantías; no diagnosticar; no compartir documentos; la cita se confirma solo
con su código. El saludo usa la hora de Puerto Rico. Las respuestas de baja,
privacidad y `/start` no se cambiaron (son avisos legales). La pregunta final
ofrece la doble alternativa: «¿Quieres ver los horarios disponibles o prefieres
hablar con alguien del equipo?».

Hallazgo durante la prueba (anterior a este cambio): «Pago como 200»,
«alrededor de 200», «más o menos 180» y «cerca de 150 dólares» no se
entendían como factura. `conversation._ABOUT` añade «como», «alrededor de»,
«cerca de», «más o menos»; prueba parametrizada con seis frases.

Demo: «Las alzas en la factura» → «¡Súper! Hay diferentes opciones… ¿en qué
pueblo está tu hogar?» → «Caguas» → «¡Perfecto, Caguas! … ¿Más o menos cuánto
pagas de luz al mes?» → «Pago como 200» → «¡Gracias! Anoto $200… ¿Quieres ver
los horarios disponibles o prefieres hablar con alguien del equipo?», con la
barra de dos opciones visible. 446 pruebas de Python y 17 de Node.

Pendiente posible: el motor aún no pregunta «¿casa o apartamento?» ni por un
estudio de consumo previo; la IA de `/ia` sí lo hace.

## Lenguaje «en arroz y habichuela» en todo el sistema, 21 de noviembre de 2026

Reporte: en `/ia`, «¿Cómo convierten las placas solares la luz del sol en
electricidad?» recibió una respuesta técnica (fotones, electrones, protones,
«fotoelectricidad»), con un error de física, y empezando con «¡Perfecto!».

- `voice.PLAIN`: hablar como a una abuela o un vecino, palabras de todos los
  días, máximo tres oraciones, sin términos técnicos salvo que la persona los
  use, con comparaciones de la vida diaria. La guía ahora dice que «¡Perfecto!»
  y «¡Súper!» solo reconocen una respuesta de la persona; ante una pregunta se
  contesta directo. Ejemplo sencillo de placas (calculadora con cuadrito solar).
- `voice.GLOSSARY`: definiciones correctas y sencillas de placas, inversor,
  batería, medición neta, red, apagón y kW/kWh, iguales a `/soluciones` y a la
  base verificada. Motivo: con solo la regla de sencillez, `qwen2.5:3b` definió
  la medición neta al revés («cuentan solo lo que tú consumes, sin incluir lo
  que la luz del sol genera»).
- `/ia` ya no pide «lenguaje educativo»; el inversor se define sin corriente
  continua/alterna. Las ocho respuestas técnicas verificadas de
  `knowledge.py` (usadas en `/chat`), tres textos fijos de `webchat.py` y los
  pasos de `/soluciones` se reescribieron sin jerga, con el mismo contenido.
- Pruebas: la regla y el glosario llegan a las tres rutas de IA; ninguna
  respuesta fija, texto de conocimiento ni `/soluciones` usa la jerga listada;
  el glosario mantiene «la que le devuelve» y «créditos» en medición neta.

Prueba real (`qwen2.5:3b`, conversación nueva): medición neta → «un contador
que cuenta tanto lo que tomas de la luz de la calle [como] lo que regresas con
las placas solares» (correcto; escribió «quanto»); batería en apagón → guarda
lo de las placas de día para usarlo cuando se va la luz; kW/kWh → comparación
del carro. Límite: un modelo pequeño puede equivocarse o simplificar de más
(la de batería omitió que depende del tamaño y del diseño); el validador es de
patrones, no revisa si una explicación es correcta.

## Modo oscuro con el interruptor de Uiverse (Galahhad), 21 de noviembre de 2026

El titular pidió añadir el interruptor «strong-squid-82» donde hubiera
interruptores. No había ninguno de encendido/apagado (`crm-view-switch` es un
selector Tabla/Tablero y `menu-toggle` el botón del menú); el componente es de
día/noche, así que el titular eligió usarlo para el modo oscuro.

- Interruptor en la barra superior de `/app` y de `/ia`; detalle de la
  adaptación y licencia en `docs/UIVERSE_COMPONENTS.md` y
  `frontend/assets/licenses/uiverse-components.txt`.
- `theme.js` aplica el tema antes de pintar; guarda la elección en este
  navegador (`reigel-theme`, con try/catch) y, sin elección, sigue la
  preferencia del sistema y sus cambios. La elección en `/app` vale en `/ia`.
- `dark-mode.css`: variables y superficies de ambas vistas. Auditoría en el
  navegador de las 12 vistas de `/app` y de `/ia` (fondos claros, texto
  oscuro y contraste WCAG calculado): se corrigieron, entre otros, el botón
  «Volver» y las sugerencias de `/ia` (texto claro sobre blanco), la barra de
  periodo, listas, tarjetas, etiquetas y textos secundarios.
- Hallazgo previo, corregido en ambos modos: «+ Nuevo prospecto» tenía texto
  blanco sobre naranja (2,86:1); ahora navy (≈6,4:1).
- Sin corregir: el emblema «R.» de Automatización y la etiqueta de Marketing
  quedan cerca de 4:1 sobre degradados que la auditoría no mide con exactitud;
  vienen de antes.
- Verificado: teclado (espacio cambia el tema, foco visible), lector de
  pantalla («switch, Modo oscuro»), persistencia al recargar y paso a `/ia`;
  el sitio público no carga el tema. Nota: con el panel de vista previa oculto
  (`visibilityState: hidden`) las transiciones se congelan y las capturas
  muestran colores intermedios; no es un fallo del tema.

## `/soluciones`: crédito visible retirado, 21 de noviembre de 2026

Por instrucción del titular se quitó de la sección «Cómo funciona» la línea
«Ilustraciones: Power Solar, powersolarpr.com (consultado el 19 de noviembre
de 2026). Textos de Team Caguas.». La fuente y la fecha siguen registradas en
`frontend/assets/power-solar/SOURCES.md`; la prueba ahora exige que la línea no
aparezca en la página y que la fuente siga en ese registro. Queda una línea
parecida en la bienvenida de `/ia` («Ilustraciones: Power Solar,
powersolarpr.com. Toca un tema…»), que no se tocó.
Después, también por instrucción del titular, se quitó el crédito de la
bienvenida de `/ia` (y `/`); se conserva la indicación «Toca un tema para llevar
la pregunta al campo de mensaje.». Prueba nueva para `/soluciones`, `/ia` y `/`.

## `/ia`: letras «cortadas», acciones inventadas y ahorro, 21 de noviembre de 2026

Reporte: «¡Perfecto! Para evaluar el consumo y os costos… primero revisamos…
hacemos un seguimiento… dónde puedes ahorrar».

- Letras: no se pierden en el sistema. Con el modelo real, el texto enviado
  por SSE y el guardado coinciden carácter por carácter en tres pruebas. «os
  costos», «quanto», «custos» son errores del propio `qwen2.5:3b`.
- «¡Perfecto!» al contestar una pregunta: ahora se quita en el servidor
  (`ai_chat.opening_ack`) salvo que la persona esté contestando una pregunta
  de R.E.I.G.E.L. (`answering_our_question`). El modelo no seguía la instrucción.
- Acciones inventadas: la guía prohíbe «revisamos», «calculamos», «podemos
  hacer»; el glosario añade «evaluación o estudio de consumo» en tercera
  persona; el validador de `/ia` y de `/chat` rechaza esas formas, «hagamos»,
  «te puedo ofrecer» y «una visita» (`_TEAM_ACTIONS`).
- Ahorro: la guía pide no usar «ahorrar»; el validador rechaza «puedes/puedas
  … ahorrar», «formas/áreas de ahorrar» y «puede(n) ahorrar».
- Respuesta rechazada: se muestra el mensaje seguro (`SAFE_REPLACEMENT`).

Medición con modelos locales ya instalados (12 respuestas, mismo filtro):
`qwen2.5:3b` 10/12 aceptadas pero con faltas y simplificaciones;
`llama3.2:3b` 8/12, con mejor español y salvedades, y sus 4 rechazos en la
misma pregunta por «cómo puedes ahorrar». El modelo se elige con
`REIGEL_CHAT_MODEL` (configuración del servidor; no se cambió).

## Prueba de `llama3.2:3b` en la vista previa, 22 de noviembre de 2026

A pedido del titular, la demo con IA usa `llama3.2:3b` (ya instalado; no se
descargó nada): `scripts/preview_team_caguas.py --ia-modelo` y la
configuración `reigel-preview-ia`, ahora en el puerto 8878 (antes compartía el
8877 con la demo sintética y la app la movía sola). El servidor real no cambia:
su modelo sigue siendo el de `REIGEL_CHAT_MODEL` (o `qwen2.5:3b` por defecto).

- Pregunta de consumo y costos: con `llama3.2:3b` se rechazaba siempre por
  «cómo puedes ahorrar». Se añadió a la guía un ejemplo sencillo y una entrada
  de glosario («consumo y costos de la luz»), sin datos no verificados.
- Filtro ampliado con lo observado: «miramos», «veamos», «queremos ver» y
  pedir que la persona traiga, envíe o comparta facturas. Se quita también
  «¡Excelente pregunta!» al empezar.
- Medición final (12 respuestas, mismo filtro): 10 aceptadas; los 2 rechazos
  fueron «primero miramos», atrapados correctamente. Flujo del asesor
  idéntico al ejemplo. Español sin faltas.
- Límite: una respuesta aceptada explicó la medición neta con un «contador de
  bicicletas» confuso; otra dijo que el contador «devuelve» la electricidad.
  El filtro es de palabras y no detecta explicaciones incorrectas.

## IA encendida 24/7 en la computadora del titular (opción provisional), 22 de noviembre de 2026

Diagnóstico (sin cambios en el equipo): Windows se suspende a los 15 minutos
con corriente; Ollama arranca solo al iniciar sesión (clave Run «Ollama
Server») pero nada lo levanta si se cierra; el servidor de R.E.I.G.E.L. solo
arranca a mano y escucha en `127.0.0.1`; `compose.yaml` no incluye Ollama y la
dirección de Ollama está fija en el código.

Preparado (el titular registra la tarea; no se registró nada):
`scripts/run_forever.ps1` (supervisor), `scripts/install_autostart.ps1`
(copia de seguridad → tarea al iniciar sesión, o al encender con
`-SinIniciarSesion` tipo S4U sin contraseña → arranque y comprobación) y
`scripts/uninstall_autostart.ps1`. Guía: `docs/OPERACION_24_7.md`. El
supervisor evita la suspensión con `SetThreadExecutionState` solo mientras
corre; no cambia opciones de energía.

Probado en modo demo (`-Preview`, puerto 8879, base sintética): arranque,
reinicio tras matar el servidor (10 s: espera de 5 s más el arranque), segunda
copia que termina sola, registro con acentos correctos, limpieza de procesos.
Corregido durante la prueba: archivos guardados como UTF-8 con BOM (PowerShell
5.1 los leía como ANSI), código de salida conservado y detección inmediata de
la caída. Pruebas estáticas en `tests/test_autostart_scripts.py`.

No probado: el registro real de la tarea, el arranque sin sesión ni el primer
arranque contra la base comercial (migración de propietario y códigos de cita).

## `/ia`: generación suave con el sol de Power Solar, 22 de noviembre de 2026

Pedido del titular: que el texto aparezca de forma suave (no a golpes de
frase) y que en la punta del texto haya un sol cuyo aro de rayos gire como
engranaje mientras el rayo eléctrico queda quieto.

- El servidor sigue enviando solo frases ya validadas; el navegador las revela
  por palabras completas a ritmo constante (mínimo 60 caracteres por segundo,
  más rápido si se acumula texto, para no quedarse atrás) y cada tramo entra con
  un fundido de 0,5 s. Al terminar, el mensaje espera a que acaben de aparecer
  las últimas palabras (máximo 6 s) antes de fijarse.
- Sol en SVG propio (`ia.js`, `SUN_SVG`): 12 rayos que giran (3,2 s por
  vuelta), aro y rayo fijos, color `#f9b000`; centro blanco en modo claro y del
  color del fondo en oscuro. Sustituye al cursor naranja parpadeante y a los
  tres puntos de espera. Decorativo (`aria-hidden`); la espera conserva el
  aviso para lectores de pantalla.
- Sin animación (movimiento reducido, pestaña oculta o entorno sin
  `requestAnimationFrame`) el texto aparece de inmediato.
- Corregido de paso: la nota «Respuesta incompleta.» aparecía mientras la
  respuesta se estaba escribiendo; ahora solo en respuestas guardadas sin
  terminar.
- Verificado con `llama3.2:3b` en la demo (puerto 8878): sol durante la espera
  y en la punta, crecimiento gradual (0 → 16 → 61 → 96 → 166 caracteres…), sol
  retirado al terminar. El panel de vista previa estaba oculto, así que el
  avance por fotogramas se simuló con un temporizador solo en esa prueba.

## `/ia`: las sugerencias se envían al tocarlas, 22 de noviembre de 2026

Antes: tocar una sugerencia («Cómo funciona la evaluación», las tarjetas del
sistema) pegaba la pregunta y había que pulsar Enviar. Ahora se envía de
inmediato. Si ya se está escribiendo una respuesta o la IA no está
disponible, la pregunta queda en el campo como antes, para no perderla. El
texto de ayuda dice «Toca un tema y R.E.I.G.E.L. te contesta enseguida.».
Prueba nueva en `tests/frontend_ia.test.cjs`; verificado en la demo
(puerto 8878) con respuesta real. Los botones de temas del sitio público que
abren `/chat` siguen preparando la pregunta sin enviarla («Tú decides si la
envías»); no se cambiaron.

## Botones de temas del sitio: envío directo con autorización de un solo uso, 22 de noviembre de 2026

Pedido del titular: los temas del sitio público también se envían al
tocarlos. Regla de seguridad diseñada por el titular para `/ia`, donde la
pregunta llega en la dirección (`/ia?q=…`) y cualquiera podría compartir un
enlace así:

- Al tocar un tema, `chat.js` guarda en `sessionStorage` (`ia:autosend`) la
  pregunta y la hora, y navega en la misma pestaña.
- `ia.js` (`shouldAutoSend`, escrita por el titular) envía solo si la IA está
  lista, no hay otra respuesta en curso, y la autorización existe, es de la
  misma pregunta y tiene menos de 30 s. La autorización se consume siempre,
  aunque se rechace. Sin ella (enlace compartido, otra pestaña, más de 30 s o
  pregunta distinta) la pregunta solo se pega en el campo.
- Si la IA no estaba lista al cargar, la autorización no se consume y la
  pregunta sale sola cuando la IA queda disponible («Reintentar»), dentro de
  los 30 s y si el visitante no la cambió (`autoSendPending`).
- La pregunta enviada desde un tema abre su propia conversación.
- Sin IA disponible, el botón abre el chat de citas y la pregunta se envía al
  abrirse.
- Texto de `/soluciones`: «Elige un tema y R.E.I.G.E.L. te contesta
  enseguida.» (antes «Tú decides si la envías»).

No es autenticación: evita que un enlace externo hable en nombre del
visitante. Pruebas: tres casos nuevos en `tests/frontend_ia.test.cjs`
(autorizado, enlace externo, autorización vencida o distinta) y
`test_core.py` actualizado. Demo (8878): tema desde `/soluciones` → enviado
y respondido, autorización consumida; `/ia?q=…` directo → solo en el campo.

## `/ia`: motor de sugerencias conversacionales, 22 de noviembre de 2026

Propuesta del titular: 160 preguntas con rotación, contexto y memoria. Implementado
en `reigel/suggestions.py` y `GET /api/ia/suggestions` (solo lee conversaciones del
solicitante; ajena = 404). Selección determinista, sin tokens: 6 por ronda, una por
categoría en la primera pasada, nunca una pregunta ya hecha, sin repetir las vistas
hasta agotar el banco. Puntuación: relevancia del contexto (mensajes recientes pesan
más), nivel según el avance, empujón leve a evaluar/preparar y seguir el último tema.
La interfaz las muestra bajo la bienvenida y tras cada respuesta; al tocar se envían.
Doble clic = un envío; un error de conexión devuelve la pregunta al campo.

Catálogo: 103 preguntas en palabras sencillas. Excluidas de las 160: cifras y cálculos
(cuántas placas, W, horas, costo total, recuperación), ahorro y rentabilidad, jerga
(MPPT, LFP, mono/policristalino, corriente alterna/continua, demanda), pedir datos de
factura, revisar contratos, equipos médicos (requiere una persona) y marcas. Tras
probar con `llama3.2:3b` se retiraron seis de mantenimiento, limpieza, daños y
tormentas: el modelo indicó limpiar con paño o agua y afirmó hechos falsos.

Guía y filtro añaden: no subir al techo ni manipular equipos (`_UNSAFE_DIY`).
Medición real: una pregunta por categoría, 15/15 aceptadas por el filtro, pero varias
con imprecisiones; preguntas de riesgo, 10/12 aceptadas y aún con consejos inseguros.
Límite: si alguien ESCRIBE esas preguntas, la respuesta sigue siendo generada y el
filtro de patrones no garantiza que sea correcta. Sin sugerencias generadas por IA.

## Respuestas fijas de seguridad, 22 de noviembre de 2026

`reigel/safety.py` detecta, sin usar el modelo, emergencias (humo, chispas, fuego,
olor a quemado, cable caído, descarga), revisión tras tormentas, limpieza o subir al
techo, daños o manipulación de equipos, y mantenimiento. Responde con un texto fijo:
no tocar, alejarse, técnico cualificado y, en emergencia, 911.

Cubre las tres rutas que responden a clientes: `/ia` (antes de `stream_workspace`),
`/chat` (`WebChat._answer`) y el modo IA de canales (`channels._respond_locked`), que
envía sin revisión humana. Las dudas generales siguen al modelo («¿por qué el sistema
no funciona en un apagón?»), y ninguna sugerencia del catálogo cae en una respuesta fija.

Verificado: `tests/test_safety.py` (incluye que el modelo no se llama en `/ia` ni en
canales) y demo en 8878: cinco preguntas de riesgo con respuesta fija en menos de
60 ms y dos preguntas normales respondidas por `llama3.2:3b`. Canales: solo con envío
simulado; no se envió ningún mensaje real.

Límites: la detección es por patrones; una forma no prevista de preguntar llega al
modelo. Los textos fijos conviene que los revise una persona responsable de seguridad
de Power Solar. La respuesta del modelo a «¿por qué el sistema no funciona en un
apagón?» sigue siendo generada y puede ser imprecisa.

## `/soluciones`: visualización interactiva de energía, 22 de noviembre de 2026

Sección `#energia-en-casa`, antes de «Un sistema con batería, paso a paso». Escena SVG
original tomando como referencia visual una captura de otra aplicación; no se usa la
captura, su marca ni sus medidas. Archivos: `frontend/css/energy-scene.css`,
`frontend/js/energy-scene.js` (sin dependencias ni llamadas de red).

- Seis estados: día, noche y apagón, cada uno con y sin batería. Partículas por
  dirección entre placas, inversor, batería, red y casa; corte visible de la red;
  ventanas según el estado; anotaciones progresivas con `IntersectionObserver`; cámara
  sutil solo con puntero fino.
- Sin cifras: los indicadores son estados y barras ilustrativas, con la etiqueta
  «Simulación educativa · No son datos de tu casa». Se omitieron kW, porcentajes y horas
  de la referencia por la política de contenido del sitio.
- Apagón sin batería: las placas se apagan por seguridad y la casa queda sin luz. Con
  respaldo: solo los equipos conectados, según tamaño y diseño.
- Sin JavaScript se ve el estado de día y los controles quedan ocultos.

Verificado: `tests/test_energy_scene.py`; seis estados en navegador; 1280 y 375 px sin
desbordes; controles de 44 px; sin texto menor de 13 px en el panel; recursos 200; rutas
existentes intactas. Límites: el panel de vista previa estaba oculto, así que la fluidez
real no se midió (solo 7 cuadros simulados, 0,2 ms de promedio); `prefers-reduced-motion`
quedó implementado y revisado en código, pero no se emuló en navegador. Sin publicar.

## `/soluciones`: rediseño de la consola de energía, 22 de noviembre de 2026

`#energia-en-casa` pasa a ser una maqueta iluminada con instrumentos integrados
(`energy-scene.css` y `.js`, `?v=7`). Una evaluación de diseño pidió cambios y se
aplicaron: ruta red → panel → casa de noche sin batería, apagón con batería claramente
de día, carga y descarga visibles, aviso de que el respaldo dura mientras haya carga,
letra mayor y botón flotante que solo cede si taparía los controles.

Pendiente: segunda evaluación de diseño (no se ejecutó), lector de pantalla, teléfono
físico, `forced-colors` y contraste sobre el cielo de apagón de día. El apagón de noche
solo se explica en texto. Sin commit ni publicación.

## R.E.I.G.E.L. Identity (2026-11-22)

- Clientes (`/cuenta`) y Team (`/app`, `/app/acceso`) usan tablas, cookies y sesiones separadas. Migraciones aditivas `reigel_identity_v1` y `reigel_identity_totp_v2`; se aplican al arrancar y no se ejecutaron sobre la base comercial.
- El segundo factor del Team es TOTP compatible con Google Authenticator. El secreto se cifra con `REIGEL_TOTP_KEY` o con `<base>.totp.key`, junto a la base y fuera del repositorio. Desde SEC-003, `scripts/backup.py` copia también esa clave como `<copia>.totp.key` y, si falta con autenticadores registrados, el servidor falla cerrado en vez de crear otra (ver «SEC-003»).
- Comprobado con pruebas locales, vectores RFC 6238 y un escaneo del QR con Google Authenticator en un teléfono real sobre la demo sintética (2026-11-22). Sin probar: OAuth con proveedores reales.
- Bloqueado hasta configurar: credenciales OAuth y un canal autorizado de correo/SMS. Sin canal, correo y teléfono no se pueden verificar ni recuperar; el acceso por usuario sí funciona.
- Transición del Team (sustituida el 25 de noviembre de 2026, ver «Acceso del equipo endurecido»): ya no existe la entrada solo con contraseña ni la política `team_totp_required`; Google Authenticator es obligatorio para todas las cuentas.

## Fase 1 de aprendizaje, tramo A: cola con aprobación humana y banco de preguntas, 25 de noviembre de 2026

R.E.I.G.E.L. puede registrar lo que no supo responder bien, una persona del equipo
propone una respuesta y solo un administrador la aprueba. Aprender y publicar son pasos
separados: en este tramo nada aprendido llega a un cliente. No se editaron
`ai_chat.py`, `voice.py`, `assistant.py` ni `api.py` (otra tarea los modifica); se
importan solo para leer.

- `reigel/learning.py`: migración aditiva e idempotente `learning_queue_v1` (tablas
  `learning_gaps`, `learning_proposals`, `learning_eval_cases`, `learning_eval_runs`),
  aplicada al construir `LearningQueue(store)`. Desde el tramo B la construye `create_app`
  (ver abajo); en desarrollo solo se aplicó a bases temporales.
- Flujo: `record_gap` (agrupa por ruta y clave normalizada; conserva el motivo de mayor
  incertidumbre; un hueco resuelto que reaparece se reabre), `propose` (asesor o
  administrador, con fuente o criterio obligatorio), `approve`, `reject`, `reject_gap`,
  `resolve` (solo administrador) y `list` (asesor o administrador desde el tramo B: tras
  redactarla, la cola no contiene datos de visitantes y el asesor la necesita para proponer;
  filtrable y ordenado por prioridad actual, con horas en `America/Puerto_Rico`; se guarda UTC). Cada acción queda en
  `audit_events`, incluido un intento de aprobación bloqueado.
- Al aprobar, la respuesta debe pasar `validate_reply` (/chat) y
  `validate_workspace_reply` (/ia) con `verified=True`, más un veto propio a cualquier
  mención de financiación. Si no pasa, la aprobación se rechaza con el motivo y la
  propuesta sigue pendiente.
- Privacidad: la pregunta se guarda redactada con `ia_workspace.hide_contacts` (correos y
  teléfonos) más un ocultamiento propio de números muy largos, direcciones postales,
  números de cinco o más cifras y nombres presentados («me llamo…», «soy…»). No hay
  columnas de conversación, visitante, IP, cookie ni nombre. El ocultamiento es por
  patrones: un nombre sin presentación o una dirección sin palabra clave pasan.
- Retención: `purge_expired` borra los huecos no aprobados (abiertos, propuestos o
  descartados) cuya última aparición supera 90 días, con sus propuestas. Es explícita:
  nada la programa todavía. No sustituye ni atiende las solicitudes de acceso,
  corrección o eliminación de `privacy.py`.
- Prioridad `P = 100 × U × R × N / (1 + C)`, de 0 a 100: U por motivo, R por tema con los
  patrones de `suggestions.TOPICS`, N mitad frecuencia y mitad recencia, C fijo (0,25 por
  defecto, configurable por instancia). Es una heurística para ordenar la cola, no una
  ley ni una medida de impacto.
- `reigel/learning_eval.py`: 10 casos iniciales (techo de madera, colocar placas, sombra,
  reserva, hablar con una persona, baja, privacidad, precio, ahorro y financiamiento) con
  expectativas por patrones y un evaluador. `publish_like_ia` copia el recorrido de
  `api.ia_events` sobre la respuesta completa; si la ruta cambia, hay que actualizarlo.
- `scripts/eval_ia.py`: ejecuta el banco contra Ollama local con las instrucciones de /ia
  (`ai_chat.stream_workspace`), en una base temporal que se borra al salir (`--output`
  guarda una copia en JSON). No lee `.env` ni descarga modelos; si Ollama no responde,
  termina con código 2. Una respuesta sustituida por el mensaje seguro cuenta como pasada
  para la persona, pero el resumen la señala aparte.

Corridas reales (qwen2.5:3b, 25 nov 2026, temperatura de /ia, resultados variables entre
corridas): 6, 6 y 7 de 10. Fallaron siempre reserva («Reservaste una cita»), baja («No
recibirá más mensajes», «no enviaré más mensajes») y privacidad (nunca remitió a «Citas y
equipo»); hablar con una persona falló dos veces («hablaré como si fuera una persona del
equipo») y la tercera la ruta la sustituyó. Esas frases pasaron el validador de /ia y se
habrían publicado; corregirlo toca `ai_chat.py` y queda para la tarea que lo edita. Los
patrones del banco se ampliaron con esas frases observadas. Los tres casos de techo pasan
gracias a la invitación fija que añade la ruta: el modelo solo no invitó a «Citas y equipo».

Límites: los validadores y las expectativas son patrones, no revisión semántica (por
ejemplo, «el equipo de financiamiento» o «te hará un estudio» pasan). El banco mide solo
/ia; los resultados de una corrida no llegan a `/app` hasta el tramo B. Pendiente (tramo
B): captura en `ai_chat`, rutas en `api.py`, vista «Aprendizaje» en `/app` y uso de lo
aprobado como «Respuestas revisadas por el equipo». Sin commit ni publicación.

## Fase 1 de aprendizaje, tramo B: captura, rutas, vista «Aprendizaje» y validadores, 25 de noviembre de 2026

Corrección de seguridad primero. El banco mostró que /ia publicaba acciones que no
hace («Reservaste una cita», «No recibirás más mensajes de nuestra parte», «¿Quieres que
te ayude a hacer esa llamada?», «hablaré con una persona del equipo») y frases en
portugués.

- `ai_chat.claimed_action` rechaza afirmaciones de reserva, baja o registro, borrado de
  datos, llamada o contacto prometido, y traspaso al equipo o hacerse pasar por persona.
  `ai_chat.mixes_portuguese` rechaza ã/õ/ç y palabras portuguesas que no existen en
  español («ou», «com», «agora», «pergunta», «ajudar», «avaliação»…). Se aplican en
  `validate_workspace_reply` y `validate_reply`. En `assistant.validate_draft` solo se
  aplican las reservas, bajas, borrados y el portugués: en el modo `ai` de un canal el
  equipo sí puede atender o llamar, así que ofrecerlo sigue permitido. El inglés no se
  bloquea. Falso positivo conocido: «No puedo decirte cuánto vas a ahorrar» se retira por
  el patrón de ahorro ya existente.
- Peticiones de reserva, cambio de cita, hablar con una persona, baja y privacidad en /ia:
  se detectan con el clasificador determinista de /chat y, si la respuesta aceptada no
  menciona «Citas y equipo», el servidor añade una frase fija validada
  (`ai_chat.REFERRAL_INVITATIONS`), como ya hacía con el techo. Si el modelo afirma la
  acción, se sustituye por el mensaje seguro, que también remite a «Citas y equipo».
- `ai_chat.WorkspaceOutput` es ahora la frontera de salida de /ia: la usan
  `api.ia_events` y `learning_eval.publish`, así que el banco mide lo que se publica, no
  una copia.

Tramo B:

- `create_app` construye `LearningQueue` sobre su propia base (migración aditiva) y ejecuta
  la retención de 90 días al arrancar y, como mucho, una vez al día al listar la cola. En
  desarrollo solo se ejecutó en bases temporales; el servidor real la aplicará la próxima vez
  que arranque con `main.py`.
- Captura sin bloquear ni filtrar datos (errores de registro solo se anotan en el registro,
  sin contenido): /ia registra `blocked` cuando sustituye una respuesta y `model_error`
  cuando el modelo falla; /chat registra `fallback` cuando el modelo se pidió y no se usó, o
  cuando sale la respuesta genérica, y `no_knowledge` cuando no hay fuente verificada. Se
  guarda el texto ya enmascarado y redactado.
- Rutas (`actor`, `payload`, `DomainError`, controles de origen y límites por IP y por
  cuenta): `GET /api/learning/gaps`, `GET /api/learning/gaps/{id}/proposals`,
  `POST /api/learning/gaps` (señalar, `staff_flag`), `POST /api/learning/gaps/{id}/proposals`
  (asesor o administrador); `POST /api/learning/proposals/{id}/approve|reject` y
  `POST /api/learning/gaps/{id}/reject|resolve` (solo administrador);
  `GET /api/learning/eval` (equipo) y `POST /api/learning/eval` (solo administrador, cuatro
  por hora, en segundo plano, exige el modelo local configurado disponible y guarda la corrida
  en `learning_eval_runs`).
- Vista «Aprendizaje» en /app (`frontend/js/learning.js`, `frontend/css/learning.css`):
  último resultado del banco, cola por prioridad con filtros, proponer, señalar, y para
  administradores aprobar, rechazar, descartar, resolver y ejecutar el banco. Texto escapado;
  el servidor vuelve a comprobar cada permiso.
- Lo aprobado se ofrece al modelo como «Respuestas revisadas por el equipo de Power Solar»
  (hasta tres, por coincidencia de palabras con la pregunta, en /ia y en /chat). No cuenta
  como fuente verificada para los validadores y se revalida al leerla.

Banco tras la corrección (scripts/eval_ia.py, 25 nov 2026, resultados variables entre
corridas): primera corrida, 10 de 10 con cada modelo; corrida final, qwen2.5:3b 9 de 10 con
cinco sustituciones y llama3.2:3b 10 de 10 con dos. El fallo de qwen es de financiamiento:
«cómo te van a aprobar el financiamiento» dentro de una negación, que el patrón del banco no
distingue. Varios casos de remisión pasan gracias a la frase fija del servidor, no al modelo.
Falsos positivos observados en `coaches_installation` (no modificado): «No es tarea de la
persona colocar las placas» y «la cantidad de placas solares que se instalen» se retiran.

Sin verificar: la vista en el navegador de la vista previa 8878, porque no se reinició el
proceso (el reinicio fue denegado) y sigue con el backend anterior. Sin commit ni publicación.

## Acceso del equipo endurecido: Google Authenticator obligatorio y correos autorizados, 25 de noviembre de 2026

Pedido del titular: el acceso a `/app` debe exigir Google Authenticator y limitarse a cuentas de Power Solar.

### Qué cambió

- **Google Authenticator (TOTP) obligatorio para todas las cuentas** (propietario, administradores y asesores), sin excepciones ni interruptor.
  - `Store.login` (`reigel/core.py`) solo comprueba la contraseña y devuelve el paso siguiente; nunca crea sesión. Con TOTP registrado responde `{"mfa_required": true}`; sin TOTP, `{"mfa_required": true, "enrollment_required": true}` y una cookie `reigel_team_enroll` (HttpOnly, SameSite=Strict, ruta `/api/team-identity/totp`, 10 minutos).
  - Primer acceso: `POST /api/team-identity/totp/enroll` devuelve el QR y `POST /api/team-identity/totp/enroll/confirm` valida el primer código, registra el autenticador y solo entonces crea la sesión. Ese ticket nunca reemplaza un autenticador ya registrado (409); eso solo lo hace un código de recuperación.
  - Se eliminaron `POST /api/team-identity/totp/disable`, `PUT /api/team-identity/policy`, `Identity.totp_disable`, `Identity.set_totp_policy` y `password_login_gate`. La fila antigua `team_totp_required` queda intacta e ignorada.
  - `Store.session_user` rechaza cualquier sesión de una cuenta sin TOTP o cuyo correo ya no esté autorizado; las sesiones creadas antes de este cambio dejan de dar acceso hasta que la persona registre Google Authenticator.
  - Teléfono perdido: solo el flujo existente de código de recuperación (`/app/acceso` o `scripts/team_recovery.py` en el servidor).
- **Lista de correos autorizados, controlada solo por el propietario** (`reigel/team_access.py`, tabla `team_allowed_emails`).
  - Solo un correo de la lista puede crearse como usuario del equipo, iniciar sesión, completar un código o conservar sesión. Correos normalizados (sin espacios, en minúsculas).
  - Siembra opcional desde `REIGEL_TEAM_ALLOWED_EMAILS` (separados por comas) en cada arranque: solo añade correos que nunca estuvieron en la lista; no quita ninguno y no vuelve a añadir uno que el propietario quitó. Las entradas no válidas se ignoran sin escribir su valor en el registro.
  - Quitar un correo cierra al instante sus sesiones, pasos de acceso pendientes y códigos de registro o recuperación sin usar. No se borra ningún registro (la fila queda marcada con `removed_at`).
  - Protección contra bloqueo: la cuenta del propietario no se puede quitar (409), su correo se vuelve a autorizar en cada arranque y la regla «Power Solar» nunca la bloquea.
  - Errores de acceso genéricos: correo desconocido, cuenta inactiva, correo fuera de la lista o contraseña incorrecta reciben el mismo 401 «Correo o contraseña incorrectos.», con una verificación Argon2id completa (hash ficticio cuando no aplica) y una sola escritura de auditoría `auth.login_failed` en todos los fallos.
  - Rutas del propietario (sesión, rol de propietario en servidor y cabecera CSRF en escrituras; correo en el cuerpo JSON, nunca en la URL): `GET /api/team-access` (120/min), `POST /api/team-access/emails`, `POST /api/team-access/emails/remove` y `PUT /api/team-access/name-rule` (30/hora por dirección y por cuenta).
  - Interfaz: panel «Correos autorizados» solo para el propietario en `/app` → «Equipo y ajustes». Todo el texto se escapa.
- **Regla «Power Solar»**: con la regla activa (predeterminado), un correo autorizado debe contener `powersolar` (sin distinguir mayúsculas) en el nombre o en el dominio. Solo el propietario la activa o desactiva; al activarla se cierran las sesiones de las cuentas que no la cumplen. **Es un filtro organizativo, no un control de seguridad**: cualquiera puede crear un correo con esa palabra. Los controles reales son la lista y Google Authenticator. Así se explica en el código, aquí y en la interfaz.
- Auditoría en `audit_events`: `team_access.email_seeded`, `team_access.email_added`, `team_access.email_removed`, `team_access.owner_auto_allowed`, `team_access.name_rule.0/1`, `auth.sessions_revoked`, `auth.password_ok`, `auth.login_failed`, `auth.login`, `team.totp_enrolled_at_login`.
- `/api/public/config` publica ahora solo `name`, `timezone`, `market`, `privacy_contact` y `site_url`; antes exponía todos los ajustes internos.
- Migraciones aditivas e idempotentes: `reigel_team_access_v1` (tabla `team_allowed_emails`, ajuste `team_email_name_rule=1`) y `reigel_identity_totp_mandatory_v3` (tabla `team_enroll_challenges`). No se ejecutaron sobre la base comercial.

### Antes del próximo arranque real de `main.py` (para no quedarse fuera)

1. Hacer una copia de la base comercial con `scripts/backup.py` y conservar la clave TOTP (`REIGEL_TOTP_KEY` o el archivo `<base>.totp.key` junto a la base). Sin esa clave, cada persona tendría que usar un código de recuperación.
2. Decidir la lista inicial:
   - escribir en `.env` `REIGEL_TEAM_ALLOWED_EMAILS=ana.powersolar@example.com,luis.powersolar@example.com` con el correo de cada integrante real; o
   - no definirla y confiar en la autorización automática del propietario: solo el propietario podrá entrar y después añadirá a los demás desde `/app` → «Equipo y ajustes» → «Correos autorizados».
3. Comprobar que el correo de cada integrante real contiene `powersolar` en el nombre o en el dominio. Si alguno no lo cumple, el propietario debe entrar primero y desactivar la regla «Power Solar» en ese mismo panel; hasta entonces esa persona recibirá el error genérico. La cuenta del propietario nunca queda bloqueada por esta regla.
4. Avisar al equipo: al arrancar, todas las sesiones abiertas dejan de servir. En su próximo acceso cada persona, incluido el propietario, escribe su contraseña, escanea el QR con Google Authenticator y confirma un código de 6 dígitos (hora del teléfono en automático). Desde entonces entra siempre con contraseña y código.
5. (Sustituido por SEC-003: el primer registro exige además un código de invitación.) Como la primera persona que entra con una contraseña registra el autenticador, las contraseñas iniciales se entregan por un canal privado y cada persona debe entrar pronto. Si alguien pierde el teléfono, un administrador emite un código de recuperación en `/app/acceso`; si es el propietario, se usa `scripts/team_recovery.py` en el servidor.

### Demostración sintética

`scripts/preview_team_caguas.py` crea cuentas `example.com` que contienen `powersolar`: propietario `admin.powersolar@example.com` y asesor `asesor.powersolar@example.com`, preinscritos solo en la demo con una clave TOTP aleatoria de cada ejecución que se imprime junto a las contraseñas sintéticas, y `nuevo.powersolar@example.com` sin TOTP para mostrar el registro obligatorio. `--codigo CLAVE` imprime el código actual de una clave sintética. La preinscripción comprueba `synthetic_preview` y no existe fuera de la demo.

### Verificación
- `.\.venv\Scripts\python.exe -m pytest -q`: 830 passed (incluye `tests/test_team_access.py`, nuevos casos en `tests/test_identity.py` y el filtro público `tests/test_public_gate.py`, que sigue negando todas las rutas del equipo, también las nuevas).
- `node --check` sobre los 20 archivos de `frontend/js`: sin errores. `node --test` de `frontend_operations`, `frontend_ia`, `frontend_chat` y `frontend_learning`: 34 de 34.
- Navegador sobre la vista previa sintética 8878 (reiniciada con este backend): el primer acceso de `nuevo.powersolar@example.com` muestra el QR obligatorio, rechaza un código incorrecto y entra con el correcto; el acceso siguiente pide solo el código, rechaza uno incorrecto y entra con el correcto, sin sesión antes del código. Como propietario: el panel lista los correos, rechaza uno sin `powersolar` con la regla activa, normaliza y añade otro, desactiva y reactiva la regla, quita un correo (su inicio de sesión pasa al error genérico) y no permite quitar al propietario (409).
- Sin verificar: el arranque real de `main.py` con la base comercial (no se migró ni se abrió), un escaneo con un teléfono real en esta iteración, la copia pública en 8880 (sigue con el proceso anterior y no se reinició) y el envío de correos (no existe). Sin commit ni publicación.

## SEC-003: código de invitación, clave TOTP protegida y control de administradores (25 de noviembre de 2026)

Pedido del titular: corregir los hallazgos de seguridad del acceso del equipo. Sustituye los pasos de primer acceso de «Acceso del equipo endurecido»: desde ahora la contraseña sola nunca permite registrar Google Authenticator.

### Qué cambió

- **Primer registro con código de invitación (H1).**
  - Una cuenta sin Google Authenticator que acierta la contraseña recibe `{"mfa_required": true, "enrollment_required": true, "invitation_required": true}` y ninguna sesión. `POST /api/team-identity/totp/enroll` exige `invitation_code`: un código de un solo uso emitido para esa misma cuenta. El código se consume antes de mostrar el QR, así que el QR sale una sola vez; si la configuración vence (10 minutos), hace falta un código nuevo.
  - Se reutiliza `team_access_grants` (propósito `enroll`): solo se guarda el hash SHA-256, vence a las `INVITE_HOURS = 72` horas (`reigel/identity.py`; la recuperación sigue en 60 minutos), emitir uno nuevo anula los anteriores sin usar y borra cualquier QR pendiente de un código anterior. Todo queda en la auditoría.
  - Formato pensado para entregarse en persona: 16 caracteres sin letras o cifras que se confundan, en grupos `XXXX-XXXX-XXXX-XXXX`; mayúsculas, espacios y guiones no importan al escribirlo.
  - Quién emite: un administrador solo para asesores; solo el propietario para administradores; nadie por HTTP para el propietario (tampoco él mismo). El código del propietario, de invitación o de recuperación, solo se obtiene en el servidor con `scripts/team_recovery.py --purpose enroll|recovery`, que muestra un aviso, pide escribir «SI» (o `--yes`) y queda auditado (`team.grant_issued_locally.*`). El servidor rechaza una invitación para una cuenta que ya tiene autenticador y una recuperación para una que no lo tiene.
  - `/app/acceso` sin sesión pide ahora correo, contraseña y código; el código solo ya no basta. Una contraseña incorrecta no consume el código.
  - Interfaz: en `/app` → «Equipo y ajustes», cada persona que el usuario puede gestionar tiene «Emitir código de invitación» (o «Código de recuperación» si ya registró el autenticador). El código se muestra una vez, con la fecha de vencimiento y la indicación de entregarlo en persona. El acceso de `/app` pide el código de invitación antes del QR.
- **La clave TOTP nunca se regenera en silencio (H2, H11).**
  - Sin `REIGEL_TOTP_KEY` ni `<base>.totp.key`, la clave nueva solo se crea si no existe ningún secreto TOTP. Si hay autenticadores registrados, toda operación de Google Authenticator responde 503 con un mensaje claro, no se crea ningún archivo y el servidor lo registra al arrancar. Un `REIGEL_TOTP_KEY` mal formado (no base64 o distinto de 32 bytes) da el mismo 503 controlado, nunca un 500.
  - `scripts/doctor.py --base RUTA` comprueba la clave antes de arrancar (solo lectura; no migra ni imprime la clave).
  - `scripts/backup.py` copia también la clave como `<copia>.totp.key` y avisa de guardarla aparte y en un lugar seguro; si la clave viene de `REIGEL_TOTP_KEY`, recuerda que no está en la copia. Pasos de restauración en `docs/OPERACION.md`.
- **Solo el propietario cambia administradores (H3).** Un administrador gestiona solo asesores: no puede cambiar nombre, contraseña, estado ni horario de otro administrador o del propietario. Un administrador solo ajusta el horario de su propia cuenta. Nadie cambia su propia contraseña por `PATCH /api/team/{id}`: se usa «Cambiar contraseña», que pide la actual. Correo y rol no se editan por esa ruta.
- **Límite por cuenta (H4):** 20 intentos de contraseña por hora y por cuenta, sumando todas las direcciones, además del límite por dirección. El error sigue siendo genérico y el coste de verificación es el mismo. El registro con código en `/app/acceso` tiene su propio límite por cuenta (10 por hora). Un tercero que conozca el correo puede agotar ese límite y retrasar el acceso de esa persona durante una hora; es el precio de frenar ataques distribuidos.
- **Bloqueo escalonado de códigos (H5):** cada ciclo de 5 códigos incorrectos bloquea 15 minutos, luego 1 hora y luego 24 horas; un código correcto o una recuperación lo reinicia. Auditoría `team.totp_locked` y `team.totp_lock_escalated.60m` / `.1440m`.
- **Auditoría (H12):** `auth.login_failed` guarda el identificador de la cuenta cuando el correo corresponde a una cuenta activa (nunca la contraseña). Se registran los códigos de invitación o recuperación no válidos (`team.invitation_invalid`, `team.grant_code_invalid`), los fallos al confirmar el primer código (`team.enrollment_confirm_failed`) y los rechazos CSRF (`security.csrf_rejected`).
  - Red del cliente: `identity_audit.client_net` guarda solo la red truncada (`/24` en IPv4, `/48` en IPv6), nunca la dirección completa. Basta para ver si los intentos vienen de una misma zona o proveedor, y no identifica a un dispositivo concreto. Detrás de un proxy o túnel se registra la red del proxy, porque `X-Forwarded-For` no se considera fiable.
- **Cambiar de autenticador cierra las demás sesiones (H13).** Registrar un teléfono nuevo desde la sesión conserva solo la sesión actual; una recuperación o un primer registro cierran todas. Una sesión anterior a Google Authenticator ya no vuelve a valer después del registro.
- Migración aditiva e idempotente `reigel_identity_invitation_v4`: columnas `identity_audit.client_net` (nula) y `team_totp.lock_count` (0 por omisión). No se ejecutó sobre la base comercial.
- Demostración sintética: propietario y asesor siguen preinscritos; `nuevo.powersolar@example.com` necesita contraseña y el código de invitación sintético que la demo imprime solo en su salida.

### Pasos del propietario antes del primer arranque real

1. Detener el servicio y hacer la copia: `.\.venv\Scripts\python.exe scripts\backup.py`. Guardar la copia y su archivo `.totp.key` por separado, en lugares seguros.
2. Comprobar la clave: `.\.venv\Scripts\python.exe scripts\doctor.py --sin-pruebas --base RUTA_DE_LA_BASE`. Debe decir OK. Si dice ERROR, restaurar la clave original antes de seguir; no arrancar para «probar».
3. Revisar la lista de correos autorizados (`REIGEL_TEAM_ALLOWED_EMAILS` o el panel del propietario) y la regla «Power Solar», como en la sección anterior.
4. Arrancar el servidor. Las cuentas que ya tienen Google Authenticator siguen entrando con contraseña y código; ninguna sesión antigua sin autenticador vuelve a valer.
5. Propietario, en la consola del servidor: `.\.venv\Scripts\python.exe scripts\team_recovery.py --db RUTA_DE_LA_BASE --email CORREO_DEL_PROPIETARIO --motivo "primer acceso" --purpose enroll`, confirmar con «SI» y anotar el código (vence en 72 horas).
6. Propietario en `/app`: correo y contraseña → código de invitación → escanear el QR → código de 6 dígitos.
7. Propietario en «Equipo y ajustes»: «Emitir código de invitación» para cada administrador y entregarlo en persona.
8. Cada administrador (o el propietario) emite el código de cada asesor y lo entrega en persona. Ningún código se envía por correo, chat ni capturas.
9. Teléfono perdido: un administrador emite la recuperación de un asesor; el propietario, la de un administrador; la del propietario se obtiene con `scripts/team_recovery.py --purpose recovery` en el servidor. La persona la usa en `/app/acceso` con su correo y contraseña.

### Verificación (local)

- `.\.venv\Scripts\python.exe -m pytest -q`: 847 passed (incluye `tests/test_team_invitation.py`, 17 casos nuevos: invitación válida, reutilizada, vencida, de otra cuenta y anulada por una nueva; reglas de emisión; script local con confirmación; `/app/acceso` con contraseña; H3; límite por cuenta; auditoría con red truncada; bloqueo escalonado; cierre de sesiones; clave ausente sin crear una nueva; clave mal formada; simulacro de copia y restauración en ruta nueva con archivo de clave y con `REIGEL_TOTP_KEY`; diagnóstico de `doctor.py`).
- `node --check` sobre `frontend/js/*.js`: sin errores. `node --test` de `frontend_operations`, `frontend_ia`, `frontend_chat` y `frontend_learning`: 34 de 34.
- Navegador sobre la demo sintética 8878 (reiniciada con este código): `nuevo.powersolar@example.com` con contraseña correcta recibe el paso de invitación y ningún QR; un código falso se rechaza; el código sintético impreso (escrito en minúsculas y con espacios) muestra el QR y el código de 6 dígitos abre la sesión; el mismo código reutilizado en `/app/acceso` se rechaza (401). Como propietario: botones «Emitir código de invitación» / «Código de recuperación» para todos menos para sí mismo; el código de un administrador nuevo se mostró una vez con vencimiento e instrucciones. Como ese administrador: ningún botón sobre el propietario, solo «Horario» en su cuenta; emitir para el propietario, para sí mismo o sin CSRF da 403; cambiar contraseña o nombre del propietario da 403; emitir para un asesor funciona. Un código de asesor vencido (fecha alterada en la base sintética temporal) se rechaza en `/app`.
- Sin verificar: el arranque real con la base comercial (no se abrió ni se migró), `doctor.py --base` contra la base real, un escaneo con un teléfono real en esta iteración, un administrador intentando emitir para otro administrador en el navegador (solo hay uno en la demo; cubierto por pruebas), las copias públicas 8877 y 8880 (no se reiniciaron) y el comportamiento detrás del túnel público (allí la red registrada sería la del proxy). Sin commit ni publicación.

## `/soluciones`, `/empresa` y `/proceso`: aplicación, escena de energía y capítulos de ingeniería, 25 de noviembre de 2026

Solo frontend (`system-showcase.css?v=9`, `system-showcase.js?v=6`, `energy-scene.css?v=8`, `energy-scene.js?v=8`); sin archivos nuevos, dependencias ni cambios de servidor.

- **Aplicación Tesla (`.sc-app`, `/soluciones`).** Titular «Toda tu energía. En la palma de tu mano.» y tres indicadores en pestañas (flechas, Inicio y Fin): preferencias, monitoreo y alertas. Las seis funciones anteriores quedaron como líneas de apoyo dentro de los paneles. Cada panel lleva un dibujo propio rotulado «Demostración simulada», sin cifras. La captura no se toca: la selección enciende un punto externo sobre el gris, encima del teléfono relacionado. Sin JavaScript los tres bloques se ven seguidos. La nota de funciones pasó a «Las funciones dependen del modelo de Powerwall, de su configuración y de la región.»; la disponibilidad en Puerto Rico de los avisos por mal tiempo no está verificada y por eso se dice «en algunas regiones».
- **Escena de energía (`#energia-en-casa`).** Titular «Una casa. Múltiples posibilidades energéticas.». El dibujo suma equipos del hogar tras las ventanas (con respaldo y sin respaldo), una unidad exterior, luz de calle, un interruptor que se abre con la nota «Separado de la red» en la interrupción con batería, y tres marcas de carga (baja, media, llena) que se recorren una vez y se detienen. De día con batería, la red recibe el excedente solo cuando la carga llega a llena. Leyenda: generación solar, consumo del hogar, almacenamiento del excedente, red e inversor. Sin vehículo eléctrico: `EXTENSIONS.vehicle` queda en `false` y documentado. La calculadora no se conectó: la escena solo emite el evento `energy-scene:change`, que hoy nadie escucha.
- **Capítulos de ingeniería.** «03 — Ingeniería · Perfil bajo» y «04 — Ejecución · Instalación eficiente» pasaron de `/empresa` a `/proceso` (banda «Montaje e instalación», tras «Tu techo, en la evaluación»), sin cambios de contenido salvo el enlace «Ver el proceso completo», que ahora apunta a `#proceso`. `/empresa` conserva la apertura, 01 y 02, y enlaza a `/proceso#ingenieria-montaje`; `/proceso` enlaza de vuelta a `/empresa#ingenieria`. En el capítulo 01, «documentado más abajo» pasó a «documentado en el capítulo 03, en la página Evaluación».

Verificado en la demo sintética (8877) a 1920, 1440, 1024, 768 y 390 px: sin desbordes ni errores de consola; seis estados de la escena con ratón y teclado; pestañas con ratón y flechas; movimiento ligado al desplazamiento en ambas páginas; enlaces entre páginas con clic real. Sin verificar: `prefers-reduced-motion` y la vista sin JavaScript en navegador (revisados en código y en el HTML servido), lector de pantalla, `forced-colors`, teléfono físico y Safari. Sin commit ni publicación.

## `/captacion` y `/proceso`: secuencia del apagón y línea de tiempo de la transición, 25 de noviembre de 2026

Solo frontend (`system-showcase.css?v=10`, `system-showcase.js?v=7`, `frontend/landing.html`, `frontend/pages/proceso.html`); sin archivos nuevos, dependencias, imágenes nuevas ni cambios de servidor.

- **Secuencia del apagón (`.sc-storm`, `/captacion`).** La banda existente «Cuando se va la luz.» pasa a titularse «Cuando la red falla, lo esencial sigue encendido.» (antetítulo «INDEPENDENCIA Y RESILIENCIA ENERGÉTICA»). Con JS y sin movimiento reducido, un escenario fijo recorre cinco pasos ligados al desplazamiento y reversibles: calle dibujada en SVG con suministro, falla de la red (faroles y tendido), casas sin respaldo a oscuras, una casa con almacenamiento que conserva parte de sus ventanas, y paso a la foto real con el título. El dibujo lleva «Representación ilustrativa.» y la foto «Imagen de referencia.»; la foto no se retocó ni lleva capas encima. Hay enlace «Saltar la secuencia» y un único enlace secundario a `/contacto#evaluacion`; no se añadió CTA principal (siguen siendo 3 en la página). Sin JS, con movimiento reducido, al imprimir o si el escenario no cabe en la ventana: foto, título y textos, sin dibujo.
- **Línea de tiempo (`.sc-jr`, `#transicion`, `/proceso`).** Entre el encabezado y «De tu necesidad a una propuesta.»: cinco etapas con numerales grandes, iconos de trazo, línea de progreso que se rellena con el desplazamiento y un detalle por etapa (botón con `aria-expanded`; en horizontal uno abierto a la vez, en vertical independientes). Horizontal desde 961 px (requiere `subgrid`; sin él queda vertical). Sin JS las cinco etapas muestran su detalle. CTA principal «Comienza tu transición energética» → `/contacto#evaluacion` (la página pasa de 0 a 1 CTA principal) y enlace «Solicita una orientación sin compromiso» → `/chat`, el chat de coordinación. Las etapas enlazan a `#proceso`, `#perfil-bajo`, `#instalacion`, `/preguntas` y `/soluciones#sc-app-title` en lugar de repetir su contenido.
- **Pendiente de confirmar por el titular** (redacción neutra publicada): quién gestiona permisos y trámites con LUMA (etapa 03); garantías de instalación, servicios posventa y canales de asistencia (etapa 05); que la etapa 02 contemple «necesidades futuras» como parte real del diseño. No se publican plazos, años de garantía, cantidades de instalaciones ni aprobación de financiación.

Verificado en la demo sintética (8877) a 1920, 1440, 1024, 768 y 390 px: sin desbordes ni errores de consola; estados idénticos al avanzar y al retroceder en ambas secciones; el sujeto de la foto queda en cuadro en todos los anchos; contraste del título y del antetítulo sobre la foto medido por píxel (mínimo 4,96:1 con texto de 43 a 60 px; antetítulo de 12 px, mínimo 5,35:1); etapas con ratón, teclado (Tab, Intro, Espacio) y toque a 390 px. Sin verificar: `prefers-reduced-motion` real del sistema (se comprobó el estado estático quitando la clase), lector de pantalla, Safari/iOS y Firefox, un teléfono físico, y el movimiento con cuadros reales en `/proceso` más allá de 1440 px (el panel quedó oculto y se comprobó la ruta de cálculo directo).

### Seguimiento privado de proyectos (propuesta futura)

No hay código para esto. Es una propuesta para decidir.

- **Qué mostraría al cliente:** estado de la solicitud, evaluación, documentación pendiente, diseño, permisos, programación, activación, garantías y asistencia.
- **Qué existe para construirlo:** cuentas de cliente en `reigel/identity.py` (tablas `customers`, `customer_identifiers`, `customer_sessions`, códigos de verificación), separadas del acceso del equipo; etapas comerciales del CRM en `reigel/core.py` (`STAGES`, de `nuevo` a `ganado`/`perdido`). Hoy no hay etapas posteriores a la venta ni un vínculo entre una cuenta de cliente y un prospecto del CRM: ambas cosas habría que crearlas con una migración aditiva.
- **Riesgos:** privacidad (dirección, documentos y estado de un trámite son datos personales); autorización por cliente en servidor, de modo que nadie vea el proyecto de otro, incluidas las reasignaciones; datos que el equipo debe mantener al día (un estado viejo es peor que no mostrar nada); no convertir un estado en una promesa de plazo o de aprobación.
- **Decisiones del titular:** cuáles son las etapas reales después de la venta y quién las actualiza; quién gestiona permisos y trámites; qué documentos se suben y dónde se guardan; cómo se verifica la identidad del cliente; qué se notifica y por qué canal; retención y eliminación de esos datos.
