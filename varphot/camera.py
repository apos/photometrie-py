"""Kamera-Charakterisierung: Bayer-Ebenen, Gain, Ausleserauschen, Full Well, Linearitaet, Dunkelstrom.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (Notebook 07, KONZEPT.md §11.8).

Warum: Fehlerbudget (Gain, Ausleserauschen), Saettigungsgrenze und der Gueltigkeitsbereich der Linearitaet haengen vom
Aufbau und der Einstellung ab (Gain-Modus, Temperatur). Herstellerkurven weichen mitunter ab — AAVSO-Beobachter
berichten das fuer die IMX533-Kameras ausdruecklich (Forum „Player One IMX533 settings"); deshalb wird selbst gemessen.

Alle Messungen laufen **je Farbebene** (R, G1, G2, B) und im Bildmittelpunkt (ROI), nie am gemittelten Gruen: Das Mitteln zweier
Ebenen verkleinert die Streuung und verfaelscht Gain und Rauschen (AAVSO DSLR Observing Manual v1.4, Anhang A).
Eingaben sind rohe Bayer-Bilder in ADU (keine Kalibrierung, kein Debayern).

Quellen: AAVSO DSLR Observing Manual v1.4 (2016), Anhang A (Gain, Rauschen, Full Well, Maximalwert, Offset) und Anhang E
(Linearitaet) — im Wortlaut gelesen; Photon-Transfer-Methode allgemein: Janesick, J. R. 2001, Scientific Charge-Coupled
Devices, SPIE Press, doi:10.1117/3.374903 (Buch per Suche bestaetigt, nicht eingesehen).
"""
from __future__ import annotations

import numpy as np
from astropy.stats import sigma_clipped_stats

# (Zeile, Spalte) der Pixel je Bayer-Muster; "RGGB": R oben links, G1 oben rechts, G2 unten links, B unten rechts
BAYER_OFFSETS = {
    "RGGB": {"R": (0, 0), "G1": (0, 1), "G2": (1, 0), "B": (1, 1)},
    "BGGR": {"B": (0, 0), "G1": (0, 1), "G2": (1, 0), "R": (1, 1)},
    "GRBG": {"G1": (0, 0), "R": (0, 1), "B": (1, 0), "G2": (1, 1)},
    "GBRG": {"G1": (0, 0), "B": (0, 1), "R": (1, 0), "G2": (1, 1)},
}
PLANES = ("R", "G1", "G2", "B")


