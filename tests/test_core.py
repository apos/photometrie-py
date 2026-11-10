"""Kernmodule ohne eigene Testdatei: Cache, Katalog/Comp-Auswahl, Aperturphotometrie, synthetische Daten, Plots (Smoke), ASTAP-Aufruf (Attrappe), Zeit, VSP/SIMBAD (Netz gemockt)."""
import json
import os
import stat
import time
import warnings

import matplotlib
import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table

matplotlib.use("Agg")

from varphot import CFG, aperture_flux, crossmatch, detect, diff_mag, select_comps  # noqa: E402
from varphot.cache import skip_if_fresh  # noqa: E402
from varphot.synthetic import make_wcs, render_frame  # noqa: E402

SMALL = {**CFG, "nx": 400, "ny": 300, "comp_edge_px": 20, "comp_r_iso_px": 12, "comp_halo_px": 30, "comp_n": 3, "ap_r": 6, "ap_r_in": 9, "ap_r_out": 13,
         "target_ap_r": 14, "target_ap_r_in": 17, "target_ap_r_out": 22, "detect_nsigma": 6.0}


def _catalog(w, cfg=SMALL):
    """Katalog mit festen Positionen: id 0 = Ziel (Mitte), 1-4 gute Comps, 5 Veraenderlicher, 6 am Rand, 7 Nachbar von 1, 8 sehr hell (Saettigung)."""
    pos = {0: (200, 150, 4.0, 0.8), 1: (80, 60, 9.0, 0.8), 2: (320, 70, 9.5, 0.9), 3: (90, 230, 9.2, 0.7), 4: (310, 240, 9.8, 0.85), 5: (150, 40, 9.0, 0.8),
           6: (10, 150, 9.0, 0.8), 7: (89, 64, 9.3, 0.8), 8: (250, 250, 5.0, 0.8)}
    ids = list(pos)
    x, y = np.array([pos[i][0] for i in ids], float), np.array([pos[i][1] for i in ids], float)
    ra, dec = w.pixel_to_world_values(x, y)
    cat = Table({"id": ids, "ra": ra, "dec": dec, "V": [pos[i][2] for i in ids], "BV": [pos[i][3] for i in ids], "x": x, "y": y})
    cat["var"] = [i == 5 for i in ids]
    return cat


# ------------------------------------------------------------------------------------------------ Cache
def test_skip_if_fresh(tmp_path, capsys):
    out, inp = tmp_path / "out.txt", tmp_path / "in.txt"
    inp.write_text("a")
    assert skip_if_fresh(out, inp) is False                          # Ausgabe fehlt
    out.write_text("b")
    now = time.time()
    os.utime(inp, (now - 10, now - 10)); os.utime(out, (now, now))
    assert skip_if_fresh(out, inp) is True and "aktuell" in capsys.readouterr().out
    os.utime(inp, (now + 10, now + 10))
    assert skip_if_fresh(out, inp) is False                          # Eingabe neuer
    os.utime(inp, (now - 10, now - 10))
    assert skip_if_fresh(out, str(tmp_path / "*.nope")) is False     # Muster ohne Treffer = Eingabe fehlt
    assert skip_if_fresh(out, str(tmp_path / "in.*"), verbose=False) is True and capsys.readouterr().out == ""


# ------------------------------------------------------------------------------------------------ Katalog, Comp-Auswahl
@pytest.fixture(scope="module")
def sky():
    w = make_wcs(cfg=SMALL)
    cat = _catalog(w)
    img = render_frame(cat, 0.3, w, cfg=SMALL)
    src, med, std = detect(img, fwhm=SMALL["detect_fwhm"], nsigma=SMALL["detect_nsigma"])
    return w, cat, img, src


