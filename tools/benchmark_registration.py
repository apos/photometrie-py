"""Registrierung gegen die WCS im Kopf pruefen (echte LCO-Bilder): Quote und Positionsfehler.

Warum: Die Registrierung (varphot.registration) ersetzt den Plate-Solve je Bild; ob sie auf echten Bildern traegt, zeigt nur der Vergleich mit einer unabhaengigen Wahrheit: der WCS im Kopf der Bilder mit ``WCSERR`` = 0.

Aufruf::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/benchmark_registration.py

Ausgabe: Zahl registrierter Bilder, Positionsfehler gegen den Kopf (Median, 90 %, Maximum, in Bogensekunden). Erwartung (KONZEPT §12.3): alle registriert, Median < 1″, Maximum < 3″. Rueckgabecode 1, wenn die Erwartung verfehlt wird.
"""
import sys

import numpy as np
from astropy.io import fits

from varphot import read_frame
from varphot.registration import bright_sources, register_frame
from varphot.testdata import testdata_dir


def main() -> int:
    base = testdata_dir() / "lco-dcep"
    good = []
    for f in sorted(base.glob("*.fits.fz")):
        with fits.open(f) as h:
            hd = h["SCI"].header if "SCI" in h else h[0].header
            if str(hd.get("TELESCOP", "")) == "0m4-11" and int(hd.get("WCSERR", 0) or 0) == 0:
                good.append(f)
    if len(good) < 10:
        print("zu wenige LCO-Bilder — python tools/download_testdata.py lco-dcep")
        return 2
    img0, _, w0 = read_frame(good[0])
    ref = bright_sources(img0, 5.0, n_max=60)
    pts = np.array([[600, 500], [1500, 1000], [2400, 1500], [900, 1700], [2800, 300]], float)
    ok, errs, notes = 0, [], []
    for f in good[1:]:
        img, _, w = read_frame(f)
        r = register_frame(ref, img, w0, 5.0)
        if not r.ok:
            notes.append(r.note)
            continue
        ok += 1
        a = np.array(r.wcs.pixel_to_world_values(pts[:, 0], pts[:, 1]))
        b = np.array(w.pixel_to_world_values(pts[:, 0], pts[:, 1]))
        errs.append(float(np.hypot((a[0] - b[0]) * np.cos(np.radians(58)), a[1] - b[1]).max() * 3600))
    n = len(good) - 1
    print(f"registriert {ok} von {n}; Fehler gegen den Kopf: Median {np.median(errs):.2f}″, 90 % {np.percentile(errs, 90):.2f}″, Maximum {max(errs):.2f}″")
    for t in notes[:3]:
        print("  Fehlschlag:", t)
    good_enough = ok == n and np.median(errs) < 1.0 and max(errs) < 3.0
    print("Erwartung erfuellt" if good_enough else "Erwartung VERFEHLT (alle registriert, Median < 1″, Maximum < 3″)")
    return 0 if good_enough else 1


if __name__ == "__main__":
    sys.exit(main())
