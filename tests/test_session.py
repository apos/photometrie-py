"""Sitzung (session.json, Ordnerstruktur, zuletzt benutzte) und Siril-Skripte (Aufbau; Siril selbst ist nicht installiert)."""
import json
import subprocess

import pytest

from varphot import siril
from varphot.session import Session, session_tag


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "cfg" / "observer.json"))        # Datenordner-Suche: kein echter Datenordner
    from varphot import observer
    monkeypatch.setattr(observer, "REPO_ROOT", tmp_path / "repo" / "PHOTOMETRIE_PY")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("VARPHOT_SESSION", raising=False)


def test_session_dirs_save_load_and_current(tmp_path):
    s = Session(str(tmp_path / "nacht1"), target="del Cep", method="osc", tag="t")
    made = s.ensure_dirs()
    assert {"lights", "darks", "flats", "biases", "probe", "probe/scharf", "process", "masters", "scripts", "results"} <= set(made)
    assert s.ensure_dirs() == []                                                      # zweites Mal: nichts Neues
    s.save()
    t = Session.load(tmp_path / "nacht1")
    assert t.target == "del Cep" and t.method == "osc" and t.path("probe", "scharf").is_dir()
    assert Session.current().workspace == str(tmp_path / "nacht1")                    # zuletzt benutzte
    other = Session(str(tmp_path / "nacht2"), target="x"); other.save(remember=False)
    assert Session.current().workspace == str(tmp_path / "nacht1")
    import os
    os.environ["VARPHOT_SESSION"] = str(tmp_path / "nacht2")
    assert Session.current().target == "x"


def test_session_update_unknown_keys_and_missing(tmp_path):
    s = Session(str(tmp_path / "w"))
    s.update(plan="p.json", ref_fwhm_px=4.2)
    assert Session.load(tmp_path / "w").ref_fwhm_px == 4.2
    with pytest.raises(KeyError, match="unbekannte"):
        s.update(gibtsnicht=1)
    with pytest.raises(FileNotFoundError, match="NB00"):
        Session.load(tmp_path / "leer")
    (tmp_path / "w" / "session.json").write_text(json.dumps({"workspace": "/alt/pfad", "target": "y", "zukunft": 1}))
    t = Session.load(tmp_path / "w")                                                  # neuere Felder ignoriert, Ordner = Ort der Datei
    assert t.target == "y" and t.workspace == str(tmp_path / "w")


def test_current_without_any_session_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="NB00"):
        Session.current()


def test_results_dir_and_tag():
    assert session_tag("del Cep", "osc", "2026-11-10") == "del_cep_osc_2026_11_10"


# ------------------------------------------------------------------------------------------------ Siril
def _files(tmp_path, kinds):
    for d, ext in kinds.items():
        (tmp_path / d).mkdir()
        if ext:
            (tmp_path / d / f"a{ext}").write_text("x")


def test_sequence_kind(tmp_path):
    _files(tmp_path, {"r": ".CR2", "f": ".fits", "e": None})
    (tmp_path / "m").mkdir(); (tmp_path / "m" / "a.rw2").write_text("x"); (tmp_path / "m" / "b.fit").write_text("x")
    assert siril.sequence_kind(tmp_path / "r") == "raw" and siril.sequence_kind(tmp_path / "f") == "fits"
    assert siril.sequence_kind(tmp_path / "e") is None and siril.sequence_kind(tmp_path / "nix") is None and siril.sequence_kind(tmp_path / "m") == "raw"


def test_calibration_script_mono_and_cfa():
    k = {"lights": "fits", "darks": "fits", "flats": "fits", "biases": "fits"}
    mono = siril.build_calibration_script("mono", k)
    assert mono.startswith("# Von varphot") and "requires 1.2.0" in mono and "-cfa" not in mono
    assert "convert bias -out=../process" in mono and "stack bias rej 3 3 -nonorm -out=../masters/bias_master" in mono
    assert "calibrate flat -bias=../masters/bias_master" in mono and "stack pp_flat rej 3 3 -norm=mul -out=../masters/flat_master" in mono
    assert "calibrate light -dark=../masters/dark_master -flat=../masters/flat_master" in mono and mono.rstrip().endswith("close")
    osc = siril.build_calibration_script("osc", {**k, "lights": "raw"})
    assert "convertraw light -out=../process" in osc and "calibrate light -dark=../masters/dark_master -flat=../masters/flat_master -cfa -equalize_cfa" in osc
    assert "calibrate flat -bias=../masters/bias_master -cfa" in osc and "debayer" not in osc          # Farbe: nicht debayern