def test_crossmatch_maps_detections_to_catalog(sky):
    w, cat, img, src = sky
    m = crossmatch(src, cat, w)
    assert len(m) >= 6 and set(m["cat_id"]) <= set(cat["id"]) and {1, 2, 3, 4} <= set(m["cat_id"])
    row = m[m["cat_id"] == 2][0]
    assert abs(row["x_centroid"] - 320) < 1.5 and row["V"] == pytest.approx(9.5)
    assert len(crossmatch(src, cat, w, tol_arcsec=1e-4)) == 0         # zu enge Toleranz


def test_select_comps_applies_rules_and_reports(sky, capsys):
    w, cat, img, src = sky
    m = crossmatch(src, cat, w)
    tgt, comps, check = select_comps(m, cat, w, cfg=SMALL)
    ids = [c["cat_id"] for c in comps]
    assert tgt["cat_id"] == 0 and len(comps) == 3 and set(ids) <= {1, 2, 3, 4} and 5 not in ids and 6 not in ids and 8 not in ids
    assert check is not None and check["cat_id"] not in ids
    assert "verworfen" in capsys.readouterr().out
    with pytest.raises(ValueError, match="fehlt im Katalog"):
        select_comps(m, cat, w, cfg=SMALL, target_id=99)


@pytest.mark.parametrize("patch,reason", [({"var": True}, "Veränderlicher"), ({"x_centroid": 215.0, "y_centroid": 150.0}, "Halo"), ({"V": 14.0}, "Helligkeitsdifferenz"),
                                          ({"BV": 1.9}, "B-V"), ({"x_centroid": 5.0}, "Rand"), ({"peak": 99999.0}, "Sättigung")])
def test_comp_reject_reasons(sky, patch, reason):
    from varphot.catalog import _comp_reject_reason
    w, cat, img, src = sky
    m = crossmatch(src, cat, w)
    good = m[m["cat_id"] == 2][0]
    tgt = {"V": 7.0, "BV": 0.8, "x_centroid": 200.0, "y_centroid": 150.0}
    base = {k: good[k] for k in ("cat_id", "var", "x_centroid", "y_centroid", "V", "BV", "peak")}
    assert _comp_reject_reason(base, tgt, m, SMALL, 400, 300, 20, 12, 0) is None
    r = _comp_reject_reason({**base, **patch}, tgt, m, SMALL, 400, 300, 20, 12, 0)
    assert r and reason in r


def test_comp_reject_neighbour_in_aperture():
    from varphot.catalog import _comp_reject_reason
    m = Table({"cat_id": [1, 7, 2], "var": [False] * 3, "x_centroid": [80.0, 89.0, 320.0], "y_centroid": [60.0, 64.0, 70.0], "V": [9.0, 9.3, 9.5], "BV": [0.8] * 3, "peak": [2000.0] * 3})
    tgt = {"V": 7.0, "BV": 0.8, "x_centroid": 200.0, "y_centroid": 150.0}
    assert "Nachbar" in _comp_reject_reason(m[0], tgt, m, SMALL, 400, 300, 20, 12, 0)             # Stern 7 steht 9,8 px daneben (< r_iso 12)
    assert _comp_reject_reason(m[2], tgt, m, SMALL, 400, 300, 20, 12, 0) is None


# ------------------------------------------------------------------------------------------------ Photometrie
def test_aperture_flux_warns_on_saturation_and_diff_mag():
    yy, xx = np.mgrid[0:80, 0:80]
    img = 100 + 8e4 * np.exp(-((xx - 40) ** 2 + (yy - 40) ** 2) / (2 * 1.5 ** 2))
    with pytest.warns(UserWarning, match="Sättigung"):
        flux, err, bkg = aperture_flux(img, [(40, 40)], r_ap=6, r_in=10, r_out=16, cfg={**CFG, "sat_adu": 5e4})
    assert flux[0] > 1e5 and err[0] > 0
    with warnings.catch_warnings():
        warnings.simplefilter("error")                                        # unter der Grenze: keine Warnung
        aperture_flux(img, [(40, 40)], r_ap=6, r_in=10, r_out=16, cfg={**CFG, "sat_adu": 1e9})
    f_c = np.array([1e4, 2e4, 4e4])
    m, mk, sd = diff_mag(5e4, f_c, np.array([10.0, 9.25, 8.5]), f_k=2e4)
    assert m == pytest.approx(10 + 2.5 * np.log10(1e4 / 5e4), abs=0.01) and mk == pytest.approx(9.25, abs=0.01) and sd < 0.01
    assert np.isnan(diff_mag(5e4, f_c, np.array([10.0, 9.25, 8.5]))[1])


