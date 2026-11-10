"""Aperturphotometrie und differentielle Helligkeit."""
import numpy as np
from photutils.aperture import CircularAperture, CircularAnnulus, ApertureStats

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
    st = ApertureStats(img, ap)
    flux = st.sum - bkg * ap.area
    peak = st.max - bkg
    if np.any(peak > cfg["sat_adu"]):
        print(f"WARNUNG: Peak {float(np.max(peak)):.0f} ADU — Sättigung/Nichtlinearität prüfen")
    return flux, np.sqrt(np.abs(st.sum)), bkg


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
