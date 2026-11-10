#!/usr/bin/env python
"""Vergleicht Gaia-DR3-abgeleitete Helligkeiten mit der AAVSO-Sequenz (VSP) im Feld eines Ziels.

``python tools/compare_gaia_vsp.py "Delta Cep" --simbad "del Cep" --fov 180 --maglimit 11``  (VSP- und SIMBAD-Name unterscheiden sich)

Warum: Die Comps stammen teils aus Gaia (``varphot.vsp.fill_with_gaia``). AAVSO ist die Referenz (Johnson/Cousins, aus
APASS/Landolt-Anschluss); dieses Skript misst, wie gut Gaia-Werte dazu passen — vor jeder Verwendung fuer eine Meldung.
Verglichen werden (je VSP-Stern, Gaia-Treffer innerhalb 2″):
  * V aus G und BP-RP (Polynom der Gaia-EDR3-Dokumentation, ``varphot.vsp.v_from_gaia``),
  * synthetisches Johnson V, B, R aus Gaia-XP-Spektren (``gaiadr3.synthetic_photometry_gspc``, Montegriffo et al. 2023).
Ausgabe: Tabelle und Mittelwert/Streuung der Differenzen (Gaia minus VSP). Benoetigt Netz (ESA-TAP, ARI-Spiegel).
"""
import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astropy.coordinates import SkyCoord  # noqa: E402

from varphot.vsp import _tap_json, fetch_vsp, resolve_target, v_from_gaia  # noqa: E402


def compare(star: str, simbad: str | None = None, fov: float = 180, maglimit: float = 11.0,
            radius_deg: float = 1.6) -> pd.DataFrame:
    tg = resolve_target(simbad or star)
    vsp = fetch_vsp(star, fov_arcmin=fov, maglimit=maglimit)
    q = ("SELECT g.source_id,g.ra,g.dec,g.phot_g_mean_mag AS g,g.bp_rp,g.ruwe,s.v_jkc_mag AS vs,s.b_jkc_mag AS bs,s.r_jkc_mag AS rs "
         "FROM gaiadr3.gaia_source AS g LEFT JOIN gaiadr3.synthetic_photometry_gspc AS s USING (source_id) "
         f"WHERE 1=CONTAINS(POINT('ICRS',g.ra,g.dec),CIRCLE('ICRS',{tg['ra']:.4f},{tg['dec']:.4f},{radius_deg})) "
         f"AND g.phot_g_mean_mag BETWEEN 5 AND {maglimit + 1} AND g.bp_rp IS NOT NULL")
    rows = _tap_json(q, 240)
    gc = SkyCoord([r["ra"] for r in rows], [r["dec"] for r in rows], unit="deg")
    idx, sep, _ = SkyCoord(vsp["ra"], vsp["dec"], unit="deg").match_to_catalog_sky(gc)

    def num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return np.nan

    out = []
    for i, (j, s) in enumerate(zip(idx, sep.arcsec)):
        if s > 2.0:
            continue
        r = rows[j]
        V, B, Rc = num(vsp["V"][i]), num(vsp["B"][i]), num(vsp["Rc"][i])
        out.append(dict(label=str(vsp["label"][i]), V=V, B=B, Rc=Rc, bp_rp=r["bp_rp"], ruwe=r["ruwe"],
                        dV_poly=float(v_from_gaia(r["g"], r["bp_rp"])) - V, dV_synth=num(r["vs"]) - V,
                        dB_synth=num(r["bs"]) - B, dR_synth=num(r["rs"]) - Rc))
    return pd.DataFrame(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("star", help="Name fuer die AAVSO-VSP, z. B. \"Delta Cep\"")
    ap.add_argument("--simbad", help="SIMBAD-Name, z. B. \"del Cep\" (Standard: wie star)")
    ap.add_argument("--fov", type=float, default=180)
    ap.add_argument("--maglimit", type=float, default=11.0)
    a = ap.parse_args(argv)
    warnings.filterwarnings("ignore")
    df = compare(a.star, a.simbad, a.fov, a.maglimit)
    pd.set_option("display.width", 200)
    print(df.round(3).to_string(index=False))
    for c in ("dV_poly", "dV_synth", "dB_synth", "dR_synth"):
        x = df[c].dropna()
        print(f"{c:9s} n={len(x):3d}  Mittel {x.mean():+.3f}  Median {x.median():+.3f}  Streuung {x.std():.3f}  max|.| {x.abs().max():.3f}")


if __name__ == "__main__":
    main()
