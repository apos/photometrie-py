"""Qualitätssicherung der Oberfläche: Darstellungsregeln für Notebooks, Mockup-Pflicht für jeden Baustein, Kontrast, Schrittnummerierung.

Warum: Textwüsten, breite Tabellen und ungeprüfte Mockups sind dreimal aufgefallen (2026-11-12). Diese Tests machen die Regeln aus ``docs/gui.md`` prüfbar, damit sie nicht erst im Review auffallen.
"""
import importlib.util
import inspect
import json
import re
from pathlib import Path

import pytest

from varphot import nbui as ui

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))
MAX_MARKDOWN_CHARS = 600


def _cells(path):
    return json.loads(path.read_text(encoding="utf-8"))["cells"]


def _lum(h):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


@pytest.mark.parametrize("name,fg,bg", ui.CONTRAST_PAIRS, ids=[p[0] for p in ui.CONTRAST_PAIRS])
def test_text_contrast_meets_wcag_aa(name, fg, bg):
    hi, lo = sorted((_lum(fg), _lum(bg)), reverse=True)
    assert (hi + 0.05) / (lo + 0.05) >= 4.5, f"{name}: {fg} auf {bg}"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_no_markdown_tables_and_no_text_walls(path):
    for i, c in enumerate(_cells(path)):
        if c["cell_type"] != "markdown":
            continue
        src = "".join(c["source"])
        assert len(re.findall(r"^\s*\|.*\|\s*$", src, re.M)) < 2, f"{path.name}[{i}]: Markdown-Tabelle, stattdessen ui.fields/ui.kv/ui.tiles verwenden"
        assert len(src) <= MAX_MARKDOWN_CHARS, f"{path.name}[{i}]: {len(src)} Zeichen Fließtext, in Karten (ui.step) aufteilen"


@pytest.mark.parametrize("nb", sorted(ui.STEPS))
def test_step_numbers_run_from_one_without_gaps_and_match_the_stepper(nb):
    path = next(p for p in NOTEBOOKS if p.name.startswith(nb))
    nums = []
    for c in _cells(path):
        m = re.search(r'ui\.step\("%s", ("?)([\d.]+)\1' % nb, "".join(c["source"]))
        if m:
            nums.append(m.group(2))
    mains = [int(n.split(".")[0]) for n in nums]
    assert mains == sorted(mains), f"{nb}: Schritte nicht aufsteigend {nums}"
    assert sorted(set(mains)) == list(range(1, len(ui.STEPS[nb]) + 1)), f"{nb}: Nummern {sorted(set(mains))} passen nicht zur Schrittleiste ({len(ui.STEPS[nb])} Schritte)"
    for n in nums:
        if "." in n:
            assert n.split(".")[1] != "0" and int(n.split(".")[1]) >= 1
    for main in set(mains):                                                                                  # Unterschritt „b“ ohne „a“ gibt es nicht
        subs = sorted(int(n.split(".")[1]) for n in nums if "." in n and int(n.split(".")[0]) == main)
        assert subs in ([], list(range(1, len(subs) + 1))), f"{nb}: Unterschritte von {main} lückenhaft: {subs}"


def test_every_public_building_block_has_a_preview():
    spec = importlib.util.spec_from_file_location("gui_preview", ROOT / "tools" / "gui_preview.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    public = {n for n, f in inspect.getmembers(ui, inspect.isfunction) if not n.startswith("_") and f.__module__ == ui.__name__}
    assert public <= set(mod.SAMPLES), f"Baustein ohne Vorschau in tools/gui_preview.py: {sorted(public - set(mod.SAMPLES))}"
    for name, sample in mod.SAMPLES.items():
        assert isinstance(sample(), str), name


def test_preview_page_builds(tmp_path):
    spec = importlib.util.spec_from_file_location("gui_preview", ROOT / "tools" / "gui_preview.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "v.html"
    mod.main(out)
    assert "vp-t" in out.read_text(encoding="utf-8") and out.stat().st_size > 20_000


VAGUE = [r"[Nn]ächste Zelle ausführen", r"wie unten beschrieben", r"Zelle unten ausführen", r"(?m)^[#* ]*Auswahl übernehmen\s*$", r'"Felder ausfüllen"',
         r"Weiter mit der nächsten Zelle", r"vor der nächsten Zelle", r"Zelle darunter ausführen\W*$"]


def test_instructions_name_their_object_instead_of_vague_pointers():
    """„Nächste Zelle ausführen“, „Auswahl übernehmen“ oder „Felder ausfüllen“ sagen nicht, welche Zelle, was übernommen wird, welche Felder: Gegenstand und Ziel nennen (docs/gui.md §2)."""
    texts = {}
    for path in NOTEBOOKS:
        for i, c in enumerate(_cells(path)):
            src = "".join(c["source"])
            if c["cell_type"] == "markdown" or src.startswith("from varphot import nbui as ui"):
                texts[f"{path.name}[{i}]"] = src
    texts["varphot/hints.py"] = (ROOT / "varphot" / "hints.py").read_text(encoding="utf-8")
    hits = [(where, pat) for where, src in texts.items() for pat in VAGUE if re.search(pat, src)]
    assert not hits, f"unklare Formulierungen: {hits}"
