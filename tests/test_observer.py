import pytest

from varphot.observer import (BUILTIN_SITES, Camera, Observer, Site, all_sites, config_path,
                              load_config, save_config, upsert_site)


def test_roundtrip(tmp_path):
    p = tmp_path / "cfg" / "observer.json"
    obs = Observer("abcd", "Testort", Camera(model="QHY268M", gain_e_per_adu=0.8))
    sites = [Site("Testort", 50.1000, 8.2000, 100)]
    save_config(obs, sites, p)
    o2, s2 = load_config(p)
    assert o2.aavso_code == "ABCD"                      # Grossschreibung
    assert o2.camera.model == "QHY268M" and o2.camera.gain_e_per_adu == 0.8
    assert s2 == sites
    assert oct(p.stat().st_mode & 0o777) == "0o600"     # nur Benutzer


def test_missing_config_gives_empty(tmp_path):
    obs, sites = load_config(tmp_path / "gibt_es_nicht.json")
    assert obs.aavso_code == "" and sites == []


def test_site_validation():
    with pytest.raises(ValueError):
        Site("x", 95, 0)
    with pytest.raises(ValueError):
        Site("x", 0, 200)          # Laenge 8,45 Ost ist ok, 200 nicht
    with pytest.raises(ValueError):
        Site(" ", 0, 0)


def test_observer_code_validation():
    with pytest.raises(ValueError):
        Observer("A P Q")
    assert Observer("").aavso_code == ""


def test_earth_location_is_geodetic():
    loc = Site("Testort", 50.1000, 8.2000, 100).earth_location
    assert loc.lat.deg == pytest.approx(50.1000, abs=1e-4)
    assert loc.lon.deg == pytest.approx(8.2000, abs=1e-4)
    assert loc.height.to("m").value == pytest.approx(100, abs=1e-3)


def test_all_sites_order_and_override():
    own = [Site(BUILTIN_SITES[0].name, 1, 2, 3), Site("Testort", 50.1000, 8.2000, 100)]
    sites = all_sites(own)
    assert sites[0].name == BUILTIN_SITES[0].name and sites[0].lat_deg == 1   # eigene gewinnt
    assert [s.name for s in sites].count(BUILTIN_SITES[0].name) == 1
    assert sites[-1].name == BUILTIN_SITES[1].name


def test_upsert_replaces_same_name():
    s = upsert_site([Site("A", 1, 1), Site("B", 2, 2)], Site("A", 9, 9))
    assert [x.name for x in s] == ["B", "A"] and s[-1].lat_deg == 9


def test_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "x.json"))
    assert config_path() == tmp_path / "x.json"


def test_builtin_sites_are_public_testdata_sites():
    for s in BUILTIN_SITES:
        assert "Testdaten" in s.name           # nur oeffentliche Testdaten-Standorte, nichts Persoenliches
        assert isinstance(s.earth_location.lat.deg, float)
