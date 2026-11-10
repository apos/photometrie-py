"""Stapelverarbeitung mit echten (kleinen) FITS-Dateien, Datensatz-Download-Ablauf (gemockt), WCS-Plot."""
import numpy as np
import pandas as pd
import pytest
from astropy.io import fits

from varphot import testdata as td
from varphot.batch import read_frame, run_batch


def _write(path, wcs=True, exptime=10.0, date="2020-01-10T01:00:00", extra=None):
    yy, xx = np.mgrid[0:120, 0:160]
    img = 300 + 5000 * np.exp(-((xx - 60) ** 2 + (yy - 60) ** 2) / (2 * 2.0 ** 2)) + 3000 * np.exp(-((xx - 110) ** 2 + (yy - 50) ** 2) / (2 * 2.0 ** 2))
    hdr = fits.Header()
    hdr.update({"DATE-OBS": date, "EXPTIME": exptime, "GAIN": 2.0, "RDNOISE": 5.0, "SATURATE": 60000.0, "AIRMASS": 1.2, "L1FWHM": 2.5, "FILTER": "V", "TELESCOP": "T"})
    if wcs:
        hdr.update({"CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "CRVAL1": 100.0, "CRVAL2": 20.0, "CRPIX1": 80, "CRPIX2": 60, "CDELT1": -0.0004, "CDELT2": 0.0004})
    hdr.update(extra or {})
    fits.PrimaryHDU(img.astype(np.float32), hdr).writeto(path)
    return path


def _stars():
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.crval, w.wcs.cdelt, w.wcs.ctype = [80, 60], [100.0, 20.0], [-0.0004, 0.0004], ["RA---TAN", "DEC--TAN"]
    ra, dec = w.pixel_to_world_values([60, 110], [60, 50])
    return pd.DataFrame({"id": ["target", "c1"], "ra": ra, "dec": dec})


def test_run_batch_measures_all_frames_and_flags_missing_wcs(tmp_path):
    files = [_write(tmp_path / "a.fits"), _write(tmp_path / "b.fits", date="2020-01-10T01:05:00"), _write(tmp_path / "c.fits", wcs=False)]
    cfg = {"ap_r": 6, "ap_r_in": 9, "ap_r_out": 13, "sat_adu": 60000}
    seen = []
    df = run_batch(files, _stars(), cfg=cfg, workers=1, progress=lambda it, total: (seen.append(total), it)[1])
    assert seen == [3] and len(df) == 6
    ok = df[df["file"] == "a.fits"].set_index("star_id")
    assert ok.loc["target", "flux"] > ok.loc["c1", "flux"] > 0 and ok.loc["target", "star_flag"] == "" and ok["airmass"].iloc[0] == pytest.approx(1.2)
    assert (df[df["file"] == "c.fits"]["star_flag"] == "NO_WCS").all()
    b = df[df["file"] == "b.fits"]
    assert b["jd_mid"].iloc[0] - ok["jd_mid"].iloc[0] == pytest.approx(5 / 1440, abs=1e-6)         # 5 min spaeter


def test_read_frame_picks_2d_hdu_and_merges_primary_header(tmp_path):
    p = tmp_path / "m.fits"
    prim = fits.PrimaryHDU(header=fits.Header({"OBJECT": "X"}))
    sci = fits.ImageHDU(np.ones((5, 6), np.float32), name="SCI")
    fits.HDUList([prim, sci]).writeto(p)
    img, hdr, w = read_frame(p)
    assert img.shape == (5, 6) and hdr["OBJECT"] == "X" and w is None
    fits.PrimaryHDU(header=fits.Header()).writeto(tmp_path / "leer.fits")
    with pytest.raises(ValueError, match="keine 2D-Bilddaten"):
        read_frame(tmp_path / "leer.fits")


def test_qc_frames_flags_cloud_and_seeing():
    from varphot.batch import qc_frames
    rows = []
    for f, scale, fwhm in (("1", 1.0, 2.0), ("2", 1.0, 2.0), ("3", 1.0, 2.0), ("4", 0.3, 2.0), ("5", 1.0, 9.0)):      # 4: duenne Wolken, 5: schlechtes Seeing
        for sid, fl in (("t", 5e4), ("c1", 4e4), ("c2", 3e4), ("c3", 2e4)):
            rows.append(dict(file=f, star_id=sid, flux=fl * scale, flux_err=fl * scale * 0.01, star_flag="", fwhm_arcsec=fwhm, jd_mid=int(f)))
    out = qc_frames(pd.DataFrame(rows), {"t": "target", "c1": "comp", "c2": "comp", "c3": "comp"}, cfg={"snr_min": 10, "transp_min": 0.6, "fwhm_max_arcsec": 4.0})
    flags = out.drop_duplicates("file").set_index("file")["frame_flags"]
    assert flags["1"] == "" and flags["4"] == "LOW_TRANSPARENCY" and flags["5"] == "BAD_SEEING"


# ------------------------------------------------------------------------------------------------ Datensatz-Download
def test_download_dataset_flow_with_mocks(tmp_path, monkeypatch):
    monkeypatch.setattr(td, "lco_frames", lambda: [{"filename": "f1.fz", "url": "u1", "version_set": [{"md5": "m1"}]}, {"filename": "f2.fz", "url": "u2", "version_set": [{"md5": "m2"}]}])
    monkeypatch.setattr(td, "hatp32_files", lambda: [{"name": "h1.fits", "download_url": "hu", "size": 3}])
    got = []
    monkeypatch.setattr(td, "download_file", lambda url, dest, md5=None, size=None: (got.append((url, dest.name, md5, size)), "geladen")[1])
    msgs = []
    d = td.download_dataset("lco-dcep", dest=tmp_path / "lco", progress=msgs.append)
    assert d == tmp_path / "lco" and got == [("u1", "f1.fz", "m1", None), ("u2", "f2.fz", "m2", None)] and "2 Dateien" in msgs[0]
    got.clear()
    td.download_dataset("hatp32", dest=tmp_path / "h", progress=msgs.append)
    assert got == [("hu", "h1.fits", None, 3)]
    got.clear()
    dry = td.download_dataset("hatp32", dest=tmp_path / "trocken", dry_run=True, progress=msgs.append)
    assert got == [] and not dry.exists()


def test_get_json_retries_then_raises(monkeypatch):
    import requests
    n = []

    class R:
        def raise_for_status(self): raise requests.HTTPError("x")
    monkeypatch.setattr(td.requests, "get", lambda *a, **k: (n.append(1), R())[1])
    monkeypatch.setattr(td.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError):
        td._get_json("http://x", tries=3)
    assert len(n) == 3
    ok = type("O", (), {"raise_for_status": lambda self: None, "json": lambda self: {"a": 1}})()
    monkeypatch.setattr(td.requests, "get", lambda *a, **k: ok)
    assert td._get_json("http://x") == {"a": 1}


def test_hatp32_files_filters_directories(monkeypatch):
    monkeypatch.setattr(td, "_get_json", lambda url, params=None, tries=3: [{"type": "file", "name": "a"}, {"type": "dir", "name": "b"}])
    assert [f["name"] for f in td.hatp32_files()] == ["a"]


# ------------------------------------------------------------------------------------------------ WCS-Plot
def test_plot_wcs_check_smoke(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    from types import SimpleNamespace
    from varphot.plot import plot_wcs_check
    rng = np.random.default_rng(1)
    n = 300
    chk = SimpleNamespace(x=rng.uniform(0, 4000, n), y=rng.uniform(0, 3000, n), dra=rng.normal(0, 0.2, n), ddec=rng.normal(0, 0.2, n), G=rng.uniform(10, 14, n),
                          pixel_scale_arcsec=1.0, median_dra_arcsec=0.01, median_ddec_arcsec=-0.02, rms_arcsec=0.2, n_match=n, offset_arcsec=0.02, worst_cell_arcsec=0.1, verdict="OK")
    plot_wcs_check(chk, (3000, 4000), outfile=str(tmp_path / "w.png"))
    assert (tmp_path / "w.png").stat().st_size > 5000


# ------------------------------------------------------------------------------------------------ WCS je Bild per Registrierung
def test_run_batch_registers_frames_without_wcs(tmp_path):
    from astropy.wcs import WCS

    from varphot.registration import bright_sources
    w = WCS(naxis=2)
    w.wcs.crpix, w.wcs.crval, w.wcs.cdelt, w.wcs.ctype = [200, 150], [100.0, 20.0], [-0.0004, 0.0004], ["RA---TAN", "DEC--TAN"]
    rng = np.random.default_rng(4)
    pts = np.c_[rng.uniform(60, 340, 30), rng.uniform(50, 250, 30)]
    flux = np.geomspace(2e3, 4e4, 30)[::-1]
    yy, xx = np.mgrid[:300, :400]

    def render(p, seed):
        img = 300 + np.random.default_rng(seed).normal(0, 3, (300, 400))
        for (x, y), f in zip(p, flux):
            img += f / (2 * np.pi * 1.7 ** 2) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.7 ** 2))
        return img.astype(np.float32)
    ref_img = render(pts, 1)
    ref = dict(xy=bright_sources(ref_img, 4.0), wcs=w, fwhm=4.0)
    shifted = pts + [9.0, -6.0]                                                          # Nachfuehrfehler: das Feld ist um (9, -6) px verschoben
    for name, p in (("a.fits", shifted), ("b.fits", pts + [3.0, 2.0])):
        h = fits.Header({"DATE-OBS": "2020-01-10T01:00:00", "EXPTIME": 10.0, "GAIN": 2.0, "RDNOISE": 5.0, "SATURATE": 60000.0})      # ohne WCS
        fits.PrimaryHDU(render(p, 5), h).writeto(tmp_path / name)
    ra, dec = w.pixel_to_world_values(pts[[0, 4]][:, 0], pts[[0, 4]][:, 1])                # Ziel = Stern 0, Comp = Stern 4 (wahre Himmelspositionen)
    stars = pd.DataFrame({"id": ["target", "c1"], "ra": ra, "dec": dec})
    cfg = {"ap_r": 6, "ap_r_in": 9, "ap_r_out": 13, "sat_adu": 60000}
    df = run_batch([tmp_path / "a.fits", tmp_path / "b.fits"], stars, cfg=cfg, workers=1, reference=ref)
    assert set(df["wcs_source"]) == {"registered"} and (df["star_flag"] == "").all() and df["reg_rms_px"].max() < 0.7
    f = df[df["file"] == "a.fits"].set_index("star_id")["flux"]
    assert f["target"] == pytest.approx(flux[0], rel=0.05) and f["c1"] == pytest.approx(flux[4], rel=0.05)      # die Aperturen sitzen auf den verschobenen Sternen
    none = run_batch([tmp_path / "a.fits"], stars, cfg=cfg, workers=1)                  # ohne Referenz: wie bisher NO_WCS
    assert (none["star_flag"] == "NO_WCS").all() and (none["wcs_source"] == "none").all()
    with pytest.raises(ValueError, match="Referenz"):
        run_batch([tmp_path / "a.fits"], stars, cfg=cfg, wcs_mode="register")
    with pytest.raises(ValueError, match="wcs_mode"):
        run_batch([tmp_path / "a.fits"], stars, cfg=cfg, wcs_mode="egal")
