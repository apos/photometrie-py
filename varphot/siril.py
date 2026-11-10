"""Siril-Skripte aus der Sitzung erzeugen (Kalibrierung, Wandlung von Probebildern) und, wenn Siril da ist, ausfuehren.

Autor: Axel Pospischil. Stand 2026-11-10 (NB00/NB01, KONZEPT §12.4).

Warum: Siril kalibriert (Bias/Dark/Flat) und wandelt RAW-Bilder; das soll nicht von Hand in der Oberflaeche geklickt werden. Das Modul schreibt aus dem Sitzungsordner (``lights/ darks/ flats/ biases/``)
ein Skript, das in Siril (``siril-cli -d <Ordner> -s <Skript>``) oder in der Oberflaeche (Skripte → Skript ausfuehren) laeuft. Ergebnis: ``process/pp_light_*.fit``.
Wie: je Aufnahmeart ``convert`` (FITS) bzw. ``convertraw`` (RAW); Master-Bias/-Dark/-Flat mit ``stack … rej`` und Einzelbilder mit ``calibrate``; Farbkameras im CFA-Bereich
(``-cfa -equalize_cfa``, **ohne** Debayern; danach ``tools/split_cfa.py``/``varphot.cfa``).
Quelle: Befehle und Optionen nach der Siril-Befehlsreferenz (``convert``, ``convertraw``, ``stack``, ``calibrate``, ``cd``, ``requires``) — **nicht** gegen die laufende Version geprueft.
**NICHT getestet:** Siril ist auf dem Entwicklungsrechner nicht installiert; es wird nur geprueft, dass die Skripte wie vorgesehen aufgebaut sind (``tests/test_siril.py``). Nach dem ersten echten Lauf: Kopfzeilen
(EXPTIME, DATE-OBS, BAYERPAT), Bildmaxima und Anzahl der ``pp_light_*``-Bilder pruefen (Reifegrad ``siril_session`` in ``maturity.py``).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".rw2", ".dng", ".orf", ".raf", ".pef", ".srw"}
FITS_EXT = {".fit", ".fits", ".fts"}
SIRIL_CLI_PATHS = ["/Applications/Siril.app/Contents/MacOS/siril-cli", "/Applications/Siril.app/Contents/MacOS/siril", "/usr/bin/siril-cli", "/usr/local/bin/siril-cli", "/usr/bin/siril"]


def find_siril() -> str | None:
    """Pfad von ``siril-cli`` (oder ``siril``), sonst ``None``."""
    return next((p for p in SIRIL_CLI_PATHS if Path(p).exists()), None) or shutil.which("siril-cli") or shutil.which("siril")


def sequence_kind(folder) -> str | None:
    """``"raw"``, ``"fits"`` oder ``None`` (leer/fehlt) nach den Dateiendungen im Ordner; bei Mischung gilt ``raw`` (FITS-Dateien neben RAW sind meist Ergebnisse frueherer Laeufe)."""
    p = Path(folder)
    if not p.is_dir():
        return None
    ext = {f.suffix.lower() for f in p.iterdir() if f.is_file()}
    if ext & RAW_EXT:
        return "raw"
    if ext & FITS_EXT:
        return "fits"
    return None


def _convert_cmd(kind: str, base: str, out: str) -> str:
    return f"{'convertraw' if kind == 'raw' else 'convert'} {base} -out={out}"


def build_calibration_script(method: str = "mono", kinds: dict | None = None, rejection: str = "rej 3 3") -> str:
    """Kalibrierungsskript fuer den Sitzungsordner (Arbeitsverzeichnis = Sitzungsordner).

    ``method``: ``mono``/``monorgb`` (normal kalibrieren) oder ``osc``/``dslr`` (``-cfa -equalize_cfa``, kein Debayern). ``kinds``: Aufnahmeart je Ordner (``raw``/``fits``/``None``) fuer
    ``lights``, ``darks``, ``flats``, ``biases``; fehlende Ordner (``None``) werden uebersprungen (ohne Bias wird nicht davon abgezogen, ohne Dark/Flat nicht dunkel-/flatkorrigiert). Ohne ``lights`` ``ValueError``.
    Ergebnis: ``process/pp_light_*.fit`` und die Master in ``masters/``. Aufbau: Bias → Master; Flat (mit Bias kalibriert) → Master (``-norm=mul``); Dark → Master; Lights kalibrieren. Validierung: ``tests/test_siril.py``.
    """
    kinds = kinds or {}
    if not kinds.get("lights"):
        raise ValueError("kein lights/-Ordner mit Bildern — nichts zu kalibrieren")
    cfa = method in ("osc", "dslr")
    L = ["# Von varphot erzeugt (NB01). Aufruf: siril-cli -d <Sitzungsordner> -s scripts/calibrate.ssf  — NICHT getestet (siehe varphot/siril.py)", "requires 1.2.0"]
    if kinds.get("biases"):
        L += ["cd biases", _convert_cmd(kinds["biases"], "bias", "../process"), "cd ../process", f"stack bias {rejection} -nonorm -out=../masters/bias_master", "cd .."]
    if kinds.get("darks"):
        L += ["cd darks", _convert_cmd(kinds["darks"], "dark", "../process"), "cd ../process", f"stack dark {rejection} -nonorm -out=../masters/dark_master", "cd .."]
    if kinds.get("flats"):
        L += ["cd flats", _convert_cmd(kinds["flats"], "flat", "../process"), "cd ../process"]
        L += ["calibrate flat -bias=../masters/bias_master" + (" -cfa" if cfa else "")] if kinds.get("biases") else []
        L += [f"stack {'pp_flat' if kinds.get('biases') else 'flat'} {rejection} -norm=mul -out=../masters/flat_master", "cd .."]
    L += ["cd lights", _convert_cmd(kinds["lights"], "light", "../process"), "cd ../process"]
    opts = ([" -dark=../masters/dark_master"] if kinds.get("darks") else []) + ([" -flat=../masters/flat_master"] if kinds.get("flats") else []) + ([" -bias=../masters/bias_master"] if kinds.get("biases") and not kinds.get("darks") else [])
    L += ["calibrate light" + "".join(opts) + (" -cfa -equalize_cfa" if cfa else ""), "close"]
    return "\n".join(L) + "\n"


def build_convert_script(kind: str = "raw", base: str = "probe", out: str = "fits") -> str:
    """Skript, das die Bilder des Arbeitsverzeichnisses nach FITS wandelt (RAW **ohne Debayern**, CFA bleibt erhalten); Ergebnis ``<out>/<base>_00001.fit`` usw."""
    return f"# Von varphot erzeugt (NB00): Probebilder nach FITS — NICHT getestet\nrequires 1.2.0\n{_convert_cmd(kind, base, out)}\nclose\n"


def write_script(path, text: str) -> Path:
    """Schreibt ein Skript (Ordner werden angelegt) und gibt den Pfad zurueck."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def run_script(script, workdir, siril: str | None = None, timeout: int = 3600, runner=subprocess.run) -> tuple[bool, str]:
    """Fuehrt ein Skript mit ``siril-cli -d <workdir> -s <script>`` aus; Rueckgabe ``(ok, Protokoll)``. Ohne Siril: ``(False, Hinweis)`` — das Skript kann dann in der Oberflaeche ausgefuehrt werden.

    ``ok`` nur bei Rueckgabecode 0. Timeout/Startfehler ergeben ``ok=False`` mit Meldung (keine Ausnahme).
    """
    siril = siril or find_siril()
    if not siril:
        return False, f"Siril nicht gefunden — Skript in der Siril-Oberflaeche ausfuehren (Arbeitsverzeichnis {workdir}, Skript {script})"
    try:
        r = runner([siril, "-d", str(workdir), "-s", str(script)], capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"Zeitlimit ({timeout} s)"
    except OSError as e:
        return False, f"Siril nicht startbar: {e}"
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def calibrated_frames(process_dir, prefix: str = "pp_light") -> list[Path]:
    """Kalibrierte Einzelbilder ``<prefix>_*.fit(s)`` im Ordner ``process/`` (sortiert)."""
    p = Path(process_dir)
    return sorted(f for f in p.glob(f"{prefix}_*") if f.suffix.lower() in FITS_EXT) if p.is_dir() else []
