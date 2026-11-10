"""Planung: Sternmetriken, Belichtungsempfehlung, Aperturen, Plan-Datei (synthetische Daten)."""
import datetime as dt

import numpy as np
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
    assert set(METHODS) == {"mono", "osc", "dslr"}
