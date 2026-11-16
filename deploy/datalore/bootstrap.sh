#!/usr/bin/env bash
# Richtet Datalore mit varphot auf diesem Rechner ein (Linux oder Mac, Docker oder Podman) und startet es. Mehrfaches Ausfuehren ist ungefaehrlich.
# Schritte: 1. .env aus .env.example anlegen (DB_PASSWORD erzeugen)  2. Agent-Image beschaffen: schon da / aus dem imgstore laden / lokal bauen
#           3. agents-config.yaml erzeugen  4. ASTAP-Sterndatenbank ins Volume laden  5. Datalore starten
# Aufruf:   ./bootstrap.sh [--no-start] [--build]       (--build erzwingt den lokalen Bau statt imgstore)
# Umgebung: DOCKER (docker|podman), IMGSTORE_DIR (Ordner mit den Images, siehe deploy/imgstore), SKIP_ASTAP_DB=1 (Datenbank spaeter laden)
# Danach (einmalig, im Browser): Admin anlegen und den Lizenzschluessel im Admin-Panel unter "License" eintragen (JetBrains Account → Organisation).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
DOCKER="${DOCKER:-docker}"
export DOCKER
START=1; FORCE_BUILD=0
for a in "$@"; do case "$a" in --no-start) START=0 ;; --build) FORCE_BUILD=1 ;; *) echo "unbekannte Option $a" >&2; exit 2 ;; esac; done

command -v "$DOCKER" > /dev/null 2>&1 || { echo "'$DOCKER' nicht gefunden: Docker Desktop, OrbStack oder Docker Engine installieren" >&2; exit 1; }
"$DOCKER" info > /dev/null 2>&1 || { echo "Docker-Daemon antwortet nicht (Docker Desktop/OrbStack starten?)" >&2; exit 1; }
"$DOCKER" compose version > /dev/null 2>&1 || { echo "'$DOCKER compose' fehlt (Compose-Plugin installieren)" >&2; exit 1; }

# 1. .env
if [ ! -f .env ]; then
  cp .env.example .env; chmod 600 .env
  echo ".env angelegt aus .env.example — bitte VARPHOT_DATA_DIR, EXCHANGE_DIR, DATALORE_PUBLIC_URL, DATALORE_BIND pruefen/anpassen (Datei oeffnen), dann bootstrap.sh erneut starten."
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)"
  sed -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$PW|" .env > .env.tmp && mv .env.tmp .env && chmod 600 .env
  exit 0
fi
set -a; # shellcheck disable=SC1091
. ./.env; set +a
if [ -z "${DB_PASSWORD:-}" ]; then
  PW="$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 32 || true)"
  sed -e "s|^DB_PASSWORD=.*|DB_PASSWORD=$PW|" .env > .env.tmp && mv .env.tmp .env && chmod 600 .env
  echo "DB_PASSWORD erzeugt (steht nur in .env; Kopie im Passwortmanager ablegen)"
  set -a; . ./.env; set +a
fi

# 2. Agent-Image
if [ "$FORCE_BUILD" = "0" ] && "$DOCKER" image inspect "$AGENT_IMAGE" > /dev/null 2>&1; then
  echo "Agent-Image $AGENT_IMAGE ist vorhanden"
else
  NAME="${AGENT_IMAGE%%:*}"; TAG="${AGENT_IMAGE##*:}"
  if [ "$FORCE_BUILD" = "0" ] && [ -n "${IMGSTORE_DIR:-}" ] && "$HERE/../imgstore/imgstore" verify "$NAME:$TAG" -p varphot > /dev/null 2>&1; then
    "$HERE/../imgstore/imgstore" pull "$NAME:$TAG" -p varphot
  else
    echo "Image nicht im imgstore (oder --build): baue lokal (dauert 10-20 Minuten) ..."
    ./build.sh
  fi
fi

# 3. Konfiguration
./render-config.sh

# 4. ASTAP-Datenbank
if [ "${SKIP_ASTAP_DB:-0}" != "1" ]; then ./astap-db.sh; fi

# 5. Start
if [ "$START" = "1" ]; then
  "$DOCKER" compose up -d
  echo
  echo "Datalore laeuft: $DATALORE_PUBLIC_URL"
  echo "Beim ersten Start: Admin-Konto anlegen, Lizenzschluessel im Admin-Panel eintragen, Environment 'photometrie-agent' waehlen."
fi
