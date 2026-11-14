"""VSX-Bereich (varphot.vsx) und Ort/Zeit-Pruefung (varphot.visibility) in der Inhaltspruefung; alle Netzzugriffe ueber eine Attrappe."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from varphot import vsx
from varphot.aavso import Observation, check_plausibility
from varphot.visibility import airmass_kasten_young, altitudes

NOW = 2461000.0
DEL_CEP = {"Name": "del Cep", "AUID": "000-BCQ-471", "RA2000": "337.29279", "Declination2000": "58.41519", "MaxMag": "3.49 V", "MinMag": "4.36 V"}
RA, DEC = 337.29276, 58.41519
MCDONALD = SimpleNamespace(lat_deg=30.6800415, lon_deg=-104.015066, height_m=2030.0)
BALKON = SimpleNamespace(lat_deg=49.3, lon_deg=-7.5, height_m=120.0)
J0 = 2458802.62                                                      # Nacht vom 12./13.11.2019 (LCO-Testdaten), δ Cep hoch im Norden


def _codes(f, level=None):
    return {x.code for x in f if level is None or x.level == level}


# ---------------------------------------------------------------- parse_mag / catalog_range
@pytest.mark.parametrize("text,expected", [
    ("3.49 V", (3.49, "ok")), ("4.0: V", (4.0, "unsicher")), ("<17.5 V", (None, "grenze")), ("(0.013) V", (None, "amplitude")), ("?", (None, "leer")), ("", (None, "leer")),
    (None, (None, "leer")), ("14.03 G", (None, "band")), ("(0.008)TESS", (None, "amplitude")), ("12.87V", (12.87, "ok")), ("abc", (None, "unlesbar")), ("3,5 V", (None, "unlesbar"))])
def test_parse_mag_formats_seen_in_vsx(text, expected):
    assert vsx.parse_mag(text, "V") == expected


def test_catalog_range_needs_both_values_in_band_and_says_why():
    r, why = vsx.catalog_range(DEL_CEP)
    assert (r.lo, r.hi, r.band, r.uncertain, r.name) == (3.49, 4.36, "V", False, "del Cep") and why == ""
    assert vsx.catalog_range({"MaxMag": "8.29 V", "MinMag": "(0.013) V"})[0] is None
    assert "nur Amplitude" in vsx.catalog_range({"MaxMag": "8.29 V", "MinMag": "(0.013) V"})[1]
    assert "nicht im Band V" in vsx.catalog_range({"MaxMag": "14.03 G", "MinMag": "14.05 G"})[1]
    assert "fehlt" in vsx.catalog_range({"MaxMag": "12.87 V"})[1]
    assert vsx.catalog_range({"MaxMag": "9.0: V", "MinMag": "10.0 V"})[0].uncertain is True
    assert vsx.catalog_range({"MaxMag": "10.0 V", "MinMag": "9.0 V"})[0].lo == 9.0         # vertauschte Reihenfolge schadet nicht
    assert vsx.catalog_range(None)[0] is None


# ---------------------------------------------------------------- Abfrage mit Attrappe
class Fake:
    """Attrappe fuer die Netzabfrage: protokolliert URLs und antwortet je nach Stichwort."""
    def __init__(self, objects=None, cone=None, fail=False):
        self.urls, self.objects, self.cone, self.fail = [], objects or {}, cone or [], fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("offline")
        if "api.object" in url:
            for k, v in self.objects.items():
                if k in url.lower().replace("+", " ").replace("%2a", "*"):
                    return json.dumps({"VSXObject": v})
            return json.dumps({"VSXObject": []})
        return json.dumps({"VSXObjects": {"VSXObject": self.cone}})


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.delenv("VARPHOT_VSX", raising=False)
    return tmp_path / "vsx.json"


def test_fetch_by_name_strips_star_prefix_and_caches(cache):
    f = Fake({"del cep": DEL_CEP})
    o, st = vsx.fetch_object("* del Cep", fetch=f, cache=cache, now=1000.0)
    assert st == "ok" and o["Name"] == "del Cep" and len(f.urls) == 1 and "ident=del+Cep" in f.urls[0] and "%2A" not in f.urls[0]
    o2, st2 = vsx.fetch_object("del Cep", fetch=Fake(fail=True), cache=cache, now=1000.0 + 86400)      # Treffer kommt aus dem Zwischenspeicher, kein Netz noetig
    assert st2 == "ok" and o2 == o
    o3, st3 = vsx.fetch_object("del Cep", fetch=Fake(fail=True), cache=cache, now=1000.0 + 31 * 86400)   # abgelaufen
    assert o3 is None and st3 == "nicht erreichbar"


def test_auid_first_then_name_then_cone(cache):
    f = Fake({"del cep": DEL_CEP})
    vsx.fetch_object("del Cep", auid="000-BCQ-471", fetch=f, cache=cache, now=1.0)
    assert "ident=000-BCQ-471" in f.urls[0] and len(f.urls) == 2                                      # AUID unbekannt in der Attrappe → danach Name
    g = Fake(cone=[dict(DEL_CEP, Name="Nachbar", RA2000="337.3", Declination2000="58.5"), DEL_CEP, {"Name": "Gaia", "RA2000": "337.29276", "Declination2000": "58.41519", "MaxMag": "14 G", "MinMag": "15 G"}])
    o, st = vsx.fetch_object("unbekannt", ra=RA, dec=DEC, fetch=g, cache=cache, now=2.0)
    assert st == "ok" and o["Name"] == "del Cep"                                                      # naechster Eintrag mit brauchbarem V-Bereich, Gaia-G-Eintrag wird uebergangen
    assert "api.list" in g.urls[-1] and "radius=0.003" in g.urls[-1]


def test_offline_and_not_found_and_off_never_raise(cache, monkeypatch):
    assert vsx.fetch_object("x", fetch=Fake(fail=True), cache=cache, now=1.0) == (None, "nicht erreichbar")
    assert vsx.fetch_object("Nonsens", fetch=Fake(), cache=cache, now=1.0) == (None, "nicht gefunden")
    assert vsx.fetch_object("Nonsens", fetch=Fake(fail=True), cache=cache, now=2.0)[1] == "nicht gefunden"   # "nicht gefunden" ist 1 Tag im Zwischenspeicher
    monkeypatch.setenv("VARPHOT_VSX", "off")
    f = Fake({"del cep": DEL_CEP})
    assert vsx.fetch_object("del Cep", fetch=f, cache=cache) == (None, "aus") and f.urls == []
    rng, msg = vsx.lookup_range("del Cep", fetch=f, cache=cache)
    assert rng is None and "ausgeschaltet" in msg


def test_garbage_answer_is_treated_as_unreachable(cache):
    assert vsx.fetch_object("x", fetch=lambda u: "<html>Just a moment...</html>", cache=cache, now=1.0)[1] == "nicht erreichbar"


def test_lookup_range_messages(cache):
    r, msg = vsx.lookup_range("del Cep", fetch=Fake({"del cep": DEL_CEP}), cache=cache, now=1.0)
    assert r.lo == 3.49 and msg == ""
    r, msg = vsx.lookup_range("amp", fetch=Fake({"amp": {"Name": "NSV 1", "MaxMag": "8.29 V", "MinMag": "(0.013) V"}}), cache=cache, now=1.0)
    assert r is None and "nur Amplitude" in msg and "nicht geprueft" in msg
    assert "nicht erreichbar" in vsx.lookup_range("y", fetch=Fake(fail=True), cache=cache, now=1.0)[1]


def test_request_contains_no_private_data(cache):
    f = Fake({"del cep": DEL_CEP})
    vsx.fetch_object("del Cep", fetch=f, cache=cache, now=1.0)
    assert all(u.startswith("https://vsx.aavso.org/index.php?") for u in f.urls)
    assert vsx.USER_AGENT == "varphot"


# ---------------------------------------------------------------- Regel R1 (Bereich)
def _obs(n=20, mag0=3.8, jd0=J0, airmass=None, **kw):
    return [Observation("DEL CEP", jd0 + i * 0.004, mag0 + 0.01 * (i % 3), 0.01 + 0.0005 * (i % 4), "V", False, chart="X43370RNS", kname="C1", kmag=7.5 + 0.005 * (i % 2),
                        airmass=None if airmass is None else airmass(jd0 + i * 0.004), **kw) for i in range(n)]


CAT = vsx.catalog_range(DEL_CEP)[0]


def test_r1_normal_data_is_silent_and_gross_errors_warn_only():
    assert "katalog_bereich" not in _codes(check_plausibility(_obs(), catalog=CAT, now_jd=NOW))
    f = check_plausibility(_obs(mag0=5.8), catalog=CAT, now_jd=NOW)
    assert "katalog_bereich" in _codes(f, "WARN") and "katalog_bereich" not in _codes(f, "ERROR")
    assert "falscher Stern" in next(x.text for x in f if x.code == "katalog_bereich") and "del Cep" in next(x.text for x in f if x.code == "katalog_bereich")


def test_r1_tolerance_is_half_a_magnitude_and_wider_for_uncertain_ranges():
    assert "katalog_bereich" not in _codes(check_plausibility(_obs(mag0=4.36 + 0.4), catalog=CAT, now_jd=NOW))        # +0,4 mag ausserhalb: innerhalb der Toleranz (LCO-Testdaten: 0,21)
    assert "katalog_bereich" in _codes(check_plausibility(_obs(mag0=4.36 + 0.7), catalog=CAT, now_jd=NOW))
    unsure = vsx.CatalogRange(3.49, 4.36, "V", uncertain=True)
    assert "katalog_bereich" not in _codes(check_plausibility(_obs(mag0=4.36 + 0.7), catalog=unsure, now_jd=NOW))
    assert "katalog_bereich" in _codes(check_plausibility(_obs(mag0=4.36 + 1.3), catalog=unsure, now_jd=NOW))


def test_r1_is_off_without_catalog_and_existing_behaviour_is_unchanged():
    assert "katalog_bereich" not in _codes(check_plausibility(_obs(mag0=9.0), now_jd=NOW))
    assert "mag_bereich" in _codes(check_plausibility(_obs(mag0=9.0), expected_range=(3.3, 4.5), catalog=CAT, now_jd=NOW), "ERROR")


# ---------------------------------------------------------------- Regel R2 (Ort und Zeit)
def _am_at(site):
    def f(jd):
        star, _ = altitudes(RA, DEC, [jd], site.lat_deg, site.lon_deg, site.height_m)
        return round(airmass_kasten_young(float(star[0])), 4)
    return f


def _r2(obs, site=MCDONALD, **kw):
    return check_plausibility(obs, site=site, target_radec=(RA, DEC), now_jd=NOW, **kw)


def test_airmass_formula_and_altitudes():
    assert airmass_kasten_young(90) == pytest.approx(1.0, abs=0.001) and airmass_kasten_young(30) == pytest.approx(1.994, abs=0.002)
    assert airmass_kasten_young(0) != airmass_kasten_young(0)                                      # nan unter dem Horizont
    star, sun = altitudes(RA, DEC, [J0, J0 + 0.5], MCDONALD.lat_deg, MCDONALD.lon_deg, 2030.0)
    assert star[0] > 30 and sun[0] < -12 and sun[1] > 0                                           # in der Nacht dunkel, 12 h spaeter Tag


def test_r2_consistent_file_is_silent():
    f = _r2(_obs(airmass=_am_at(MCDONALD)))
    assert not _codes(f) & {"stern_horizont", "sonne_hoch", "luftmasse_ort"}


@pytest.mark.parametrize("shift_h,expect", [(2, {"luftmasse_ort"}), (12, {"sonne_hoch"})])
def test_r2_wrong_time_is_found(shift_h, expect):
    am = _am_at(MCDONALD)
    obs = [Observation(**{**o.__dict__, "jd": o.jd + shift_h / 24}) for o in _obs(airmass=am)]               # Datei traegt die Luftmasse der echten Zeit, die Zeit selbst ist verschoben
    assert expect <= _codes(_r2(obs))


def test_r2_wrong_site_and_wrong_sign_of_longitude_are_found():
    obs = _obs(airmass=_am_at(MCDONALD))
    assert "luftmasse_ort" in _codes(_r2(obs, site=BALKON), "WARN")
    assert "sonne_hoch" in _codes(_r2(obs, site=SimpleNamespace(lat_deg=30.68, lon_deg=104.015, height_m=2030.0)), "WARN")


def test_r2_star_below_horizon_is_an_error():
    site = SimpleNamespace(lat_deg=-60.0, lon_deg=-104.0, height_m=0.0)                          # δ Cep (+58°) von 60° S nie sichtbar
    assert "stern_horizont" in _codes(_r2(_obs(), site=site), "ERROR")


def test_r2_without_airmass_column_or_without_site_does_nothing_extra():
    f = _r2(_obs())
    assert "luftmasse_ort" not in _codes(f)
    assert not _codes(check_plausibility(_obs(), now_jd=NOW)) & {"stern_horizont", "sonne_hoch", "luftmasse_ort"}


def test_r2_tolerates_sec_z_style_airmass():
    import math

    def sec(jd):
        star, _ = altitudes(RA, DEC, [jd], MCDONALD.lat_deg, MCDONALD.lon_deg, 2030.0)
        return 1 / math.sin(math.radians(float(star[0])))
    assert "luftmasse_ort" not in _codes(_r2(_obs(airmass=sec)))


@pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "PHOTOMETRIE_PY_DATA" / "exports").is_dir(), reason="echte Testdaten nicht vorhanden")
def test_real_lco_export_has_no_new_findings():
    d = Path(__file__).resolve().parents[2] / "PHOTOMETRIE_PY_DATA" / "exports"
    files = sorted(d.glob("aavso_DEL_CEP_V_*_TESTDATEN_NICHT_EINREICHEN.txt"))
    if not files:
        pytest.skip("kein Export")
    obs = []
    for line in files[-1].read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        c = line.split(",")
        obs.append(Observation(c[0], float(c[1]), float(c[2]), float(c[3]), c[4], c[5] == "YES", airmass=float(c[11]), chart=c[13]))
    f = check_plausibility(obs, catalog=CAT, site=MCDONALD, target_radec=(RA, DEC), now_jd=NOW)
    assert not _codes(f) & {"katalog_bereich", "stern_horizont", "sonne_hoch", "luftmasse_ort"}
