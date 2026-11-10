"""Aperturradius aus den Daten: Wachstumskurve und S/N-Optimum statt einer festen Regel.

Autor: Axel Pospischil. Stand 2026-11-10 (NB00 Schritt 4, KONZEPT §12.2).

Warum: Die Regel „1,5 × FWHM“ (AAVSO DSLR-Handbuch §6.1.1) setzt einen Gauss-Stern voraus. Auf echten Bildern haben helle Sterne Fluegel und sind breiter als schwache (LCO δ Cep: FWHM 7,1 gegen 5,2 px);
ein FWHM-Median, der aus den hellen Sternen stammt, liefert dann eine zu grosse oder zu kleine Apertur. Zwei bekannte Verfahren beantworten das aus den Daten:

* **Wachstumskurve** (Stetson 1990, DAOGROW): der eingeschlossene Fluss eines Sterns in Abhaengigkeit vom Radius; ab einem Radius, in dem sie flach wird, liegt (fast) alles Licht innen.
* **S/N-Optimum** (Howell 1989): das S/N einer Messung ueber dem Radius hat ein Maximum — nahe der FWHM, bei schwachen Sternen darunter (kleine Apertur = wenig Himmelsrauschen), bei hellen darueber.

Wie: :func:`optimal_aperture` misst beides an den ungesaettigten, isolierten Sternen eines Probebildes. Regel (Startwerte, nicht aus Daten hergeleitet): ``ap_r`` = kleinster Radius, der in der Wachstumskurve der **hellen** Sterne
``fraction`` (95 %) des Flusses einschliesst, mindestens 1,0 × FWHM der schwachen Sterne, hoechstens 5 × FWHM (nur ein Schutz gegen Nachbarsterne/Hintergrundgradienten in der Kurve; der gemessene Radius der LCO-Sterne lag bei 3 × FWHM). Das S/N der schwachen Sterne bleibt **Anzeige** (Verhaeltnis zum Optimum), keine Grenze.
Warum der Flussanteil Vorrang hat: Helle Sterne (das Ziel!) haben Fluegel; in einer zu kleinen Apertur geht ein groesserer Anteil ihres Lichts verloren als bei schwachen Comps, und dieser Anteil schwankt mit dem Seeing —
das staucht die Amplitude und erzeugt Streuung (LCO δ Cep: Apertur 5 px gab Amplitude 0,64 mag und Periode 5,375 d, 10 px gab 0,81 mag und 5,363 d; Literatur 0,88 mag und 5,366 d). Das S/N-Optimum (0,67 × FWHM bei Gauss-Sternen) waere
fuer eine einzelne schwache Quelle richtig, nicht fuer Differenzphotometrie eines hellen Ziels gegen schwache Comps.
Quellen: Howell, S. B. 1989, PASP 101, 616, doi:10.1086/132477 (Titel/Kennung per Suche geprueft; Volltext **nicht** gelesen: „S/N-Maximum bei einem mittleren Radius nahe der PSF-FWHM“ nach Sekundaerquellen);
Stetson, P. B. 1990, PASP 102, 932, doi:10.1086/132719 (Titel per Suche geprueft; Kennung der DOI nicht gegengelesen; Volltext nicht gelesen); AAVSO DSLR Observing Manual v1.4 §6.1.1 (gelesen: 1,2–1,5 × FWHM).
Grenzen: braucht mindestens 3 isolierte, ungesaettigte Sterne (sonst Rueckfall auf 1,5 × FWHM mit Hinweis); gilt fuer das Bild, an dem gemessen wurde (Seeing/Fokus der Reihe schwanken); Nachbarsterne im Radiusbereich verfaelschen die Kurve (robuster Himmelsmedian im Ring, keine Nachbarmaske).
"""
from __future__ import annotations

import numpy as np
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture


