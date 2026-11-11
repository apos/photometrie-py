"""Tests fuer varphot.astrometry (ASTAP-Solve, Fallback, gnomonische Projektion)."""
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from varphot import gnomonic, solve_image
from varphot.astrometry import ASTAP_DEFAULT, read_wcs_sidecar

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


# ------------------------------------------------------------ Sternbildlinien clippen statt verwerfen
from varphot import great_circle_xy, polyline_in_window


def test_great_circle_is_straight_line_when_both_ends_in_front():
    x, y = great_circle_xy(10, 10, 14, 6, 12, 8, n=20)              # beide Enden um Zentrum (12, 8)
    assert np.all(np.isfinite(x)) and np.allclose(np.polyfit(x, y, 1)[0] * x + np.polyfit(x, y, 1)[1], y, atol=1e-6)
    assert (x[0], y[0]) == pytest.approx(gnomonic(10, 10, 12, 8), abs=1e-9)


def test_great_circle_keeps_front_part_when_one_end_is_behind():
    # Ende 1 im Fenster um (0, 0), Ende 2 auf der Gegenseite (RA 180): vorderer Teil bleibt, hinterer NaN
    x, y = great_circle_xy(5, 0, 180, 0, 0, 0, n=60)
    assert np.isfinite(x[0]) and np.isnan(x[-1])
    ok = np.isfinite(x)
    assert ok.sum() > 10 and np.all(np.diff(np.flatnonzero(ok)) == 1)  # zusammenhaengender Anfangsteil
    assert polyline_in_window(x, y, 13.5)                              # beginnt im Fenster


def test_polyline_crossing_window_without_sample_inside():
    # Strecke quer durchs Fenster, beide Stuetzpunkte weit draussen
    assert polyline_in_window([-30, 30], [0, 0], 13.5)
    assert not polyline_in_window([-30, 30], [20, 20], 13.5)           # laeuft oberhalb vorbei
    assert not polyline_in_window([np.nan, np.nan], [0, 0], 13.5)


def test_orion_lines_never_enter_m16_window():
    """Regression v0.2.0/P0-1: Orion (RA ~85) liegt auf der Gegenseite von M16 (RA 275)."""
    import json
    d = json.loads((ROOT / "data" / "constellation_lines.json").read_text())["Ori"]
    hit = False
    for s1, s2 in json.loads((ROOT / "data" / "const_topology.json").read_text())["Ori"]["lines"]:
        a, b = d["stars"][s1], d["stars"][s2]
        x, y = great_circle_xy(a["ra"], a["dec"], b["ra"], b["dec"], 274.75, -13.87)
        hit |= polyline_in_window(x, y, 13.5)
    assert not hit


def test_long_line_through_window_is_kept_for_ophiuchus_like_case():
    # Linie von (-20, -5) nach (+20, +5) um Zentrum (0, 0) schneidet das Fenster, beide Sterne liegen draussen
    x, y = great_circle_xy(340, -5, 20, 5, 0, 0, n=40)
    assert polyline_in_window(x, y, 13.5)


def test_clipping_finds_at_least_all_lines_of_the_old_endpoint_rule_and_more():
    """Neue Regel (Linie berührt Fenster) ist eine Obermenge der alten (beide Endpunkte vorn und <= 1,6*HALF)."""
    import json
    from varphot import gnomonic
    d = json.loads((ROOT / "data" / "constellation_lines.json").read_text())
    half, extra = 13.5, 0
    for ra0, dec0 in [(274.75, -13.87), (337.29, 58.42), (37.95, 89.26), (83.8, 0.0)]:
        for e in d.values():
            for s1, s2 in e["lines"]:
                if s1 not in e["stars"] or s2 not in e["stars"]:
                    continue
                a, b = e["stars"][s1], e["stars"][s2]
                x1, y1 = gnomonic(a["ra"], a["dec"], ra0, dec0)
                x2, y2 = gnomonic(b["ra"], b["dec"], ra0, dec0)
                old = (np.all(np.isfinite([x1, y1, x2, y2])) and max(abs(x1), abs(x2), abs(y1), abs(y2)) <= half * 1.6
                       and polyline_in_window([x1, x2], [y1, y2], half))
                gx, gy = great_circle_xy(a["ra"], a["dec"], b["ra"], b["dec"], ra0, dec0, n=48)
                new = polyline_in_window(gx, gy, half)
                assert new or not old                      # nie weniger als vorher
                extra += int(new and not old)
    assert extra >= 5                                      # gemessen 2026-11-10: 8 zusätzliche Linien


def _wcs_header() -> fits.Header:
    h = fits.Header()
    h["SIMPLE"] = True
    h["BITPIX"] = -32
    h["NAXIS"] = 2
    h["NAXIS1"] = 9252
    h["NAXIS2"] = 6946
    h["CTYPE1"] = "RA---TAN"
    h["CTYPE2"] = "DEC--TAN"
    h["CRVAL1"] = 274.7535148268
    h["CRVAL2"] = -13.87065703067
    h["PLTSOLVD"] = True
    return h


@pytest.mark.parametrize("linux_format", [False, True], ids=["mac-80-Zeichen-Karten", "linux-Textzeilen"])
def test_read_wcs_sidecar_both_formats(tmp_path, linux_format):
    """Regression: das Linux-ASTAP schreibt die .wcs mit Zeilenenden ohne Auffuellung (TypeError beim Lesen)."""
    h = _wcs_header()
    if linux_format:
        text = "\n".join(c.image.rstrip() for c in h.cards) + "\nEND\n"
    else:
        text = "".join(c.image for c in h.cards) + "END".ljust(80)
    f = tmp_path / "bild.wcs"
    f.write_bytes(text.encode("ascii"))
    got = read_wcs_sidecar(f)
    assert got["NAXIS"] == 2 and isinstance(got["NAXIS"], int)
    assert got["NAXIS1"] == 9252
    assert got["CTYPE1"] == "RA---TAN"
    assert got["CRVAL1"] == pytest.approx(274.7535148268)
    assert got["PLTSOLVD"] is True