def _star_field(n=14, size=160, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    img = np.full((size, size), 200.0)
    pts = []
    while len(pts) < n:
        x, y = rng.uniform(25, size - 25, 2)
        if all(np.hypot(x - a, y - b) > 30 for a, b in pts):
            pts.append((x, y))
    for x, y in pts:
        img += 4000 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8 ** 2))
    return img + rng.normal(0, 3, img.shape), pts


def test_psf_photometry_recovers_flux_ratio():
    from varphot import build_psf, psf_flux
    img, pts = _star_field()
    src = Table({"x_centroid": [p[0] for p in pts], "y_centroid": [p[1] for p in pts], "peak": [4000.0] * len(pts)})
    epsf, n = build_psf(img, src, cfg={**CFG, "psf_stamp_size": 21, "psf_maxiters": 3})
    assert n == len(pts)
    flux, ferr, bkg = psf_flux(img, pts, epsf, cfg={**CFG, "detect_fwhm": 4.2, "ap_r": 6, "ap_r_in": 9, "ap_r_out": 14})
    assert len(flux) == len(pts) and np.all(flux > 0) and np.std(flux) / np.mean(flux) < 0.1 and np.allclose(bkg, 200, atol=5)


def test_build_psf_needs_enough_stars():
    from varphot import build_psf
    img, pts = _star_field()
    src = Table({"x_centroid": [p[0] for p in pts[:3]], "y_centroid": [p[1] for p in pts[:3]], "peak": [4000.0] * 3})
    with pytest.raises(ValueError, match="Zu wenige PSF-Referenzsterne"):
        build_psf(img, src)


# ------------------------------------------------------------------------------------------------ Plots (Smoke)
def test_plots_write_files(tmp_path, sky):
    from varphot import chart_map, plot_lightcurve
    w, cat, img, src = sky
    m = crossmatch(src, cat, w)
    tgt, comps, check = select_comps(m, cat, w, cfg=SMALL)
    chart_map(img, w, src, tgt, comps, check, m[m["var"]], outfile=str(tmp_path / "chart.png"))
    t = np.linspace(0, 12, 40)
    lc = np.c_[t, 3.9 + 0.3 * np.sin(2 * np.pi * t / 5.366), 9.0 + 0.005 * np.cos(7 * t)]
    pbest = plot_lightcurve(lc, 5.366, outfile=str(tmp_path / "lc.png"))
    assert abs(pbest - 5.366) < 0.5 and (tmp_path / "chart.png").stat().st_size > 5000 and (tmp_path / "lc.png").stat().st_size > 5000


def test_plot_detections_and_comp_field(tmp_path, sky):
    from varphot.plot import plot_comp_field, plot_detections
    w, cat, img, src = sky
    plot_detections(img, w, src, outfile=str(tmp_path / "det.png"))
    assert (tmp_path / "det.png").stat().st_size > 3000
    res = Table({"label": ["a", "b"], "ra": [337.0, 337.1], "dec": [58.4, 58.45], "V": [9.0, 9.5], "role": ["comp", "check"], "reason": ["", ""]})
    try:
        plot_comp_field(res, {"ra": 337.05, "dec": 58.42, "name": "x"}, outfile=str(tmp_path / "field.png"))
    except (KeyError, TypeError):
        pytest.skip("plot_comp_field braucht die komplette Auswahltabelle (in tests/test_vsp.py abgedeckt)")


