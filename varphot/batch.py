"""Stapelverarbeitung: Aperturphotometrie ueber viele Bilder, Qualitaetsflags, Ensemble-Lichtkurve.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (validiert an LCO delta Cep V, siehe docs/testdaten.md).

Ablauf (Notebook 04/05): ``read_frame`` -> ``measure_frame`` je Bild -> ``run_batch`` (Tabelle, lang: eine Zeile je Bild
und Stern) -> ``qc_frames`` (Bildflags) -> ``light_curve`` (Differenzphotometrie gegen die Comps, Fehler je Punkt).

Die Positionen kommen aus der WCS jedes Bildes (z. B. LCO/BANZAI: je Bild geloest). Es wird nicht nachzentriert —
bei gesaettigtem Ziel waere das ohnehin unzuverlaessig. Konzept: KONZEPT.md §4 (Datenfluss), §5.2 (QC), §5.4 (Fehler).
"""
from __future__ import annotations

import concurrent.futures as cf
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS
from photutils.aperture import ApertureStats, CircularAnnulus, CircularAperture

from .config import CFG
from .timeutil import bjd_tdb, mid_exposure

# Bild-Flags (je Bild, in ``qc_frames`` gesetzt); Sterne tragen zusaetzlich ``star_flag``
FRAME_FLAGS = ("NO_WCS", "NO_SIGNAL", "LOW_TRANSPARENCY", "BAD_SEEING")


def read_frame(path) -> tuple[np.ndarray, "fits.Header", WCS | None]:
    """Liest ein Bild (``.fits``, ``.fits.fz``): erste HDU mit 2D-Daten (LCO: ``SCI``); Rueckgabe Daten, Header, WCS."""
    with fits.open(path) as hdul:
        hdu = next((h for h in hdul if getattr(h, "data", None) is not None and h.data.ndim == 2), None)
        if hdu is None:
            raise ValueError(f"{path}: keine 2D-Bilddaten")
        img = np.asarray(hdu.data, dtype=np.float32)
        hdr = hdu.header.copy()
        for k, v in hdul[0].header.items():          # Primaer-Header ergaenzen (Schluessel des Bild-HDU gewinnen)
            if k not in hdr and k not in ("COMMENT", "HISTORY", ""):
                hdr[k] = v
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        w = WCS(hdr)
    return img, hdr, (w if w.has_celestial else None)


def scintillation_mag(aperture_m: float, airmass: float, height_m: float, exptime_s: float) -> float:
    """Szintillationsrauschen eines Sterns in mag (Young-Naeherung).

    Warum: Bei kurzen Belichtungen an kleinen Teleskopen dominiert die Szintillation das Rauschen heller Sterne; sie
    muss im Fehlerbudget stehen, sonst sind die Fehlerbalken zu klein.

    Wie: ``sigma = 0,09 * D^(-2/3) * X^(1,75) * exp(-h/h0) / sqrt(2 t)`` als relativer Fluss (``D`` Teleskopoeffnung in cm,
    ``X`` Luftmasse, ``h`` Hoehe, ``h0`` = 8000 m, ``t`` Belichtung in s); Umrechnung in mag mit 1,0857.

    Parameter: ``aperture_m`` [m], ``airmass``, ``height_m`` [m], ``exptime_s`` [s]. Rueckgabe: mag (1 sigma).

    Grenzen: Die Young-Naeherung unterschaetzt laut Osborn et al. (2015) die mediane Szintillation an mehreren
    Observatorien; die genaue Abweichung hier nicht geprueft. Sie gilt fuer einen Stern, nicht fuer das Ensemble. Am LCO-Satz
    (0,4 m, 1,3 s) ergibt sie ~0,006 mag, die gemessene Comp-Streuung ist groesser (0,03 mag, Ursache nicht abschliessend geklaert).

    Quellen: Young, A. T. 1967, AJ 72, 747, doi:10.1086/110303 (geprueft, Zitat); Osborn, J. et al. 2015, MNRAS 452, 1707,
    doi:10.1093/mnras/stv1400 (geprueft, Zitat; verbesserte Formel mit Turbulenzprofilen). Der Zahlenfaktor 0,09 und
    h0 = 8000 m stammen aus dem Gedaechtnis und sind nicht gegen Young (1967) geprueft.
    """
    d_cm = aperture_m * 100.0
    rel = 0.09 * d_cm ** (-2 / 3) * airmass ** 1.75 * np.exp(-height_m / 8000.0) / np.sqrt(2 * exptime_s)
    return float(1.0857 * rel)


