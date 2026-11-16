#!/usr/bin/env bash
# Einmalige Anmeldung der KI-Kommandozeilen im Docker-Volume /auth (AI_AUTH_VOLUME, Standard varphot-ai-auth), das jeder Agent einhaengt.
# Die Anmeldung macht der Nutzer selbst im Browser; hier wird kein Schluessel und kein Kennwort eingegeben, gespeichert oder ausgegeben.
#
# Aufruf:  ./ai-login.sh claude        Anmeldung mit dem Claude-Konto (Abo) -> Adresse im Browser oeffnen, Code zurueck ins Terminal einfuegen
#          ./ai-login.sh gemini        Gemini CLI (siehe Hinweis unten)
#          ./ai-login.sh status        zeigt, was angemeldet ist (ohne Kontodaten)
#          ./ai-login.sh logout claude|gemini
# Danach laeuft NB03 (Schritt KI-Zweitlesung, Auswahl „Claude“) in jedem neuen Agent; ein laufender Agent sieht das Volume sofort.
# Hinweis Gemini: Google hat „Login mit Google“ fuer private Konten ohne Bezahltarif am 2026-06-18 auf die Antigravity CLI verlegt (Seite der Gemini CLI,
# geprueft 2026-11-16); die Gemini CLI geht dann nur noch mit API-Schluessel (GEMINI_API_KEY) oder Code Assist (Unternehmen). Ein Schluessel gehoert NICHT in die
# .env oder ins Repo: ./ai-login.sh gemini fragt ihn nicht ab — er muesste in /auth/gemini/.env (Zeile GEMINI_API_KEY=...) liegen, von Hand und nur im Volume.
# Kompatibel mit macOS (bash 3.2).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DOCKER="${DOCKER:-docker}"
[ -f "$HERE/.env" ] && { set -a; . "$HERE/.env"; set +a; }
IMAGE="${AGENT_IMAGE:?AGENT_IMAGE fehlt (.env)}"
VOL="${AI_AUTH_VOLUME:-varphot-ai-auth}"
TTY=(); [ -t 0 ] && [ -t 1 ] && TTY=(-it)      # status/logout gehen auch ohne Terminal (cron, Skript); die Anmeldung braucht eins
RUN=("$DOCKER" run --rm ${TTY[@]+"${TTY[@]}"} -v "$VOL:/auth" -e CLAUDE_CONFIG_DIR=/auth/claude --entrypoint)

case "${1:-}" in
  claude) "${RUN[@]}" claude "$IMAGE" auth login ;;
  gemini) echo "Die Gemini CLI startet; die Anmeldeart im Menue waehlen (Beenden: Strg+C zweimal)."; "${RUN[@]}" gemini "$IMAGE" ;;
  status)
    "${RUN[@]}" sh "$IMAGE" -c 'echo "Claude:"; claude auth status 2>&1 | sed -E "s/\"(email|orgName|orgId|accountId)\"[^,}]*/\"\1\": \"…\"/g"; echo; echo "Gemini:"; ls -A /auth/gemini 2>/dev/null | sed "s/^/  Datei: /" || true' ;;
  logout)
    case "${2:-}" in
      claude) "${RUN[@]}" claude "$IMAGE" auth logout ;;
      gemini) "${RUN[@]}" sh "$IMAGE" -c 'rm -rf /auth/gemini/* /auth/gemini/.[!.]* 2>/dev/null; echo "Gemini-Anmeldung geloescht"' ;;
      *) echo "Aufruf: $0 logout claude|gemini" >&2; exit 2 ;;
    esac ;;
  *) echo "Aufruf: $0 claude | gemini | status | logout claude|gemini" >&2; exit 2 ;;
esac
