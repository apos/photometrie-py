"""Ablauf-Funktionen (Bilder, Referenz, Kalibrierung, Feld, Messung, Periode) mit synthetischen Bildern; Netz gemockt."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from varphot import workflow as W
from varphot.session import Session

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from varphot import observer
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "cfg" / "observer.json"))
    monkeypatch.setattr(observer, "REPO_ROOT", tmp_path / "repo" / "PHOTOMETRIE_PY")
    monkeypatch.delenv("VARPHOT_SESSION", raising=False)


def _wcs():
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.crval, w.wcs.cdelt, w.wcs.ctype = [300, 220], [100.0, 30.0], [-0.0004, 0.0004], ["RA---TAN", "DEC--TAN"]
    return w


STAR_PX = np.array([[300, 220], [120, 90], [480, 100], [130, 360], [470, 350], [300, 80], [300, 380], [200, 220]], float)       # 0 = Ziel, 1.. = Comps
FLUX = np.array([3e4, 2.0e4, 1.5e4, 1.2e4, 1.0e4, 8e3, 6e3, 5e3])


def _render(dy=0.0, dx=0.0, target_scale=1.0, seed=1, fwhm=3.5):
    yy, xx = np.mgrid[:440, :600]
    img = 300 + np.random.default_rng(seed).normal(0, 3, (440, 600))
    s = fwhm / 2.3548
    for k, ((x, y), f) in enumerate(zip(STAR_PX, FLUX)):
        f = f * (target_scale if k == 0 else 1.0)
        img += f / (2 * np.pi * s ** 2) * np.exp(-((xx - x - dx) ** 2 + (yy - y - dy) ** 2) / (2 * s ** 2))
    return img.astype(np.float32)


def _write(path, img, wcs=True, extra=None):
    h = fits.Header({"DATE-OBS": "2020-01-10T01:00:00", "EXPTIME": 10.0, "GAIN": 1.5, "RDNOISE": 4.0, "SATURATE": 60000.0, "L1FWHM": 3.0, "SITE": "T", "LATITUDE": 30.0, "LONGITUD": -104.0, "HEIGHT": 2000.0})
    if wcs:
        h.update(_wcs().to_header())
    h.update(extra or {})
    fits.PrimaryHDU(img, h).writeto(path, overwrite=True)


def _session(tmp_path, n=14, wcs=True, period=2.0):
    s = Session(str(tmp_path / "s"), target="del Cep", method="mono", tag="t")
    s.ensure_dirs()
    s.frames_dir = str(s.path("process"))
    rng = np.random.default_rng(3)
    for i in range(n):
        t = i * 0.37
        scale = 10 ** (-0.4 * (0.3 * np.sin(2 * np.pi * t / period)))
        h = {"DATE-OBS": f"2020-01-{10 + int(t):02d}T{int((t % 1) * 24):02d}:00:00"}
        _write(s.path("process", f"pp_light_{i:05d}.fit"), _render(dy=rng.normal(0, 2), dx=rng.normal(0, 2), target_scale=scale, seed=10 + i), wcs=wcs, extra=h)
    _write(s.path("process", "dark_00001.fit"), _render(), wcs=False)                 # Zwischenprodukt: darf nicht in die Reihe
    ref = s.path("process", "pp_light_00000.fit")
    s.update(ref_frame=str(ref), ref_wcs="")
    ra, dec = _wcs().pixel_to_world_values(STAR_PX[:, 0], STAR_PX[:, 1])
    rec = {"ziel": {"name": "* del Cep", "ra": float(ra[0]), "dec": float(dec[0]), "V": 4.0}, "vsp": {"chartid": "X1"},
           "sterne": [{"rolle": "comp" if k < 6 else "check", "auid": f"A{k}", "label": f"C{k}", "ra": float(ra[k]), "dec": float(dec[k]), "V": 10.0 - 2.5 * np.log10(FLUX[k] / FLUX[1]), "V_err": 0.02, "B": 10.8, "B_err": 0.03, "G": None, "R": None}
                      for k in range(1, 7)]}
    fc = s.path("results", "t", "field_config.json")
    fc.parent.mkdir(parents=True, exist_ok=True)
    fc.write_text(json.dumps(rec))
    s.update(field_config=str(fc), results=str(fc.parent))
    return s


# ------------------------------------------------------------------------------------------------ Bilder, Referenz
def test_collect_frames_prefers_pp_light_and_filters_telescope(tmp_path):
    s = _session(tmp_path, n=3)
    assert [f.name for f in W.collect_frames(s)] == ["pp_light_00000.fit", "pp_light_00001.fit", "pp_light_00002.fit"]
    s.notes["telescope"] = "X"
    assert W.collect_frames(s) == []                                                   # kein Bild dieses Teleskops
    (s.path("process") / "pp_light_00000.fit").unlink(); [f.unlink() for f in s.path("process").glob("pp_light_*")]
    s.notes = {}
    assert [f.name for f in W.collect_frames(s)] == []                                  # dark_ ist Zwischenprodukt
    assert W.collect_frames(Session(str(tmp_path / "leer"))) == []


def test_pick_reference_prefers_many_sharp_stars_and_skips_wcserr(tmp_path):
    s = Session(str(tmp_path / "r")); s.ensure_dirs()
    fr = []
    for i, (fw, err) in enumerate([(7.0, 0), (3.0, 0), (3.0, 4), (5.0, 0)]):
        p = s.path("process", f"pp_light_{i:05d}.fit")
        _write(p, _render(fwhm=fw, seed=i), wcs=False, extra={"WCSERR": err})
        fr.append(p)
    ref, tab = W.pick_reference(fr, n_try=4)
    assert ref.name == "pp_light_00001.fit" and "pp_light_00002.fit" not in set(tab["file"])
    with pytest.raises(ValueError, match="keine Bilder"):
        W.pick_reference([])
    only_bad = [s.path("process", "pp_light_00002.fit")]
    assert W.pick_reference(only_bad)[0] == only_bad[0]                                  # alle verworfen: Rueckfall erstes Bild


# ------------------------------------------------------------------------------------------------ Kalibrierung
def test_calibration_step_without_siril(tmp_path, monkeypatch):
    from varphot import siril
    monkeypatch.setattr(siril, "find_siril", lambda: None)
    s = Session(str(tmp_path / "c"), method="osc"); s.ensure_dirs()
    assert W.calibration_step(s)["status"] == "keine_lights"
    (s.path("lights") / "a.CR2").write_text("x"); (s.path("darks") / "d.fits").write_text("x")
    r = W.calibration_step(s)
    assert r["status"] == "skript" and r["kinds"]["lights"] == "raw" and r["kinds"]["darks"] == "fits" and r["script"].exists()
    assert "-cfa -equalize_cfa" in r["script"].read_text() and "convertraw light" in r["script"].read_text()
    ran = []
    monkeypatch.setattr(siril, "find_siril", lambda: "/x/siril-cli")
    monkeypatch.setattr(siril, "run_script", lambda script, wd, **k: (ran.append(script), (True, "ok"))[1])
    r = W.calibration_step(s)
    assert ran and r["status"] == "fehler"                                               # Skript lief, aber es entstanden keine Bilder
    (s.path("process") / "pp_light_00001.fit").write_text("x")
    assert W.calibration_step(s)["status"] == "fertig"
    assert W.calibration_step(s, run=False)["status"] == "skript"


# ------------------------------------------------------------------------------------------------ Plate-Solve
def test_solve_reference_header_fallback_and_load_reference(tmp_path):
    s = _session(tmp_path, n=2)
    res, summ = W.solve_reference(s, s.path("process", "pp_light_00000.fit"), astap=str(tmp_path / "nix"))          # kein ASTAP: WCS im Kopf
    assert res.source == "header" and summ["scale_arcsec"] == pytest.approx(1.44, abs=0.01)
    img, hdr, w = W.load_reference(s)
    assert img.shape == (440, 600) and w is not None
    bare = Session(str(tmp_path / "b"))
    with pytest.raises(ValueError, match="Referenzbild"):
        W.load_reference(bare)
    _write(tmp_path / "x.fits", _render(), wcs=False)
    with pytest.raises(RuntimeError, match="Weder ASTAP"):
        W.solve_reference(bare, tmp_path / "x.fits", astap=str(tmp_path / "nix"))


def test_wcs_quality_never_raises():
    q = W.wcs_quality(_wcs(), np.full((100, 100), 10.0), {"DATE-OBS": "2020-01-10T00:00:00"})
    assert q["checked"] is False and q["note"]


# ------------------------------------------------------------------------------------------------ Feld
def test_vsp_name_candidates():
    assert W.vsp_name_candidates("del Cep", "* del Cep") == ["Delta Cep", "del Cep"]
    assert W.vsp_name_candidates("V* RR Lyr")[0] == "V* RR Lyr" or "RR Lyr" in " ".join(W.vsp_name_candidates("V* RR Lyr", "V* RR Lyr"))
    assert W.vsp_name_candidates("", "") == []


def test_select_field_with_mocked_catalogs(tmp_path, monkeypatch):
    from varphot import vsp
    s = _session(tmp_path, n=2)
    W.solve_reference(s, s.path("process", "pp_light_00000.fit"), astap=str(tmp_path / "nix"))
    sample = json.loads((DATA / "vsp_delta_cep_180_11.json").read_text())
    monkeypatch.setattr(vsp, "resolve_target", lambda name, **k: dict(name="* del Cep", ra=337.2929, dec=58.4152, otype="Ce*", B=4.4, V=3.8, BV=0.6))
    asked = []
    monkeypatch.setattr(vsp, "fetch_vsp", lambda star, **k: (asked.append(star), vsp.vsp_table({**sample, "chartid": "X43370IPN"}))[1])
    from types import SimpleNamespace
    plan = SimpleNamespace(v_comp_min=6.0, method="osc", aavso_filter="TB", target="del Cep", ra_deg=337.29, dec_deg=58.41, v_mean=3.8, aperture={"ap_r": 5, "ap_r_in": 8.0, "ap_r_out": 11})
    r = W.select_field(s, plan=plan, gaia_check=False)
    assert asked[0] == "Delta Cep" and r["record"]["vsp"]["chartid"] == "X43370IPN"
    assert any("Gaia-Ergaenzung aus" in w for w in r["warnings"]) and any("Nachbar-Radius" in w for w in r["warnings"])      # TB: nur AAVSO-Sequenz
    assert r["record"]["regeln"]["comp_bv_abs"] == [0.3, 1.0] and r["record"]["regeln"]["comp_v_range"][0] == 6.0
    assert Path(Session.load(s.workspace).field_config).exists() and r["counts"]["comp"] + r["counts"]["verworfen"] > 0
    def nonet(*a, **k): raise OSError("kein Netz")
    monkeypatch.setattr(vsp, "fetch_vsp", nonet)
    with pytest.raises(RuntimeError, match="VSP lieferte keine Sequenz"):
        W.select_field(s, plan=plan, gaia_check=False)
    monkeypatch.setattr(vsp, "resolve_target", nonet)
    with pytest.raises(RuntimeError, match="SIMBAD"):
        W.select_field(s, plan=None, gaia_check=False)


def _field_with_rules(tmp_path, monkeypatch, rules):
    from types import SimpleNamespace

    from varphot import vsp
    s = _session(tmp_path, n=2)
    W.solve_reference(s, s.path("process", "pp_light_00000.fit"), astap=str(tmp_path / "nix"))
    sample = json.loads((DATA / "vsp_delta_cep_180_11.json").read_text())
    monkeypatch.setattr(vsp, "resolve_target", lambda name, **k: dict(name="* del Cep", ra=337.2929, dec=58.4152, otype="Ce*", B=4.4, V=3.8, BV=0.6))
    monkeypatch.setattr(vsp, "fetch_vsp", lambda star, **k: vsp.vsp_table({**sample, "chartid": "X"}))
    plan = SimpleNamespace(v_comp_min=6.0, method="osc", aavso_filter="TB", target="del Cep", ra_deg=337.29, dec_deg=58.41, v_mean=3.8, aperture={"ap_r": 5, "ap_r_in": 8.0, "ap_r_out": 11})
    return W.select_field(s, plan=plan, gaia_check=False, use_gaia_fill=False, rules=rules, min_comps=0)


LOOSE = {"comp_bv_abs": None, "comp_v_range": [0, 20], "comp_bv_tol": 9, "comp_err_max": 9, "comp_r_iso_arcsec": 0.0}


def test_select_field_warns_when_no_check_star_exists(tmp_path, monkeypatch):
    """Ohne Check-Stern fehlt die unabhaengige Gegenprobe: die Auswahl meldet das, auch wenn die Comps-Warnung schon greift."""
    r = _field_with_rules(tmp_path, monkeypatch, LOOSE)
    assert r["counts"]["check"] == 0 and r["counts"]["comp"] == 0
    assert any(w.startswith("kein Check-Stern") and "Gegenprobe" in w for w in r["warnings"])


def test_select_field_no_check_warning_when_check_star_present(tmp_path, monkeypatch):
    r = _field_with_rules(tmp_path, monkeypatch, {**LOOSE, "field_margin_deg": -5, "comp_n": 3})
    assert r["counts"]["check"] == 1 and r["counts"]["comp"] == 3
    assert not any("kein Check-Stern" in w for w in r["warnings"])


# ------------------------------------------------------------------------------------------------ Messung und Periode
def test_measure_header_wcs_gives_light_curve_with_known_period(tmp_path):
    s = _session(tmp_path, n=22, wcs=True, period=2.0)
    r = W.measure(s, wcs_mode="header", ap={"ap_r": 6, "ap_r_in": 9.0, "ap_r_out": 13}, workers=1, aperture_m=0.4)
    assert r["flags"].get("brauchbar", 0) >= 18 and len(r["lc"]) >= 18 and r["ap"]["ap_r"] == 6
    assert (s.results_dir() / "zeitreihe.csv").exists() and (s.results_dir() / "messtabelle.csv").exists()
    assert r["lc"]["mag"].max() - r["lc"]["mag"].min() == pytest.approx(0.6, abs=0.15)           # Amplitude 2 × 0,3 mag
    p = W.analyse_period(r["lc"], 1.0, 4.0)
    assert p["period"] == pytest.approx(2.0, rel=0.06) and len(p["top"]) == 3 and p["harmonic"]["rms"] < 0.1


def test_measure_registers_frames_without_wcs_in_header(tmp_path):
    s = _session(tmp_path, n=12, wcs=False)
    _write(s.path("process", "pp_light_00000.fit"), _render(seed=10), wcs=True)                 # Referenz traegt die WCS, die Reihe nicht
    r = W.measure(s, ap={"ap_r": 6, "ap_r_in": 9.0, "ap_r_out": 13}, workers=1)               # auto
    wc = r["frames"]["wcs_source"].value_counts().to_dict()
    assert wc.get("registered", 0) >= 9 and len(r["lc"]) >= 9 and r["wcs_mode"] == "auto"
    again = W.measure(s, ap={"ap_r": 6, "ap_r_in": 9.0, "ap_r_out": 13}, workers=1)             # zweiter Lauf: Zwischenspeicher
    assert any("Zwischenspeicher" in n for n in again["notes"])


def test_measure_errors_and_aperture_from_reference(tmp_path):
    s = _session(tmp_path, n=4)
    r = W.measure(s, wcs_mode="header", workers=1)                                             # keine Apertur angegeben: aus dem Referenzbild
    assert any("Apertur aus dem Referenzbild" in n for n in r["notes"]) and r["ap"]["ap_r"] >= 3
    with pytest.raises(ValueError, match="field_config"):
        W.measure(Session(str(tmp_path / "x")))
    s2 = Session(str(tmp_path / "y"), field_config=str(tmp_path / "f.json")); (tmp_path / "f.json").write_text("{}")
    with pytest.raises(ValueError, match="keine Bilder"):
        W.measure(s2)
    img = _render()
    a = W.aperture_from_image(img, {"GAIN": 1.5, "RDNOISE": 4.0, "SATURATE": 60000.0})
    assert a["ap_r_in"] > a["ap_r"]
    with pytest.raises(ValueError, match="Sterne"):
        W.aperture_from_image(np.full((100, 100), 10.0), {})


def test_analyse_period_errors():
    with pytest.raises(ValueError, match="mindestens 8"):
        W.analyse_period(pd.DataFrame({"bjd_tdb": [1.0, 2.0], "mag": [1.0, 1.1]}))
    with pytest.raises(ValueError, match="zu kurz"):
        W.analyse_period(pd.DataFrame({"bjd_tdb": np.linspace(0, 0.1, 10), "mag": np.zeros(10)}))


def test_prepare_lco_demo_links_probe_and_reference(tmp_path):
    base = tmp_path / "lco"; base.mkdir()
    for i in range(6):
        img = np.zeros((20, 20), np.float32)
        h = fits.Header({"TELESCOP": "0m4-11" if i != 1 else "1m0-03", "WCSERR": 4 if i == 0 else 0, "EXPTIME": 1.0})
        fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(img, h, name="SCI")]).writeto(base / f"f{i}.fits.fz", overwrite=True)
    s = Session(str(tmp_path / "ws"))
    r = W.prepare_lco_demo(s, data_dir=base, n_probe=2)
    assert len(r["probe"]) == 2 and r["sharp"].exists() and r["sharp"].parent.name == "scharf"
    t = Session.load(tmp_path / "ws")
    assert t.source == "lco-demo" and t.wcs_mode == "header" and t.notes["telescope"] == "0m4-11" and t.target == "del Cep"
    with pytest.raises(FileNotFoundError, match="download_testdata"):
        W.prepare_lco_demo(Session(str(tmp_path / "w2")), data_dir=tmp_path / "leer")
    with pytest.raises(FileNotFoundError, match="weniger als"):
        W.prepare_lco_demo(Session(str(tmp_path / "w3")), data_dir=base, n_probe=9)


def test_archive_reason_detects_lco_headers(tmp_path):
    s = _session(tmp_path, n=2)
    assert W.archive_reason(s) == ""
    for f in s.path("process").glob("pp_light_*.fit"):
        with fits.open(f, mode="update") as h:
            h[0].header["ORIGIN"] = "LCOGT"
    assert "Las Cumbres" in W.archive_reason(s)
    for f in s.path("process").glob("pp_light_*.fit"):
        with fits.open(f, mode="update") as h:
            h[0].header["ORIGIN"] = "meine Sternwarte"; h[0].header["PROPID"] = "ABC-123"
    assert "PROPID" in W.archive_reason(s)
    assert W.archive_reason(Session(str(tmp_path / "leer"))) == ""
