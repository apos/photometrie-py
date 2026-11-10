"""Beobachtungsplanung: Probebilder auswerten (FWHM, Saettigung), Belichtung und Aperturen vorschlagen, Plan speichern.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (Notebook 00, KONZEPT.md §12).

Warum: Eine Aufnahmereihe laesst sich nicht nachtraeglich retten, wenn das Ziel gesaettigt ist, die Sterne zu scharf (Bayer-Kameras) oder die Belichtung
ausserhalb des linearen Bereichs liegt. Wenige **Probebilder** vorab liefern FWHM und Saettigungsabstand; daraus folgen Belichtungszeit, Fokus-/Defokus-Hinweis und
Aperturradien. Das Ergebnis wird mit Ziel, Methode (Monochrom + Filter, Farbkamera, DSLR/spiegellos), Kamera und Standort als **Plan** gespeichert und kann von den
Folge-Notebooks gelesen werden.

Regeln (AAVSO DSLR Observing Manual v1.4, im Wortlaut gelesen): Sterne (Ziel, Comps, Check) unter **75 %** des Maximalwerts (§4.5.2); Aperturradius **1,2–1,5 × FWHM** des
groessten Sterns (§6.1.1), Himmelsring mit innerem Radius „several pixels“ ueber der Apertur und mindestens so vielen Pixeln wie die Apertur, besser mehr (§6.1.2);
bei Bayer-Kameras **FWHM im Rohbild ≥ 8–10 Pixel** (§5.5.1).
"""
from __future__ import annotations

import math
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

METHODS = {
    "mono": "Monochrom-Kamera + Standardfilter (Johnson-Cousins, z. B. V)",
    "monorgb": "Monochrom-Kamera + RGB-Filter (Astroimaging; TB/TG/TR)",
    "osc": "Farbkamera (One-Shot-Color, Bayer)",
    "dslr": "DSLR / spiegellos (Bayer, RAW)",
}
SAFE_FRACTION = 0.75          # AAVSO DSLR-Handbuch §4.5.2
MIN_RAW_FWHM_BAYER = 8.0      # AAVSO DSLR-Handbuch §5.5.1 (8-10 px im Rohbild)


def green_plane(img, pattern: str = "RGGB") -> np.ndarray:
    """Mittel der beiden Gruen-Ebenen eines rohen Bayer-Bildes (halbe Aufloesung) — so wird fuer ``TG`` gemessen (Handbuch §5.4)."""
    from .camera import bayer_planes
    p = bayer_planes(img, pattern)
    return 0.5 * (p["G1"] + p["G2"])


