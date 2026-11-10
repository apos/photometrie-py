import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from varphot.cfa import split_cfa_array, split_cfa_fits


def raw_with_star(nx=400, ny=300, pattern="RGGB", x0=203.0, y0=151.0):
    yy, xx = np.mgrid[0:ny, 0:nx]
    img = 100.0 + 4000.0 * np.exp(-((xx - x0) ** 2 + (yy - y0) ** 2) / (2 * 3.0 ** 2))
    w = WCS(naxis=2)
    w.wcs.crpix = [nx / 2, ny / 2]
    w.wcs.crval = [337.29, 58.41]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.cdelt = [-1.5 / 3600, 1.5 / 3600]
    return img, w


def test_split_arrays_and_green_mean():
    img = np.arange(16, dtype=float).reshape(4, 4)
    d = split_cfa_array(img, "RGGB", with_g12=True)
    assert d["R"][0].tolist() == [[0, 2], [8, 10]] and d["B"][0].tolist() == [[5, 7], [13, 15]]
    assert d["G"][0].tolist() == [[2.5, 4.5], [10.5, 12.5]] and d["G"][1] == (0.5, 0.5)
    assert d["G1"][1] == (1.0, 0.0) and d["G2"][1] == (0.0, 1.0) and d["R"][1] == (0.0, 0.0) and d["B"][1] == (1.0, 1.0)


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG"])
def test_split_fits_keeps_star_at_same_sky_position(tmp_path, pattern):
    img, w = raw_with_star()
    hdr = w.to_header()
    hdr["EXPTIME"], hdr["BAYERPAT"], hdr["PIXSCALE"] = 2.5, pattern, 1.5
    p = tmp_path / "light_0001.fits"
    fits.PrimaryHDU(img.astype(np.float32), hdr).writeto(p)
    outs = split_cfa_fits(p, tmp_path / "out")
    assert [o.name for o in outs] == ["light_0001_R.fits", "light_0001_G.fits", "light_0001_B.fits"]
    ra, dec = w.pixel_to_world_values(203.0, 151.0)                                    # Stern im Rohbild
    for o in outs:
        with fits.open(o) as h:
            d, hh = h[0].data, h[0].header
            assert d.shape == (150, 200) and hh["EXPTIME"] == 2.5 and "BAYERPAT" not in hh and hh["CFACHAN"] in "RGB"
            assert hh["PIXSCALE"] == pytest.approx(3.0)
            wp = WCS(hh)
            x, y = wp.world_to_pixel_values(ra, dec)
            yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]]
            m = (np.hypot(xx - x, yy - y) < 6)
            cy, cx = (np.sum(yy[m] * (d[m] - 100)) / np.sum(d[m] - 100), np.sum(xx[m] * (d[m] - 100)) / np.sum(d[m] - 100))
            assert abs(cx - x) < 0.35 and abs(cy - y) < 0.35, (o.name, cx, x, cy, y)      # Schwerpunkt liegt dort, wo die WCS den Stern erwartet
    assert (tmp_path / "out" / "light_0001_G.fits").exists()
