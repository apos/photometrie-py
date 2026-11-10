"""Zeitstempel: Mitte der Belichtung (JD, UTC) und BJD_TDB.

Autor: Axel Pospischil. BJD_TDB = Mittenzeit (TDB) + Lichtlaufzeit zum Schwerpunkt des Sonnensystems fuer die Richtung des
Ziels. Der Standort geht in die TDB-Umrechnung und die Lichtlaufzeit (Erdbewegung) ein; Fehler von 1 km sind hier
vernachlaessigbar (< 4 µs), die Koordinaten des Ziels muessen auf wenige Bogensekunden stimmen.
Quelle: Eastman, J., Siverd, R. & Gaudi, B. S. 2010, PASP 122, 935, arXiv:1005.4415 (geprueft, Zitat): BJD_TDB als
Standard fuer Zeitreihen empfohlen, Zeitstandard immer angeben. Hinweis: Das AAVSO-Extended-Format kennt als Datum nur
JD, HJD und EXCEL (Stand 2021, v1.2) — fuer den Export ist die UTC-Mitte als JD zu liefern, BJD_TDB bleibt fuer die Auswertung.
"""
from __future__ import annotations

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from .observer import Site


def mid_exposure(hdr) -> Time:
    """Mitte der Belichtung (UTC) aus ``DATE-OBS`` (Beginn) + ``EXPTIME``/2.

    Warum: AAVSO und Periodenanalyse brauchen die Mittenzeit, Header geben meist den Beginn an. Grenze: erwartet ISO-Zeit
    (``2020-01-10T01:08:27.336``) in UTC; ``DATE-OBS`` ohne Zeitzone gilt als UTC. Header mit Ortszeit (MicroObservatory:
    ``DATE-OBS`` mit Offset, ``UT-OBS`` in UTC) muessen vorher umgeschrieben werden.
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
    """BJD_TDB (als Julianisches Datum) fuer UTC-Zeiten ``t_utc`` und ein Ziel bei (ra, dec) [ICRS, Grad].

    Warum: Die Lichtlaufzeit der Erdbahn (bis ±500 s) verschiebt Maxima je nach Jahreszeit; fuer Perioden- und O-C-Analysen
    muss auf einen gemeinsamen Bezugspunkt umgerechnet werden. Wie: ``astropy.time.Time.light_travel_time(kind='barycentric')``
    auf die TDB-Zeit am Standort ``site`` addiert. Grenze: Das Ziel wird als unendlich weit entfernt angenommen.
    Validierung: ``tests/test_batch.py`` (Betrag < 505 s); LCO-Bild: +63 s am 2020-01-10 fuer delta Cep.
    Quelle: Eastman et al. 2010 (siehe Modulkopf).
    """
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
