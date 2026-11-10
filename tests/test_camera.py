"""Kamera-Charakterisierung an synthetischen Bayer-Bildern mit bekannter Wahrheit."""
import numpy as np
import pytest

from varphot import (bayer_planes, dark_current_e_per_s, full_well_e, gain_from_pair, linearity_curve, pair_stats,
                     ptc_fit, read_noise_e)
from varphot.camera import center_roi
from varphot.observer import Camera, Observer, load_config, save_config
from varphot.synthetic import bayer_frame

RNG = np.random.default_rng(11)
GAIN, RN, OFF, MAXADU = 2.0, 3.0, 100.0, 16383


def frame(sig):
    return bayer_frame((400, 600), sig, GAIN, RN, OFF, MAXADU, rng=RNG)


def test_bayer_planes_split_rggb():
    img = np.arange(16, dtype=float).reshape(4, 4)
    p = bayer_planes(img, "RGGB")
    assert p["R"].tolist() == [[0, 2], [8, 10]] and p["G1"].tolist() == [[1, 3], [9, 11]]
    assert p["G2"].tolist() == [[4, 6], [12, 14]] and p["B"].tolist() == [[5, 7], [13, 15]]
    assert bayer_planes(img, "BGGR")["B"].tolist() == [[0, 2], [8, 10]]
    with pytest.raises(ValueError):
        bayer_planes(img, "XYZW")


def test_center_roi_size():
    assert center_roi(np.zeros((300, 400)), 100).shape == (100, 100)
    assert center_roi(np.zeros((50, 40)), 100).shape == (40, 40)


def test_gain_from_pair_and_read_noise_recovered():
    b1, b2 = (bayer_planes(frame(0.0))["G1"], bayer_planes(frame(0.0))["G1"])
    f1, f2 = (bayer_planes(frame(20000.0))["G1"], bayer_planes(frame(20000.0))["G1"])
    g = gain_from_pair(f1, f2, b1, b2)
    assert g == pytest.approx(GAIN, rel=0.05)
    assert read_noise_e(b1, b2, GAIN) == pytest.approx(RN, rel=0.1)


def test_ptc_fit_recovers_gain_per_plane():
    levels = [800, 2500, 5000, 9000, 14000, 20000, 26000]
    for plane in ("R", "G1", "B"):
        means, vars_ = [], []
        for s in levels:
            a, b = bayer_planes(frame(s))[plane], bayer_planes(frame(s))[plane]
            m, v = pair_stats(a, b)
            means.append(m); vars_.append(v)
        res = ptc_fit(means, vars_, offset=OFF, max_adu=MAXADU)
        assert res["gain"] == pytest.approx(GAIN, rel=0.04), plane
        assert res["r2"] > 0.99 and res["n"] >= 5


def test_ptc_fit_needs_enough_points():
    with pytest.raises(ValueError):
        ptc_fit([1000, 2000], [500, 900], offset=100, max_adu=16383)


def test_full_well_follows_vendor_convention():
    assert full_well_e(4.449, 16383) == pytest.approx(72889, rel=1e-3)        # Player One IMX533 (Hersteller/AAVSO-Forum)
    assert full_well_e(2.0, 16383, offset=100) == pytest.approx(2 * 16283)


def test_linearity_finds_saturation_and_short_time_limits():
    t = np.arange(2, 62, 2.0)
    true = 300.0 * t + 1900.0                                  # ADU, Offset 1900, 300 ADU/s -> 13 000 ADU bei ~37 s
    m = np.where(true > 13000, 13000 + 0.2 * (true - 13000), true)   # weiche Saettigung ab 13 000 ADU
    m = np.where(t < 6, m * 0.97, m)                           # kurze Zeiten: Verschlusseffekt -3 %
    res = linearity_curve(t, m, max_adu=14000, tol_pct=1.0)
    assert res["b"] == pytest.approx(300.0, rel=0.01) and res["a"] == pytest.approx(1900, rel=0.05)
    assert res["t_min"] == 6.0                                  # 2 und 4 s fallen heraus
    assert 34 <= res["t_max"] <= 38 and res["adu_max"] <= 13100  # Ende dort, wo die Saettigung beginnt


def test_linearity_all_linear():
    t = np.arange(2, 40, 2.0)
    res = linearity_curve(t, 50.0 * t + 1000.0, max_adu=3000)
    assert res["linear"].all() and res["t_min"] == t[0] and res["t_max"] == t[-1]


def test_dark_current_slope():
    t = np.array([10, 30, 60, 120, 240.0])
    dark_adu_per_s = 0.5 / GAIN                                # 0,5 e-/s/px
    means = OFF + dark_adu_per_s * t + RNG.normal(0, 0.02, len(t))
    assert dark_current_e_per_s(t, means, GAIN) == pytest.approx(0.5, rel=0.05)
    with pytest.raises(ValueError):
        dark_current_e_per_s([1, 2], [1, 2], 1.0)


def test_camera_profile_roundtrip_and_old_files_load(tmp_path):
    p = tmp_path / "o.json"
    save_config(Observer("abcd", "S", Camera(model="X", bayer_pattern="RGGB", bit_depth=14, saturation_adu=16383,
                                             offset_adu=100, full_well_e=72889, gain_e_per_adu=4.449, source="gemessen")), [], p)
    o, _ = load_config(p)
    assert o.camera.bayer_pattern == "RGGB" and o.camera.bit_depth == 14 and o.camera.full_well_e == 72889
    p.write_text('{"aavso_code": "", "site_name": "", "camera": {"model": "alt", "gain_e_per_adu": 1.0}, "sites": []}')
    assert load_config(p)[0].camera.model == "alt"              # alte Datei ohne neue Felder


def test_summarize_and_group():
    from varphot.camera import group_by_exposure, summarize_frame
    img = bayer_frame((300, 400), 5000.0, GAIN, RN, OFF, MAXADU, rng=RNG)
    s = summarize_frame(img, "RGGB", 50)
    assert set(s["rois"]) == {"R", "G1", "G2", "B"} and s["rois"]["G1"].shape == (50, 50)
    assert s["max"] == img.max() and s["median"] == pytest.approx(np.median(img))
    recs = [dict(exptime=1.0), dict(exptime=1.0004), dict(exptime=2.0), dict(exptime=2.0), dict(exptime=2.0), dict(exptime=3.0)]
    g = group_by_exposure(recs, decimals=2)
    assert list(g) == [1.0, 2.0] and len(g[2.0]) == 3          # 3.0 hat nur ein Bild -> faellt weg
