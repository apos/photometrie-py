"""Tests fuer varphot.vsp (offline: gespeicherte AAVSO-VSP-Antwort fuer Delta Cep, Gaia per Monkeypatch)."""
import json
from pathlib import Path

import numpy as np
import pytest
from astropy.table import Table

from varphot import vsp as V

DATA = Path(__file__).parent / "data"
DELCEP = {"name": "* del Cep", "ra": 337.29276110013086, "dec": 58.415193781569435, "BV": 0.60}


@pytest.fixture(scope="module")
def table():
    return V.vsp_table(json.loads((DATA / "vsp_delta_cep_180_11.json").read_text()))


def test_table_parsing(table):
    assert len(table) == 40
    r = table[table["auid"] == "000-BNR-681"][0]
    assert r["label"] == "63" and r["V"] == pytest.approx(6.294)
    assert r["ra"] == pytest.approx(337.2887, abs=1e-3) and r["dec"] == pytest.approx(58.4048, abs=1e-3)
    assert r["BV"] == pytest.approx(-0.010, abs=1e-3)


@pytest.mark.parametrize("comment, expected", [
    ("NSV 25915", ["NSV-Eintrag (Verdacht auf Veränderlichkeit)"]),
    ("HD 212454 - ACV, ampl 0.004 mag.", []),                       # Amplitude vernachlaessigbar
    ("HD 239991 - ORG: - V= 8.58, ampl. 0.008 TESS. Only for visual use.",
     ["nur für visuelle Beobachtung"]),
    ("RR Lyr-type, ampl 0.5 mag", ["als veränderlich gelistet"]),
    ("BINO_COMP", []),
    ("", []),
])
def test_vsp_flags(comment, expected):
    assert V.vsp_flags(comment) == expected


def test_in_field_circle_and_rectangle():
    f = (2.49, 1.67)
    # 0,7 Grad noerdlich: im rotationssicheren Kreis (r = 0,785), 1,0 Grad nicht
    assert bool(V.in_field(0.0, 0.7, 0.0, 0.0, f, 0.0))
    assert not bool(V.in_field(0.0, 1.0, 0.0, 0.0, f, 0.0))
    # 1,1 Grad oestlich: nur im Rechteck mit langer Seite Ost-West (PA 0), nicht bei PA 90
    assert bool(V.in_field(1.1, 0.0, 0.0, 0.0, f, 0.0, pa_deg=0))
    assert not bool(V.in_field(1.1, 0.0, 0.0, 0.0, f, 0.0, pa_deg=90))


def test_v_from_gaia():
    assert V.v_from_gaia(9.0, 0.0) == pytest.approx(9.027, abs=1e-3)
    assert V.v_from_gaia(9.0, 1.0) == pytest.approx(9.0 - (-0.02704 + 0.01424 - 0.2156 + 0.01426), abs=1e-9)


def test_selection_without_gaia(table):
    res = V.select_comps_catalog(table, DELCEP, use_gaia=False)
    nsv = res[res["auid"] == "000-BNR-681"][0]                         # NSV + Farbe
    assert nsv["role"] == "verworfen" and "NSV" in nsv["reasons"]
    vis = res[res["auid"] == "000-BKS-048"][0]
    assert vis["role"] == "verworfen" and "visuell" in vis["reasons"]
    far = res[res["auid"] == "000-BCQ-368"][0]                          # 1,4 Grad entfernt
    assert "außerhalb des Feldes" in far["reasons"]
    assert (res["role"] != "verworfen").sum() >= 4
    assert all(r["reasons"] for r in res if r["role"] == "verworfen")   # jede Ablehnung begruendet


def test_pa_known_gives_more_comps(table):
    safe = V.select_comps_catalog(table, DELCEP, use_gaia=False)
    pa0 = V.select_comps_catalog(table, DELCEP, {"field_pa_deg": 0}, use_gaia=False)
    assert (pa0["role"] != "verworfen").sum() > (safe["role"] != "verworfen").sum()


def _fake_gaia(monkeypatch, rows_for):
    cols = ["source_id", "ra", "dec", "G", "bp_rp", "varflag", "ruwe", "nss"]

    def fake(ra, dec, radius_arcsec=40, gmax=18, cache_dir=None, force=False):
        rows = rows_for(ra, dec)
        return Table(rows=rows, names=cols) if rows else Table(names=cols, dtype=[int, float, float, float, float, "U16", float, int])
    monkeypatch.setattr(V, "gaia_cone", fake)


