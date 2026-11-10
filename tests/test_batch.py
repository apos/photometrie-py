"""Tests fuer Zeit, Feldgeometrie, Ensemble-Photometrie und Bildqualitaet (synthetische Daten, kein Netz)."""
import numpy as np
import pandas as pd
import pytest
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

from varphot import (bjd_tdb, diff_mag, ensemble_mag, field_from_wcs, light_curve, measure_frame, mid_exposure, qc_frames,
                     read_frame, run_batch, scintillation_mag, site_from_header)
from varphot.observer import Site

RNG = np.random.default_rng(7)


def make_wcs(nx=300, ny=200, scale=0.58, rot90=False):
    w = WCS(naxis=2)
    w.wcs.crpix = [nx / 2, ny / 2]
    w.wcs.crval = [337.29, 58.41]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    s = scale / 3600
    w.wcs.cd = [[0, -s], [s, 0]] if rot90 else [[-s, 0], [0, s]]
    return w


# ------------------------------------------------------------------ Zeit
def test_mid_exposure_adds_half_exptime():
    t = mid_exposure({"DATE-OBS": "2020-01-10T01:08:27.000", "EXPTIME": 10.0})
    assert t.isot == "2020-01-10T01:08:32.000"


def test_site_from_header_requires_site_key():
    assert site_from_header({"LATITUDE": 31.7, "LONGITUD": 110.9}) is None       # Vorzeichen nie raten
    s = site_from_header({"SITE": "X", "LATITUDE": 30.68, "LONGITUD": -104.0, "HEIGHT": 2030})
    assert s.lon_deg == -104.0 and s.height_m == 2030


def test_bjd_correction_is_within_light_travel_bounds():
    site = Site("T", 30.7, -104.0, 2000)
    t = Time("2020-01-10T01:00:00", scale="utc")
    d = (bjd_tdb(t, 337.29, 58.41, site)[0] - t.jd) * 86400
    assert abs(d) < 505                       # max. ~500 s (1 AE)
    assert d != 0
    # Ziel im Ekliptikpol-Bereich: halbe Jahresschwingung -> Vorzeichen wechselt in 6 Monaten nicht zwingend, Betrag klein
    t2 = Time("2020-07-10T01:00:00", scale="utc")
    assert abs((bjd_tdb(t2, 337.29, 58.41, site)[0] - t2.jd) * 86400) < 505


def test_scintillation_young_formula():
    m = scintillation_mag(0.4, 1.0, 0.0, 1.0)                 # 0,4 m, 1 s, Zenit, Meeresniveau
    assert 0.005 < m < 0.02
    assert scintillation_mag(0.4, 2.0, 0.0, 1.0) > m          # mehr Luftmasse -> mehr
    assert scintillation_mag(0.4, 1.0, 0.0, 10.0) < m         # laengere Belichtung -> weniger
    # Osborn et al. 2015, Gl. 2: sigma = sqrt(1e-5) D^(-2/3) t^(-1/2) X^1,5 exp(-h/8000) -> in mag mal 1,0857 (c_y = 1)
    assert scintillation_mag(0.4, 1.0, 0.0, 1.0, c_y=1.0) == pytest.approx(1.0857 * 3.1623e-3 * 0.4 ** (-2 / 3), rel=1e-3)
    assert scintillation_mag(0.4, 1.0, 0.0, 1.0) == pytest.approx(1.5 * scintillation_mag(0.4, 1.0, 0.0, 1.0, c_y=1.0))


# ------------------------------------------------------------------ Feldgeometrie
def test_field_from_wcs_edges_and_angle():
    w = make_wcs(300, 200)
    f = field_from_wcs(w, (200, 300))
    assert f["field_deg"][0] == pytest.approx(300 * 0.58 / 3600, rel=1e-3)
    assert f["field_deg"][1] == pytest.approx(200 * 0.58 / 3600, rel=1e-3)
    assert f["pa_deg"] == pytest.approx(0, abs=0.5) or f["pa_deg"] == pytest.approx(180, abs=0.5)   # lange Seite West-Ost
    fr = field_from_wcs(make_wcs(300, 200, rot90=True), (200, 300))
    assert fr["pa_deg"] == pytest.approx(90, abs=0.5)                                                # lange Seite Nord-Sued
    assert fr["ra0"] == pytest.approx(337.29, abs=0.01)


# ------------------------------------------------------------------ Differenzphotometrie
def test_diff_mag_recovers_known_magnitude():
    v_c = np.array([9.0, 10.0, 11.0])
    zp = 21.0
    f_c = 10 ** (-0.4 * (v_c - zp))
    f_t = 10 ** (-0.4 * (4.0 - zp))
    m, _, sd = diff_mag(f_t, f_c, v_c)
    assert m == pytest.approx(4.0, abs=1e-9) and sd == pytest.approx(0, abs=1e-9)


