"""Transformationskoeffizienten an einem synthetischen Standardfeld mit bekannter Wahrheit."""
import numpy as np
import pandas as pd
import pytest

from varphot import (TransformSolution, catalog_from_vsp_table, fit_extinction, fit_transform, instrumental_table, linfit,
                     loo_validation, transform_target)
from varphot.synthetic import standard_field

RNG = np.random.default_rng(21)


@pytest.fixture(scope="module")
def field():
    cat, meas, truth = standard_field(n_stars=30, n_frames=10, noise_mag=0.008, rng=np.random.default_rng(4))
    instr, frames = instrumental_table(meas)
    return cat, meas, truth, instr, frames


def test_linfit_clips_outlier():
    x = np.linspace(0, 1, 20)
    y = 2 * x + 1 + RNG.normal(0, 0.005, 20)
    y[7] += 1.0
    f = linfit(x, y)
    assert f["slope"] == pytest.approx(2.0, abs=0.03) and not f["mask"][7] and f["n_used"] == 19
    with pytest.raises(ValueError):
        linfit([1, 2], [1, 2])


def test_instrumental_table_removes_frame_offsets(field):
    cat, meas, truth, instr, frames = field
    assert set(instr.columns) >= {"b", "g", "r", "b_sd"} and instr["g"].notna().all()
    assert instr["g_sd"].median() < 0.03                      # Pegelspruenge (0,03 mag) sind herausgerechnet
    assert set(frames["channel"]) == {"b", "g", "r"}


def test_fit_transform_recovers_coefficients(field):
    cat, meas, truth, instr, frames = field
    sol = fit_transform(cat, instr)
    assert sol.Tbv == pytest.approx(truth["Tbv"], rel=0.05)
    assert sol.Tb_bv == pytest.approx(truth["Tb_bv"], abs=0.03)
    assert sol.Tv_bv == pytest.approx(truth["Tv_bv"], abs=0.03)
    assert sol.Tr_bv == pytest.approx(truth["Tr_bv"], abs=0.03)
    assert sol.n_stars == 30 and 0.3 <= sol.bv_range[0] < sol.bv_range[1] <= 1.4 and not sol.warnings


def test_extinction_from_frame_offsets(field):
    cat, meas, truth, instr, frames = field
    k = fit_extinction(frames)
    for ch in ("b", "g", "r"):
        assert k[ch] == pytest.approx(truth["k"][ch], abs=0.06)


def test_transform_target_closer_to_truth_than_standardized(field):
    cat, meas, truth, instr, frames = field
    sol = fit_transform(cat, instr)
    # Ziel = Standardstern 3 gegen Comp = Standardstern 10
    t, c = cat.iloc[3], cat.iloc[10]
    dB, dV, dR = (instr[ch].iloc[3] - instr[ch].iloc[10] for ch in ("b", "g", "r"))
    out = transform_target(dB, dV, dR, dict(B=c["B"], V=c["V"], R=c["R"]), sol)
    assert abs(out["V"] - t["V"]) < 0.03 and abs(out["B"] - t["B"]) < 0.06
    assert abs(out["BV"] - (t["B"] - t["V"])) < 0.08
    std_V = c["V"] + dV
    assert abs(out["V"] - t["V"]) <= abs(std_V - t["V"]) + 1e-9          # Transformation verschlechtert nicht
    with pytest.raises(ValueError):
        transform_target(None, dV, None, dict(B=1, V=1), sol)             # weder dB noch Katalogfarbe


def test_loo_validation_improves_over_standardized(field):
    cat, meas, truth, instr, frames = field
    sol = fit_transform(cat, instr)
    v = loo_validation(cat, instr, sol)
    assert set(v) == {"B", "V", "R"} and v["V"]["n"] == 30
    assert v["V"]["rms_transformed"] < 0.03
    assert v["V"]["rms_transformed"] < v["V"]["rms_standardized"]         # Transformation lohnt sich bei Farbspreizung
    assert v["B"]["rms_transformed"] < v["B"]["rms_standardized"]