def test_gaia_stage_rejects_neighbour_ruwe_and_inconsistency(table, monkeypatch):
    def rows_for(ra, dec):
        r = table[np.isclose(table["ra"], ra) & np.isclose(table["dec"], dec)][0]
        vg = r["V"]                                   # Gaia-V == VSP-V (bp_rp = 0 -> G = V - 0.027)
        me = (1, ra, dec, vg - 0.027, 0.0, "NOT_AVAILABLE", 1.0, 0)
        out = [me]
        if r["auid"] == "000-BNR-684":                # heller Nachbar in 10"
            out.append((2, ra + 10 / 3600, dec, vg - 0.027 + 1.0, 0.5, "NOT_AVAILABLE", 1.0, 0))
        if r["auid"] == "000-BPG-270":                # hohe RUWE
            out[0] = (1, ra, dec, vg - 0.027, 0.0, "NOT_AVAILABLE", 3.0, 0)
        if r["auid"] == "000-BNR-686":                # VSP-V passt nicht zu Gaia
            out[0] = (1, ra, dec, vg - 0.027 + 0.8, 0.0, "NOT_AVAILABLE", 1.0, 0)
        return out
    _fake_gaia(monkeypatch, rows_for)
    res = V.select_comps_catalog(table, DELCEP, {"field_pa_deg": 0})
    by = {r["auid"]: r for r in res}
    assert "Gaia-Nachbar" in by["000-BNR-684"]["reasons"]
    assert "RUWE" in by["000-BPG-270"]["reasons"]
    assert "≠ Gaia-V" in by["000-BNR-686"]["reasons"]
    assert by["000-BNR-686"]["role"] == "verworfen"


def test_reject_summary_counts(table):
    res = V.select_comps_catalog(table, DELCEP, use_gaia=False)
    s = V.reject_summary(res)
    assert s["Feld"] >= 20 and "veränderlich/NSV" in s


# ------------------------------------------------------------ Gaia-Feldsterne (fill_with_gaia)
def _cands(rows):
    cols = ["source_id", "ra", "dec", "G", "bp_rp", "varflag", "ruwe", "nss"]
    return Table(rows=rows, names=cols)


def test_fill_with_gaia_adds_isolated_stars_and_logs_rejections(table, monkeypatch):
    ra0, dec0 = DELCEP["ra"], DELCEP["dec"]
    bprp_t = float(V.bprp_from_bv(DELCEP["BV"]))
    # G so waehlen, dass V (aus G, BP-RP) im Bereich 5,5-10,5 liegt
    rows = [
        (11, ra0, dec0 + 0.20, 8.0, bprp_t, "NOT_AVAILABLE", 1.0, 0),          # gut
        (12, ra0, dec0 - 0.25, 8.5, bprp_t + 0.05, "NOT_AVAILABLE", 1.0, 0),   # gut
        (13, ra0, dec0 + 0.30, 8.2, bprp_t + 0.02, "NOT_AVAILABLE", 1.0, 0),   # Nachbar -> verworfen (Rang 2)
        (14, ra0, dec0 + 0.35, 8.0, bprp_t, "VARIABLE", 1.0, 0),               # Gaia-variabel -> nie Kandidat
        (15, ra0, dec0 - 0.30, 8.0, bprp_t + 1.0, "NOT_AVAILABLE", 1.0, 0),    # Farbe passt nicht
        (16, ra0, dec0 + 1.50, 8.0, bprp_t, "NOT_AVAILABLE", 1.0, 0),          # ausserhalb des Feldes
        (17, ra0, dec0 + 0.005, 8.0, bprp_t, "NOT_AVAILABLE", 1.0, 0),         # im Halo des Ziels
    ]
    monkeypatch.setattr(V, "_gaia_candidates_raw", lambda *a, **k: _cands(rows))

    def fake_cone(ra, dec, radius_arcsec=36, gmax=18, cache_dir=None, force=False):
        me = [r for r in rows if abs(r[2] - dec) < 1e-9][0]
        out = [(me[0], ra, dec, me[3], me[4], "NOT_AVAILABLE", 1.0, 0)]
        if me[0] == 13:                                   # Nachbar 10" entfernt, nur 1 mag schwaecher
            out.append((99, ra + 10 / 3600 / np.cos(np.radians(dec)), dec, me[3] + 1.0, 0.9, "NOT_AVAILABLE", 1.0, 0))
        return _cands(out)
    monkeypatch.setattr(V, "gaia_cone", fake_cone)

    cfg = {"field_pa_deg": 0, "comp_n": 10}                      # Ziel 10 Comps; VSP allein liefert 9, kein Check
    base = V.select_comps_catalog(table, DELCEP, cfg, use_gaia=False)
    assert int((base["role"] == "comp").sum()) == 9 and not (base["role"] == "check").any()
    res = V.fill_with_gaia(base, DELCEP, cfg)
    g = res[res["source"] == "Gaia"]
    roles = {int(a.split()[-1]): str(r) for a, r in zip(g["auid"], g["role"])}
    assert roles[11] == "comp" and roles[12] == "check"        # 9 VSP-Comps + 1 Gaia-Comp, dann Check
    assert roles[13] == "verworfen"
    assert "Gaia-Nachbar" in [r for a, r in zip(g["auid"], g["reasons"]) if a.endswith(" 13")][0]
    assert not {14, 15, 16, 17} & set(roles)                    # Kandidatenfilter, nicht aufgefuehrt
    assert (res["role"] == "comp").sum() == 10
    assert set(res[res["source"] == "VSP"]["auid"]) == set(base["auid"])   # VSP-Zeilen unveraendert
    assert all(res["V_err"][res["source"] == "Gaia"] == V.VSP_CFG["gaia_v_err"])


