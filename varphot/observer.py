"""Beobachter, Standort und Kamera — einmal erfassen, in jedem Notebook wiederverwenden.

Persoenliche Angaben (Koordinaten des Beobachtungsortes, AAVSO-Code) liegen NUR in einer lokalen
Datei ausserhalb des Repos (``~/.config/varphot/observer.json``, abweichend ueber ``VARPHOT_CONFIG``).
Das Repo ist oeffentlich — dort stehen nur Standorte der Testdatensaetze (``BUILTIN_SITES``).

Der Standort wird gebraucht fuer BJD_TDB (Lichtlaufzeit zum Sonnensystem-Schwerpunkt) und die Luftmasse;
der AAVSO-Code und die Kameradaten fuer den AAVSO-Export (Formular „Detector Details").
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_CONFIG = Path("~/.config/varphot/observer.json")


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


@dataclass
class Observer:
    aavso_code: str = ""
    site_name: str = ""
    camera: Camera = field(default_factory=Camera)

    def __post_init__(self):
        self.aavso_code = self.aavso_code.strip().upper()
        if self.aavso_code and not re.fullmatch(r"[A-Z0-9]{2,6}", self.aavso_code):
            raise ValueError(f"AAVSO-Beobachtercode '{self.aavso_code}': erwartet 2-6 Buchstaben/Ziffern")


# Oeffentliche Standorte der Testdatensaetze (Werte aus den FITS-Headern bzw. Betreiberangaben).
BUILTIN_SITES: list[Site] = [
    Site("LCO McDonald (Testdaten delta Cep)", 30.6800415, -104.015066, 2030.0),
    Site("MicroObservatory Whipple (Testdaten HAT-P-32; Hoehe nicht im Header)", 31.68, -110.88, 0.0),
]


def config_path(path: str | Path | None = None) -> Path:
    return Path(path or os.environ.get("VARPHOT_CONFIG") or DEFAULT_CONFIG).expanduser()


def load_config(path: str | Path | None = None) -> tuple[Observer, list[Site]]:
    """Liest die lokale Konfiguration; fehlt sie, kommt ein leerer Beobachter und keine eigenen Standorte."""
    p = config_path(path)
    if not p.exists():
        return Observer(), []
    d = json.loads(p.read_text(encoding="utf-8"))
    cam = Camera(**d.get("camera", {}))
    obs = Observer(d.get("aavso_code", ""), d.get("site_name", ""), cam)
    return obs, [Site(**s) for s in d.get("sites", [])]


def save_config(observer: Observer, sites: list[Site], path: str | Path | None = None) -> Path:
    """Schreibt die lokale Konfiguration (Verzeichnis wird angelegt, Rechte nur fuer den Benutzer)."""
    p = config_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {"aavso_code": observer.aavso_code, "site_name": observer.site_name,
         "camera": asdict(observer.camera), "sites": [asdict(s) for s in sites]}
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    p.chmod(0o600)
    return p


def all_sites(own: list[Site]) -> list[Site]:
    """Eigene Standorte zuerst, danach die Testdaten-Standorte (gleiche Namen: eigene gewinnen)."""
    names = {s.name for s in own}
    return list(own) + [s for s in BUILTIN_SITES if s.name not in names]


def upsert_site(sites: list[Site], site: Site) -> list[Site]:
    """Ersetzt einen Standort gleichen Namens oder haengt ihn an."""
    return [s for s in sites if s.name != site.name] + [site]
