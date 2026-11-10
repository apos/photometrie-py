"""Quellendetektion auf einem einzelnen Frame."""
import numpy as np
from astropy.stats import sigma_clipped_stats
from photutils.background import Background2D, MedianBackground
from photutils.detection import DAOStarFinder


def detect(img, fwhm=4.5, nsigma=8.0, background="global", box_size=128):
    """Gibt (sources, median, std) zurück; sources ist None wenn nichts gefunden.

    ``background="global"``: ein Himmelswert für das ganze Bild (Standard, schnell; gut für
    leere Sternfelder).  ``background="2d"``: ortsabhängiger Hintergrund (``Background2D``,
    ``box_size`` px) — nötig bei Nebeln und Gradienten, sonst erkennt der Finder Nebelknoten.
    ``median``/``std`` sind in beiden Fällen Median bzw. Rauschen des Hintergrunds.
    """
    img = np.asarray(img, dtype=float)
    if background == "2d":
        bkg = Background2D(img, box_size=box_size, filter_size=3,
                           bkg_estimator=MedianBackground())
        sub = img - bkg.background
        _, _, std = sigma_clipped_stats(sub, sigma=3.0)
        med = float(np.median(bkg.background))
        rms_map = bkg.background_rms
    elif background == "global":
        rms_map = None
        _, med, std = sigma_clipped_stats(img, sigma=3.0)
        sub = img - med
    else:
        raise ValueError(f"background muss 'global' oder '2d' sein, nicht {background!r}")
    finder = DAOStarFinder(fwhm=fwhm, threshold=nsigma * std)
    src = finder(sub)
    if src is not None and rms_map is not None:
        # Nebel/Textur: Quelle nur behalten, wenn ihr Peak auch über dem LOKALEN Rauschen
        # (Background2D-RMS um die Position) um nsigma liegt — sonst Nebelknoten.
        xi = np.clip(np.round(np.asarray(src["x_centroid"])).astype(int), 0, img.shape[1] - 1)
        yi = np.clip(np.round(np.asarray(src["y_centroid"])).astype(int), 0, img.shape[0] - 1)
        keep = np.asarray(src["peak"]) >= nsigma * rms_map[yi, xi]
        src = src[keep] if keep.any() else None
    return src, med, std
