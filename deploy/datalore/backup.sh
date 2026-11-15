#!/usr/bin/env bash
# Sicherung der Datalore-Daten (Notebooks, Konten, Einstellungen) fuer Umzug oder Wiederherstellung: Datenbank (logischer Dump) und Volume datalore-storage.
# Ziel: BACKUP_DIR (Standard ./backup). NICHT enthalten: .env (Passwort) und der Lizenzschluessel — beides getrennt im Passwortmanager (README „Geheimnisse“).
# Es wird nichts geloescht. Aufruf: ./backup.sh            Umgebung: DOCKER, BACKUP_DIR
set -euo pipefail
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
DOCKER="${DOCKER:-docker}"
set -a; # shellcheck disable=SC1091
. ./.env; set +a
PROJECT="${COMPOSE_PROJECT_NAME:-datalore}"
OUT="${BACKUP_DIR:-$HERE/backup}"
STAMP="$(date +%Y-%m-%d_%H%M)"
mkdir -p "$OUT"

"$DOCKER" compose exec -T postgresql pg_dump -U admin -d datalore --no-owner | gzip > "$OUT/datalore_db_$STAMP.sql.gz.part"
mv "$OUT/datalore_db_$STAMP.sql.gz.part" "$OUT/datalore_db_$STAMP.sql.gz"

"$DOCKER" run --rm --user root --entrypoint tar -v "${PROJECT}_datalore-storage:/v:ro" "jetbrains/datalore-postgres:${DATALORE_VERSION:-2026.4.1}" czf - -C /v . > "$OUT/datalore_storage_$STAMP.tgz.part"
mv "$OUT/datalore_storage_$STAMP.tgz.part" "$OUT/datalore_storage_$STAMP.tgz"

echo "Datalore-Backup $STAMP in $OUT:"
ls -l "$OUT"/*_"$STAMP".* | awk '{print "  " $5 " Bytes  " $9}'
