#!/usr/bin/env python
"""CFA-Bilder (kalibrierte Bayer-FITS) in R-, G-, B-Einzelbilder trennen: ``python tools/split_cfa.py EINGABEORDNER AUSGABEORDNER [--pattern RGGB] [--g12]``.

G = Mittel beider Gruen-Ebenen; WCS und Pixelskala werden fuer die halbe Aufloesung angepasst. Ergebnis: ``<name>_R.fits``, ``<name>_G.fits``, ``<name>_B.fits`` — dann NB02 je Kanal.
Siril kalibriert vorher im CFA-Bereich (``tools/siril_calibrate_cfa.ssf``). Details: varphot/cfa.py.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from varphot.cfa import split_cfa_fits  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("eingabe", type=Path)
    ap.add_argument("ausgabe", type=Path)
    ap.add_argument("--pattern", help="Bayer-Muster (Standard: BAYERPAT aus der Kopfzeile, sonst RGGB)")
    ap.add_argument("--g12", action="store_true", help="zusaetzlich G1 und G2 einzeln schreiben")
    a = ap.parse_args(argv)
    files = sorted(p for p in a.eingabe.iterdir() if p.suffix.lower() in (".fit", ".fits", ".fts"))
    if not files:
        print(f"keine FITS-Dateien in {a.eingabe}")
        return 1
    for i, f in enumerate(files, 1):
        split_cfa_fits(f, a.ausgabe, a.pattern, a.g12)
        if i % 25 == 0 or i == len(files):
            print(f"[{i}/{len(files)}] {f.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
