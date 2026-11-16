#!/usr/bin/env bash
# Pakete im Agent-Image aktuell halten: pruefen (check) und mit frischen Paketen neu bauen (build).
#
# Warum: Das Image ist eine Momentaufnahme (Python-Pakete, Siril, ASTAP, Claude Code, Gemini CLI, Node.js, Betriebssystempakete). Wer es nicht neu baut, laeuft
# mit dem Stand vom letzten Bau — auch bei Sicherheitskorrekturen. Selbstaktualisierung im laufenden Container wuerde beim naechsten Start verloren gehen und
# macht den Stand unvorhersagbar; deshalb ist sie aus, und aktualisiert wird durch einen Neubau, den man pruefen kann (Vergleich der Paketlisten, Funktionsprobe).
#
# Aufruf:  ./update.sh check     zeigt, was veraltet ist (aendert nichts; Rueckgabecode 10 = es gibt Neuerungen, 0 = aktuell, sonst Fehler)
#          ./update.sh build     baut mit NO_CACHE=1 neu (Basis-Image, apt, pip, npm, ASTAP frisch), prueft, zeigt die Unterschiede, legt ein Datumsetikett an
#                                (<image>-JJJJMMTT = Rueckfall) und legt das Image mit imgstore ab, falls IMGSTORE_DIR gesetzt ist
# Danach: laufende Agents behalten das alte Image bis zum Stopp (Datalore: Notebook-Rechner beenden); neue Agents starten mit dem neuen. Rueckfall:
#         docker tag <image>-JJJJMMTT <image>
# Regelmaessig: `check` woechentlich per cron (README), `build` nach einem Befund oder monatlich von Hand.
# Kompatibel mit macOS (bash 3.2).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER:-docker}"
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
IMAGE="${IMAGE:-${AGENT_IMAGE:-varphot-datalore-agent:${DATALORE_VERSION:-2026.4.1}-py312}}"
PYBIN=/opt/python/envs/photometrie/bin/python
ROOT_RUN=("$DOCKER" run --rm --user root --entrypoint sh)

cmd_check() {
  "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1 || { echo "Image $IMAGE nicht vorhanden (build.sh oder imgstore pull)" >&2; exit 1; }
  echo "== Image $IMAGE (gebaut $("$DOCKER" image inspect "$IMAGE" --format '{{.Created}}' | cut -c1-10)) =="
  out="$("${ROOT_RUN[@]}" "$IMAGE" -c '
    echo "--- installiert ---"
    echo "claude $(claude --version 2>&1 | head -1)"; echo "gemini $(gemini --version 2>&1 | head -1)"; echo "node $(node --version)"
    echo "siril $(siril-cli --version 2>&1 | head -1)"; echo "astap $(astap_cli -h 2>&1 | head -1)"
    echo "--- apt (veraltet) ---"
    apt-get update -qq 2>&1 | tail -n 1
    apt list --upgradable 2>/dev/null | grep -v "^Listing" | sed "s/^/  /" || true
    echo "--- npm: Gemini CLI ---"
    have=$(npm ls -g --depth=0 @google/gemini-cli 2>/dev/null | sed -n "s/.*gemini-cli@//p" | head -1); want=$(npm view @google/gemini-cli version 2>/dev/null)
    echo "  installiert ${have:-?}, neueste ${want:-?}"; [ -n "$have" ] && [ -n "$want" ] && [ "$have" != "$want" ] && echo "  UPDATE gemini-cli"
    echo "--- pip (veraltet, Umgebung photometrie) ---"
    '"$PYBIN"' -m pip list --outdated --format=columns 2>&1 | sed "s/^/  /" | head -40
  ' 2>&1)" || { echo "$out"; echo "Pruefung fehlgeschlagen (Netz?)" >&2; exit 1; }
  echo "$out"
  # Neuerungen: apt-Zeilen mit "[upgradable", die Zeile "UPDATE gemini-cli", Datenzeilen der pip-Tabelle (Name, Version beginnt mit Ziffer)
  n_apt=$(echo "$out" | grep -c "upgradable" || true)
  n_npm=$(echo "$out" | grep -c "UPDATE gemini-cli" || true)
  n_pip=$(echo "$out" | sed -n '/--- pip/,$p' | grep -cE '^  [A-Za-z0-9_.-]+ +[0-9]' || true)
  echo "== Zusammenfassung: apt $n_apt, npm $n_npm, pip $n_pip =="
  if [ $((n_apt + n_npm + n_pip)) -gt 0 ]; then echo "Es gibt Neuerungen -> ./update.sh build"; exit 10; fi
  echo "Alles aktuell."
}

cmd_build() {
  ARCH_TAG="$(date +%Y%m%d)"
  OLD_FREEZE="$(mktemp)"; OLD_TOOLS="$(mktemp)"
  ARCH="$("$DOCKER" image inspect "$IMAGE" --format '{{.Architecture}}' 2>/dev/null || uname -m)"
  cp "$HERE/freeze.$ARCH.txt" "$OLD_FREEZE" 2>/dev/null || : > "$OLD_FREEZE"
  cp "$HERE/tools.$ARCH.txt" "$OLD_TOOLS" 2>/dev/null || : > "$OLD_TOOLS"
  if "$DOCKER" image inspect "$IMAGE" >/dev/null 2>&1; then "$DOCKER" tag "$IMAGE" "$IMAGE-$ARCH_TAG-vorher"; echo "Rueckfall-Etikett: $IMAGE-$ARCH_TAG-vorher"; fi
  NO_CACHE=1 IMAGE="$IMAGE" "$HERE/build.sh"
  echo "== Funktionsprobe =="
  "$DOCKER" run --rm --entrypoint sh "$IMAGE" -c "$PYBIN -c 'import varphot, astropy, photutils, scipy; print(\"varphot\", varphot.__version__, \"astropy\", astropy.__version__, \"photutils\", photutils.__version__)' && astap_cli -h 2>&1 | head -1 && siril-cli --version 2>&1 | head -1 && claude --version && gemini --version"
  echo "== Unterschiede gegenueber dem vorigen Bau (Python-Pakete) =="
  d="$(diff "$OLD_FREEZE" "$HERE/freeze.$ARCH.txt" | grep -E '^[<>]' | head -60 || true)"; [ -n "$d" ] && echo "$d" || echo "  keine"
  echo "== Unterschiede (Werkzeuge) =="
  d="$(diff "$OLD_TOOLS" "$HERE/tools.$ARCH.txt" | grep -E '^[<>]' || true)"; [ -n "$d" ] && echo "$d" || echo "  keine"
  "$DOCKER" tag "$IMAGE" "$IMAGE-$ARCH_TAG"
  if [ -n "${IMGSTORE_DIR:-}" ] && command -v imgstore >/dev/null 2>&1; then imgstore push "$IMAGE" -p varphot; fi
  rm -f "$OLD_FREEZE" "$OLD_TOOLS"
  echo "Fertig. Neue Agents starten mit dem neuen Image; laufende Notebook-Rechner in Datalore beenden, damit sie es uebernehmen."
}

case "${1:-}" in
  check) cmd_check ;;
  build) cmd_build ;;
  *) echo "Aufruf: $0 check | build" >&2; exit 2 ;;
esac
