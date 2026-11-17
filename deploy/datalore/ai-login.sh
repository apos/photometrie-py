#!/usr/bin/env bash
# Einmalige Anmeldung der KI-Kommandozeilen im Docker-Volume /auth (AI_AUTH_VOLUME, Standard varphot-ai-auth), das jeder Agent einhaengt.
# Die Anmeldung macht der Nutzer selbst (Claude im Browser; den Gemini-Schluessel gibt er selbst ein). Nichts davon wird ausgegeben, in Argumentlisten gelegt oder ins Image/Repo geschrieben.
#
# Aufruf:  ./ai-login.sh claude        Anmeldung mit dem Claude-Konto (Abo) -> Adresse im Browser oeffnen, Code zurueck ins Terminal einfuegen
#          ./ai-login.sh gemini-key    Gemini: API-Schluessel (aus Google AI Studio) verdeckt abfragen und nur im Volume ablegen (/auth/gemini/.env)
#          ./ai-login.sh gemini        Gemini CLI interaktiv anmelden (nur wo Google das fuer das Konto noch anbietet, siehe Hinweis unten)
#          ./ai-login.sh status        zeigt, was angemeldet ist (ohne Kontodaten)
#          ./ai-login.sh logout claude|gemini
# Danach laeuft NB03 (Schritt KI-Zweitlesung, Auswahl „Claude“ bzw. „Gemini“) in jedem neuen Agent; ein laufender Agent sieht das Volume sofort.
# Hinweis Gemini: Google hat „Login mit Google“ fuer private Konten ohne Bezahltarif am 2026-06-18 auf die Antigravity CLI verlegt (Seite der Gemini CLI,
# geprueft 2026-11-16); die Gemini CLI geht dann nur noch mit API-Schluessel (GEMINI_API_KEY) oder Code Assist (Unternehmen). Darum der Weg ueber gemini-key.
# Der Schluessel gehoert NICHT in die deploy/datalore/.env, nicht ins Repo, nicht in observer.json: gemini-key liest ihn verdeckt von der Eingabe (nicht in der
# Argumentliste, nicht im Shell-Verlauf) und schreibt ihn mit Rechten 600 nur in das Volume. Wer ihn nicht eintippen will: Zeile GEMINI_API_KEY=... von Hand in /auth/gemini/.env.
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
  gemini-key)
    if [ -t 0 ]; then read -r -s -p "Gemini-API-Schluessel (Eingabe unsichtbar): " K; echo; else read -r K; fi
    [ -n "${K:-}" ] || { echo "Kein Schluessel eingegeben." >&2; exit 2; }
    printf 'GEMINI_API_KEY=%s\n' "$K" | "$DOCKER" run --rm -i -v "$VOL:/auth" --entrypoint sh "$IMAGE" -c 'umask 077; mkdir -p /auth/gemini; cat > /auth/gemini/.env'
    unset K
    echo "Schluessel im Volume $VOL abgelegt (/auth/gemini/.env, Rechte 600). Pruefen: $0 status; in NB03 erscheint „Gemini (Cloud)“ ohne den Zusatz „nicht verfuegbar“ (Cloud muss in observer.json eingeschaltet sein)." ;;
  gemini) echo "Die Gemini CLI startet; die Anmeldeart im Menue waehlen (Beenden: Strg+C zweimal)."; "${RUN[@]}" gemini "$IMAGE" ;;
  status)
    "${RUN[@]}" sh "$IMAGE" -c 'echo "Claude:"; claude auth status 2>&1 | sed -E "s/\"(email|orgName|orgId|accountId)\"[^,}]*/\"\1\": \"…\"/g"; echo; echo "Gemini:"; ls -A /auth/gemini 2>/dev/null | sed "s/^/  Datei: /" || true' ;;
  logout)
    case "${2:-}" in
      claude) "${RUN[@]}" claude "$IMAGE" auth logout ;;
      gemini) "${RUN[@]}" sh "$IMAGE" -c 'rm -rf /auth/gemini/* /auth/gemini/.[!.]* 2>/dev/null; echo "Gemini-Anmeldung geloescht"' ;;
      *) echo "Aufruf: $0 logout claude|gemini" >&2; exit 2 ;;
    esac ;;
  *) echo "Aufruf: $0 claude | gemini-key | gemini | status | logout claude|gemini" >&2; exit 2 ;;
esac
