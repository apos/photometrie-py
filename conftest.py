"""Root-conftest.py: Git-Hooks beim ersten pytest-Aufruf aktivieren."""
import subprocess
from pathlib import Path

subprocess.run(
    ["git", "config", "core.hooksPath", "tools/hooks"],
    cwd=Path(__file__).parent,
    capture_output=True,
)
