"""AAVSO Extended Format: Beispiele der AAVSO-Formatseite (v1.2) und typische Fehler."""
import numpy as np
import pandas as pd
import pytest

from varphot.aavso import (Observation, build_extended, format_row, notes_string, observations_from_lightcurve, validate_extended)

EX1 = """#TYPE=EXTENDED
#OBSCODE=TST01
#SOFTWARE=IRAF 12.4
#DELIM=,
#DATE=JD
#OBSTYPE=CCD
#NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,GROUP,CHART,NOTES
SS CYG,2450702.1234,11.135,0.003,V,NO,STD,105,na,na,na,na,na,X16382L,This is a test
"""
EX3 = """#TYPE=EXTENDED
#OBSCODE=TST01
#SOFTWARE=GCX 2.0
#DELIM=,
#DATE=JD
#OBSTYPE=CCD
#NAME,DATE,MAG,MERR,FILT,TRANS,MTYPE,CNAME,CMAG,KNAME,KMAG,AMASS,GROUP,CHART,NOTES
SS CYG,2450702.1234,11.235,0.003,B,NO,STD,ENSEMBLE,na,105,10.593,1.561,1,X16382L,na
SS CYG,2450702.1254,11.135,0.003,V,NO,STD,ENSEMBLE,na,105,10.492,1.563,1,X16382L,na
"""


def test_official_examples_are_valid():
    assert validate_extended(EX1) == [] and validate_extended(EX3) == []


def test_build_roundtrip_is_valid_and_formats_numbers():
    obs = [Observation("del cep", 2458858.547546, 3.8421, 0.0123, "TG", False, kname="g1", kmag=11.3, airmass=1.3254, group=1, chart="Gaia DR3 V-deriv",
                       notes=notes_string("OSC CMOS camera, green channel", NOBS=3, Tv_bv=None))]
    txt = build_extended(obs, "ABCD", "varphot 0.3.0", "DSLR", comments=["Testdatei"])
    row = [l for l in txt.splitlines() if not l.startswith("#")][0].split(",")
    assert row[:6] == ["DEL CEP", "2458858.54755", "3.842", "0.012", "TG", "NO"] and row[7:9] == ["ENSEMBLE", "na"] and row[11] == "1.325"
    assert row[14] == "OSC CMOS camera; green channel|NOBS=3"
    assert "#DELIM=comma" in txt and validate_extended(txt) == []


@pytest.mark.parametrize("bad,expect", [
    (EX1.replace("#OBSTYPE=CCD\n", ""), "OBSTYPE fehlt"),
    (EX1.replace(",V,NO,", ",X,NO,"), "Filtercode"),
    (EX1.replace("#DELIM=,", "#DELIM=|"), "nicht erlaubt"),
    (EX1.replace("11.135", "11"), "Punkt"),
    (EX3.replace("ENSEMBLE,na", "ENSEMBLE,10.5"), "ENSEMBLE"),
    (EX1 + "\n", "Leerzeile"),
    (EX1.replace("SS CYG,", " SS CYG,"), "Leerzeichen"),
    (EX1.replace(",X16382L,This is a test", ",X16382L"), "Felder"),
    (EX1.replace("2450702.1234", "12/31/2007"), "Julianisches Datum"),
    (EX1.replace(",NO,STD,105,", ",MAYBE,STD,105,"), "TRANS"),
    (EX1.replace(",STD,105,", ",DIF,na,"), "DIF braucht CNAME"),
    (EX1.replace(",0.003,", ",0.00300001,"), "MERR"),
    (EX1.replace("11.135", "11.13500000"), "MAG"),
])
def test_invalid_files_are_caught(bad, expect):
    assert any(expect in i for i in validate_extended(bad)), validate_extended(bad)


def test_lightcurve_to_observations_skips_nan_and_uses_check_mag():
    lc = pd.DataFrame(dict(jd_mid=[2458800.1, 2458800.2, 2458800.3], mag=[3.9, np.nan, 4.0], mag_err=[0.02, 0.02, 0.02], airmass=[1.2, 1.2, 1.3], check=[11.3, 11.3, 11.4]))
    obs = observations_from_lightcurve(lc, "del Cep", "V", True, kname="g1", kmag_col="check", chart="X43370RHC")
    assert len(obs) == 2 and obs[0].kmag == 11.3 and obs[0].trans is True
    txt = build_extended(obs, "ABCD", "varphot", "DSLR")
    assert validate_extended(txt) == [] and txt.count(",YES,") == 2


