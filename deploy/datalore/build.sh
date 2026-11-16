#!/usr/bin/env bash
# Baut das Agent-Image (deploy/datalore/Dockerfile) fuer die Architektur dieses Rechners (oder PLATFORM=linux/amd64|linux/arm64).
#
# Aufruf:  deploy/datalore/build.sh            baut varphot-datalore-agent:<datalore-version>-py312
# Ablauf:  1. requirements.agent.txt aus requirements_datalore_base.txt + requirements.txt des Repos erzeugen (Zeilen mit -e/-r/-- fallen weg)
#          2. docker build mit der Repo-Wurzel als Kontext
#          3. Paketstand (pip freeze) nach deploy/datalore/freeze.<arch>.txt schreiben (zum Vergleichen, nicht zur Eingabe)
# Umgebung: DOCKER (docker|podman, Standard docker), DATALORE_VERSION (Standard aus .env, sonst 2026.4.1), PLATFORM, IMAGE (voller Name), ASTAP_SHA256.
# Kompatibel mit macOS (bash 3.2).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DOCKER="${DOCKER:-docker}"
if [ -f "$HERE/.env" ]; then
  # shellcheck disable=SC1091
  VER_ENV="$(grep -E '^DATALORE_VERSION=' "$HERE/.env" | tail -n 1 | cut -d= -f2- || true)"
fi
DATALORE_VERSION="${DATALORE_VERSION:-${VER_ENV:-2026.4.1}}"
IMAGE="${IMAGE:-varphot-datalore-agent:${DATALORE_VERSION}-py312}"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unbekannt)"
DIRTY=""
if [ -n "$(git -C "$ROOT" status --porcelain varphot tools data pyproject.toml requirements.txt deploy 2>/dev/null)" ]; then DIRTY="+lokale-aenderungen"; fi

REQ_OUT="$HERE/requirements.agent.txt"
{
  cat "$HERE/requirements_datalore_base.txt"
  echo "# --- Projekt: requirements.txt des Repos ---"
  grep -v -E '^[[:space:]]*(-e|-r|--)' "$ROOT/requirements.txt"
} > "$REQ_OUT"

ARGS=(build -f "$HERE/Dockerfile" -t "$IMAGE"
      --build-arg "DATALORE_VERSION=$DATALORE_VERSION"
      --build-arg "GIT_COMMIT=$COMMIT$DIRTY"
      --build-arg "BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)")
[ -n "${PLATFORM:-}" ] && ARGS+=(--platform "$PLATFORM")
[ -n "${ASTAP_SHA256:-}" ] && ARGS+=(--build-arg "ASTAP_SHA256=$ASTAP_SHA256")
ARGS+=("$ROOT")

echo "Baue $IMAGE (Git-Stand $COMMIT$DIRTY, ${PLATFORM:-native Architektur}) mit $DOCKER ..."
"$DOCKER" "${ARGS[@]}"

ARCH="$("$DOCKER" image inspect "$IMAGE" --format '{{.Architecture}}')"
"$DOCKER" run --rm --entrypoint cat "$IMAGE" /opt/python/envs/photometrie/freeze.txt > "$HERE/freeze.$ARCH.txt"
echo "Fertig: $IMAGE ($ARCH, $("$DOCKER" image inspect "$IMAGE" --format '{{.Size}}' | awk '{printf "%.1f GB", $1/1e9}'))"
echo "Pruefen: $DOCKER run --rm --entrypoint sh $IMAGE -c 'astap_cli -h | head -2; siril-cli --version; python -c \"import varphot\"'"
