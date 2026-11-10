"""Tests fuer varphot.detect (synthetisch + optional echtes Bild)."""
from pathlib import Path

import numpy as np
import pytest

from varphot import detect

ROOT = Path(__file__).resolve().parent.parent
M16 = ROOT / "demo" / "real_m16" / "m16_ha_benchmark.fit"


def _field(seed=0, n=300, star=(150.0, 120.0), blob=False):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    img = rng.normal(100, 3, (n, n))
    g = lambda x0, y0, s, a: a * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * s ** 2))
    img += g(*star, 5 / 2.355, 400)                  # Stern, FWHM 5 px
    if blob:
        img += g(60, 220, 25, 25)                    # breiter, flacher Nebelknoten
    return img


@pytest.mark.parametrize("mode", ["global", "2d"])
def test_finds_star_at_known_position(mode):
    src, med, std = detect(_field(), fwhm=5.0, nsigma=8, background=mode)
    assert src is not None
    d = np.hypot(src["x_centroid"] - 150, src["y_centroid"] - 120)
    assert d.min() < 0.3


def test_2d_background_ignores_broad_blob():
    src, *_ = detect(_field(blob=True), fwhm=5.0, nsigma=8, background="2d")
    d = np.hypot(src["x_centroid"] - 60, src["y_centroid"] - 220)
    assert d.min() > 15                               # kein Treffer auf dem Nebelknoten


def test_invalid_background_raises():
    with pytest.raises(ValueError):
        detect(_field(), background="foo")


@pytest.mark.skipif(not M16.exists(), reason="M16-Testbild nicht vorhanden")
def test_real_image_star_count_plausible():
    from astropy.io import fits
    img = fits.getdata(M16)
    src, *_ = detect(img, fwhm=5.0, nsigma=25, background="2d")
    assert 3000 < len(src) < 12000                    # gemessen 2026-11-10: 7097
    assert src["x_centroid"].min() >= 0 and src["x_centroid"].max() <= img.shape[1]
