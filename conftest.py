"""Root-conftest.py: Git-Hooks beim ersten pytest-Aufruf aktivieren."""
import subprocess
from pathlib import Path

subprocess.run(
    ["git", "config", "core.hooksPath", "tools/hooks"],
    cwd=Path(__file__).parent,
    capture_output=True,
)


import pytest


@pytest.fixture(autouse=True)
def _isolate_last_session_pointer(tmp_path_factory, monkeypatch):
    """Tests duerfen den echten Zeiger ``last_session.json`` im Datenordner nicht ueberschreiben (am 2026-11-14 zeigte er auf einen geloeschten pytest-Ordner)."""
    from varphot import session
    p = tmp_path_factory.mktemp("pointer") / "last_session.json"
    monkeypatch.setattr(session, "_pointer_file", lambda: p)
