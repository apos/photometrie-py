"""Sitzung: ein Ordner (zugleich Siril-Arbeitsordner) mit ``session.json`` — alles, was die Notebooks voneinander wissen muessen.

Autor: Axel Pospischil. Stand 2026-11-10 (KONZEPT §12.4).

Warum: Bisher gaben die Notebooks ihre Ergebnisse ueber Umgebungsvariablen und feste Pfade weiter (NB02 suchte die ``session_config.json`` mit ``Path.home().rglob`` durch die ganze Benutzerablage). Eine Sitzung
legt einmal fest: Ziel, Methode, Kamera, Ordner (``lights/ darks/ flats/ biases/ probe/ process/ scripts/ results/``), Plan, Referenzbild und WCS, Feldkonfiguration, Ergebnisordner. Jedes Notebook liest sie und schreibt
dazu, was es herstellt; der Nutzer fragt nichts doppelt ab. ``VARPHOT_SESSION=<Ordner>`` waehlt eine Sitzung; sonst die zuletzt benutzte (``last_session.json`` im Datenordner).
Grenzen: keine Mehrbenutzer-/Mehrfachzugriffe; die Datei ist Klartext-JSON ohne persoenliche Angaben ausser Pfaden — sie liegt im Sitzungsordner (nicht im Repo).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SUBDIRS = ("lights", "darks", "flats", "biases", "probe", "probe/scharf", "process", "masters", "scripts", "results")


@dataclass
class Session:
    """Zustand einer Beobachtungssitzung (siehe Modulkopf); Pfade als Text, damit die Datei lesbar bleibt."""
    workspace: str
    target: str = ""
    method: str = ""                      # mono, monorgb, osc, dslr
    camera_model: str = ""
    camera_setting: str = ""
    aavso_filter: str = ""
    obstype: str = ""
    source: str = "own"                   # own | lco-demo | demo
    plan: str = ""                        # Pfad der Plan-JSON (NB00)
    frames_dir: str = ""                  # kalibrierte Bilder der Reihe (Standard: process/)
    ref_frame: str = ""                   # scharfes Referenzbild (Plate-Solve)
    ref_wcs: str = ""                     # ASTAP-.wcs der Referenz
    ref_fwhm_px: float | None = None
    wcs_mode: str = "auto"                # auto | header | register
    field_config: str = ""
    tag: str = ""
    results: str = ""
    notes: dict = field(default_factory=dict)

    # ---- Pfade
    def path(self, *parts) -> Path:
        return Path(self.workspace).expanduser().joinpath(*parts)

    def ensure_dirs(self) -> list[str]:
        """Legt die Unterordner an (vorhandene bleiben); Rueckgabe: neu angelegte Namen."""
        made = []
        for d in SUBDIRS:
            p = self.path(d)
            if not p.exists():
                p.mkdir(parents=True)
                made.append(d)
        return made

    @property
    def file(self) -> Path:
        return self.path("session.json")

    def results_dir(self) -> Path:
        p = Path(self.results) if self.results else self.path("results", self.tag or "lauf")
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ---- Speichern/Laden
    def save(self, remember: bool = True) -> Path:
        """Schreibt ``session.json`` (Ordner wird angelegt) und merkt sich die Sitzung als zuletzt benutzte."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if remember:
            _remember(self.path())
        return self.file

    def update(self, **kw) -> "Session":
        """Setzt Felder (nur bekannte) und speichert."""
        names = {f.name for f in fields(self)}
        bad = set(kw) - names
        if bad:
            raise KeyError(f"unbekannte Sitzungsfelder: {sorted(bad)}")
        for k, v in kw.items():
            setattr(self, k, v)
        self.save()
        return self

    @classmethod
    def load(cls, workspace) -> "Session":
        """Liest ``<workspace>/session.json``; unbekannte Schluessel (neuere Version) werden ignoriert."""
        p = Path(workspace).expanduser() / "session.json"
        if not p.exists():
            raise FileNotFoundError(f"{p} fehlt — NB00 ausfuehren (legt die Sitzung an)")
        d = json.loads(p.read_text(encoding="utf-8"))
        names = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in names}
        d.setdefault("workspace", str(p.parent))
        d["workspace"] = str(p.parent)                          # Ordner wurde evtl. verschoben: der Pfad der Datei gilt
        return cls(**d)

    DERIVED = ("plan", "ref_frame", "ref_wcs", "ref_fwhm_px", "field_config", "results", "tag")

    @classmethod
    def open(cls, workspace, **fields_) -> "Session":
        """Oeffnet die Sitzung im Ordner oder legt sie an; ``fields_`` (Ziel, Methode, Kamera …) ueberschreiben die gespeicherten Werte.

        Warum: NB00 darf erneut laufen (andere Belichtung, anderes Probebild), ohne die Ergebnisse aus NB01 (Referenz, Comps) zu verlieren. Aendern sich aber **Ziel oder Methode**, gelten Plan, Referenz, WCS und Feld nicht mehr:
        die abgeleiteten Felder (:attr:`DERIVED`) werden geleert und ``notes['zurueckgesetzt']`` nennt den Grund. Neu angelegt wird erst beim Speichern (:meth:`save`).
        """
        p = Path(workspace).expanduser() / "session.json"
        if not p.exists():
            return cls(str(Path(workspace).expanduser()), **fields_)
        s = cls.load(Path(workspace).expanduser())
        changed = [k for k in ("target", "method") if k in fields_ and getattr(s, k) and getattr(s, k) != fields_[k]]
        for k, v in fields_.items():
            setattr(s, k, v)
        if changed:
            for k in cls.DERIVED:
                setattr(s, k, None if k == "ref_fwhm_px" else "")
            s.notes = {**s.notes, "zurueckgesetzt": f"{', '.join(changed)} geaendert — Plan, Referenz und Feld neu erzeugen (NB00/NB01)"}
        return s

    @classmethod
    def current(cls) -> "Session":
        """Die Sitzung aus ``VARPHOT_SESSION`` oder die zuletzt benutzte; ``FileNotFoundError`` mit Hinweis, wenn es keine gibt."""
        env = os.environ.get("VARPHOT_SESSION")
        if env:
            return cls.load(env)
        last = _last_pointer()
        if last and (Path(last) / "session.json").exists():
            return cls.load(last)
        raise FileNotFoundError("keine Sitzung gefunden — NB00 ausfuehren (oder VARPHOT_SESSION=<Ordner> setzen)")


def _pointer_file() -> Path:
    from .observer import data_dir
    base = data_dir() if data_dir().is_dir() else Path("~/.config/varphot").expanduser()
    return base / "last_session.json"


def _remember(workspace) -> None:
    p = _pointer_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"workspace": str(workspace)}) + "\n", encoding="utf-8")
    except OSError:
        pass                                                      # nur eine Bequemlichkeit


def _last_pointer() -> str | None:
    p = _pointer_file()
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("workspace")
    except (OSError, ValueError):
        return None


def session_tag(target: str, method: str, date: str) -> str:
    """Kennung fuer den Ergebnisordner: ``<ziel>_<methode>_<datum>`` (nur Buchstaben/Ziffern/Unterstrich)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", f"{target}_{method}_{date}").strip("_").lower()
