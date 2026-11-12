#!/usr/bin/env python3
"""Notebook-Zellen aus lokalen .ipynb-Dateien in Datalore synchronisieren.

Jedes Notebook mit einer *_dl_ids.json-Datei wird Zelle für Zelle aktualisiert.
Wenn Datalore nicht erreichbar ist (Tunnel down), wird übersprungen (exit 0).

Einmaliges Setup:
    make init-datalore   # OAuth-Login, speichert Session in ~/.cache/varphot-datalore/

Aufruf:
    python tools/sync_datalore.py                      # alle Notebooks
    python tools/sync_datalore.py notebooks/01_*.ipynb # bestimmtes Notebook
"""
from __future__ import annotations
import json, os, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG  = json.loads((ROOT / "datalore.json").read_text())

DL_CLI = Path(os.environ.get(
    "DATALORE_CLI",
    Path.home() / ".claude/plugins/cache/jetbrains-datalore/datalore-skills/2026.4/skills/datalore-notebook/scripts/datalore",
))
SESSION_DIR = Path(CFG.get("session_dir", "~/.cache/varphot-datalore")).expanduser()


def _reachable(host: str, timeout: float = 3.0) -> bool:
    try:
        urllib.request.urlopen(f"{host}/api/agent/v1/version", timeout=timeout)
        return True
    except Exception:
        return False


def _session_ok() -> bool:
    return (SESSION_DIR / ".datalore-session").exists()


def _cli(notebook_id: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(DL_CLI), "--json", "notebook", "--notebook-id", notebook_id, *args], capture_output=True, text=True, cwd=SESSION_DIR, check=False)


def _remote_cells(notebook_id: str, first_id: str) -> dict[str, dict] | None:
    """Zellen des Worksheet-Tabs, der ``first_id`` enthält (Typ und Quelltext je Zell-ID); ``None`` wenn kein Tab passt."""
    for ws in range(12):
        r = _cli(notebook_id, "cells", "--full", "--worksheet-index", str(ws))
        if r.returncode:
            return None
        data = json.loads(r.stdout)
        cells = data if isinstance(data, list) else data.get("cells", [])
        if any(c["cellId"] == first_id for c in cells):
            return {c["cellId"]: c for c in cells}
    return None


def _sync_notebook(nb_path: Path, dl_ids: list[str], notebook_id: str) -> tuple[int, int, int]:
    """Synchronisiert eine Notebook-Datei; gibt (aktualisiert, Fehler, unveraendert) zurück.

    Nur geänderte Zellen werden geschrieben. Wechselt der Zelltyp (Markdown ↔ Code), legt der Sync die Zelle in Datalore neu an und trägt die neue ID in ``*_dl_ids.json`` ein,
    weil ``cell edit`` den Typ nicht ändert.
    """
    nb    = json.loads(nb_path.read_text(encoding="utf-8"))
    cells = nb["cells"]
    if len(cells) != len(dl_ids):
        print(f"  ⚠ {nb_path.name}: {len(cells)} Zellen ≠ {len(dl_ids)} DL-IDs — übersprungen")
        return 0, 0, 0
    remote = _remote_cells(notebook_id, dl_ids[0]) or {}
    ok = fail = same = 0
    ids_changed = False
    for i, (cell, dl_id) in enumerate(zip(cells, dl_ids)):
        src, ctype = "".join(cell["source"]), cell["cell_type"].upper()
        cur = remote.get(dl_id)
        if cur is not None and cur["cellType"] == ctype and cur["source"] == src:
            same += 1
            continue
        if cur is not None and cur["cellType"] != ctype:
            r = _cli(notebook_id, "cell", "create", "--type", ctype, "--before", dl_id, "--source", src, *(["--run", "--wait"] if ctype == "CODE" else []))
            if r.returncode == 0:
                new = json.loads(r.stdout)
                new_id = new.get("cellId") or new["cell"]["cellId"]
                _cli(notebook_id, "cell", "delete", dl_id)
                dl_ids[i], ids_changed = new_id, True
                ok += 1
                continue
        else:
            r = _cli(notebook_id, "cell", "edit", dl_id, "--source", src, "--wait")
            if r.returncode == 0:
                ok += 1
                continue
        fail += 1
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        print(f"  ✗ {dl_id}: {msg[-1][:100] if msg else 'unbekannter Fehler'}")
    if ids_changed:
        nb_path.with_name(nb_path.stem + "_dl_ids.json").write_text(json.dumps(dl_ids, indent=2) + "\n")
    return ok, fail, same


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    host        = CFG["host"]
    notebook_id = CFG["notebook_id"]

    if not _reachable(host):
        print(f"ℹ Datalore nicht erreichbar ({host}) — Sync übersprungen (Tunnel starten: ssh -N -L 18080:127.0.0.1:8080 panama-wg)")
        return 0

    if not _session_ok():
        print(f"⚠ Keine Datalore-Session in {SESSION_DIR}")
        print("  Einmalig ausführen:  make init-datalore")
        return 1

    nb_paths = [Path(p) for p in argv] if argv else sorted(ROOT.glob("notebooks/*.ipynb"))

    total_ok = total_fail = 0
    for nb_path in nb_paths:
        ids_path = nb_path.with_name(nb_path.stem + "_dl_ids.json")
        if not ids_path.exists():
            continue
        dl_ids = json.loads(ids_path.read_text())
        print(f"→ {nb_path.name} ({len(dl_ids)} Zellen) …")
        ok, fail, same = _sync_notebook(nb_path, dl_ids, notebook_id)
        total_ok += ok
        total_fail += fail
        status = "✓" if fail == 0 else "⚠"
        print(f"  {status} {ok} aktualisiert, {same} unverändert{f', {fail} Fehler' if fail else ''}")

    if total_fail:
        print(f"\n⚠ {total_fail} Zellen konnten nicht synchronisiert werden")
        return 1
    print(f"\n✓ {total_ok} Zellen aktualisiert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
