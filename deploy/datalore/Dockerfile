# Agent-Image fuer Datalore (On-Premises) mit allem, was varphot braucht: Python-Umgebung, ASTAP (CLI), Siril (CLI), varphot-Stand.
# Autor: Axel Pospischil. Stand 2026-11 (KONZEPT.md §17).
#
# Warum: Das Image soll auf jedem Docker-Host (Linux amd64, Mac Apple Silicon arm64) ohne Zutaten vom Host laufen. Bisher kamen ASTAP-Binary,
# Sterndatenbank und Repo per Mount vom Host (panama). Jetzt: ASTAP und Siril im Image, Repo als Momentaufnahme im Image (ein Mount darueber ersetzt sie),
# die grosse Sterndatenbank in einem Docker-Volume (deploy/datalore/astap-db.sh), nicht im Image.
#
# Lizenz: Das Image baut auf ``jetbrains/datalore-agent`` auf; JetBrains beschreibt diesen Weg selbst (Hilfe „Customize or update environment“).
# Es enthaelt Schichten von JetBrains und darf deshalb nicht oeffentlich oder an Dritte weitergegeben werden (EULA Abschnitt 3d); fuer eigene Rechner ist es ein Archiv fuer die eigene Installation.
# Es enthaelt keine Geheimnisse (kein Lizenzschluessel, kein Passwort).
#
# KI-Kommandozeilen (Stand 2026-11-16, KONZEPT §11.15.4/§17): Claude Code (signiertes apt-Repository, Kanal stable) und Gemini CLI (npm, Node.js 22). Sie sind NUR installiert,
# keine Anmeldung und kein Schluessel im Image. Die Anmeldung legt der Nutzer einmal an (ai-login.sh) und sie liegt im Docker-Volume /auth (nicht im Image, nicht im Repo,
# nicht im Nextcloud-Ordner). Aktualisieren: Image neu bauen (update.sh); die Selbstaktualisierung der Programme ist im Container wirkungslos und aus.
#
# Bauen:  deploy/datalore/build.sh   (Build-Kontext ist die Repo-Wurzel, siehe .dockerignore)
# Pruefen: docker run --rm --entrypoint sh <image> -c 'astap_cli -h; siril-cli --version; claude --version; gemini --version; python -c "import varphot"'
ARG DATALORE_VERSION=2026.4.1
FROM jetbrains/datalore-agent:${DATALORE_VERSION}

ARG DATALORE_VERSION
ARG NAME=photometrie
ARG TARGETARCH
# Optional: erwartete Pruefsumme der ASTAP-Zip-Datei (SourceForge liefert immer die neueste Version; ohne Wert wird die Summe nur ausgegeben)
ARG ASTAP_SHA256=""
ARG GIT_COMMIT=unbekannt
# Kanal des Claude-Code-Repositories: stable (etwa eine Woche alt, ohne Versionen mit grossen Fehlern) oder latest
ARG CLAUDE_CHANNEL=stable
ARG NODE_MAJOR=22
ARG BUILD_DATE=unbekannt
LABEL org.opencontainers.image.title="varphot Datalore agent" \
      org.opencontainers.image.description="Datalore agent with Python 3.12 venv, ASTAP CLI, Siril CLI and a varphot snapshot" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.base.name="jetbrains/datalore-agent:${DATALORE_VERSION}"

