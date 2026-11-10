"""Apertur- und PSF-Photometrie sowie differentielle Helligkeit."""
import warnings

import numpy as np
from astropy.nddata import NDData
from astropy.table import Table
from photutils.aperture import CircularAperture, CircularAnnulus, ApertureStats
from photutils.psf import EPSFBuilder, PSFPhotometry, extract_stars

from .config import CFG


def aperture_flux(img, xy, r_ap=None, r_in=None, r_out=None, cfg=None):
    """Gibt (flux_array, flux_err_array, bkg_array) zurück.

    xy: Liste von (x, y)-Tupeln.
    Warnung bei Peak > CFG['sat_adu'] (Sättigung / Nichtlinearität).
    """
    cfg = cfg or CFG
    r_ap = r_ap if r_ap is not None else cfg["ap_r"]
    r_in = r_in if r_in is not None else cfg["ap_r_in"]
    r_out = r_out if r_out is not None else cfg["ap_r_out"]

    ap = CircularAperture(xy, r=r_ap)
    an = CircularAnnulus(xy, r_in=r_in, r_out=r_out)
    sky = ApertureStats(img, an, sigma_clip=None)
    bkg = sky.median
    st = ApertureStats(img, ap, sigma_clip=None)    # Standard-Clipping wuerde helle Sternkerne abschneiden
    flux = st.sum - bkg * ap.area
    peak = st.max - bkg
    if np.any(peak > cfg["sat_adu"]):
        print(f"WARNUNG: Peak {float(np.max(peak)):.0f} ADU — Sättigung/Nichtlinearität prüfen")
    return flux, np.sqrt(np.abs(st.sum)), bkg


def build_psf(img, sources, cfg=None):
    """Empirische PSF (EPSF) aus nicht-gesättigten, isolierten Sternen aufbauen.

    Parameters
    ----------
    img : ndarray
        2-D-Frame in ADU (Hintergrund muss *nicht* subtrahiert sein).
    sources : astropy.table.Table
        Quelltabelle mit ``x_centroid``, ``y_centroid``, ``peak``.
        Typischerweise der Return-Wert von :func:`~varphot.detect`.
    cfg : dict, optional

    Returns
    -------
    epsf : photutils.psf.EPSFModel
        Kann direkt an :func:`psf_flux` übergeben werden.
    n_stars : int
        Anzahl der für den Aufbau verwendeten Sterne.
    """
    cfg = cfg or CFG
    stamp   = int(cfg.get("psf_stamp_size", 25))
    oversmp = int(cfg.get("psf_oversampling", 2))
    maxiter = int(cfg.get("psf_maxiters", 5))
    peak_lo = float(cfg.get("psf_peak_lo",  500))
    peak_hi = float(cfg.get("sat_adu", 50000)) * 0.6
    ny, nx  = img.shape
    edge    = stamp // 2 + 2

    good = sources[
        (sources["peak"] > peak_lo) &
        (sources["peak"] < peak_hi) &
        (sources["x_centroid"] > edge) &
        (sources["x_centroid"] < nx - edge) &
        (sources["y_centroid"] > edge) &
        (sources["y_centroid"] < ny - edge)
    ]
    if len(good) < 5:
        raise ValueError(
            f"Zu wenige PSF-Referenzsterne: {len(good)} (mindestens 5 nötig). "
            "PSF-Stamp-Größe verkleinern oder Bildqualität prüfen."
        )

    stars_tbl = Table({"x": good["x_centroid"], "y": good["y_centroid"]})
    nddata     = NDData(data=img.astype(float))
    stars      = extract_stars(nddata, stars_tbl, size=stamp)
    builder    = EPSFBuilder(oversampling=oversmp, maxiters=maxiter, progress_bar=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        epsf, _ = builder(stars)
    return epsf, len(good)


def psf_flux(img, xy, epsf, cfg=None):
    """PSF-Photometrie für bekannte Positionen (fokussiertes Seeing).

    Verwendet :class:`photutils.psf.PSFPhotometry` ohne eigene Quellensuche —
    es werden nur die übergebenen Positionen gefittet.

    Parameters
    ----------
    img : ndarray
        2-D-Frame in ADU.
    xy : list of (float, float)
        Positionen als ``[(x0, y0), (x1, y1), …]``.
    epsf : photutils.psf.EPSFModel
        Ausgabe von :func:`build_psf`.
    cfg : dict, optional

    Returns
    -------
    flux : ndarray
        Hintergrundkorrigierter Fluss je Stern.
    flux_err : ndarray
        Formaler Fit-Fehler (1-σ).
    bkg : ndarray
        Lokaler Hintergrundmedian je Stern.

    Notes
    -----
    Für *defokussierte* Sterne (FWHM > ~15 px) ist Aperturphotometrie besser
    geeignet; PSF-Fitting setzt eine stabile, fokussierte Abbildung voraus.
    """
    cfg       = cfg or CFG
    fwhm      = float(cfg.get("detect_fwhm", 4.5))
    fit_half  = max(5, int(fwhm * 2.5))
    fit_shape = 2 * fit_half + 1
    ap_r      = float(cfg.get("ap_r", 10))
    r_in      = float(cfg.get("ap_r_in",  18))
    r_out     = float(cfg.get("ap_r_out", 26))

    xs = np.asarray([p[0] for p in xy], dtype=float)
    ys = np.asarray([p[1] for p in xy], dtype=float)

    # Background per star via annulus — identical method to aperture_flux to keep
    # the flux scale consistent across both photometry modes.
    bkg = np.zeros(len(xy))
    for i, (x, y) in enumerate(zip(xs, ys)):
        an  = CircularAnnulus([(x, y)], r_in=r_in, r_out=r_out)
        sky = ApertureStats(img, an, sigma_clip=None)
        bkg[i] = float(np.atleast_1d(sky.median)[0])

    # Subtract global median sky before PSF fitting; individual residuals are small.
    img_sub = img.astype(float) - float(np.median(bkg))

    phot     = PSFPhotometry(epsf, fit_shape=(fit_shape, fit_shape),
                             aperture_radius=ap_r)
    init_tbl = Table({"x_init": xs, "y_init": ys})
    result   = phot(img_sub, init_params=init_tbl)

    flux     = np.asarray(result["flux_fit"],  dtype=float)
    flux_err = np.asarray(result["flux_err"],  dtype=float)
    return flux, flux_err, bkg


def diff_mag(f_t, f_c, V_c, f_k=None):
    """Differentielle Helligkeit via Ensemble-Nullpunkt.

    f_t: Fluss Ziel (Skalar)
    f_c: Fluss-Array der Comps
    V_c: Katalog-V-Array der Comps
    f_k: Fluss Check-Stern (optional)

    Rückgabe: (mag_ziel, mag_check_or_nan, zp_scatter)
    """
    zp = V_c + 2.5 * np.log10(f_c)
    zp_med = np.median(zp)
    zp_sd = np.std(zp, ddof=1)
    m_t = -2.5 * np.log10(f_t) + zp_med
    m_k = -2.5 * np.log10(f_k) + zp_med if f_k is not None else np.nan
    return m_t, m_k, zp_sd
