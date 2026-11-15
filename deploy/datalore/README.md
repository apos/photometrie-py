# Datalore mit varphot auf jedem Docker-Host

Ziel: dieselbe Datalore-Installation (Server, Postgres, Agent mit Python, ASTAP und Siril) auf **jedem** Docker-Host starten — Linux amd64 (panama) oder Mac Apple Silicon (M4) —, ohne Zutaten vom Host. Das Image wird gebaut, mit `imgstore` im Nextcloud-Ordner abgelegt und auf dem Zielrechner geladen (`../imgstore/README.md`). Konzept und Entscheidungen: KONZEPT.md §17.

## Inhalt

| Datei | Zweck |
|---|---|
| `Dockerfile`, `build.sh` | Agent-Image: Python-3.12-Umgebung (Pakete aus `requirements.txt`), ASTAP-CLI, Siril-CLI, varphot-Stand |
| `docker-compose.yml`, `.env.example` | Datalore-Server und Postgres; alle Host-Werte stehen in `.env` |
| `render-config.sh` | erzeugt `agents-config.yaml` (Agent-Definition) aus `.env` |
| `astap-db.sh` | lädt die ASTAP-Sterndatenbank (1,7 GB) in ein Docker-Volume |
| `bootstrap.sh` | richtet alles ein und startet (Image beschaffen, Konfiguration, Datenbank, `docker compose up`) |
| `backup.sh`, `restore.sh` | Notebooks, Konten und Einstellungen sichern und auf einem anderen Host einspielen |

## Schnellstart (neuer Rechner)

```bash
git clone <repo> photometrie-py && cd photometrie-py/deploy/datalore
export IMGSTORE_DIR=~/Nextcloud/WORKSPACE/DOCKER_REGISTRY      # dort liegen die fertigen Images (sonst baut bootstrap.sh selbst, 10–20 min)
./bootstrap.sh          # 1. Aufruf: legt .env an und endet — Pfade und Adresse prüfen
./bootstrap.sh          # 2. Aufruf: Image laden, Konfiguration, Sterndatenbank, Start
```

Danach im Browser `DATALORE_PUBLIC_URL` öffnen, Admin-Konto anlegen und den **Lizenzschlüssel** im Admin-Panel unter „License“ eintragen. Neuer Rechner mit alten Daten: vorher auf dem alten `./backup.sh`, auf dem neuen nach dem ersten Start `./restore.sh <db.sql.gz> <storage.tgz>`.

## Mac mit Apple Silicon (M4)

- **Docker**: Docker Desktop (verlangt bei der Installation einmal das Administratorpasswort) oder OrbStack. Beide stellen `/var/run/docker.sock` bereit; `DOCKER_SOCK` bleibt auf dem Standard. Podman ist nur für den Image-Bau erprobt (`DOCKER=podman ./build.sh`), nicht für den Betrieb des Datalore-Servers.
- **Architektur**: Ein Linux-Container läuft auf der CPU-Architektur der VM — auf dem M4 ist das arm64. Ein amd64-Image liefe nur emuliert (langsam, fehleranfällig). Darum gibt es das Image in **beiden** Architekturen; `imgstore pull` wählt die passende. Die Basis-Images von JetBrains und alle Teile (ASTAP-CLI für aarch64, Siril aus Ubuntu) gibt es für beide.
- **Pfade**: `VARPHOT_DATA_DIR` und `EXCHANGE_DIR` müssen in einem Ordner liegen, den Docker Desktop freigibt (Standard: `/Users`).
- **GPU**: Container auf dem Mac sehen die Apple-GPU nicht. varphot rechnet auf der CPU (astropy, photutils); die GPU brächte nichts. `ENABLE_GPU_AGENT=1` gibt es nur für Linux mit NVIDIA Container Toolkit.
- **Fernzugriff** (Tablet unterwegs): Datalore ist eine Webseite. Mac zu Hause laufen lassen, `DATALORE_BIND` auf die WireGuard-/Tailscale-Adresse des Macs (oder `0.0.0.0` im Heimnetz mit WireGuard davor) und `DATALORE_PUBLIC_URL` auf dieselbe Adresse setzen. Nie ohne VPN ins offene Internet stellen (siehe Docker-Socket).

## Docker-Socket — was das heißt und wie es entkoppelt ist

Datalore startet jede Notebook-Berechnung als eigenen Agent-Container. Dazu bekommt der Server den **Docker-Socket** des Hosts (`/var/run/docker.sock`): ein Dateianschluss, über den er dem Docker-Daemon Befehle gibt. Zwei Folgen:

1. **Der Server hat damit Vollzugriff auf Docker des Hosts** (praktisch Root). Datalore gehört hinter VPN/Heimnetz, nicht ins offene Netz; Zugang nur für Konten, denen man traut. Das war auf panama schon so.
2. **Pfade in `agents-config.yaml` gelten für den Daemon, nicht für den Server-Container.** Ein Ordner `/home/apos/...` muss auf dem Host existieren, auf dem der Daemon läuft (beim Mac: in der Docker-VM, freigegeben aus `/Users`). Auf panama waren solche Pfade fest eingetragen — das machte den Umzug unmöglich.

