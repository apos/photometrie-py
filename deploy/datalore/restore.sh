#!/usr/bin/env bash
# Spielt ein Backup (backup.sh) in eine FRISCHE Datalore-Installation ein: Datenbank und Volume datalore-storage. Vorher muss der Stack einmal laufen (bootstrap.sh),
# damit Volumes und Datenbank existieren. Bestehende Daten in der Zieldatenbank werden ersetzt, deshalb Rueckfrage (--yes ueberspringt sie).
# Aufruf: ./restore.sh <datalore_db_*.sql.gz> <datalore_storage_*.tgz> [--yes]       Umgebung: DOCKER
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
DOCKER="${DOCKER:-docker}"
DB="${1:?Aufruf: restore.sh <db.sql.gz> <storage.tgz> [--yes]}"; ST="${2:?Storage-Archiv fehlt}"
[ -f "$DB" ] && [ -f "$ST" ] || { echo "Datei nicht gefunden" >&2; exit 1; }
set -a; # shellcheck disable=SC1091
. ./.env; set +a
PROJECT="${COMPOSE_PROJECT_NAME:-datalore}"
if [ "${3:-}" != "--yes" ]; then
  printf "Datenbank und Storage-Volume von %s werden ERSETZT. Fortfahren? [ja/NEIN] " "$PROJECT"; read -r a; [ "$a" = "ja" ] || { echo abgebrochen; exit 1; }
fi
"$DOCKER" compose stop datalore
"$DOCKER" compose exec -T postgresql psql -U admin -d postgres -c "DROP DATABASE IF EXISTS datalore WITH (FORCE)" -c "CREATE DATABASE datalore"
gunzip -c "$DB" | "$DOCKER" compose exec -T postgresql psql -U admin -d datalore -q -v ON_ERROR_STOP=1 > /dev/null
"$DOCKER" run --rm --user root --entrypoint sh -i -v "${PROJECT}_datalore-storage:/v" "jetbrains/datalore-postgres:${DATALORE_VERSION:-2026.4.1}" -c 'rm -rf /v/* /v/.[!.]* 2>/dev/null; tar xzf - -C /v' < "$ST"
"$DOCKER" compose start datalore
echo "Wiederhergestellt. Datalore startet; danach Anmeldung mit den Konten aus dem Backup."