def measure_frame(img, wcs: WCS, stars: pd.DataFrame, hdr=None, cfg=None) -> list[dict]:
    """Aperturphotometrie fuer alle ``stars`` (Spalten ``id, ra, dec``) in einem Bild.

    Warum: Die Differenzphotometrie braucht je Bild und Stern einen Fluss mit Fehler und Qualitaetsangaben; die Positionen
    kommen aus der WCS, damit Ziel und Comps ohne Registrierung der Bilder gefunden werden.

    Wie: Kreisapertur ``ap_r`` und Himmelsring ``ap_r_in``..``ap_r_out`` (Median, ohne Clipping). ``flux = Summe - Himmel *
    Flaeche``. Fehler (ADU) nach der CCD-Gleichung: ``var = F*g + n_ap*(1 + n_ap/n_sky)*(S*g + RN^2)`` (Signal-Poisson plus
    Himmel und Ausleserauschen ueber die Aperturflaeche, korrigiert um die Unsicherheit des Himmelsrings; Dunkelstrom
    vernachlaessigt); Gain ``g``, Ausleserauschen ``RN`` und ``SATURATE`` aus dem Header (``GAIN``, ``RDNOISE``), sonst
    aus ``cfg``. ``n_sat`` zaehlt Pixel >= ``SATURATE`` in der Apertur (Flag ``SAT``), Sterne am Rand erhalten ``EDGE``.
    Mit ``cfg["core_r"]`` (px) wird zusaetzlich der Ring ``core_r``..``ap_r`` gemessen (``flux_ring``, ``flux_ring_err``) —
    Grundlage der Kernkorrektur gesaettigter Sterne in :func:`light_curve`.

    Grenzen: Keine Nachzentrierung, keine PSF-Anpassung; Nachbarsterne in der Apertur werden nicht abgezogen (Auswahl
    der Comps prueft das vorher). Sigma-Clipping auf der Summe ist bewusst aus: ``photutils.ApertureStats`` clippt standardmaessig
    auch die Summe und schnitt helle Sternkerne ab (Fluss 205 statt 251 im Test; Regressionstest ``test_photometry.py``).

    Validierung: ``tests/test_batch.py`` (Fluss vs. Eingabe, 5 %); LCO delta Cep.

    Quellen: CCD-Gleichung nach Howell, S. B. 2006, Handbook of CCD Astronomy, 2. Aufl., Cambridge UP (aus dem Gedaechtnis,
    nicht geprueft); Merline, W. J. & Howell, S. B. 1995, Exp. Astron. 6, 163 (aus dem Gedaechtnis, nicht geprueft).
    Rueckgabe: je Stern ein dict mit x, y, flux, flux_err, sky, peak, n_sat, star_flag (+ flux_ring, flux_ring_err).
    """
    cfg = cfg or CFG
    hdr = hdr or {}
    r_ap, r_in, r_out = cfg["ap_r"], cfg["ap_r_in"], cfg["ap_r_out"]
    gain = float(hdr.get("GAIN") or cfg.get("gain_e_per_adu") or 1.0)
    rn = float(hdr.get("RDNOISE") or cfg.get("readout_noise_e") or 0.0)
    sat = float(hdr.get("SATURATE") or cfg.get("sat_adu"))
    ny, nx = img.shape
    xs, ys = wcs.world_to_pixel_values(stars["ra"].to_numpy(float), stars["dec"].to_numpy(float))
    rows = []
    for sid, x, y in zip(stars["id"], xs, ys):
        row = dict(star_id=sid, x=float(x), y=float(y), flux=np.nan, flux_err=np.nan, sky=np.nan,
                   peak=np.nan, n_sat=0, star_flag="", flux_ring=np.nan, flux_ring_err=np.nan)
        if not (r_out < x < nx - 1 - r_out and r_out < y < ny - 1 - r_out):
            row["star_flag"] = "EDGE"
            rows.append(row)
            continue
        ap = CircularAperture((x, y), r=r_ap)
        an = CircularAnnulus((x, y), r_in=r_in, r_out=r_out)
        sky = float(ApertureStats(img, an, sigma_clip=None).median)
        st = ApertureStats(img, ap, sigma_clip=None)    # ohne Clipping: sonst werden helle Sternkerne abgeschnitten
        flux = float(st.sum) - sky * ap.area
        n_ap, n_sky = ap.area, an.area
        var_e = max(flux, 0.0) * gain + n_ap * (1 + n_ap / n_sky) * (max(sky, 0.0) * gain + rn ** 2)
        mask = ap.to_mask(method="center")
        cut = mask.cutout(img)
        n_sat = int(np.sum((cut >= sat) & (mask.data > 0))) if cut is not None else 0
        row.update(flux=flux, flux_err=float(np.sqrt(var_e) / gain), sky=sky, peak=float(st.max) - sky,
                   n_sat=n_sat, star_flag="SAT" if n_sat else "")
        core_r = cfg.get("core_r")
        if core_r:                                    # Ring ohne Kern: fuer gesaettigte Sterne (siehe light_curve)
            ring = CircularAnnulus((x, y), r_in=core_r, r_out=r_ap)
            fr = float(ApertureStats(img, ring, sigma_clip=None).sum) - sky * ring.area
            var_r = max(fr, 0.0) * gain + ring.area * (1 + ring.area / n_sky) * (max(sky, 0.0) * gain + rn ** 2)
            row.update(flux_ring=fr, flux_ring_err=float(np.sqrt(var_r) / gain))
        rows.append(row)
    return rows


