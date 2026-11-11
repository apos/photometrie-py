"""Prueft, dass ``solve_image`` ein komprimiertes Original (``.fits.fz``) nicht loescht (ASTAP loescht Eingabedateien nach dem Entpacken).

Aufruf::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/check_astap_fz_safe.py

Arbeitet an einer **Kopie** der Datei ``elp0m411-kb88-20191114-0205-e91.fits.fz`` (LCO-Testdaten) in einem Wegwerfordner. Ausgabe ``ORIGINAL_OK`` (Rueckgabecode 0) oder ``ORIGINAL_GEFAEHRDET`` (1);
2 ohne Testdaten/ASTAP.
"""
import shutil
import sys
import tempfile
from pathlib import Path

from varphot.astrometry import ASTAP_DEFAULT, solve_image
from varphot.testdata import testdata_dir


def main() -> int:
    src = testdata_dir() / "lco-dcep" / "elp0m411-kb88-20191114-0205-e91.fits.fz"
    if not src.exists() or not Path(ASTAP_DEFAULT).exists():
        print("Testdaten oder ASTAP fehlen:", src, ASTAP_DEFAULT)
        return 2
    d = Path(tempfile.mkdtemp())
    try:
        cp = d / src.name
        shutil.copy2(src, cp)
        r = solve_image(cp)
        unpacked = d / cp.name.replace(".fits.fz", ".fits")
        print("Quelle:", r.source, "| Original vorhanden:", cp.exists(), "| .wcs daneben:", cp.with_suffix(".wcs").exists(), "| entpackte .fits:", unpacked.exists(), "| Dateien:", sorted(p.name for p in d.iterdir()))
        ok = cp.exists() and r.source == "ASTAP" and cp.with_suffix(".wcs").exists() and not unpacked.exists()
        print("ORIGINAL_OK" if ok else "ORIGINAL_GEFAEHRDET")
        return 0 if ok else 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