def test_ensemble_mag_clips_outlier_and_reports_scatter():
    v_c = np.array([9.0, 9.5, 10.0, 10.5, 11.0])
    f_c = 10 ** (-0.4 * (v_c - 21.0))
    f_c[2] *= 1.8                                              # ein Comp "kaputt" (z. B. Cosmic)
    f_t = 10 ** (-0.4 * (4.0 - 21.0))
    m, err, n, sd = ensemble_mag(f_t, f_c, v_c)
    assert m == pytest.approx(4.0, abs=1e-6) and n == 4        # Ausreisser verworfen
    m3, _, n3, _ = ensemble_mag(f_t, f_c[:3], v_c[:3])         # unter 4 Comps kein Clipping
    assert n3 == 3


def test_ensemble_mag_error_has_photon_term():
    v_c = np.array([9.0, 10.0, 11.0, 12.0])
    f_c = 10 ** (-0.4 * (v_c - 21.0))
    f_t = 1e5
    _, e0, _, _ = ensemble_mag(f_t, f_c, v_c)
    _, e1, _, _ = ensemble_mag(f_t, f_c, v_c, f_t_err=1e4)
    assert e1 > e0 and e1 == pytest.approx(1.0857 * 0.1, rel=0.05)


# ------------------------------------------------------------------ Stapel + Qualitaet
def synth_frame(path, w, stars, t0, flux_scale=1.0, fwhm="2.0", nx=300, ny=200, noise=2.0):
    yy, xx = np.mgrid[0:ny, 0:nx]
    img = 20 + RNG.normal(0, noise, (ny, nx))
    for ra, dec, f in stars:
        x, y = w.world_to_pixel_values(ra, dec)
        img += flux_scale * f / (2 * np.pi * 1.6 ** 2) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.6 ** 2))
    h = w.to_header()
    h["DATE-OBS"], h["EXPTIME"], h["GAIN"], h["RDNOISE"], h["SATURATE"] = t0, 10.0, 1.0, 5.0, 60000.0
    h["AIRMASS"], h["L1FWHM"], h["TELESCOP"], h["FILTER"] = 1.2, float(fwhm), "T", "V"
    fits.PrimaryHDU(img.astype(np.float32), h).writeto(path, overwrite=True)


@pytest.fixture
def run(tmp_path):
    w = make_wcs()
    pos = [(337.29, 58.41), (337.30, 58.42), (337.28, 58.40), (337.31, 58.40), (337.27, 58.42)]
    stars = pd.DataFrame({"id": ["target", "c1", "c2", "c3", "k"], "role": ["target", "comp", "comp", "comp", "check"],
                          "ra": [p[0] for p in pos], "dec": [p[1] for p in pos], "V": [4.0, 9.0, 9.5, 10.0, 10.5]})
    zp = 18.0
    fl = [10 ** (-0.4 * (v - zp)) for v in stars["V"]]
    paths = []
    for i in range(6):
        scale = {3: 0.15, 4: 1.0}.get(i, 1.0)                    # Bild 3 = dicke Wolke
        fw = "6.5" if i == 4 else "2.0"                          # Bild 4 = schlechtes Seeing
        p = tmp_path / f"f{i}.fits"
        synth_frame(p, w, [(a, d, f) for (a, d), f in zip(pos, fl)], f"2020-01-10T01:0{i}:00", scale, fw)
        paths.append(p)
    cfg = {"ap_r": 6, "ap_r_in": 9, "ap_r_out": 14, "sat_adu": 60000, "snr_min": 10, "transp_min": 0.6, "fwhm_max_arcsec": 4.0}
    tab = run_batch(paths, stars, cfg, workers=1)
    return stars, cfg, qc_frames(tab, dict(zip(stars["id"], stars["role"])), cfg)


def test_batch_flux_matches_input(run):
    stars, cfg, tab = run
    t = tab[(tab["file"] == "f0.fits") & (tab["star_id"] == "c1")].iloc[0]
    assert t["flux"] == pytest.approx(10 ** (-0.4 * (9.0 - 18.0)), rel=0.05)
    assert t["flux_err"] > 0 and t["sky"] == pytest.approx(20, abs=2)


def test_qc_flags_cloud_and_seeing(run):
    _, _, tab = run
    fl = tab.drop_duplicates("file").set_index("file")["frame_flags"]
    assert fl["f0.fits"] == "" and fl["f1.fits"] == "" and fl["f2.fits"] == ""
    assert "LOW_TRANSPARENCY" in fl["f3.fits"] or "NO_SIGNAL" in fl["f3.fits"]
    assert "BAD_SEEING" in fl["f4.fits"]