def bayer_planes(img, pattern: str = "RGGB") -> dict[str, np.ndarray]:
    """Trennt ein rohes Bayer-Bild in die vier Farbebenen (halbe Aufloesung, ``float64``).

    Warum: Gain/Rauschen duerfen nicht ueber verschiedene Farbpixel gemischt werden; die Ebenen haben unterschiedliche
    Empfindlichkeit. Wie: Jede Ebene ist ``img[r::2, c::2]`` mit den Offsets des Musters (``BAYER_OFFSETS``). Grenze: Das
    Muster muss stimmen (im FITS meist ``BAYERPAT``; Software spiegelt manchmal ein Bild, dann Muster pruefen).
    """
    if pattern.upper() not in BAYER_OFFSETS:
        raise ValueError(f"Bayer-Muster {pattern!r} unbekannt (gueltig: {', '.join(BAYER_OFFSETS)})")
    a = np.asarray(img, dtype=np.float64)
    h, w = (a.shape[0] // 2) * 2, (a.shape[1] // 2) * 2
    a = a[:h, :w]
    return {k: a[r::2, c::2].copy() for k, (r, c) in BAYER_OFFSETS[pattern.upper()].items()}


def center_roi(plane, size: int = 100) -> np.ndarray:
    """Quadratischer Ausschnitt um die Bildmitte einer Ebene (Standard 100 x 100, wie im AAVSO-Handbuch)."""
    ny, nx = plane.shape
    s = min(size, ny, nx)
    y0, x0 = (ny - s) // 2, (nx - s) // 2
    return plane[y0:y0 + s, x0:x0 + s]


def _clipped_mean(a) -> float:
    return float(sigma_clipped_stats(np.asarray(a, float), sigma=5.0, maxiters=3)[0])


def pair_stats(a, b, size: int = 100) -> tuple[float, float]:
    """Mittelwert und zeitliche Varianz zweier gleicher Aufnahmen (Ebenen) im Mittelbereich.

    Rueckgabe ``(mean, var)`` mit ``mean`` = Mittel beider Bilder [ADU], ``var = var(a − b)/2`` [ADU²]. Die Differenz
    entfernt feste Muster (Flatfield-Struktur, Offset-Muster) und lässt nur das zeitliche Rauschen uebrig; die
    Varianz einer Differenz ist die doppelte Einzelvarianz (daher ``/2``).
    """
    ra, rb = center_roi(a, size), center_roi(b, size)
    mean = 0.5 * (_clipped_mean(ra) + _clipped_mean(rb))
    var = float(np.var(ra - rb, ddof=1) / 2.0)
    return mean, var


def gain_from_pair(f1, f2, b1, b2, size: int = 100) -> float:
    """System-Gain [e⁻/ADU] aus einem Flat-Paar und einem Bias-Paar (Handbuch Anhang A, „System Gain“).

    Warum: Schnellste Gain-Messung; als Gegenprobe zur Photon-Transfer-Anpassung (:func:`ptc_fit`).
    Wie: ``gain = [(F1+F2) − (B1+B2)] / [σ²(F1−F2) − σ²(B1−B2)]`` mit Mittelwerten ``(F1+F2)`` der beiden Bilder im Mittelbereich
    und ``σ`` der Differenzbilder. Alle Bilder derselben Farbebene. Flat-Pegel ~2/3 des Maximalwerts, nichts gesaettigt.
    Grenzen: Eine einzelne Messung; Nichtlinearitaet oder ungleiche Flat-Helligkeit der beiden Bilder verfaelschen sie.
    Validierung: ``tests/test_camera.py`` (synthetisch, ±5 %). Quelle: Handbuch v1.4 Anhang A; Janesick 2001.
    """
    ff1, ff2, bb1, bb2 = (center_roi(x, size) for x in (f1, f2, b1, b2))
    num = (_clipped_mean(ff1) + _clipped_mean(ff2)) - (_clipped_mean(bb1) + _clipped_mean(bb2))
    den = np.var(ff1 - ff2, ddof=1) - np.var(bb1 - bb2, ddof=1)
    if den <= 0:
        raise ValueError("Varianz der Flat-Differenz nicht groesser als die der Bias-Differenz — Pegel zu niedrig?")
    return float(num / den)


def ptc_fit(means, variances, offset: float, max_adu: float | None = None,
            lo_frac: float = 0.05, hi_frac: float = 0.8) -> dict:
    """Photon-Transfer-Kurve: Gain aus mehreren Flat-Paaren (Ausleserauschen NICHT aus dem Achsenabschnitt).

    Warum: Robuster als ein einzelnes Paar (Handbuch: „more involved but more robust“); zeigt Nichtlinearitaet als Kruemmung.
    Wie: Je Paar ``(mean, var)`` aus :func:`pair_stats`. Signal ``S = mean − offset`` [ADU]; im linearen Bereich gilt
    ``var = S/gain + σ_read²`` (Schrotrauschen + Ausleserauschen, alles in ADU, Gain in e⁻/ADU). gewichtete (``1/var``, denn die Varianzschaetzung hat konstanten relativen Fehler) Kleinste-Quadrate-Gerade von ``var`` gegen
    ``S``: Steigung = 1/Gain; der Achsenabschnitt entspricht formal dem Ausleserauschen² [ADU²], wird hier aber nur ausgewiesen, nicht benutzt. Verwendet werden nur Paare mit
    ``lo_frac·(max_adu−offset) ≤ S ≤ hi_frac·(max_adu−offset)`` (ohne ``max_adu`` alle).
    Rueckgabe: ``gain`` [e⁻/ADU], ``n`` (benutzte Paare), ``slope``, ``intercept`` [ADU²], ``r2`` (Guete der Geraden; niedrig = Nichtlinearitaet oder
    verrauschte Pegel).
    Grenzen: Setzt Schrotrauschen-dominiertes Signal und stabile Lichtquelle voraus; Pixel-zu-Pixel-Empfindlichkeit (Flat) ist durch die
    Differenz entfernt. Das Ausleserauschen laesst sich aus dem Achsenabschnitt nicht zuverlaessig bestimmen: bei den noetigen Pegeln
    (S >> RN²·Gain) ist die Schrotrauschen-Varianz um Groessenordnungen groesser und ein kleiner Steigungsfehler verschiebt den Achsenabschnitt
    stark (im Test lieferte er 0 statt 3 e⁻). Dafuer gilt :func:`read_noise_e` (Bias-Paar). Grenzwerte 5 %/80 % sind Startwerte.
    Validierung: ``tests/test_camera.py`` (Gain ±3 %). Quelle: Handbuch v1.4 Anhang A („Alternate Method“); Janesick 2001.
    """
    m, v = np.asarray(means, float), np.asarray(variances, float)
    s = m - offset
    ok = np.ones(len(s), bool)
    if max_adu is not None:
        span = max_adu - offset
        ok = (s >= lo_frac * span) & (s <= hi_frac * span)
    if ok.sum() < 3:
        raise ValueError(f"zu wenige Paare im linearen Bereich ({int(ok.sum())} < 3)")
    # Die Varianzschaetzung hat konstanten *relativen* Fehler (~sqrt(2/N)) -> Gewicht 1/var; sonst bestimmen die hellen Punkte alles
    slope, icpt = np.polyfit(s[ok], v[ok], 1, w=1.0 / np.maximum(v[ok], 1e-9))
    pred = slope * s[ok] + icpt
    ss_tot = float(np.sum((v[ok] - v[ok].mean()) ** 2))
    r2 = 1.0 - float(np.sum((v[ok] - pred) ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    gain = 1.0 / slope
    return dict(gain=float(gain), n=int(ok.sum()), slope=float(slope), intercept=float(icpt), r2=r2)


def read_noise_e(b1, b2, gain: float, size: int = 100) -> float:
    """Ausleserauschen [e⁻ rms] aus einem Bias-Paar: ``σ(B1−B2)/√2 · gain`` (Handbuch Anhang A, „Readout noise“).

    Warum: Im Bias gibt es nur Ausleserauschen (kein Signal) — die direkteste Messung. Grenze: ``gain`` muss stimmen; Pegel
    nahe Null koennen durch das Abschneiden am ADU-Nullpunkt verfaelscht sein (Offset pruefen). Gilt je Einstellung (Gain-Modus).
    """
    d = center_roi(b1, size) - center_roi(b2, size)
    return float(np.std(d, ddof=1) / np.sqrt(2.0) * gain)


def full_well_e(gain: float, max_adu: float, offset: float = 0.0) -> float:
    """Full Well [e⁻] = ``gain · (max_adu − offset)``.

    Das Handbuch (Anhang A) setzt ``gain · max_adu`` (``offset = 0``); der Hersteller-Wert der IMX533 (72 889 e⁻ = 4,449 · 16 383)
    folgt derselben Konvention. Bei hohem Gain ist das nicht die physikalische Pixeltiefe, sondern die Elektronenzahl bis zur
    ADC-Grenze. ``offset`` nur setzen, wenn die nutzbare Signalspanne gemeint ist.
    """
    return float(gain * (max_adu - offset))


def linearity_curve(exptimes, mean_adu, max_adu: float | None = None, ref_range: tuple[float, float] = (0.15, 0.6),
                    tol_pct: float = 1.0) -> dict:
    """Linearitaet aus einer Belichtungsreihe (Mittelwert eines festen Bereichs gegen die Belichtungszeit).

    Warum: Photometrie setzt voraus, dass ADU proportional zur Lichtmenge ist; Nahe der Saettigung (und bei kurzen Zeiten durch die reale
    Verschlusszeit) weicht es ab. Der Beobachter braucht die ADU-Grenzen, in denen Sterne liegen duerfen.
    Wie (Handbuch Anhang E): Gerade ``mean = a + b·t`` durch die Punkte im Referenzbereich ``ref_range`` (Anteile von ``max_adu``;
    ohne ``max_adu``: untere Haelfte der Werte), robust nachgezogen (Punkte mit |Residuum| > 3·``tol_pct`` fliegen heraus, bis es stabil ist). Zaehlrate ``r = (mean − a)/t``; Residuum ``100·(r − b)/b`` in Prozent. Linearer Bereich =
    zusammenhaengende Punkte um den Referenzbereich mit ``|Residuum| ≤ tol_pct``.
    Rueckgabe: ``a`` (Achsenabschnitt = Offset), ``b`` (ADU/s), ``t``, ``mean``, ``rate``, ``residual_pct``, ``linear``
    (Maske), ``t_min``, ``t_max``, ``adu_min``, ``adu_max``.
    Grenzen: Verlangt eine stabile Lichtquelle (Handbuch: drei Bilder je Belichtung vergleichen); Toleranz 1 % ist ein Startwert; bei
    Rolling Shutter weichen sehr kurze Belichtungen ab. Validierung: ``tests/test_camera.py``. Quelle: Handbuch v1.4 Anhang E,
    dort nach AAVSO CCD Photometry Guide v1.1, InfoBox 3.1 (die Anleitung selbst nicht eingesehen).
    """
    t, m = np.asarray(exptimes, float), np.asarray(mean_adu, float)
    o = np.argsort(t)
    t, m = t[o], m[o]
    if max_adu is not None:
        sel = (m >= ref_range[0] * max_adu) & (m <= ref_range[1] * max_adu)
    else:
        sel = m <= np.percentile(m, 50)
    if sel.sum() < 3:
        raise ValueError("zu wenige Punkte im Referenzbereich fuer die Gerade (< 3)")
    use = sel.copy()
    for _ in range(4):                       # Referenzgerade robust: Ausreisser (z. B. Verschlusseffekt bei kurzen Zeiten) herausnehmen
        b, a = np.polyfit(t[use], m[use], 1)
        rate = (m - a) / t
        res = 100.0 * (rate - b) / b
        new_use = sel & (np.abs(res) <= 3.0 * tol_pct)
        if new_use.sum() < 3 or (new_use == use).all():
            break
        use = new_use
    ok = np.abs(res) <= tol_pct
    cand = np.flatnonzero(sel & ok)
    if len(cand) == 0:
        raise ValueError("kein Punkt im Referenzbereich liegt innerhalb der Toleranz")
    anchor = int(cand[len(cand) // 2])       # Ausgangspunkt: Mitte der brauchbaren Referenzpunkte
    lo = hi = anchor
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    while hi < len(t) - 1 and ok[hi + 1]:
        hi += 1
    lin = np.zeros(len(t), bool)
    lin[lo:hi + 1] = True
    return dict(a=float(a), b=float(b), t=t, mean=m, rate=rate, residual_pct=res, linear=lin,
                t_min=float(t[lo]), t_max=float(t[hi]), adu_min=float(m[lo]), adu_max=float(m[hi]))


def dark_current_e_per_s(exptimes, dark_means, gain: float) -> float:
    """Dunkelstrom [e⁻/s/Pixel] aus Darks verschiedener Belichtung bei konstanter Temperatur.

    Wie: Steigung der Geraden ``mean_dark = c + d·t`` [ADU/s] mal ``gain``; der Achsenabschnitt ``c`` (Offset) faellt heraus.
    Grenzen: Funktioniert nur bei stabil geregelter Temperatur (gekuehlte Kamera) und erkennbarem Signal; bei sehr kleinem Dunkelstrom
    (Ares-C Pro: 4,4e-5 e⁻/s bei −20 °C laut Hersteller) geht die Steigung im Rauschen unter — dann nur die Obergrenze angeben. Das Handbuch
    (Anhang A) weist darauf hin, dass sich bei DSLR der Dunkelstrom nicht so messen laesst (interne Verarbeitung).
    """
    t, m = np.asarray(exptimes, float), np.asarray(dark_means, float)
    if len(t) < 3:
        raise ValueError("mindestens 3 Belichtungszeiten noetig")
    slope = np.polyfit(t, m, 1)[0]
    return float(slope * gain)


def summarize_frame(img, pattern: str = "RGGB", size: int = 100) -> dict:
    """Verdichtet ein rohes Bayer-Bild auf das, was die Messungen brauchen (spart Speicher bei vielen Grossbildern).

    Rueckgabe: ``rois`` (Mittelbereich je Farbebene, ``size`` x ``size``), ``max`` (hellster Pixel des Bildes, fuer den
    Maximalwert), ``median`` (Median des ganzen Bildes, fuer den Offset bei Bias-Bildern).
    """
    img = np.asarray(img, dtype=np.float64)
    planes = bayer_planes(img, pattern)
    return dict(rois={k: center_roi(v, size).copy() for k, v in planes.items()}, max=float(img.max()),
                median=float(np.median(img)))


def group_by_exposure(records: list[dict], decimals: int = 3) -> dict[float, list[dict]]:
    """Gruppiert Bildzusammenfassungen (mit Schluessel ``exptime``) nach gleicher Belichtungszeit (gerundet).

    Warum: Flat-/Linearitaetsreihen bestehen aus mehreren Bildern je Belichtung; fuer die Paar-Statistik werden gleiche
    Belichtungen gebraucht. Nur Gruppen mit mindestens zwei Bildern bleiben erhalten.
    """
    out: dict[float, list[dict]] = {}
    for r in records:
        out.setdefault(round(float(r["exptime"]), decimals), []).append(r)
    return {k: v for k, v in sorted(out.items()) if len(v) >= 2}
