"""Ablauf der Notebooks 01 (Vorbereitung) und 02 (Messung) als getestete Funktionen — die Notebooks zeigen nur Entscheidungen und Ergebnisse.

Autor: Axel Pospischil. Stand 2026-11-10 (KONZEPT §12.4).

Warum: Die Logik stand in langen Notebook-Zellen (nicht testbar, schwer zu lesen, von der Demo mit den LCO-Daten gepraegt). Jetzt arbeiten die Funktionen auf einer :class:`varphot.session.Session`; das Notebook
fragt einmal (Formular), ruft sie nacheinander auf und zeigt Tabellen und Bilder.
Inhalt: Bilder sammeln und das Referenzbild waehlen (:func:`collect_frames`, :func:`pick_reference`), Kalibrierung ueber Siril (:func:`calibration_step`), Plate-Solve mit Gaia-Pruefung
(:func:`solve_reference`, :func:`wcs_quality`), Comp-Auswahl und ``field_config.json`` (:func:`select_field`), Messung mit WCS aus Kopf oder Registrierung, Qualitaetsflags, Lichtkurve und Periode (:func:`measure`,
:func:`analyse_period`), Apertur aus dem Referenzbild (:func:`aperture_from_image`).
"""
from __future__ import annotations

import datetime
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .session import Session

GREEK = {"alf": "Alpha", "bet": "Beta", "gam": "Gamma", "del": "Delta", "eps": "Epsilon", "zet": "Zeta", "eta": "Eta", "tet": "Theta", "the": "Theta", "iot": "Iota", "kap": "Kappa", "lam": "Lambda",
         "mu": "Mu", "nu": "Nu", "ksi": "Xi", "xi": "Xi", "omi": "Omicron", "pi": "Pi", "rho": "Rho", "sig": "Sigma", "tau": "Tau", "ups": "Upsilon", "phi": "Phi", "chi": "Chi", "psi": "Psi", "ome": "Omega"}
FITS_PATTERNS = ("*.fits.fz", "*.fits", "*.fit", "*.fts")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Bilder und Referenz
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def collect_frames(sess: Session) -> list[Path]:
    """Kalibrierte Bilder der Reihe: ``sess.frames_dir`` (sonst ``process/``); mit ``pp_light_*`` nur diese; ``notes['telescope']`` filtert nach ``TELESCOP`` (Archivdaten mehrerer Teleskope).

    Warum: Siril legt in ``process/`` auch Zwischenprodukte ab (``bias_``, ``dark_``, ``flat_``, ``light_``); nur die kalibrierten Lights (``pp_light_``) gehoeren zur Reihe. Leere Liste, wenn nichts da ist (Aufrufer meldet).
    """
    from astropy.io import fits
    d = Path(sess.frames_dir) if sess.frames_dir else sess.path("process")
    files = sorted({f for pat in FITS_PATTERNS for f in d.glob(pat)}) if d.is_dir() else []
    pp = [f for f in files if f.name.startswith("pp_light")]
    files = pp or [f for f in files if not re.match(r"(bias|dark|flat|light)_", f.name)]
    tel = sess.notes.get("telescope")
    if tel:
        keep = []
        for f in files:
            with fits.open(f) as h:
                hdr = h["SCI"].header if "SCI" in h else h[0].header
                if str(hdr.get("TELESCOP", "")) == tel:
                    keep.append(f)
        files = keep
    return files


