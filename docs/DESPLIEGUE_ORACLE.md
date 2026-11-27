# Conseguir el servidor gratuito · Oracle Cloud Always Free

Esto es el **prólogo** de [DESPLIEGUE.md](DESPLIEGUE.md): te lleva de no tener nada a
tener una máquina Ubuntu en internet, con dominio y con Docker, lista para empezar por
el Paso 1 de esa guía. Lo que viene después —`.env`, construir, arrancar, copias de
seguridad— ya está escrito allí y no se repite aquí.

**Estado honesto (27 de noviembre de 2026):** nadie ha desplegado todavía. Lo único
comprobado desde el repositorio es que la imagen construye para ARM64, que es la
arquitectura de la máquina gratuita buena de Oracle (ver el Registro al final). Todo lo
demás de esta guía es procedimiento, no resultado medido.

## Por qué una máquina y no un servicio gestionado

Se miraron los planes gratuitos de Render, Fly, Koyeb y Railway. Ninguno sirve aquí, y
la razón es siempre la misma: **el CRM vive en una base SQLite sobre un disco**. Render
duerme a los quince minutos y sus discos son de pago; Koyeb y Fly cambiaron condiciones
durante 2026; Railway da crédito de prueba. En un plan sin disco persistente, cada
redespliegue o reinicio devuelve la aplicación a una base vacía. Para enseñar el sitio
serviría. Para que el equipo trabaje, no: perder el volumen es perder el negocio.

Una máquina gratuita sí tiene disco de verdad, no duerme, y corre exactamente el mismo
`compose.yaml` que ya está probado en local.

## Lo que solo puedes hacer tú

El asistente no crea cuentas, no da datos de tarjeta y no compra. Esto es tuyo:

1. **Crear la cuenta de Oracle Cloud.** Pide un móvil y una tarjeta para verificar
   identidad. Oracle dice que no cobra mientras la cuenta siga en Always Free, pero
   puede hacer una retención temporal de comprobación. Si la cuenta está en un país y
   la tarjeta en otro, la verificación suele fallar.
2. **Elegir la contraseña y guardar la clave SSH.** La clave privada se descarga una
   sola vez: si la pierdes, la máquina queda inaccesible y hay que rehacerla.
3. **Registrar el dominio** (abajo hay una opción gratuita).
4. **Decidir si me das acceso SSH** para que corra los comandos, o los corres tú
   copiándolos. Las dos cosas valen; la segunda es la que no te obliga a confiarme una
   llave.

## Paso O1 · Crear la instancia

En la consola de Oracle: **Compute → Instances → Create instance**.

- **Imagen:** Ubuntu 24.04 (Canonical). No uses Oracle Linux salvo que lo prefieras: la
  guía de Docker de DESPLIEGUE.md está escrita para Debian/Ubuntu.
- **Forma (shape):** `VM.Standard.A1.Flex`, que es **ARM** (Ampere). Pide los OCPU y la
  memoria que te deje la consola; Oracle ha cambiado esta asignación más de una vez, así
  que toma lo que ofrezca en lugar de buscar una cifra concreta. Con 1 OCPU y 6 GB sobra
  para esto.
- **Si sale «Out of capacity»:** es normal en la forma A1 y no es un error tuyo.
  Reintenta más tarde o en otro dominio de disponibilidad. La alternativa es
  `VM.Standard.E2.1.Micro` (AMD, x86, 1 GB de RAM), que siempre hay: funciona, pero con
  1 GB hay que añadir intercambio (más abajo) y la construcción de la imagen va lenta.
- **Clave SSH:** sube tu clave pública o deja que Oracle genere el par y **descarga la
  privada en ese momento**.

Apunta la **IP pública** que te dé la instancia.

## Paso O2 · Abrir los puertos, que son dos cortafuegos

Esta es la causa número uno de que un despliegue en Oracle parezca muerto: se abre un
cortafuegos y se olvida el otro. La máquina no responde y no hay ningún error que lo
explique.

