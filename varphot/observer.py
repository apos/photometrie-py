"""Beobachter, Standort und Kamera — einmal erfassen, in jedem Notebook wiederverwenden.

Persoenliche Angaben (Koordinaten des Beobachtungsortes, AAVSO-Code) liegen NUR ausserhalb des Repos
(das Repo ist oeffentlich). Suchreihenfolge der Datei ``observer.json``:

1. Umgebungsvariable ``VARPHOT_CONFIG`` (voller Dateipfad),
2. Datenordner neben dem Repo: ``<Elternordner des Repos>/PHOTOMETRIE_PY_DATA/`` (liegt mit im Nextcloud-Ordner),
3. ``~/.config/varphot/observer.json``.

Im Repo stehen nur Standorte der Testdatensaetze (``BUILTIN_SITES``).

Der Standort wird gebraucht fuer BJD_TDB (Lichtlaufzeit zum Sonnensystem-Schwerpunkt) und die Luftmasse;
der AAVSO-Code und die Kameradaten fuer den AAVSO-Export (Formular „Detector Details").
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIRNAME = "PHOTOMETRIE_PY_DATA"
USER_CONFIG = Path("~/.config/varphot/observer.json")
REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Site:
    """Beobachtungsort (WGS84; Laenge positiv nach Osten)."""
    name: str
    lat_deg: float
    lon_deg: float
    height_m: float = 0.0

    def __post_init__(self):
        if not -90 <= self.lat_deg <= 90:
            raise ValueError(f"Breite {self.lat_deg} ausserhalb -90..90")
        if not -180 <= self.lon_deg <= 180:
            raise ValueError(f"Laenge {self.lon_deg} ausserhalb -180..180 (Osten positiv)")
        if not self.name.strip():
            raise ValueError("Standortname fehlt")

    @property
    def earth_location(self):
        """``astropy.coordinates.EarthLocation`` (fuer Time.light_travel_time und AltAz)."""
        from astropy import units as u
        from astropy.coordinates import EarthLocation
        return EarthLocation.from_geodetic(self.lon_deg * u.deg, self.lat_deg * u.deg, self.height_m * u.m)


@dataclass
class Camera:
    """Kameradaten fuer das AAVSO-Formular. Leere Felder = noch nicht gemessen/bekannt."""
    model: str = ""
    cam_type: str = "CMOS"
    gain_e_per_adu: float | None = None
    readout_noise_e: float | None = None
    dark_current_e_per_s: float | None = None     # e-/Pixel/s bei ``dark_temp_c``
    dark_temp_c: float | None = None
    linearity: str = ""
    notes: str = ""
    # Erweiterung durch NB07 (Kamera-Charakterisierung); alle optional, aeltere Dateien bleiben lesbar
    bayer_pattern: str = ""                       # "RGGB" usw.; leer = Monochrom
    bit_depth: int | None = None                  # ADC-Bittiefe (z. B. 14)
    saturation_adu: float | None = None           # gemessener Maximalwert [ADU]
    offset_adu: float | None = None               # System-Offset (Bias-Pegel) [ADU]
    full_well_e: float | None = None              # gain * max_adu [e-]
    linear_min_adu: float | None = None           # unterer Rand des linearen Bereichs [ADU] (NB07, ±1 %)
    linear_max_adu: float | None = None           # oberer Rand des linearen Bereichs [ADU] — Obergrenze fuer Sterne (NB00 nutzt ihn)
    gain_setting: str = ""                        # Einstellung, auf die sich die Werte beziehen (z. B. "Gain 0, LRN, -10 C")
    source: str = ""                              # "gemessen (NB07, Datum)" oder "Hersteller"


@dataclass
class Observer:
    aavso_code: str = ""
    site_name: str = ""
    camera: Camera = field(default_factory=Camera)                 # aktive Kamera/Einstellung
    cameras: list = field(default_factory=list)                    # alle gespeicherten Kameraprofile (Camera je Modell+Einstellung)

    def __post_init__(self):
        self.aavso_code = self.aavso_code.strip().upper()
        if self.aavso_code and not re.fullmatch(r"[A-Z0-9]{2,6}", self.aavso_code):
            raise ValueError(f"AAVSO-Beobachtercode '{self.aavso_code}': erwartet 2-6 Buchstaben/Ziffern")


# Oeffentliche Standorte der Testdatensaetze (Werte aus den FITS-Headern bzw. Betreiberangaben).
BUILTIN_SITES: list[Site] = [
    Site("LCO McDonald (Testdaten delta Cep)", 30.6800415, -104.015066, 2030.0),
    Site("MicroObservatory Whipple (Testdaten HAT-P-32; Hoehe nicht im Header)", 31.68, -110.88, 0.0),
]


def data_dir() -> Path:
    """Datenordner neben dem Repo (gleicher Elternordner, z. B. im Nextcloud-Ordner)."""
    return REPO_ROOT.parent / DATA_DIRNAME


def config_path(path: str | Path | None = None) -> Path:
    """Pfad der Konfigurationsdatei (Reihenfolge siehe Modul-Docstring)."""
    if path:
        return Path(path).expanduser()
    if os.environ.get("VARPHOT_CONFIG"):
        return Path(os.environ["VARPHOT_CONFIG"]).expanduser()
    if data_dir().is_dir():
        return data_dir() / "observer.json"
    return USER_CONFIG.expanduser()


def load_config(path: str | Path | None = None) -> tuple[Observer, list[Site]]:
    """Liest die lokale Konfiguration; fehlt sie, kommt ein leerer Beobachter und keine eigenen Standorte."""
    p = config_path(path)
    if not p.exists():
        return Observer(), []
    d = json.loads(p.read_text(encoding="utf-8"))
    cam = Camera(**d.get("camera", {}))
    obs = Observer(d.get("aavso_code", ""), d.get("site_name", ""), cam, [Camera(**c) for c in d.get("cameras", [])])
    return obs, [Site(**s) for s in d.get("sites", [])]


def save_config(observer: Observer, sites: list[Site], path: str | Path | None = None) -> Path:
    """Schreibt die lokale Konfiguration (Verzeichnis wird angelegt, Rechte nur fuer den Benutzer)."""
    p = config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:                                                             # fremde Schluessel (z. B. ``ai`` der KI-Zweitlesung) bleiben erhalten
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        d = {}
    d.update({"aavso_code": observer.aavso_code, "site_name": observer.site_name,
              "camera": asdict(observer.camera), "cameras": [asdict(c) for c in observer.cameras], "sites": [asdict(s) for s in sites]})
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        p.chmod(0o600)
    except (PermissionError, NotImplementedError):
        pass  # chmod not supported on some filesystems (e.g. network mounts in Datalore)
    return p


def all_sites(own: list[Site]) -> list[Site]:
    """Eigene Standorte zuerst, danach die Testdaten-Standorte (gleiche Namen: eigene gewinnen)."""
    names = {s.name for s in own}
    return list(own) + [s for s in BUILTIN_SITES if s.name not in names]


def upsert_site(sites: list[Site], site: Site) -> list[Site]:
    """Ersetzt einen Standort gleichen Namens oder haengt ihn an."""
    return [s for s in sites if s.name != site.name] + [site]


def upsert_camera(cameras: list, cam: Camera) -> list:
    """Ersetzt das Profil gleichen Modells *und* gleicher Einstellung (``gain_setting``) oder haengt es an."""
    return [c for c in cameras if (c.model, c.gain_setting) != (cam.model, cam.gain_setting)] + [cam]


def camera_kind(cam) -> str:
    """Art der Kamera fuer Auswahllisten: ``Mono``, ``Farbe (Bayer RGGB)`` oder ``Farbe (DSLR)``.

    Gilt fuer :class:`Camera` und :class:`varphot.camera_presets.CameraPreset` (beide haben ``bayer_pattern`` und ``cam_type``). Ein Profil ohne Bayer-Muster
    und ohne DSLR-Typ gilt als Mono — ein altes Farbkamera-Profil, dessen Muster NB07 noch nicht gemessen hat, wird deshalb als Mono angezeigt.
    """
    pattern = (getattr(cam, "bayer_pattern", "") or "").strip()
    if pattern:
        return f"Farbe (Bayer {pattern})"
    return "Farbe (DSLR)" if (getattr(cam, "cam_type", "") or "").upper().startswith("DSLR") else "Mono"


def camera_label(cam: Camera) -> str:
    """Anzeigename eines Profils: ``Modell — Einstellung`` (fehlende Teile entfallen)."""
    return " — ".join(x for x in (cam.model, cam.gain_setting) if x) or "(leer)"
