"""Plate-Solving mit kuenstlich defokussierten Bildern: bis zu welcher Unschaerfe loest ASTAP noch?

Warum: Fuer die Photometrie heller Sterne wird bewusst unscharf gestellt (KONZEPT §12.1). Ob ASTAP solche Bilder noch loest, laesst sich vor der Aufnahmenacht an einem echten scharfen Bild pruefen:
Das Bild wird mit :func:`varphot.synthetic.defocus_image` verunschaerft (Gauss oder Kreisring), ohne WCS neu geschrieben, mit ASTAP geloest und die Bildmitte mit der WCS des Originals verglichen.

Aufruf (Beispiel LCO delta Cep, Testdaten per ``tools/download_testdata.py lco-dcep``)::

    python tools/defocus_solve_test.py --frame ../PHOTOMETRIE_PY_DATA/testdata/lco-dcep/<Datei>.fits.fz --blur 0 4 8 12 20 30 --kind gauss donut

Eigene Bilder: ``--frame`` auf ein scharfes Bild mit gueltiger WCS im Header (Wahrheit) zeigen lassen. Grenzen: Eine Faltung ersetzt kein echtes Defokussieren (siehe ``defocus_image``); ASTAP-Einstellungen
(Suchradius, Sternzahl) wie in ``solve_image``. Ergebnis fuer LCO delta Cep: KONZEPT §12.1.
"""
import argparse
import tempfile
import time

import numpy as np
from astropy.io import fits

from varphot import read_frame
from varphot.astrometry import solve_image
from varphot.synthetic import defocus_image


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--frame", required=True)
    ap.add_argument("--blur", type=float, nargs="+", default=[0, 4, 8, 12, 20, 30, 45], help="zusaetzliche Breite (FWHM bzw. Ringdurchmesser) in Pixeln")
    ap.add_argument("--kind", nargs="+", default=["gauss", "donut"], choices=["gauss", "donut"])
    ap.add_argument("--radius", type=float, default=5.0, help="ASTAP-Suchradius [Grad]")
    a = ap.parse_args()

    img, hdr, w = read_frame(a.frame)
    if w is None:
        raise SystemExit("Das Bild braucht eine gueltige WCS im Header (Wahrheit fuer den Vergleich)")
    ny, nx = img.shape
    ra0, dec0 = (float(v) for v in w.pixel_to_world_values(nx / 2, ny / 2))
    scale = float(np.hypot(*w.pixel_scale_matrix[:, 0])) * 3600 if hasattr(w, "pixel_scale_matrix") else 1.0
    fov = ny * scale / 3600
    keep = {k: hdr[k] for k in ("RA", "DEC", "EXPTIME", "DATE-OBS", "OBJECT") if k in hdr}
    print(f"Bild {ny}x{nx}, {scale:.2f}\"/px, Feldhoehe {fov:.3f} Grad")
    print(f"{'Art':6} {'blur px':>8} {'Ergebnis':>9} {'Versatz ["]':>11} {'s':>5}")
    for kind in a.kind:
        for b in a.blur:
            arr = defocus_image(img, b, kind) if b else img
            h = fits.Header()
            for k, v in keep.items():
                h[k] = v
            with tempfile.TemporaryDirectory() as d:
                fits.PrimaryHDU(arr.astype(np.float32), h).writeto(f"{d}/t.fits")
                t0 = time.time()
                r = solve_image(f"{d}/t.fits", radius_deg=a.radius, fov_deg=fov, timeout=180)
            ok = r.wcs is not None and r.source == "ASTAP"
            if ok:
                c = r.wcs.pixel_to_world_values(nx / 2, ny / 2)
                sep = np.hypot((c[0] - ra0) * np.cos(np.radians(dec0)), c[1] - dec0) * 3600
            print(f"{kind:6} {b:8g} {'geloest' if ok else 'NICHT':>9} {(f'{sep:.1f}' if ok else '—'):>11} {time.time() - t0:5.1f}", flush=True)


if __name__ == "__main__":
    main()
