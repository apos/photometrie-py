"""Bausteine der Notebook-Darstellung (varphot.nbui): HTML entsteht, Hervorhebung und Abhaken stimmen, alle umgebauten Notebook-Zellen laufen."""
import json
from pathlib import Path

import pytest

from varphot import nbui as ui

NB_DIR = Path(__file__).resolve().parents[1] / "notebooks"
TEXTS = {"mono": "a", "monorgb": "b", "osc": "c", "dslr": "d"}


def test_stepper_marks_done_current_and_open():
    h = ui.stepper("00", 4)
    assert h.count(ui.OK_LINE) == 3 and "Probebilder" in h and "font-weight:600\">Probebilder" in h
    assert ui.stepper("99", 1) == ""


def test_tasks_are_checkboxes_and_preselection_works():
    h = ui.tasks(["a", ("b", "Zusatz", True)])
    assert h.count('type="checkbox"') == 2 and h.count(" checked") == 1 and "Zusatz" in h


def test_markdown_subset():
    assert "<b>x</b>" in ui._md("**x**") and "<code" in ui._md("`c`") and "<i>k</i>" in ui._md("*k*")
    assert "<i>" not in ui._md("2 * 3 * 4")                                                          # Rechenzeichen werden nicht kursiv


def test_cases_highlight_only_the_active_method():
    h = ui.cases("osc", TEXTS)
    assert h.count("Ihr Fall") == 1 and h.count(ui.OK_LINE) == 1
    assert ui.cases(None, TEXTS).count(ui.OK_LINE) == 0


def test_step_with_sub_number_highlights_main_step():
    h = ui.step("00", "1.2", "Titel", tag="einmalig", meta=[("Wo", "x")], intro="i", blocks=[ui.note("ok", "n")])
    assert ">1.2<" in h and "einmalig" in h and "Wo" in h
    assert ">" + "1.2" not in ui.step("01", None, "ohne Nummer")


def test_header_with_flow_and_case_row():
    h = ui.header("01", "T", "E", flow=[("a", "b")] * 3, method="mono", texts=TEXTS, fall_title="Fall")
    assert "NB01" in h and "Ergebnis" in h and h.count("border-top:3px") == 3 and "Fall" in h


def _converted_cells():
    for p in sorted(NB_DIR.glob("*.ipynb")):
        for i, c in enumerate(json.loads(p.read_text(encoding="utf-8"))["cells"]):
            src = "".join(c["source"])
            if c["cell_type"] == "code" and src.startswith(ui.CARD_PREFIX):
                yield pytest.param(src, id=f"{p.stem}[{i}]")


@pytest.mark.parametrize("src", list(_converted_cells()))
def test_every_nbui_cell_renders(src, monkeypatch):
    shown = []
    import IPython.display as d
    monkeypatch.setattr(d, "display", lambda obj, *a, **k: shown.append(obj.data))
    exec(compile(src, "<nb>", "exec"), {"__name__": "__nb__", "METHOD": "osc"})
    assert shown and shown[0].startswith("<div") and "<style>" in shown[0]


def test_result_blocks_render_tones_bars_and_table():
    import numpy as np
    import pandas as pd
    h = ui.result("warn", "Titel", "rechts", [ui.stats([("a", "1", "x", "ok")]), ui.status_rows([("none", "T", "optional", "Folge")]),
                                              ui.bars([("A", 8, 8, "8,0 h", "bis 59°", "ok"), ("B", 0, 8, "0 h", "nie", "none")], "Kopf")])
    assert "Titel" in h and "optional" in h and "width:100%" in h and "nie" in h
    t = ui.table(pd.DataFrame({"x": [1.5, np.nan, 2.0], "ok": [True, False, True]}))
    assert "1,5" in t and "–" in t and t.count("✓") == 2 and t.count("✗") == 1 and "<th" in t
    assert "weitere Zeilen" in ui.table(pd.DataFrame({"a": range(40)}), max_rows=10)
    assert "Wert" in ui.table(pd.Series({"a": 1.0, "b": 2.5}))


def test_say_picks_tone_from_first_symbol(monkeypatch):
    import IPython.display as d
    shown = []
    monkeypatch.setattr(d, "display", lambda obj, *a, **k: shown.append(obj.data))
    ui.say("⚠ Achtung")
    ui.say("✓ gut", "und mehr")
    ui.say("neutral")
    assert ui.TONES["warn"] in shown[0] and ui.TONES["ok"] in shown[1] and "gut und mehr" in shown[1] and ui.TONES["info"] in shown[2]