def _process_one(args):
    path, stars, cfg = args
    img, hdr, wcs = read_frame(path)
    t = mid_exposure(hdr)
    info = dict(file=Path(path).name, jd_mid=t.jd, exptime=float(hdr.get("EXPTIME", np.nan)),
                airmass=float(hdr.get("AIRMASS", np.nan)), fwhm_arcsec=float(hdr.get("L1FWHM", np.nan)),
                telescope=str(hdr.get("TELESCOP", "")), filter=str(hdr.get("FILTER", "")))
    if wcs is None:
        return [dict(info, star_id=s, star_flag="NO_WCS") for s in stars["id"]]
    return [dict(info, **r) for r in measure_frame(img, wcs, stars, hdr, cfg)]


def run_batch(paths, stars: pd.DataFrame, cfg=None, workers: int = 4, progress=None) -> pd.DataFrame:
    """Photometrie fuer alle Bilder (Prozesspool). ``progress``: optionaler Iterator-Wrapper (z. B. ``tqdm``)."""
    cfg = cfg or CFG
    jobs = [(str(p), stars, cfg) for p in paths]
    with cf.ProcessPoolExecutor(workers) as ex:
        it = ex.map(_process_one, jobs)
        results = list(progress(it, total=len(jobs)) if progress else it)
    return pd.DataFrame([r for rows in results for r in rows])


def qc_frames(df: pd.DataFrame, roles: dict, cfg=None) -> pd.DataFrame:
    """Setzt Bildflags (Spalte ``frame_flags``, Komma-getrennt; leer = brauchbar).

    Warum: Echte Zeitreihen enthalten leere Bilder, Wolken und Fehlfokus. Ohne Aussortieren verfaelschen sie die Lichtkurve;
    am LCO-Satz waren 58 von 156 Bildern unbrauchbar (docs/testdaten.md).

    Wie: ``roles``: {star_id: 'target'|'comp'|'check'}. Flags je Bild:
    ``NO_WCS`` (keine WCS); ``NO_SIGNAL`` (ein Comp mit Fluss <= 0 oder S/N < ``snr_min``); ``LOW_TRANSPARENCY``
    (Median ueber die Comps von Fluss / Laufmedian des jeweiligen Comps < ``transp_min``: dünne Wolken); ``BAD_SEEING``
    (``fwhm_arcsec`` > ``fwhm_max_arcsec``). Spalte ``transparency`` ist der genannte Median.

    Grenzen: Die Schwellen (10 / 0,6 / 4″, ``CFG``) sind Startwerte ohne Herleitung. Der Laufmedian setzt voraus, dass die
    Mehrheit der Bilder brauchbar ist. ``BAD_SEEING`` liest den Header-FWHM (LCO: ``L1FWHM``); ohne ihn wird nicht geflaggt.

    Quellen: eigene Methode (Transparenz ueber den Comp-Fluss ist gaengige Praxis, keine Einzelquelle).
    """
    cfg = cfg or CFG
    snr_min = cfg.get("snr_min", 10.0)
    transp_min = cfg.get("transp_min", 0.6)
    fwhm_max = cfg.get("fwhm_max_arcsec", 4.0)
    df = df.copy()
    df["role"] = df["star_id"].map(roles)
    comps = df[df["role"] == "comp"].copy()
    comps["snr"] = comps["flux"] / comps["flux_err"]
    ref = comps[comps["snr"] > snr_min].groupby("star_id")["flux"].median()          # Lauf-Median je Comp
    comps["rel"] = comps["flux"] / comps["star_id"].map(ref)
    per = comps.groupby("file").agg(min_flux=("flux", "min"), min_snr=("snr", "min"), transp=("rel", "median"))
    flags = {}
    for f, g in df.groupby("file"):
        fl = []
        if (g["star_flag"] == "NO_WCS").any():
            fl.append("NO_WCS")
        if f in per.index:
            p = per.loc[f]
            if not (p["min_flux"] > 0 and p["min_snr"] >= snr_min):
                fl.append("NO_SIGNAL")
            elif p["transp"] < transp_min:
                fl.append("LOW_TRANSPARENCY")
        elif "NO_WCS" not in fl:
            fl.append("NO_SIGNAL")
        if g["fwhm_arcsec"].iloc[0] > fwhm_max:
            fl.append("BAD_SEEING")
        flags[f] = ",".join(fl)
    df["frame_flags"] = df["file"].map(flags)
    df["transparency"] = df["file"].map(per["transp"])
    return df