def test_fill_with_gaia_noop_when_ensemble_complete(table, monkeypatch):
    called = []
    monkeypatch.setattr(V, "_gaia_candidates_raw", lambda *a, **k: called.append(1))
    base = V.select_comps_catalog(table, DELCEP, {"field_pa_deg": 90}, use_gaia=False)   # 8 Comps
    out = V.fill_with_gaia(base, DELCEP, {"field_pa_deg": 90, "comp_n": 4})
    assert out is base and not called


def test_bprp_from_bv_matches_vsp_gaia_pairs():
    # gemessene Paare (B-V, BP-RP) um del Cep: Naeherung muss im Mittel < 0,2 mag danebenliegen
    pairs = [(0.26, 0.35), (0.34, 0.60), (0.44, 0.74), (0.46, 0.62), (0.58, 0.73), (0.62, 0.78),
             (0.93, 1.34), (0.98, 1.12), (0.99, 1.12)]
    bv, bp = np.array(pairs).T
    assert np.mean(np.abs(V.bprp_from_bv(bv) - bp)) < 0.2


# ------------------------------------------------------------ TAP-Antwortformate und Ausfall-Umschaltung
class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_tap_json_handles_list_rows_and_dict_rows(monkeypatch):
    meta = [{"name": "source_id"}, {"name": "g"}]                     # ARI: kleine Namen, Zeilen als Dicts
    ari = {"metadata": meta, "data": [{"source_id": 1, "g": 9.5}]}
    esa = {"metadata": [{"name": "source_id"}, {"name": "G"}], "data": [[2, 8.5]]}
    q = "SELECT source_id, phot_g_mean_mag AS G FROM gaiadr3.gaia_source"
    monkeypatch.setattr(V, "_TAP_ORDER", [V.GAIA_TAP_ARI])
    monkeypatch.setattr(V.requests, "post", lambda *a, **k: _Resp(ari))
    assert V._tap_json(q) == [{"source_id": 1, "G": 9.5}]
    monkeypatch.setattr(V.requests, "post", lambda *a, **k: _Resp(esa))
    assert V._tap_json(q) == [{"source_id": 2, "G": 8.5}]


def test_tap_json_falls_back_and_demotes_failed_service(monkeypatch):
    calls = []

    def post(url, **k):
        calls.append(url)
        if url == V.GAIA_TAP:
            raise V.requests.Timeout("ESA haengt")
        return _Resp({"metadata": [{"name": "x"}], "data": [[1]]})
    monkeypatch.setattr(V, "_TAP_ORDER", [V.GAIA_TAP, V.GAIA_TAP_ARI])
    monkeypatch.setattr(V.requests, "post", post)
    assert V._tap_json("SELECT 1 AS x") == [{"x": 1}]
    assert calls == [V.GAIA_TAP, V.GAIA_TAP_ARI] and V._TAP_ORDER[0] == V.GAIA_TAP_ARI   # ESA ans Ende
