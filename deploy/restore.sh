#!/usr/bin/env bash
# Restaurar una copia en un servidor con Docker (docs/DESPLIEGUE.md).
#
#   deploy/restore.sh /var/backups/reigel/base/powersolar-FECHA.db \
#                     /var/backups/reigel/clave/powersolar-FECHA.db.totp.key
#
# El segundo argumento se omite si la clave viene de REIGEL_TOTP_KEY en .env o
# si la copia no tiene cuentas con Google Authenticator.
#
# Detiene el servicio, verifica la copia y su clave con scripts/restore.py
# (si la clave no abre los autenticadores, no restaura nada), deja lo anterior
# en una carpeta «antes-de-restaurar-…» dentro del volumen y vuelve a arrancar.
set -euo pipefail
umask 077

copy="${1:-}"
key="${2:-}"
if [ -z "$copy" ] || [ ! -f "$copy" ]; then
    echo "Uso: deploy/restore.sh COPIA.db [COPIA.db.totp.key]" >&2
    exit 2
fi
if [ -n "$key" ] && [ ! -f "$key" ]; then
    echo "No existe el archivo de clave: $key" >&2
    exit 2
fi
copy="$(realpath "$copy")"
[ -n "$key" ] && key="$(realpath "$key")"

cd "$(dirname "$0")/.."

echo "Se va a DETENER el servicio y reemplazar la base activa por:"
echo "  $copy"
printf 'Escribe SI para continuar: '
read -r answer
if [ "$answer" != "SI" ]; then
    echo "Cancelado. No se cambió nada."
    exit 3
fi

docker compose stop

staging="/app/data/restaurar"
run() { docker compose run --rm --no-deps -T app "$@"; }
cleanup() { run rm -rf "$staging" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Los archivos entran por la entrada estándar: quedan con el usuario de la
# aplicación y permisos privados, sin depender de los permisos del servidor.
run sh -c "umask 077; rm -rf $staging; mkdir -p $staging; cat > $staging/copia.db" < "$copy"
if [ -n "$key" ]; then
    run sh -c "umask 077; cat > $staging/copia.db.totp.key" < "$key"
fi

if run python scripts/restore.py --from "$staging/copia.db" --db /app/data/reigel.db --yes; then
    cleanup
    trap - EXIT
    docker compose up -d
    echo "Servicio arrancado. Comprueba: docker compose exec app python scripts/deploy_check.py"
else
    echo "No se restauró nada. La base anterior sigue en su sitio y el servicio quedó DETENIDO." >&2
    echo "Para volver a arrancarlo tal como estaba: docker compose up -d" >&2
    exit 1
fi
