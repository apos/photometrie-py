"""Katalog-Crossmatch und Comp/Check-Auswahl."""
import numpy as np
from astropy.coordinates import SkyCoord
import astropy.units as u

from .config import CFG


def crossmatch(src, cat, w, tol_arcsec=None):
    """Verknüpft detektierte Quellen mit dem Referenzkatalog per Himmelskoordinaten."""
    tol = (tol_arcsec or CFG["xmatch_tol_arcsec"]) * u.arcsec
    sc = SkyCoord(*w.pixel_to_world_values(src["x_centroid"], src["y_centroid"]), unit="deg")
    cc = SkyCoord(cat["ra"], cat["dec"], unit="deg")
    idx, sep, _ = sc.match_to_catalog_sky(cc)
    ok = sep < tol
    out = src[ok].copy()
    out["cat_id"] = cat["id"][idx[ok]]
    out["V"] = cat["V"][idx[ok]]
    out["BV"] = cat["BV"][idx[ok]]
    out["var"] = cat["var"][idx[ok]]
    return out


def select_comps(m, cat, w, cfg=None, target_id=0):
    """Wählt Comp- und Check-Sterne nach Regeln aus.

    Rückgabe: (target_dict, comps_list, check_row_or_None)
    target_dict enthält Position und Katalogwerte des Ziels.
    Jeder Stern in comps/check, der die Regeln nicht erfüllt, fällt mit Flag aus
    statt stillschweigend zu verschwinden.
    """
    cfg = cfg or CFG
    nx, ny = cfg["nx"], cfg["ny"]
    edge = cfg["comp_edge_px"]
    r_iso = cfg["comp_r_iso_px"]

    c0 = cat[cat["id"] == target_id][0]
    tx, ty = w.world_to_pixel_values(c0["ra"], c0["dec"])
    tgt = {
        "V": c0["V"], "BV": c0["BV"],
        "x_centroid": float(tx), "y_centroid": float(ty),
        "cat_id": target_id,
    }

    cand, rejected = [], []
    for r in m:
        reason = _comp_reject_reason(r, tgt, m, cfg, nx, ny, edge, r_iso, target_id)
        if reason:
            rejected.append((r["cat_id"], reason))
        else:
            cand.append(r)

    if rejected:
        print(f"Comp-Auswahl: {len(rejected)} Kandidaten verworfen (QC):")
        for cid, reason in rejected[:5]:
            print(f"  id={cid}: {reason}")
        if len(rejected) > 5:
            print(f"  … und {len(rejected) - 5} weitere")

    cand.sort(key=lambda r: abs(r["V"] - (tgt["V"] + cfg["comp_dmag"])))
    comps = cand[:cfg["comp_n"]]
    check = cand[cfg["comp_n"]] if len(cand) > cfg["comp_n"] else None
    return tgt, comps, check


def _comp_reject_reason(r, tgt, m, cfg, nx, ny, edge, r_iso, target_id):
    if r["cat_id"] == target_id or r["var"]:
        return "Ziel oder bekannter Veränderlicher"
    dist_tgt = np.hypot(r["x_centroid"] - tgt["x_centroid"], r["y_centroid"] - tgt["y_centroid"])
    if dist_tgt < 60:
        return "im Halo des defokussierten Ziels"
    if abs(r["V"] - tgt["V"]) > 6:
        return f"Helligkeitsdifferenz {abs(r['V'] - tgt['V']):.1f} mag > 6"
    if abs(r["BV"] - tgt["BV"]) > cfg["comp_bv_tol"]:
        return f"B-V-Differenz {abs(r['BV'] - tgt['BV']):.2f} > {cfg['comp_bv_tol']}"
    if not (edge < r["x_centroid"] < nx - edge and edge < r["y_centroid"] < ny - edge):
        return "zu nah am Rand"
    d = np.hypot(m["x_centroid"] - r["x_centroid"], m["y_centroid"] - r["y_centroid"])
    if np.sum(d < r_iso) > 1:
        return "Nachbar im Aperturbereich"
    if r["peak"] > cfg["comp_peak_max"]:
        return f"Peak {r['peak']:.0f} > {cfg['comp_peak_max']} (Sättigung)"
    return None
