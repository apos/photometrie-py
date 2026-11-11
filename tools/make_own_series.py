"""Baut aus den LCO-Testdaten eine **simulierte eigene Reihe ohne WCS** (Sitzungsordner mit ``process/pp_light_*.fit``, ``probe/`` und ``probe/scharf/``) — Testfall „Eigendatenweg“.

Warum: Eigene, Siril-kalibrierte Bilder tragen keine WCS im Kopf. Mit den echten LCO-Bildern (Archiv-WCS entfernt, sonst unveraendert) laesst sich der Weg Planung → Vorbereitung → Messung → Bericht ohne eigene Aufnahmen
pruefen. Die Bilder behalten ihre Archiv-Kopfzeilen (``ORIGIN = LCOGT``): NB03 erkennt sie als **fremde Daten** und erzwingt den Testcode ``TST01``.

Aufruf::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/make_own_series.py /tmp/ws_own --n 105

Waehlt Bilder des Teleskops ``0m4-11`` ohne WCS-Fehlermarke (``WCSERR`` = 0), schreibt sie unkomprimiert ohne WCS-Schluessel; das erste dient als scharfes Referenzbild, drei weitere als Probebilder. Der Zielordner darf nicht existieren.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

STRIP = ("CTYPE", "CRVAL", "CRPIX", "CD1_", "CD2_", "PC1_", "PC2_", "CDELT", "WCSERR", "A_", "B_", "AP_", "BP_", "RADESYS", "LONPOLE", "LATPOLE", "CUNIT")


def _write(src: Path, dst: Path) -> None:
    from varphot import read_frame
    img, hdr, _ = read_frame(src)
    h = fits.Header()
    for k, v in hdr.items():
        if k in ("COMMENT", "HISTORY", "") or k.startswith(STRIP):
            continue
        try:
            h[k] = v
        except (ValueError, TypeError):
            pass
    fits.PrimaryHDU(img.astype(np.float32), h).writeto(dst, overwrite=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("workspace")
    ap.add_argument("--n", type=int, default=105, help="Zahl der Bilder der Reihe")
    ap.add_argument("--data", default=None, help="Ordner der LCO-Testdaten (Standard: testdata_dir()/lco-dcep)")
    a = ap.parse_args(argv)
    from varphot.testdata import testdata_dir
    base = Path(a.data) if a.data else testdata_dir() / "lco-dcep"
    ws = Path(a.workspace).expanduser()
    if ws.exists():
        print("Zielordner existiert schon:", ws)
        return 2
    files = sorted(base.glob("*.fits.fz"))
    if not files:
        print(f"keine LCO-Testdaten in {base} — python tools/download_testdata.py lco-dcep")
        return 2
    good = []
    for f in files:
        with fits.open(f) as h:
            hd = h["SCI"].header if "SCI" in h else h[0].header
            if str(hd.get("TELESCOP", "")) == "0m4-11" and int(hd.get("WCSERR", 0) or 0) == 0:
                good.append(f)
    if len(good) < 12:
        print("zu wenige brauchbare Bilder:", len(good))
        return 2
    (ws / "process").mkdir(parents=True)
    (ws / "probe" / "scharf").mkdir(parents=True)
    for i, f in enumerate(good[:a.n]):
        _write(f, ws / "process" / f"pp_light_{i:05d}.fit")
    for i in (1, 2, 3):
        _write(good[i * 10], ws / "probe" / f"probe_{i}.fit")
    _write(good[0], ws / "probe" / "scharf" / "sharp.fit")
    print(f"{min(a.n, len(good))} Bilder in {ws / 'process'}, 3 Probebilder, 1 scharfes Referenzbild — Bilder ohne WCS, Archiv-Kopf (ORIGIN LCOGT)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
