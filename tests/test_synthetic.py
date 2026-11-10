"""Defokus-Simulation (defocus_image): Fluss, Breitenzuwachs, Ringform."""
import numpy as np
import pytest

from varphot.synthetic import defocus_image


def _star(size=121, fwhm=3.0, flux=1e5, bkg=100.0):
    yy, xx = np.mgrid[:size, :size]
    s = fwhm / 2.3548
    c = size // 2
    return bkg + flux / (2 * np.pi * s * s) * np.exp(-((xx - c) ** 2 + (yy - c) ** 2) / (2 * s * s)), flux


def _fwhm(img):
    c = img.shape[0] // 2
    prof = img[c] - np.median(img)
    half = prof.max() / 2
    above = np.flatnonzero(prof >= half)
    return above[-1] - above[0] + 1


@pytest.mark.parametrize("kind", ["gauss", "donut"])
def test_flux_is_conserved(kind):
    img, flux = _star()
    out = defocus_image(img, 12.0, kind)
    assert (out - 100.0).sum() == pytest.approx(flux, rel=0.01) and out.shape == img.shape


def test_gauss_width_adds_in_quadrature():
    img, _ = _star(fwhm=3.0)
    out = defocus_image(img, 8.0, "gauss")
    assert _fwhm(out) == pytest.approx(np.hypot(3.0, 8.0), abs=1.5)


def test_donut_has_central_hole_and_outer_diameter():
    img, _ = _star(fwhm=2.0)
    out = defocus_image(img, 40.0, "donut", obstruction=0.4)
    c = out.shape[0] // 2
    prof = out[c] - 100.0
    assert prof[c] < 0.5 * prof.max()                                   # Loch in der Mitte
    ring = np.flatnonzero(prof > 0.05 * prof.max())
    assert 36 <= ring[-1] - ring[0] + 1 <= 44                           # Aussendurchmesser ~ 40 px


def test_zero_blur_returns_copy_and_bad_kind_raises():
    img, _ = _star()
    out = defocus_image(img, 0.0)
    assert np.array_equal(out, img) and out is not img
    with pytest.raises(ValueError, match="kind"):
        defocus_image(img, 5.0, "box")