def pick_reference(frames: list[Path], n_try: int = 8, fwhm_guess: float = 4.0) -> tuple[Path, pd.DataFrame]:
    """Waehlt das Referenzbild: unter bis zu ``n_try`` gleichmaessig verteilten Bildern das mit den meisten scharfen Sternen (``Sterne / FWHM``).

    Warum: Das Referenzbild wird mit ASTAP geloest und ist der Bezug der Registrierung; es soll viele, scharfe, ungesaettigte Sterne haben. Bilder mit WCS-Fehlermarke im Kopf (``WCSERR`` ≠ 0, LCO) werden
    uebersprungen. Rueckgabe: Pfad und Tabelle der Kandidaten (``file, n_stars, fwhm, score``). Grenzen: schnelle Naeherung ohne Pruefung der Himmelshelligkeit/Wolken. Validierung: ``tests/test_workflow.py``.
    """
    from .batch import read_frame
    from .plan import fwhm_summary, star_metrics
    if not frames:
        raise ValueError("keine Bilder zur Auswahl des Referenzbildes")
    idx = np.unique(np.linspace(0, len(frames) - 1, min(n_try, len(frames))).astype(int))
    rows = []
    for i in idx:
        img, hdr, _ = read_frame(frames[i])
        if int(hdr.get("WCSERR", 0) or 0) != 0:
            continue
        df = star_metrics(img, max_adu=float(hdr.get("SATURATE", 0) or 0) or None, fwhm_guess=fwhm_guess, max_fit=30)
        fw = fwhm_summary(df)
        n = int(len(df[~df["saturated"]]))
        rows.append(dict(file=frames[i].name, n_stars=n, fwhm=fw["fwhm"], score=(n / fw["fwhm"]) if fw["fwhm"] and np.isfinite(fw["fwhm"]) else 0.0, _i=int(i)))
    if not rows:
        return frames[0], pd.DataFrame(columns=["file", "n_stars", "fwhm", "score"])
    tab = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    return frames[int(tab.iloc[0]["_i"])], tab.drop(columns="_i")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Kalibrierung (Siril)
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def calibration_step(sess: Session, run: bool = True) -> dict:
    """Erzeugt das Siril-Kalibrierungsskript aus den Ordnern der Sitzung (``scripts/calibrate.ssf``) und fuehrt es aus, wenn ``run`` und Siril vorhanden.

    Rueckgabe ``dict(status, script, kinds, log, frames)``; ``status``: ``fertig`` (Lights kalibriert), ``skript`` (Skript liegt bereit, Siril fehlt/``run=False``), ``fehler`` (Siril lief, brachte aber keine Bilder),
    ``keine_lights`` (kein Bild in ``lights/``). **Nicht mit echtem Siril getestet** (``varphot.siril``).
    """
    from . import siril
    kinds = {d: siril.sequence_kind(sess.path(d)) for d in ("lights", "darks", "flats", "biases")}
    if not kinds["lights"]:
        return dict(status="keine_lights", script=None, kinds=kinds, log="lights/ ist leer oder fehlt", frames=[])
    script = siril.write_script(sess.path("scripts", "calibrate.ssf"), siril.build_calibration_script(sess.method or "mono", kinds))
    sess.path("masters").mkdir(exist_ok=True)
    sess.path("process").mkdir(exist_ok=True)
    if not run or not siril.find_siril():
        return dict(status="skript", script=script, kinds=kinds, log="" if run is False else "Siril nicht gefunden", frames=siril.calibrated_frames(sess.path("process")))
    ok, log = siril.run_script(script, sess.path())
    frames = siril.calibrated_frames(sess.path("process"))
    return dict(status="fertig" if ok and frames else "fehler", script=script, kinds=kinds, log=log, frames=frames)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Plate-Solve und Pruefung
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def solve_reference(sess: Session, ref: Path, radius_deg: float = 10.0, astap: str | None = None, timeout: int = 300, fov_deg: float | None = None):
    """Loest das Referenzbild (ASTAP, Fallback WCS im Kopf) und merkt sich Bild und ``.wcs`` in der Sitzung. Rueckgabe ``(SolveResult, Kurzbefund)`` (:func:`varphot.astrometry.plate_solve_summary`).

    ``fov_deg``: Bildhoehe in Grad (NB00: kurze Seite des Feldes aus Sensor und Brennweite); ``None`` = ASTAP bestimmt sie aus dem Kopf (``PIXSCALE``/``FOCALLEN``). Das Original bleibt unveraendert; ASTAP legt ``<bild>.wcs`` daneben. Ohne Loesung (``wcs`` leer) ``RuntimeError`` mit Hinweisen.
    """
    from .astrometry import ASTAP_DEFAULT, plate_solve_summary, solve_image
    from .batch import read_frame
    res = solve_image(ref, astap=astap or ASTAP_DEFAULT, radius_deg=radius_deg, timeout=timeout, fov_deg=fov_deg)
    if res.wcs is None:
        raise RuntimeError("Weder ASTAP noch der FITS-Kopf liefern eine WCS: " + "; ".join(res.notes) + " — Sterne? Sterndatenbank? Suchradius?")
    side = Path(ref).with_suffix(".wcs")
    img, _, _ = read_frame(ref)
    sess.update(ref_frame=str(ref), ref_wcs=str(side) if side.exists() else "")
    summ = plate_solve_summary(res, img.shape) if res.source == "ASTAP" else dict(solved=True, source=res.source, scale_arcsec=round(float(np.sqrt(abs(np.linalg.det(res.wcs.pixel_scale_matrix)))) * 3600, 3))
    return res, summ


