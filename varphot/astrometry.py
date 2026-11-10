"""Plate Solving mit ASTAP — liefert eine WCS, ohne die FITS-Datei zu veraendern.

ASTAP schreibt mit ``-wcs`` NICHT in den FITS-Header, sondern legt neben das Bild eine
Textdatei ``<bild>.wcs`` (FITS-Header als 80-Zeichen-Karten). Diese wird hier gelesen.
Das Originalbild bleibt unveraendert (kein ``-update``).
"""
from __future__ import annotations

import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS

ASTAP_DEFAULT = "/Applications/ASTAP.app/Contents/MacOS/astap"


@dataclass
class SolveResult:
    """Ergebnis von :func:`solve_image`."""
    wcs: WCS | None
    source: str                 # "ASTAP", "header" oder "keine"
    log: str = ""               # ASTAP-Ausgabe (gekuerzt)
    header: fits.Header | None = None
    notes: list[str] = field(default_factory=list)


def _wcs_from_header(hdr: fits.Header) -> WCS | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        w = WCS(hdr)
    return w if w.has_celestial else None


def read_wcs_sidecar(path: Path) -> fits.Header:
    """Liest eine ASTAP-``.wcs``-Datei (Karten ohne Zeilenumbruch) als Header."""
    return fits.Header.fromstring(path.read_bytes().decode("ascii", "replace"))


def solve_image(image: str | Path, astap: str = ASTAP_DEFAULT, radius_deg: float = 10.0,
                fov_deg: float | None = None, timeout: int = 300) -> SolveResult:
    """Loest ``image`` mit ASTAP; faellt bei Misserfolg auf eine WCS im FITS-Header zurueck.

    ``radius_deg``: Suchradius um die Naeherungsposition aus dem Header (RA/DEC bzw. OBJCTRA).
    ``fov_deg``: Feldhoehe in Grad; ``None`` = ASTAP bestimmt sie aus dem Header.
    Bei gescheiterter Loesung wird NIE eine WCS erfunden: entweder Header-WCS (mit Hinweis) oder
    ``wcs=None``.
    """
    image = Path(image)
    notes: list[str] = []
    with fits.open(image) as hdul:
        img_hdr = hdul[0].header.copy()

    if not Path(astap).exists():
        notes.append(f"ASTAP nicht gefunden: {astap}")
        w = _wcs_from_header(img_hdr)
        return SolveResult(w, "header" if w else "keine", "", img_hdr, notes)

    sidecar = image.with_suffix(".wcs")
    sidecar.unlink(missing_ok=True)          # keine alte Loesung mit neuer verwechseln
    cmd = [astap, "-f", str(image), "-r", str(radius_deg), "-wcs"]
    if fov_deg:
        cmd += ["-fov", str(fov_deg)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log = (run.stdout + run.stderr).strip()

    if sidecar.exists() and "Solution found" in log:
        hdr = read_wcs_sidecar(sidecar)
        w = _wcs_from_header(hdr)
        if w is not None:
            return SolveResult(w, "ASTAP", log[-800:], hdr, notes)
        notes.append("ASTAP-.wcs ohne gueltige Himmelskoordinaten")

    notes.append("ASTAP: keine Loesung")
    w = _wcs_from_header(img_hdr)
    if w is not None:
        notes.append("Fallback: WCS aus dem FITS-Header")
        return SolveResult(w, "header", log[-800:], img_hdr, notes)
    return SolveResult(None, "keine", log[-800:], img_hdr, notes)


def gnomonic(ra, dec, ra0, dec0, min_cos: float = 0.1):
    """Gnomonische Projektion (Grad) um (ra0, dec0); x waechst nach Osten links (x = -xi).

    Punkte auf der abgewandten Himmelshalbkugel (Abstand > ~84 Grad, ``cos c <= min_cos``)
    haben keine gueltige Abbildung und liefern ``(nan, nan)`` — sonst wuerden sie gespiegelt
    ins Bild fallen (Fehler in v0.2.0: Orion erschien im Feld von M16).
    """
    import numpy as np
    r0, d0 = np.radians(ra0), np.radians(dec0)
    r, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    dr = (r - r0 + np.pi) % (2 * np.pi) - np.pi
    cos_c = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(dr)
    ok = cos_c > min_cos
    with np.errstate(divide="ignore", invalid="ignore"):
        x = -np.degrees(np.cos(d) * np.sin(dr) / cos_c)
        y = np.degrees((np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(dr)) / cos_c)
    x, y = np.where(ok, x, np.nan), np.where(ok, y, np.nan)
    return (float(x), float(y)) if x.ndim == 0 else (x, y)
