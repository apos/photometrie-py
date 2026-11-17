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
    gexe = exe.parent / "gemini"                                                                   # Attrappe der Gemini-Kommandozeile
    gexe.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$@\" > \"{rec}/gargv.txt\"\ncat > \"{rec}/gstdin.txt\"\ncp \"$GEMINI_SYSTEM_MD\" \"{rec}/gsystem.md\"\n"
                    "echo '7. [BEOBACHTERCODE] steht im Kopf (Gemini).'\n")
    gexe.chmod(0o755)
    (tmp_path / "ghome" / ".gemini").mkdir(parents=True)
    (tmp_path / "ghome" / ".gemini" / ".env").write_text("GEMINI_API_KEY=testschluessel\n")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "ghome"))
    monkeypatch.setenv("GEMINI_API_KEY", "")
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
          "w_ai": SimpleNamespace(value=mode), "w_mode": SimpleNamespace(value="untransformiert"),
          "PLAN": SimpleNamespace(method="mono", camera_model="QHY268M", aavso_filter="V", obstype="CCD"), "MODE_T": False, "BAND": "V", "FILT": "V", "OBSTYPE": "CCD",
          "OBSTYPE_UNCONFIRMED": False, "IS_TESTDATA": True, "DATA": __import__("pandas").DataFrame({"jd_mid": [2458802.65, 2458858.55]}), "today": "2026-11-17", "OBSV": [1, 2], "comps": [1, 2, 3], "N_ENS": 3, "n_gaia": 0, "CHART": "X43370IPN"}
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
    assert "zweite Leserin" in argv and "HINWEIS: Der Text ist anonymisiert" in argv                  # Systemprompt mit Platzhalter-Hinweis
    log = (exports / "aavso_x_V_ki_gesendet.md").read_text(encoding="utf-8")
    assert "ABCD" not in log and "[BEOBACHTERCODE]" in log
    bericht = (exports / "aavso_x_V_bericht.md").read_text(encoding="utf-8")
    assert "ABCD steht im Kopf" in bericht and "KI-Zweitlesung (unverbindlich; Claude (Cloud)" in bericht          # lokal zurückübersetzt
    assert ns["AI_RESULT"].error == "" and "ABCD steht im Kopf" in ns["AI_RESULT"].text


def test_cloud_cell_is_inert_when_cloud_is_not_enabled(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, enabled=False)
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert "nicht eingeschaltet" in _html(shown) and not any(isinstance(o, widgets.VBox) for o in shown) and not (rec / "stdin.txt").exists()


def test_cloud_cell_skips_when_mode_is_off(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, mode="aus")
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert not (rec / "stdin.txt").exists() and not (rec / "gstdin.txt").exists()


def test_cloud_cell_gemini_preview_confirmation_send_and_restore(tmp_path, monkeypatch):
    """Gemini wie Claude: Vorschau (mit Hinweis zur Datennutzung), nichts ohne Bestaetigung, dann anonymisiert gesendet und lokal zurueckuebersetzt."""
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, mode="gemini")
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    html = _html(shown)
    assert "Anbieter: Gemini" in html and "Datennutzung bei Google" in html and "ABCD" not in html and "Musterstadt" not in html
    ok, go, out = next(o for o in shown if isinstance(o, widgets.VBox)).children
    assert "Gemini" in go.description and not (rec / "gstdin.txt").exists()
    go.click()                                                                                 # ohne Bestaetigung
    assert not (rec / "gstdin.txt").exists() and not (exports / "aavso_x_V_ki_gesendet.md").exists()
    ok.value = True
    go.click()
    sent = (rec / "gstdin.txt").read_text()
    assert sent.startswith("## Kontext") and "ABCD" not in sent and "Musterstadt" not in sent and "[BEOBACHTERCODE]" in sent
    assert not (rec / "stdin.txt").exists()                                                    # Claude wurde nicht aufgerufen
    system = (rec / "gsystem.md").read_text()
    assert "Kein Urteil ohne woertliches Zitat" in system and "HINWEIS: Der Text ist anonymisiert" in system
    assert "ABCD" not in (exports / "aavso_x_V_ki_gesendet.md").read_text(encoding="utf-8")
    bericht = (exports / "aavso_x_V_bericht.md").read_text(encoding="utf-8")
    assert "ABCD steht im Kopf (Gemini)" in bericht and "KI-Zweitlesung (unverbindlich; Gemini (Cloud)" in bericht
    assert ns["AI_RESULT"].error == "" and "ABCD steht im Kopf" in ns["AI_RESULT"].text


def test_cloud_cell_gemini_without_login_is_not_available(tmp_path, monkeypatch):
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch, mode="gemini")
    (tmp_path / "ghome" / ".gemini" / ".env").unlink()
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    assert "Gemini ist nicht verfügbar" in _html(shown) and "keine Anmeldung" in _html(shown) and not any(isinstance(o, widgets.VBox) for o in shown)


def test_form_offers_gemini_with_state(tmp_path, monkeypatch):
    """Das Auswahlfeld nennt Gemini mit seinem Zustand (nicht mehr "noch nicht eingerichtet")."""
    src = _cell("from varphot import nbui as ui\nimport os, json, datetime")
    assert "noch nicht eingerichtet" not in src and '_cl["gemini-cli"]' in src


def test_cloud_cell_sends_context_and_case_specific_system_prompt(tmp_path, monkeypatch):
    """Der Text beginnt mit dem Kontext (Erwartung, Absicht), die Systemanweisung hat die zusammengestellten Pruefpunkte."""
    ns, shown, rec, exports = _setup(tmp_path, monkeypatch)
    exec(compile(_cell("from varphot import detect_backends"), "nb03[13]", "exec"), ns)
    ok, go, out = next(o for o in shown if isinstance(o, widgets.VBox)).children
    ok.value = True
    go.click()
    sent = (rec / "stdin.txt").read_text()
    argv = (rec / "argv.txt").read_text()
    assert sent.startswith("## Kontext") and "Filter V, TRANS NO, OBSTYPE CCD" in sent and "QHY268M" in sent
    assert "Kein Urteil ohne woertliches Zitat" in argv and "Testkennzeichnung" in argv and "[BEOBACHTERCODE]" in argv        # Prüfpunkte, Testfall, Anonymisierungshinweis