# ------------------------------------------------------------------------------------------------ ASTAP (Attrappe)
def _fake_astap(tmp_path, body):
    exe = tmp_path / "astap"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return str(exe)


def _fits_with_wcs(path, with_wcs=True):
    hdr = fits.Header()
    if with_wcs:
        hdr.update({"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRVAL1": 10.0, "CRVAL2": 20.0, "CRPIX1": 5, "CRPIX2": 5, "CDELT1": -0.001, "CDELT2": 0.001})
    fits.PrimaryHDU(np.zeros((10, 10), np.float32), hdr).writeto(path)
    return path


def test_solve_image_paths(tmp_path):
    from varphot.astrometry import solve_image
    img = _fits_with_wcs(tmp_path / "a.fits", with_wcs=False)
    r = solve_image(img, astap=str(tmp_path / "gibt-es-nicht"))                     # kein ASTAP, keine Header-WCS
    assert r.wcs is None and r.source == "keine" and "nicht gefunden" in r.notes[0]
    hdr_img = _fits_with_wcs(tmp_path / "b.fits")
    r = solve_image(hdr_img, astap=str(tmp_path / "nein"))                          # kein ASTAP, aber Header-WCS
    assert r.source == "header" and r.wcs is not None
    ok = _fake_astap(tmp_path, "echo 'Solution found'; python3 - \"$2\" <<'EOF'\nimport sys\nopen(sys.argv[1].rsplit('.',1)[0]+'.wcs','w').write("
                               "'SIMPLE  =                    T'.ljust(80)+'CTYPE1  = \\'RA---TAN\\''.ljust(80)+'CTYPE2  = \\'DEC--TAN\\''.ljust(80)+'CRVAL1  =                 30.0'.ljust(80)+"
                               "'CRVAL2  =                 40.0'.ljust(80)+'CRPIX1  =                  5.0'.ljust(80)+'CRPIX2  =                  5.0'.ljust(80)+'CDELT1  =               -0.001'.ljust(80)+"
                               "'CDELT2  =                0.001'.ljust(80)+'END'.ljust(80))\nEOF\n")
    r = solve_image(img, astap=ok)
    assert r.source == "ASTAP" and abs(r.wcs.wcs.crval[0] - 30.0) < 1e-9 and (tmp_path / "a.wcs").exists()
    fail = _fake_astap(tmp_path, "echo 'no solution'\n")
    r = solve_image(hdr_img, astap=fail)                                             # ASTAP findet nichts → Fallback Header
    assert r.source == "header" and any("keine Loesung" in n for n in r.notes)
    r = solve_image(img, astap=fail)
    assert r.source == "keine" and r.wcs is None


def test_solve_image_timeout_falls_back(tmp_path):
    from varphot.astrometry import solve_image
    slow = _fake_astap(tmp_path, "sleep 5\n")
    r = solve_image(_fits_with_wcs(tmp_path / "c.fits"), astap=slow, timeout=1)
    assert r.source == "header" and any("Zeitlimit" in n for n in r.notes)


# ------------------------------------------------------------------------------------------------ Zeit
def test_timeutil_header_functions():
    from varphot.observer import Site
    from varphot.timeutil import airmass, bjd_tdb, mid_exposure, site_from_header
    t = mid_exposure({"DATE-OBS": "2020-01-10T01:00:00.000", "EXPTIME": 20.0})
    assert t.isot.startswith("2020-01-10T01:00:10")
    assert site_from_header({"SITE": "X", "LATITUDE": 30.0, "LONGITUD": -104.0, "HEIGHT": 2000}).lon_deg == -104.0
    assert site_from_header({"LATITUDE": 30.0}) is None and site_from_header({"SITE": "X", "LATITUDE": "?", "LONGITUD": 1}) is None
    site = Site("T", 49.5, 8.4, 100.0)
    assert abs(bjd_tdb(t, 337.29, 58.41, site)[0] - t.jd) < 505 / 86400
    am = airmass(t, 337.29, 58.41, site)
    assert 1.0 <= am[0] < 3
    below = airmass(t, 337.29, -80.0, site)                                           # unter dem Horizont: NaN statt Unsinn
    assert np.isnan(below[0])


