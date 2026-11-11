"""Sofort-Hinweise der Formulare (varphot.hints): Texte, Stufen, Bindung an Widgets."""
from varphot import hints as H


def levels(items):
    return [lv for lv, _ in items]


def test_render_empty_and_levels():
    assert H.render([]) == ""
    html = H.render([("ok", "a"), ("error", "b")])
    assert html.count("<div") == 2 and "#2e7d32" in html and "#c62828" in html and "color:#1b1b1b" in html      # Schrift ausdruecklich gesetzt (dunkle Notebook-Designs)


def test_nb00_lco_mode_says_everything_is_preset():
    h = H.nb00_hints("lco", "mono", "V", "Mono")
    assert levels(h) == ["ok"] and "vorgegeben" in h[0][1]


def test_nb00_camera_must_match_method():
    assert "error" in levels(H.nb00_hints("real", "mono", "V", "Farbe (Bayer RGGB)"))
    assert "error" in levels(H.nb00_hints("real", "osc", "TG", "Mono"))
    assert "error" not in levels(H.nb00_hints("real", "osc", "TG", "Farbe (Bayer RGGB)"))
    assert "error" not in levels(H.nb00_hints("real", "dslr", "TG", "Farbe (DSLR)"))


def test_nb00_filter_matches_method():
    assert any(lv == "warn" for lv, _ in H.nb00_hints("real", "mono", "TG", "Mono"))
    assert any(lv == "warn" for lv, _ in H.nb00_hints("real", "osc", "V", "Farbe (Bayer RGGB)"))
    assert not any(lv == "warn" for lv, _ in H.nb00_hints("real", "mono", "V", "Mono"))


def test_nb00_real_mode_names_probe_folders():
    h = H.nb00_hints("real", "mono", "V", "Mono", "/x/ws")
    assert "/x/ws/probe/" in h[0][1] and "scharf" in h[0][1]


def test_nb00_observer_hints():
    assert H.nb00_observer_hints("LCO", True, False, "", "Q", "Mono")[0][0] == "ok"
    assert "Neuer Standort" in H.nb00_observer_hints("", False, True, "", "", "")[0][1]
    assert any(lv == "warn" for lv, _ in H.nb00_observer_hints("S", False, False, "", "", ""))
    assert any("ABCD" in t for _, t in H.nb00_observer_hints("S", False, False, "ABCD", "", ""))
    assert any("Fall D" in t for _, t in H.nb00_observer_hints("S", False, False, "A", "Lumix", "Farbe (DSLR)"))


def test_nb01_hints():
    assert "error" in levels(H.nb01_hints("run", False, "mono", "", False, 10, True, True))              # Siril fehlt
    assert "ok" in levels(H.nb01_hints("run", True, "osc", "", False, 10, True, True))
    assert any("CFA" in t for _, t in H.nb01_hints("run", True, "osc", "", False, 10, True, True))
    assert "error" in levels(H.nb01_hints("done", True, "mono", "/nicht/da.fits", False, 10, True, True))   # Referenzbild fehlt
    assert any(lv == "warn" for lv, _ in H.nb01_hints("run", True, "mono", "", False, 10, True, True, lco=True))
    assert sum(lv == "warn" for lv, _ in H.nb01_hints("done", True, "mono", "", False, 10, False, False)) == 2


def test_nb02_hints():
    assert "error" in levels(H.nb02_hints("auto", "auto", 8, 1.5, "10", "5", "0.4", True))               # Periode von >= bis
    assert "error" in levels(H.nb02_hints("auto", "auto", 8, 1.5, "x", "5", "0.4", True))
    assert any(lv == "warn" for lv, _ in H.nb02_hints("auto", "manual", 8, 0, "", "", "", False))
    assert not any(lv in ("error", "warn") for lv, _ in H.nb02_hints("auto", "auto", 8, 1.5, "", "", "0.4", True))


def test_nb03_hints():
    assert "error" in levels(H.nb03_hints(True, "", "untransformiert", "V", "", True))                    # eigene Daten ohne Beobachtercode
    assert any("TST01" in t for _, t in H.nb03_hints(False, "ABCD", "untransformiert", "V", "", True))
    assert "error" in levels(H.nb03_hints(False, "ABCD", "transformiert", "V", "", True))                # ohne Transformationsdatei
    assert any(lv == "ok" and "TRANS=YES" in t for lv, t in H.nb03_hints(False, "ABCD", "transformiert", "V", "t.json", False))
    assert any(lv == "warn" for lv, _ in H.nb03_hints(True, "ABCD", "untransformiert", "V", "", True, lco=True))


def test_bind_updates_on_change_and_survives_errors():
    class W:                                                    # minimales Widget: value + observe
        def __init__(self, v=""):
            self.value, self._cb = v, []
        def observe(self, cb, names=None):
            self._cb.append(cb)
        def set(self, v):
            self.value = v
            for cb in self._cb:
                cb({"new": v})
    panel, field = W(), W("a")
    H.bind(panel, [field], lambda: [("ok", f"wert {field.value}")])
    assert "wert a" in panel.value
    field.set("b")
    assert "wert b" in panel.value
    H.bind(panel, [field], lambda: 1 / 0)
    assert "Hinweis nicht verfuegbar" in panel.value
