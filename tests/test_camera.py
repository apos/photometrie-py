"""Kamera-Charakterisierung an synthetischen Bayer-Bildern mit bekannter Wahrheit."""
import numpy as np
import pytest

from varphot import (bayer_planes, dark_current_e_per_s, detect_saturation, exposure_from_header, full_well_e, gain_from_pair,
                     iso_from_header, linearity_curve, pair_stats,
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


def test_detect_saturation_plateau_vs_bright_unsaturated():
    sat = [16383.0] * 6 + [12000.0, 9000.0]
    r = detect_saturation(sat)
    assert r["saturated"] and r["max_adu"] == 16383 and r["bits"] == 14 and r["n_at_max"] == 6
    bright = [15800.0, 15200.0, 14000.0, 9000.0]                    # hell, aber nie am Anschlag
    assert not detect_saturation(bright)["saturated"]
    assert not detect_saturation([16383.0] * 5, nominal=65535)["saturated"]     # Plateau, aber weit unter der nominellen Grenze
    assert detect_saturation([4095.0] * 4)["bits"] == 12


def test_header_helpers():
    assert exposure_from_header({"EXPOSURE": "2.5"}) == 2.5 and exposure_from_header({"X": 1}) is None
    assert exposure_from_header({"EXPTIME": "abc", "EXPOSURE": 3}) == 3.0
    assert iso_from_header({"ISOSPEED": 640}) == 640.0 and iso_from_header({}) is None


def test_presets_and_profiles(tmp_path):
    from varphot import get_preset, preset_choices, PRESETS
    from varphot.camera_presets import slug
    assert {"ares-c-pro", "lumix-s9", "eigene"} <= set(PRESETS)
    s9 = get_preset("lumix-s9")
    assert s9.format_px == (6000, 4000) and s9.bit_depth is None and s9.raw_input == "raw" and s9.bayer_status == "E"
    assert get_preset("ares-c-pro").bit_depth == 14 and "Gain 0, LRN" in get_preset("ares-c-pro").settings
    assert get_preset("ares-c-pro").settings["Gain 0, LRN"].full_well_e == 72889
    assert ("Panasonic Lumix DC-S9", "lumix-s9") in preset_choices()
    assert slug("Gain 0, LRN") == "gain-0-lrn" and slug("ISO 640 (Dual Native high)") == "iso-640-dual-native-high"
    with pytest.raises(KeyError):
        get_preset("gibt-es-nicht")
    from varphot.observer import camera_label, upsert_camera
    a, b = Camera(model="X", gain_setting="ISO 100"), Camera(model="X", gain_setting="ISO 640")
    cams = upsert_camera(upsert_camera([], a), b)
    cams = upsert_camera(cams, Camera(model="X", gain_setting="ISO 100", gain_e_per_adu=1.5))
    assert [c.gain_setting for c in cams] == ["ISO 640", "ISO 100"] and cams[-1].gain_e_per_adu == 1.5
    assert camera_label(a) == "X — ISO 100"
    p = tmp_path / "o.json"
    save_config(Observer("abcd", "S", b, cams), [], p)
    o, _ = load_config(p)
    assert len(o.cameras) == 2 and o.camera.gain_setting == "ISO 640"


def _plane_values(level_adu, sigma, n=10000, rng=None, transform=None):
    rng = rng or np.random.default_rng(3)
    v = np.rint(rng.normal(level_adu, sigma, n))
    return transform(v) if transform else v


def test_histogram_gaps_clean_vs_companded_vs_scaled():
    from varphot import histogram_gaps, compression_verdict
    clean = [histogram_gaps(_plane_values(lv, 12.0)) for lv in (800, 3000, 9000, 14000)]
    assert all(r["reliable"] and r["gap_fraction"] < 0.01 and r["step"] == 1 for r in clean)
    assert compression_verdict(clean)["suspect"] is False
    # verlustbehaftet: ab 2000 ADU nur jeder 4. Wert (wie eine Kompanderung)
    comp = lambda v: np.where(v > 2000, 2000 + np.round((v - 2000) / 4) * 4, v)
    cmp_ = [histogram_gaps(_plane_values(lv, 12.0, transform=comp)) for lv in (800, 3000, 9000, 14000)]
    assert cmp_[0]["gap_fraction"] < 0.01 and cmp_[2]["gap_fraction"] > 0.5 and cmp_[2]["step"] == 4
    v = compression_verdict(cmp_)
    assert v["suspect"] is True and v["worst_gap"] > 0.5
    # skaliert: 14 -> 16 Bit (x4): nur Vielfache von 4
    scaled = [histogram_gaps(_plane_values(lv, 12.0, transform=lambda x: x * 4)) for lv in (800, 3000, 9000)]
    assert all(r["step"] == 4 and r["gap_fraction"] > 0.5 for r in scaled)


def test_histogram_gaps_low_noise_not_reliable():
    from varphot import histogram_gaps, compression_verdict
    r = histogram_gaps(_plane_values(500, 1.0))
    assert r["reliable"] is False
    assert compression_verdict([r, r])["suspect"] is None


def test_camera_kind_labels_mono_and_color():
    from varphot import PRESETS
    from varphot.observer import Camera, camera_kind
    assert camera_kind(Camera(model="QHY268M", cam_type="CMOS")) == "Mono"
    assert camera_kind(Camera(model="X", cam_type="CMOS", bayer_pattern="RGGB")) == "Farbe (Bayer RGGB)"
    assert camera_kind(Camera(model="Y", cam_type="DSLR")) == "Farbe (DSLR)"
    assert camera_kind(PRESETS["qhy268m"]) == "Mono"
    assert camera_kind(PRESETS["ares-c-pro"]) == "Farbe (Bayer RGGB)"
    assert camera_kind(PRESETS["lumix-s9"]).startswith("Farbe")