**a) La lista de seguridad de la red (en la consola).**
Networking → Virtual Cloud Networks → tu VCN → Security Lists → la lista por defecto →
*Add Ingress Rules*. Dos reglas, origen `0.0.0.0/0`, protocolo TCP, puertos destino
`80` y `443`.

**b) El cortafuegos de la propia máquina (por SSH).**
Las imágenes de Ubuntu de Oracle vienen con reglas de `iptables` que solo dejan pasar
SSH, y esas reglas sobreviven al reinicio. Hay que abrir los dos puertos también ahí:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

Comprueba desde tu computadora que el puerto responde antes de seguir. Si esto falla, no
sigas: lo que venga después fallará por este motivo y parecerá otra cosa.

## Paso O3 · Un dominio, gratis si hace falta

Caddy pide el certificado HTTPS a Let's Encrypt, y para eso hace falta un nombre de
dominio real apuntando a la IP. Una IP pelada no sirve.

Si ya tienes dominio, crea un registro `A` que apunte a la IP pública y salta al paso
siguiente.

Si no lo tienes, **DuckDNS** da un subdominio gratuito y permanente, y Let's Encrypt
emite certificados para él sin problema: entra en `duckdns.org`, crea el nombre que
quieras y apúntalo a la IP de la instancia. Queda algo como
`TU-NOMBRE.duckdns.org`.

No uses servicios tipo `nip.io` que resuelven la IP dentro del nombre: Let's Encrypt los
trata como dominio público compartido y topas con sus límites.

Espera a que el nombre resuelva antes de arrancar la pila:

```bash
getent hosts TU-NOMBRE.duckdns.org
```

## Paso O4 · Preparar la máquina

Por SSH, con el usuario `ubuntu`:

```bash
sudo apt update && sudo apt upgrade -y
```

Instala Docker siguiendo la guía oficial de Docker para Ubuntu (el repositorio de
Docker, no el paquete `docker.io` de Ubuntu, que va por detrás). Después:

```bash
sudo usermod -aG docker $USER && newgrp docker
docker --version && docker compose version
```

**Solo si tomaste la máquina micro de 1 GB**, añade intercambio o la construcción se
quedará sin memoria:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Paso O5 · Traer el código

```bash
git clone https://github.com/JoniCore-X/reigel.git
cd reigel
```

El repositorio es público y **no contiene `.env`, ni base, ni claves**: todo eso lo
escribes en el servidor. A partir de aquí sigue [DESPLIEGUE.md](DESPLIEGUE.md) desde su
**Paso 2 · Escribir `.env`**, donde `DOMAIN` es el nombre del paso O3 y `CADDY_EMAIL` tu
correo para los avisos del certificado.

## Sobre ARM

La máquina A1 es ARM64 y la imagen se construye en el propio servidor, así que no hay
que hacer nada especial: `docker compose build` usa la arquitectura de la máquina. Las
dos dependencias que llevan código compilado, `cryptography` y `argon2-cffi`, publican
ruedas para ARM64, de modo que `pip` no tiene que compilar nada.

Lo que **no** funciona igual en ARM es Ollama: el perfil de IA local de `compose.yaml`
es opcional y viene apagado. Déjalo apagado en este servidor. El sitio público, el chat
de coordinación y el CRM no dependen de él; lo que depende son las rutas generativas,
que se degradan a sus respuestas de respaldo.

## Lo que sigue siendo tuyo después

- **Las copias de seguridad.** El Paso 7 de DESPLIEGUE.md las explica. En una máquina
  gratuita importan más, no menos: nadie te garantiza nada.
- **Mantener la cuenta viva.** Oracle reclama instancias de cuentas inactivas. Entrar a
  la consola de vez en cuando evita sustos.
- **La decisión de migrar la base comercial.** La Ruta B del Paso 3 lo cubre. No se hace
  durante una tarea de desarrollo.

## Registro

- **27 de noviembre de 2026.** Escrita la guía. Comprobado desde el repositorio que la
  imagen construye para `linux/arm64` con `docker buildx`, que era la única duda técnica
  que se podía resolver sin tener la cuenta. No se ha creado ninguna cuenta, no se ha
  levantado ninguna instancia y nada de lo demás está verificado contra un servidor real.