def test_light_curve_uses_only_good_frames_and_recovers_target(run):
    stars, _, tab = run
    lc = light_curve(tab, stars, "target", site=Site("T", 30.7, -104.0, 2000), aperture_m=0.4)
    assert set(lc["file"]) == {"f0.fits", "f1.fits", "f2.fits", "f5.fits"}
    assert lc["mag"].median() == pytest.approx(4.0, abs=0.05)
    assert lc["bjd_tdb"].notna().all() and (lc["bjd_tdb"].diff().dropna() > 0).all()
    assert "scint_mag" in lc and "check_minus_cat" in lc
    assert abs(lc["check_minus_cat"].median()) < 0.1


def test_read_frame_picks_sci_extension(tmp_path):
    w = make_wcs()
    p = tmp_path / "x.fits"
    fits.HDUList([fits.PrimaryHDU(header=fits.Header({"TELESCOP": "A"})),
                  fits.ImageHDU(np.ones((20, 30), np.float32), w.to_header(), name="SCI")]).writeto(p)
    img, hdr, wc = read_frame(p)
    assert img.shape == (20, 30) and wc is not None and hdr["TELESCOP"] == "A"


def test_weighted_ensemble_prefers_precise_comps():
    v_c = np.array([9.0, 10.0, 11.0, 12.0])
    f_c = 10 ** (-0.4 * (v_c - 21.0))
    f_c_bad = f_c.copy(); f_c_bad[3] *= 1.15                       # der schwache Comp ist verrauscht
    err = np.array([0.001, 0.002, 0.005, 0.15]) * f_c
    m_w, _, _, _ = ensemble_mag(1e5, f_c_bad, v_c, f_c_err=err, clip=99)
    m_u, _, _, _ = ensemble_mag(1e5, f_c_bad, v_c, clip=99)
    m_t, _, _, _ = ensemble_mag(1e5, f_c, v_c)
    assert abs(m_w - m_t) < 0.01                                    # gewichtet: schwacher Comp zaehlt kaum
    assert abs(m_u - m_t) < 0.1


def _sat_frame(w, fwhm, flux, sat=60000.0, nx=300, ny=200):
    yy, xx = np.mgrid[0:ny, 0:nx]
    s = fwhm / 2.355
    img = 20 + RNG.normal(0, 1.0, (ny, nx))
    for ra, dec, f in flux:
        x, y = w.world_to_pixel_values(ra, dec)
        img += f / (2 * np.pi * s ** 2) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s ** 2))
    return np.minimum(img, sat)


def test_core_correction_removes_seeing_dependence():
    """Ziel gesaettigt: Gesamtfluss haengt vom Seeing ab, der Ring ausserhalb des Kerns (hochgerechnet) nicht."""
    w = make_wcs()
    pos = [(337.29, 58.41), (337.30, 58.42), (337.28, 58.40), (337.31, 58.40)]
    stars = pd.DataFrame({"id": ["target", "c1", "c2", "c3"], "role": ["target", "comp", "comp", "comp"],
                          "ra": [p[0] for p in pos], "dec": [p[1] for p in pos], "V": [4.0, 9.0, 9.5, 10.0]})
    fl = [4e6, 1.5e4, 1e4, 6e3]
    cfg = {"ap_r": 10, "ap_r_in": 16, "ap_r_out": 24, "sat_adu": 60000, "core_r": 3.0, "snr_min": 5}
    mags = {}
    for fwhm in (2.5, 4.0):
        img = _sat_frame(w, fwhm, [(a, d, f) for (a, d), f in zip(pos, fl)])
        rows = measure_frame(img, w, stars, {"GAIN": 1.0, "RDNOISE": 3.0, "SATURATE": 60000.0}, cfg)
        r = {x["star_id"]: x for x in rows}
        assert r["target"]["n_sat"] > 0 and r["c1"]["n_sat"] == 0
        frac = np.median([r[c]["flux_ring"] / r[c]["flux"] for c in ("c1", "c2")])
        mags[fwhm] = (r["target"]["flux"], r["target"]["flux_ring"] / frac)
    raw = abs(mags[2.5][0] / mags[4.0][0] - 1)
    cor = abs(mags[2.5][1] / mags[4.0][1] - 1)
    assert raw > 0.02                                  # ohne Korrektur: Seeing-abhaengiger Verlust
    assert cor < raw / 3                               # mit Kernmaske klar kleiner
