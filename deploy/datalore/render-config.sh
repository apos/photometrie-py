#!/usr/bin/env bash
# Erzeugt agents-config.yaml aus den Werten in .env (Ordner, Image, Netzwerk, GPU). Datalore liest nur diese Datei, kennt aber keine Variablen;
# deshalb wird sie hier erzeugt statt von Hand gepflegt. Nach jeder Aenderung an .env erneut ausfuehren und den Server neu starten:
#   ./render-config.sh && docker compose up -d --force-recreate datalore
# Kompatibel mit macOS (bash 3.2).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
[ -f .env ] || { echo ".env fehlt (cp .env.example .env oder bootstrap.sh)" >&2; exit 1; }
set -a; # shellcheck disable=SC1091
. ./.env; set +a

: "${AGENT_IMAGE:?AGENT_IMAGE fehlt in .env}"
: "${VARPHOT_DATA_DIR:?VARPHOT_DATA_DIR fehlt in .env}"
: "${EXCHANGE_DIR:?EXCHANGE_DIR fehlt in .env}"
PROJECT="${COMPOSE_PROJECT_NAME:-datalore}"
DBVOL="${ASTAP_DB_VOLUME:-varphot-astap-db}"
AUTHVOL="${AI_AUTH_VOLUME:-varphot-ai-auth}"
for d in "$VARPHOT_DATA_DIR" "$EXCHANGE_DIR"; do
  case "$d" in /*) ;; *) echo "Pfad muss absolut sein: $d" >&2; exit 1 ;; esac
  mkdir -p "$d"
done

vols() {   # Mounts eines Agents, eingerueckt
  echo "        - \"$VARPHOT_DATA_DIR:/work/PHOTOMETRIE_PY_DATA\""
  echo "        - \"$EXCHANGE_DIR:/exchange\""
  echo "        - \"$DBVOL:/opt/astap_db:ro\""
  echo "        - \"$AUTHVOL:/auth\""
  if [ -n "${VARPHOT_REPO_DIR:-}" ]; then echo "        - \"$VARPHOT_REPO_DIR:/work/PHOTOMETRIE_PY:ro\""; fi
}

{
  echo "# ERZEUGT von render-config.sh aus .env — nicht von Hand aendern."
  echo "docker:"
  echo "  network: ${PROJECT}-agents-network"
  echo "  dataloreHost: datalore"
  echo "  instances:"
  echo "    - id: photometrie-agent"
  echo "      default: true"
  echo "      label: \"docker-photometrie\""
  echo "      description: \"docker-photometrie (Python 3.12, varphot, ASTAP, Siril, CPU)\""
  echo "      image: $AGENT_IMAGE"
  echo "      volumes:"
  vols
  if [ "${ENABLE_GPU_AGENT:-0}" = "1" ]; then
    echo "    - id: gpu-agent"
    echo "      label: \"docker-photometrie-gpu\""
    echo "      description: \"docker-photometrie (NVIDIA GPU)\""
    echo "      image: $AGENT_IMAGE"
    echo "      deviceRequests:"
    echo "        - driver: \"nvidia\""
    echo "          count: 1"
    echo "          capabilities: [[\"gpu\"]]"
    echo "      volumes:"
    vols
  fi
} > agents-config.yaml
echo "agents-config.yaml erzeugt (Image $AGENT_IMAGE, Daten $VARPHOT_DATA_DIR)"
