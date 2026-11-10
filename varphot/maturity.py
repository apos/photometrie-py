"""Reifegrad der Funktionen: Was ist an echten Daten geprueft, was nur synthetisch, was gar nicht?

Autor: Axel Pospischil. Stand 2026-11-10.

Warum: Mehrere Pfade der Pipeline (Transformation, Siril-Skript, Farbkamera-Export) sind bisher nur mit synthetischen Daten oder gar nicht an echten Bildern gelaufen. Wer daraus Daten fuer die AAVSO
erzeugt, soll das **vorher sehen**, nicht erst, wenn etwas auffaellt. Die Notebooks (NB02, NB03, NB08) rufen :func:`maturity_warnings` fuer die benutzten Funktionen auf und tragen die Hinweise in den Bericht ein.
Wie: Eine Tabelle ``MATURITY`` (Schluessel -> Stufe, Text). Stufen: ``real`` (an echten Daten geprueft), ``synthetisch`` (Tests/Demo mit erzeugten Daten), ``ungetestet`` (nie ausgefuehrt), ``offen`` (Regel bei der AAVSO unklar).
**Pflege:** Wird eine Funktion an echten Daten geprueft, die Stufe hier hochsetzen (mit Datum und Datensatz) — nichts anderes veraendert die Hinweise.
"""
from __future__ import annotations

MATURITY: dict[str, tuple[str, str]] = {
    "aavso_format": ("real", "Formatpruefung gegen die Beispiele der AAVSO-Format-Seite; Export aus den LCO-Testdaten (nur als TST01/Testdatei)."),
    "lightcurve_mono": ("real", "Lichtkurve δ Cep aus LCO-Daten (Periode 5,363 d gegen 5,366 d Literatur)."),
    "transform_fit": ("synthetisch", "Koeffizienten-Fit und Guetetest nur mit synthetischen Bildern; nie mit echten Standardfeld-Aufnahmen."),
    "transform_lightcurve": ("synthetisch", "Transformierte Lichtkurve (NB02) nur mit synthetischen Mehrkanaldaten getestet."),
    "cfa_split": ("synthetisch", "Kanaltrennung (R, G, B) nur mit synthetischen Bayer-Bildern; WCS-Anpassung nicht an echten RAW-/Siril-Dateien geprueft."),
    "siril_cfa_script": ("ungetestet", "tools/siril_calibrate_cfa.ssf nach der Befehlsreferenz geschrieben, nie in Siril ausgefuehrt."),
    "monorgb": ("synthetisch", "Methode Mono + RGB-Filter nur im Planungs-Demo; keine echten RGB-Aufnahmen der QHY268M."),
    "obstype_colour": ("offen", "OBSTYPE fuer Farbkamera/RGB-Filter: Format-Seite und AAVSO-Forum widersprechen sich (DSLR laut Forum). Bei der AAVSO bestaetigen."),
    "std_field_vsp": ("real", "Standardfelder ueber die VSP-Schnittstelle abgerufen (6 Felder, Sterne mit U/B/V/Rc/Ic)."),
    "registration": ("real", "WCS je Bild per Registrierung an 104 LCO-δ-Cep-Bildern geprueft (Median 0,5″ gegen den Kopf); Eigendatenweg Ende-zu-Ende mit LCO-Bildern ohne WCS (Periode 5,365 d). Mit Bildern einer eigenen Kamera noch nicht."),
    "aperture_growth": ("real", "Aperturwahl aus Wachstumskurve an LCO-Bildern geprueft (9 px: Amplitude 0,79 mag, Periode 5,366 d; 5 px: 0,64 mag); mit eigener Kamera/Farbkamera noch nicht."),
    "siril_session": ("ungetestet", "Siril-Skripte aus der Sitzung (varphot/siril.py) nur auf ihren Aufbau geprueft; Siril ist auf dem Entwicklungsrechner nicht installiert."),
    "plan_probe": ("synthetisch", "Planung aus Probebildern nur mit synthetischen Bildern."),
    "plan_defocus": ("synthetisch", "Defokus-Vergleich (NB00 3c): Rechnung (Spitzenwert ∝ 1/FWHM², S/N ∝ 1/FWHM) nur mit synthetischen Bildern und einem kuenstlich verunschaerften LCO-Bild geprueft; nie mit echtem Defokus am Teleskop."),
    "plate_solve_defocus": ("real", "ASTAP-Grenze fuer kuenstlich verunschaerfte LCO-δ-Cep-Bilder gemessen (Gauss bis FWHM ~20 px, Donut ~12 px); echtes Defokussieren ungeprueft."),
}


def maturity(key: str) -> tuple[str, str]:
    """(Stufe, Text) eines Schluessels; unbekannte Schluessel gelten als ``ungetestet``."""
    return MATURITY.get(key, ("ungetestet", f"'{key}' nicht in der Reifegrad-Tabelle"))


def maturity_warnings(keys) -> list[str]:
    """Hinweistexte fuer alle benutzten Funktionen, die **nicht** an echten Daten geprueft sind (Stufe != ``real``)."""
    out = []
    for k in keys:
        lvl, txt = maturity(k)
        if lvl != "real":
            out.append(f"[{lvl}] {k}: {txt}")
    return out
