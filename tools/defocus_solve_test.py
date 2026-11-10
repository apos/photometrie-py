"""Plate-Solving mit kuenstlich defokussierten Bildern: bis zu welcher Unschaerfe loest ASTAP noch?

Warum: Fuer die Photometrie heller Sterne wird bewusst unscharf gestellt (KONZEPT §12.1). Ob ASTAP solche Bilder noch loest, laesst sich vor der Aufnahmenacht an einem echten scharfen Bild pruefen:
Das Bild wird mit :func:`varphot.synthetic.defocus_image` verunschaerft (Gauss oder Kreisring), ohne WCS neu geschrieben, mit ASTAP geloest und die Bildmitte mit der WCS des Originals verglichen.

Aufruf (Beispiel LCO delta Cep, Testdaten per ``tools/download_testdata.py lco-dcep``)::

    python tools/defocus_solve_test.py --frame ../PHOTOMETRIE_PY_DATA/testdata/lco-dcep/<Datei>.fits.fz --blur 0 4 8 12 20 30 --kind gauss donut

Eigene Bilder: ``--frame`` auf ein scharfes Bild mit gueltiger WCS im Header (Wahrheit) zeigen lassen. Grenzen: Eine Faltung ersetzt kein echtes Defokussieren (siehe ``defocus_image``); ASTAP-Einstellungen
(Suchradius, Sternzahl) wie in ``solve_image``. Ergebnis fuer LCO delta Cep: KONZEPT §12.1.
"""
import argparse

from varphot import read_frame
from varphot.astrometry import defocus_solve_ladder


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
    hint = {k: hdr[k] for k in ("RA", "DEC", "EXPTIME", "DATE-OBS", "OBJECT") if k in hdr}
    print(f"Bild {img.shape[0]}x{img.shape[1]}")
    print(f"{'Art':6} {'blur px':>8} {'Ergebnis':>9} {'Versatz ["]':>11} {'s':>5}")
    defocus_solve_ladder(img, w, hint, a.blur, a.kind, radius_deg=a.radius,
                         progress=lambda r: print(f"{r['kind']:6} {r['blur_px']:8g} {'geloest' if r['solved'] else 'NICHT':>9} {(str(r['offset_arcsec']) if r['solved'] else '—'):>11} {r['seconds']:5.1f}", flush=True))


if __name__ == "__main__":
    main()
