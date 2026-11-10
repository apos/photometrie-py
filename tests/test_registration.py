"""WCS-Uebertragung: bekannte Verschiebung/Drehung, Rundreise Pixel->Himmel, defokussierte Bilder, Fehlerfaelle."""
import numpy as np
import pytest
from astropy.wcs import WCS

from varphot.registration import bright_sources, register_frame, wcs_from_transform
from varphot.synthetic import defocus_image


def _ref_wcs(nx=800, ny=600):
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.crval, w.wcs.cdelt, w.wcs.ctype = [nx / 2, ny / 2], [100.0, 30.0], [-0.5 / 3600, 0.5 / 3600], ["RA---TAN", "DEC--TAN"]
    return w


def _stars(n=40, nx=800, ny=600, seed=2):
    rng = np.random.default_rng(seed)
    return np.c_[rng.uniform(40, nx - 40, n), rng.uniform(40, ny - 40, n)], np.geomspace(2e3, 6e4, n)[::-1]


def _render(xy, flux, fwhm, shape=(600, 800), sky=200.0, seed=5, noise=3.0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    img = sky + rng.normal(0, noise, shape)
    s = fwhm / 2.3548
    for (x, y), f in zip(xy, flux):
        x0, x1, y0, y1 = int(x) - 25, int(x) + 26, int(y) - 25, int(y) + 26
        sub = (slice(max(y0, 0), min(y1, shape[0])), slice(max(x0, 0), min(x1, shape[1])))
        img[sub] += f / (2 * np.pi * s * s) * np.exp(-((xx[sub] - x) ** 2 + (yy[sub] - y) ** 2) / (2 * s * s))
    return img


def _moved(xy, angle_deg, shift):
    """Sternpositionen im verschobenen/gedrehten Bild (Drehung um die Bildmitte)."""
    a = np.radians(angle_deg)
    c = np.array([400.0, 300.0])
    R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return (xy - c) @ R.T + c + np.asarray(shift)


def test_wcs_from_transform_roundtrip():
    ref = _ref_wcs()
    A = np.array([[np.cos(0.1), -np.sin(0.1)], [np.sin(0.1), np.cos(0.1)]])
    M = np.eye(3); M[:2, :2] = A; M[:2, 2] = [13.5, -7.25]
    w = wcs_from_transform(ref, M)
    p = np.array([[120.0, 80.0], [640.0, 410.0]])
    q = p @ A.T + M[:2, 2]
    assert np.allclose(w.pixel_to_world_values(p[:, 0], p[:, 1]), ref.pixel_to_world_values(q[:, 0], q[:, 1]), atol=1e-9)
    assert np.sqrt(abs(np.linalg.det(w.pixel_scale_matrix))) * 3600 == pytest.approx(0.5, rel=1e-6)


@pytest.mark.parametrize("angle,shift", [(0.0, (0, 0)), (0.0, (17.3, -9.1)), (1.2, (-25.0, 12.0))])
def test_register_recovers_known_motion(angle, shift):
    xy, flux = _stars()
    ref_img = _render(xy, flux, 4.0, seed=1)
    ref_xy = bright_sources(ref_img, 4.0)
    xy2 = _moved(xy, angle, shift)
    keep = (xy2[:, 0] > 30) & (xy2[:, 0] < 770) & (xy2[:, 1] > 30) & (xy2[:, 1] < 570)
    img = _render(xy2[keep], flux[keep], 4.0, seed=2)
    reg = register_frame(ref_xy, img, _ref_wcs(), 4.0)
    assert reg.ok and reg.n_match >= 10 and reg.rms_px < 0.5 and reg.scale == pytest.approx(1.0, abs=0.003)
    # die abgeleitete WCS bildet die bewegten Sterne auf dieselben Himmelspositionen ab wie die Referenz
    sky_new = reg.wcs.pixel_to_world_values(xy2[keep][:, 0], xy2[keep][:, 1])
    sky_ref = _ref_wcs().pixel_to_world_values(xy[keep][:, 0], xy[keep][:, 1])
    err_arcsec = np.hypot((sky_new[0] - sky_ref[0]) * np.cos(np.radians(30)), sky_new[1] - sky_ref[1]) * 3600
    assert np.median(err_arcsec) < 0.2 and err_arcsec.max() < 0.6                  # unter ~1 px (0,5″/px)


def test_register_defocused_frame_against_sharp_reference():
    xy, flux = _stars()
    ref_xy = bright_sources(_render(xy, flux, 3.0, seed=1), 3.0)
    img = defocus_image(_render(_moved(xy, 0.4, (11.0, 6.0)), flux, 3.0, seed=3, sky=200.0), 12.0, "donut")
    reg = register_frame(ref_xy, img, _ref_wcs(), 12.0, nsigma=5.0)
    assert reg.ok and reg.rms_px < 0.6 and reg.shift_px == pytest.approx(np.hypot(11.0, 6.0), abs=1.5)


def test_register_failures_are_reported_not_raised():
    xy, flux = _stars()
    ref_xy = bright_sources(_render(xy, flux, 4.0), 4.0)
    empty = np.full((600, 800), 200.0) + np.random.default_rng(0).normal(0, 3, (600, 800))
    r = register_frame(ref_xy, empty, _ref_wcs(), 4.0)
    assert not r.ok and r.wcs is None and ("Sterne im Bild" in r.note or "keine Zuordnung" in r.note)
    r = register_frame(ref_xy[:2], empty, _ref_wcs(), 4.0)
    assert not r.ok and "Referenz hat nur" in r.note
    other = _render(np.random.default_rng(9).uniform(40, 560, (30, 2)), np.geomspace(2e3, 6e4, 30), 4.0, seed=4)       # ganz anderes Sternfeld
    r = register_frame(ref_xy, other, _ref_wcs(), 4.0)
    assert not r.ok and r.note


def test_scale_deviation_is_rejected():
    xy, flux = _stars()
    ref_xy = bright_sources(_render(xy, flux, 4.0), 4.0)
    c = np.array([400.0, 300.0])
    scaled = (xy - c) * 1.12 + c
    keep = (scaled[:, 0] > 30) & (scaled[:, 0] < 770) & (scaled[:, 1] > 30) & (scaled[:, 1] < 570)
    r = register_frame(ref_xy, _render(scaled[keep], flux[keep], 4.0, seed=6), _ref_wcs(), 4.0, max_scale_dev=0.05)
    assert not r.ok and "Massstab" in r.note


def test_fixed_pattern_defects_do_not_trap_the_registration_at_identity():
    """Hotpixel an gleicher Stelle in jedem Bild duerfen die Zuordnung nicht auf „keine Verschiebung“ ziehen (Fund an echten Bildern: identische Zuordnung mit 22 Treffern, Fluss 0 an den Aperturen)."""
    xy, flux = _stars()
    rng = np.random.default_rng(11)
    hot = np.c_[rng.uniform(30, 770, 40), rng.uniform(30, 570, 40)].astype(int)
    def with_defects(img):
        img = img.copy()
        img[hot[:, 1], hot[:, 0]] += 5e3                                      # einzelne sehr helle Pixel an festen Orten
        return img
    ref_img = with_defects(_render(xy, flux, 4.0, seed=1))
    ref_xy = bright_sources(ref_img, 4.0)
    shifted = _moved(xy, 0.0, (23.0, -14.0))
    keep = (shifted[:, 0] > 30) & (shifted[:, 0] < 770) & (shifted[:, 1] > 30) & (shifted[:, 1] < 570)
    img = with_defects(_render(shifted[keep], flux[keep], 4.0, seed=2))
    reg = register_frame(ref_xy, img, _ref_wcs(), 4.0)
    assert reg.ok and reg.shift_px == pytest.approx(np.hypot(23.0, 14.0), abs=1.0)            # die Sterne bewegten sich, die Defekte nicht
