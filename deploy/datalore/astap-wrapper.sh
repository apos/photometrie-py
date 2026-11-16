#!/bin/sh
# Wrapper fuer ASTAP im Datalore-Agent: varphot ruft /usr/local/bin/astap auf (varphot/astrometry.py).
# Benutzt die Kommandozeilenversion /usr/local/bin/astap_cli (im Image, statisch, braucht kein Display) mit der Sterndatenbank
# in $ASTAP_DB (Standard /opt/astap_db, ein Docker-Volume, befuellt von deploy/datalore/astap-db.sh). Die CLI meldet "Solution found" selbst und schreibt die .wcs.
CLI=/usr/local/bin/astap_cli
if [ ! -x "$CLI" ]; then
  echo "astap_cli fehlt im Image" >&2
  exit 127
fi
DB="${ASTAP_DB:-/opt/astap_db}"
if [ -d "$DB" ] && [ -n "$(ls -A "$DB" 2>/dev/null)" ]; then
  exec "$CLI" -d "$DB" "$@"
fi
echo "Hinweis: Sterndatenbank $DB ist leer (deploy/datalore/astap-db.sh ausfuehren)" >&2
exec "$CLI" "$@"
