"""Bereitschaft vor der Beobachtung: Software (Python, Pakete, ASTAP, Siril, Datenordner, KI) und Planungsgrundlagen (Kameraprofil NB07, Transformation NB08, Standardfelder).

Autor: Axel Pospischil. Stand 2026-11-10 (NB00 Schritt 0 und 2b, NB01 Vorbedingungen).

Warum: Die Pruefung der Vorbedingungen stand nur in NB01; NB00 ist aber der erste Einstieg (Planung vor der Aufnahme) und braucht dieselben Programme. Ausserdem wusste der Plan nicht, ob ein gemessenes
Kameraprofil (NB07) oder Transformationskoeffizienten (NB08) vorliegen und welches Standardfeld am Beobachtungsort ueberhaupt sichtbar ist. Beides zeigt dieses Modul **vor** der Aufnahmenacht, mit Hinweis,
welches Notebook den fehlenden Teil liefert. Nichts hier blockiert: fehlende optionale Teile sind Hinweise, ``ok=False`` ohne ``optional`` ist ein echtes Hindernis.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGES = [("numpy", "numpy"), ("scipy", "scipy"), ("pandas", "pandas"), ("matplotlib", "matplotlib"), ("astropy", "astropy"), ("photutils", "photutils"), ("astroquery", "astroquery"),
            ("requests", "requests"), ("ipywidgets", "ipywidgets"), ("ipyfilechooser", "ipyfilechooser")]
ASTAP_PATHS = ["/Applications/ASTAP.app/Contents/MacOS/astap", "/opt/astap/astap", "/usr/bin/astap", "/usr/local/bin/astap"]
SIRIL_PATHS = ["/Applications/Siril.app/Contents/MacOS/siril", "/usr/bin/siril", "/usr/local/bin/siril"]
MIN_PYTHON = (3, 12)


@dataclass
class Check:
    """Eine Zeile der Bereitschaftstabelle: ``ok``, ``optional`` (Fehlen ist kein Hindernis) und ``detail`` (was fehlt, welches Notebook hilft)."""
    label: str
    ok: bool
    detail: str = ""
    optional: bool = False


def find_program(paths: list[str], name: str) -> str | None:
    """Erster vorhandener Pfad aus ``paths``, sonst ``shutil.which(name)``; ``None`` wenn nichts gefunden."""
    return next((p for p in paths if Path(p).exists()), None) or shutil.which(name)


def software_checks(ai: bool = True) -> list[Check]:
    """Python-Version, Pakete (mit Version), ASTAP, Siril, Datenordner, ``observer.json`` (Standort, Beobachtercode) und die KI-Wege (optional).

    Warum/Wie: dieselben Pruefungen wie bisher in NB01, ergaenzt um Python-Version (>= 3.12), ``photutils``/``scipy``/``pandas`` (Kernpakete), Datenordner und ``observer.json``; ASTAP ist fuer echte Bilder noetig,
    Siril optional. Grenzen: prueft nur, ob etwas **da** ist, nicht ob es funktioniert (ASTAP-Sterndatenbank, Siril-Version). Validierung: ``tests/test_readiness.py``.
    """
    from . import __version__
    from .observer import config_path, data_dir, load_config
    out = [Check("Python", sys.version_info >= MIN_PYTHON, f"{sys.version.split()[0]}  —  {sys.executable}" + ("" if sys.version_info >= MIN_PYTHON else f"  (benoetigt >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})")),
           Check("varphot", True, __version__)]
    for label, mod in PACKAGES:
        try:
            out.append(Check(f"Paket {label}", True, getattr(importlib.import_module(mod), "__version__", "?")))
        except ImportError:
            out.append(Check(f"Paket {label}", False, f"nicht installiert — pip install {label}"))
    for name, paths, exe, hint in (("ASTAP", ASTAP_PATHS, "astap", "noetig fuer Plate-Solving echter Bilder (NB02)"), ("Siril", SIRIL_PATHS, "siril", "optional: Kalibrierung (NB01), Kanaltrennung")):
        found = find_program(paths, exe)
        out.append(Check(f"Programm {name}", found is not None, found or f"nicht gefunden ({hint})", optional=name == "Siril"))
    dd = data_dir()
    out.append(Check("Datenordner", dd.is_dir(), str(dd) if dd.is_dir() else f"{dd} fehlt (Messdaten, Plaene, Beobachter liegen sonst in ~/.config/varphot)", optional=True))
    cp = config_path()
    if cp.exists():
        obs, sites = load_config()
        out.append(Check("Beobachter (observer.json)", bool(obs.site_name), f"Standort '{obs.site_name or '—'}', AAVSO-Code {obs.aavso_code or '— (nur zum Einreichen noetig)'}" + ("" if obs.site_name else " — NB00 Schritt 0b ausfuellen"), optional=True))
    else:
        out.append(Check("Beobachter (observer.json)", False, f"{cp} fehlt — NB00 Schritt 0b ausfuellen (Standort, Kamera)", optional=True))
    if ai:
        try:
            from .aireview import detect_backends, preflight_lines
            out += [Check(*row, optional=True) for row in preflight_lines(detect_backends())]
        except Exception as e:                       # nie die Pruefung der Software blockieren
            out.append(Check("KI-Zweitlesung", False, f"Pruefung fehlgeschlagen: {type(e).__name__}: {e}", optional=True))
    return out


def camera_readiness(cam, method: str, model: str, setting: str) -> list[Check]:
    """Status des Kameraprofils (NB07) und der Transformation (NB08) fuer die geplante Kamera und Methode.

    Wie: NB07 gilt als ausgefuehrt, wenn das Profil Gain **und** Linearitaetsobergrenze enthaelt (``cam.gain_e_per_adu``, ``cam.linear_max_adu``). NB08 wird nur bei Farbmethoden gebraucht (``osc``, ``dslr``,
    ``monorgb``): vorhanden, wenn ``transform_<Modell>_<Einstellung>.json`` existiert (:func:`varphot.transform.solution_path`); Alter und Guetetest stehen in der Datei, hier nur das Vorhandensein.
    Ohne Profil/Koeffizienten sagt ``detail``, was stattdessen gilt (75-%-Regel, Meldung als TG/TB/TR untransformiert). Validierung: ``tests/test_readiness.py``.
    """
    from .transform import TransformSolution, solution_path
    out = []
    has07 = cam is not None and cam.gain_e_per_adu is not None and cam.linear_max_adu is not None
    if has07:
        out.append(Check("NB07 Kameraprofil", True, f"Gain {cam.gain_e_per_adu:g} e-/ADU, Obergrenze {cam.linear_max_adu:.0f} ADU ({cam.source or 'Quelle unbekannt'})"))
    else:
        out.append(Check("NB07 Kameraprofil", False, "fehlt — NB07 ausfuehren (Gain, Ausleserauschen, Linearitaet, RAW-Kompression); bis dahin gilt die 75-%-Regel mit nominellem Maximalwert", optional=True))
    if method in ("osc", "dslr", "monorgb"):
        p = solution_path(model, setting)
        if p.exists():
            try:
                sol = TransformSolution.load(p)
                good = [b for b, v in (sol.validation or {}).items() if v.get("rms_transformed", 1) <= v.get("rms_standardized", 0) and v.get("rms_transformed", 1) <= 0.06]
                out.append(Check("NB08 Transformation", True, f"{p.name}: Tbv {sol.Tbv:.3f}; Guetetest bestanden fuer {', '.join(good) or 'kein Band'} — nur diese Baender transformiert melden"))
            except Exception as e:
                out.append(Check("NB08 Transformation", False, f"{p.name} nicht lesbar: {type(e).__name__}", optional=True))
        else:
            out.append(Check("NB08 Transformation", False, "keine Koeffizienten — Aufnahmen werden als TG/TB/TR **untransformiert** gemeldet; fuer V/B/R mit TRANS=YES NB08 an einem Standardfeld ausfuehren", optional=True))
    return out


def std_field_visibility(site, date=None, min_alt: float = 30.0, fields: dict | None = None):
    """Welche AAVSO-Standardfelder (:data:`varphot.vsp.STD_FIELDS`) sind in der Nacht am Standort sichtbar? Tabelle ``field, hours, alt_max, ok`` (nach Stunden absteigend).

    Warum: NB08 braucht ein Standardfeld mit grossem Farbbereich; NGC 3532 und NGC 1252 sind von Mitteleuropa nie sichtbar, M 67 und M 11 nur in bestimmten Monaten. Wie: :func:`varphot.plan.night_altitudes`
    je Feld; ``hours`` = Stunden mit dunklem Himmel (Sonne < −12°) und Feld > ``min_alt`` Grad, ``alt_max`` hoechste Hoehe in der Nacht. Grenzen: nur die gewaehlte Nacht (``date``), ohne Mond und Wetter.
    Validierung: ``tests/test_readiness.py``.
    """
    import pandas as pd

    from .plan import night_altitudes
    from .vsp import STD_FIELDS
    rows = []
    for name, (ra, dec, _fov) in (fields or STD_FIELDS).items():
        na = night_altitudes(ra, dec, site, date, step_min=30)
        dark = na[na["dark"]]
        good = dark[dark["alt_target"] > min_alt]
        rows.append(dict(field=name, hours=round(len(good) * 0.5, 1), alt_max=round(float(dark["alt_target"].max()), 1) if len(dark) else float("nan"), ok=len(good) >= 2))
    return pd.DataFrame(rows).sort_values("hours", ascending=False).reset_index(drop=True)


def render_html(checks: list[Check], title: str) -> str:
    """HTML-Tabelle der Pruefungen fuer Notebooks: ✓ gruen, ✗ rot (Hindernis), · grau (optional fehlt); Fusszeile nennt, ob alle **nicht optionalen** Punkte erfuellt sind."""
    rows, all_ok = "", True
    for c in checks:
        icon, color = ("✓", "#4caf50") if c.ok else (("·", "#888") if c.optional else ("✗", "#f44336"))
        all_ok &= c.ok or c.optional
        rows += (f'<tr><td style="padding:3px 10px;color:{color};font-weight:bold">{icon}</td><td style="padding:3px 10px">{c.label}</td>'
                 f'<td style="padding:3px 10px;color:#888;font-size:12px">{c.detail}</td></tr>')
    col = "#4caf50" if all_ok else "#f44336"
    msg = "Alle notwendigen Vorbedingungen erfuellt." if all_ok else "⚠ Mindestens eine notwendige Vorbedingung fehlt (✗)."
    return (f'<table style="border-collapse:collapse;font-family:monospace;font-size:13px;margin:6px 0"><tr style="background:#1e1e2e;color:#cdd6f4"><th colspan="3" style="padding:6px 14px;text-align:left">{title}</th></tr>'
            f'{rows}<tr><td colspan="3" style="padding:6px 10px;color:{col};font-weight:bold">{msg}</td></tr></table>')
