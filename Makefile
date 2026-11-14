.PHONY: test strip sync-datalore init-datalore install-hooks help

# Git-Hooks automatisch aktivieren: liest direkt aus tools/hooks/ — kein manueller Schritt nötig.
# Schreibt einmalig in .git/config; läuft bei jedem make-Aufruf (idempotent).
_ := $(shell git config core.hooksPath tools/hooks 2>/dev/null)

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

sync-datalore: strip    ## Notebook-Zellen zu Datalore synchronisieren (WireGuard muss verbunden sein)
	@$(PYTHON) tools/sync_datalore.py

init-datalore:          ## Einmalig: Datalore-Session einrichten (OAuth-Login)
	mkdir -p $(SESSION)
	cd $(SESSION) && $(DL_CLI) init $(DL_HOST)/notebook/$(DL_NB) --scope notebook_with_workspace_view
	@echo "Session gespeichert in $(SESSION)"

install-hooks:          ## Git-Hooks aktivieren (Makefile macht das automatisch; nur zur Kontrolle)
	@git config core.hooksPath tools/hooks
	@echo "✓ core.hooksPath = tools/hooks (git liest Hooks direkt aus tools/hooks/)"

help:                   ## Diese Hilfe anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