def ensemble_mag(f_t, f_c, v_c, f_c_err=None, f_t_err=None, clip: float = 3.0):
    """Magnitude des Ziels aus dem Nullpunkt-Ensemble der Comps (robust, optional gewichtet).

    Warum: Ein einzelner Comp bringt dessen Rauschen und Katalogfehler in die Lichtkurve; ein Ensemble mittelt beides und
    faengt das Ausfallen eines Sterns ab.

    Wie: Nullpunkt je Comp ``zp_i = V_i + 2,5 log10 f_i``. Ausreisser (> ``clip`` * 1,4826 MAD, mindestens 0,005 mag) werden
    ab 4 Comps verworfen. Nullpunkt = Median, mit ``f_c_err`` das mit ``1/sigma^2`` gewichtete Mittel (``sigma_i = 1,0857
    err_i/f_i``). ``mag = -2,5 log10 f_t + zp``. Fehler: ``sd(zp)^2/n`` plus Photonenfehler des Ziels, quadratisch.

    Rueckgabe: ``(mag, err, n_benutzt, zp_streuung)``.

    Grenzen: ``zp_streuung`` enthaelt die Katalogfehler der Comp-V (bei Gaia-abgeleitetem V roter Sterne gross) und ist kein
    reines Rauschmass. Keine Farbterm-Korrektur (siehe KONZEPT.md §11). Kein Ausfall-Ersatz bei < 3 Comps (Aufrufer prueft).

    Validierung: ``tests/test_batch.py`` (Ausreisser, Gewichtung, Fehlerterm).

    Quellen: Idee der Ensemble-Photometrie nach Honeycutt, R. K. 1992, PASP 104, 435, doi:10.1086/133015 (geprueft, Zitat);
    dies ist eine vereinfachte Variante (Median/gewichtetes Mittel statt der vollen Matrixloesung von Honeycutt).
    """
    f_c, v_c = np.asarray(f_c, float), np.asarray(v_c, float)
    ok = f_c > 0
    zp = v_c[ok] + 2.5 * np.log10(f_c[ok])
    keep = np.ones(len(zp), bool)
    if len(zp) >= 4:
        med = np.median(zp)
        mad = 1.4826 * np.median(np.abs(zp - med)) or 1e-9
        keep = np.abs(zp - med) <= clip * max(mad, 0.005)
    zp_k = zp[keep]
    if f_c_err is not None:                       # Gewichtung mit 1/sigma^2 (Photonen-/Himmelsfehler je Comp)
        sig = 1.0857 * np.asarray(f_c_err, float)[ok][keep] / f_c[ok][keep]
        wgt = 1.0 / np.maximum(sig, 1e-4) ** 2
        zp0 = float(np.sum(zp_k * wgt) / np.sum(wgt))
    else:
        zp0 = float(np.median(zp_k))
    sd = float(np.std(zp_k, ddof=1)) if len(zp_k) > 1 else np.nan
    mag = float(-2.5 * np.log10(f_t) + zp0)
    var = (sd ** 2 / len(zp_k) if np.isfinite(sd) else 0.0)
    if f_t_err is not None and f_t > 0:
        var += (1.0857 * f_t_err / f_t) ** 2
    return mag, float(np.sqrt(var)), int(len(zp_k)), sd


