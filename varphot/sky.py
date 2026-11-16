"""Himmelshintergrund im Ring: Median mit Sigma-Clipping nur auf den Ringpixeln.

Autor: Axel Pospischil. Stand 2026-11-16 (KONZEPT §11.17).

Warum: Im Himmelsring liegen oft fremde Sterne, Hot Pixel oder Kosmik. Ein reiner Median verträgt bis knapp die Hälfte solcher Pixel, wird aber
von einem hellen Nachbarn oder mehreren Sternen im Ring nach oben gezogen; der Himmel ist dann zu hoch, der Fluss des Sterns zu klein, und zwar
je Bild verschieden (Seeing ändert, wie viel Licht des Nachbarn im Ring liegt). Das verfälscht die Lichtkurve systematisch, nicht nur zufällig.

Wie: Aus den Pixeln des Rings (Mittelpunktsmethode, nur endliche Werte) werden Ausreißer iterativ verworfen — Mitte = Median, Streuung =
``mad_std`` (1,4826 · MAD, unempfindlich gegen die Ausreißer selbst), Schwelle ``sky_clip_sigma`` (Standard 3) beidseitig, höchstens
``sky_clip_iters`` Durchgänge (Standard 5). Der Himmel ist der Median der übrigen Pixel, ``n_used`` ihre Zahl (geht in die Fehlerrechnung ein: die
Unsicherheit des Himmels hängt von den *benutzten* Pixeln ab). ``sky_clip_sigma = None`` oder ``0`` schaltet das Clipping ab (altes Verhalten).

Wichtig: Das Clipping gilt **nur für den Ring**. Die Summe in der Apertur wird nie geclippt — ``photutils.ApertureStats`` clippt standardmäßig auch die
Summe und schnitt helle Sternkerne ab (Fluss 205 statt 251 im Test; Regressionstest ``tests/test_photometry.py``).

Grenzen: Es ist keine Sternmaske. Liegt mehr als die Hälfte des Rings im Licht eines Nachbarn, trägt auch der geclippte Median den falschen Wert; dann hilft
nur ein anderer Ring oder das Verwerfen des Sterns (``catalog._comp_reject_reason``, Nachbar innerhalb ``comp_r_iso_px``). Bleiben weniger als die Hälfte der
Pixel (oder weniger als 10) übrig, wird das Ergebnis des Clippings verworfen und der ungeclippte Median benutzt (die Verteilung ist dann nicht „Himmel plus
einzelne Ausreißer“); ist die Streuung null (mehr als die Hälfte der Pixel exakt gleich, z. B. Nullen), wird nicht geclippt. Das Clipping wirkt symmetrisch; ein echter Himmelsgradient über den Ring bleibt unberührt (er ist klein gegen 3 σ und mittelt sich im Median).

Validierung: ``tests/test_sky.py`` (Nachbarstern im Ring, Hot Pixel, glatter Himmel unverändert, zu wenige Pixel, Abschaltung).

Quellen: Iteratives Sigma-Clipping mit Median und MAD ist Standard (astropy ``sigma_clip``); verwandt ist die robuste Himmelsschätzung im Ring bei DAOPHOT
(Stetson 1987, PASP 99, 191, doi:10.1086/131977; Zitat per Suche geprüft, ob und wie der Aufsatz das Clipping beschreibt, ist nicht geprüft).
"""
from __future__ import annotations

import numpy as np
from astropy.stats import sigma_clip
from photutils.aperture import CircularAnnulus

from .config import CFG

MIN_KEEP = 10          # weniger übrige Pixel: Clipping verwerfen


def sky_from_values(values, sigma: float | None = 3.0, iters: int = 5) -> tuple[float, int, int]:
    """Himmel (Median nach Clipping), Zahl benutzter und verworfener Pixel aus den Ringwerten.

    Leerer Ring: ``(nan, 0, 0)``. ``sigma`` ``None`` oder ``0``: reiner Median.
    """
    v = np.asarray(values, float).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return float("nan"), 0, 0
    plain = float(np.median(v))
    if not sigma or v.size < 2 * MIN_KEEP:
        return plain, int(v.size), 0
    if float(np.median(np.abs(v - plain))) == 0.0:         # mehr als die Haelfte exakt gleich (z. B. Nullen, Sättigungsplateau): keine Streuung messbar
        return plain, int(v.size), 0
    kept = sigma_clip(v, sigma=sigma, maxiters=iters, cenfunc="median", stdfunc="mad_std", masked=True)
    good = v[~np.ma.getmaskarray(kept)]
    if good.size < max(MIN_KEEP, v.size // 2):
        return plain, int(v.size), 0
    return float(np.median(good)), int(good.size), int(v.size - good.size)


def sky_level(img, xy, r_in: float, r_out: float, cfg=None) -> tuple[float, int, int]:
    """Himmel für einen Stern bei ``xy`` = (x, y) im Ring ``r_in``..``r_out`` (siehe Modulkopf); Rückgabe ``(Himmel, n_benutzt, n_verworfen)``."""
    cfg = cfg or CFG
    mask = CircularAnnulus((float(xy[0]), float(xy[1])), r_in=r_in, r_out=r_out).to_mask(method="center")
    vals = mask.get_values(np.asarray(img))
    return sky_from_values(vals, cfg.get("sky_clip_sigma", 3.0), int(cfg.get("sky_clip_iters", 5)))
