"""Bereitschaft (Software, NB07/NB08, Standardfelder), Defokus-Rechnungen, Plate-Solve fuer Arrays (ASTAP-Attrappe)."""
import stat

import numpy as np
import pandas as pd
import pytest
from astropy.wcs import WCS

from varphot import readiness as R
from varphot.observer import Camera, Observer, Site, save_config


# ------------------------------------------------------------------------------------------------ Software
def test_software_checks_basic(tmp_path, monkeypatch):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "observer.json"))
    monkeypatch.setattr(R, "find_program", lambda paths, name: "/x/astap" if name == "astap" else None)
    rows = {c.label: c for c in R.software_checks(ai=False)}
    assert rows["Python"].ok and rows["Paket numpy"].ok and rows["Programm ASTAP"].ok and not rows["Programm Siril"].ok and rows["Programm Siril"].optional
    assert not rows["Beobachter (observer.json)"].ok and "fehlt" in rows["Beobachter (observer.json)"].detail
    save_config(Observer("TST01", "Ort", Camera()), [Site("Ort", 49.5, 8.4, 100)], tmp_path / "observer.json")
    assert "Standort 'Ort'" in {c.label: c for c in R.software_checks(ai=False)}["Beobachter (observer.json)"].detail


def test_software_checks_missing_package_and_python(monkeypatch):
    monkeypatch.setattr(R, "PACKAGES", [("gibtesnicht", "gibtesnicht_xyz")])
    monkeypatch.setattr(R, "MIN_PYTHON", (99, 0))
    rows = R.software_checks(ai=False)
    assert not rows[0].ok and "benoetigt" in rows[0].detail
    pk = next(c for c in rows if c.label == "Paket gibtesnicht")
    assert not pk.ok and "pip install" in pk.detail


