"""Regressionstests Aperturphotometrie."""
import numpy as np
import pytest


def test_aperture_flux_not_clipped_for_bright_star():
    """Regression: photutils ApertureStats clippt standardmaessig -> helle Sternkerne fehlten im Fluss."""
    from varphot import aperture_flux
    yy, xx = np.mgrid[0:100, 0:100]
    f = 1e5
    img = 50 + f / (2 * np.pi * 1.6 ** 2) * np.exp(-((xx - 50) ** 2 + (yy - 50) ** 2) / (2 * 1.6 ** 2))
    flux, _, bkg = aperture_flux(img, [(50, 50)], r_ap=8, r_in=14, r_out=22, cfg={"sat_adu": 1e9, "ap_r": 8, "ap_r_in": 14, "ap_r_out": 22})
    assert flux[0] == pytest.approx(f, rel=0.01) and bkg[0] == pytest.approx(50, abs=0.5)

