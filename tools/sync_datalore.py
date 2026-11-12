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
import json, os, shutil, subprocess, sys, urllib.request
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


def _sync_notebook(nb_path: Path, dl_ids: list[str], notebook_id: str) -> tuple[int, int]:
    """Synchronisiert eine Notebook-Datei; gibt (ok, fail) zurück."""
    nb    = json.loads(nb_path.read_text(encoding="utf-8"))
    cells = nb["cells"]
    if len(cells) != len(dl_ids):
        print(f"  ⚠ {nb_path.name}: {len(cells)} Zellen ≠ {len(dl_ids)} DL-IDs — übersprungen")
        return 0, 0
    ok = fail = 0
    for cell, dl_id in zip(cells, dl_ids):
        src = "".join(cell["source"])
        r = subprocess.run(
            [str(DL_CLI), "notebook", "--notebook-id", notebook_id,
             "cell", "edit", dl_id, "--wait"],
            input=src, text=True, capture_output=True, cwd=SESSION_DIR,
        )
        if r.returncode == 0:
            ok += 1
        else:
            fail += 1
            msg = (r.stderr or r.stdout or "").strip().splitlines()
            print(f"  ✗ {dl_id}: {msg[-1][:100] if msg else 'unbekannter Fehler'}")
    return ok, fail


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    host        = CFG["host"]
    notebook_id = CFG["notebook_id"]

    if not _reachable(host):
        print(f"ℹ Datalore nicht erreichbar ({host}) — Sync übersprungen (Tunnel starten: ssh -N -L 18080:127.0.0.1:8080 panama-wg)")
        return 0

    if not _session_ok():
        print(f"⚠ Keine Datalore-Session in {SESSION_DIR}")
        print(f"  Einmalig ausführen:  make init-datalore")
        return 1

    nb_paths = [Path(p) for p in argv] if argv else sorted(ROOT.glob("notebooks/*.ipynb"))

    total_ok = total_fail = 0
    for nb_path in nb_paths:
        ids_path = nb_path.with_name(nb_path.stem + "_dl_ids.json")
        if not ids_path.exists():
            continue
        dl_ids = json.loads(ids_path.read_text())
        print(f"→ {nb_path.name} ({len(dl_ids)} Zellen) …")
        ok, fail = _sync_notebook(nb_path, dl_ids, notebook_id)
        total_ok += ok
        total_fail += fail
        status = "✓" if fail == 0 else "⚠"
        print(f"  {status} {ok} ok{f', {fail} Fehler' if fail else ''}")

    if total_fail:
        print(f"\n⚠ {total_fail} Zellen konnten nicht synchronisiert werden")
        return 1
    print(f"\n✓ {total_ok} Zellen synchronisiert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
