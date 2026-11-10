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

import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

METHODS = {
    "mono": "Monochrom-Kamera + Filter (z. B. V)",
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
    """Median-FWHM, robuste Streuung und Zahl der Sterne aus :func:`star_metrics`."""
    f = df["fwhm"].dropna().to_numpy()
    f = f[(f > 0.8) & (f < 200)]
    if len(f) == 0:
        return dict(fwhm=float("nan"), scatter=float("nan"), n=0)
    return dict(fwhm=float(np.median(f)), scatter=float(1.4826 * np.median(np.abs(f - np.median(f)))), n=int(len(f)))


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


def night_altitudes(ra_deg: float, dec_deg: float, site, date: dt.date | None = None, step_min: int = 30) -> pd.DataFrame:
    """Hoehe des Ziels und der Sonne ueber eine Nacht (UTC-Zeitgitter, ``step_min``) am Standort ``site`` (:class:`varphot.observer.Site`).

    Warum: Planung — wann steht das Ziel hoch genug (Luftmasse) und ist es dunkel? Wie: ``astropy`` AltAz fuer Ziel und Sonne; Spalten ``utc``, ``alt_target``,
    ``airmass``, ``alt_sun``, ``dark`` (Sonne < −12°, nautische Daemmerung) und ``ok`` (dunkel und Ziel > 30°). Grenzen: ohne Mond, ohne Wetter;
    Zeitgitter von 12:00 UT bis 12:00 UT des Folgetags (fuer Mitteleuropa deckt das die Nacht ab, fuer andere Zeitzonen ``date`` anpassen).
    """
    from astropy import units as u
    from astropy.coordinates import AltAz, SkyCoord, get_sun
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
    return df


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