USER root
# siril zieht GTK3 und systemd-Pakete nach (ohne Auswirkung im Container, kein init); der Stub „systemctl“ der Basis wird dabei ersetzt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3.12-venv siril curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Claude Code (apt-Repository von Anthropic, Schluessel-Fingerabdruck wird geprueft) und Node.js (NodeSource) fuer die Gemini CLI.
# Beides erscheint unter /usr/bin bzw. /usr/lib/node_modules und ist damit fuer jeden Prozess im Container im PATH (Datalore startet die Kernel nicht ueber eine Login-Shell).
RUN apt-get update && apt-get install -y --no-install-recommends gnupg \
 && install -d -m 0755 /etc/apt/keyrings \
 && curl -fsSL --retry 3 https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc \
 && gpg --show-keys --with-colons /etc/apt/keyrings/claude-code.asc | grep -q '^fpr:::::::::31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE:' \
 && echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/${CLAUDE_CHANNEL} ${CLAUDE_CHANNEL} main" > /etc/apt/sources.list.d/claude-code.list \
 && curl -fsSL --retry 3 https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
 && apt-get update && apt-get install -y --no-install-recommends claude-code nodejs \
 && npm install -g @google/gemini-cli@latest && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/* \
 && claude --version && gemini --version

# ASTAP-Kommandozeile (statisch, kein Display): Zip je Architektur von SourceForge (Autor Han Kleijn, MPL 2.0)
RUN case "${TARGETARCH}" in amd64) A=amd64 ;; arm64) A=aarch64 ;; *) echo "Architektur ${TARGETARCH} nicht unterstuetzt" >&2; exit 1 ;; esac \
 && curl -fsSL --retry 3 -o /tmp/astap.zip "https://sourceforge.net/projects/astap-program/files/linux_installer/astap_command-line_version_Linux_${A}.zip/download" \
 && { [ -z "${ASTAP_SHA256}" ] || echo "${ASTAP_SHA256}  /tmp/astap.zip" | sha256sum -c -; } \
 && echo "ASTAP-Zip (${A}) sha256: $(sha256sum /tmp/astap.zip | cut -d' ' -f1)" \
 && unzip -o -q /tmp/astap.zip -d /tmp/astap \
 && install -m 755 "$(find /tmp/astap -type f -name 'astap_cli*' | head -n 1)" /usr/local/bin/astap_cli \
 && rm -rf /tmp/astap /tmp/astap.zip \
 && { /usr/local/bin/astap_cli -h > /tmp/astap_help.txt 2>&1; [ $? -lt 126 ]; } && head -n 2 /tmp/astap_help.txt && rm /tmp/astap_help.txt
COPY deploy/datalore/astap-wrapper.sh /usr/local/bin/astap
RUN chmod 755 /usr/local/bin/astap

USER datalore
# Python-Umgebung (venv unter /opt/python/envs, wie sie Datalore fuer eigene Environments vorsieht)
COPY deploy/datalore/requirements.agent.txt /tmp/requirements_project.txt
RUN /usr/bin/python3.12 -m venv /opt/python/envs/${NAME} \
 && /opt/python/envs/${NAME}/bin/python -m pip install --no-cache-dir --upgrade pip \
 && /opt/python/envs/${NAME}/bin/python -m pip install --no-cache-dir -r /tmp/requirements_project.txt \
 && /opt/python/envs/${NAME}/bin/python -m ipykernel install --sys-prefix --name python3 \
 && /opt/python/envs/${NAME}/bin/python -m pip freeze > /opt/python/envs/${NAME}/freeze.txt

# varphot als Momentaufnahme unter /work/PHOTOMETRIE_PY; ein Mount des Git-Klons an dieser Stelle ersetzt sie (Entwicklung ohne Neubau).
# Der Datenordner heisst relativ dazu /work/PHOTOMETRIE_PY_DATA (varphot.observer.data_dir) und wird immer gemountet.
USER root
RUN mkdir -p /work/PHOTOMETRIE_PY /work/PHOTOMETRIE_PY_DATA /exchange /opt/astap_db /auth/claude /auth/gemini \
 && chown -R datalore:datalore /work /exchange /auth \
 && ln -s /auth/gemini /home/datalore/.gemini && chown -h datalore:datalore /home/datalore/.gemini
COPY --chown=datalore:datalore varphot /work/PHOTOMETRIE_PY/varphot
COPY --chown=datalore:datalore tools /work/PHOTOMETRIE_PY/tools
COPY --chown=datalore:datalore data /work/PHOTOMETRIE_PY/data
COPY --chown=datalore:datalore pyproject.toml /work/PHOTOMETRIE_PY/pyproject.toml
USER datalore
RUN echo /work/PHOTOMETRIE_PY > /opt/python/envs/${NAME}/lib/python3.12/site-packages/project_repo.pth \
 && /opt/datalore/build_code_insight_data.sh /opt/python/envs/${NAME}
ENV ASTAP_DB=/opt/astap_db
# Anmeldungen der KI-Kommandozeilen liegen im Volume /auth (ai-login.sh); Claude Code legt Konfiguration und Anmeldung unter CLAUDE_CONFIG_DIR ab, die Gemini CLI unter ~/.gemini (Verweis auf /auth/gemini).
ENV CLAUDE_CONFIG_DIR=/auth/claude \
    DISABLE_AUTOUPDATER=1
