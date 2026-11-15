#!/usr/bin/env bash
# Laedt die ASTAP-Sterndatenbanken (ASTAP_DB_URLS in .env) in das Docker-Volume ASTAP_DB_VOLUME. Die Datenbank ist zu gross fuer das Image (1,7 GB)
# und aendert sich selten; sie liegt deshalb in einem Volume, das die Agents schreibgeschuetzt einhaengen. Mehrfaches Ausfuehren ueberspringt, was schon da ist.
# Quelle: SourceForge-Projekte astap-program (D-Datenbanken) und hnsky (G/V-Datenbanken), Han Kleijn. Aufruf: ./astap-db.sh
# Umgebung: DOCKER (docker|podman). Das Volume wird mit dem Agent-Image selbst befuellt (hat curl, unzip, dpkg-deb).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER:-docker}"
[ -f "$HERE/.env" ] || { echo ".env fehlt" >&2; exit 1; }
set -a; # shellcheck disable=SC1091
. "$HERE/.env"; set +a
: "${AGENT_IMAGE:?}"; : "${ASTAP_DB_URLS:?ASTAP_DB_URLS leer}"
VOL="${ASTAP_DB_VOLUME:-varphot-astap-db}"

"$DOCKER" volume inspect "$VOL" > /dev/null 2>&1 || "$DOCKER" volume create "$VOL" > /dev/null
echo "Volume $VOL, Pakete: $ASTAP_DB_URLS"

# Im Container: jede URL einmal laden und auspacken; Marker .done-<name> verhindert erneutes Laden.
"$DOCKER" run --rm --user root -e URLS="$ASTAP_DB_URLS" -v "$VOL:/db" --entrypoint sh "$AGENT_IMAGE" -c '
set -eu
for u in $URLS; do
  f=$(basename "$(dirname "$u")")                       # .../d80_star_database.deb/download -> d80_star_database.deb
  if [ -e "/db/.done-$f" ]; then echo "schon vorhanden: $f"; continue; fi
  echo "lade $f ..."
  curl -fsSL --retry 3 -o "/tmp/$f" "$u"
  rm -rf /tmp/x && mkdir /tmp/x
  case "$f" in
    *.deb) dpkg-deb -x "/tmp/$f" /tmp/x ;;
    *.zip) unzip -q -o "/tmp/$f" -d /tmp/x ;;
    *) echo "unbekanntes Format: $f" >&2; exit 1 ;;
  esac
  # alle Dateien der Datenbank (ASTAP-Namensschema, z. B. d80_0101.1476 / g17_0101.290) flach nach /db
  find /tmp/x -type f \( -name "*.1476" -o -name "*.290" -o -name "*.001" -o -name "*.wcs" -o -name "*.dat" -o -name "*.db*" -o -name "*.[0-9][0-9][0-9]*" \) -exec cp {} /db/ \;
  touch "/db/.done-$f"
  rm -rf /tmp/x "/tmp/$f"
done
echo "Dateien im Volume: $(ls /db | grep -v "^\.done" | wc -l), Platz: $(du -sh /db | cut -f1)"
'
