#!/usr/bin/env python3
"""Vorschau (Mockup) aller GUI-Bausteine und aller umgebauten Notebook-Zellen als eine HTML-Seite.

Warum: Eine Oberfläche wird zuerst als sichtbares Mockup abgestimmt, dann gebaut. Diese Seite ist das lebende Mockup: jeder Baustein aus ``varphot/nbui.py`` steht in ``SAMPLES``,
und ``tests/test_gui_rules.py`` schlägt fehl, wenn ein neuer Baustein hier fehlt. So entsteht kein Baustein ohne Ansicht.

Aufruf::

    python tools/gui_preview.py [ausgabe.html]      # Standard: build/gui-vorschau.html, im Browser öffnen
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from varphot import nbui as ui  # noqa: E402

CASES = {"mono": "im Meldefilter, z. B. V", "monorgb": "im Grünfilter (TG)", "osc": "RAW ohne Debayern", "dslr": "RAW erst in Siril nach FITS"}

SAMPLES = {
    "icon": lambda: "".join(ui.icon(n) for n in ui._PATHS),
    "stepper": lambda: ui.stepper("00", 4),
    "para": lambda: ui.para("Ein kurzer Absatz mit **fett**, *kursiv* und `code`."),
    "note": lambda: "".join(ui.note(k, f"Hinweis der Art {k}.") for k in ui.NOTE),
    "tasks": lambda: ui.tasks(["Offene Aufgabe", ("Erledigte Aufgabe mit Zusatzzeile", "Zusatz in Grau", True)]),
    "tiles": lambda: ui.tiles([("photo", "Messbild 1", "halbe Zeit"), ("focus", "Scharfes Bild", "wie Messbild 2", True)]),
    "cases": lambda: ui.cases("osc", CASES),
    "fields": lambda: ui.fields([("Feld", "Wert im Testlauf", "Wert bei eigenen Aufnahmen")]),
    "kv": lambda: ui.kv([("Name", "Beschreibung"), ("Zweiter", "Noch eine")]),
    "numbered": lambda: ui.numbered(["Erst das", "Dann das"]),
    "code": lambda: ui.code("<Ordner>/probe/\n<Ordner>/probe/scharf/"),
    "chips": lambda: ui.chips(["probe/", "probe/scharf/"]),
    "details": lambda: ui.details("Mehr anzeigen", ui.para("Verborgener Inhalt.")),
    "step": lambda: ui.step("00", "1.2", "Schrittkarte", tag="einmalig", meta=[("Wo", "Am Teleskop"), ("Dauer", "10 min")], intro="Einleitung.", blocks=[ui.tasks(["Aufgabe"])]),
    "header": lambda: ui.header("01", "Notebook-Kopf", "Ergebnis des Notebooks", wann="vor der Messung", flow=[("Schritt 1", "a"), ("Schritt 2", "b"), ("Schritt 3", "c")], method="mono", texts=CASES),
    "result": lambda: ui.result("ok", "Beobachtung heute Nacht möglich", "LCO McDonald", [ui.stats([("Fenster (UTC)", "01:00 bis 07:00", "13. November"), ("Mond", "13 %", "stört nicht", "ok")])]),
    "panel": lambda: ui.panel("Bereitschaft", [ui.status_rows([("ok", "Gut", "", "erfüllt"), ("none", "Optional", "fehlt, optional", "Folge steht hier"), ("error", "Hindernis", "", "muss behoben werden")])]),
    "stats": lambda: ui.stats([("A", "1", "Zusatz"), ("B", "2", "Zusatz", "warn")]),
    "status_rows": lambda: ui.status_rows([("ok", "Titel", "Etikett", "Text")]),
    "bars": lambda: ui.bars([("NGC 7790", 8, 8, "8,0 h", "bis 59°", "ok"), ("M 11", 1, 8, "1,0 h", "bis 37°", "warn"), ("NGC 3532", 0, 8, "0 h", "nie über 30°", "none")], "Standardfelder"),
    "table": lambda: ui.table(__import__("pandas").DataFrame({"Feld": ["NGC 7790", "M 67"], "Stunden": [8.0, 4.5], "sichtbar": [True, False]})),
    "say": lambda: "",
    "show": lambda: "",
    "current_method": lambda: "",
}


def main(out: Path) -> None:
    head = "<h3 style='font:13px sans-serif;color:#666;margin:22px 0 2px'>{}</h3>"
    parts = [head.format(n) + f() for n, f in SAMPLES.items() if n not in ("show", "current_method", "say")]
    import IPython.display as d
    shown: list[str] = []
    real = d.display
    d.display = lambda o, *a, **k: shown.append(o.data)
    try:
        for p in sorted((ROOT / "notebooks").glob("*.ipynb")):
            for i, c in enumerate(json.loads(p.read_text(encoding="utf-8"))["cells"]):
                src = "".join(c["source"])
                if c["cell_type"] == "code" and src.startswith(ui.CARD_PREFIX):
                    shown.clear()
                    exec(compile(src, f"{p.name}[{i}]", "exec"), {"METHOD": "osc"})
                    parts.append(head.format(f"{p.stem}, Zelle {i}") + "".join(shown))
    finally:
        d.display = real
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("<meta charset=utf-8><body style='max-width:780px;margin:20px auto;background:#fff'>" + ui.CSS + "".join(parts), encoding="utf-8")
    print(f"{len(parts)} Abschnitte → {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "gui-vorschau.html")