def growth_curve(img, xy, radii, sky_r_in: float, sky_r_out: float) -> np.ndarray:
    """Eingeschlossener Fluss ``F(r)`` (ADU, himmelskorrigiert) je Stern (Zeile) und Radius (Spalte).

    Himmel = Median im Ring ``sky_r_in``..``sky_r_out`` (ohne Clipping, wie :func:`varphot.batch.measure_frame`); ``F(r) = Summe(r) − Himmel · Flaeche(r)``.
    """
    img = np.asarray(img, float)
    xy = np.atleast_2d(np.asarray(xy, float))
    sky = np.asarray(ApertureStats(img, CircularAnnulus(xy, r_in=sky_r_in, r_out=sky_r_out), sigma_clip=None).median, float)
    out = np.empty((len(xy), len(radii)))
    for j, r in enumerate(radii):
        ap = CircularAperture(xy, r=r)
        out[:, j] = np.asarray(ApertureStats(img, ap, sigma_clip=None).sum, float) - sky * ap.area
    return out


def snr_curve(flux_r: np.ndarray, radii, sky_adu: float, gain: float = 1.0, read_noise_e: float = 0.0, sky_area_px: float = 1000.0) -> np.ndarray:
    """S/N einer Messung ueber dem Radius (CCD-Gleichung wie in :func:`varphot.batch.measure_frame`): ``S/N = F·g / sqrt(F·g + n·(1 + n/n_sky)·(S·g + RN²))``.

    ``flux_r``: ``F(r)`` in ADU (eine Kurve), ``sky_adu``: Himmel je Pixel [ADU], ``n = π r²`` Pixel der Apertur, ``sky_area_px`` = Pixel des Himmelsrings.
    """
    r = np.asarray(radii, float)
    n = np.pi * r ** 2
    f_e = np.maximum(flux_r, 0.0) * gain
    var = f_e + n * (1 + n / sky_area_px) * (max(sky_adu, 0.0) * gain + read_noise_e ** 2)
    return f_e / np.sqrt(np.maximum(var, 1e-12))


