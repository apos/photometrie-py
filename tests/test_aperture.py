"""Aperturradius aus Wachstumskurve und S/N-Optimum: Gauss-Sterne mit bekannter Wahrheit, Fluegel, Rueckfall."""
import numpy as np
import pandas as pd
import pytest

from varphot.aperture import growth_curve, optimal_aperture, snr_curve


def _field(fwhm=4.0, n=12, size=520, sky=200.0, seed=1, wings=0.0, noise=3.0):
    """Sterne mit Gauss-Kern (optional Fluegel: zweite, breitere Gauss-Komponente mit Flussanteil ``wings``), Flussbereich 3e3–6e4."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:size, :size]
    img = np.full((size, size), sky) + rng.normal(0, noise, (size, size))
    pts = []
    while len(pts) < n:
        x, y = rng.uniform(45, size - 45, 2)
        if all(np.hypot(x - a, y - b) > 60 for a, b in pts):
            pts.append((x, y))
    fluxes = np.geomspace(3e3, 6e4, n)
    s = fwhm / 2.3548
    for (x, y), f in zip(pts, fluxes):
        r2 = (xx - x) ** 2 + (yy - y) ** 2
        img += f * (1 - wings) / (2 * np.pi * s ** 2) * np.exp(-r2 / (2 * s ** 2))
        if wings:
            s2 = 3 * s
            img += f * wings / (2 * np.pi * s2 ** 2) * np.exp(-r2 / (2 * s2 ** 2))
    tab = pd.DataFrame(dict(x=[p[0] for p in pts], y=[p[1] for p in pts], raw_max=fluxes / (2 * np.pi * s ** 2), fwhm=fwhm))
    return img, tab


def test_growth_curve_matches_gaussian_enclosed_fraction():
    img, tab = _field(n=4)
    r = np.array([2.0, 4.0, 6.0])
    F = growth_curve(img, tab[["x", "y"]].to_numpy(), r, 30.0, 40.0)
    s = 4.0 / 2.3548
    expected = 1 - np.exp(-r ** 2 / (2 * s ** 2))
    assert np.allclose(F[-1] / (np.geomspace(3e3, 6e4, 4)[-1]), expected, atol=0.02)


def test_snr_curve_has_interior_maximum():
    r = np.arange(1, 20, 0.5)
    s = 4.0 / 2.3548
    flux = 5e3 * (1 - np.exp(-r ** 2 / (2 * s ** 2)))
    snr = snr_curve(flux, r, sky_adu=200.0, gain=1.5, read_noise_e=3.0, sky_area_px=2000.0)
    k = int(np.argmax(snr))
    assert 0 < k < len(r) - 1 and 0.5 * 4.0 < r[k] < 1.2 * 4.0                         # Maximum nahe 0,7 FWHM (Gauss, himmelsbegrenzt)


def test_gaussian_optimum_and_growth_radius():
    img, tab = _field(fwhm=4.0)
    res = optimal_aperture(img, tab, 4.0, gain=1.5, read_noise_e=3.0)
    assert res["method"] == "growth+snr"
    assert 0.55 * 4 <= res["r_snr"] <= 0.9 * 4                                           # Optimum der schwachen Sterne ~0,67 FWHM
    assert 0.9 * 4 <= res["r_growth"] <= 1.3 * 4                                         # 95-%-Radius ~1,04 FWHM
    assert 4 <= res["ap_r"] <= 6 and res["snr_ratio"] >= 0.7                            # nie unter 1 FWHM, S/N nahe am Optimum
    assert res["ap_r_in"] == res["ap_r"] + 3 and res["ap_r_out"] > res["ap_r_in"]
    assert res["snr_ratio"] >= res["snr_ratio_handbook"] - 1e-9                          # besser oder gleich 1,5 × FWHM


def test_wings_enlarge_growth_radius_like_real_bright_stars():
    img0, tab0 = _field(fwhm=4.0, wings=0.0)
    img1, tab1 = _field(fwhm=4.0, wings=0.12)                                            # 12 % des Lichts in breiten Fluegeln
    r0, r1 = optimal_aperture(img0, tab0, 4.0), optimal_aperture(img1, tab1, 4.0)
    assert r1["r_growth"] > r0["r_growth"] + 1                                          # die feste 1,5-FWHM-Regel haette das nicht gesehen


def test_fallback_with_few_stars_and_at_edges():
    img, tab = _field()
    res = optimal_aperture(img, tab.head(2), 4.0)
    assert res["method"] == "fallback" and res["ap_r"] == 6 and "mindestens 3" in res["notes"][0]
    edge = tab.copy()
    edge["x"] = 5.0
    res = optimal_aperture(img, edge, 4.0)
    assert res["method"] == "fallback" and "Platz" in res["notes"][0]
    with pytest.raises(ValueError, match="positive Zahl"):
        optimal_aperture(img, tab, float("nan"))


def test_snr_is_reported_not_enforced():
    img, tab = _field(fwhm=4.0, wings=0.25)                                              # starke Fluegel: grosser Radius, S/N der schwachen Sterne leidet
    res = optimal_aperture(img, tab, 4.0, snr_floor=0.95)
    r95 = res["radii"][np.flatnonzero(res["growth"] >= 0.95)[0]]
    assert res["ap_r"] >= np.floor(r95) and res["ap_r"] <= 2.5 * 4.0                      # Flussanteil bestimmt den Radius
    assert res["snr_ratio"] < 0.95 and any("Kompromiss" in n for n in res["notes"])         # aber der S/N-Verlust wird genannt