def star_metrics(img, max_adu: float | None = None, fwhm_guess: float = 4.0, nsigma: float = 20.0, max_fit: int = 15,
                 sat_frac: float = 0.98, edge: int = 25) -> pd.DataFrame:
    """Sterne eines (Probe-)Bildes mit Spitzenwert, Saettigungsmarke und FWHM.

    Warum: Aus den hellsten Sternen folgt der Saettigungsabstand, aus den mittelhellen, ungesaettigten die Sternbreite (FWHM), nach der Aperturen und Fokus gewaehlt werden.
    Wie: Detektion mit :func:`varphot.detect.detect` (DAOStarFinder, globaler Himmel). Je Stern ``raw_max`` = hoechster Pixel im 5x5-Fenster (ADU, mit Offset);
    gesaettigt, wenn ``raw_max ≥ sat_frac·max_adu``. FWHM per ``photutils.psf.fit_fwhm`` (kreisfoermige Gauss-Anpassung) an bis zu ``max_fit`` ungesaettigten,
    isolierten Sternen mit Spitze zwischen 20·σ und 60 % des Maximalwerts. Rueckgabe: Tabelle (``x, y, raw_max, peak, saturated, fwhm``), nach ``raw_max`` absteigend.
    Grenzen: Gauss-FWHM ist fuer stark defokussierte (ringfoermige) Sterne ungenau; fuer ``fwhm_guess`` weit unter der echten Breite findet die Detektion weniger Sterne
    (die Funktion wiederholt mit der gemessenen Breite einmal). Validierung: ``tests/test_plan.py`` (synthetisch, FWHM ±5 %).
    """
    from photutils.psf import fit_fwhm

    from .detect import detect

    img = np.asarray(img, float)
    ny, nx = img.shape
    cols = ["x", "y", "raw_max", "peak", "saturated", "fwhm"]
    sources = None
    guess = fwhm_guess
    for _ in range(2):
        sources, med, std = detect(img, fwhm=guess, nsigma=nsigma)
        if sources is None or len(sources) == 0:
            return pd.DataFrame(columns=cols)
        sel = np.asarray(sources["peak"]) > 0
        x, y = np.asarray(sources["x_centroid"])[sel], np.asarray(sources["y_centroid"])[sel]
        raw_max = np.array([img[max(int(round(b)) - 2, 0):int(round(b)) + 3, max(int(round(a)) - 2, 0):int(round(a)) + 3].max() for a, b in zip(x, y)])
        df = pd.DataFrame(dict(x=x, y=y, raw_max=raw_max, peak=raw_max - med))
        df["saturated"] = (df["raw_max"] >= sat_frac * max_adu) if max_adu else False
        cand = df[(~df["saturated"]) & (df["peak"] > 20 * std) & (df["peak"] < (0.6 * (max_adu - med) if max_adu else np.inf))
                  & (df["x"] > edge) & (df["x"] < nx - edge) & (df["y"] > edge) & (df["y"] < ny - edge)].copy()
        # isoliert: kein weiterer Stern naeher als 6*guess
        if len(cand):
            dx = cand["x"].to_numpy()[:, None] - df["x"].to_numpy()[None, :]
            dy = cand["y"].to_numpy()[:, None] - df["y"].to_numpy()[None, :]
            d = np.hypot(dx, dy)
            d[d == 0] = np.inf
            cand = cand[d.min(axis=1) > 6 * guess]
        cand = cand.sort_values("raw_max", ascending=False).head(max_fit)
        df["fwhm"] = np.nan
        if len(cand):
            shape = int(2 * np.ceil(2.5 * guess) + 1)
            try:
                fw = np.asarray(fit_fwhm(img - med, xypos=list(zip(cand["x"], cand["y"])), fwhm=guess, fit_shape=shape), float)
            except Exception:                           # Anpassung scheitert bei sehr schlechten Sternen -> keine FWHM
                fw = np.full(len(cand), np.nan)
            df.loc[cand.index, "fwhm"] = fw
        measured = df["fwhm"].dropna()
        if len(measured) >= 3 and abs(np.median(measured) - guess) / guess > 0.5 and _ == 0:
            guess = float(np.median(measured))           # Detektion mit der gemessenen Breite wiederholen
            continue
        break
    return df.sort_values("raw_max", ascending=False).reset_index(drop=True)[cols]


