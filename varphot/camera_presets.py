"""Kamera-Vorlagen: bekannte Kameras mit Sensor, Bayer-Muster, Bittiefe und Herstellerwerten — Auswahl in NB01 und NB07.

Autor: Axel Pospischil. Stand 2026-11.

Warum: NB07 (Kamera-Charakterisierung) und NB01 (Beobachter/Kamera) sollen nicht fuer jede Kamera von Hand befuellt werden. Eine Vorlage liefert
das, was *vorab* bekannt ist (Sensor, Pixelzahl, Bayer-Muster, Eingabeformat, Herstellerwerte zum Vergleich); gemessen wird trotzdem selbst
(NB07), weil Herstellerangaben abweichen koennen und je Einstellung (Gain-Modus, ISO) gelten.

Jede Angabe traegt einen Pruefstatus (``status``): ``G`` = im Wortlaut gelesen (Quelle genannt), ``F`` = Suchauszug/Testbericht, ``E`` = Annahme oder
abgeleitet, ``?`` = unbekannt (muss gemessen werden). Nichts hier ist eine Messung.

Eigene Kameras ohne Vorlage: ``CameraPreset`` mit den bekannten Angaben anlegen oder in NB07 "eigene Kamera" waehlen.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VendorValues:
    """Herstellerwerte einer Einstellung (None = unbekannt); nur zum Vergleich mit der Messung."""
    gain_e_per_adu: float | None = None
    read_noise_e: float | None = None
    full_well_e: float | None = None
    dark_current_e_per_s: float | None = None
    dark_temp_c: float | None = None
    status: str = "?"
    source: str = ""


@dataclass
class CameraPreset:
    key: str
    model: str
    cam_type: str                         # "CMOS", "DSLR/Mirrorless" ...
    sensor: str
    format_px: tuple[int, int]            # (Breite, Hoehe) der vollen Ausgabe
    pixel_um: float | None
    pixel_status: str                     # Pruefstatus von pixel_um
    bayer_pattern: str                    # "RGGB" usw.; Annahme/gelesen -> bayer_status
    bayer_status: str
    bit_depth: int | None                 # None = unbekannt -> wird in NB07 aus dem Maximalwert abgeleitet
    bit_status: str
    raw_input: str                        # "fits" (Kamerasoftware schreibt FITS) oder "raw" (RW2/CR2/... -> Siril convertraw -> FITS)
    obstype: str                          # AAVSO OBSTYPE (Auslegung siehe KONZEPT §11.2)
    settings: dict[str, VendorValues] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


PRESETS: dict[str, CameraPreset] = {
    "ares-c-pro": CameraPreset(
        key="ares-c-pro", model="Player One Ares-C Pro", cam_type="CMOS",
        sensor="Sony IMX533, 1\"-Quadrat 11,31 x 11,31 mm, Rolling Shutter, gekuehlt (2-stufig TEC)",
        format_px=(3008, 3008), pixel_um=3.76, pixel_status="G", bayer_pattern="RGGB", bayer_status="G",
        bit_depth=14, bit_status="G", raw_input="fits", obstype="DSLR",
        settings={
            "Gain 0, LRN": VendorValues(4.449, 4.46, 72889, 0.000044, -20.0, "G",
                                        "Herstellerdiagramme, zitiert im AAVSO-Forum „Player One IMX533 settings“ (Gain 0, LRN); Dunkelstrom Handbuch S. 16"),
            "Gain 0, normal": VendorValues(4.473, 5.547, 73269, 0.000044, -20.0, "G",
                                           "Ares-C Pro Camera Manual V1.0 (Dez. 2024), Diagramme S. 15 (aus dem Bild abgelesen)"),
        },
        notes=["Fenster nur entspiegelt (D32x2 mm AR), kein IR-Sperrfilter -> externer UV/IR-Sperrfilter noetig",
               "HCG oeffnet bei Gain 125 (Sprung in Gain und Rauschen); je Gain-Modus eigenes Profil messen",
               "Ausgabe RAW16 bei 14-Bit-ADC: Skalierung im FITS pruefen"],
        sources=["https://player-one-astronomy.com/download/Product%20specification%20manual/Ares-C%20Pro%20camera%20Manual.pdf",
                 "https://archive.aavso.org/player-one-imx533-settings"],
    ),
    "lumix-s9": CameraPreset(
        key="lumix-s9", model="Panasonic Lumix DC-S9", cam_type="DSLR/Mirrorless",
        sensor="35-mm-Vollformat-CMOS, ca. 24,2 MP effektiv (25,3 MP gesamt); laut Testberichten derselbe Sensor wie Lumix S5 II",
        format_px=(6000, 4000), pixel_um=5.93, pixel_status="E",
        bayer_pattern="RGGB", bayer_status="E", bit_depth=None, bit_status="?", raw_input="raw", obstype="DSLR",
        settings={
            "ISO 100": VendorValues(status="?", source="keine Herstellerwerte fuer Gain/Rauschen veroeffentlicht gefunden — messen"),
            "ISO 640 (Dual Native high)": VendorValues(status="?", source="Dual Native ISO 100/640 laut Testberichten (F); Werte messen"),
        },
        notes=["Nur elektronischer Verschluss (Panasonic-Spezifikation, G) -> Rolling Shutter; Belichtungen nicht sehr kurz waehlen",
               "Belichtungszeit max. ca. 60 s; ueber ISO 1600 kuerzer (Panasonic-Spezifikation, G)",
               "5-Achsen-Bildstabilisierung (Sensor-Shift, G) fuer Photometrie ausschalten (auch Objektivstabilisierung) — Annahme (E), pruefen",
               "RAW-Bittiefe nicht angegeben (G: 'not stated'); ein Blog nennt 12 Bit im elektronischen Modus (F, unbestaetigt) -> NB07 leitet sie aus dem Maximalwert ab",
               "Pixelabstand 5,93 µm abgeleitet aus 35,6 mm / 6000 px (E; Sensorbreite aus einem Testbericht), nicht amtlich",
               "Bayer-Muster RGGB ist die uebliche Annahme (E): im konvertierten FITS (BAYERPAT) bzw. an den Ebenen pruefen",
               "Eingabe: RAW (RW2) -> Siril `convertraw` ohne -debayer -> FITS (CFA bleibt); Kopfzeilen (EXPTIME, ISO) nach der Umwandlung pruefen",
               "Darks: klassisch, nicht belichtungsskaliert (AAVSO-Handbuch §4.4.2; fuer Canon/Nikon belegt, hier testen)"],
        sources=["https://help.na.panasonic.com/answers/features-and-specifications-lumix-s-series-model-dc-s9k/",
                 "https://www.newsshooter.com/2024/05/22/panasonic-lumix-s9/"],
    ),
    "eigene": CameraPreset(
        key="eigene", model="", cam_type="CMOS", sensor="", format_px=(0, 0), pixel_um=None, pixel_status="?",
        bayer_pattern="", bayer_status="?", bit_depth=None, bit_status="?", raw_input="fits", obstype="CCD",
        settings={"Standard": VendorValues()}, notes=["Eigene Kamera: Modell, Bayer-Muster (leer = Monochrom) und Bittiefe von Hand eintragen"],
    ),
}


def preset_choices() -> list[tuple[str, str]]:
    """``[(Anzeigename, key), ...]`` fuer Auswahllisten (Dropdown)."""
    return [(p.model or "Eigene Kamera …", k) for k, p in PRESETS.items()]


def get_preset(key: str) -> CameraPreset:
    if key not in PRESETS:
        raise KeyError(f"unbekannte Kamera-Vorlage '{key}' (gueltig: {', '.join(PRESETS)})")
    return PRESETS[key]


def slug(text: str) -> str:
    """Dateisystemfreundlicher Name aus Modell/Einstellung (``'Gain 0, LRN'`` -> ``'gain-0-lrn'``)."""
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
