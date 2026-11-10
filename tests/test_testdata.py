"""Download-Logik ohne Netz (Antworten gemockt)."""
import hashlib

import pytest

from varphot import testdata as td


def test_testdata_dir_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VARPHOT_TESTDATA", str(tmp_path / "x"))
    assert td.testdata_dir() == tmp_path / "x"
    monkeypatch.delenv("VARPHOT_TESTDATA")
    from varphot import observer
    monkeypatch.setattr(observer, "REPO_ROOT", tmp_path / "PHOTOMETRIE_PY")
    assert td.testdata_dir().name == "astro_testdata"                      # kein Datenordner -> ~/astro_testdata
    (tmp_path / observer.DATA_DIRNAME).mkdir()
    assert td.testdata_dir() == tmp_path / observer.DATA_DIRNAME / "testdata"


def test_lco_frames_paginates_filters_and_ignores_count(monkeypatch):
    pages = {0: [{"basename": f"elp0m411-a{i}"} for i in range(100)],
             100: [{"basename": f"ogg0m406-b{i}"} for i in range(60)] + [{"basename": "elp0m411-c"}]}

    def fake(url, params=None, tries=3):
        return {"count": 24, "results": pages[params["offset"]]}      # count lügt (wie im echten Archiv)
    monkeypatch.setattr(td, "_get_json", fake)
    fr = td.lco_frames()
    assert len(fr) == 101 and all(f["basename"].startswith("elp0m411-") for f in fr)


class FakeResp:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_content(self, n): yield self.data


def test_download_checks_md5_and_skips_existing(tmp_path, monkeypatch):
    data = b"hello fits"
    md5 = hashlib.md5(data).hexdigest()
    calls = []
    monkeypatch.setattr(td.requests, "get", lambda *a, **k: calls.append(1) or FakeResp(data))
    dest = tmp_path / "f.fz"
    assert td.download_file("u", dest, md5=md5) == "geladen" and dest.read_bytes() == data
    assert td.download_file("u", dest, md5=md5) == "vorhanden" and len(calls) == 1   # nicht erneut geladen
    with pytest.raises(IOError):                                                        # falsche Pruefsumme
        td.download_file("u", tmp_path / "g.fz", md5="0" * 32)
    assert not (tmp_path / "g.fz").exists() and not (tmp_path / "g.fz.part").exists()


def test_unknown_dataset():
    with pytest.raises(KeyError):
        td.download_dataset("gibt-es-nicht")
