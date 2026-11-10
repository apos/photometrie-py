"""Tests fuer varphot.wcscheck (synthetisches Feld, kein Netz)."""
import numpy as np
import pytest
from astropy.table import Table
from astropy.wcs import WCS

from varphot import check_wcs
from varphot import wcscheck as W

NX, NY, SCALE = 4000, 3000, 1.0          # px, px, "/px
RA0, DEC0 = 120.0, 20.0


def make_wcs(rot_deg=0.0, shift_arcsec=(0.0, 0.0)):
    w = WCS(naxis=2)
    w.wcs.crpix = [NX / 2, NY / 2]
    w.wcs.crval = [RA0 + shift_arcsec[0] / 3600 / np.cos(np.radians(DEC0)), DEC0 + shift_arcsec[1] / 3600]
    a = np.radians(rot_deg)
    s = SCALE / 3600
    w.wcs.cd = s * np.array([[-np.cos(a), np.sin(a)], [np.sin(a), np.cos(a)]])
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def make_gaia(n=600, seed=3, pm=0.0):
    rng = np.random.default_rng(seed)
    x, y = rng.uniform(100, NX - 100, n), rng.uniform(100, NY - 100, n)
    ra, dec = make_wcs().pixel_to_world_values(x, y)
    return Table({"source_id": np.arange(n), "ra": ra, "dec": dec, "pmra": rng.normal(0, pm, n), "pmdec": rng.normal(0, pm, n),
                  "G": rng.uniform(10, 14, n), "ruwe": np.ones(n)})


def detections(gaia, wcs_true, epoch=2024.3, noise_px=0.2, seed=5):
    """'Erkannte' Pixelpositionen: wahre Position zur Aufnahmeepoche + Zentroidrauschen."""
    rng = np.random.default_rng(seed)
    sky = W.epoch_positions(gaia, epoch)
    x, y = wcs_true.world_to_pixel(sky)
    return x + rng.normal(0, noise_px, len(x)), y + rng.normal(0, noise_px, len(y))


def test_perfect_wcs_is_ok():
    g = make_gaia()
    c = check_wcs(make_wcs(), detections(g, make_wcs()), g, 2024.3, (NY, NX))
    assert c.verdict == "OK" and c.n_match > 500
    assert c.offset_arcsec < 0.05 and c.rms_arcsec < 0.3 and c.recovery > 0.95


def test_shifted_wcs_is_flagged():
    g = make_gaia()
    bad = make_wcs(shift_arcsec=(1.5, 0.0))                 # 1,5" Versatz bei 1"/px
    c = check_wcs(bad, detections(g, make_wcs()), g, 2024.3, (NY, NX))
    assert c.verdict.startswith("Warnung") and "Versatz" in c.verdict
    assert c.median_dra_arcsec == pytest.approx(1.5, abs=0.15)        # erkannt - Gaia: Vorzeichen stimmt


def test_rotation_error_shows_in_worst_cell_and_trend():
    g = make_gaia()
    c = check_wcs(make_wcs(rot_deg=0.03), detections(g, make_wcs()), g, 2024.3, (NY, NX))   # ~ 1,9" am Rand
    assert c.verdict.startswith("Warnung") and c.trend_arcsec > 1.0 and c.worst_cell_arcsec > 1.0


def test_proper_motion_is_applied():
    g = make_gaia(pm=300.0)                                  # 300 mas/yr -> 2,5" in 8,3 Jahren
    det = detections(g, make_wcs(), epoch=2024.3)
    good = check_wcs(make_wcs(), det, g, 2024.3, (NY, NX))
    stale = check_wcs(make_wcs(), det, g, 2016.0, (NY, NX))   # Eigenbewegung ignoriert
    assert good.rms_arcsec < 0.3 and good.verdict == "OK"
    assert stale.rms_arcsec > 3 * good.rms_arcsec


def test_too_few_matches_gives_no_verdict():
    g = make_gaia(n=5)
    c = check_wcs(make_wcs(), detections(g, make_wcs()), g, 2024.3, (NY, NX))
    assert "Zu wenige" in c.verdict and np.isnan(c.rms_arcsec)


def test_gaia_field_fills_missing_proper_motion(monkeypatch, tmp_path):
    rows = [dict(source_id=1, ra=1.0, dec=2.0, pmra=None, pmdec=None, G=10.0, ruwe=1.0),
            dict(source_id=2, ra=1.1, dec=2.1, pmra=5.0, pmdec=-3.0, G=11.0, ruwe=1.1)]
    monkeypatch.setattr(W, "_tap_json", lambda *a, **k: rows)
    t = W.gaia_field(1.0, 2.0, 0.5, cache_dir=tmp_path, force=True)
    assert list(t["pmra"]) == [0.0, 5.0] and list(t["pmdec"]) == [0.0, -3.0]
