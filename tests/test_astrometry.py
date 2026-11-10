"""Tests fuer varphot.astrometry (ASTAP-Solve, Fallback, gnomonische Projektion)."""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from varphot import gnomonic, solve_image
from varphot.astrometry import ASTAP_DEFAULT

ROOT = Path(__file__).resolve().parent.parent
M16 = ROOT / "demo" / "real_m16" / "m16_ha_benchmark.fit"   # lokal, nicht im Repo (.gitignore)


def test_gnomonic_center_and_axes():
    assert gnomonic(10, 20, 10, 20) == pytest.approx((0, 0), abs=1e-9)
    _, y = gnomonic(10, 21, 10, 20)
    assert y == pytest.approx(1.0, abs=0.01)           # 1 Grad noerdlich
    x, _ = gnomonic(11, 0, 10, 0)
    assert x == pytest.approx(-1.0, abs=0.01)          # Osten liegt links (x negativ)


def test_gnomonic_far_hemisphere_is_nan():
    """Regression v0.2.0: Orion (RA 89) erschien gespiegelt im Feld von M16 (RA 275)."""
    x, y = gnomonic(88.8, 7.4, 274.75, -13.87)
    assert np.isnan(x) and np.isnan(y)
    xs, ys = gnomonic(np.array([88.8, 275.0]), np.array([7.4, -13.0]), 274.75, -13.87)
    assert np.isnan(xs[0]) and np.isfinite(xs[1])


def test_blank_image_gives_no_wcs(tmp_path):
    f = tmp_path / "blank.fits"
    fits.PrimaryHDU(np.random.default_rng(1).normal(100, 5, (300, 300)).astype("f4")).writeto(f)
    r = solve_image(f)
    assert r.source == "keine" and r.wcs is None      # nie eine WCS erfinden


@pytest.mark.skipif(not (M16.exists() and Path(ASTAP_DEFAULT).exists()),
                    reason="M16-Testbild oder ASTAP nicht vorhanden")
def test_real_image_solves_with_expected_scale():
    r = solve_image(M16, radius_deg=5)
    assert r.source == "ASTAP"
    scale = r.wcs.proj_plane_pixel_scales()[0].to("arcsec").value
    assert scale == pytest.approx(206.265 * 1.9 / 479.46, abs=0.005)   # aus XPIXSZ und FOCALLEN