Entkopplung vom Betriebssystem: der Socket-Pfad ist die Variable `DOCKER_SOCK` (Standard `/var/run/docker.sock`; Docker rootless: `/run/user/<uid>/docker.sock`), alle Ordner sind Variablen in `.env`, `render-config.sh` setzt sie in `agents-config.yaml` ein, die Sterndatenbank liegt in einem benannten Volume, das auf jedem Host gleich heißt. Nicht umgesetzt (ungetestet, bei Bedarf nachrüstbar): ein Socket-Proxy (z. B. `tecnativa/docker-socket-proxy`), der nur die vom Server gebrauchten Docker-Befehle durchlässt.

## Geheimnisse — was, wo

| Geheimnis | Wo es herkommt | Wo es liegt | Ins Image/Archiv/Git? |
|---|---|---|---|
| **Datalore-Lizenzschlüssel** | JetBrains Account → Organisation (jederzeit neu abrufbar) | im Admin-Panel von Datalore (steckt dann in der Datenbank); Kopie im Passwortmanager | nein |
| **DB_PASSWORD** | `bootstrap.sh` erzeugt es | `deploy/datalore/.env` (chmod 600); Kopie im Passwortmanager | nein (`.env` ist in `.gitignore`, nicht im Image-Kontext) |
| **Datalore-Admin-Passwort** | beim ersten Start gewählt | Passwortmanager | nein |
| API-Schlüssel der KI-Backends | je Nutzer, `observer.json`/Umgebung | nur im Datenordner/Passwortmanager (Regel: nie in Datalore, nie ins Repo) | nein |

**Empfehlung:** die KeePass-Datenbank im Nextcloud-Ordner (läuft auf Mac, Linux, iPad) für den Lizenzschlüssel (Notiz oder Anhang) und `.env` (Anhang). Apple-Passwörter (iCloud-Schlüsselbund) eignen sich für das Datalore-Admin-Passwort — Autofill auf dem Tablet —, aber nicht für eine 2-KB-Lizenz oder eine ganze `.env`. Verloren ist ohnehin wenig: der Lizenzschlüssel ist beim JetBrains Account abrufbar, und `restore.sh` braucht kein altes `DB_PASSWORD` (der Dump ist besitzerfrei). Das Image enthält keinen Schlüssel und kein Passwort; es darf daher im Nextcloud-Ordner liegen.

## Lizenz (Datalore On-Premises, Stand 2026-11-15)

Gelesen: Lizenzvereinbarung Version 3.3 (jetbrains.com/legal/docs/datalore/datalore_onprem) und die Hilfeseite „Manage licenses“.

- **Gerechnet wird nach Nutzern**, nicht nach Installationen: der Schlüssel enthält Organisation und maximale Nutzerzahl. Eine Obergrenze für Installationen, Server oder Instanzen steht **nicht** im Text; ebenso wenig, ob er an einen Host gebunden ist. Mehrere eigene Installationen (panama, Mac) sind also nicht ausdrücklich erlaubt und nicht verboten.
- **Sicherungskopien** zu Archivzwecken sind erlaubt (3b iv). **Verboten** sind Änderungen/abgeleitete Werke ohne Erlaubnis (3d ii) sowie Weitergabe an Dritte (3d vi). Das Agent-Image ist eine **von JetBrains dokumentierte Anpassung** (Hilfe „Customize or update environment“: eigenes Image `FROM jetbrains/datalore-agent`), enthält aber JetBrains-Schichten. Darum: nur für die eigenen Rechner, nie öffentlich, nie an Dritte (auch nicht in einer öffentlichen Registry).
- **Empfehlung**: eine kurze Rückfrage an datalore@jetbrains.com — „Darf der Schlüssel (n Nutzer) auf zwei eigenen Rechnern, nicht gleichzeitig durch verschiedene Personen, installiert sein?“ Der Text dafür steht in KONZEPT.md §17.6. Bis zur Antwort: einen Server produktiv betreiben, den anderen nur zum Test/als Ausweichrechner.

## Betrieb

```bash
./render-config.sh && docker compose up -d --force-recreate datalore   # nach Änderung von .env
./astap-db.sh                                                            # Sterndatenbank (erneut) laden; überspringt Vorhandenes
./build.sh                                                               # Image neu bauen (nach Änderung an requirements.txt/ASTAP/Siril)
../imgstore/imgstore push varphot-datalore-agent:2026.4.1-py312 -p varphot   # Image im Nextcloud-Store ablegen (je Architektur auf dem passenden Rechner)
```

Entwicklung ohne Neubau: `VARPHOT_REPO_DIR` auf einen Git-Klon setzen; er wird über die Momentaufnahme im Image eingehängt. Ohne Wert gilt der Stand, mit dem das Image gebaut wurde (`docker inspect`: Label `org.opencontainers.image.revision`).

ASTAP: SourceForge liefert immer die neueste CLI-Version; `build.sh` zeigt die Prüfsumme der geladenen Zip-Datei. `ASTAP_SHA256=<Summe> ./build.sh` erzwingt eine bestimmte Version.
