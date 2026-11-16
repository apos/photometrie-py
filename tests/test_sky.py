"""Himmel im Ring (varphot/sky.py): Sigma-Clipping nur auf den Ringpixeln (KONZEPT §11.17)."""
import numpy as np
import pytest

from varphot.batch import measure_frame
from varphot.config import CFG
from varphot.sky import sky_from_values, sky_level

RNG = np.random.default_rng(7)


def _flat(n=200, sky=1000.0, sd=10.0):
    return RNG.normal(sky, sd, (n, n))


def _star(img, x, y, peak, sigma=2.0):
    yy, xx = np.indices(img.shape)
    img += peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))


def test_flat_sky_is_unchanged_by_clipping():
    img = _flat()
    clipped = sky_level(img, (100, 100), 18, 26, dict(CFG, sky_clip_sigma=3.0))[0]
    plain = sky_level(img, (100, 100), 18, 26, dict(CFG, sky_clip_sigma=None))[0]
    assert clipped == pytest.approx(plain, abs=1.0)            # Rauschen 10 ADU, Ring ~1100 px: Unterschied klein


def test_bright_neighbour_in_ring_is_removed():
    img = _flat()
    _star(img, 100, 100, 20000.0)                              # Ziel
    _star(img, 100 + 22, 100, 8000.0, sigma=4.0)               # heller Nachbar mitten im Ring (r = 22)
    clipped = sky_level(img, (100, 100), 18, 26, dict(CFG, sky_clip_sigma=3.0))
    plain = sky_level(img, (100, 100), 18, 26, dict(CFG, sky_clip_sigma=None))
    assert abs(clipped[0] - 1000.0) < abs(plain[0] - 1000.0)   # geclippt naeher am wahren Himmel
    assert abs(clipped[0] - 1000.0) < 2.0
    assert clipped[2] > 0 and plain[2] == 0                    # Pixel wurden verworfen / ohne Clipping nichts


def test_hot_pixels_do_not_matter():
    v = np.r_[RNG.normal(500, 5, 1000), np.full(40, 60000.0)]
    sky, used, rej = sky_from_values(v, 3.0, 5)
    assert sky == pytest.approx(500, abs=1.0) and rej >= 40 and used + rej == 1040


def test_off_switch_gives_plain_median():
    v = np.r_[RNG.normal(500, 5, 300), np.full(120, 5000.0)]
    assert sky_from_values(v, None)[0] == pytest.approx(float(np.median(v)))
    assert sky_from_values(v, 0)[2] == 0


def test_zero_spread_is_not_clipped():
    v = np.r_[np.full(80, 100.0), np.full(20, 5000.0)]         # MAD = 0: sonst waere jeder abweichende Pixel "Ausreisser"
    sky, used, rej = sky_from_values(v, 3.0, 5)
    assert rej == 0 and used == 100 and sky == 100.0


def test_empty_and_nan_rings():
    assert np.isnan(sky_from_values([], 3.0)[0])
    sky, used, rej = sky_from_values([np.nan] * 5 + [10.0] * 30, 3.0)
    assert sky == 10.0 and used == 30


def test_measure_frame_reports_clipped_pixels_and_better_flux_with_neighbour():
    from astropy.wcs import WCS
    import pandas as pd
    img = _flat()
    _star(img, 100, 100, 6000.0)
    _star(img, 122, 100, 9000.0, sigma=4.0)
    w = WCS(naxis=2); w.wcs.crpix = [1, 1]; w.wcs.cdelt = [-0.0003, 0.0003]; w.wcs.crval = [10.0, 20.0]; w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    ra, dec = w.pixel_to_world_values(99, 99)                  # 0-basiert (99, 99) = (x=100, y=100) bei crpix=1? robust: unten ueber x/y der Zeile pruefen
    stars = pd.DataFrame(dict(id=["t"], ra=[float(ra)], dec=[float(dec)]))
    on = measure_frame(img, w, stars, cfg=dict(CFG, sky_clip_sigma=3.0))[0]
    off = measure_frame(img, w, stars, cfg=dict(CFG, sky_clip_sigma=None))[0]
    assert on["sky_n_clipped"] > 0 and off["sky_n_clipped"] == 0
    assert abs(on["sky"] - 1000.0) <= abs(off["sky"] - 1000.0)


def test_aperture_sum_is_not_clipped_bright_star_flux_correct():
    """Regression: Sigma-Clipping darf die Summe in der Apertur (helle Sternkerne) nicht beruehren."""
    from varphot.photometry import aperture_flux
    img = _flat(sd=1.0)
    _star(img, 100, 100, 30000.0, sigma=2.5)
    f, _, bkg = aperture_flux(img, [(100, 100)], r_ap=10, r_in=18, r_out=26)
    true = 30000.0 * 2 * np.pi * 2.5 ** 2
    assert f[0] == pytest.approx(true, rel=0.03) and bkg[0] == pytest.approx(1000.0, abs=1.0)
