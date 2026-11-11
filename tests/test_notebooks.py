"""Notebooks: gueltiges Format, keine Ausgaben im Repo, jede Code-Zelle uebersetzbar; NB00 laeuft im Demo-Modus komplett durch."""
import json
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"
NOTEBOOKS = sorted(NB_DIR.glob("*.ipynb"))


def _code_cells(path):
    nb = json.loads(path.read_text(encoding="utf-8"))
    return [("".join(c["source"])) for c in nb["cells"] if c["cell_type"] == "code"]


def test_expected_notebooks_exist():
    names = {p.name for p in NOTEBOOKS}
    assert {"00_planung.ipynb", "01_vorbereitung.ipynb", "02_messung.ipynb", "03_bericht.ipynb", "07_kamera_charakterisierung.ipynb", "08_transformation.ipynb"} <= names
    assert not any(n.startswith(("01_kalib", "02_plate", "03_feld", "04_photo", "05_licht", "06_bericht")) for n in names)       # alte Notebooks entfernt


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_is_valid_and_stripped(path):
    import nbformat
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)
    for c in nb.cells:
        if c.cell_type == "code":
            assert c.outputs == [] and c.execution_count is None, f"{path.name}: Zelle mit Ausgabe (nbstripout laufen lassen)"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_every_code_cell_compiles(path):
    for i, src in enumerate(_code_cells(path)):
        compile(src, f"{path.name}[{i}]", "exec")


@pytest.mark.parametrize("path", [p for p in NOTEBOOKS if p.name[:2] in ("00", "01", "02", "03")], ids=lambda p: p.name)
def test_main_notebooks_start_with_form_and_explain_how(path):
    nb = json.loads(path.read_text(encoding="utf-8"))
    first = "".join(nb["cells"][0]["source"])
    assert "So bedienen Sie dieses Notebook" in first and "Fall" in first                              # kurze Anleitung und Fallunterscheidung am Anfang
    assert "Wann:" in first                                                                            # wann im Ablauf / was herauskommt
    text = "\n".join("".join(c["source"]) for c in nb["cells"])
    assert "Ab hier automatisch" in text                                                               # Entscheidungen zuerst, Automatik danach
    if not path.name.startswith("00"):
        assert "Formular — was eintragen" in text                                                      # jedes Formular wird Feld fuer Feld erklaert
    assert text.count("bind(") >= (2 if path.name.startswith("00") else 1)                             # Sofort-Hinweis nach jeder Auswahl (varphot.hints); NB00: Schritt 0b und Schritt 1
    assert "nach jeder Auswahl sofort ein Hinweis" in text                                             # und die Anleitung nennt es


def test_nb00_demo_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "observer.json"))
    monkeypatch.setenv("VARPHOT_NB00_MODE", "demo")
    monkeypatch.setenv("VARPHOT_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("VARPHOT_METHOD", "osc")
    monkeypatch.setenv("VARPHOT_AI", "off")
    monkeypatch.chdir(NB_DIR)
    g = {"__name__": "__nb__"}
    import matplotlib.pyplot as plt
    monkeypatch.setattr(plt, "show", lambda *a, **k: None)
    for i, src in enumerate(_code_cells(NB_DIR / "00_planung.ipynb")):
        exec(compile(src, f"00_planung[{i}]", "exec"), g)                                       # noqa: S102 - eigenes Notebook
    assert g["MODE"] == "demo" and g["PLAN"].method == "osc" and g["PLAN"].aperture and g["PLAN"].fwhm_sharp_px
    assert g["PLAN"].aperture_info.get("method") in ("growth+snr", "fallback")
    assert not (tmp_path / "ws" / "session.json").exists()                                      # Demo speichert nichts