def test_too_few_stars_and_narrow_color_range_warn():
    cat, meas, truth = standard_field(n_stars=8, n_frames=6, rng=np.random.default_rng(2), bv_range=(0.6, 0.8))
    instr, _ = instrumental_table(meas)
    sol = fit_transform(cat, instr, min_n=6)
    assert any("Farbbereich" in w for w in sol.warnings) and any("Standardsterne" in w for w in sol.warnings)
    with pytest.raises(ValueError):
        fit_transform(cat.iloc[:4], instr, min_n=6)


def test_solution_roundtrip(tmp_path, field):
    cat, meas, truth, instr, frames = field
    sol = fit_transform(cat, instr)
    sol.camera_model, sol.k_extinction = "X", fit_extinction(frames)
    p = sol.save(tmp_path / "t.json")
    back = TransformSolution.load(p)
    assert back.Tv_bv == sol.Tv_bv and back.camera_model == "X" and isinstance(back.bv_range, tuple)


def test_catalog_from_vsp_table():
    vsp = pd.DataFrame(dict(label=["a", "b", "c"], ra=[1.0, 2.0, 3.0], dec=[1.0, 2.0, 3.0], V=[9.0, 10.0, 11.0],
                            B=[9.5, np.nan, 11.6], Rc=[8.8, 9.7, None]))
    c = catalog_from_vsp_table(vsp)
    assert c["id"].tolist() == ["a", "c"] and np.isnan(c["R"].iloc[1]) and c["R"].iloc[0] == 8.8


def test_gaia_derived_catalog_is_refused():
    cat, meas, truth = standard_field(n_stars=12, n_frames=4, rng=np.random.default_rng(8))
    instr, _ = instrumental_table(meas)
    bad = cat.copy(); bad["source"] = ["Gaia"] * 3 + ["AAVSO"] * 9
    with pytest.raises(ValueError, match="Gaia"):
        fit_transform(bad, instr)
    bad2 = cat.copy(); bad2["id"] = ["g1"] + list(cat["id"][1:])
    with pytest.raises(ValueError, match="Gaia-Kennung"):
        fit_transform(bad2, instr)
    ok = cat.copy(); ok["source"] = "AAVSO"
    assert fit_transform(ok, instr).n_stars == 12                                  # saubere Quelle geht durch


def test_transformed_light_curve_recovers_catalog_values_better_than_standardized(field):
    from varphot import transformed_light_curve
    cat, meas, truth, instr, frames = field
    sol = fit_transform(cat, instr)
    target = cat["id"].iloc[2]
    stars = cat.copy(); stars["role"] = np.where(stars["id"] == target, "target", "comp")
    lc = transformed_light_curve(meas, stars, target, sol)
    t = cat[cat["id"] == target].iloc[0]
    assert len(lc) == 10 and (lc["n_comps"] >= 20).all()
    assert abs(lc["V"].median() - t["V"]) < 0.03 and abs(lc["B"].median() - t["B"]) < 0.06
    assert abs(lc["BV"].median() - (t["B"] - t["V"])) < 0.08
    comps = stars[stars["role"] == "comp"].set_index("id")                                # ohne Transformation: Δv + V_comp, Median ueber die Comps
    from varphot.transform import transform_target  # noqa: F401
    mv = -2.5 * np.log10(meas["g"].pivot_table(index="file", columns="star_id", values="flux"))
    std = np.median((mv[target].to_numpy()[:, None] - mv[comps.index].to_numpy()) + comps["V"].to_numpy()[None, :], axis=1)
    assert abs(lc["V"].median() - t["V"]) <= abs(np.median(std) - t["V"]) + 1e-9
    with pytest.raises(ValueError, match="Gaia"):
        bad = stars.copy(); bad["source"] = "Gaia"
        transformed_light_curve(meas, bad, target, sol)
