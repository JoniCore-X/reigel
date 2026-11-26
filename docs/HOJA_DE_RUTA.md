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

## Fase 2 · `/chat` (coordinación) — hecha (19 nov 2026)

- Mismo lenguaje visual que `/ia`: cabecera, burbujas, estados y compositor.
- Reserva por pasos (asesor → día → hora → datos → confirmación) con progreso
  visible y teclado completo; la confirmación sigue dependiendo del servidor.

## Fase 3 · Sitio corporativo — contenido hecho (21 nov 2026); faltan componentes Uiverse

- `/soluciones`: «Cómo funciona un sistema con batería» con las ilustraciones
  oficiales y texto propio.
- `/empresa`: hechos publicados por Power Solar, atribuidos (empresa
  puertorriqueña fundada en 2018, parte de Power Group, líneas de solución,
  socios tecnológicos), sin cifras de clientes ni empleados.
- Nuevos componentes Uiverse documentados donde aporten (tarjetas, botones,
  conmutadores), revisando la cascada antes de añadir reglas.

## Acceso y suscripción (pedido el 21 nov 2026)

- Fase A — hecha (21 nov 2026): rol de propietario, baja en un paso con
  transferencia de trabajo y planes fuera del sitio público (solo en `/app`).
- Fase B: suscripción interna (plan asignado, licencias según asesores
  activos, facturas y estado de pago; suspensión por impago si el titular lo
  decide), sin cobrar dinero real.
- Fase C: pasarela de pago en modo de prueba, cuando el titular cree la cuenta.
- Fase D: IA comercial con aprobación humana (borradores de publicaciones,
  seguimiento, prioridad de prospectos, guiones para citas). Imágenes y video
  requieren otros modelos o un servicio de pago: decisión del titular.

## Fase 4 · `/app` (equipo)

- Paleta de comandos (Ctrl+K) para buscar prospectos, tareas y vistas.
- Modo oscuro con preferencia del sistema — hecho (21 nov 2026) en `/app` e `/ia`, con el interruptor de Uiverse de Galahhad.
- Agenda en vista semanal.
- Pipeline con arrastrar y soltar, con alternativa de teclado.
- Avisos con contador que se actualiza solo.

## Fase 5 · Robustez de `/ia` en servidor

- Una sola generación por conversación (exclusión en servidor).
- Reintentos idempotentes con identificador de solicitud.

## Fase 6 · Operación (requiere decisiones del titular)

- Despliegue con Docker — preparado (25 nov 2026), sin desplegar: `docs/DESPLIEGUE.md`.
  El titular eligió servidor con Docker. Falta que el titular contrate servidor y
  dominio, autorice las descargas y haga el primer arranque, que será la primera
  prueba real de la imagen (nunca se construyó ni se arrancó).
- Topología de Ollama para Docker/producción — resuelta sin tocar el código:
  contenedor acompañante opcional (perfil `ia`) que comparte la red de la
  aplicación y escucha solo en `127.0.0.1`. Pendiente de decidir: hacer
  configurable la dirección de Ollama para aislarlo en su propia red.
- Política del modo IA en Telegram (hoy envía sin revisión si se activa).
- Migración real: detener servicio, `scripts/backup.py`, guardar SHA256,
  arrancar el código nuevo. Hacia el servidor: `deploy/restore.sh` (ruta B de
  `docs/DESPLIEGUE.md`). Sin ensayar con la base comercial.
- Antes de publicar: lista de `docs/DESPLIEGUE.md` (permisos de imágenes, placa
  de 410 W, formulario de `/contacto`, IA sin revisión humana, privacidad).
