"""Zeitstempel: Mitte der Belichtung (JD, UTC) und BJD_TDB.

BJD_TDB = Mittenzeit (TDB) + Lichtlaufzeit zum Schwerpunkt des Sonnensystems fuer die Richtung des Ziels.
Der Standort geht in die TDB-Umrechnung und die Lichtlaufzeit (Erdbewegung) ein; Fehler von 1 km sind hier
vernachlaessigbar (< 4 µs), die Koordinaten des Ziels muessen auf wenige Bogensekunden stimmen.
"""
from __future__ import annotations

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .observer import Site


def mid_exposure(hdr) -> Time:
    """Mitte der Belichtung (UTC) aus ``DATE-OBS`` (Beginn) + ``EXPTIME``/2.

    Erwartet ISO-Zeit (``2020-01-10T01:08:27.336``); ``DATE-OBS`` ohne Zeitzone gilt als UTC.
    """
    t0 = Time(str(hdr["DATE-OBS"]), scale="utc")
    return t0 + 0.5 * float(hdr.get("EXPTIME", 0.0)) * u.s


def site_from_header(hdr) -> Site | None:
    """Standort aus dem Header im LCO-Stil: ``SITE`` (Name), ``LATITUDE``, ``LONGITUD`` (Ost +), ``HEIGHT``.

    Ohne ``SITE`` kommt ``None``: Header ohne Namen (z. B. MicroObservatory) geben die Laenge teils ohne
    Vorzeichen (West) an; das Vorzeichen wird nie geraten, der Standort muss dann gesetzt werden.
    """
    try:
        name, lat, lon = str(hdr["SITE"]), float(hdr["LATITUDE"]), float(hdr["LONGITUD"])
    except (KeyError, ValueError):
        return None
    return Site(name, lat, lon, float(hdr.get("HEIGHT", 0.0) or 0.0))


def bjd_tdb(t_utc: Time, ra_deg: float, dec_deg: float, site: Site) -> np.ndarray:
    """BJD_TDB (als Julianisches Datum) fuer UTC-Zeiten ``t_utc`` und ein Ziel bei (ra, dec) [ICRS, Grad]."""
    t = Time(t_utc, location=site.earth_location)
    ltt = t.light_travel_time(SkyCoord(ra_deg, dec_deg, unit="deg"), kind="barycentric")
    return np.atleast_1d((t.tdb + ltt).jd)


def airmass(t_utc: Time, ra_deg: float, dec_deg: float, site: Site) -> np.ndarray:
    """Luftmasse (sec z; unter 20° Hoehe ungenau) fuer Ziel und Standort."""
    from astropy.coordinates import AltAz
    alt = SkyCoord(ra_deg, dec_deg, unit="deg").transform_to(
        AltAz(obstime=Time(t_utc), location=site.earth_location)).alt.deg
    alt = np.atleast_1d(alt)
    z = np.radians(90 - alt)
    return np.where(alt > 0, 1 / np.cos(z), np.nan)
