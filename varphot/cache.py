"""Zell-Cache-Hilfsfunktion für Jupyter-Notebooks.

Typische Verwendung am Anfang einer teuren Schrittzelle::

    _SKIP = skip_if_fresh(OUT, IN1, "dir/*.fits")
    if _SKIP:
        pass   # nächste Zelle einfach nicht ausführen
    else:
        # teure Berechnung …
"""
from __future__ import annotations

import glob
from pathlib import Path


def skip_if_fresh(output: str | Path, *inputs: str | Path, verbose: bool = True) -> bool:
    """True → *output* existiert und ist neuer als alle *inputs* → Schritt überspringen.

    *inputs* dürfen Glob-Muster enthalten (z. B. ``"cal/*.fits"``).
    Wenn ein Glob-Muster keine Treffer liefert, gilt die zugehörige Datei als
    "fehlt" → Return False (Schritt wird neu ausgeführt).

    Rückgabe False bedeutet: Schritt muss (neu) ausgeführt werden.
    """
    out = Path(output)
    if not out.exists():
        return False

    out_mtime = out.stat().st_mtime

    for pattern in inputs:
        matches = glob.glob(str(pattern))
        if not matches:
            # Muster ohne Treffer → Input fehlt oder wurde noch nicht erzeugt
            return False
        for p in matches:
            fp = Path(p)
            if not fp.exists():
                return False
            if fp.stat().st_mtime > out_mtime:
                return False   # Input ist neuer → neu berechnen

    if verbose:
        print(f"✓ {out.name} ist aktuell — Schritt übersprungen")
    return True
