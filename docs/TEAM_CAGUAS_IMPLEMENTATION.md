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
contraseña solo para el entorno sintético:

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