def test_format_row_replaces_delimiter_in_text():
    r = format_row(Observation("X", 2450000.5, 9.0, notes="a,b"), ",")
    assert r.endswith("a;b") and len(r.split(",")) == 15


# ---------------------------------------------------------------- Plausibilitaet (Inhalt)
from varphot.aavso import check_plausibility
from varphot.maturity import maturity_warnings

NOW = 2461000.0


def _obs(n=20, mag0=3.8, **kw):
    base = dict(star="DEL CEP", filt="V", trans=False, chart="X43370RNS", kname="C1", airmass=1.3)
    base.update(kw)
    e = base.pop("err", 0.01)
    return [Observation(jd=2460900.0 + i * 0.005, mag=mag0 + 0.01 * (i % 3), kmag=7.5 + 0.005 * (i % 2), err=None if e is None else e + 0.0005 * (i % 4), **base) for i in range(n)]


def _codes(f, level=None):
    return {x.code for x in f if level is None or x.level == level}


def test_plausible_file_has_no_findings():
    assert check_plausibility(_obs(), obstype="CCD", expected_range=(3.3, 4.5), now_jd=NOW) == []


def test_future_time_and_duplicates_and_old_time_are_errors():
    f = check_plausibility(_obs(), now_jd=2460900.0)
    assert "zeit_zukunft" in _codes(f, "ERROR")
    o = _obs()
    o.append(o[0])
    assert "doppelt" in _codes(check_plausibility(o, now_jd=NOW), "ERROR")
    assert "zeit_alt" in _codes(check_plausibility([Observation("X", 2400000.5 + 100 * i, 5.0, 0.01, chart="X43370RNS") for i in range(6)], now_jd=NOW), "ERROR")


def test_wrong_star_range_is_error_but_few_outliers_only_warn():
    assert "mag_bereich" in _codes(check_plausibility(_obs(mag0=9.0), expected_range=(3.3, 4.5), now_jd=NOW), "ERROR")
    o = _obs()
    o[0].mag = 6.0
    f = check_plausibility(o, expected_range=(3.3, 4.5), now_jd=NOW)
    assert "mag_bereich" in _codes(f, "WARN") and "mag_bereich" not in _codes(f, "ERROR")


def test_errors_missing_negative_constant():
    assert "fehler_fehlt" in _codes(check_plausibility(_obs(err=None), now_jd=NOW), "ERROR")
    assert "fehler_negativ" in _codes(check_plausibility(_obs(err=-0.01), now_jd=NOW), "ERROR")
    c = _obs(); [setattr(x, "err", 0.01) for x in c]
    assert "fehler_konstant" in _codes(check_plausibility(c, now_jd=NOW), "WARN")


def test_filter_trans_obstype_rules():
    assert "filter_trans" in _codes(check_plausibility(_obs(filt="TG", trans=True), obstype="DSLR", now_jd=NOW), "ERROR")
    assert "filter_trans" in _codes(check_plausibility(_obs(filt="V", trans=False), obstype="DSLR", now_jd=NOW), "ERROR")
    assert "obstype" in _codes(check_plausibility(_obs(filt="TG"), obstype="CCD", now_jd=NOW), "WARN")
    assert "koeffizienten" in _codes(check_plausibility(_obs(filt="V", trans=True, notes="na"), obstype="CCD", now_jd=NOW), "WARN")


def test_chart_rules():
    assert "chart_fehlt" in _codes(check_plausibility(_obs(chart=None), now_jd=NOW), "WARN")
    assert "chart_gaia" in _codes(check_plausibility(_obs(chart="Gaia DR3 V-deriv"), now_jd=NOW), "WARN")
    assert "chart_form" in _codes(check_plausibility(_obs(chart="abc"), now_jd=NOW), "WARN")


def test_check_star_scatter_offset_and_jumps():
    o = _obs()
    for i, x in enumerate(o):
        x.kmag = 7.5 + (0.2 if i % 2 else -0.2)
    assert "check_streuung" in _codes(check_plausibility(o, now_jd=NOW), "WARN")
    assert "check_offset" in _codes(check_plausibility(_obs(), kmag_expected=7.0, now_jd=NOW), "WARN")
    o = _obs()
    o[5].mag += 0.8
    assert "sprung" in _codes(check_plausibility(o, now_jd=NOW), "WARN")


def test_maturity_warns_only_for_unverified():
    w = maturity_warnings(["aavso_format", "transform_lightcurve", "siril_cfa_script", "unbekannt"])
    assert len(w) == 3 and not any("aavso_format" in x for x in w) and "[ungetestet] siril_cfa_script" in "\n".join(w)
