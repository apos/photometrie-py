.PHONY: test strip sync-datalore init-datalore install-hooks help

PYTHON   := uv run python
PYTEST   := uv run pytest
DL_CLI   ?= $(HOME)/.claude/plugins/cache/jetbrains-datalore/datalore-skills/2026.4/skills/datalore-notebook/scripts/datalore
DL_HOST  := $(shell python3 -c "import json; print(json.load(open('datalore.json'))['host'])" 2>/dev/null)
DL_NB    := $(shell python3 -c "import json; print(json.load(open('datalore.json'))['notebook_id'])" 2>/dev/null)
SESSION  := $(HOME)/.cache/varphot-datalore

test:                   ## Tests ausführen
	$(PYTEST) tests/ -q

strip:                  ## Notebook-Outputs entfernen (vor git commit)
	uv run nbstripout notebooks/*.ipynb

sync-datalore: strip    ## Notebook-Zellen zu Datalore synchronisieren (Tunnel muss laufen)
	$(PYTHON) tools/sync_datalore.py

init-datalore:          ## Einmalig: Datalore-Session einrichten (OAuth-Login)
	mkdir -p $(SESSION)
	$(DL_CLI) init $(DL_HOST)/notebook/$(DL_NB) --scope notebook_api --cwd $(SESSION) || \
	    $(DL_CLI) init $(DL_HOST)/notebook/$(DL_NB) --scope notebook_with_workspace_view
	@echo "Session gespeichert in $(SESSION)"

install-hooks:          ## Git-Hooks installieren (einmalig nach git clone)
	cp tools/hooks/post-merge .git/hooks/post-merge
	chmod +x .git/hooks/post-merge
	@echo "post-merge Hook installiert — Datalore-Sync läuft automatisch nach git pull/merge"

help:                   ## Diese Hilfe anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
