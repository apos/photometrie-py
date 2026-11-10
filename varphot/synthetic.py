"""Synthetische Testdaten für die Demo und Unit-Tests.

Nur für Tests und die Demo — nicht in der echten Pipeline verwenden.
"""
import numpy as np
from astropy.wcs import WCS
from astropy.table import Table

from .config import CFG

_rng = np.random.default_rng(42)


def make_wcs(ra0=337.29, dec0=58.41, cfg=None):
    cfg = cfg or CFG
    w = WCS(naxis=2)
    w.wcs.crpix = [cfg["nx"] / 2, cfg["ny"] / 2]
    w.wcs.crval = [ra0, dec0]
    w.wcs.cdelt = [-cfg["scale_arcsec"] / 3600, cfg["scale_arcsec"] / 3600]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def make_catalog(w, n=60, cfg=None):
    cfg = cfg or CFG
    nx, ny = cfg["nx"], cfg["ny"]
    x = _rng.uniform(60, nx - 60, n)
    y = _rng.uniform(60, ny - 60, n)
    mag = np.sort(_rng.uniform(7.0, 13.0, n))
    bv = _rng.normal(0.8, 0.35, n).clip(0.0, 1.8)
    ra, dec = w.pixel_to_world_values(x, y)
    cat = Table({"id": np.arange(n), "ra": ra, "dec": dec, "V": mag, "BV": bv, "x": x, "y": y})
    cat["var"] = False
    cat["V"][0] = 4.0
    cat["x"][0], cat["y"][0] = nx * 0.5, ny * 0.5
    cat["ra"][0], cat["dec"][0] = w.pixel_to_world_values(cat["x"][0], cat["y"][0])
    cat["var"][0] = True
    cat["var"][7] = True
    return cat


def render_frame(cat, t, w, fwhm=4.5, zp=21.0, airmass_trend=0.0, cfg=None):
    """Rendert einen synthetischen Frame mit Poisson-Rauschen."""
    cfg = cfg or CFG
    nx, ny = cfg["nx"], cfg["ny"]
    P = cfg.get("period_days", 5.366)
    yy, xx = np.mgrid[0:ny, 0:nx]
    img = 800 + 30 * np.sin(xx / 400.0)
    for r in cat:
        v = r["V"]
        if r["id"] == 0:
            v = 3.75 + 0.35 * np.sin(2 * np.pi * t / P)
        if r["id"] == 7:
            v = r["V"] + 0.4 * np.sin(2 * np.pi * t / 0.9)
        v += airmass_trend
        flux = 10 ** (-0.4 * (v - zp))
        s = (22.0 if r["id"] == 0 else fwhm) / 2.355
        x0, y0 = r["x"], r["y"]
        x1, x2 = int(x0 - 6 * fwhm), int(x0 + 6 * fwhm)
        y1, y2 = int(y0 - 6 * fwhm), int(y0 + 6 * fwhm)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, nx), min(y2, ny)
        sub = np.exp(-((xx[y1:y2, x1:x2] - x0) ** 2 + (yy[y1:y2, x1:x2] - y0) ** 2) / (2 * s * s))
        img[y1:y2, x1:x2] += flux * sub / (2 * np.pi * s * s)
    img = _rng.poisson(img.clip(0)).astype(float) + _rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 65535)
