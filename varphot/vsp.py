"""Vergleichssterne aus der AAVSO-Sequenz (VSP) + Gaia-Gegenprüfung — Auswahl ohne Bild.

Ablauf (P0-2): Ziel bei SIMBAD auflösen -> VSP-Sequenz holen -> Gaia DR3 um jeden Kandidaten
abfragen -> Regeln anwenden -> Comp/Check/Reserve mit Begründung für jeden verworfenen Stern.
Alle Netzabfragen werden als JSON zwischengespeichert (Offline-Betrieb am Teleskop).

Hosts: SIMBAD über den Harvard-Spiegel (``simbad.cds.unistra.fr`` antwortet auf ``/simbad/`` mit 404),
Gaia DR3 über das ESA-TAP (``gea.esac.esa.int``). ``vizier.cds.unistra.fr`` liefert (Stand 2026-11-10)
ein Zertifikat für ``aladin.cds.unistra.fr`` (Hostname-Fehler), der VizieR-Spiegel in Harvard liefert für
``I/355/gaiadr3`` leere Kegel -> beides nicht verwendet. Zertifikatsprüfung wird NICHT abgeschaltet.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.table import Table

VSP_URL = "https://app.aavso.org/vsp/api/chart/"
SIMBAD_TAP = "https://simbad.cfa.harvard.edu/simbad/sim-tap/sync"
GAIA_TAP = "https://gea.esac.esa.int/tap-server/tap/sync"
DEFAULT_CACHE = Path.home() / ".cache" / "varphot"

# Auswahlregeln (Startwerte, ueberschreibbar per cfg); Begruendungen: BM 00002 Abschnitt 3
VSP_CFG = {
    "field_deg": (2.49, 1.67),       # Apo 80/540 + QHY268M (6252x4176 px, 3,76 um): rotationssicher nutzen
    "field_margin_deg": 0.05,        # Randabstand
    "field_pa_deg": None,            # None = rotationssicher (Kreis); sonst Drehwinkel der langen Seite [Grad,
                                     # gegen den Uhrzeigersinn aus Ost-West-Lage; nach dem Plate Solve aus der WCS]
    "comp_v_range": (5.5, 10.5),     # nicht zu hell (Saettigung) und nicht zu schwach (S/N)
    "comp_err_max": 0.05,            # max. Fehler der VSP-V-Helligkeit [mag]
    "comp_bv_tol": 0.40,             # max. |B-V(Comp) - B-V(Ziel)|
    "comp_r_iso_arcsec": 36.0,       # kein Gaia-Nachbar im Aperturbereich (25 px * 1,44")
    "comp_neighbour_dmag": 3.0,      # Nachbar zaehlt, wenn er max. so viel schwaecher ist wie der Comp
    "comp_ruwe_max": 1.4,
    "vg_tol": 0.30,                  # max. Abweichung VSP-V gegen Gaia-V (aus G und BP-RP) [mag]
    "comp_n": 8,
    # Gaia-Feldsterne als Ergaenzung (fill_with_gaia)
    "gaia_v_err": 0.05,              # angesetzter V-Fehler fuer Gaia-abgeleitete V (Polynom sigma ~0,04 + Photometrie)
    "gaia_bprp_tol": 0.45,           # max. |BP-RP(Stern) - BP-RP(Ziel)| (entspricht etwa 0,4 mag in B-V)
    "gaia_min_sep_deg": 0.05,        # Abstand zum (defokussierten) Ziel
    "gaia_max_checks": 30,           # max. Nachbarabfragen (je ~3 s, danach im Cache)
}


# ---------------------------------------------------------------- Cache / Netz
def _cache_file(cache_dir, name: str) -> Path:
    d = Path(cache_dir) if cache_dir else DEFAULT_CACHE
    d.mkdir(parents=True, exist_ok=True)
    return d / (re.sub(r"[^A-Za-z0-9._+-]+", "_", name) + ".json")


def _cached_json(cache_dir, name, fetch, force=False):
    f = _cache_file(cache_dir, name)
    if f.exists() and not force:
        return json.loads(f.read_text())
    data = fetch()
    f.write_text(json.dumps(data))
    return data


def resolve_target(name: str, cache_dir=None, force=False) -> dict:
    """Ziel bei SIMBAD aufloesen: RA/Dec [Grad], B, V, B-V, Objekttyp (Bezeichner wie ``* del Cep``)."""
    ident = name if name.startswith(("*", "V*", "HD", "HIP", "NAME")) else f"* {name}"

    def fetch():
        q = ("SELECT b.main_id, b.ra, b.dec, b.otype, a.B, a.V FROM basic b "
             "JOIN ident i ON i.oidref=b.oid LEFT JOIN allfluxes a ON a.oidref=b.oid "
             f"WHERE i.id='{ident.replace(chr(39), '')}'")
        r = requests.post(SIMBAD_TAP, data=dict(request="doQuery", lang="adql", format="json", query=q),
                          timeout=60)
        r.raise_for_status()
        j = r.json()
        if not j["data"]:
            raise LookupError(f"SIMBAD kennt '{ident}' nicht (Schreibweise: z. B. '* del Cep', 'V* RR Lyr')")
        return dict(zip([c["name"] for c in j["metadata"]], j["data"][0]))

    d = _cached_json(cache_dir, f"simbad_{ident}", fetch, force)
    out = {"name": d["main_id"], "ra": float(d["ra"]), "dec": float(d["dec"]), "otype": d["otype"],
           "B": d["B"], "V": d["V"]}
    out["BV"] = (d["B"] - d["V"]) if (d["B"] is not None and d["V"] is not None) else None
    return out


def fetch_vsp(star: str, fov_arcmin: float = 180, maglimit: float = 10.0,
              cache_dir=None, force=False) -> Table:
    """AAVSO-VSP-Sequenz als Tabelle (RA/Dec in Grad, V/B/Rc/Ic mit Fehlern, Kommentar, Flags)."""
    def fetch():
        r = requests.get(VSP_URL, params=dict(star=star, fov=fov_arcmin, maglimit=maglimit, format="json"),
                         timeout=60)
        r.raise_for_status()
        return r.json()

    d = _cached_json(cache_dir, f"vsp_{star}_{fov_arcmin:g}_{maglimit:g}", fetch, force)
    return vsp_table(d)


def vsp_table(d: dict) -> Table:
    """Wandelt die VSP-JSON-Antwort in eine Tabelle (auch fuer Offline-Fixtures)."""
    rows = []
    for p in d["photometry"]:
        c = SkyCoord(p["ra"], p["dec"], unit=(u.hourangle, u.deg))
        b = {x["band"]: (x["mag"], x["error"]) for x in p["bands"]}
        g = lambda band, k: b[band][k] if band in b else np.nan
        comment = (p.get("comments") or "").strip()
        rows.append(dict(auid=p["auid"], label=p["label"], ra=c.ra.deg, dec=c.dec.deg,
                         V=g("V", 0), V_err=g("V", 1), B=g("B", 0), B_err=g("B", 1),
                         Rc=g("Rc", 0), Ic=g("Ic", 0), comment=comment))
    t = Table(rows=rows)
    t["BV"] = t["B"] - t["V"]
    return t


def vsp_flags(comment: str) -> list[str]:
    """Warnhinweise aus dem VSP-Kommentar (Veraenderlichkeit, nur visuell)."""
    c = comment or ""
    out = []
    if re.search(r"\bNSV\b", c):
        out.append("NSV-Eintrag (Verdacht auf Veränderlichkeit)")
    m = re.search(r"ampl\w*\.?\s*([0-9.]+)\s*mag", c, re.I) or re.search(r"ampl\w*\.?\s*([0-9.]+)", c, re.I)
    typed = re.search(r"\b(ACV|EA|EB|EW|DSCT|RR|SR|LB|CEP|ROT|BY)\b", c)
    if m:                                    # Amplitude bekannt: nur relevant, wenn > 0,02 mag
        if float(m.group(1).rstrip(".")) > 0.02:
            out.append("als veränderlich gelistet")
    elif typed:
        out.append("als veränderlich gelistet")
    if re.search(r"only for visual", c, re.I):
        out.append("nur für visuelle Beobachtung")
    return out


# ---------------------------------------------------------------- Gaia
def v_from_gaia(g, bp_rp):
    """Johnson-V aus Gaia G und BP-RP (Gaia-EDR3-Dokumentation, Tab. 5.8; Koeffizienten aus dem
    Gedaechtnis -> gegen die Doku pruefen; gueltig fuer -0,5 < BP-RP < 2,75, sigma ~ 0,04 mag)."""
    c = np.asarray(bp_rp, float)
    return np.asarray(g, float) - (-0.02704 + 0.01424 * c - 0.2156 * c ** 2 + 0.01426 * c ** 3)


def _tap_json(query: str, timeout: int = 90, tries: int = 3) -> list[dict]:
    """ADQL-Abfrage am ESA-Gaia-TAP (JSON) mit Wiederholung bei Timeout (der Dienst antwortet zeitweise langsam)."""
    import time
    last = None
    for k in range(tries):
        try:
            r = requests.post(GAIA_TAP, data=dict(REQUEST="doQuery", LANG="ADQL", FORMAT="json", QUERY=query),
                              timeout=timeout)
            r.raise_for_status()
            j = r.json()
            names = [c["name"] for c in j["metadata"]]
            return [dict(zip(names, row)) for row in j["data"]]
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(2 * (k + 1))
    raise RuntimeError(f"Gaia-TAP nach {tries} Versuchen nicht erreichbar: {last}")


def gaia_cone(ra: float, dec: float, radius_arcsec: float = 40.0, gmax: float = 18.0,
              cache_dir=None, force=False) -> Table:
    """Gaia-DR3-Quellen (ESA-TAP) im Kegel um (ra, dec) [Grad]; Ergebnis wird zwischengespeichert."""
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag AS G, bp_rp, phot_variable_flag AS varflag, ruwe, "
         "non_single_star AS nss FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),"
         f"CIRCLE('ICRS',{ra:.6f},{dec:.6f},{radius_arcsec / 3600:.6f})) AND phot_g_mean_mag<{gmax:g}")

    def fetch():
        return _tap_json(q, 90)

    rows = _cached_json(cache_dir, f"gaia_{ra:.5f}_{dec:.5f}_{radius_arcsec:g}_{gmax:g}", fetch, force)
    t = Table(rows=[{k: (np.nan if v is None else v) for k, v in r.items()} for r in rows]) if rows else \
        Table(names=["source_id", "ra", "dec", "G", "bp_rp", "varflag", "ruwe", "nss"],
              dtype=[int, float, float, float, float, "U16", float, int])
    return t


# ---------------------------------------------------------------- Auswahl
def in_field(ra, dec, ra0, dec0, field_deg, margin_deg=0.0, pa_deg=None):
    """True, wenn (ra, dec) im Sensorfeld um (ra0, dec0) liegt. ``pa_deg=None``: Kreis mit dem
    Radius der halben kurzen Seite (gilt fuer jede Kamerarotation); sonst das gedrehte Rechteck."""
    from .astrometry import gnomonic
    x, y = gnomonic(ra, dec, ra0, dec0)          # x: Osten links (negativ), y: Norden
    xi = -np.asarray(x, float)                   # Osten positiv
    eta = np.asarray(y, float)
    long_, short_ = max(field_deg), min(field_deg)
    if pa_deg is None:
        return np.hypot(xi, eta) <= 0.5 * short_ - margin_deg
    a = np.radians(pa_deg)
    u_, v_ = xi * np.cos(a) + eta * np.sin(a), -xi * np.sin(a) + eta * np.cos(a)
    return (np.abs(u_) <= 0.5 * long_ - margin_deg) & (np.abs(v_) <= 0.5 * short_ - margin_deg)


def _stage1_reasons(r, sep_deg, inside, target, cfg):
    """Regeln, die nur die VSP-Daten brauchen (kein Netz)."""
    why = list(vsp_flags(r["comment"]))
    v_lo, v_hi = cfg["comp_v_range"]
    if not inside:
        pa = cfg["field_pa_deg"]
        why.append(f"außerhalb des Feldes ({sep_deg:.2f}° vom Ziel; "
                   f"{'rotationssicher' if pa is None else f'PA {pa:g}°'})")
    if np.isnan(r["V"]) or np.isnan(r["B"]):
        why.append("V oder B fehlt (keine Farbe)")
    else:
        if not (v_lo <= r["V"] <= v_hi):
            why.append(f"V={r['V']:.2f} außerhalb {v_lo}–{v_hi}")
        if r["V_err"] > cfg["comp_err_max"]:
            why.append(f"V-Fehler {r['V_err']:.3f} > {cfg['comp_err_max']}")
        if target.get("BV") is not None and abs(r["BV"] - target["BV"]) > cfg["comp_bv_tol"]:
            why.append(f"B-V {r['BV']:.2f} weicht {abs(r['BV'] - target['BV']):.2f} vom Ziel ab "
                       f"(> {cfg['comp_bv_tol']})")
    return why


def select_comps_catalog(vsp: Table, target: dict, cfg: dict | None = None, use_gaia: bool = True,
                         cache_dir=None) -> Table:
    """Bewertet jeden VSP-Stern und weist eine Rolle zu: ``comp`` / ``check`` / ``reserve`` / ``verworfen``.

    ``target``: Ergebnis von :func:`resolve_target` (ra, dec, BV). Stufe 1 (nur VSP-Daten): Feld, Helligkeit,
    Fehler, Farbe, Veraenderlichkeits-Hinweise. Stufe 2 (Gaia DR3, nur fuer die Ueberlebenden von Stufe 1):
    Nachbarn im Aperturbereich, Gaia-Variabilitaet, RUWE, Nicht-Einzelstern, Konsistenz VSP-V gegen
    Gaia-V. ``use_gaia=False`` -> Stufe 2 entfaellt (in ``notes`` vermerkt). Verworfene Sterne
    behalten ihre Begruendungen in ``reasons``.
    """
    cfg = {**VSP_CFG, **(cfg or {})}
    tc = SkyCoord(target["ra"] * u.deg, target["dec"] * u.deg)
    cc = SkyCoord(vsp["ra"] * u.deg, vsp["dec"] * u.deg)
    sep_deg = tc.separation(cc).deg
    inside = in_field(vsp["ra"], vsp["dec"], target["ra"], target["dec"], cfg["field_deg"],
                      cfg["field_margin_deg"], cfg["field_pa_deg"])

    out = vsp.copy()
    out["sep_deg"] = sep_deg
    reasons, notes = [], []
    n = len(vsp)
    G, BPRP, VG = (np.full(n, np.nan) for _ in range(3))
    for i, r in enumerate(vsp):
        reasons.append(_stage1_reasons(r, sep_deg[i], bool(inside[i]), target, cfg))
        notes.append([] if use_gaia else ["ohne Gaia-Gegenprüfung"])

    if use_gaia:
        for i in [k for k in range(n) if not reasons[k]]:          # Stufe 2 nur fuer Ueberlebende
            gs = gaia_cone(vsp["ra"][i], vsp["dec"][i], cfg["comp_r_iso_arcsec"], 18.0, cache_dir)
            if not len(gs):
                notes[i].append("Gaia: keine Quelle gefunden")
                continue
            d = cc[i].separation(SkyCoord(gs["ra"] * u.deg, gs["dec"] * u.deg)).arcsec
            # der Stern selbst: naechste Quelle <= 3", bei Mehrdeutigkeit die zur VSP-V-Helligkeit passende
            cand = np.flatnonzero(d <= 3.0)
            if not len(cand):
                notes[i].append("kein Gaia-Gegenstück ≤ 3″")
                k = None
            else:
                k = int(cand[np.argmin(np.abs(gs["G"][cand] - vsp["V"][i]))])
                me = gs[k]
                G[i], BPRP[i] = me["G"], me["bp_rp"]
                if np.isfinite(me["bp_rp"]):
                    VG[i] = v_from_gaia(me["G"], me["bp_rp"])
                    if abs(VG[i] - vsp["V"][i]) > cfg["vg_tol"]:
                        reasons[i].append(f"VSP-V {vsp['V'][i]:.2f} ≠ Gaia-V {VG[i]:.2f} (Δ>{cfg['vg_tol']})")
                if str(me["varflag"]).strip() == "VARIABLE":
                    reasons[i].append("Gaia: VARIABLE")
                if np.isfinite(me["ruwe"]) and me["ruwe"] > cfg["comp_ruwe_max"]:
                    reasons[i].append(f"Gaia RUWE {me['ruwe']:.1f} > {cfg['comp_ruwe_max']} (Doppelstern?)")
                if me["nss"]:
                    reasons[i].append("Gaia: Nicht-Einzelstern-Lösung")
            ref_g = G[i] if np.isfinite(G[i]) else vsp["G"][i] if "G" in vsp.colnames else vsp["V"][i]
            others = np.arange(len(gs)) != k
            bad = others & (d <= cfg["comp_r_iso_arcsec"]) & (gs["G"] < ref_g + cfg["comp_neighbour_dmag"])
            if bad.any():
                j = int(np.argmin(np.where(bad, d, 1e9)))
                reasons[i].append(f"Gaia-Nachbar G={gs['G'][j]:.1f} in {d[j]:.0f}″")

    out["G"], out["bp_rp"], out["V_gaia"] = G, BPRP, VG
    out["reasons"] = ["; ".join(r) for r in reasons]
    out["notes"] = ["; ".join(x) for x in notes]

    ok = np.array([not r for r in reasons])
    # Rangfolge: Farbnaehe zum Ziel, dann V-Fehler (kleiner = besser), dann Abstand zum Ziel
    bv_t = target.get("BV") if target.get("BV") is not None else 0.0
    score = np.abs(out["BV"] - bv_t) + 2 * np.nan_to_num(out["V_err"], nan=1.0) + 0.1 * sep_deg
    role = np.array(["verworfen"] * n, dtype="U10")
    idx = [i for i in np.argsort(score) if ok[i]]
    for rank, i in enumerate(idx):
        role[i] = "comp" if rank < cfg["comp_n"] else ("check" if rank == cfg["comp_n"] else "reserve")
    out["role"], out["score"] = role, score
    out["source"] = "VSP"
    return out


def bprp_from_bv(bv):
    """Grobe Naeherung BP-RP ~ 0,04 + 1,2*(B-V) (Anpassung an 9 VSP-Sterne um del Cep, 2026-11-10;
    gilt nur fuer die Auswahl der Farbnaehe, nicht fuer Photometrie)."""
    return 0.04 + 1.2 * np.asarray(bv, float)


def _gaia_candidates_raw(ra, dec, radius_deg, g_lo, g_hi, cache_dir=None, force=False) -> Table:
    """Gaia-DR3-Kandidaten im Kegel (ESA-TAP): serverseitig RUWE < 1,4, Einzelstern, mit BP-RP, G im Bereich."""
    q = ("SELECT source_id, ra, dec, phot_g_mean_mag AS G, bp_rp, phot_variable_flag AS varflag, ruwe, "
         "non_single_star AS nss FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT('ICRS',ra,dec),"
         f"CIRCLE('ICRS',{ra:.6f},{dec:.6f},{radius_deg:.4f})) AND phot_g_mean_mag BETWEEN {g_lo:g} AND {g_hi:g} "
         "AND ruwe<1.4 AND non_single_star=0 AND bp_rp IS NOT NULL")

    def fetch():
        return _tap_json(q, 180)

    rows = _cached_json(cache_dir, f"gaiafield_{ra:.5f}_{dec:.5f}_{radius_deg:g}_{g_lo:g}_{g_hi:g}", fetch, force)
    names = ["source_id", "ra", "dec", "G", "bp_rp", "varflag", "ruwe", "nss"]
    return Table(rows=[{k: (np.nan if v is None else v) for k, v in r.items()} for r in rows]) if rows else \
        Table(names=names, dtype=[int, float, float, float, float, "U16", float, int])


def fill_with_gaia(res: Table, target: dict, cfg: dict | None = None, cache_dir=None) -> Table:
    """Ergaenzt das Ensemble mit Gaia-DR3-Feldsternen, wenn die VSP-Auswahl zu klein ist.

    Gaia-Kandidaten: im Feld, V (aus G und BP-RP) im ``comp_v_range``, Farbe nah am Ziel, kein VARIABLE,
    RUWE < 1,4, Einzelstern, kein VSP-Stern (dort gilt die VSP-Bewertung), nicht im Halo des Ziels. Nach
    Farbnaehe sortiert werden sie nacheinander auf Nachbarn im Aperturbereich geprueft (ESA-TAP, je ~3 s)
    bis genug Sterne da sind. VSP-Comps behalten Vorrang. Die V-Werte sind Gaia-abgeleitet (Fehler
    ``gaia_v_err``) und sollten gegen die VSP-Comps gegengeprueft werden; Zeilen tragen ``source='Gaia'``.
    """
    cfg = {**VSP_CFG, **(cfg or {})}
    roles = np.asarray(res["role"]).astype(str)
    n_comp = int((roles == "comp").sum())
    has_check = bool((roles == "check").any())
    need = max(0, cfg["comp_n"] - n_comp) + (0 if has_check else 1)
    if need == 0:
        return res

    bprp_t = float(bprp_from_bv(target["BV"]))
    v_lo, v_hi = cfg["comp_v_range"]
    radius = float(np.hypot(*(0.5 * np.asarray(cfg["field_deg"]))))
    cand = _gaia_candidates_raw(target["ra"], target["dec"], radius, v_lo - 0.4, v_hi + 0.4, cache_dir)
    if not len(cand):
        return res
    c_ra, c_dec = np.asarray(cand["ra"], float), np.asarray(cand["dec"], float)
    tc = SkyCoord(target["ra"] * u.deg, target["dec"] * u.deg)
    cc = SkyCoord(c_ra * u.deg, c_dec * u.deg)
    sep = tc.separation(cc).deg
    vg = v_from_gaia(cand["G"], cand["bp_rp"])
    inside = in_field(c_ra, c_dec, target["ra"], target["dec"], cfg["field_deg"], cfg["field_margin_deg"],
                      cfg["field_pa_deg"])
    vsp_cc = SkyCoord(np.asarray(res["ra"], float) * u.deg, np.asarray(res["dec"], float) * u.deg)
    in_vsp = cc.match_to_catalog_sky(vsp_cc)[1].arcsec <= 3.0
    ok = (inside & (vg >= v_lo) & (vg <= v_hi) & (np.abs(cand["bp_rp"] - bprp_t) <= cfg["gaia_bprp_tol"])
          & (np.asarray(cand["varflag"]).astype(str) != "VARIABLE") & (sep >= cfg["gaia_min_sep_deg"]) & ~in_vsp)
    order = [i for i in np.argsort(np.abs(np.asarray(cand["bp_rp"]) - bprp_t) + 0.1 * sep) if ok[i]]

    rows = [dict(zip(res.colnames, [res[c][i] for c in res.colnames])) for i in range(len(res))]
    template = {c: (np.nan if res[c].dtype.kind == "f" else "") for c in res.colnames}
    good = checked = 0
    for i in order:
        if good >= need or checked >= cfg["gaia_max_checks"]:
            break
        checked += 1
        near = gaia_cone(c_ra[i], c_dec[i], cfg["comp_r_iso_arcsec"], 18.0, cache_dir)
        d = SkyCoord(c_ra[i] * u.deg, c_dec[i] * u.deg).separation(
            SkyCoord(np.asarray(near["ra"], float) * u.deg, np.asarray(near["dec"], float) * u.deg)).arcsec \
            if len(near) else np.array([])
        bad = [j for j in range(len(near)) if d[j] > 0.5 and near["G"][j] < cand["G"][i] + cfg["comp_neighbour_dmag"]]
        row = dict(template)
        row.update(auid=f"Gaia DR3 {int(cand['source_id'][i])}", label=f"g{checked}", ra=c_ra[i], dec=c_dec[i],
                   V=float(vg[i]), V_err=cfg["gaia_v_err"], BV=np.nan, sep_deg=float(sep[i]), G=float(cand["G"][i]),
                   bp_rp=float(cand["bp_rp"][i]), V_gaia=float(vg[i]), comment="Gaia-abgeleitetes V", source="Gaia",
                   score=float(abs(cand["bp_rp"][i] - bprp_t) + 0.1 * sep[i]))
        if bad:
            j = min(bad, key=lambda k: d[k])
            row.update(role="verworfen", reasons=f"Gaia-Nachbar G={near['G'][j]:.1f} in {d[j]:.0f}″")
        else:
            row.update(role="comp" if n_comp + good < cfg["comp_n"] else ("check" if not has_check else "reserve"),
                       reasons="")
            if row["role"] == "check":
                has_check = True
            good += 1
        rows.append(row)
    out = Table(rows=rows, names=res.colnames)          # Dtypes neu ableiten (sonst wird 'Gaia' zu 'VSP'-Breite gekappt)
    out.meta["gaia_checked"], out.meta["gaia_candidates"] = checked, int(len(order))
    return out


def reject_summary(res: Table) -> dict[str, int]:
    """Haeufigkeit der Ablehnungsgruende (nach Kategorie) ueber alle verworfenen Sterne."""
    cats = {"außerhalb des Feldes": "Feld", "NSV": "veränderlich/NSV", "veränderlich": "veränderlich/NSV",
            "nur für visuelle": "nur visuell", "V-Fehler": "V-Fehler", "B-V": "Farbe", "außerhalb 5": "Helligkeit",
            "V oder B fehlt": "keine Farbe", "Gaia-Nachbar": "Gaia-Nachbar", "RUWE": "Gaia RUWE/NSS",
            "Nicht-Einzelstern": "Gaia RUWE/NSS", "VARIABLE": "Gaia variabel", "≠ Gaia-V": "VSP/Gaia-V-Konflikt"}
    out: dict[str, int] = {}
    for r in res["reasons"]:
        seen = set()
        for part in filter(None, r.split("; ")):
            for key, cat in cats.items():
                if key in part:
                    seen.add(cat)
                    break
        for c in seen:
            out[c] = out.get(c, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
