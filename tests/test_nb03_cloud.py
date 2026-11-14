"""NB03 Schritt 6 mit Cloud-KI: Vorschau, Bestätigung, anonymisierter Versand, Rückübersetzung (mit Attrappe des Programms ``claude``)."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as widgets

from varphot import nbui as ui

NB = Path(__file__).resolve().parents[1] / "notebooks" / "03_bericht.ipynb"


def _cell(prefix):
    for c in json.loads(NB.read_text(encoding="utf-8"))["cells"]:
        src = "".join(c["source"])
        if c["cell_type"] == "code" and src.startswith(prefix):
            return src
    raise AssertionError(prefix)


def _setup(tmp_path, monkeypatch, mode="claude", enabled=True):
    rec = tmp_path / "rec"
    rec.mkdir()
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text(f"#!/bin/sh\nif [ \"$1\" = auth ]; then echo '{{\"loggedIn\": true, \"authMethod\": \"claude.ai\"}}'; exit 0; fi\n"
                   f"printf '%s\\n' \"$@\" > \"{rec}/argv.txt\"\ncat > \"{rec}/stdin.txt\"\necho '7. [BEOBACHTERCODE] steht im Kopf, aber ein Check-Stern fehlt.'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])
    cfg = tmp_path / "observer.json"
    cfg.write_text(json.dumps({"aavso_code": "ABCD", "site_name": "Balkon Musterstadt", "ai": {"cloud": {"enabled": enabled}}}))
    monkeypatch.setenv("VARPHOT_CONFIG", str(cfg))
    monkeypatch.delenv("VARPHOT_AI", raising=False)
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "aavso_x_V_bericht.md").write_text("# Export\n\nBeobachter ABCD\n", encoding="utf-8")
    shown = []
    import IPython.display as d
    monkeypatch.setattr(d, "display", lambda o, *a, **k: shown.append(o))
    ns = {"ui": ui, "widgets": widgets, "display": shown.append, "EXPORTS": exports, "name": "aavso_x_V.txt", "ISSUES": [], "ERRORS": [], "FINDINGS": [],
          "TEXT": "#OBSCODE=ABCD\n#NOTES Standort Balkon Musterstadt\n", "OBS": SimpleNamespace(aavso_code="ABCD", site_name="Balkon Musterstadt"), "_own": [],
          "w_ai": SimpleNamespace(value=mode)}
    return ns, shown, rec, exports


def _html(shown):
    return "".join(getattr(o, "data", "") for o in shown if hasattr(o, "data"))


def test_cloud_cell_shows_preview_and_sends_nothing_before_confirmation(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch)
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    html = _html(shown)
    assert "Anbieter: Claude" in html and "[BEOBACHTERCODE]" in html and "ABCD" not in html and "Musterstadt" not in html
    assert not (rec / "stdin.txt").exists()                                                  # noch nichts gesendet
    box = next(o for o in shown if isinstance(o, widgets.VBox))
    ok, go, out = box.children
    go.click()                                                                                 # ohne Bestätigung
    assert not (rec / "stdin.txt").exists() and not (exports / "aavso_x_V_ki_gesendet.md").exists()


def test_cloud_cell_sends_anonymized_text_after_confirmation_and_restores_answer(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch)
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    ok, go, out = next(o for o in shown if isinstance(o, widgets.VBox)).children
    ok.value = True
    go.click()
    sent = (rec / "stdin.txt").read_text()
    assert "ABCD" not in sent and "Musterstadt" not in sent and "[BEOBACHTERCODE]" in sent
    argv = (rec / "argv.txt").read_text()
    assert "Du pruefst den Bericht" in argv and "HINWEIS: Der Text ist anonymisiert" in argv                  # Systemprompt mit Platzhalter-Hinweis
    log = (exports / "aavso_x_V_ki_gesendet.md").read_text(encoding="utf-8")
    assert "ABCD" not in log and "[BEOBACHTERCODE]" in log
    bericht = (exports / "aavso_x_V_bericht.md").read_text(encoding="utf-8")
    assert "ABCD steht im Kopf" in bericht and "KI-Zweitlesung (unverbindlich; Claude (Cloud)" in bericht          # lokal zurückübersetzt
    assert ns["AI_RESULT"].error == "" and "ABCD steht im Kopf" in ns["AI_RESULT"].text


def test_cloud_cell_is_inert_when_cloud_is_not_enabled(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, enabled=False)
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert "nicht eingeschaltet" in _html(shown) and not any(isinstance(o, widgets.VBox) for o in shown) and not (rec / "stdin.txt").exists()


def test_cloud_cell_skips_when_mode_is_off_or_gemini(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, mode="aus")
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert not (rec / "stdin.txt").exists()
    (tmp_path / "zwei").mkdir()
    ns, shown, rec, exports = _setup(tmp_path / "zwei", monkeypatch, mode="gemini")
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert "Gemini ist noch nicht eingerichtet" in _html(shown)
