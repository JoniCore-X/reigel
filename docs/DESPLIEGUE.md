# Despliegue en un servidor con Docker · R.E.I.G.E.L.

Guía para poner R.E.I.G.E.L. en internet en un servidor propio o alquilado (VPS)
con un dominio. Está escrita para seguirla paso a paso, copiando los comandos.

**Estado honesto (25 de noviembre de 2026):** los archivos están preparados y
revisados, pero **nadie ha desplegado todavía** en un servidor. El 26 de
noviembre la pila se construyó y arrancó una vez en la computadora de desarrollo,
con datos de demostración y el dominio `localhost` (ver el Registro). Lo que sí
se comprobó y lo que no está
en [Qué se probó y qué no](#qué-se-probó-y-qué-no). El primer arranque real es
también la primera prueba real: hazlo con calma y sigue la lista de verificación.

En todos los comandos, `reigel.ejemplo.com` y `tu-correo@ejemplo.com` son
ejemplos: sustitúyelos por los tuyos **en el servidor**, nunca en el repositorio.

## Cómo queda montado

```
Internet ──80/443──> Caddy (HTTPS automático) ──red interna──> app (R.E.I.G.E.L.)
                                                                 │  └─ volumen solar_data: base SQLite + clave de Google Authenticator
                                                                 └─ (opcional) Ollama, solo en 127.0.0.1 del mismo contenedor de red
```

- **Caddy** es lo único visible desde internet. Pide y renueva solo el
  certificado HTTPS y redirige HTTP a HTTPS.
- **La aplicación** no publica ningún puerto. Corre con un usuario sin
  privilegios, con el sistema de archivos en solo lectura, sin capacidades de
  Linux y con un único proceso (los límites de solicitudes viven en memoria).
  Solo puede escribir en `/app/data` (el volumen) y en un `/tmp` en memoria.
- **Dirección real del visitante:** la aplicación acepta las cabeceras de
  reenvío únicamente de la dirección fija de Caddy en la red interna
  (`172.30.87.2`). Antes aceptaba cualquiera (`--forwarded-allow-ips "*"` en la
  versión anterior del Dockerfile), lo que permitía falsificar la dirección y
  esquivar los límites de intentos. Eso está corregido y cubierto por pruebas.
- **Los datos** (base SQLite y archivo de clave `reigel.db.totp.key`) viven en
  el volumen `solar_data`. Borrar ese volumen borra el negocio: nunca uses
  `docker compose down -v` ni `docker volume rm`.
- **Los secretos** van en un archivo `.env` que solo existe en el servidor.

## Lo que solo puedes hacer tú

El asistente no compra, no crea cuentas, no publica y no maneja credenciales.
Estas tareas son tuyas:

1. Elegir y pagar el servidor (o decidir usar tu propia máquina).
2. Elegir y pagar el dominio, y crear el registro DNS.
3. Instalar Docker en el servidor y autorizar las descargas (lista más abajo).
4. Escribir el archivo `.env` en el servidor.
5. Crear tu cuenta de propietario, leer tu contraseña inicial y registrar tu
   Google Authenticator con tu teléfono.
6. Copiar la base comercial desde tu computadora al servidor, si vas a migrarla.
7. Decidir si se activa la IA local y autorizar la descarga de Ollama y del modelo.
8. Decidir dónde se guardan las copias de seguridad fuera del servidor.
9. Resolver la lista [Antes de publicar](#antes-de-publicar).

## Requisitos

| Qué | Sin IA | Con IA local (Ollama) |
|---|---|---|
| Procesador | 1 vCPU | 4 vCPU o más |
| Memoria | 1 GB (2 GB cómodo) | 8 GB o más |
| Disco | 10 GB | 25 GB o más |
| Sistema | Linux de 64 bits (Ubuntu o Debian recientes) | igual |

- Un dominio o subdominio (por ejemplo `reigel.ejemplo.com`) con un registro
  DNS **A** que apunte a la dirección IPv4 pública del servidor. No crees un
  registro AAAA (IPv6) salvo que configures IPv6 en Docker: sin eso, las visitas
  por IPv6 llegarían a la aplicación con una dirección interna compartida.
- Si el dominio pasa por un servicio intermedio (CDN o «proxy» del proveedor de
  DNS), desactívalo para este registro («solo DNS»). Con un intermediario, todas
  las visitas llegarían con la dirección de ese servicio.
- Puertos **80 y 443** abiertos hacia el servidor (y 443/UDP si quieres HTTP/3).
  El 22 solo para tu acceso por SSH. Ningún otro.
- Docker Engine con el complemento Compose
  (instrucciones oficiales: https://docs.docker.com/engine/install/).

### Descargas que debes autorizar

Nada de esto se ha descargado. Los tamaños son aproximados y cambian con cada
versión; compruébalos al descargar.

| Descarga | Cuándo | Tamaño aproximado |
|---|---|---|
| Docker Engine y Compose | al preparar el servidor | 100–150 MB (unos 400 MB instalado) |
| Imagen `python:3.14-slim` | `docker compose build` | 45–50 MB (unos 130 MB en disco) |
| Paquetes de `requirements.txt` | `docker compose build` | 30–50 MB |
| Imagen `caddy:2-alpine` | `docker compose up -d` | 15–20 MB (unos 50 MB en disco) |
| Imagen `ollama/ollama` (solo con IA) | al activar el perfil `ia` | 1–2 GB (hasta unos 4 GB en disco) |
| Modelo `qwen2.5:3b` o `llama3.2:3b` (solo con IA) | `ollama pull` | unos 2 GB cada uno |

## Paso 1 · Preparar el servidor

Entra por SSH y ejecuta. El cortafuegos del ejemplo es `ufw` (Ubuntu/Debian).

```bash
# Cortafuegos: solo SSH, HTTP y HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw enable

# Comprobar Docker (instálalo antes con la guía oficial)
docker --version
docker compose version
```

Aviso: los puertos que Docker publica (80 y 443) no pasan por `ufw`; por eso en
este montaje solo Caddy publica puertos. No añadas `ports:` a `app` ni a `ollama`.

Descarga el código. El repositorio es público, así que no hace falta ninguna
credencial para leerlo (sustituye la dirección por la de tu repositorio):

```bash
sudo mkdir -p /opt/reigel && sudo chown "$USER" /opt/reigel
git clone https://github.com/USUARIO/REPOSITORIO.git /opt/reigel
cd /opt/reigel
```

`git clone` deja el repositorio en `main`, que es la rama que se publica. No hace
falta cambiar de rama. (Hasta el 26 de noviembre de 2026 esta guía mandaba hacer
`git checkout rediseno-reigel`; esa rama se fusionó en `main` y se borró, así que
seguir aquella instrucción fallaba.)

## Paso 2 · Escribir `.env` (lo haces tú)

```bash
cd /opt/reigel
cp .env.example .env
chmod 600 .env
nano .env
```

Completa como mínimo:

```
DOMAIN=reigel.ejemplo.com
CADDY_EMAIL=tu-correo@ejemplo.com
```

- `DOMAIN`: el dominio, sin `https://` ni barras. `compose.yaml` deduce de ahí
  `SITE_URL=https://DOMAIN` y fija `REIGEL_ENV=production` y
  `REIGEL_DB_PATH=/app/data/reigel.db`; no hace falta escribirlas.
- `CADDY_EMAIL`: correo para los avisos del certificado.
- `REIGEL_ALLOWED_HOSTS`: déjalo vacío. El dominio de `SITE_URL` ya se acepta.
- `REIGEL_TOTP_KEY`: **déjalo vacío** (recomendado). La clave de Google
  Authenticator se crea sola como archivo en el volumen
  (`/app/data/reigel.db.totp.key`) y las copias la guardan aparte. Si prefieres
  definirla tú, tendrás que custodiarla: sin ella nadie entra con su código.
- `REIGEL_TEAM_ALLOWED_EMAILS`: correos del equipo autorizados, separados por
  comas. Solo añade al arrancar, nunca quita. Puedes dejarlo vacío: tu correo de
  propietario queda autorizado solo y el resto lo gestionas en `/app`.
- IA (`REIGEL_CHAT_AI`, `COMPOSE_PROFILES`): vacías por ahora. Ver el paso 6.

Reglas: `.env` no se sube al repositorio (el repositorio es público y `.gitignore`
lo excluye), no se envía por chat ni correo y no entra en la imagen de Docker.
`docker compose config` **imprime en pantalla los valores de `.env`**: usa
siempre `docker compose config --quiet` y no compartas esa salida.

## Paso 3 · Construir y decidir de dónde salen los datos

```bash
cd /opt/reigel
docker compose config --quiet && echo "Configuración válida"
docker compose build        # descarga python:3.14-slim y los paquetes
```

Ahora elige **una** de las dos rutas.

### Ruta A · Empezar con una base nueva

```bash
docker compose up -d        # descarga caddy:2-alpine y arranca
docker compose ps           # app debe quedar «healthy»; caddy, «running»
docker compose logs --tail 50 caddy   # debe obtener el certificado
```

Crea tu cuenta de propietario (la primera cuenta es el propietario):

```bash
docker compose exec app python scripts/bootstrap.py --email tu-correo@ejemplo.com --name "Tu Nombre"
```

El comando no muestra la contraseña: la guarda en un archivo dentro del volumen.
Léela **tú**, en privado, y borra el archivo:

```bash
docker compose exec app cat /app/data/local-access.txt
docker compose exec app rm /app/data/local-access.txt
docker compose restart app
```

(El archivo menciona `http://127.0.0.1:8765/app`; en el servidor la dirección es
`https://reigel.ejemplo.com/app`.)

### Ruta B · Traer la base comercial desde tu computadora Windows

Hazlo sin prisa: es la base del negocio.

1. **En Windows, detén el servidor** (cierra `start.ps1` o ejecuta
   `.\scripts\uninstall_autostart.ps1`) y saca una copia verificada:

   ```powershell
   .\.venv\Scripts\python.exe scripts\backup.py
   ```

   Anota el `SHA256` que imprime. La copia queda en
   `%LOCALAPPDATA%\PowerSolar\backups\` como `powersolar-FECHA.db`, junto con
   `powersolar-FECHA.db.totp.key` (la clave de Google Authenticator). Si en tu
   `.env` de Windows usabas `REIGEL_TOTP_KEY`, no habrá archivo de clave: copia
   tú mismo ese valor al `.env` del servidor.

2. **Lleva los dos archivos al servidor tú mismo**, por un canal cifrado (`scp`
   desde PowerShell). No uses OneDrive, correo ni chat.

   ```powershell
   scp "$env:LOCALAPPDATA\PowerSolar\backups\powersolar-FECHA.db" usuario@reigel.ejemplo.com:/home/usuario/
   scp "$env:LOCALAPPDATA\PowerSolar\backups\powersolar-FECHA.db.totp.key" usuario@reigel.ejemplo.com:/home/usuario/
   ```

3. **En el servidor**, comprueba que llegó idéntica y restaura:

   ```bash
   sha256sum ~/powersolar-FECHA.db          # debe coincidir con el SHA256 anotado
   cd /opt/reigel
   bash deploy/restore.sh ~/powersolar-FECHA.db ~/powersolar-FECHA.db.totp.key
   ```

   El script verifica la integridad de la copia y que la clave **abre de verdad**
   los autenticadores registrados. Si la clave falta o no corresponde, no
   restaura nada. Después arranca el servicio; las migraciones aditivas se
   aplican solas en ese primer arranque y la dirección pública guardada en la
   base se actualiza con la de `SITE_URL`.

4. Entra en `https://reigel.ejemplo.com/app` con tu contraseña y tu código de
   Google Authenticator de siempre. Confirma que el propietario eres tú.

5. Cuando todo funcione: haz la primera copia en el servidor (paso 7), borra los
   dos archivos de tu carpeta personal del servidor
   (`rm ~/powersolar-FECHA.db ~/powersolar-FECHA.db.totp.key`) y **deja de usar
   la base de Windows**. Dos bases activas a la vez se separan y no se pueden
   volver a juntar.

Esta migración no se ha ensayado con la base comercial (no se abrió ni se
copió). El procedimiento de restauración sí está probado con bases sintéticas.

## Paso 4 · Tu Google Authenticator (solo ruta A o cuenta nueva)

El acceso del equipo exige contraseña y código del autenticador. El primer
registro necesita un código de invitación, y el tuyo solo se puede emitir desde
la consola del servidor:

```bash
docker compose exec app python scripts/team_recovery.py --db /app/data/reigel.db \
  --email tu-correo@ejemplo.com --motivo "Primer registro del titular" --purpose enroll
```

Escribe `SI` cuando lo pida. El código es de un solo uso y vence a las 72 horas.
Luego, en tu navegador:

1. Abre `https://reigel.ejemplo.com/app`, escribe correo y contraseña.
2. Escribe el código de invitación.
3. Escanea el código QR con Google Authenticator en tu teléfono.
4. Escribe el código de seis cifras que muestra la aplicación.
5. Ya dentro, cambia la contraseña inicial.

Si pierdes el teléfono: mismo comando con `--purpose recovery` (vence a los 60
minutos). Para el resto del equipo, añade sus correos a la lista de acceso en
`/app` (o en `REIGEL_TEAM_ALLOWED_EMAILS` y reinicia) y emite sus invitaciones
desde `/app`. Entrega los códigos en persona.

## Paso 5 · Verificación

```bash
cd /opt/reigel
docker compose ps
docker compose exec app python scripts/deploy_check.py
curl -sS https://reigel.ejemplo.com/health
curl -sSI https://reigel.ejemplo.com/ | grep -i -E "strict-transport|content-security|x-frame"
curl -sS -m 5 http://reigel.ejemplo.com:8765/health || echo "Correcto: el puerto de la aplicación no es público"
curl -sS -m 5 http://reigel.ejemplo.com:11434/ || echo "Correcto: Ollama no es público"
```

Lista de comprobación:

- [ ] `deploy_check.py` termina en `RESULTADO: APROBADO` (modo producción,
      dirección HTTPS, proxy de confianza, usuario sin privilegios, base íntegra,
      administrador, clave de Google Authenticator, dirección de los visitantes).
- [ ] `/health` responde `{"status":"ok","database":true}` por HTTPS.
- [ ] `http://reigel.ejemplo.com` redirige a `https://`.
- [ ] Entras en `/app` con contraseña y código, y sales.
- [ ] Reserva de prueba en `/chat`: eliges horario, das un contacto de prueba,
      confirmas, la ves en la Agenda de `/app` y la cancelas.
- [ ] Después de entrar en `/app` desde tu navegador, repite `deploy_check.py`:
      «Dirección de los visitantes» debe salir `[OK]`. Si sale `[ERROR]`, la
      aplicación no está viendo la dirección real de los visitantes (los límites
      de intentos se compartirían entre todos): detente y revisa el DNS (sin
      intermediarios) e IPv6.
- [ ] Reinicia el servidor (`sudo reboot`) y comprueba que todo vuelve solo.
- [ ] **Enciende el motor comercial autónomo.** Llega apagado a propósito. En
      `/app` → R.E.I.G.E.L., pulsa primero **«Ver el plan sin aplicarlo»** para
      leer qué decidiría con tus registros reales, y solo entonces **«Encender el
      motor»**. A partir de ahí revisa la cartera por su cuenta y abre tareas y
      avisos internos; no envía mensajes, no marca llamadas y no cambia la etapa
      de ningún registro. El interruptor vive en la base de datos, así que
      sobrevive a los reinicios, y se apaga con el mismo botón.

`scripts/doctor.py` es el diagnóstico del código en la computadora de
desarrollo: necesita Git, Node.js y las pruebas, que no viajan en la imagen.
Dentro del contenedor marcaría errores de «Estructura» y «Dependencias» que no
son fallos del servidor. En el servidor se usa `scripts/deploy_check.py`.

## Paso 6 · IA local con Ollama (opcional, apagada por defecto)

Sin IA, el sitio, `/chat` (con sus reglas propias y reservas) y `/app` funcionan.
`/` e `/ia` necesitan la IA para conversar.

**Antes de activarla, ten presente:**

- Las respuestas de la IA en `/`, `/ia` y `/chat` **se publican al visitante sin
  revisión humana**. Solo pasan validadores de patrones (sin cifras, precios,
  promesas ni contactos), que no entienden el significado de la respuesta.
- En un servidor sin tarjeta gráfica la IA es **lenta**: un modelo de 3 mil
  millones de parámetros en 2–4 vCPU compartidas produce pocas palabras por
  segundo y una respuesta puede tardar de medio minuto a más de un minuto. Con
  menos de 4 vCPU y 8 GB no es razonable. Esta velocidad **no se ha medido** en
  un servidor; mídela antes de anunciarla.
- Cada modelo ocupa unos 2 GB de disco y entre 3 y 5 GB de memoria mientras está
  cargado. El contenedor está limitado a 5 GB y 2 CPU (`OLLAMA_MEMORY`,
  `OLLAMA_CPUS` en `.env`). `OLLAMA_CPUS` no puede superar las CPU del servidor.
- Descargar la imagen de Ollama y el modelo son descargas grandes que autorizas tú.

Cómo funciona: la dirección de Ollama está fija en el código
(`http://127.0.0.1:11434`). Por eso Ollama corre como contenedor acompañante que
**comparte la red de la aplicación** (`network_mode: "service:app"`) y escucha
solo en `127.0.0.1`: la aplicación lo alcanza, pero ni Caddy ni internet pueden.

Activar:

```bash
cd /opt/reigel
nano .env                  # COMPOSE_PROFILES=ia   y   REIGEL_CHAT_AI=ollama
docker compose up -d       # descarga ollama/ollama y recrea app con la nueva configuración
docker compose exec ollama ollama pull qwen2.5:3b     # unos 2 GB
docker compose exec app python scripts/deploy_check.py   # «IA local: Ollama responde y tiene qwen2.5:3b»
```

Si usas otro modelo (por ejemplo `llama3.2:3b`), descárgalo igual y escribe su
nombre en `REIGEL_LOCAL_MODEL` o `REIGEL_CHAT_MODEL`. Los alias «cloud» se rechazan.

Si tras una actualización la IA aparece como no disponible, recrea el
acompañante (pierde la red cuando se recrea `app`):

```bash
docker compose up -d --force-recreate ollama
```

Apagar la IA:

```bash
docker compose --profile ia rm -sf ollama
nano .env                  # vaciar COMPOSE_PROFILES y REIGEL_CHAT_AI
docker compose up -d
```

## Paso 7 · Copias de seguridad

En un servidor no interviene OneDrive: las copias se quedan donde tú las
pongas, y sacarlas del servidor es tarea tuya.

```bash
cd /opt/reigel
sudo mkdir -p /var/backups/reigel && sudo chown "$USER" /var/backups/reigel
bash deploy/backup.sh
```

Qué hace `deploy/backup.sh`:

1. Ejecuta `scripts/backup.py` dentro del contenedor, con el servicio en marcha:
   copia consistente con la API de SQLite (incluye lo pendiente en el WAL) y
   verificación de integridad. Nunca copies a mano los archivos del volumen con
   el servicio encendido.
2. Saca la copia del volumen y comprueba su SHA256.
3. Guarda la **base** en `/var/backups/reigel/base/` y la **clave** de Google
   Authenticator en `/var/backups/reigel/clave/`, con el mismo nombre. Quien
   tenga las dos puede leer los secretos de los autenticadores: llévalas a
   lugares distintos (por ejemplo, la base a un disco externo y la clave a tu
   gestor de contraseñas). La clave no cambia; basta con tenerla bien guardada
   una vez y verificarla de vez en cuando.
4. Borra las copias de más de 30 días (`REIGEL_BACKUP_KEEP_DAYS`), solo después
   de haber guardado una nueva y verificada.

Programarla cada noche (03:15, hora del servidor):

```bash
crontab -e
# añadir esta línea:
15 3 * * * cd /opt/reigel && bash deploy/backup.sh >> /var/backups/reigel/backup.log 2>&1
```

Las copias contienen datos de clientes. Una copia que se queda en el mismo
servidor no protege si el servidor se pierde: decide tú a dónde se llevan y
quién puede leerlas. El script no sube nada a ningún servicio.

### Probar una copia sin tocar nada

Hazlo al menos una vez al mes. Verifica la integridad y que la clave abre los
autenticadores, sin cambiar la base activa:

```bash
cd /opt/reigel
COPIA=/var/backups/reigel/base/powersolar-FECHA.db
CLAVE=/var/backups/reigel/clave/powersolar-FECHA.db.totp.key
docker compose exec -T app sh -c 'umask 077; mkdir -p /app/data/prueba; cat > /app/data/prueba/copia.db' < "$COPIA"
docker compose exec -T app sh -c 'umask 077; cat > /app/data/prueba/copia.db.totp.key' < "$CLAVE"
docker compose exec app python scripts/restore.py --from /app/data/prueba/copia.db --db /app/data/reigel.db --check
docker compose exec app rm -rf /app/data/prueba
```

### Restaurar

```bash
cd /opt/reigel
bash deploy/restore.sh /var/backups/reigel/base/powersolar-FECHA.db /var/backups/reigel/clave/powersolar-FECHA.db.totp.key
```

El script pide escribir `SI`, detiene el servicio, verifica la copia y la clave,
mueve lo que había a una carpeta `antes-de-restaurar-…` dentro del volumen (no
borra nada), coloca la base y la clave y vuelve a arrancar. Todo lo ocurrido
después de la copia se pierde.

**Regla de la clave (igual que en el servidor):** si la copia tiene cuentas con
Google Authenticator y la clave falta o no es la suya, **no se restaura nada**.
El servidor tampoco inventa una clave nueva: respondería 503 en cada acceso con
autenticador. Si la clave se perdió para siempre, la única salida es restaurar
con `scripts/restore.py --sin-clave` y emitir un código de recuperación para
cada persona con `scripts/team_recovery.py --purpose recovery`.

## Paso 8 · Actualizar y volver atrás

Actualizar:

```bash
cd /opt/reigel
bash deploy/backup.sh                               # siempre antes
git rev-parse --short HEAD                          # anota la versión actual
docker image tag reigel-app:local reigel-app:anterior
git pull --ff-only
docker compose build
docker compose up -d
docker compose exec app python scripts/deploy_check.py
```

Volver atrás (solo el código), si algo falla:

```bash
cd /opt/reigel
git checkout VERSION_ANOTADA
docker image tag reigel-app:anterior reigel-app:local
docker compose up -d --no-build
```

Las migraciones de la base son aditivas (añaden tablas y columnas, no quitan),
así que normalmente el código anterior sigue funcionando con la base ya migrada.
Eso no está probado versión por versión. Si el código anterior no arranca con la
base nueva, restaura la copia hecha antes de actualizar con `deploy/restore.sh`
(perdiendo lo ocurrido desde esa copia).

Otros comandos útiles:

```bash
docker compose logs --tail 100 app     # registro de la aplicación
docker compose restart app             # reiniciar tras cambiar .env usa: docker compose up -d
docker compose stop                    # detener sin borrar nada
```

Nunca: `docker compose down -v`, `docker volume rm reigel_solar_data` ni
`docker system prune --volumes`. Borran la base y la clave.

## Nota para Windows o tu propia máquina

Se puede, pero es peor opción que un servidor Linux:

- Con **Docker Desktop** (Windows o Mac) las visitas llegan a los contenedores
  con una dirección interna común. La aplicación vería a todos los visitantes
  como uno solo: los límites de intentos se compartirían (un abuso bloquearía a
  todos) y la auditoría no distinguiría redes. En Linux con Docker Engine esto no ocurre.
- Necesitas abrir los puertos 80 y 443 en tu router hacia la máquina, una
  dirección pública (muchos proveedores residenciales la cambian o bloquean esos
  puertos) y la máquina encendida siempre, con UPS si hay apagones.
- Los volúmenes de Docker Desktop viven dentro de su máquina virtual, no en
  OneDrive. No muevas datos del servicio a una carpeta sincronizada.
- `deploy/backup.sh` y `deploy/restore.sh` son de Bash: en Windows se ejecutan
  desde WSL o Git Bash, y no se han probado allí.
- La opción «tu PC como servidor» de [OPERACION_24_7.md](OPERACION_24_7.md) es
  otra cosa: no usa Docker y no publica nada en internet.

## Antes de publicar

El despliegue técnico no resuelve nada de esto. Cada punto es una decisión tuya:

- [ ] **Imágenes sin permiso confirmado.** Varias imágenes de placas, baterías,
      casas y de la aplicación Tesla son material de fabricante o de origen sin
      verificar; su uso comercial no está confirmado. El detalle, archivo por
      archivo, está en `frontend/assets/power-solar/SOURCES.md`. Confirma el
      permiso o retíralas antes de publicar.
- [x] **Potencia de la placa confirmada.** El titular confirmó el 25 de
      noviembre de 2026 que la placa es de 420 W; el sitio publica 420 W.
- [ ] **Formulario real en `/contacto`.** La página incrusta un formulario real
      de Google Forms: lo que escriba un visitante llega a esa cuenta de Google,
      fuera de R.E.I.G.E.L. Confirma que es el formulario correcto, quién lo lee
      y qué se hace con esos datos.
- [ ] **La IA responde sin revisión humana** en `/`, `/ia` y el respaldo de
      `/chat`, solo con validadores de patrones. Decide si se publica con IA o sin ella.
- [ ] **Canales de Meta bloqueados** (WhatsApp, Messenger, Instagram): no envían.
      Telegram es opcional y no está conectado; si se activa su modo IA, envía
      sin revisión.
- [ ] **No hay correo ni SMS.** El sistema no envía confirmaciones,
      recordatorios ni recuperación de contraseña por correo o SMS. Las citas se
      confirman en pantalla (referencia y archivo de calendario) y los códigos de
      acceso se entregan en persona.
- [ ] **Privacidad y retención.** La base guarda datos de contacto de personas
      reales. El sistema registra solicitudes de privacidad para revisión humana
      pero **no borra ni exporta registros por sí solo**; una baja comercial y
      una solicitud de eliminación son cosas distintas. La cola de aprendizaje
      se purga a los 90 días y las conversaciones de visitantes de `/ia` duran 7
      días; lo demás se conserva hasta que alguien decida otra cosa. La
      auditoría guarda solo la red truncada del visitante. Las copias de
      seguridad también contienen esos datos y duran lo que fije la retención.
      Decide plazos, responsable y contacto de privacidad, y dónde está
      físicamente el servidor.
- [ ] **El repositorio es público.** Todo el código, los textos y las imágenes
      son visibles para cualquiera. Nunca subas `.env`, bases, copias ni claves.
      Las contraseñas y los datos de clientes solo existen en el servidor.
- [ ] **Aprobación corporativa.** No consta en la documentación del proyecto
      que Power Solar haya aprobado el uso de su marca y sus materiales en un
      sitio público. Confírmalo antes de publicar.
- [ ] **Versiones sin fijar.** `requirements.txt` usa rangos y las imágenes
      (`python:3.14-slim`, `caddy:2-alpine`, `ollama/ollama:latest`) son
      etiquetas que cambian. Dos construcciones en fechas distintas pueden no
      ser idénticas. Fijarlas por versión exacta es una mejora pendiente.

## Qué se probó y qué no

Probado en la computadora de desarrollo, sin descargas:

- `docker compose config` valida `compose.yaml` (sintaxis, redes, volúmenes,
  variables obligatorias) con un `.env` de ejemplo.
- `tests/test_deployment_files.py` comprueba el contrato: la aplicación no
  publica puertos, la confianza en cabeceras de reenvío se limita a la dirección
  de Caddy (y con esa configuración el componente de Uvicorn resuelve la
  dirección real e ignora las falsificadas), usuario sin privilegios, volumen de
  datos, exclusiones de `.dockerignore` y `.gitignore`, `.env.example` sin
  valores, y Caddyfile con marcadores y sin cabeceras duplicadas.
- `scripts/restore.py` y `scripts/deploy_check.py`, con bases sintéticas:
  restaurar base y clave, conservar lo reemplazado, y negarse si la clave falta
  o no corresponde.
- Sintaxis de `deploy/backup.sh` y `deploy/restore.sh` (`bash -n`).

Probado el 26 de noviembre de 2026 con Docker Desktop en Windows, base nueva,
cuenta ficticia y `DOMAIN=localhost` (certificado interno de Caddy):

- La imagen se construye; `app` queda «healthy» y Caddy arranca con
  `cap_drop: ALL` más `NET_BIND_SERVICE` y solo lectura.
- HTTP redirige a HTTPS (308); `/`, `/captacion`, `/proceso`, `/chat`, `/ia`,
  `/app`, `/app/acceso` y `/health` responden 200; las rutas privadas, 401 sin
  sesión. El puerto 8765 no es alcanzable desde fuera del contenedor.
- Dentro del contenedor: uid 10001, sin capacidades, código en solo lectura,
  `/app/data` con permisos 0700 y la clave con 0600.
- Ruta A completa: `bootstrap.py`, invitación con `team_recovery.py`,
  contraseña, registro de Google Authenticator y acceso. Tras
  `docker compose restart app`, la sesión, la contraseña y la clave siguen
  válidas (un código nuevo del mismo autenticador entra).
- `deploy/backup.sh` (SHA256 verificado, base y clave en carpetas distintas) y
  `deploy/restore.sh` con esa misma copia; el servicio vuelve a «healthy».
- Apagado ordenado en 2 segundos, sin errores en los registros de la aplicación.
  Consumo en reposo: unos 50 MB la aplicación y 12 MB Caddy.
- `deploy_check.py` marca ERROR en «Dirección de los visitantes» en Docker
  Desktop, como advierte la nota para Windows; en Linux debe quedar en OK.

Vuelto a comprobar el 26 de noviembre de 2026 por la noche, con el código de
`main` ya con el motor autónomo, la extracción de creencias y la página de
certificaciones, antes de preparar el primer despliegue real:

- La imagen se construye desde cero: 253 MB.
- Arranca «healthy» con las mismas restricciones que aplica `compose.yaml`
  —solo lectura, `/tmp` en memoria, uid 10001, todas las capacidades retiradas,
  sin privilegios nuevos— y un volumen de datos nuevo.
- Responden 200: `/health`, `/captacion`, `/proceso`,
  `/soluciones/certificaciones`, `/chat`, `/ia`, `/app`, `/robots.txt` y
  `/sitemap.xml`. `/api/leads` y `/api/agent` responden 401 sin sesión.
- Dentro del contenedor: uid 10001, `/app/data` con permisos 700, y `touch` en
  `/app/reigel` falla con «Read-only file system».
- La base sobrevive a `docker restart` con el mismo SHA256; apagado ordenado en
  0,7 s y cero trazas de error en el registro.
- `scripts/deploy_check.py` dentro del contenedor marca un único ERROR, «ninguno:
  ejecutar scripts/bootstrap.py», que es lo correcto en una base recién creada.

Se hizo con un contenedor suelto y un volumen temporal, no con `docker compose
up`, para no mezclar el `.env` de desarrollo de la computadora; el contenedor, el
volumen y la imagen se borraron al terminar.

Y después la pila completa con Caddy, desde una copia limpia del proyecto fuera
del repositorio y con su propio `.env` (`DOMAIN=localhost`), para que ningún
valor del `.env` de desarrollo entrara en los contenedores:

- `docker compose config --quiet` valida; `app` queda «healthy» y Caddy arranca
  después, porque espera a que lo esté.
- Caddy emite su certificado interno para `localhost` («issuer: local»).
- `http://localhost/` redirige con **308** a `https://localhost/`.
- Por HTTPS responden 200 las diecisiete rutas públicas, incluidas `/`, `/ia`,
  `/chat`, `/app`, `/soluciones/certificaciones` y `/sitemap.xml`;
  `/api/leads`, `/api/agent` y `/api/needs` responden 401 sin sesión.
- El puerto 8765 de la aplicación **no es alcanzable desde el host**: solo Caddy
  llega a ella.
- Cabeceras que ve el visitante: `Strict-Transport-Security` a un año con
  `includeSubDomains`, política de contenido sin `unsafe-inline` en los scripts,
  `X-Frame-Options: DENY`, `nosniff` y `Referrer-Policy`. Las pone la aplicación,
  no Caddy, y no aparecen duplicadas.
- Consumo en reposo: 69 MB la aplicación y 15 MB Caddy.

El navegador de esta computadora **no confía** en la CA interna de Caddy y
rechaza `https://localhost`. Es lo esperado y no se saltó: con un dominio real,
Let's Encrypt emite un certificado que sí se confía. Para mirar el sitio en local
hay que aceptar el aviso a mano en el navegador.

**No probado** (requiere un servidor o más descargas):

- La obtención del certificado HTTPS público, que exige dominio y puertos reales.
- Linux real: la dirección real del visitante y los permisos del volumen.
- El perfil `ia`: Ollama sin capacidades y compartiendo la red de la aplicación;
  la velocidad y el consumo de la IA.
- La migración de la base comercial, que no se abrió ni se copió.
- La retención de copias a 30 días y `caddy validate`.

Si algo de la lista «no probado» falla en el primer arranque, lo esperable es
un contenedor que no inicia y un mensaje claro en `docker compose logs`; los
datos no corren peligro porque todavía no hay datos en el servidor.

## Mejora propuesta en el código (no hecha)

La dirección de Ollama está escrita en `reigel/ai_chat.py` y
`reigel/assistant.py`. Sería más limpio leerla de una variable (por ejemplo
`REIGEL_OLLAMA_URL`) aceptando solo `http://`, sin credenciales y con un
servidor de una lista cerrada: `127.0.0.1`, `localhost`, `::1` o el nombre
interno `ollama`. Así Ollama iría en su propia red interna sin salida a
internet, en vez de compartir la red (y la salida) de la aplicación. No se hizo
porque esos archivos no formaban parte de esta tarea.

## Registro

**25 de noviembre de 2026 — preparación del despliegue con Docker.** (Entrada
dejada aquí y no en `TEAM_CAGUAS_IMPLEMENTATION.md` porque otro trabajo estaba
en curso sobre el acceso del equipo y ese archivo es donde suele anotarse.)

- Cambiado: `Dockerfile`, `compose.yaml`, `deploy/Caddyfile`, `.dockerignore`,
  `.env.example`; nuevos `deploy/backup.sh`, `deploy/restore.sh`,
  `scripts/restore.py`, `scripts/deploy_check.py`,
  `tests/test_deployment_files.py` y esta guía.
- Corregido: confianza en cabeceras de reenvío de cualquier origen
  (`--forwarded-allow-ips "*"`), que permitía falsificar la dirección del cliente.
- Alcance: preparación y pruebas locales. No hubo despliegue, publicación,
  descargas, cuentas, commit ni push. No se leyó `.env`, la base comercial ni
  ninguna clave, con una excepción involuntaria: una ejecución de
  `docker compose config` durante la validación mostró el valor de
  `REIGEL_LOCAL_MODEL` del `.env` local (un nombre de modelo, no un secreto).
  Las validaciones siguientes se hicieron en una carpeta temporal con un `.env`
  de ejemplo.

**26 de noviembre de 2026 — primera prueba real con Docker.** Hecha en una copia
aislada del commit `4fb002d`, con un `.env` de relleno; no se leyó el `.env`
real ni la base comercial. Resultado en «Qué se probó y qué no». Dos avisos:
una construcción hecha con el disco lleno dejó en la caché una capa con
archivos vacíos y la aplicación no arrancaba; se resolvió con
`docker compose build --no-cache`. Y `deploy/backup.sh` necesita permiso de
escritura en las carpetas de destino (por defecto `/var/backups/reigel`).
Al terminar se eliminaron contenedores, volúmenes e imágenes de la prueba.