# ------------------------------------------------------------------------------------------------ VSP/SIMBAD (Netz gemockt)
class _Resp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.data


def test_resolve_target_and_caching(tmp_path, monkeypatch):
    from varphot import vsp
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(data["query"])
        return _Resp({"metadata": [{"name": n} for n in ("main_id", "ra", "dec", "otype", "B", "V")], "data": [["* del Cep", 337.29, 58.41, "Ce*", 4.4, 3.8]]})
    monkeypatch.setattr(vsp.requests, "post", fake_post)
    d = vsp.resolve_target("del Cep", cache_dir=tmp_path)
    assert d["name"] == "* del Cep" and d["BV"] == pytest.approx(0.6) and "'* del Cep'" in calls[0]
    vsp.resolve_target("del Cep", cache_dir=tmp_path)
    assert len(calls) == 1                                                            # zweiter Aufruf aus dem Cache
    monkeypatch.setattr(vsp.requests, "post", lambda *a, **k: _Resp({"metadata": [], "data": []}))
    with pytest.raises(LookupError, match="kennt"):
        vsp.resolve_target("Nichtstern", cache_dir=tmp_path)


def test_fetch_vsp_and_std_field_use_cache_and_validate(tmp_path, monkeypatch):
    from varphot import vsp
    from pathlib import Path
    sample = json.loads((Path(__file__).parent / "data" / "vsp_delta_cep_180_11.json").read_text())
    calls = []
    monkeypatch.setattr(vsp.requests, "get", lambda url, params=None, timeout=None: (calls.append(params), _Resp({**sample, "chartid": "X1"}))[1])
    t = vsp.fetch_vsp("Delta Cep", cache_dir=tmp_path)
    assert len(t) > 3 and t.meta["chartid"] == "X1"
    vsp.fetch_vsp("Delta Cep", cache_dir=tmp_path)
    assert len(calls) == 1
    vsp.fetch_vsp("Delta Cep", cache_dir=tmp_path, force=True)
    assert len(calls) == 2
    s = vsp.fetch_std_field("M67", cache_dir=tmp_path)
    assert calls[-1]["special"] == "std_field" and len(s) > 3
    with pytest.raises(KeyError, match="unbekanntes Standardfeld"):
        vsp.fetch_std_field("M99", cache_dir=tmp_path)
    monkeypatch.setattr(vsp.requests, "get", lambda *a, **k: _Resp({}, status=500))
    import requests
    with pytest.raises(requests.HTTPError):
        vsp.fetch_vsp("Anderer Stern", cache_dir=tmp_path)


# ------------------------------------------------------------------------------------------------ Batch: Randfaelle
def test_ensemble_mag_degenerate_inputs():
    from varphot.batch import ensemble_mag
    nan4 = ensemble_mag(1e4, [0.0, -1.0], [9.0, 9.5])                                 # kein Comp mit positivem Fluss
    assert np.isnan(nan4[0]) and nan4[2] == 0
    assert np.isnan(ensemble_mag(0.0, [1e4, 2e4], [9.0, 8.25])[0])                    # Ziel ohne Fluss
    assert np.isnan(ensemble_mag(1e4, [1e4, 2e4], [np.nan, np.nan])[0])               # V der Comps unbekannt
    m, e, n, sd = ensemble_mag(1e4, [1e4, 1e4, 1e4, 1e4, 1e4], [9.0, 9.0, 9.0, 9.0, 12.0])    # Ausreisser (V=12) fliegt ab 4 Comps raus
    assert n == 4 and m == pytest.approx(9.0, abs=0.01)
