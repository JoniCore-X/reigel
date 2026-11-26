#!/usr/bin/env bash
# Copia de seguridad de R.E.I.G.E.L. en un servidor con Docker (docs/DESPLIEGUE.md).
#
# Usa scripts/backup.py dentro del contenedor (copia consistente con la API de
# SQLite y verificación de integridad), saca la copia del volumen y guarda la
# base y la clave de Google Authenticator en carpetas DISTINTAS: quien tenga
# las dos puede leer los secretos de los autenticadores.
#
#   deploy/backup.sh
#
# Variables opcionales:
#   REIGEL_BACKUP_DIR       carpeta de las copias de la base   (/var/backups/reigel/base)
#   REIGEL_KEY_BACKUP_DIR   carpeta de las copias de la clave  (/var/backups/reigel/clave)
#   REIGEL_BACKUP_KEEP_DAYS días que se conservan              (30)
#
# No sube nada a ningún servicio. Llevar las copias fuera del servidor es una
# decisión y una tarea del titular.
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

base_dir="${REIGEL_BACKUP_DIR:-/var/backups/reigel/base}"
key_dir="${REIGEL_KEY_BACKUP_DIR:-/var/backups/reigel/clave}"
keep_days="${REIGEL_BACKUP_KEEP_DAYS:-30}"

case "$keep_days" in
    ''|*[!0-9]*) echo "REIGEL_BACKUP_KEEP_DAYS debe ser un número de días." >&2; exit 2 ;;
esac
if [ "$base_dir" = "$key_dir" ]; then
    echo "La base y la clave deben guardarse en carpetas distintas." >&2
    exit 2
fi

mkdir -p "$base_dir" "$key_dir"
chmod 700 "$base_dir" "$key_dir"

name="powersolar-$(date -u +%Y%m%dT%H%M%SZ).db"
inside="/app/data/backups/$name"

cleanup() {
    docker compose exec -T app rm -f "$inside" "$inside.totp.key" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# 1. Copia consistente dentro del volumen, con la aplicación en marcha.
report="$(docker compose exec -T app python scripts/backup.py --output "$inside")"
expected="$(printf '%s\n' "$report" | sed -n 's/^SHA256: //p' | tr -d '\r')"

# 2. Sacar la base y comprobar que llegó idéntica.
docker compose cp "app:$inside" "$base_dir/$name" >/dev/null
actual="$(sha256sum "$base_dir/$name" | cut -d' ' -f1)"
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    rm -f "$base_dir/$name"
    echo "La copia no coincide con la original (SHA256). No se guardó." >&2
    exit 1
fi
chmod 600 "$base_dir/$name"
printf '%s  %s\n' "$actual" "$name" > "$base_dir/$name.sha256"

# 3. La clave, si vive en un archivo, va a su propia carpeta.
if docker compose exec -T app test -f "$inside.totp.key"; then
    docker compose cp "app:$inside.totp.key" "$key_dir/$name.totp.key" >/dev/null
    chmod 600 "$key_dir/$name.totp.key"
    if [ "$(wc -c < "$key_dir/$name.totp.key")" -ne 32 ]; then
        echo "La clave copiada no tiene 32 bytes. Revisa el volumen de datos." >&2
        exit 1
    fi
    key_note="clave en $key_dir/$name.totp.key"
else
    key_note="sin archivo de clave (viene de REIGEL_TOTP_KEY o todavía no hay autenticadores)"
fi

# 4. Retención: solo después de una copia nueva y verificada.
find "$base_dir" -maxdepth 1 -type f -name 'powersolar-*.db*' -mtime "+$keep_days" -delete
find "$key_dir" -maxdepth 1 -type f -name 'powersolar-*.db.totp.key' -mtime "+$keep_days" -delete

echo "Copia verificada: $base_dir/$name"
echo "SHA256: $actual"
echo "Google Authenticator: $key_note"
echo "Se conservan $keep_days días. Guarda la clave en otro lugar que la base."
