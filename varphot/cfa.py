"""Kanaltrennung rohen/kalibrierten Bayer-Bildern (CFA) in R-, G- und B-Einzelbilder — mit korrekter WCS und Kopfzeile.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (KONZEPT.md §11.3/§11.4).

Warum: Die Photometrie (NB02) arbeitet mit Einkanalbildern je Farbe. Siril kann trennen (``seqsplit_cfa``: vier Bilder je Aufnahme, Praefix ``CFA_``; ``seqextract_Green``: Praefix ``Green_`` — Siril-Dokumentation),
die Dokumentation sagt aber nichts ueber die Reihenfolge der vier Dateien, die Behandlung der beiden Gruen-Ebenen und die Anpassung von WCS/Pixelskala. Diese Funktion macht es **deterministisch und testbar**:
jede Ebene ist ``img[r::2, c::2]`` nach dem Bayer-Muster, ``G`` ist das Mittel beider Gruen-Ebenen (Handbuch §5.4: „extract both green channels, average them together“), und die WCS wird fuer die halbe Aufloesung angepasst.
Siril bleibt fuer die Kalibrierung zustaendig (Dark/Flat im CFA-Bereich, ohne Debayern: ``tools/siril_calibrate_cfa.ssf``).

Quellen: AAVSO DSLR Observing Manual v1.4 §5.4 (gelesen); Siril-Befehlsreferenz (``seqsplit_cfa``, ``seqextract_Green``, ``calibrate -cfa -equalize_cfa``, ``convertraw`` — Syntax gelesen, nicht ausgefuehrt).
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS

from .camera import BAYER_OFFSETS, bayer_planes
from .plan import plane_wcs

_WCS_KEYS = ("CD1_1", "CD1_2", "CD2_1", "CD2_2", "PC1_1", "PC1_2", "PC2_1", "PC2_2", "CDELT1", "CDELT2", "CRPIX1", "CRPIX2")


def _plane_header(hdr: fits.Header, channel: str, offset: tuple[float, float]) -> fits.Header:
    h = hdr.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        w = WCS(hdr)
    if w.has_celestial:
        w2 = plane_wcs(w, offset)
        for k in _WCS_KEYS:
            h.remove(k, ignore_missing=True)
        h.update(w2.to_header())
    for k in ("BAYERPAT", "XBAYROFF", "YBAYROFF"):
        h.remove(k, ignore_missing=True)
    h["CFACHAN"] = (channel, "Bayer-Kanal (G = Mittel beider Gruen-Ebenen)")
    h["CFAOFFX"] = (offset[0], "Offset der Ebene im Rohbild [px], Spalte")
    h["CFAOFFY"] = (offset[1], "Offset der Ebene im Rohbild [px], Zeile")
    if "PIXSCALE" in h:
        h["PIXSCALE"] = float(h["PIXSCALE"]) * 2
    return h


def split_cfa_array(img, pattern: str = "RGGB", with_g12: bool = False) -> dict[str, tuple[np.ndarray, tuple[float, float]]]:
    """Ebenen mit ihren Offsets: ``{"R": (Array, (dx, dy)), "G": (Mittel G1/G2, (0,5, 0,5)), "B": …}``; mit ``with_g12`` zusaetzlich ``G1``/``G2``."""
    pl = bayer_planes(img, pattern)
    off = {k: (float(c), float(r)) for k, (r, c) in BAYER_OFFSETS[pattern.upper()].items()}
    out = {"R": (pl["R"], off["R"]), "G": (0.5 * (pl["G1"] + pl["G2"]), (0.5 * (off["G1"][0] + off["G2"][0]), 0.5 * (off["G1"][1] + off["G2"][1]))), "B": (pl["B"], off["B"])}
    if with_g12:
        out["G1"], out["G2"] = (pl["G1"], off["G1"]), (pl["G2"], off["G2"])
    return out


def split_cfa_fits(path, outdir, pattern: str | None = None, with_g12: bool = False) -> list[Path]:
    """Trennt ein CFA-FITS in ``<name>_R.fits``, ``<name>_G.fits``, ``<name>_B.fits`` (optional ``_G1``/``_G2``) in ``outdir``.

    ``pattern``: Bayer-Muster; ``None`` = aus der Kopfzeile (``BAYERPAT``), sonst ``RGGB``. Die Pixelwerte bleiben unveraendert (``float32``); WCS, Pixelskala (``PIXSCALE``, ×2) und Kopfzeile werden angepasst,
    ``CFACHAN``/``CFAOFFX``/``CFAOFFY`` dokumentieren die Herkunft. Rueckgabe: geschriebene Dateien. Grenze: gleicht keine Farbunterschiede der Ebenen aus (Flatfield im CFA-Bereich vorher, ``-equalize_cfa`` in Siril).
    Validierung: ``tests/test_cfa.py`` (Stern bleibt ueber die WCS auf demselben Himmelsort).
    """
    path, outdir = Path(path), Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if getattr(h, "data", None) is not None and h.data.ndim == 2)
        img, hdr = np.asarray(hdu.data, dtype=np.float32), hdu.header.copy()
    pat = (pattern or str(hdr.get("BAYERPAT", "RGGB"))).strip().upper() or "RGGB"
    stem = path.name
    for suf in (".fits.fz", ".fit.fz", ".fits", ".fit", ".fts"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
            break
    out = []
    for ch, (arr, off) in split_cfa_array(img, pat, with_g12).items():
        p = outdir / f"{stem}_{ch}.fits"
        fits.PrimaryHDU(arr.astype(np.float32), _plane_header(hdr, ch, off)).writeto(p, overwrite=True)
        out.append(p)
    return out
