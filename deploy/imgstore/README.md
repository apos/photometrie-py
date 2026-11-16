# imgstore — Image-„Registry“ als Ordner im Nextcloud-Sync

Ein einziges Bash-Skript (`imgstore`), das Docker-Images als `docker save | zstd` in einen Ordner legt und von dort wieder in Docker lädt. Kein Server, kein Konto, kein Kontingent. Generisch: ein Ordner nimmt beliebig viele Projekte auf; nichts hier hängt an varphot.

## Warum nicht Docker Hub, GHCR oder eine eigene Registry?

- Docker Hub/GHCR: Kontingent und Konto; das Agent-Image enthält Schichten von JetBrains (Datalore-EULA 3d: keine Weitergabe an Dritte) — in einem öffentlichen oder fremden Dienst nicht ratsam.
- Eigene Registry (`registry:2`) mit Nextcloud-Ordner als Speicher: **ausgeschlossen** — Registry-Speicher ist ein Geflecht aus vielen Dateien mit Referenzzählung; Nextcloud-Sync auf mehreren Rechnern kann es zerstören.
- Ordner mit je einer Archivdatei pro Image und Architektur: ein Sync kopiert nur ganze Dateien; Prüfsumme und `.part`-Umbenennung verhindern halbe Dateien.

Nachteil: kein Schichten-Teilen. Jede Architektur ist ein vollständiges Archiv (Agent-Image: 6,5 GB unkomprimiert, 1,8 GB bei zstd-Stufe 10; Ablegen 1–8 min, Laden etwa 30 s). Wer das stört, setzt eine private Registry auf — `imgstore` bleibt daneben nutzbar.

## Einrichten (je Rechner einmal)

```bash
brew install zstd            # macOS;   Linux: apt install zstd
mkdir -p ~/.config/imgstore && echo "$HOME/Nextcloud/WORKSPACE/DOCKER_REGISTRY" > ~/.config/imgstore/dir
# oder je Aufruf:  export IMGSTORE_DIR=/Pfad/zum/Ordner
```

## Benutzen

```bash
imgstore push varphot-datalore-agent:2026.4.1-py312 -p varphot     # lokales Image ablegen (Architektur wird erkannt)
imgstore list                                                       # alles im Store
imgstore pull varphot-datalore-agent:2026.4.1-py312 -p varphot      # pruefen + laden (Architektur dieses Rechners)
imgstore verify varphot-datalore-agent:2026.4.1-py312 -p varphot    # nur Pruefsumme
```

Ablage: `<Store>/<projekt>/<name>/<tag>/<arch>.tar.zst` mit `<arch>.sha256` und `<arch>.meta`. Je Architektur baut man auf einem passenden Rechner (amd64 auf panama, arm64 auf dem Mac) und legt dort ab; beide Dateien liegen nebeneinander, `pull` wählt automatisch. `-a arm64` erzwingt eine Architektur, `DOCKER=podman` nimmt Podman, `ZSTD_LEVEL=3` komprimiert schneller, `19` kleiner.

Der Sync kann Wochen später noch eine halbe Datei haben: `pull` prüft die SHA-256-Summe vor dem Laden und bricht bei Abweichung ab. Es wird nie etwas gelöscht; alte Tags räumt man von Hand auf.

## Tests

`tests/test_imgstore.py` (Attrappe für `docker`, braucht nur `zstd` und `bash`).