def optimal_aperture(img, stars, fwhm_px: float, gain: float = 1.0, read_noise_e: float = 0.0, fraction: float = 0.95, snr_floor: float = 0.80,
                     min_factor: float = 1.0, max_factor: float = 5.0, step: float = 0.5, gap_px: float = 3.0, annulus_area_factor: float = 1.5) -> dict:
    """Aperturradius aus Wachstumskurve (helle Sterne) und S/N-Optimum (schwache Sterne) eines Probebildes.

    ``stars``: Tabelle mit ``x, y, raw_max`` der **ungesaettigten, isolierten** Sterne (Spalte ``fwhm`` nicht NaN, wie von :func:`varphot.plan.star_metrics`), ``fwhm_px``: Median-FWHM.
    Rueckgabe (Pixel): ``ap_r, ap_r_in, ap_r_out`` (wie :func:`varphot.plan.aperture_from_fwhm`), ``r_growth`` (95 %-Radius der hellen Sterne), ``r_snr`` (S/N-Maximum der schwachen), ``snr_ratio``
    (S/N bei ``ap_r`` relativ zum Maximum), ``handbook_r`` (1,5 × FWHM) und ``snr_ratio_handbook``, ``method`` (``growth+snr`` oder ``fallback``), ``notes``, ``radii``, ``growth`` (Median je Radius, normiert) und ``snr`` (Median-Kurve der schwachen Sterne, normiert auf das Maximum).
    Regel: ``ap_r`` = ``r_growth`` (95-%-Radius der hellen Sterne), begrenzt auf [``min_factor``·FWHM_schwach, ``max_factor``·FWHM]. Faellt das S/N der schwachen Sterne dabei unter ``snr_floor`` · Maximum, steht ein Hinweis in ``notes``
(Kompromiss zugunsten des Flussanteils, KONZEPT §12.2); die Entscheidung bleibt beim Nutzer (manueller Radius).
    Der Himmelsring (``r_in = ap_r + gap_px``, Flaeche ≥ ``annulus_area_factor`` · Aperturflaeche) wird danach wie im Handbuch bemessen. Validierung: ``tests/test_aperture.py`` (Gauss: r_snr ≈ 0,67 FWHM, 95 %-Radius ≈ 1,04 FWHM).
    """
    from .plan import aperture_from_fwhm
    if not np.isfinite(fwhm_px) or fwhm_px <= 0:
        raise ValueError("fwhm_px muss eine positive Zahl sein (Probebild ohne messbare Sterne?)")
    ap_hb = aperture_from_fwhm(fwhm_px)
    res = dict(handbook_r=ap_hb["ap_r"], method="fallback", notes=[], **ap_hb)
    st = stars.dropna(subset=["fwhm"]).sort_values("raw_max", ascending=False) if "fwhm" in stars else stars.sort_values("raw_max", ascending=False)
    if len(st) < 3:
        res["notes"].append(f"nur {len(st)} brauchbare Sterne (mindestens 3 noetig) — Rueckfall auf 1,5 × FWHM nach Handbuch")
        return res
    rmax = float(min(max(4.0 * fwhm_px, 12.0), 40.0))
    radii = np.arange(1.0, rmax + step / 2, step)
    sky_in, sky_out = rmax + gap_px, rmax + gap_px + max(8.0, 0.5 * rmax)
    xy = st[["x", "y"]].to_numpy(float)
    keep = (xy[:, 0] > sky_out + 2) & (xy[:, 0] < np.asarray(img).shape[1] - sky_out - 2) & (xy[:, 1] > sky_out + 2) & (xy[:, 1] < np.asarray(img).shape[0] - sky_out - 2)
    st, xy = st[keep], xy[keep]
    if len(st) < 3:
        res["notes"].append("zu wenige Sterne mit Platz fuer den grossen Messring — Rueckfall auf 1,5 × FWHM")
        return res
    F = growth_curve(img, xy, radii, sky_in, sky_out)
    sky = float(np.median(ApertureStats(np.asarray(img, float), CircularAnnulus(xy, r_in=sky_in, r_out=sky_out), sigma_clip=None).median))
    half = len(st) // 2
    bright, faint = F[:max(half, 1)], F[half:] if half else F
    gb = np.median(bright / bright[:, -1:], axis=0)                                 # normierte Wachstumskurve (Median der hellen Sterne)
    ok = np.flatnonzero(gb >= fraction)
    r_growth = float(radii[ok[0]]) if len(ok) else float(radii[-1])
    sky_area = np.pi * (sky_out ** 2 - sky_in ** 2)
    f_med = np.median(faint, axis=0)
    snr = snr_curve(f_med, radii, sky, gain, read_noise_e, sky_area)
    snr_n = snr / snr.max()
    r_snr = float(radii[int(np.argmax(snr))])
    fw_faint = float(np.nanmedian(st["fwhm"].to_numpy()[half:])) if half else fwhm_px
    lo, hi = min_factor * fw_faint, max_factor * fwhm_px
    r = float(np.clip(r_growth, lo, hi))
    if r_growth > hi:
        res["notes"].append(f"Wachstumskurve erreicht {100 * fraction:.0f} % erst bei {r_growth:.1f} px (> {max_factor:g} × FWHM): Nachbarsterne/Hintergrundgradient in der Kurve? — auf {hi:.1f} px begrenzt")
    elif r_growth > 3.0 * fwhm_px:
        res["notes"].append(f"Wachstumskurve erreicht {100 * fraction:.0f} % erst bei {r_growth:.1f} px (> 3 × FWHM): ausgepraegte Fluegel der hellen Sterne — grosse Apertur noetig, Nachbarn im Ring pruefen")
    ap = aperture_from_fwhm(r / 1.5, 1.5, gap_px, annulus_area_factor)                # aperture_from_fwhm rechnet ceil(1.5·x); so wird ceil(r) und der Ring wie im Handbuch
    idx = lambda rr: int(np.argmin(np.abs(radii - rr)))
    if float(snr_n[idx(ap["ap_r"])]) < snr_floor:
        res["notes"].append(f"S/N der schwachen Sterne bei {ap['ap_r']} px nur {100 * float(snr_n[idx(ap['ap_r'])]):.0f} % des Optimums (Maximum bei {r_snr:.1f} px) — Kompromiss zugunsten des Flussanteils; bei Bedarf kleineren Radius waehlen")
    res.update(ap, r_growth=r_growth, r_snr=r_snr, snr_ratio=float(snr_n[idx(ap["ap_r"])]), snr_ratio_handbook=float(snr_n[idx(ap_hb["ap_r"])]), method="growth+snr", fwhm_faint=fw_faint,
               fwhm_bright=float(np.nanmedian(st["fwhm"].to_numpy()[:max(half, 1)])), n_stars=int(len(st)), radii=radii, growth=gb, snr=snr_n)
    return res
