"""Prüfstand für die KI-Zweitlesung: misst Fehlalarm- und Übersehensrate (KONZEPT §11.15.9, Modul ``varphot.aieval``).

Aufruf (aus dem Projektordner)::

    uv run python tools/eval_ai_review.py --list                          # Fälle anzeigen, nichts senden
    uv run python tools/eval_ai_review.py --backend claude                # Plan und erste Nachricht zeigen, NICHTS senden
    uv run python tools/eval_ai_review.py --backend claude --run --yes-send-cloud --repeats 2
    uv run python tools/eval_ai_review.py --backend local --run --repeats 3   # lokale KI (verlässt das Heimnetz nicht; ein Aufruf dauert dort bis zu 2,5 Minuten)

``--backend``: ``claude`` oder ``gemini`` (Cloud, braucht ``ai.cloud.enabled`` und Anmeldung wie in NB03) oder ``local`` (wie NB03 „Lokal“). Ohne ``--run`` zeigt das Werkzeug nur den Plan (Zahl der Aufrufe, Anweisung, erster Text anonymisiert wie in NB03) und endet; Cloud
sendet **nur mit ``--run`` und ``--yes-send-cloud``** (Einwilligung für genau diesen Lauf). Der Text ist ein Testbericht (LCO-Testdaten, Code TST01); er läuft trotzdem durch
dieselbe Anonymisierung und dieselbe Prüfung auf Restwerte. ``--rescore DATEI.jsonl`` wertet gespeicherte Antworten mit der aktuellen Wertung neu (kein Aufruf, nichts gesendet). ``--split``: ``measure`` (Standard, die maßgeblichen Fälle), ``tune`` (zum Abstimmen der Anweisung) oder ``all``. ``--repeats``: Wiederholungen je Fall
(ein Modell antwortet nicht jedes Mal gleich). ``--jobs``: gleichzeitige Aufrufe (Standard 1; Cloud-Kontingent beachten).

Ausgabe: je Lauf eine Zeile in ``<out>/ai_eval_<Weg>_<Datum>.jsonl`` (ganze Antwort inklusive) und der Bericht ``….md``; Standardordner ``PHOTOMETRIE_PY_DATA/ai_eval`` (sonst ``./ai_eval``). Rückgabecode 0 = fertig
(oder Plan gezeigt), 3 = Weg nicht verfügbar, 2 = Aufruf falsch.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from varphot import ai_review, choose_backend, detect_backends
from varphot.aieval import build_case, cases, format_report, load_baseline, prompt_id, score_run
from varphot.aireview import detect_cloud_backends, load_ai_config
from varphot.anonymize import AnonymizationError, collect_secrets, prepare_for_cloud
from varphot.observer import data_dir, load_config


def _pick_backend(name: str, cfg: dict):
    if name == "local":
        return choose_backend(detect_backends(cfg))
    kind = {"claude": "claude-cli", "gemini": "gemini-cli"}[name]
    return next((b for b in detect_cloud_backends(cfg) if b.kind == kind), None)


def _rescore(path: Path, facts: dict, body: str) -> int:
    """Wertet gespeicherte Antworten mit der **aktuellen** Wertung neu (ohne Aufruf). Ältere Dateien ohne Feld ``sent``: der Text wird aus den Fällen neu gebaut (Cloud: wie beim Senden anonymisiert)."""
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    by_id = {c.id: c for c in cases("all")}
    cfg = load_ai_config()
    obs, own = load_config()
    runs = []
    for r in rows:
        c = by_id[r["case"]]
        sent = r.get("sent")
        if sent is None:
            cloud = "Cloud" in r.get("backend", "")
            _, msg = build_case(c, facts, body, anon_note=cloud)
            sent = prepare_for_cloud(msg, collect_secrets(obs, own, cfg), max_chars=cfg["cloud"]["max_chars"]).text if cloud else msg
        new = score_run(c, r["answer"], sent, r.get("error", ""), r.get("seconds", 0.0))
        new["repeat"] = r.get("repeat", 0)
        runs.append(new)
    label = rows[0].get("backend", "?") if rows else "?"
    md = path.with_name(path.stem + "_neu.md")
    md.write_text(format_report(label + " (neu gewertet)", rows[0].get("prompt", "?") if rows else "?", runs), encoding="utf-8")
    print(md.read_text(encoding="utf-8"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--backend", choices=["claude", "gemini", "local"])
    ap.add_argument("--split", choices=["measure", "tune", "all"], default="measure")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--list", action="store_true", help="Fälle anzeigen und enden")
    ap.add_argument("--rescore", type=Path, metavar="JSONL", help="gespeicherte Antworten neu werten (nichts senden, kein Aufruf); schreibt <Datei>_neu.md")
    ap.add_argument("--run", action="store_true", help="Aufrufe wirklich ausführen (ohne: nur Plan zeigen)")
    ap.add_argument("--yes-send-cloud", action="store_true", help="zusätzlich bei Cloud: Einwilligung, den Text an den Anbieter zu senden (für diesen Lauf)")
    a = ap.parse_args(argv)

    facts, body = load_baseline()
    cs = cases(a.split)
    if a.list:
        for c in cases("all"):
            print(f"{c.split:8} {c.id:28} {'Kontrolle' if c.is_control else 'Punkt ' + '/'.join(map(str, c.expect)):10} {c.description}")
        return 0
    if a.rescore:
        return _rescore(a.rescore, facts, body)
    if not a.backend:
        ap.error("--backend fehlt (claude, gemini oder local)")
    cfg = load_ai_config()
    bk = _pick_backend(a.backend, cfg)
    if bk is None or not bk.usable:
        print("Weg nicht verfügbar:", bk.detail if bk else "kein lokaler Weg gefunden")
        return 3
    cloud = a.backend != "local"
    obs, own = load_config()
    secrets = collect_secrets(obs, own, cfg) if cloud else []
    jobs = []                                              # (Fall, Wiederholung, Systemanweisung, gesendeter Text)
    try:
        for c in cs:
            system, msg = build_case(c, facts, body, anon_note=cloud)
            sent = prepare_for_cloud(msg, secrets, max_chars=cfg["cloud"]["max_chars"]).text if cloud else msg
            jobs += [(c, r, system, sent) for r in range(a.repeats)]
    except AnonymizationError as e:
        print("Nicht gesendet, Anonymisierung unvollständig:", e)
        return 3
    pid = prompt_id(facts)
    print(f"Weg: {bk.label()} | Gruppe: {a.split} | {len(cs)} Fälle × {a.repeats} = {len(jobs)} Aufrufe | Anweisung {pid} | Text je Aufruf ≈ {len(jobs[0][3])} Zeichen")
    if not a.run or (cloud and not a.yes_send_cloud):
        print("\nNICHTS ausgeführt (nur Plan). Der erste Text" + (" (anonymisiert)" if cloud else "") + " wäre:\n\n" + jobs[0][3] + "\n\nZum Ausführen: --run" + (" --yes-send-cloud" if cloud else ""))
        return 0

    out = a.out or ((data_dir() / "ai_eval") if data_dir().is_dir() else Path("ai_eval"))
    out.mkdir(parents=True, exist_ok=True)
    stem = f"ai_eval_{a.backend}_{datetime.date.today().isoformat()}"
    jsonl = out / f"{stem}.jsonl"
    runs: list[dict] = []

    def one(job):
        c, r, system, sent = job
        res = ai_review(sent, bk, system=system, timeout=a.timeout)
        run = score_run(c, res.text, sent, res.error, res.seconds)
        run["repeat"] = r
        run["sent"] = sent
        return run

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex, open(jsonl, "a", encoding="utf-8") as fh:
        for i, run in enumerate(ex.map(one, jobs), 1):
            runs.append(run)
            fh.write(json.dumps({**run, "backend": bk.label(), "prompt": pid}, ensure_ascii=False) + "\n")
            fh.flush()
            mark = {"ok": ("Treffer" if run.get("detected") else "ÜBERSEHEN") if "detected" in run else ("FEHLALARM" if run.get("false_alarm") else "ok"), "error": "Fehler", "format": "Format"}[run["status"]]
            print(f"[{i}/{len(jobs)}] {run['case']:28} #{run['repeat']} {mark:10} {run['seconds']:5.1f} s  gemeldet: {run.get('flagged', '—')}", flush=True)
    md = out / f"{stem}.md"
    md.write_text(format_report(bk.label(), pid, runs), encoding="utf-8")
    print(f"\nBericht: {md}\nRohdaten: {jsonl}\n")
    print(md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