def fwhm_summary(df: pd.DataFrame) -> dict:
    """Median-FWHM, robuste Streuung und Zahl der Sterne aus :func:`star_metrics`; dazu die FWHM der helleren und der schwaecheren Haelfte.

    Warum: Auf echten Bildern (LCO δ Cep) waren helle Sterne breiter als schwache (7 px gegen 4,5 px; Fluegel der PSF). Die Apertur nach dem Handbuch richtet sich nach dem **groessten** Stern,
    Comps sind aber schwaecher; der Unterschied soll sichtbar sein, nicht in einem Median verschwinden. Rueckgabe: ``fwhm`` (Median aller), ``scatter`` (1,4826·MAD), ``n``, ``fwhm_bright`` und
    ``fwhm_faint`` (Median der helleren/schwaecheren Haelfte nach ``raw_max``, ab 6 Sternen, sonst NaN) und ``grows_with_brightness`` (``fwhm_bright/fwhm_faint`` > 1,25). Validierung: ``tests/test_plan.py``.
    """
    d = df.dropna(subset=["fwhm"])
    d = d[(d["fwhm"] > 0.8) & (d["fwhm"] < 200)]
    f = d["fwhm"].to_numpy()
    if len(f) == 0:
        return dict(fwhm=float("nan"), scatter=float("nan"), n=0, fwhm_bright=float("nan"), fwhm_faint=float("nan"), grows_with_brightness=False)
    br = fa = float("nan")
    if len(d) >= 6:
        s = d.sort_values("raw_max", ascending=False)["fwhm"].to_numpy()
        br, fa = float(np.median(s[:len(s) // 2])), float(np.median(s[len(s) // 2:]))
    return dict(fwhm=float(np.median(f)), scatter=float(1.4826 * np.median(np.abs(f - np.median(f)))), n=int(len(f)), fwhm_bright=br, fwhm_faint=fa,
                grows_with_brightness=bool(np.isfinite(br) and np.isfinite(fa) and br / fa > 1.25))


def defocus_tradeoff(fwhm_sharp: float, fwhm_def: float) -> dict:
    """Folgen des Defokussierens gegenueber dem scharfen Bild (Naeherungen fuer gleichen Fluss).

    Warum: Defokussieren senkt den Spitzenwert (laengere Belichtung ohne Saettigung, weniger Szintillation, Bayer-Muster verschmiert) und kostet S/N der schwachen Sterne. Wie (Gauss-Sterne): Spitzenwert ∝ 1/FWHM²,
    also ``peak_factor = (FWHM_scharf/FWHM_defokus)²`` und gleiche Saettigungsgrenze bei ``exposure_gain = 1/peak_factor`` mal laengerer Belichtung; S/N eines himmelsbegrenzten Sterns ∝ 1/FWHM
    (Aperturflaeche ∝ FWHM²), also ``snr_factor = FWHM_scharf/FWHM_defokus``; ``aperture_area_factor`` = Flaechenzuwachs der Apertur.
    Grenzen: Naeherung fuer Gauss-Profile — bei Donuts (Ringe) und starker Defokussierung ungenau; bei hellen Sternen, die photonenbegrenzt sind, faellt der S/N-Verlust kleiner aus. Validierung: ``tests/test_plan.py``.
    """
    r = fwhm_sharp / fwhm_def
    return dict(peak_factor=r ** 2, exposure_gain=1.0 / r ** 2, snr_factor=r, aperture_area_factor=1.0 / r ** 2)


def defocus_needed(raw_max: float, offset: float, limit_adu: float, fwhm_now: float, exptime_now: float, exptime_want: float) -> float:
    """FWHM [px], die noetig ist, damit der hellste Stern bei ``exptime_want`` unter ``limit_adu`` bleibt (Spitzenwert ∝ 1/FWHM², Fluss ∝ Belichtung).

    Warum: Man will oft eine bestimmte Belichtung (Szintillation, Nachfuehrung) und fragt, wie weit man defokussieren muss. Wie: ``peak' = offset + (raw_max − offset)·t_want/t_now``; ist
    ``peak' ≤ limit``, bleibt ``fwhm_now``; sonst ``fwhm_now·sqrt((peak' − offset)/(limit − offset))``. Grenzen: Gauss-Naeherung, setzt Linearitaet voraus. Validierung: ``tests/test_plan.py``.
    """
    scaled = offset + (raw_max - offset) * exptime_want / exptime_now
    if scaled <= limit_adu:
        return float(fwhm_now)
    return float(fwhm_now * np.sqrt((scaled - offset) / (limit_adu - offset)))


def recommend_exposure(raw_max: float, exptime_s: float, limit_adu: float, offset: float = 0.0) -> float:
    """Laengste Belichtungszeit [s], bei der der hellste Pixel unter ``limit_adu`` bleibt (lineare Skalierung des Signals).

    Warum: Aus einer Probeaufnahme (``raw_max`` bei ``exptime_s``) folgt, wie lange man belichten darf, ohne dass der hellste Stern ``limit_adu`` ueberschreitet.
    Wie: ``t_max = t · (limit − offset)/(raw_max − offset)`` — setzt Linearitaet und gleiche Bedingungen (Seeing, Transparenz, Phase des Veraenderlichen) voraus.
    Grenzen: Ein Veraenderlicher wird heller und kann den Wert uebersteigen: fuer den **hellsten Zustand** (V_max) planen. Gesaettigte Probebilder liefern nur
    eine Obergrenze fuer ``raw_max`` — dann mit kuerzerer Belichtung neu aufnehmen. Quelle: AAVSO DSLR Observing Manual v1.4 §4.5.2 (75-%-Regel, gelesen).
    """
    sig = raw_max - offset
    if sig <= 0:
        raise ValueError("Probebild ohne Signal ueber dem Offset")
    return float(exptime_s * (limit_adu - offset) / sig)


def aperture_from_fwhm(fwhm_px: float, factor: float = 1.5, gap_px: float = 3.0, annulus_area_factor: float = 1.5) -> dict:
    """Aperturradien aus der FWHM: ``ap_r = factor·FWHM``, Himmelsring innen ``ap_r + gap``, Flaeche des Rings ≥ ``annulus_area_factor`` · Aperturflaeche.

    Warum: Zu kleine Aperturen verlieren Sternlicht (und reagieren auf Seeing), zu grosse addieren Rauschen; das Handbuch nennt 1,2–1,5 × FWHM des groessten Sterns,
    „better to err on the larger size“ bei schlechter Nachfuehrung. Wie: ``ap_r = ceil(factor·FWHM)``; ``r_in = ap_r + gap_px``;
    ``r_out = ceil(sqrt(r_in² + annulus_area_factor·ap_r²))`` (Ringflaeche = Faktor mal Aperturflaeche; Handbuch: mindestens gleich gross, besser mehr).
    Grenzen: Startwerte; mit Nachbarsternen im Ring Radius anpassen. Rueckgabe in Pixeln des ausgewerteten Bildes (bei Bayer: der Farbebene — FWHM dort messen).
    Quelle: AAVSO DSLR Observing Manual v1.4 §6.1.1–6.1.2 (gelesen).
    """
    ap = int(np.ceil(factor * fwhm_px))
    r_in = ap + gap_px
    r_out = int(np.ceil(np.sqrt(r_in ** 2 + annulus_area_factor * ap ** 2)))
    return dict(ap_r=ap, ap_r_in=float(r_in), ap_r_out=r_out)


def plane_wcs(wcs, offset=(0.5, 0.5)):
    """WCS fuer eine halbaufloesende Bayer-Ebene (``img[r::2, c::2]`` bzw. das Gruen-Mittel) aus der WCS des Rohbildes.

    Warum: Positionen aus der Rohbild-WCS muessen in die Koordinaten der ausgewerteten Ebene umgerechnet werden. Wie: Ebenenpixel ``i`` entspricht Rohpixel ``2·i + offset`` (0-basiert; ``offset`` =
    (Spalte, Zeile) der Ebene: R (0,0), G1 (1,0), G2 (0,1), B (1,1), Gruen-Mittel (0,5, 0,5)); ``CRPIX' = (CRPIX − 1 − offset)/2 + 1``, Pixelskala ×2.
    """
    w = wcs.deepcopy()
    off = np.asarray(offset, float)
    w.wcs.crpix = (np.asarray(w.wcs.crpix, float) - 1 - off) / 2.0 + 1
    if w.wcs.has_cd():
        w.wcs.cd = np.asarray(w.wcs.cd) * 2.0
    else:
        w.wcs.cdelt = np.asarray(w.wcs.cdelt) * 2.0
    return w


def check_field_stars(img, wcs, stars: pd.DataFrame, exptime_s: float, limit_adu: float, offset: float = 0.0, aperture: dict | None = None,
                      gain: float = 1.0, read_noise_e: float = 0.0, max_adu: float | None = None, snr_min: float = 100.0,
                      target_exptime_s: float | None = None) -> pd.DataFrame:
    """Jeden Katalogstern (Ziel, Comps, Check) einzeln gegen die Obergrenze und das S/N-Minimum pruefen.

    Warum: Nicht nur der hellste Stern des Bildes zaehlt, sondern **jeder Stern, der in die Photometrie eingeht** (Handbuch §4.5.2: „neither the target star nor any of the comparison and check stars is
    saturated“; §6.3.1: S/N ≥ 100). Bei einem Veraenderlichen ist oft ein Comp der erste, der anschlaegt — oder das Ziel in seiner hellen Phase.
    Wie: ``stars`` (Spalten ``id, role, ra, dec, V``) werden mit der WCS auf Pixel abgebildet; je Stern Aperturphotometrie (:func:`varphot.batch.measure_frame`, CCD-Gleichung mit ``gain``/``read_noise_e``),
    hellster Pixel ``raw_max`` (5x5), Saettigung (``raw_max ≥ 0,98·max_adu`` oder ``n_sat`` > 0), ``t_max_s`` = :func:`recommend_exposure` je Stern und ``snr`` bei der Probebelichtung; ``snr_at`` skaliert das
    S/N mit der Wurzel der Belichtungszeit (Photonenrauschen-Naeherung) auf ``target_exptime_s`` (Standard: Probebelichtung). Rueckgabe: Tabelle je Stern mit ``limiting`` (Stern mit kleinstem ``t_max_s``) und ``ok_snr``.
    Grenzen: Stern ausserhalb des Bildes oder am Rand wird mit ``star_flag`` EDGE gemeldet (keine Werte); die Skalierung setzt Linearitaet voraus; bei Bayer-Bildern ``img``/``wcs`` der Ebene uebergeben (:func:`plane_wcs`).
    Validierung: ``tests/test_plan.py``.
    """
    from .batch import measure_frame
    from .config import CFG
    ap = aperture or aperture_from_fwhm(4.0)
    cfg = {**CFG, **ap, "gain_e_per_adu": gain, "readout_noise_e": read_noise_e, "sat_adu": max_adu or CFG["sat_adu"]}
    hdr = {"GAIN": gain, "RDNOISE": read_noise_e, "SATURATE": max_adu or CFG["sat_adu"]}
    rows = measure_frame(np.asarray(img, float), wcs, stars.rename(columns={}), hdr, cfg)
    meas = pd.DataFrame(rows).rename(columns={"star_id": "id"})
    out = stars.merge(meas, on="id", how="left")
    ny, nx = np.asarray(img).shape
    raw = []
    for _, r in out.iterrows():
        if r["star_flag"] == "EDGE" or not np.isfinite(r["x"]):
            raw.append(np.nan)
            continue
        x, y = int(round(r["x"])), int(round(r["y"]))
        raw.append(float(np.asarray(img)[max(y - 2, 0):y + 3, max(x - 2, 0):x + 3].max()))
    out["raw_max"] = raw
    lim_sat = 0.98 * max_adu if max_adu else np.inf
    out["saturated"] = (out["raw_max"] >= lim_sat) | (out["n_sat"] > 0)
    out["over_limit"] = out["raw_max"] > limit_adu
    out["t_max_s"] = [recommend_exposure(m, exptime_s, limit_adu, offset) if np.isfinite(m) and m > offset else np.nan for m in out["raw_max"]]
    out["snr"] = out["flux"] / out["flux_err"]
    t_ref = target_exptime_s or exptime_s
    out["snr_at"] = out["snr"] * np.sqrt(t_ref / exptime_s)
    out["ok_snr"] = out["snr_at"] >= snr_min
    valid = out["t_max_s"].notna()
    out["limiting"] = False
    if valid.any():
        out.loc[out.loc[valid, "t_max_s"].idxmin(), "limiting"] = True
    return out


def comp_v_min(table: pd.DataFrame, exptime_s: float, rec_exptime_s: float, limit_adu: float, offset: float = 0.0) -> float | None:
    """Hellste Helligkeit (V), die ein Comp bei der empfohlenen Belichtung haben darf, ohne ``limit_adu`` zu ueberschreiten.

    Warum: NB03 soll nur Comps waehlen, die nicht saettigen. Wie: Aus den ungesaettigten Katalogsternen des Probebildes ``ZP = median(V + 2,5·log10(raw_max − offset))``;
    bei ``rec_exptime_s`` steigt das Signal um ``rec/exptime``; ``V_min = ZP − 2,5·log10(rec/exptime · ... )``: ein Stern erreicht die Grenze, wenn ``(limit − offset) = (raw_max − offset)·rec/exptime``,
    also bei ``V_min = ZP + 2,5·log10(rec/exptime) − 2,5·log10(limit − offset)``. Rueckgabe ``None`` ohne brauchbare Sterne. Grenzen: setzt Linearitaet und V-Werte im Katalog voraus; der Spitzenwert haengt
    von der FWHM ab (Comps aehnlicher Breite wie das Ziel).
    """
    t = table[(~table["saturated"]) & table["raw_max"].notna() & (table["raw_max"] > offset) & table["V"].notna()]
    if t.empty:
        return None
    zp = float(np.median(t["V"] + 2.5 * np.log10(t["raw_max"] - offset)))
    return float(zp + 2.5 * np.log10(rec_exptime_s / exptime_s) - 2.5 * np.log10(limit_adu - offset))


def night_altitudes(ra_deg: float, dec_deg: float, site, date: dt.date | None = None, step_min: int = 30) -> pd.DataFrame:
    """Hoehe des Ziels und der Sonne ueber eine Nacht (UTC-Zeitgitter, ``step_min``) am Standort ``site`` (:class:`varphot.observer.Site`).

    Warum: Planung — wann steht das Ziel hoch genug (Luftmasse), ist es dunkel und stoert der Mond? Wie: ``astropy`` AltAz fuer Ziel, Sonne und Mond (eingebaute Ephemeride, ohne Netz);
    Spalten ``utc``, ``alt_target``, ``airmass``, ``alt_sun``, ``dark`` (Sonne < −12°, nautische Daemmerung), ``ok`` (dunkel und Ziel > 30°), ``alt_moon``, ``moon_sep`` (Abstand Mond–Ziel [°]),
    ``moon_illum`` (beleuchteter Anteil, aus der Elongation Sonne–Mond genaehert), ``moon_ok`` (Mond unter dem Horizont **oder** Abstand > 40° bei Beleuchtung < 50 %; Startwerte) und ``ok_moon`` (``ok`` und ``moon_ok``).
    Warum der Mond zaehlt: Er hellt den Himmel auf (Himmelsrauschen, Gradienten im Himmelsring) — fuer helle Ziele wie δ Cep meist unkritisch, fuer schwache Ziele und kurze Abstaende schon.
    Grenzen: ohne Wetter; Mondhelligkeit nur grob (kein Streulichtmodell); Zeitgitter von 12:00 UT bis 12:00 UT des Folgetags (fuer Mitteleuropa deckt das die Nacht ab, sonst ``date`` anpassen).
    """
    from astropy import units as u
    from astropy.coordinates import AltAz, SkyCoord, get_body, get_sun
    from astropy.time import Time

    date = date or dt.datetime.now(dt.timezone.utc).date()
    t0 = Time(dt.datetime.combine(date, dt.time(12, 0)), scale="utc")
    times = t0 + np.arange(0, 24 * 60 + 1, step_min) * u.min
    frame = AltAz(obstime=times, location=site.earth_location)
    alt = SkyCoord(ra_deg, dec_deg, unit="deg").transform_to(frame).alt.deg
    sun = get_sun(times).transform_to(frame).alt.deg
    z = np.radians(90 - alt)
    airmass = np.where(alt > 0, 1 / np.cos(z), np.nan)
    df = pd.DataFrame(dict(utc=[t.strftime("%Y-%m-%d %H:%M") for t in times.to_datetime()], alt_target=alt, airmass=airmass, alt_sun=sun))
    df["dark"] = df["alt_sun"] < -12
    df["ok"] = df["dark"] & (df["alt_target"] > 30)
    target = SkyCoord(ra_deg, dec_deg, unit="deg")
    moon = get_body("moon", times, location=site.earth_location)          # topozentrisch: fuer Hoehe und Abstand zum Ziel
    df["alt_moon"] = moon.transform_to(frame).alt.deg
    df["moon_sep"] = moon.separation(target.transform_to(moon.frame)).deg
    elong = get_body("moon", times).separation(get_sun(times)).rad          # geozentrisch: Elongation Sonne–Mond fuer die Phase
    df["moon_illum"] = 0.5 * (1.0 - np.cos(elong))
    df["moon_ok"] = (df["alt_moon"] < 0) | ((df["moon_sep"] > 40) & (df["moon_illum"] < 0.5))
    df["ok_moon"] = df["ok"] & df["moon_ok"]
    return df


def field_of_view_deg(format_px, pixel_um: float, focal_mm: float) -> tuple[float, float]:
    """Bildfeld (lange, kurze Seite) in Grad aus Pixelzahl, Pixelgroesse und Brennweite; ``FOV = 2·atan(Sensorkante / 2f)``.

    Warum: NB03 braucht die Feldgroesse fuer die Comp-Suche; sie soll aus dem Aufbau kommen statt von Hand. Grenzen: ohne Verzeichnung und ohne Reducer-Unsicherheit — die wirkliche Brennweite
    steht erst nach dem Plate Solve fest (NB02/NB03 mit Referenzbild ueberschreibt diesen Wert). Validierung: ``tests/test_plan.py``.
    """
    w, h = sorted((float(format_px[0]), float(format_px[1])), reverse=True)
    f = lambda px: math.degrees(2 * math.atan(px * pixel_um / 1000.0 / (2 * focal_mm)))
    return round(f(w), 3), round(f(h), 3)


@dataclass
class ObservingPlan:
    """Ergebnis der Planung (NB00); wird als JSON im Datenordner abgelegt (``plans/``)."""
    target: str
    ra_deg: float
    dec_deg: float
    v_mean: float | None = None
    v_max: float | None = None                    # hellster Zustand (fuer die Saettigungsplanung)
    method: str = "mono"                          # Schluessel aus METHODS
    aavso_filter: str = "V"                       # V, TG, TB, TR ...
    obstype: str = "CCD"
    camera_model: str = ""
    camera_setting: str = ""
    bayer_pattern: str = ""
    site_name: str = ""
    fwhm_px: float | None = None                  # im ausgewerteten Bild (bei Bayer: Gruenebene)
    fwhm_raw_px: float | None = None              # im Rohbild
    aperture: dict = field(default_factory=dict)  # ap_r, ap_r_in, ap_r_out
    offset_adu: float | None = None
    max_adu: float | None = None
    limit_adu: float | None = None                # obere Grenze fuer den hellsten Pixel
    limit_source: str = ""
    exptime_max_s: float | None = None
    exptime_recommended_s: float | None = None
    v_comp_min: float | None = None               # hellster zulaessiger Comp (V) bei der empfohlenen Belichtung (aus den Probebildern)
    field_checks: list = field(default_factory=list)   # je Katalogstern: id, Rolle, V, hellster Pixel, t_max, S/N
    moon: dict = field(default_factory=dict)      # Beleuchtung/Abstand im Beobachtungsfenster
    fwhm_sharp_px: float | None = None            # FWHM des scharfen Referenzbildes (NB00 Schritt 3c)
    defocus_factor: float | None = None           # FWHM(geplanter Fokus)/FWHM(scharf)
    plate_solve: dict = field(default_factory=dict)  # Ergebnis des Plate-Solve-Tests (getestet, geloest, Skala, Leiter der Unschaerfe)
    readiness: dict = field(default_factory=dict)  # Status NB07 (Kameraprofil), NB08 (Transformation), gewaehltes Standardfeld
    focal_length_mm: float | None = None          # Brennweite des Aufbaus (mit Reducer), Eingabe in NB00
    field_deg: list = field(default_factory=list) # Bildfeld [lange, kurze Seite] in Grad aus Sensor und Brennweite (leer = unbekannt)
    warnings: list = field(default_factory=list)
    created: str = ""
    notes: str = ""


def plan_dir() -> Path:
    from .observer import data_dir
    return data_dir() / "plans" if data_dir().is_dir() else Path("~/.config/varphot/plans").expanduser()


def plan_filename(plan: ObservingPlan) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{plan.target}-{plan.method}-{plan.camera_model}-{plan.camera_setting}".lower()).strip("-")
    return f"{slug}.json"


def save_plan(plan: ObservingPlan, directory: Path | None = None) -> Path:
    d = Path(directory or plan_dir())
    d.mkdir(parents=True, exist_ok=True)
    plan.created = plan.created or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    p = d / plan_filename(plan)
    p.write_text(json.dumps(asdict(plan), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def load_plan(path) -> ObservingPlan:
    return ObservingPlan(**json.loads(Path(path).read_text(encoding="utf-8")))


def latest_plan(target: str | None = None, directory: Path | None = None) -> ObservingPlan | None:
    """Neuester gespeicherter Plan (optional fuer ein Ziel); ``None``, wenn keiner existiert."""
    d = Path(directory or plan_dir())
    if not d.is_dir():
        return None
    cand = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in cand:
        plan = load_plan(p)
        if target is None or plan.target.lower() == target.lower():
            return plan
    return None
