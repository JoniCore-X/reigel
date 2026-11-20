# Hoja de ruta del rediseño · R.E.I.G.E.L.

Rama de trabajo: `rediseno-reigel`. Cada fase termina con pruebas, revisión en
la vista previa sintética (`.claude/launch.json`, puerto 8877) y un commit.
Nada de esto se publica ni migra la base comercial: para que los visitantes lo
vean hay que reiniciar el servidor activo, y eso lo decide el titular.

## Reglas que no cambian con el rediseño

- Contenido oficial de Power Solar solo con fuente y fecha
  (`frontend/assets/power-solar/SOURCES.md`). Se excluyen precios, pagos
  mensuales, promociones (la del 50 % del sitio tiene una nota legal de 2020),
  garantías y cifras de ahorro, aunque el sitio oficial las publique.
- No se usan fotos de clientes ni de representantes identificados por nombre.
- Componentes de Uiverse.io u otras galerías: solo con licencia permisiva
  (MIT/CC0), autor y origen anotados en `docs/UIVERSE_COMPONENTS.md` y
  `frontend/assets/licenses/`.
- La salida de IA sigue la política de cantidades y la frontera de salida de
  `/ia`; las acciones comerciales siguen en `/chat`.

## Fase 1 · `/ia` y contenido oficial — hecha (19 nov 2026)

- Renombrar, eliminar (con confirmación) y buscar conversaciones; solo el dueño.
- Bienvenida con las seis ilustraciones oficiales del sistema residencial como
  puntos de partida; preguntas sin cifras.
- `/contacto`: mapa oficial de centros de servicio con la lista equivalente en
  texto y enlace al buscador oficial.

## Fase 2 · `/chat` (coordinación)

- Mismo lenguaje visual que `/ia`: cabecera, burbujas, estados y compositor.
- Reserva por pasos (asesor → día → hora → datos → confirmación) con progreso
  visible y teclado completo; la confirmación sigue dependiendo del servidor.

## Fase 3 · Sitio corporativo

- `/soluciones`: «Cómo funciona un sistema con batería» con las ilustraciones
  oficiales y texto propio.
- `/empresa`: hechos publicados por Power Solar, atribuidos (empresa
  puertorriqueña fundada en 2018, parte de Power Group, líneas de solución,
  socios tecnológicos), sin cifras de clientes ni empleados.
- Nuevos componentes Uiverse documentados donde aporten (tarjetas, botones,
  conmutadores), revisando la cascada antes de añadir reglas.

## Fase 4 · `/app` (equipo)

- Paleta de comandos (Ctrl+K) para buscar prospectos, tareas y vistas.
- Modo oscuro con preferencia del sistema.
- Agenda en vista semanal.
- Pipeline con arrastrar y soltar, con alternativa de teclado.
- Avisos con contador que se actualiza solo.

## Fase 5 · Robustez de `/ia` en servidor

- Una sola generación por conversación (exclusión en servidor).
- Reintentos idempotentes con identificador de solicitud.

## Fase 6 · Operación (requiere decisiones del titular)

- Topología de Ollama para Docker/producción.
- Política del modo IA en Telegram (hoy envía sin revisión si se activa).
- Migración real: detener servicio, `scripts/backup.py`, guardar SHA256,
  arrancar el código nuevo.