def test_ai_rows_are_optional_and_failures_do_not_break(monkeypatch):
    from varphot import aireview
    monkeypatch.setattr(aireview, "detect_backends", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rows = R.software_checks(ai=True)
    ki = next(c for c in rows if c.label == "KI-Zweitlesung")
    assert not ki.ok and ki.optional and "boom" in ki.detail


def test_render_html_marks_blockers_and_optionals():
    html = R.render_html([R.Check("a", True, "ok"), R.Check("b", False, "fehlt", optional=True)], "T")
    assert "✓" in html and "·" in html and "✗" not in html and "erfuellt" in html
    html = R.render_html([R.Check("c", False, "weg")], "T")
    assert "✗" in html and "fehlt (✗)" in html


# ------------------------------------------------------------------------------------------------ NB07/NB08
def test_camera_readiness(tmp_path, monkeypatch):
    from varphot import transform
    monkeypatch.setattr(transform, "solution_path", lambda model, setting: tmp_path / "t.json")
    none = R.camera_readiness(None, "mono", "K", "S")
    assert len(none) == 1 and not none[0].ok and "NB07" in none[0].detail
    cam = Camera(model="K", gain_e_per_adu=1.5, linear_max_adu=14000.0, source="gemessen")
    ok = R.camera_readiness(cam, "mono", "K", "S")
    assert ok[0].ok and "Gain 1.5" in ok[0].detail and len(ok) == 1                  # Mono: NB08 nicht noetig
    colour = R.camera_readiness(cam, "osc", "K", "S")
    assert len(colour) == 2 and not colour[1].ok and "untransformiert" in colour[1].detail
    sol = transform.TransformSolution(Tb_bv=0.2, Tv_bv=-0.05, Tr_bv=0.3, Tbv=1.4, k_extinction={"b": 0.3, "g": 0.2, "r": 0.1}, n_stars=20, bv_range=(0.3, 1.4), validation={"V": {"rms_transformed": 0.02, "rms_standardized": 0.04}})
    sol.save(tmp_path / "t.json")
    colour = R.camera_readiness(cam, "osc", "K", "S")
    assert colour[1].ok and "V" in colour[1].detail
    (tmp_path / "t.json").write_text("{kaputt")
    assert not R.camera_readiness(cam, "osc", "K", "S")[1].ok


def test_std_field_visibility_northern_site():
    site = Site("Ludwigshafen", 49.5, 8.4, 100.0)
    import datetime as dt
    t = R.std_field_visibility(site, dt.date(2026, 11, 10))
    assert set(t["field"]) >= {"M67", "NGC 7790", "NGC 3532"} and t.iloc[0]["hours"] >= t.iloc[-1]["hours"]
    south = t[t["field"].isin(["NGC 3532", "NGC 1252"])]
    assert (~south["ok"]).all() and (south["hours"] == 0).all()                          # von Mitteleuropa nie sichtbar
    assert bool(t[t["field"] == "NGC 7790"]["ok"].iloc[0])                              # Cassiopeia im November hoch


# ------------------------------------------------------------------------------------------------ Defokus-Rechnungen
def test_defocus_tradeoff_and_needed():
    from varphot import defocus_needed, defocus_tradeoff
    t = defocus_tradeoff(3.0, 6.0)
    assert t["peak_factor"] == pytest.approx(0.25) and t["exposure_gain"] == pytest.approx(4.0) and t["snr_factor"] == pytest.approx(0.5)
    assert defocus_needed(30000, 100, 40000, 3.0, 1.0, 1.0) == 3.0                       # bleibt unter der Grenze
    f = defocus_needed(30000, 100, 14000, 3.0, 1.0, 1.0)
    assert f == pytest.approx(3.0 * np.sqrt(29900 / 13900))
    assert defocus_needed(30000, 100, 14000, 3.0, 1.0, 2.0) > f                          # laengere Belichtung braucht mehr Defokus


def test_fwhm_summary_brightness_trend():
    from varphot import fwhm_summary
    n = 12
    df = pd.DataFrame(dict(raw_max=np.linspace(9000, 500, n), fwhm=np.linspace(7.0, 4.5, n)))
    s = fwhm_summary(df)
    assert s["fwhm_bright"] > s["fwhm_faint"] and s["grows_with_brightness"] and s["n"] == n
    flat = fwhm_summary(pd.DataFrame(dict(raw_max=np.linspace(9000, 500, n), fwhm=[4.0] * n)))
    assert not flat["grows_with_brightness"]
    few = fwhm_summary(pd.DataFrame(dict(raw_max=[1, 2], fwhm=[4.0, 5.0])))
    assert np.isnan(few["fwhm_bright"]) and few["n"] == 2
    assert fwhm_summary(pd.DataFrame(dict(raw_max=[], fwhm=[])))["n"] == 0


# ------------------------------------------------------------------------------------------------ Plate-Solve fuer Arrays
def _fake_astap(tmp_path, crval=(30.0, 40.0), succeed=True):
    exe = tmp_path / "astap"
    wcs = ("SIMPLE  =                    T".ljust(80) + "CTYPE1  = 'RA---TAN'".ljust(80) + "CTYPE2  = 'DEC--TAN'".ljust(80) + f"CRVAL1  = {crval[0]:20.6f}".ljust(80) + f"CRVAL2  = {crval[1]:20.6f}".ljust(80)
           + "CRPIX1  =                 50.0".ljust(80) + "CRPIX2  =                 40.0".ljust(80) + "CDELT1  =           -0.0002778".ljust(80) + "CDELT2  =            0.0002778".ljust(80) + "END".ljust(80))
    body = "#!/bin/sh\n" + (f"echo 'Solution found'\nprintf '%s' \"{wcs}\" > \"${{2%.*}}.wcs\"\n" if succeed else "echo 'no'\n")
    exe.write_text(body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def _truth():
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.crval, w.wcs.cdelt, w.wcs.ctype = [50, 40], [30.0, 40.0], [-0.0002778, 0.0002778], ["RA---TAN", "DEC--TAN"]
    return w


def test_solve_array_strips_wcs_hint_and_summarises(tmp_path):
    from varphot.astrometry import plate_solve_summary, solve_array
    res = solve_array(np.zeros((80, 100)), hint={"RA": 30.0, "DEC": 40.0, "CRVAL1": 1.0, "EXPTIME": 5.0}, astap=_fake_astap(tmp_path))
    assert res.source == "ASTAP"
    s = plate_solve_summary(res, (80, 100), _truth())
    assert s["solved"] and s["scale_arcsec"] == pytest.approx(1.0, abs=0.01) and s["offset_arcsec"] < 0.5
    off = plate_solve_summary(solve_array(np.zeros((80, 100)), astap=_fake_astap(tmp_path, crval=(30.01, 40.0))), (80, 100), _truth())
    assert off["offset_arcsec"] == pytest.approx(0.01 * np.cos(np.radians(40)) * 3600, rel=0.05)
    bad = solve_array(np.zeros((80, 100)), astap=_fake_astap(tmp_path, succeed=False))
    assert bad.wcs is None and not plate_solve_summary(bad, (80, 100))["solved"]


def test_defocus_solve_ladder_with_fake_astap(tmp_path):
    from varphot.astrometry import defocus_solve_ladder
    seen = []
    t = defocus_solve_ladder(np.random.default_rng(0).normal(100, 5, (80, 100)), _truth(), blurs=(0, 8), kinds=("gauss", "donut"), astap=_fake_astap(tmp_path), progress=seen.append)
    assert list(t["kind"]) == ["gauss", "gauss", "donut", "donut"] and t["solved"].all() and len(seen) == 4 and (t["offset_arcsec"] < 0.5).all()
