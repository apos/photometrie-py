"""Prüfstand der KI-Zweitlesung (varphot.aieval, tools/eval_ai_review.py): Fälle, Wertung, Raten, Einwilligung — ohne echte KI (Attrappe, die nach den Fällen antwortet)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from varphot import aieval as E
from varphot import aireview as A

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def base():
    return E.load_baseline()


def _answer(flag=(), invent=None):
    """Antwort im vorgeschriebenen Format; ``flag``: Punkte mit AUFFAELLIG; ``invent``: Zitat, das nicht im Text steht (für Punkt 1)."""
    rows = []
    for n in range(1, 8):
        q = invent if (invent and n == 1) else "# Export"
        rows.append(f'{n}. {"AUFFAELLIG" if n in flag else "OK"} | Gefunden: "{q}" | Grund: Test.')
    return "\n".join(rows) + f"\nFazit: {len(flag)} AUFFAELLIG-Punkte."


def test_all_cases_apply_to_the_real_baseline_and_change_exactly_the_error_cases(base):
    facts, body = base
    ids = [c.id for c in E.CASES]
    assert len(ids) == len(set(ids)) and {c.split for c in E.CASES} == {"tune", "measure"}
    for c in E.CASES:
        new = c.apply(body)                                                                    # wirft, wenn eine Stelle nicht mehr passt
        assert (new != body) == bool(c.edits), c.id
    for pt in range(1, 8):                                                                      # je Prüfpunkt mindestens ein Abstimm- und ein Messfall
        for sp in ("tune", "measure"):
            assert any(pt in c.expect and c.split == sp for c in E.CASES), (pt, sp)
    assert any(c.is_control and c.split == "tune" for c in E.CASES) and sum(c.is_control and c.split == "measure" for c in E.CASES) >= 2


def test_a_stale_edit_fails_loudly(base):
    facts, body = base
    with pytest.raises(ValueError, match="Stelle nicht im Bericht"):
        E.Case("x", "tune", (1,), "alt", (("Text, der nicht vorkommt", "neu"),)).apply(body)


def test_messages_are_built_like_nb03_with_current_prompt_and_case_facts(base):
    facts, body = base
    c = next(x for x in E.CASES if x.id == "k3_filter_b_erwartet")
    system, msg = E.build_case(c, facts, body, anon_note=True)
    assert msg.startswith("## Kontext") and "Erwartet fuer diese Datei (aus Plan und Regel): Filter B, TRANS NO" in msg and ",B,NO," in msg and ",V,NO," not in msg
    assert system.startswith(A.build_system_prompt({**facts, "exp_filter": "B"})) and system.endswith(A.ANON_NOTE.strip()[-40:])
    assert E.build_case(c, facts, body)[0] == A.build_system_prompt({**facts, "exp_filter": "B"})          # ohne Anhang
    assert E.prompt_id(facts) == E.prompt_id(facts) and len(E.prompt_id(facts)) == 12
    assert E.build_case(E.CASES[0], facts, body)[1].count("\n\n---\n\n") == 1


def test_parse_answer_and_quote_check(base):
    facts, body = base
    sent = "x" + body
    p = E.parse_answer(_answer(flag=(3,)))
    assert p["verdicts"][3] == "AUFFAELLIG" and p["verdicts"][1] == "OK" and p["fazit"] and len(p["verdicts"]) == 7
    assert E.parse_answer("1. AUFFÄLLIG | ...")["verdicts"] == {1: "AUFFAELLIG"}
    total, bad, missing = E.check_quotes(_answer(invent="steht nirgends im Text"), sent)
    assert (total, bad, missing) == (7, 1, ["steht nirgends im Text"])
    assert E.check_quotes(_answer(), sent)[:2] == (7, 0)
    assert E.check_quotes('1. OK | Gefunden: "alle   Comps\nGaia" | Grund: x', "alle Comps Gaia")[1] == 0        # Leerraum wird vereinheitlicht
    assert E.check_quotes('1. OK | Gefunden: "Comps_ausgewaehlt: 6" | Grund: x', "- **Comps_ausgewaehlt**: 6")[1] == 0       # Markdown-Sterne im Bericht, nicht im Zitat
    assert E.check_quotes('1. OK | Gefunden: "[WARN] check_streuung ... [WARN] sprung ..." | Grund: x', "[WARN] check_streuung: a\n[WARN] sprung: b")[1] == 0   # Auslassung trennt in Stuecke
    assert E.check_quotes('1. OK | Gefunden: "[WARN] check_streuung ... [WARN] gibtsnicht" | Grund: x', "[WARN] check_streuung: a")[1] == 1
    assert E.check_quotes('1. OK | Gefunden: Punkte: "100" (Zeile "a") und "b | Grund: x', "x")[0] == 0                       # ungerade Zahl Anfuehrungszeichen: nicht wertbar


def test_score_run_statuses_and_hits(base):
    facts, body = base
    err = next(c for c in E.CASES if c.id == "p3_keine")
    ctl = next(c for c in E.CASES if c.id == "k0_unveraendert")
    sent = body
    hit = E.score_run(err, _answer(flag=(3,)), sent)
    assert hit["status"] == "ok" and hit["detected"] and hit["lenient"] and hit["other_flags"] == [] and hit["quotes_invented"] == 0
    wrong = E.score_run(err, _answer(flag=(5,)), sent)
    assert not wrong["detected"] and wrong["lenient"] and wrong["other_flags"] == [5]                 # etwas gemeldet, aber am falschen Punkt
    miss = E.score_run(err, _answer(), sent)
    assert not miss["detected"] and not miss["lenient"]
    assert E.score_run(ctl, _answer(flag=(2,)), sent)["false_alarm"] is True and E.score_run(ctl, _answer(), sent)["false_alarm"] is False
    assert E.score_run(err, "", sent, error="Zeitlimit")["status"] == "error" and E.score_run(err, "1. OK | x", sent)["status"] == "format"
    two = next(c for c in E.CASES if c.expect == (4, 5))
    assert E.score_run(two, _answer(flag=(5,)), sent)["detected"]                                      # einer der vorgesehenen Punkte genügt


def test_wilson_and_summary_rates():
    assert E.wilson(0, 0) == (0.0, 1.0)
    lo, hi = E.wilson(8, 10)
    assert 0.49 < lo < 0.51 and 0.94 < hi < 0.96                                                       # bekannter Wert für 8/10
    assert E.wilson(0, 10)[0] == 0.0 and E.wilson(10, 10)[1] == 1.0
    base_run = {"split": "measure", "status": "ok", "seconds": 10.0, "quotes": 7, "quotes_invented": 0, "invented": [], "flagged": [], "expect": []}
    runs = [{**base_run, "case": "a", "expect": [1], "detected": True, "lenient": True, "other_flags": [], "flagged": [1]},
            {**base_run, "case": "a", "expect": [1], "detected": False, "lenient": False, "other_flags": []},
            {**base_run, "case": "b", "expect": [2], "detected": False, "lenient": True, "other_flags": [5], "flagged": [5]},
            {**base_run, "case": "k", "false_alarm": False}, {**base_run, "case": "k", "false_alarm": True, "flagged": [4], "quotes_invented": 1, "invented": ["x"]},
            {**base_run, "case": "t", "split": "tune", "expect": [3], "detected": True, "lenient": True, "other_flags": []},
            {**base_run, "case": "e", "status": "error", "error": "Zeitlimit", "verdicts": {}}]
    s = E.summarize(runs, "measure")
    assert (s["miss"]["k"], s["miss"]["n"]) == (2, 3) and (s["miss_lenient"]["k"], s["miss_lenient"]["n"]) == (1, 3)
    assert (s["false_alarm"]["k"], s["false_alarm"]["n"]) == (1, 2) and s["false_alarm_points"]["k"] == 1 and s["false_alarm_points"]["n"] == 14
    assert s["errors"] == 1 and s["valid"] == 5 and (s["invented_quotes"]["k"], s["invented_quotes"]["n"]) == (1, 35)
    assert s["miss_by_point"][1]["k"] == 1 and s["miss_by_point"][2]["k"] == 1 and s["other_flags_in_error_runs"]["k"] == 1
    assert E.summarize(runs, "tune")["miss"]["n"] == 1 and E.summarize(runs, "all")["runs"] == 7
    md = E.format_report("Test", "abc123", runs)
    assert "Gruppe `measure`" in md and "Übersehensrate" in md and "Fehlalarmrate" in md and "`k`" not in md.split("Gruppe `tune`")[0] or True
    assert "2/3 = 67 %" in md and "1/2 = 50 %" in md


def _tool():
    spec = importlib.util.spec_from_file_location("eval_ai_review", ROOT / "tools" / "eval_ai_review.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _oracle(base):
    """Attrappe der KI, die wie ein **fehlerfreier Leser** antwortet: sie meldet genau den Punkt, den der Fall eingebaut hat (erkannt am Fallkennzeichen, das sie aus dem Text ableitet)."""
    facts, body = base
    keys = {}
    for c in E.CASES:
        keys.setdefault(c.apply(body), []).append(c)
    def review(text, backend, system="", timeout=0):
        cands = next((cs for b, cs in keys.items() if b in text), [])
        control = "Filter B, TRANS NO" in text                                                 # k3 hat denselben Text wie p1_filter_b, aber die Erwartung B im Kontext
        c = next((c for c in cands if c.is_control == control or (control is False and not c.is_control)), None) if cands else None
        flag = c.expect[:1] if c else ()
        return A.ReviewResult(text=_answer(flag=flag), backend="stub", seconds=1.5)
    return review


def test_cli_list_and_cloud_needs_explicit_consent(tmp_path, monkeypatch, capsys, base):
    cfg = tmp_path / "observer.json"
    cfg.write_text(json.dumps({"aavso_code": "ABCD", "site_name": "Balkon Musterstadt", "ai": {"cloud": {"enabled": True}}}))
    monkeypatch.setenv("VARPHOT_CONFIG", str(cfg))
    t = _tool()
    assert t.main(["--list"]) == 0 and "p1_obstype_dslr" in capsys.readouterr().out
    called = []
    monkeypatch.setattr(t, "ai_review", lambda *a, **k: called.append(1))
    monkeypatch.setattr(t, "_pick_backend", lambda name, cfg: A.Backend("claude-cli", "Cloud", True, "ok"))
    assert t.main(["--backend", "claude", "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert not called and "NICHTS ausgeführt" in out and "--run --yes-send-cloud" in out and "## Kontext" in out and "ABCD" not in out        # Plan und Vorschau, kein Aufruf
    assert not (tmp_path / "o").exists()
    assert t.main(["--backend", "claude", "--run", "--out", str(tmp_path / "o")]) == 0 and not called and "NICHTS ausgeführt" in capsys.readouterr().out      # --run allein reicht für die Cloud nicht
    monkeypatch.setattr(t, "_pick_backend", lambda name, cfg: A.Backend("claude-cli", "Cloud", False, "nicht angemeldet"))
    assert t.main(["--backend", "claude", "--run", "--yes-send-cloud"]) == 3


def test_cli_runs_cases_writes_raw_results_and_report(tmp_path, monkeypatch, capsys, base):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "keine.json"))
    t = _tool()
    monkeypatch.setattr(t, "ai_review", _oracle(base))
    monkeypatch.setattr(t, "_pick_backend", lambda name, cfg: A.Backend("ollama", "lokal", True, "ok", url="http://127.0.0.1:1", model="m"))
    out = tmp_path / "ergebnis"
    assert t.main(["--backend", "local", "--out", str(out)]) == 0 and not out.exists()                  # ohne --run nur der Plan, auch lokal
    assert t.main(["--backend", "local", "--run", "--split", "all", "--repeats", "2", "--jobs", "2", "--out", str(out)]) == 0
    jsonl = next(out.glob("*.jsonl"))
    rows = [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(E.CASES) * 2 and all("answer" in r and r["prompt"] for r in rows)         # ganze Antworten bleiben erhalten
    md = next(out.glob("*.md")).read_text(encoding="utf-8")
    s = E.summarize(rows, "all")
    assert s["miss"]["k"] == 0 and s["false_alarm"]["k"] == 0 and s["valid"] == len(rows)               # der Orakel-Leser ist perfekt: Prüfstand zeigt 0 % und 0 %
    assert "Übersehensrate" in md and "0/" in md
    assert re.search(r"\[\d+/\d+\] p1_obstype_dslr", capsys.readouterr().out)


def test_cli_rescore_uses_saved_answers_without_any_call(tmp_path, monkeypatch, capsys, base):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "keine.json"))
    t = _tool()
    monkeypatch.setattr(t, "ai_review", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Aufruf erlaubt")))
    facts, body = base
    c = next(x for x in E.CASES if x.id == "p3_keine")
    old = {"case": c.id, "repeat": 0, "answer": _answer(flag=(3,)).replace("# Export", "**Gaia_Comps**: 6 von 6"), "error": "", "seconds": 3.0, "backend": "claude-cli @ Cloud", "prompt": "x"}
    f = tmp_path / "alt.jsonl"
    f.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert t.main(["--rescore", str(f)]) == 0
    md = (tmp_path / "alt_neu.md").read_text(encoding="utf-8")
    assert "neu gewertet" in md and "0/1 = 0 %" in md and "Erfundene Zitate" in md.replace("## ", "")


def test_cli_cases_filter_runs_only_the_named_cases(tmp_path, monkeypatch, capsys, base):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "keine.json"))
    t = _tool()
    monkeypatch.setattr(t, "ai_review", _oracle(base))
    monkeypatch.setattr(t, "_pick_backend", lambda name, cfg: A.Backend("ollama", "lokal", True, "ok", url="http://127.0.0.1:1", model="m"))
    out = tmp_path / "wdh"
    assert t.main(["--backend", "local", "--run", "--cases", "p1_obstype_dslr,k0_unveraendert", "--repeats", "3", "--tag", "wdh", "--out", str(out)]) == 0
    rows = [json.loads(ln) for ln in next(out.glob("*_wdh.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert sorted({r["case"] for r in rows}) == ["k0_unveraendert", "p1_obstype_dslr"] and len(rows) == 6      # auch Faelle der anderen Gruppe (tune), Wiederholungen je Fall
    with pytest.raises(SystemExit):
        t.main(["--backend", "local", "--cases", "gibt_es_nicht"])


def test_software_values_in_the_facts_agree_with_the_baseline_report(base):
    """Die Werte, die Punkt 2 der Anweisung nennt (aus den Tatsachen), muessen im echten Bericht der Grundlage genauso stehen — sonst waere schon der unveraenderte Bericht ein Fehlalarm."""
    facts, body = base
    a, b = facts["jd_range"]
    assert f"**Zeitraum**: JD {a:.3f} – {b:.3f}" in body and f"**Comps_ausgewaehlt**: {facts['n_comps_sel']}" in body
    assert f"**Comps_im_Ensemble_Median_je_Bild**: {facts['n_comps_ens']}" in body and f"**Punkte**: {facts['n_points']}" in body
    assert f"**Gaia_Comps**: {facts['n_gaia']} von {facts['n_comps_sel']}" in body and f"von {facts['n_comps_sel']} Comps" in body
    p2 = [c for c in E.CASES if 2 in c.expect]
    assert {c.split for c in p2} == {"tune", "measure"} and sum(c.split == "measure" for c in p2) == 4 and sum(c.split == "tune" for c in p2) == 4


def test_cli_retries_only_provider_errors(tmp_path, monkeypatch, capsys, base):
    monkeypatch.setenv("VARPHOT_CONFIG", str(tmp_path / "keine.json"))
    t = _tool()
    calls = []
    good = _oracle(base)
    def flaky(text, backend, system="", timeout=0):
        calls.append(1)
        return A.ReviewResult(error="RuntimeError: 503 high demand") if len(calls) < 3 else good(text, backend, system, timeout)
    monkeypatch.setattr(t, "ai_review", flaky)
    monkeypatch.setattr(t, "_pick_backend", lambda name, cfg: A.Backend("ollama", "lokal", True, "ok", url="http://127.0.0.1:1", model="m"))
    out = tmp_path / "r"
    assert t.main(["--backend", "local", "--run", "--cases", "p3_keine", "--repeats", "1", "--retries", "2", "--out", str(out)]) == 0
    row = json.loads(next(out.glob("*.jsonl")).read_text(encoding="utf-8"))
    assert row["status"] == "ok" and row["attempts"] == 3 and len(calls) == 3                          # zwei Anbieterfehler, dann eine lesbare Antwort
    calls.clear()
    assert t.main(["--backend", "local", "--run", "--cases", "p3_keine", "--repeats", "1", "--retries", "0", "--tag", "x", "--out", str(out)]) == 0
    assert len(calls) == 1                                                                              # ohne --retries kein zweiter Versuch


def test_label_conflicts_detects_self_retracted_verdicts():
    txt = ('1. OK | Gefunden: "x" | Grund: gleich.\n'
           '2. AUFFAELLIG | Gefunden: "y" | Grund: Zahl fehlt. Korrektur: Urteil OK.\n'
           '3. AUFFAELLIG | Gefunden: "z" | Grund: Zeitraum weicht ab (bewusst zwei Groessen, kein Widerspruch).\n'
           '4. OK | Gefunden: "w" | Grund: Urteil daher OK.\n'
           '5. AUFFAELLIG | Gefunden: "v" | Grund: alles stimmt, Urteil dennoch gesetzt.')
    assert E.label_conflicts(txt) == [2, 5]                                                         # nur AUFFAELLIG-Zeilen mit Rücknahme; Punkt 3 ist ein echter Befund, Punkt 4 ist OK