def load_reference(sess: Session):
    """``(Bild, Kopf, WCS)`` des Referenzbildes: WCS aus der ASTAP-``.wcs`` (wenn vorhanden), sonst aus dem Kopf; ``ValueError`` ohne beides."""
    from .astrometry import _wcs_from_header, read_wcs_sidecar
    from .batch import read_frame
    if not sess.ref_frame:
        raise ValueError("Sitzung hat kein Referenzbild — Notebook 01 ausfuehren")
    img, hdr, w = read_frame(sess.ref_frame)
    if sess.ref_wcs and Path(sess.ref_wcs).exists():
        w = _wcs_from_header(read_wcs_sidecar(Path(sess.ref_wcs))) or w
    if w is None:
        raise ValueError("keine WCS fuer das Referenzbild")
    return img, hdr, w


def wcs_quality(wcs, img, hdr, fwhm_px: float = 5.0, nsigma: float = 10.0) -> dict:
    """Gegenpruefung der WCS an Gaia DR3 (Netz noetig): Versatz, Streuung, Urteil. Ohne Netz/Treffer ``dict(checked=False, note=...)`` — nie eine Ausnahme.

    Wie bisher in der alten NB02 (jetzt NB01) (:func:`varphot.wcscheck.check_wcs`): Aufnahmeepoche aus ``DATE-OBS``/``DATE-END``, Gaia-Kegel um die Bildmitte, erkannte Sterne gegen Gaia. Grenzen: braucht mindestens
    einige helle, ungesaettigte Sterne; Ergebnis nur fuer geloeste (ASTAP-)Bilder sinnvoll.
    """
    from astropy.time import Time

    from .detect import detect
    from .wcscheck import check_wcs, gaia_field
    try:
        ny, nx = np.asarray(img).shape
        src, _, _ = detect(np.asarray(img, float), fwhm=fwhm_px, nsigma=nsigma, background="2d")
        if src is None or len(src) < 5:
            return dict(checked=False, note="zu wenige Sterne fuer die Gaia-Pruefung")
        t0 = Time(hdr["DATE-OBS"])
        t1 = Time(hdr["DATE-END"]) if "DATE-END" in hdr else t0
        epoch = (t0.jyear + t1.jyear) / 2
        ra0, dec0 = (float(v) for v in wcs.pixel_to_world_values(nx / 2, ny / 2))
        scale_deg = float(np.sqrt(abs(np.linalg.det(wcs.pixel_scale_matrix))))
        gaia = gaia_field(ra0, dec0, 0.5 * float(np.hypot(nx, ny)) * scale_deg + 0.05, gmax=14.0, gmin=9.0)
        chk = check_wcs(wcs, (src["x_centroid"], src["y_centroid"]), gaia, epoch, (ny, nx))
        return dict(checked=True, verdict=chk.verdict, offset_arcsec=chk.offset_arcsec, rms_arcsec=chk.rms_arcsec, n_match=chk.n_match, recovery=chk.recovery, pixel_scale_arcsec=chk.pixel_scale_arcsec, chk=chk)
    except Exception as e:                                         # Netz, Format, zu wenig Treffer: nur melden
        return dict(checked=False, note=f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Feld und Comps
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def vsp_name_candidates(name: str, simbad_name: str = "") -> list[str]:
    """Schreibweisen fuer die AAVSO-VSP-Abfrage: Eingabe, SIMBAD-Name ohne ``* ``, griechische Abkuerzung ausgeschrieben (``del Cep`` → ``Delta Cep``)."""
    cands = []
    for n in (name, re.sub(r"^\*+\s*", "", simbad_name or "")):
        n = n.strip()
        if not n:
            continue
        parts = n.split()
        full = " ".join([GREEK.get(parts[0].lower(), parts[0])] + parts[1:]) if parts else n
        for c in (full, n):
            if c and c not in cands:
                cands.append(c)
    return cands


def select_field(sess: Session, plan=None, maglimit: float = 11.0, use_gaia_fill: bool = True, rules: dict | None = None, force: bool = False, gaia_check: bool = True, min_comps: int = 6) -> dict:
    """Comp- und Check-Sterne aus VSP (+ Gaia) fuer das Ziel der Sitzung, Feld und Winkel aus der WCS des Referenzbildes; schreibt ``field_config.json`` und traegt sie in die Sitzung ein.

    Regeln aus dem Plan (NB00): ``comp_v_range`` unten = hellster zulaessiger Comp, ``comp_bv_abs`` bei Bayer/RGB-Filter, keine Gaia-Ergaenzung fuer TB/TR/B/R (B/R-Werte muessen AAVSO sein; KONZEPT §11.7).
    ``min_comps``: darunter werden die Farb-/Randregeln stufenweise gelockert (vom Nutzer gesetzte bleiben; jede Stufe steht in ``warnings``). ``gaia_check``: Nachbarn/Variabilitaet der VSP-Sterne gegen Gaia pruefen (Netz; ``False`` ueberspringt das). Rueckgabe ``dict(res, record, path, counts, warnings, target)``. Ohne Netz ``RuntimeError`` (SIMBAD/VSP noetig). Validierung: ``tests/test_workflow.py`` (Netz gemockt) und LCO δ Cep.
    """
    from . import __version__
    from .astrometry import field_from_wcs
    from .vsp import VSP_CFG, fetch_vsp, fill_with_gaia, resolve_target, select_comps_catalog
    img, hdr, w = load_reference(sess)
    warn = []
    f = field_from_wcs(w, img.shape)
    field_deg, pa = f["field_deg"], f["pa_deg"]
    fov = min(180, math.ceil(60 * 1.5 * max(field_deg)))
    try:
        target = resolve_target(sess.target)
    except Exception as e:
        if plan is None:
            raise RuntimeError(f"SIMBAD nicht erreichbar ({e}) und kein Plan mit Zielkoordinaten") from e
        target = dict(name=plan.target, ra=plan.ra_deg, dec=plan.dec_deg, otype="?", B=None, V=plan.v_mean, BV=None)
        warn.append(f"SIMBAD nicht erreichbar — Koordinaten und V aus dem Plan ({e})")
    rules = dict(rules or {})
    if plan is not None:
        if plan.v_comp_min is not None:
            rules.setdefault("comp_v_range", [max(5.5, plan.v_comp_min), 10.5])
        if plan.method in ("osc", "dslr") or plan.aavso_filter in ("TG", "TB", "TR"):
            rules.setdefault("comp_bv_abs", [0.3, 1.0])
        if plan.aavso_filter in ("TB", "TR", "B", "R"):
            use_gaia_fill = False
            warn.append("Gaia-Ergaenzung aus: fuer TB/TR/B/R nur AAVSO-Sequenz-Comps")
    if plan is not None and plan.aperture and "comp_r_iso_arcsec" not in rules:           # kein Nachbar im Himmelsring: Radius in Bogensekunden aus Apertur und Pixelskala (die Vorgabe 36″ gilt nur fuer 1,44″/px)
        scale = float(np.sqrt(abs(np.linalg.det(w.pixel_scale_matrix)))) * 3600.0 * (2.0 if plan.method in ("osc", "dslr") else 1.0)
        rules["comp_r_iso_arcsec"] = round(float(plan.aperture["ap_r_out"]) * scale, 1)
        warn.append(f"Nachbar-Radius aus der Apertur: {rules['comp_r_iso_arcsec']}″ ({plan.aperture['ap_r_out']} px × {scale:.2f}″/px)")
    cfg = {"field_deg": field_deg, "field_pa_deg": pa, **rules}
    vsp, vsp_used, errors = None, None, []
    for cand in vsp_name_candidates(sess.target, target.get("name", "")):
        try:
            vsp = fetch_vsp(cand, fov_arcmin=fov, maglimit=maglimit, force=force)
            vsp_used = cand
            break
        except Exception as e:
            errors.append(f"{cand}: {type(e).__name__}")
    if vsp is None:
        raise RuntimeError("AAVSO-VSP lieferte keine Sequenz (" + "; ".join(errors) + ") — Netz? Schreibweise des Ziels?")
    def run(cfg_):
        r_ = select_comps_catalog(vsp, target, cfg_, use_gaia=gaia_check)
        n0 = int((np.asarray(r_["role"]).astype(str) == "comp").sum())
        if use_gaia_fill:
            r_ = fill_with_gaia(r_, target, cfg_)
        return r_, n0
    res, n_vsp = run(cfg)
    if int((np.asarray(res["role"]).astype(str) == "comp").sum()) < min_comps:               # kleine Felder: Regeln schrittweise lockern, jeder Schritt wird gemeldet
        for label, changes in (("Gaia-Farbtoleranz 0,9", {"gaia_bprp_tol": 0.9}), ("Farbtoleranz B−V 0,55", {"comp_bv_tol": 0.55}),
                               ("Gaia-Farbtoleranz 1,2, B−V 0,7, Feldrand 0,02°", {"gaia_bprp_tol": 1.2, "comp_bv_tol": 0.7, "field_margin_deg": 0.02}),
                               ("schwaechere Comps bis V = 12,5 (S/N in NB00 3b pruefen)", {"comp_v_range": [cfg.get("comp_v_range", VSP_CFG["comp_v_range"])[0], 12.5]})):
            changes = {k: v for k, v in changes.items() if k not in rules}                 # vom Nutzer gesetzte Regeln bleiben
            if not changes:
                continue
            cfg = {**cfg, **changes}
            res, n_vsp = run(cfg)
            n = int((np.asarray(res["role"]).astype(str) == "comp").sum())
            warn.append(f"nur wenige Comps im kleinen Feld → Regeln gelockert ({label}): jetzt {n}")
            if n >= min_comps:
                break
    roles = np.asarray(res["role"]).astype(str)
    if (roles == "check").sum() == 0 and (roles == "comp").sum() >= 5:                      # ohne Check-Stern keine Gegenprobe: ein mittelheller Comp (bevorzugt aus der AAVSO-Sequenz) wird Check
        cand = np.flatnonzero(roles == "comp")
        src_ = np.asarray(res["source"]).astype(str)[cand] if "source" in res.colnames else np.array(["VSP"] * len(cand))
        pool = cand[src_ != "Gaia"] if (src_ != "Gaia").any() else cand
        k = pool[int(np.argmin(np.abs(np.asarray(res["V"], float)[pool] - np.median(np.asarray(res["V"], float)[cand]))))]
        res["role"] = np.where(np.arange(len(res)) == k, "check", np.asarray(res["role"]).astype(str)).astype("U16")
        roles = np.asarray(res["role"]).astype(str)
        warn.append(f"kein Check-Stern gefunden — {res['label'][k]} (mittelheller Comp, V = {float(res['V'][k]):.2f}) dient als Check")
    counts = {k: int((roles == k).sum()) for k in ("comp", "check", "reserve", "verworfen")}
    if counts["comp"] < 4:
        warn.append(f"nur {counts['comp']} Comps (mindestens 4 empfohlen) — anderes Feld, Belichtung/Regeln pruefen")
    sel = res[[str(r) in ("comp", "check", "reserve") for r in res["role"]]]
    has_rc = "Rc" in res.colnames
    record = {
        "erzeugt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "varphot": __version__, "ziel": target,
        "vsp": {"stern": vsp_used, "fov_arcmin": fov, "maglimit": maglimit, "chartid": vsp.meta.get("chartid")},
        "regeln": {k: (list(v) if isinstance(v, tuple) else v) for k, v in {**VSP_CFG, **cfg}.items()},
        "sterne": [{"rolle": str(r["role"]), "auid": str(r["auid"]), "label": str(r["label"]), "ra": float(r["ra"]), "dec": float(r["dec"]), "V": float(r["V"]), "V_err": float(r["V_err"]),
                    "B": float(r["B"]), "B_err": float(r["B_err"]), "G": None if r["G"] != r["G"] else float(r["G"]),
                    "R": None if (not has_rc or r["Rc"] != r["Rc"]) else float(r["Rc"])} for r in sel],
    }
    out = sess.results_dir() / "field_config.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    sess.update(field_config=str(out))
    return dict(res=res, record=record, path=out, counts=counts, n_vsp=n_vsp, warnings=warn, target=target, field_deg=field_deg, pa_deg=pa)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Messung
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def aperture_from_image(img, hdr, fwhm_guess: float = 4.0, bayer: str | None = None) -> dict:
    """Apertur (``ap_r, ap_r_in, ap_r_out`` + Befund) aus einem Bild nach :func:`varphot.aperture.optimal_aperture`; Gain/Ausleserauschen aus dem Kopf (``GAIN``, ``RDNOISE``), sonst 1/0.

    ``bayer``: Bayer-Muster (``RGGB`` …) → Gruenebene (Rohbild-Pixel halbiert). Ohne messbare Sterne ``ValueError``.
    """
    from .aperture import optimal_aperture
    from .plan import fwhm_summary, green_plane, star_metrics
    work = green_plane(img, bayer) if bayer else np.asarray(img, float)
    df = star_metrics(work, max_adu=float(hdr.get("SATURATE", 0) or 0) or None, fwhm_guess=fwhm_guess, max_fit=40)
    fs = fwhm_summary(df)
    if not np.isfinite(fs["fwhm"]):
        raise ValueError("keine ungesaettigten, isolierten Sterne im Bild — Apertur nicht bestimmbar")
    return optimal_aperture(work, df, fs["fwhm"], gain=float(hdr.get("GAIN", 1.0) or 1.0), read_noise_e=float(hdr.get("RDNOISE", 0.0) or 0.0))


def measure(sess: Session, plan=None, wcs_mode: str | None = None, ap: dict | None = None, core_r: float | None = 1.5, workers: int = 4, progress=None, site=None, aperture_m: float | None = None, n_bootstrap: int = 200) -> dict:
    """Photometrie der ganzen Reihe → Bildflags → Lichtkurve; schreibt ``messtabelle.csv`` und ``zeitreihe.csv`` in den Ergebnisordner der Sitzung.

    ``wcs_mode``: ``auto`` (Standard: Kopf, wo vorhanden, sonst Registrierung gegen das Referenzbild), ``header``, ``register``. ``ap``: Aperturradien (Standard: Plan, sonst aus dem Referenzbild). ``core_r``: Kernmaske
    fuer ein gesaettigtes Ziel [px] (``None``/0 = aus; angewandt nur, wenn das Ziel in Bildern saettigt). ``site``: Standort (:class:`varphot.observer.Site`); fehlt er, wird er aus dem Kopf des ersten Bildes oder
    der Beobachter-Datei genommen. Rueckgabe ``dict(table, lc, frames, ap, flags, notes)``. Bilder ohne WCS (Registrierung gescheitert) tragen ``NO_WCS``. Validierung: ``tests/test_workflow.py``, LCO δ Cep (KONZEPT §12.3/§12.4).
    """
    from . import skip_if_fresh
    from .batch import light_curve, qc_frames, read_frame, read_measurements, run_batch, stars_from_field_config
    from .config import CFG
    from .registration import bright_sources
    if not sess.field_config or not Path(sess.field_config).exists():
        raise ValueError("Sitzung hat keine field_config.json — Notebook 01 ausfuehren")
    frames = collect_frames(sess)
    if not frames:
        raise ValueError(f"keine Bilder in {sess.frames_dir or sess.path('process')}")
    notes = []
    record = json.loads(Path(sess.field_config).read_text())
    stars = stars_from_field_config(record)
    stars["id"] = stars["id"].astype(str)
    roles = dict(zip(stars["id"], stars["role"]))
    wcs_mode = wcs_mode or sess.wcs_mode or "auto"
    img_r, hdr_r, w_r = load_reference(sess)
    if ap is None:
        ap = dict(plan.aperture) if plan is not None and plan.aperture else None
    if ap is None:
        a = aperture_from_image(img_r, hdr_r)
        ap = {k: a[k] for k in ("ap_r", "ap_r_in", "ap_r_out")}
        notes.append(f"Apertur aus dem Referenzbild (Wachstumskurve/S/N): {ap}")
    fwhm_ref = (sess.ref_fwhm_px or (plan.fwhm_px if plan is not None and plan.fwhm_px else None) or 4.0)
    reference = dict(xy=bright_sources(img_r, fwhm_ref), wcs=w_r, fwhm=fwhm_ref * (plan.defocus_factor or 1.0 if plan is not None else 1.0), nsigma=6.0)
    cfg = {**CFG, **ap, "core_r": core_r or None}
    out = sess.results_dir()
    raw = out / f"messtabelle_roh_{wcs_mode}_ap{ap['ap_r']}-{ap['ap_r_in']:g}-{ap['ap_r_out']}_core{core_r or 0:g}.csv"
    if skip_if_fresh(raw, sess.field_config, *[str(p) for p in frames], verbose=False):
        tab = read_measurements(raw)
        notes.append("Messtabelle aus dem Zwischenspeicher (Bilder und Feld unveraendert)")
    else:
        tab = run_batch(frames, stars, cfg, workers=workers, progress=progress, reference=reference, wcs_mode=wcs_mode)
        tab["star_id"] = tab["star_id"].astype(str)
        tab.to_csv(raw, index=False)
    tab["star_id"] = tab["star_id"].astype(str)
    tab = qc_frames(tab, roles, cfg)
    if site is None:
        from .timeutil import site_from_header
        site = site_from_header(read_frame(frames[0])[1])
        if site is None:
            from .observer import all_sites, load_config
            obs, own = load_config()
            site = next((s for s in all_sites(own) if s.name == obs.site_name), None)
    if site is None:
        notes.append("Kein Standort — BJD_TDB und Szintillation entfallen (NB00/Einrichtung: Standort speichern)")
    sat = bool(((tab["star_id"] == "target") & (tab["n_sat"] > 0)).any()) if "n_sat" in tab else False
    lc = light_curve(tab, stars, "target", site=site, aperture_m=aperture_m if site is not None else None, core_correct=bool(core_r) and sat and "flux_ring" in tab and tab["flux_ring"].notna().any(), n_bootstrap=n_bootstrap)
    fl = tab.drop_duplicates("file")[["file", "frame_flags", "wcs_source", "reg_match", "reg_rms_px", "transparency", "fwhm_arcsec"]] if "wcs_source" in tab else tab.drop_duplicates("file")[["file", "frame_flags"]]
    tab.to_csv(out / "messtabelle.csv", index=False)
    lc.to_csv(out / "zeitreihe.csv", index=False)
    flags = fl["frame_flags"].replace("", "brauchbar").value_counts().to_dict()
    return dict(table=tab, lc=lc, frames=fl, ap=ap, flags=flags, notes=notes, results=out, wcs_mode=wcs_mode, core_used=bool(core_r) and sat)


def analyse_period(lc: pd.DataFrame, pmin: float | None = None, pmax: float | None = None, time_col: str = "bjd_tdb") -> dict:
    """Perioden-Suche (Lomb-Scargle, Fourier-Anpassung mit 3 Harmonischen) der Lichtkurve.

    Ohne Vorgabe: ``pmax`` = halbe Zeitbasis (mindestens zwei Zyklen), ``pmin`` = 0,1 d. Rueckgabe ``dict(period, harmonic, freq, power, top)`` (``top`` = drei hoechste Maxima, Perioden). Bei zu wenigen Punkten
    (< 8) oder Zeitbasis < 0,3 d ``ValueError``. Grenzen: Aliase bei lueckenhaften Daten (Zeitbasis kurz gegen die Periode); die Fourier-Anpassung sucht nur im Bereich um die LS-Periode (±15 %).
    Validierung: ``tests/test_workflow.py`` (synthetischer Cepheide).
    """
    from astropy.timeseries import LombScargle

    from .periodfit import harmonic_fit
    d = lc.dropna(subset=[time_col, "mag"])
    if len(d) < 8:
        raise ValueError(f"nur {len(d)} Punkte — Periodensuche braucht mindestens 8")
    t, y = d[time_col].to_numpy(float), d["mag"].to_numpy(float)
    span = t.max() - t.min()
    if span < 0.3:
        raise ValueError(f"Zeitbasis {span:.2f} d zu kurz fuer eine Periodensuche")
    pmax = pmax or span / 2
    pmin = pmin or 0.1
    freq = np.linspace(1 / pmax, 1 / pmin, 60000)
    power = LombScargle(t, y).power(freq)
    k = int(np.argmax(power))
    P = float(1 / freq[k])
    order = np.argsort(power)[::-1]
    top, used = [], []
    for j in order:
        p = float(1 / freq[j])
        if all(abs(p - q) / q > 0.05 for q in used):
            used.append(p); top.append((p, float(power[j])))
        if len(top) == 3:
            break
    hf = harmonic_fit(t, y, 0.85 * P, 1.15 * P)
    return dict(period=P, harmonic=hf, freq=freq, power=power, top=top, span=float(span), n=int(len(d)))


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Demo mit echten Testdaten
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def prepare_lco_demo(sess: Session, data_dir=None, telescope: str = "0m4-11", n_probe: int = 3) -> dict:
    """Richtet die Sitzung fuer die echten LCO-Testdaten (δ Cep, Filter V, ``tools/download_testdata.py lco-dcep``) ein: Probebilder und ein scharfes Referenzbild als Verknuepfungen in ``probe/``,
    ``frames_dir`` = Archivordner, ``notes['telescope']``, ``wcs_mode='header'``, Ziel δ Cep, Methode ``mono``, Filter V.

    Warum: Die Notebooks sollen sich mit echten Bildern ausprobieren lassen, ohne eigene Aufnahmen. Waehlt unter den Bildern des Teleskops solche ohne WCS-Fehlermarke (``WCSERR`` = 0). ``FileNotFoundError``
    mit dem Download-Befehl, wenn die Daten fehlen. Rueckgabe ``dict(frames_dir, probe, sharp)``.
    """
    from astropy.io import fits

    from .testdata import testdata_dir
    base = Path(data_dir) if data_dir else testdata_dir() / "lco-dcep"
    files = sorted(base.glob("*.fits.fz")) if base.is_dir() else []
    if not files:
        raise FileNotFoundError(f"keine LCO-Testdaten in {base} — python tools/download_testdata.py lco-dcep")
    good = []
    for f in files:
        with fits.open(f) as h:
            hdr = h["SCI"].header if "SCI" in h else h[0].header
            if str(hdr.get("TELESCOP", "")) == telescope and int(hdr.get("WCSERR", 0) or 0) == 0:
                good.append(f)
        if len(good) >= n_probe + 1:
            break
    if len(good) < n_probe + 1:
        raise FileNotFoundError(f"weniger als {n_probe + 1} brauchbare Bilder von {telescope} in {base}")
    sess.ensure_dirs()
    probe, sharp = good[1:n_probe + 1], good[0]
    for f in probe:
        _link(f, sess.path("probe", f.name))
    _link(sharp, sess.path("probe", "scharf", sharp.name))
    sess.update(target="del Cep", method="mono", aavso_filter="V", obstype="CCD", frames_dir=str(base), wcs_mode="header", source="lco-demo", notes={**sess.notes, "telescope": telescope, "vsp_star": "Delta Cep"})
    return dict(frames_dir=base, probe=[sess.path("probe", f.name) for f in probe], sharp=sess.path("probe", "scharf", sharp.name))


def _link(src: Path, dst: Path) -> None:
    """Verknuepfung ``dst`` → ``src`` (ersetzt eine vorhandene); faellt bei Systemen ohne Symlinks auf Kopieren zurueck."""
    import os
    import shutil
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def archive_reason(sess: Session) -> str:
    """Nicht leer, wenn die Bilder der Reihe nach ihrem Kopf **fremde Archivdaten** sind (``ORIGIN`` mit ``LCO``, oder ``PROPID``/``USERID`` eines Beobachtungsprogramms); Text nennt den Grund, sonst ``""``.

    Warum: Daten fremder Beobachter (Testdaten aus dem LCO-Archiv) duerfen **nie** unter dem eigenen AAVSO-Code eingereicht werden. Beim Test mit LCO-Bildern als „eigene Sitzung“ entstand eine Datei mit dem echten Code und ohne Warnung
    (2026-11-11, danach geloescht). NB03 erzwingt deshalb den Testcode ``TST01`` und die Kennzeichnung, sobald diese Merkmale im Kopf stehen. Grenzen: erkennt nur LCO-typische Merkmale; Bilder anderer Archive werden nicht erkannt
    — dort bleibt das Haekchen „eigene Beobachtungen“ die Verantwortung des Nutzers.
    """
    from astropy.io import fits
    frames = collect_frames(sess)
    if not frames:
        return ""
    with fits.open(frames[0]) as h:
        hdr = h["SCI"].header if "SCI" in h else h[0].header
        prim = h[0].header
    origin = str(hdr.get("ORIGIN", "") or prim.get("ORIGIN", ""))
    if "LCO" in origin.upper():
        return f"ORIGIN = {origin} (Las Cumbres Observatory, Archivdaten)"
    if hdr.get("PROPID") or hdr.get("USERID") or prim.get("PROPID"):
        return f"Kopf nennt ein Beobachtungsprogramm (PROPID {hdr.get('PROPID') or prim.get('PROPID')}) — Archivdaten?"
    return ""