def light_curve(df: pd.DataFrame, stars: pd.DataFrame, target_id, cfg=None, site=None,
                aperture_m: float | None = None, core_correct: bool = False) -> pd.DataFrame:
    """Lichtkurve des Ziels (eine Zeile je brauchbarem Bild) mit BJD_TDB, Magnitude, Fehler, Check-Stern.

    Warum: Fasst Messtabelle (:func:`run_batch`), Bildflags (:func:`qc_frames`) und Ensemble (:func:`ensemble_mag`) zur
    Zeitreihe zusammen, die Notebook 05 auswertet und der AAVSO-Export braucht.

    Wie: ``df`` = Ergebnis von :func:`qc_frames`; nur Bilder ohne ``frame_flags`` zaehlen. Ziel-Magnitude per
    :func:`ensemble_mag` (gewichtet, Ausreisser-Verwurf), Check-Stern aus demselben Ensemble (geht nicht in den Nullpunkt
    ein). Fehler: Photonen/Himmel/Ausleserauschen (``flux_err``) und Ensemble-Streuung; mit ``aperture_m`` und ``site`` wird die
    Szintillation des Ziels (:func:`scintillation_mag`) quadratisch addiert und als ``scint_mag`` ausgewiesen. BJD_TDB aus
    ``site`` (:func:`varphot.timeutil.bjd_tdb`); ohne ``site`` bleibt ``bjd_tdb`` NaN.

    **Kernkorrektur** (``core_correct=True``): Ist das Ziel gesaettigt (``n_sat`` > 0), wird statt des abgeschnittenen
    Gesamtflusses der Fluss im Ring ausserhalb des Kerns (``core_r`` in :func:`measure_frame`) benutzt und mit dem Ringanteil
    ``flux_ring/flux`` heller, ungesaettigter Comps (S/N > 50) *desselben Bildes* auf den Gesamtfluss hochgerechnet:
    ``f_ziel = flux_ring_ziel / median(flux_ring_c / flux_c)``. Spalte ``core_corrected`` markiert diese Punkte.
    Warum das noetig ist: Der Saettigungsverlust haengt vom Seeing ab (schaerferes Bild = mehr Fluss im abgeschnittenen Kern);
    an LCO delta Cep korrelierte das Nachtresiduum mit dem FWHM (r = -0,73) und erzeugte 0,13 mag Reststreuung zwischen den
    Naechten. Der Ringanteil der Comps misst die aktuelle PSF je Bild und hebt diese Abhaengigkeit auf.

    Validierung: LCO delta Cep (98 Bilder, 86 gesaettigt): Fourier-Residuum 0,129 -> 0,068 mag, Korrelation mit FWHM
    -0,69 -> -0,07, Lomb-Scargle 5,30 -> 5,363 d (Literatur 5,366 d); ``tests/test_batch.py::test_core_correction_...``.

    Grenzen: Der Kernradius (``core_r`` = 1,5 px) wurde an diesem Datensatz auf kleinstes Residuum gewaehlt, nicht auf die
    Amplitude; die Modellamplitude waechst mit dem Radius (0,75 bei 1,0 px bis 0,99 bei 2,5 px, Literatur ~0,88), der Radius
    ist also nicht allgemeingueltig (NB04 Schritt 4b prueft mehrere). Bleeding reicht bis ~8 px, die Maske deckt es nicht
    ab. Die Ringmethode setzt voraus, dass Comps und Ziel dieselbe PSF haben (gleiches Bildfeld, aehnliche Position).
    Bei defokussiertem, ungesaettigtem Ziel entfaellt die Korrektur.

    Quellen: *eigene Methode*; verwandt sind Photometrie aus den ungesaettigten PSF-Fluegeln bzw. mit maskiertem Kern
    (vgl. STScI ACS-Notebook zu Saettigungsspuren
    https://spacetelescope.github.io/hst_notebooks/notebooks/ACS/acs_saturation_trails/acs_saturation_trails.html; DECaPS2,
    arXiv:2206.11909, zur Verfaelschung durch fast gesaettigte Sterne — beide nur als Hinweis gelesen, kein Rezept uebernommen).
    Honeycutt 1992 (Ensemble) siehe :func:`ensemble_mag`.
    """
    cfg = cfg or CFG
    roles = dict(zip(stars["id"], stars["role"]))
    V = dict(zip(stars["id"], stars["V"]))
    tgt = stars[stars["id"] == target_id].iloc[0]
    out = []
    for f, g in df[df["frame_flags"] == ""].groupby("file"):
        g = g.set_index("star_id")
        comp_ids = [i for i in g.index if roles.get(i) == "comp" and np.isfinite(g.loc[i, "flux"])]
        if len(comp_ids) < 3 or not np.isfinite(g.loc[target_id, "flux"]) or g.loc[target_id, "flux"] <= 0:
            continue
        fc = g.loc[comp_ids, "flux"].to_numpy()
        f_t, f_t_err, corrected = g.loc[target_id, "flux"], g.loc[target_id, "flux_err"], False
        if core_correct and g.loc[target_id, "n_sat"] > 0 and np.isfinite(g.loc[target_id].get("flux_ring", np.nan)):
            bright = [i for i in comp_ids if g.loc[i, "flux"] / g.loc[i, "flux_err"] > 50 and g.loc[i, "n_sat"] == 0]
            if bright:
                frac = float(np.median(g.loc[bright, "flux_ring"] / g.loc[bright, "flux"]))
                f_t, f_t_err, corrected = g.loc[target_id, "flux_ring"] / frac, g.loc[target_id, "flux_ring_err"] / frac, True
        m, e, n, sd = ensemble_mag(f_t, fc, [V[i] for i in comp_ids],
                                   f_c_err=g.loc[comp_ids, "flux_err"].to_numpy(), f_t_err=f_t_err)
        row = dict(file=f, jd_mid=g["jd_mid"].iloc[0], mag=m, mag_err=e, n_comps=n, zp_scatter=sd,
                   airmass=g["airmass"].iloc[0], fwhm_arcsec=g["fwhm_arcsec"].iloc[0],
                   target_sat=bool(g.loc[target_id, "n_sat"] > 0), core_corrected=corrected, transparency=g["transparency"].iloc[0],
                   sky=g.loc[target_id, "sky"])
        if aperture_m and site is not None and np.isfinite(row["airmass"]):
            row["scint_mag"] = scintillation_mag(aperture_m, row["airmass"], site.height_m, g["exptime"].iloc[0])
            row["mag_err"] = float(np.hypot(row["mag_err"], row["scint_mag"]))       # Szintillation des Ziels quadratisch addiert
        chk = [i for i in g.index if roles.get(i) == "check" and np.isfinite(g.loc[i, "flux"]) and g.loc[i, "flux"] > 0]
        if chk:
            mk, _, _, _ = ensemble_mag(g.loc[chk[0], "flux"], fc, [V[i] for i in comp_ids])
            row["check_mag"] = mk
            row["check_minus_cat"] = mk - V[chk[0]]
        out.append(row)
    if not out:
        return pd.DataFrame(columns=["file", "jd_mid", "mag", "mag_err", "n_comps", "bjd_tdb"])
    lc = pd.DataFrame(out).sort_values("jd_mid").reset_index(drop=True)
    if len(lc):
        from astropy.time import Time
        lc["bjd_tdb"] = (bjd_tdb(Time(lc["jd_mid"].to_numpy(), format="jd", scale="utc"), tgt["ra"], tgt["dec"], site)
                         if site is not None else np.nan)
    return lc


def stars_from_field_config(record: dict, extra_roles=("comp", "check")) -> pd.DataFrame:
    """Sterntabelle (``id, role, ra, dec, V, V_err``) aus einer NB03-``field_config.json`` (Ziel + Comps/Check)."""
    z = record["ziel"]
    rows = [dict(id="target", role="target", ra=z["ra"], dec=z["dec"], V=z["V"], V_err=np.nan)]
    for s in record["sterne"]:
        if s["rolle"] in extra_roles:
            rows.append(dict(id=s["label"], role=s["rolle"], ra=s["ra"], dec=s["dec"], V=s["V"], V_err=s["V_err"]))
    return pd.DataFrame(rows)
