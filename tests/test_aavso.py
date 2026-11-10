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