def test_calibration_script_without_optional_parts_and_errors():
    only = siril.build_calibration_script("mono", {"lights": "fits"})
    assert "calibrate light" in only and "-dark" not in only and "-flat" not in only and "stack" not in only
    nobias = siril.build_calibration_script("mono", {"lights": "fits", "flats": "fits", "darks": "fits"})
    assert "stack flat rej 3 3 -norm=mul" in nobias and "calibrate flat" not in nobias
    biasonly = siril.build_calibration_script("mono", {"lights": "fits", "biases": "fits"})
    assert "calibrate light -bias=../masters/bias_master" in biasonly
    with pytest.raises(ValueError, match="lights"):
        siril.build_calibration_script("mono", {"darks": "fits"})
    assert "convertraw probe -out=fits" in siril.build_convert_script("raw")


def test_run_script_paths(tmp_path):
    ok, log = siril.run_script(tmp_path / "s.ssf", tmp_path, siril="")
    assert not ok and "nicht gefunden" in log or True
    calls = []

    class R:
        returncode, stdout, stderr = 0, "fertig", ""
    ok, log = siril.run_script("s.ssf", tmp_path, siril="/x/siril-cli", runner=lambda cmd, **k: (calls.append(cmd), R())[1])
    assert ok and log == "fertig" and calls[0] == ["/x/siril-cli", "-d", str(tmp_path), "-s", "s.ssf"]
    R.returncode = 1
    assert siril.run_script("s.ssf", tmp_path, siril="/x/s", runner=lambda *a, **k: R())[0] is False

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("x", 1)
    assert "Zeitlimit" in siril.run_script("s", tmp_path, siril="/x/s", runner=boom)[1]

    def nostart(*a, **k):
        raise OSError("weg")
    assert "nicht startbar" in siril.run_script("s", tmp_path, siril="/x/s", runner=nostart)[1]


def test_write_script_and_calibrated_frames(tmp_path):
    p = siril.write_script(tmp_path / "scripts" / "c.ssf", "x\n")
    assert p.read_text() == "x\n"
    (tmp_path / "process").mkdir()
    for n in ("pp_light_00002.fit", "pp_light_00001.fits", "pp_light_00003.txt", "light_00001.fit"):
        (tmp_path / "process" / n).write_text("x")
    assert [f.name for f in siril.calibrated_frames(tmp_path / "process")] == ["pp_light_00001.fits", "pp_light_00002.fit"]
    assert siril.calibrated_frames(tmp_path / "nix") == []


def test_current_requires_explicit_save(tmp_path):
    """Session.open() allein reicht nicht — NB00 muss danach save() aufrufen (auch im Demo-Modus)."""
    Session.open(str(tmp_path / "s1"), target="Algol", method="osc", aavso_filter="V", source="demo")
    with pytest.raises(FileNotFoundError, match="NB00"):
        Session.current()

    s = Session.open(str(tmp_path / "s2"), target="Algol", method="osc", aavso_filter="V", source="demo")
    s.save()
    assert Session.current().workspace == str(tmp_path / "s2")


def test_open_keeps_results_unless_target_or_method_changes(tmp_path):
    s = Session.open(str(tmp_path / "w"), target="del Cep", method="mono")
    assert not (tmp_path / "w" / "session.json").exists()                              # angelegt erst beim Speichern
    s.update(plan="p.json", ref_frame="r.fits", field_config="f.json", tag="t")
    t = Session.open(str(tmp_path / "w"), target="del Cep", method="mono", aavso_filter="V")
    assert t.plan == "p.json" and t.field_config == "f.json" and t.aavso_filter == "V"        # erneutes NB00: Ergebnisse bleiben
    u = Session.open(str(tmp_path / "w"), target="eta Aql", method="mono")
    assert u.plan == "" and u.field_config == "" and u.ref_fwhm_px is None and "target" in u.notes["zurueckgesetzt"]
    v = Session.open(str(tmp_path / "w"), method="osc")                                   # nur die Methode aendert sich
    assert "method" in v.notes["zurueckgesetzt"]
