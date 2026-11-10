"""Planung: Sternmetriken, Belichtungsempfehlung, Aperturen, Plan-Datei (synthetische Daten)."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from varphot.observer import Site
from varphot.plan import (METHODS, ObservingPlan, aperture_from_fwhm, fwhm_summary, green_plane, latest_plan, load_plan,
                          night_altitudes, plan_filename, recommend_exposure, save_plan, star_metrics)

RNG = np.random.default_rng(5)


def starfield(fwhm=5.0, shape=(500, 600), sky=100.0, noise=4.0, max_adu=16383, peaks=(9000, 6000, 3000, 1500, 800, 20000), seed=1):
    rng = np.random.default_rng(seed)
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    img = sky + rng.normal(0, noise, shape)
    pos = [(80, 90), (200, 400), (330, 120), (420, 300), (150, 250), (450, 520)]
    s = fwhm / 2.355
    for (y0, x0), pk in zip(pos, peaks):
        img += pk * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * s * s))
    return np.clip(img, 0, max_adu)


def test_star_metrics_fwhm_and_saturation():
    img = starfield(fwhm=5.0)
    df = star_metrics(img, max_adu=16383, fwhm_guess=4.0)
    assert df["saturated"].sum() == 1 and df.iloc[0]["saturated"]                    # der Stern mit Spitze 20000 ist abgeschnitten
    s = fwhm_summary(df)
    assert s["n"] >= 3 and s["fwhm"] == pytest.approx(5.0, rel=0.06)


def test_star_metrics_adapts_to_broad_stars():
    df = star_metrics(starfield(fwhm=11.0, peaks=(9000, 7000, 5000, 3500, 2500, 1200)), max_adu=16383, fwhm_guess=4.0)
    s = fwhm_summary(df)
    assert s["n"] >= 3 and s["fwhm"] == pytest.approx(11.0, rel=0.1)


def test_green_plane_is_mean_of_both_greens():
    img = np.arange(16, dtype=float).reshape(4, 4)
    g = green_plane(img, "RGGB")
    assert g.tolist() == [[2.5, 4.5], [10.5, 12.5]]                                    # (1+4)/2, (3+6)/2, (9+12)/2, (11+14)/2


def test_recommend_exposure_scales_linearly():
    assert recommend_exposure(raw_max=8000, exptime_s=2.0, limit_adu=12300, offset=100) == pytest.approx(2.0 * 12200 / 7900)
    with pytest.raises(ValueError):
        recommend_exposure(100, 1.0, 12000, offset=100)


def test_aperture_rules_follow_manual():
    a = aperture_from_fwhm(6.0)
    assert a["ap_r"] == 9 and a["ap_r_in"] == 12.0                                     # 1,5 x FWHM; Lücke 3 px
    area_ap, area_ring = np.pi * a["ap_r"] ** 2, np.pi * (a["ap_r_out"] ** 2 - a["ap_r_in"] ** 2)
    assert area_ring >= area_ap                                                        # Handbuch: Ring mindestens so gross wie die Apertur
    assert aperture_from_fwhm(4.0, factor=1.2)["ap_r"] == 5


def test_night_altitudes_high_declination_target_visible():
    site = Site("T", 50.0, 8.0, 100.0)
    df = night_altitudes(337.29, 58.42, site, dt.date(2026, 11, 10), step_min=60)       # delta Cep, zirkumpolar bei 50° N
    assert len(df) == 25 and df["alt_target"].min() > 5 and df["ok"].any()
    assert df["dark"].any() and not df["dark"].all()


def test_plan_roundtrip_and_latest(tmp_path):
    p1 = ObservingPlan("del Cep", 337.29, 58.41, 3.75, 3.48, "osc", "TG", "DSLR", "Cam A", "Gain 0", "RGGB", "Site",
                       fwhm_px=4.2, fwhm_raw_px=8.4, aperture=aperture_from_fwhm(4.2), exptime_max_s=3.5, warnings=["x"])
    path = save_plan(p1, tmp_path)
    assert path.name == plan_filename(p1) and "del-cep" in path.name
    p2 = load_plan(path)
    assert p2.exptime_max_s == 3.5 and p2.aperture["ap_r"] == 7 and p2.created
    assert latest_plan("del cep", tmp_path).camera_model == "Cam A" and latest_plan("anderes", tmp_path) is None
    assert set(METHODS) == {"mono", "monorgb", "osc", "dslr"}


def _wcs(nx=600, ny=500, scale=1.44, ra=337.29, dec=58.41):
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.crpix = [nx / 2, ny / 2]
    w.wcs.crval = [ra, dec]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cdelt = [-scale / 3600, scale / 3600]
    return w


def test_night_altitudes_has_moon_columns():
    site = Site("T", 50.0, 8.0, 100.0)
    df = night_altitudes(337.29, 58.42, site, dt.date(2026, 11, 10), step_min=60)
    for c in ("alt_moon", "moon_sep", "moon_illum", "moon_ok", "ok_moon"):
        assert c in df
    assert df["moon_illum"].between(0, 1).all() and df["moon_sep"].between(0, 180).all()
    assert df["alt_moon"].between(-90, 90).all()


def test_moon_illum_full_vs_new():
    site = Site("T", 50.0, 8.0, 100.0)
    new = night_altitudes(0, 0, site, dt.date(2026, 11, 9), step_min=360)["moon_illum"].mean()
    full = night_altitudes(0, 0, site, dt.date(2026, 11, 24), step_min=360)["moon_illum"].mean()   # etwa 15 Tage spaeter
    assert full > new + 0.5


def test_plane_wcs_positions_consistent():
    from varphot.plan import plane_wcs
    w = _wcs()
    wp = plane_wcs(w, (0.5, 0.5))
    ra, dec = 337.30, 58.42
    xr, yr = w.world_to_pixel_values(ra, dec)
    xp, yp = wp.world_to_pixel_values(ra, dec)
    assert xp == pytest.approx((xr - 0.5) / 2, abs=1e-6) and yp == pytest.approx((yr - 0.5) / 2, abs=1e-6)


def test_check_field_stars_flags_the_limiting_comp_and_faint_star():
    from varphot.plan import check_field_stars, comp_v_min
    w = _wcs()
    yy, xx = np.mgrid[0:500, 0:600]
    img = 100.0 + np.random.default_rng(9).normal(0, 4, (500, 600))
    pos = {"T": (300, 250, 8000.0), "c1": (120, 100, 15000.0), "c2": (450, 400, 3000.0), "c3": (150, 380, 60.0)}   # c1 ist heller als das Ziel
    s = 5.0 / 2.355
    for _, (x0, y0, pk) in pos.items():
        img += pk * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * s * s))
    img = np.clip(img, 0, 16383)
    rows = []
    for k, (x0, y0, pk) in pos.items():
        ra, dec = w.pixel_to_world_values(x0, y0)
        rows.append(dict(id=k, role="target" if k == "T" else "comp", ra=float(ra), dec=float(dec), V=4.0 - 2.5 * np.log10(pk / 8000.0)))
    cat = pd.DataFrame(rows)
    t = check_field_stars(img, w, cat, exptime_s=1.0, limit_adu=12287, offset=100, aperture=aperture_from_fwhm(5.0), gain=1.0,
                          read_noise_e=5.0, max_adu=16383)
    r = t.set_index("id")
    assert r.loc["c1", "limiting"] and not r.loc["T", "limiting"]                    # der helle Comp schlaegt zuerst an
    assert r.loc["c1", "t_max_s"] < r.loc["T", "t_max_s"] < r.loc["c2", "t_max_s"]
    assert r.loc["c1", "t_max_s"] == pytest.approx(1.0 * (12287 - 100) / (15100 - 100), rel=0.03)
    assert r.loc["c1", "over_limit"] and not r.loc["T", "over_limit"]                # c1 (15 100 ADU) ueber der Obergrenze 12 287, das Ziel (8 100) darunter
    assert not r.loc["c1", "saturated"]                                              # 15 100 < 98 % von 16 383: noch nicht abgeschnitten, aber zu hell fuer die 75-%-Regel
    assert not r.loc["c3", "ok_snr"] and r.loc["T", "ok_snr"]                        # der schwache Comp hat zu wenig S/N
    vmin = comp_v_min(t, 1.0, 1.0, 12287, 100)
    assert vmin is not None and vmin == pytest.approx(4.0 - 2.5 * np.log10((12287 - 100) / (8100 - 0)), abs=0.1)


def test_field_of_view_from_setup():
    from varphot.plan import field_of_view_deg
    lo, sh = field_of_view_deg((6252, 4176), 3.76, 1645.0)      # QHY268M am C9.25 mit Reducer
    assert (lo, sh) == (0.82, 0.55) or (abs(lo - 0.8185) < 0.01 and abs(sh - 0.5466) < 0.01)
    assert field_of_view_deg((4176, 6252), 3.76, 1645.0) == (lo, sh)        # Reihenfolge egal: lange Seite zuerst
