#!/usr/bin/env python
"""Roh-Bayer-Reihe durch Siril-Umwandlung, CFA-Trennung und Plate-Solve schicken (Testfaelle SIRIL-01 / OSC-01).

Aufruf::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/check_osc_raw.py RAWORDNER ARBEITSORDNER --ra 47.042 --dec 40.956 --fov 30.3

``RAWORDNER`` enthaelt die RAW-Bilder (CR2 usw., auch in Unterordnern; sie werden nur verlinkt, nicht veraendert), ``ARBEITSORDNER`` muss neu/leer sein. Schritte:

1. Siril-Umwandlung ueber ``varphot.siril`` (RAW → CFA-FITS ohne Debayern).
2. ``varphot.cfa.split_cfa_fits``: R, G, B je Bild (halbe Aufloesung).
3. ASTAP-Plate-Solve je Kanal mit Naeherungsposition (``--ra``/``--dec`` in Grad, ``--fov`` Feldhoehe in Grad); gemeldet werden Zahl geloester Bilder, Pixelskala und Lage eines optionalen
   Zielsterns (``--target-ra``/``--target-dec``, Grad).

Rueckgabecode 0 = alle Bilder in allen Kanaelen geloest; 1 = Fehlschlaege; 2 = Umwandlung fehlgeschlagen. Die Naeherungsposition stammt aus dem Objektnamen, nicht aus dem Bild; ohne Position loest ASTAP
Weitfeldbilder nicht zuverlaessig. Beispielreihe: ``algol-cr2`` (docs/testdaten.md §4).
"""
import argparse
import shutil
import statistics as st
import sys
import time
from pathlib import Path

from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs.utils import proj_plane_pixel_scales

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from varphot import siril  # noqa: E402
from varphot.astrometry import solve_image  # noqa: E402
from varphot.cfa import split_cfa_fits  # noqa: E402

RAW_EXT = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".rw2"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("raw", type=Path)
    ap.add_argument("work", type=Path)
    ap.add_argument("--ra", type=float, required=True, help="Naeherung Rektaszension [Grad]")
    ap.add_argument("--dec", type=float, required=True, help="Naeherung Deklination [Grad]")
    ap.add_argument("--fov", type=float, help="Feldhoehe des geteilten Bildes [Grad]")
    ap.add_argument("--radius", type=float, default=5.0, help="ASTAP-Suchradius [Grad]")
    ap.add_argument("--target-ra", type=float)
    ap.add_argument("--target-dec", type=float)
    a = ap.parse_args(argv)
    if a.work.exists() and any(a.work.iterdir()):
        print(f"{a.work} ist nicht leer")
        return 2
    raw_dir = a.work / "raw"
    raw_dir.mkdir(parents=True)
    n = 0
    for f in sorted(a.raw.rglob("*")):
        if f.suffix.lower() in RAW_EXT:
            (raw_dir / f.name).symlink_to(f.resolve())
            n += 1
    print(f"{n} RAW-Bilder verlinkt")
    script = siril.write_script(raw_dir / "convert.ssf", siril.build_convert_script("raw", "frame", "fits"))
    t = time.time()
    ok, log = siril.run_script(script, raw_dir)
    fits_files = sorted((raw_dir / "fits").glob("frame_*.fit"))
    print(f"Siril: ok={ok}, {len(fits_files)}/{n} FITS in {time.time() - t:.1f} s")
    if not ok or len(fits_files) != n:
        print(log[-800:])
        return 2
    with fits.open(fits_files[0]) as h:
        hd = h[0].header
        print(f"CFA-Bild {h[0].data.shape}, BAYERPAT={hd.get('BAYERPAT')}, EXPTIME={hd.get('EXPTIME')}, DATE-OBS={hd.get('DATE-OBS')}")
    cfa = a.work / "cfa"
    for f in fits_files:
        split_cfa_fits(f, cfa, None, False)
    print(f"CFA-Trennung: {len(list(cfa.glob('*.fits')))} Dateien (R, G, B je Bild)")
    target = SkyCoord(a.target_ra, a.target_dec, unit="deg") if a.target_ra is not None else None
    sol = a.work / "solve"
    sol.mkdir()
    failed = 0
    for ch in ("G", "R", "B"):
        files = sorted(cfa.glob(f"*_{ch}.fits"))
        t, ok_n, scale, pos, bad = time.time(), 0, [], [], []
        for f in files:
            d = sol / f.name
            shutil.copy(f, d)
            with fits.open(d, mode="update") as h:
                h[0].header["RA"], h[0].header["DEC"] = a.ra, a.dec
            r = solve_image(d, radius_deg=a.radius, fov_deg=a.fov, timeout=120)
            if r.source == "ASTAP" and r.wcs:
                ok_n += 1
                scale.append(float(proj_plane_pixel_scales(r.wcs).mean() * 3600))
                if target is not None:
                    x, y = r.wcs.world_to_pixel(target)
                    pos.append((float(x), float(y)))
            else:
                bad.append(f.name)
        failed += len(bad)
        line = f"{ch}: {ok_n}/{len(files)} geloest in {time.time() - t:.0f} s"
        if scale:
            line += f'; Skala {min(scale):.2f}-{max(scale):.2f} "/px (Median {st.median(scale):.2f})'
        if pos:
            line += f"; Ziel bei x {min(p[0] for p in pos):.0f}-{max(p[0] for p in pos):.0f}, y {min(p[1] for p in pos):.0f}-{max(p[1] for p in pos):.0f}"
        if bad:
            line += f"; NICHT geloest: {', '.join(bad[:5])}"
        print(line)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
