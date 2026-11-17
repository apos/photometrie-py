"""Prüfstand für die KI-Zweitlesung: Fehlalarm- und Übersehensrate messen (KONZEPT §11.15.9).

Autor: Axel Pospischil. Stand 2026-11-17.

Warum: Ein sauberer Bericht, an dem die KI nichts findet (Lauf vom 2026-11-17: Claude und Gemini je 7 × OK), zeigt **nicht**, ob sie Fehler findet. Gemessen werden zwei Raten:

* **Übersehensrate** (miss rate): Anteil der Läufe, in denen ein **eingebauter** Fehler nicht als AUFFAELLIG am dafür vorgesehenen Prüfpunkt erscheint.
* **Fehlalarmrate** (false alarm rate): Anteil der Läufe an **fehlerfreien** Berichten (Kontrollfälle), in denen mindestens ein Punkt AUFFAELLIG ist.

Wie: Grundlage ist der echte Bericht eines Laufs (``tests/data/ai_eval/baseline_body.md``, Tatsachen in ``baseline_facts.json``). Daraus entstehen Fälle (:data:`CASES`): je Prüfpunkt der
Systemanweisung ein oder mehrere eingebaute Fehler (genau definierte Textersetzungen), dazu Kontrollfälle ohne Fehler (unverändert, harmlos geändert, gleichmäßig auf einen anderen Filter
umgestellt samt Erwartung). Die Nachricht wird wie in NB03 aus ``build_context`` und dem Bericht gebaut, die Systemanweisung aus ``build_system_prompt`` — gemessen wird also die **jeweils
aktuelle** Anweisung. Ausgewertet wird nur, was die Antwort selbst hergibt: Urteilszeilen ``<Nr>. OK|AUFFAELLIG|NICHT_PRUEFBAR``, das wörtliche Zitat (kommt es im gesendeten Text wirklich vor?),
Dauer. Wer Fehler einbaut, kennt die richtige Antwort; die Bewertung ist daher ein Textvergleich, keine zweite KI.

**Abstimmen und Messen getrennt** (sonst misst man, wie gut man auf die eigenen Fälle abgestimmt hat): Jeder Fall gehört zu ``tune`` oder ``measure``. Die Anweisung wird nur gegen ``tune``
verbessert; die berichteten Zahlen sind die der ``measure``-Fälle. Nach jeder Änderung an Anweisung oder Kontext die Messung wiederholen und beide Zahlen nennen.

Grenzen: Wenige Fälle (siehe :func:`summarize`, Wilson-Intervall); die Fehler sind künstlich und eindeutig — echte Fehler sind oft unschärfer, die gemessene Übersehensrate ist daher eher eine
**untere** Schranke. Ein Fehler wird als erkannt gezählt, wenn der **vorgesehene** Punkt AUFFAELLIG meldet (streng); ``lenient`` zählt jede Auffälligkeit. Läufe mit Fehler des Anbieters oder ohne
lesbares Format zählen in keiner Rate, werden aber ausgewiesen. Die Zahlen gelten für einen Anbieter, ein Modell und einen Tag.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .aireview import build_context, build_system_prompt

DATA_DIR = Path(__file__).resolve().parents[1] / "tests" / "data" / "ai_eval"
N_POINTS = 7                                         # Prüfpunkte der Grundlage (Testdaten, untransformiert, Mono)
VERDICT_RE = re.compile(r"^\s*(\d+)\.\s*(OK|AUFF(?:AE|Ä)LLIG|NICHT_PR(?:UE|Ü)FBAR)\b", re.M)
QUOTES_RE = re.compile(r"Gefunden:\s*(.*?)(?:\|\s*Grund:|$)", re.S)


def load_baseline(data_dir: Path | None = None) -> tuple[dict, str]:
    """Tatsachen (``baseline_facts.json``) und Berichtskörper (``baseline_body.md``) des echten Laufs."""
    d = data_dir or DATA_DIR
    facts = json.loads((d / "baseline_facts.json").read_text(encoding="utf-8"))
    facts["jd_range"] = tuple(facts["jd_range"])
    return facts, (d / "baseline_body.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Fälle
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_OFFSET = "Check-Stern im Mittel 9.317 mag, Katalog 9.423 (Differenz -0.106, Schwelle 0.05 mag) — Vergleichssterne/Nullpunkt pruefen"
_STREU = "Check-Stern streut mit 0.056 mag (> 0.05) — Photometrie/Comps pruefen"
_SPRUNG = "- [WARN] sprung: 5 Sprung/Spruenge > 0.3 mag innerhalb 10 min, groesster 0.39 mag (Ausreisser?)\n"
_REIFE = "## Reifegrad der benutzten Funktionen (Stand der Software, unabhängig davon, ob diese Datei Testdaten enthält)"


@dataclass(frozen=True)
class Case:
    """Ein Prüffall. ``expect``: Punkte, an denen der Fehler erscheinen soll (leer = Kontrollfall ohne Fehler); ``edits``: ``(alt, neu)``-Ersetzungen, jede an **allen** Stellen;
    ``facts``: Änderungen der Tatsachen (Erwartung) für Kontrollfälle, die eine Erwartung mitändern."""
    id: str
    split: str                                   # "tune" oder "measure"
    expect: tuple[int, ...]
    description: str
    edits: tuple[tuple[str, str], ...] = ()
    facts: dict = field(default_factory=dict)

    @property
    def is_control(self) -> bool:
        return not self.expect

    def apply(self, body: str) -> str:
        """Bericht mit eingebautem Fehler; wirft ``ValueError``, wenn eine Ersetzung nicht mehr zur Grundlage passt (die Fälle veralten nie stillschweigend)."""
        for old, new in self.edits:
            if old not in body:
                raise ValueError(f"Fall {self.id}: Stelle nicht im Bericht: {old[:60]!r}")
            body = body.replace(old, new)
        return body


CASES: tuple[Case, ...] = (
    # ---- Punkt 1: Filter / TRANS / OBSTYPE gegen die Erwartung
    Case("p1_obstype_dslr", "tune", (1,), "OBSTYPE DSLR statt erwartet CCD (Kopf und Bericht)", (("#OBSTYPE=CCD", "#OBSTYPE=DSLR"), ("- **OBSTYPE**: CCD", "- **OBSTYPE**: DSLR"))),
    Case("p1_filter_b", "measure", (1,), "Filter B statt erwartet V (Datenzeilen und Bericht)", ((",V,NO,", ",B,NO,"), ("- **Filter**: V", "- **Filter**: B"))),
    Case("p1_trans_yes", "measure", (1,), "TRANS YES statt erwartet NO (Datenzeilen und Bericht)", ((",V,NO,", ",V,YES,"), ("- **TRANS**: NO", "- **TRANS**: YES"))),
    # ---- Punkt 2: dieselbe Zahl, zwei Werte
    Case("p2_zeitraum", "tune", (2,), "Zeitraum im Bericht beginnt 10 Tage nach der ersten Datenzeile", (("JD 2458802.651 –", "JD 2458812.651 –"),)),
    Case("p2_comps_ausgewaehlt", "measure", (2,), "Bericht nennt 7 ausgewählte Comps, die NOTES und Gaia_Comps 'von 6'", (("- **Comps_ausgewaehlt**: 6", "- **Comps_ausgewaehlt**: 7"),)),
    Case("p2_comps_gesamt", "measure", (2,), "NOTES nennen 8 Comps, der Bericht 6", (("Ensemble 5 von 6 Comps", "Ensemble 5 von 8 Comps"),)),
    # ---- Punkt 3: Mengenwort gegen Zahl
    Case("p3_keine", "tune", (3,), "'keine Comps Gaia-abgeleitet' bei 6 von 6", (("alle Comps Gaia-abgeleitet", "keine Comps Gaia-abgeleitet"),)),
    Case("p3_teils", "measure", (3,), "'teils Gaia-abgeleitet' bei 6 von 6", (("alle Comps Gaia-abgeleitet", "teils Gaia-abgeleitet"),)),
    # ---- Punkt 4: Überschrift gegen Inhalt
    Case("p4_ueberschrift", "tune", (4,), "Überschrift 'einige Funktionen nicht an echten Daten geprüft' über 'Alle … geprüft'", ((_REIFE, "## Reifegrad: einige benutzte Funktionen sind nicht an echten Daten geprüft"),)),
    Case("p4_keine_offenen", "measure", (4, 5), "Überschrift 'Keine offenen Punkte' über drei Warnungen", (("## Offene Punkte (vor dem Einreichen entscheiden)", "## Keine offenen Punkte"),)),
    # ---- Punkt 5: Warnungen vollständig
    Case("p5_warnung_fehlt", "tune", (5,), "Sprung-Warnung steht nicht unter 'Offene Punkte'", ((_SPRUNG, ""),)),
    Case("p5_warnungen_keine", "measure", (5,), "'Warnungen: keine' obwohl Punkte aufgelistet sind", (("Warnungen: 6 von 6 Comps Gaia-abgeleitet → keine AAVSO-Sequenz-ID; als Notbehelf kennzeichnen", "Warnungen: keine"),)),
    Case("p5_offset_fehlt", "measure", (5,), "check_offset steht nicht unter 'Offene Punkte'", (("- [WARN] check_offset: " + _OFFSET + "\n- [WARN] sprung", "- [WARN] sprung"),)),
    # ---- Punkt 6: Verständlichkeit (Wert und Schwelle)
    Case("p6_ohne_wert", "tune", (6,), "check_offset ohne Wert und Schwelle (Bericht und feste Prüfung gleich)", (("check_offset: " + _OFFSET, "check_offset: Abweichung — pruefen"),)),
    Case("p6_ohne_schwelle", "measure", (6,), "check_streuung ohne Wert und Schwelle (Bericht und feste Prüfung gleich)", (("check_streuung: " + _STREU, "check_streuung: Check-Stern streut zu stark — Photometrie/Comps pruefen"),)),
    # ---- Punkt 7: Testkennzeichnung
    Case("p7_kennzeichnung_fehlt", "tune", (7,), "Zeile '# TESTDATEN - NICHT EINREICHEN' fehlt im Kopf", (("# TESTDATEN - NICHT EINREICHEN\n", ""),)),
    Case("p7_kennzeichnung_umgedeutet", "measure", (7,), "Zeile im Kopf lautet '# Daten zur Einreichung'", (("# TESTDATEN - NICHT EINREICHEN\n", "# Daten zur Einreichung\n"),)),
    # ---- Kontrollfälle: kein Fehler, jede Auffälligkeit ist ein Fehlalarm
    Case("k0_unveraendert", "tune", (), "unveränderter Bericht"),
    Case("k1_fehlerwert", "tune", (), "mittlerer Fehler 0.071 statt 0.067 (nicht gegenprüfbar)", (("- **mittlerer_Fehler_mag**: 0.067", "- **mittlerer_Fehler_mag**: 0.071"),)),
    Case("k0_unveraendert_m", "measure", (), "unveränderter Bericht (zweiter Satz, getrennte Wertung)"),
    Case("k2_fehlerwert", "measure", (), "mittlerer Fehler 0.058 statt 0.067 (nicht gegenprüfbar)", (("- **mittlerer_Fehler_mag**: 0.067", "- **mittlerer_Fehler_mag**: 0.058"),)),
    Case("k3_filter_b_erwartet", "measure", (), "Filter B überall und als Erwartung (gleichmäßig, kein Widerspruch)", ((",V,NO,", ",B,NO,"), ("- **Filter**: V", "- **Filter**: B")), {"exp_filter": "B"}),
)


def cases(split: str = "all") -> list[Case]:
    """Fälle einer Gruppe (``tune``, ``measure`` oder ``all``)."""
    return [c for c in CASES if split in ("all", c.split)]


def build_case(case: Case, facts: dict, body: str, anon_note: bool = False) -> tuple[str, str]:
    """``(Systemanweisung, Nachricht)`` für einen Fall — gebaut wie in NB03 (``anon_note``: Anhang für anonymisierten Text, wie beim Cloud-Weg)."""
    from .aireview import ANON_NOTE
    f = {**facts, **case.facts}
    system = build_system_prompt(f) + (ANON_NOTE if anon_note else "")
    return system, build_context(f) + "\n\n---\n\n" + case.apply(body)


def prompt_id(facts: dict) -> str:
    """Kurze Kennung (Hash) von Systemanweisung und Kontext für die Tatsachen der Grundlage — zeigt, ob zwei Messungen dieselbe Anweisung benutzten."""
    h = hashlib.sha256((build_system_prompt(facts) + build_context(facts)).encode("utf-8")).hexdigest()
    return h[:12]


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Auswertung einer Antwort
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_answer(text: str) -> dict:
    """Urteile je Punkt, Zahl der Zitate und der **nicht im Text vorkommenden** Zitate liefert :func:`score_run`; hier nur das Lesen: ``{Nr: Urteil}`` (AUFFAELLIG normalisiert) und Fazit-Zeile."""
    verdicts = {}
    for m in VERDICT_RE.finditer(text or ""):
        v = m.group(2).upper().replace("Ä", "AE").replace("Ü", "UE")
        verdicts.setdefault(int(m.group(1)), v)
    return {"verdicts": verdicts, "fazit": bool(re.search(r"^\s*Fazit\s*:", text or "", re.M | re.I))}


_ELLIPSIS = re.compile(r"\.{3}|…")


def _clean_quote_text(s: str) -> str:
    """Zitat und gesendeter Text werden vor dem Vergleich gleich behandelt: Markdown-Zeichen (``**``, Backticks) entfallen, Leerraum wird vereinheitlicht."""
    return _norm(s.replace("**", "").replace("`", ""))


def check_quotes(text: str, sent: str) -> tuple[int, int, list[str]]:
    """``(Zahl der Zitate, Zahl der erfundenen, Liste der erfundenen)``: ein Zitat zählt als erfunden, wenn ein Stück davon **nicht wörtlich** im gesendeten Text steht.

    Gezählt werden die in Anführungszeichen stehenden Stücke von ``Gefunden:`` bis ``Grund:``. Gleich behandelt werden Markdown-Zeichen (``**`` im Bericht, das die KI beim Zitieren weglässt) und Leerraum;
    Auslassungen (``...`` oder ``…`` im Zitat) trennen das Zitat in Stücke, jedes Stück muss vorkommen. Stücke unter 3 Zeichen zählen nicht. Zeilen mit **ungerader** Zahl gerader Anführungszeichen (verschachtelt,
    nicht sauber paarbar) werden nicht gewertet — sonst entstünden Scheinzitate aus den Lücken zwischen den Zitaten. Erster Lauf 2026-11-17 mit der strengen Fassung: 33 % „erfunden“, fast alles Artefakt dieser Fälle."""
    sent_n = _clean_quote_text(sent)
    total, missing = 0, []
    for ln in (text or "").splitlines():
        m = QUOTES_RE.search(ln)
        if not m or m.group(1).count('"') % 2:
            continue
        for q in re.findall(r'"([^"]{3,}?)"', m.group(1)):
            total += 1
            parts = [p.strip(" ,;") for p in _ELLIPSIS.split(_clean_quote_text(q))]
            if any(len(p) >= 3 and p not in sent_n for p in parts):
                missing.append(q)
    return total, len(missing), missing


def score_run(case: Case, answer: str, sent: str, error: str = "", seconds: float = 0.0) -> dict:
    """Wertung eines Laufs. ``status``: ``ok`` (lesbar), ``error`` (Anbieterfehler) oder ``format`` (weniger Urteile als Prüfpunkte). Nur ``ok`` zählt in den Raten."""
    run = {"case": case.id, "split": case.split, "expect": list(case.expect), "seconds": seconds, "error": error, "answer": answer}
    if error or not answer:
        return {**run, "status": "error", "verdicts": {}}
    p = parse_answer(answer)
    run.update(verdicts=p["verdicts"], fazit=p["fazit"])
    if len(p["verdicts"]) < N_POINTS:
        return {**run, "status": "format"}
    flagged = sorted(n for n, v in p["verdicts"].items() if v == "AUFFAELLIG")
    total, bad, missing = check_quotes(answer, sent)
    run.update(status="ok", flagged=flagged, unchecked=sorted(n for n, v in p["verdicts"].items() if v == "NICHT_PRUEFBAR"), quotes=total, quotes_invented=bad, invented=missing)
    if case.is_control:
        run["false_alarm"] = bool(flagged)
    else:
        run["detected"] = any(n in flagged for n in case.expect)
        run["lenient"] = bool(flagged)
        run["other_flags"] = [n for n in flagged if n not in case.expect]
    return run


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Zusammenfassung
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95-%-Wilson-Intervall für einen Anteil ``k`` von ``n`` (bei kleinen Stichproben ehrlicher als ``k/n ± …``); ``n = 0`` → ``(0, 1)``."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def summarize(runs: list[dict], split: str = "measure") -> dict:
    """Raten für eine Gruppe von Läufen (``split`` ``measure``, ``tune`` oder ``all``).

    ``miss``: Übersehensrate streng (vorgesehener Punkt nicht AUFFAELLIG) und ``miss_lenient`` (gar nichts gemeldet); ``false_alarm``: Anteil der Kontrollläufe mit mindestens einer Auffälligkeit;
    ``invented_quotes``: Anteil erfundener Zitate; je Prüfpunkt und je Fall die Einzelwerte. Jeweils ``(k, n, Anteil, (unten, oben))``."""
    rs = [r for r in runs if split in ("all", r["split"])]
    ok = [r for r in rs if r["status"] == "ok"]
    err = [r for r in ok if "detected" in r]
    ctl = [r for r in ok if "false_alarm" in r]

    def rate(k, n):
        return {"k": k, "n": n, "rate": (k / n if n else None), "ci95": wilson(k, n)}
    per_point, per_case = {}, {}
    for r in err:
        for pt in r["expect"]:
            d = per_point.setdefault(pt, [0, 0])
            d[0] += 0 if r["detected"] else 1
            d[1] += 1
    for r in ok:
        d = per_case.setdefault(r["case"], [0, 0])
        d[1] += 1
        d[0] += 0 if r.get("detected", r.get("false_alarm") is False) else 1
    q_all = sum(r["quotes"] for r in ok)
    return {"split": split, "runs": len(rs), "valid": len(ok), "errors": sum(r["status"] == "error" for r in rs), "format": sum(r["status"] == "format" for r in rs),
            "miss": rate(sum(not r["detected"] for r in err), len(err)), "miss_lenient": rate(sum(not r["lenient"] for r in err), len(err)),
            "false_alarm": rate(sum(r["false_alarm"] for r in ctl), len(ctl)),
            "false_alarm_points": rate(sum(len(r["flagged"]) for r in ctl), N_POINTS * len(ctl)),
            "other_flags_in_error_runs": rate(sum(bool(r["other_flags"]) for r in err), len(err)),
            "invented_quotes": rate(sum(r["quotes_invented"] for r in ok), q_all),
            "seconds_mean": (sum(r["seconds"] for r in rs) / len(rs) if rs else None),
            "miss_by_point": {pt: rate(k, n) for pt, (k, n) in sorted(per_point.items())},
            "wrong_by_case": {c: rate(k, n) for c, (k, n) in sorted(per_case.items())}}


def format_report(label: str, pid: str, runs: list[dict]) -> str:
    """Bericht als Markdown: Kopf (Anbieter/Modell, Anweisungskennung), Zahlen für ``measure`` und ``tune``, Fälle mit Fehlern, erfundene Zitate."""
    def pct(r):
        return "—" if r["rate"] is None else f"{r['k']}/{r['n']} = {100 * r['rate']:.0f} % (95-%-Intervall {100 * r['ci95'][0]:.0f}–{100 * r['ci95'][1]:.0f} %)"
    out = [f"# Prüfstand KI-Zweitlesung — {label}", "", f"Anweisung (Hash): `{pid}`. Läufe: {len(runs)}. **Maßgeblich sind die Zahlen der Gruppe `measure`** (die Anweisung wurde nur gegen `tune` abgestimmt).", ""]
    for split in ("measure", "tune"):
        s = summarize(runs, split)
        out += [f"## Gruppe `{split}` ({s['valid']} gültige von {s['runs']} Läufen; Anbieterfehler {s['errors']}, Format {s['format']})", "",
                f"- **Übersehensrate** (Fehler am vorgesehenen Punkt nicht gemeldet): {pct(s['miss'])}",
                f"- Übersehen, wenn **gar nichts** gemeldet wurde: {pct(s['miss_lenient'])}",
                f"- **Fehlalarmrate** (Kontrollläufe mit mindestens einer Auffälligkeit): {pct(s['false_alarm'])}",
                f"- Fehlalarme je Urteil (Kontrollläufe): {pct(s['false_alarm_points'])}",
                f"- Fehlerläufe mit zusätzlichen Meldungen an anderen Punkten: {pct(s['other_flags_in_error_runs'])}",
                f"- Erfundene Zitate (stehen nicht wörtlich im Text): {pct(s['invented_quotes'])}",
                f"- mittlere Dauer: {s['seconds_mean']:.1f} s" if s["seconds_mean"] is not None else "- mittlere Dauer: —", ""]
        if s["miss_by_point"]:
            out += ["Übersehen je Prüfpunkt: " + "; ".join(f"Punkt {p}: {v['k']}/{v['n']}" for p, v in s["miss_by_point"].items()), ""]
        bad = {c: v for c, v in s["wrong_by_case"].items() if v["k"]}
        if bad:
            out += ["Fälle mit falscher Antwort: " + "; ".join(f"`{c}` {v['k']}/{v['n']}" for c, v in bad.items()), ""]
    inv = [(r["case"], q) for r in runs if r["status"] == "ok" for q in r["invented"]]
    if inv:
        out += ["## Erfundene Zitate", ""] + [f"- `{c}`: „{q}“" for c, q in inv[:20]] + [""]
    return "\n".join(out) + "\n"
