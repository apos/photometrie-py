"""Hoehe von Stern und Sonne sowie Luftmasse aus Ort und Zeit (fuer die Inhaltspruefung, KONZEPT.md §11.16 R2).

Autor: Axel Pospischil. Verfahren: Stand 2026-11.

Warum: Zeit und Ort einer Meldung lassen sich gegen die Luftmasse-Spalte pruefen. Falsche Zeitzone, JD/HJD-Verwechslung, falscher Standort oder vertauschtes Vorzeichen der Laenge zeigen sich als falsche
Sternhoehe. Wie: ``astropy`` (AltAz, Sonne) fuer die Hoehen; Luftmasse nach Kasten & Young (1989), ``X = 1 / (sin h + 0,50572 (h + 6,07995)^-1,6364)`` (h in Grad). Grenzen: geometrische Hoehe ohne Refraktion;
andere Programme rechnen oft mit ``sec z`` (bei 10° Hoehe 3 % kleiner/groesser als Kasten & Young, bei 20° 0,7 %), daher Vergleich mit relativer Toleranz. Validierung: ``tests/test_vsx.py``
(LCO-Testdatei δ Cep: Abweichung <= 0,0013).
"""
from __future__ import annotations

import math

import numpy as np


def airmass_kasten_young(alt_deg: float) -> float:
    """Luftmasse aus der Hoehe in Grad; ``nan`` fuer Hoehen <= 0°."""
    if not alt_deg > 0:
        return float("nan")
    return 1.0 / (math.sin(math.radians(alt_deg)) + 0.50572 * (alt_deg + 6.07995) ** -1.6364)


def altitudes(ra_deg: float, dec_deg: float, jds, lat_deg: float, lon_deg: float, height_m: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Hoehe des Sterns und der Sonne (Grad) zu den Zeiten ``jds`` (JD, UTC) am Standort (Laenge positiv nach Osten)."""
    import astropy.units as u
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_sun
    from astropy.time import Time
    t = Time(np.atleast_1d(np.asarray(jds, dtype=float)), format="jd", scale="utc")
    frame = AltAz(obstime=t, location=EarthLocation.from_geodetic(lon_deg * u.deg, lat_deg * u.deg, height_m * u.m))
    star = SkyCoord(ra_deg * u.deg, dec_deg * u.deg).transform_to(frame).alt.deg
    sun = get_sun(t).transform_to(frame).alt.deg
    return np.atleast_1d(star), np.atleast_1d(sun)
