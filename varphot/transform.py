"""Transformation instrumenteller Kanalmagnituden (b, g, r) auf Johnson/Cousins (B, V, R) — Koeffizienten bestimmen und anwenden.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (Notebook 08, KONZEPT.md §11.5).

Warum: Die Farbkanaele einer Bayer-Kamera sind nicht Johnson B/V/R; die Abweichung haengt von der Sternfarbe ab (KONZEPT §11.3). Ohne Koeffizienten meldet man ``TG``/``TB``/``TR``
(``TRANS=NO``); mit Koeffizienten aus einem Feld bekannter Sterne darf man ``V``/``B``/``R`` mit ``TRANS=YES`` melden (AAVSO-Forum, Handbuch §6.7).

Wie (AAVSO DSLR Observing Manual v1.4 §6.5, im Wortlaut gelesen; Gleichungen 6.11–6.18): Instrumentelle Kanaele ``b, v(=g), r``, Katalogwerte ``B, V, R``.
Farbtransformation ``(b−v) = (1/Tbv)·(B−V) + ZP`` (Tbv = Kehrwert der Steigung); Groessentransformationen ``(B−b) = Tb_bv·(B−V) + ZP_b``, ``(V−v) = Tv_bv·(B−V) + ZP_v``,
``(R−r) = Tr_bv·(B−V) + ZP_r`` (Steigungen). Anwendung differentiell gegen einen Comp: ``V_var = Δv + Tv_bv·Δ(B−V) + V_comp`` mit ``Δ(B−V) = Tbv·Δ(b−v)`` (analog B, R).
Extinktion (nur bei weiten Feldern/grossen Zenitdistanzen, Gl. 6.19–6.22): zusaetzlicher Term ``−k·ΔX``.

Quellen: AAVSO DSLR Observing Manual v1.4 (2016), §6.5–6.6 (gelesen); Kloppenborg et al., JAAVSO 40 (2012) — dort fuer das Ebenenverfahren zitiert, nicht eingesehen;
Henden & Kaitchuck 1990, Astronomical Photometry (im Handbuch zitiert, nicht eingesehen); Variante der Koeffizientendefinition: Kamenec 2023, OEJV 243 (gelesen).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


def linfit(x, y, clip: float = 3.0, iters: int = 5, min_n: int = 4) -> dict:
    """Gerade ``y = a·x + b`` durch Kleinste Quadrate mit iterativem Sigma-Clipping.

    Rueckgabe: ``slope``, ``intercept``, ``slope_err``, ``rms`` (der verwendeten Punkte), ``r2``, ``n`` (alle), ``n_used``, ``mask`` (verwendete Punkte).
    Punkte mit ``|Residuum| > clip·σ`` (σ = robuste Streuung, MAD) fliegen heraus, bis die Auswahl stabil ist (mindestens ``min_n`` Punkte bleiben).
    Grenze: Eine Gerade; kein Gewicht je Punkt (alle Standardsterne zaehlen gleich).
    """
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    use = ok.copy()
    for _ in range(iters):
        if use.sum() < min_n:
            raise ValueError(f"zu wenige Punkte ({int(use.sum())} < {min_n})")
        a, b = np.polyfit(x[use], y[use], 1)
        res = y - (a * x + b)
        sig = 1.4826 * np.median(np.abs(res[use] - np.median(res[use]))) or 1e-9
        new = ok & (np.abs(res) <= clip * max(sig, 1e-6))
        if new.sum() < min_n or (new == use).all():
            break
        use = new
    a, b = np.polyfit(x[use], y[use], 1)
    res = y[use] - (a * x[use] + b)
    n = int(use.sum())
    s2 = float(np.sum(res ** 2) / max(n - 2, 1))
    sxx = float(np.sum((x[use] - x[use].mean()) ** 2))
    ss_tot = float(np.sum((y[use] - y[use].mean()) ** 2))
    return dict(slope=float(a), intercept=float(b), slope_err=float(np.sqrt(s2 / sxx)) if sxx > 0 else float("nan"),
                rms=float(np.sqrt(np.mean(res ** 2))), r2=1 - float(np.sum(res ** 2)) / ss_tot if ss_tot > 0 else float("nan"),
                n=int(ok.sum()), n_used=n, mask=use)


@dataclass
class TransformSolution:
    """Satz von Transformationskoeffizienten (ein Aufbau: Kamera + Einstellung + Filter + Optik)."""
    camera_model: str = ""
    camera_setting: str = ""
    created: str = ""
    Tbv: float | None = None               # Farbe: Δ(B−V) = Tbv·Δ(b−v)
    Tbv_err: float | None = None
    Tb_bv: float | None = None             # (B−b) = Tb_bv·(B−V) + ZP
    Tb_bv_err: float | None = None
    Tv_bv: float | None = None
    Tv_bv_err: float | None = None
    Tr_bv: float | None = None
    Tr_bv_err: float | None = None
    k_extinction: dict = field(default_factory=dict)       # k je Kanal [mag/Luftmasse], falls bestimmt
    bv_range: tuple = (None, None)         # Farbbereich der Standardsterne (Gueltigkeit)
    n_stars: int = 0
    rms: dict = field(default_factory=dict)                # Streuung der Regressionen je Groesse
    validation: dict = field(default_factory=dict)         # Leave-one-out: rms transformiert vs. nicht transformiert
    warnings: list = field(default_factory=list)
    notes: str = ""

    def save(self, path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False, default=float) + "\n", encoding="utf-8")
        return p

    @classmethod
    def load(cls, path) -> "TransformSolution":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        d["bv_range"] = tuple(d.get("bv_range", (None, None)))
        return cls(**d)


def solution_path(model: str, setting: str) -> Path:
    """Dateipfad ``PHOTOMETRIE_PY_DATA/transform_<Modell>_<Einstellung>.json`` (neben dem Kameraprofil)."""
    from .camera_presets import slug
    from .observer import data_dir
    base = data_dir() if data_dir().is_dir() else Path("~/.config/varphot").expanduser()
    return base / f"transform_{slug(model)}_{slug(setting)}.json"


def _forbid_gaia(cat: pd.DataFrame) -> None:
    """Gaia-abgeleitete Werte duerfen **nicht** in die Transformation: ``source`` mit „Gaia“ -> Fehler.

    Warum: Die Pruefung gegen die AAVSO-Sequenz (KONZEPT §11.7) zeigte fuer Gaia-synthetisches R eine Systematik von +0,045 mag und 0,03–0,05 mag Streuung in V/B; Koeffizienten aus solchen Katalogwerten
    wuerden den Fehler des Katalogs in jede gemeldete Magnitude tragen. Standardsterne muessen aus den AAVSO-Standardfeldern, der AAVSO-Sequenz oder Landolt/Stetson stammen.
    """
    if "source" in cat and cat["source"].astype(str).str.contains("gaia", case=False).any():
        raise ValueError("Katalog enthaelt Gaia-abgeleitete Werte (Spalte 'source'): fuer die Transformation nur AAVSO-Standardfeld/-Sequenz oder Landolt/Stetson verwenden")
    if "id" in cat and cat["id"].astype(str).str.match(r"^g\d+$").any():
        raise ValueError("Katalog enthaelt Sterne mit Gaia-Kennung (g1, g2 …) aus NB03: nicht als Standardsterne geeignet")


def catalog_from_vsp_table(vsp, source: str = "AAVSO") -> pd.DataFrame:
    """Katalogtabelle ``id, ra, dec, B, V, R`` aus einer AAVSO-VSP-Tabelle (:func:`varphot.vsp.fetch_vsp`); nur Sterne mit B und V (R = Rc, wenn vorhanden).

    Warum: Als Standardfeld taugt jedes Feld, dessen Sterne B/V (und R) aus der AAVSO-Sequenz kennen — z. B. das Feld des Ziels (Handbuch §6.6: die Comps im Bild eichen die
    Transformation). Grenze: Sequenzsterne sind weniger zahlreich und weniger farbenreich als ein Standardhaufen (M 67, NGC 7790); der Farbbereich begrenzt die Gueltigkeit.
    """
    df = vsp.to_pandas() if hasattr(vsp, "to_pandas") else pd.DataFrame(vsp)
    out = pd.DataFrame(dict(id=df["label"].astype(str), source=source, ra=df["ra"].astype(float), dec=df["dec"].astype(float),
                            B=pd.to_numeric(df["B"], errors="coerce"), V=pd.to_numeric(df["V"], errors="coerce"),
                            R=pd.to_numeric(df["Rc"], errors="coerce") if "Rc" in df else np.nan))
    return out.dropna(subset=["B", "V"]).reset_index(drop=True)


def instrumental_table(meas: dict[str, pd.DataFrame], star_ids=None, min_frames: int = 2) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mittlere instrumentelle Magnituden je Stern und Kanal aus Messtabellen (NB04, lang: ``file, star_id, flux, airmass, frame_flags``).

    Warum: Die Regression braucht je Stern *einen* Wert je Kanal; Aufnahmen schwanken im Pegel (Transparenz, Belichtung). Wie: ``m = −2,5·log10(flux)`` je Bild; je Bild wird der Median der
    Differenz zum Sternmittel abgezogen (entfernt gemeinsame Pegelspruenge, nicht die Farbabhaengigkeit); Mittel ueber die Bilder. Nur Bilder ohne ``frame_flags`` und Sterne mit mindestens
    ``min_frames`` Messungen. Rueckgabe ``(instr, frames)``: ``instr`` mit Spalten je Kanal (``mean``) und ``<Kanal>_sd``; ``frames`` (``channel, file, airmass, offset``) fuer die Extinktion.
    Grenze: Die absoluten Nullpunkte sind willkuerlich (gehen in ``ZP`` ein); nur Farbindizes und Differenzen haben Bedeutung.
    """
    cols, frame_rows = {}, []
    for ch, df in meas.items():
        d = df[df.get("frame_flags", "") == ""] if "frame_flags" in df else df
        d = d[d["flux"] > 0]
        if star_ids is not None:
            d = d[d["star_id"].isin(star_ids)]
        m = d.pivot_table(index="file", columns="star_id", values="flux", aggfunc="first").pipe(lambda t: -2.5 * np.log10(t))
        ref = m.median(axis=0)
        off = (m - ref).median(axis=1)
        mc = m.sub(off, axis=0)
        cnt = mc.notna().sum()
        mean, sd = mc.mean(), mc.std(ddof=1)
        mean[cnt < min_frames], sd[cnt < min_frames] = np.nan, np.nan
        cols[ch], cols[ch + "_sd"] = mean, sd
        am = d.drop_duplicates("file").set_index("file")["airmass"] if "airmass" in d else pd.Series(np.nan, index=m.index)
        frame_rows += [dict(channel=ch, file=f, airmass=am.get(f, np.nan), offset=float(o)) for f, o in off.items()]
    return pd.DataFrame(cols), pd.DataFrame(frame_rows)


def fit_extinction(frames: pd.DataFrame, min_range: float = 0.3) -> dict:
    """Extinktionskoeffizient ``k`` [mag/Luftmasse] je Kanal aus dem Gang des Bildnullpunkts mit der Luftmasse (``offset = ZP + k·X``).

    Warum/Grenze: Bei engen Feldern gilt differentielle Extinktion als vernachlaessigbar (Handbuch §6.5.1) — dann wird ``k`` nicht gebraucht. Der Nullpunktgang enthaelt auch Transparenzaenderungen;
    ``k`` ist nur sinnvoll bei klarer Nacht und Luftmassenbereich ≥ ``min_range`` (sonst Eintrag fehlt). Rueckgabe ``{Kanal: k}``.
    """
    out = {}
    for ch, g in frames.groupby("channel"):
        g = g.dropna(subset=["airmass", "offset"])
        if len(g) >= 4 and g["airmass"].max() - g["airmass"].min() >= min_range:
            out[ch] = float(np.polyfit(g["airmass"], g["offset"], 1)[0])
    return out


def fit_transform(cat: pd.DataFrame, instr: pd.DataFrame, channels: dict | None = None, clip: float = 3.0, min_n: int = 6) -> TransformSolution:
    """Transformationskoeffizienten aus Standardsternen (Katalog ``B, V, R``) und instrumentellen Kanaelen (``instr``: Spalten ``b``, ``g``, ``r``; Index = Stern-ID wie ``cat['id']``).

    Warum/Wie: Gl. 6.15–6.18 des AAVSO-Handbuchs. ``Tbv`` = 1/Steigung von ``(b−g)`` gegen ``(B−V)``; ``Tb_bv`` = Steigung von ``(B−b)`` gegen ``(B−V)``; ``Tv_bv`` = Steigung von ``(V−g)``;
    ``Tr_bv`` = Steigung von ``(R−r)`` (nur mit R im Katalog und r gemessen). Jeweils Gerade mit Sigma-Clipping (:func:`linfit`); mindestens ``min_n`` Sterne.
    Grenzen: Der (B−V)-Bereich der Sterne begrenzt die Gueltigkeit (``bv_range``); Handbuch/Forum: bei starker Emission/Absorption nicht transformieren, Ziele mit (V−R) < 1.
    Validierung: ``tests/test_transform.py`` (synthetisch, Koeffizienten ±5 %).
    """
    _forbid_gaia(cat)
    channels = channels or {"b": "b", "v": "g", "r": "r"}
    c = cat.set_index("id")
    idx = [i for i in c.index if i in instr.index]
    if len(idx) < min_n:
        raise ValueError(f"zu wenige Sterne in Katalog und Messung ({len(idx)} < {min_n})")
    C, I = c.loc[idx], instr.loc[idx]
    bv = (C["B"] - C["V"]).to_numpy()
    b, v, r = (I[channels[k]].to_numpy() if channels[k] in I else np.full(len(idx), np.nan) for k in ("b", "v", "r"))
    sol = TransformSolution(n_stars=len(idx), bv_range=(float(np.nanmin(bv)), float(np.nanmax(bv))))
    f = linfit(bv, b - v, clip, min_n=min_n)                         # (b−v) = (1/Tbv)(B−V) + ZP
    sol.Tbv, sol.Tbv_err = 1.0 / f["slope"], f["slope_err"] / f["slope"] ** 2
    sol.rms["Tbv"] = f["rms"]
    for name, cat_mag, inst in (("Tb_bv", C["B"].to_numpy(), b), ("Tv_bv", C["V"].to_numpy(), v), ("Tr_bv", C["R"].to_numpy() if "R" in C else np.full(len(idx), np.nan), r)):
        if np.isfinite(inst).sum() >= min_n and np.isfinite(cat_mag).sum() >= min_n:
            g = linfit(bv, cat_mag - inst, clip, min_n=min_n)
            setattr(sol, name, g["slope"]); setattr(sol, name + "_err", g["slope_err"]); sol.rms[name] = g["rms"]
    if f["r2"] < 0.7:
        sol.warnings.append(f"Farbtransformation (b−g gegen B−V): R² = {f['r2']:.2f} — schwache Abhaengigkeit, Farbbereich zu klein oder Kanaele zu verrauscht")
    if sol.bv_range[1] - sol.bv_range[0] < 0.6:
        sol.warnings.append(f"Farbbereich der Standardsterne nur {sol.bv_range[1] - sol.bv_range[0]:.2f} mag in B−V (empfohlen ≥ 0,6): Steigungen unsicher")
    if len(idx) < 12:
        sol.warnings.append(f"nur {len(idx)} Standardsterne (mehr als ~12 empfohlen)")
    return sol


def transform_target(dB: float | None, dV: float, dR: float | None, comp: dict, sol: TransformSolution, dX: float = 0.0,
                     k: dict | None = None, dBV_catalog: float | None = None) -> dict:
    """Transformierte Magnituden eines Ziels gegen einen Comp (Handbuch Gl. 6.11–6.14, mit Extinktionsterm Gl. 6.19–6.21 bei ``dX`` ≠ 0).

    ``dB, dV, dR``: instrumentelle Differenzen Ziel − Comp je Kanal (b, g, r); ``comp``: Katalogwerte ``B, V, R`` des Comps; ``dBV_catalog``: falls gegeben, Katalog-Farbdifferenz statt der
    instrumentellen (Handbuch: bei Veraenderlichen mit wechselnder Farbe die instrumentelle verwenden). Rueckgabe: ``V`` (immer), ``B``/``R`` (wenn Koeffizienten und Differenzen da), ``BV``
    (Farbindex des Ziels, wenn der Comp B und V hat). Grenzen: wie in :func:`fit_transform`; ohne ``Tbv`` oder ohne ``dB`` bleibt nur der Katalog-Farbterm.
    """
    k = k or {}
    if dBV_catalog is not None:
        dcol = dBV_catalog
    elif dB is not None and sol.Tbv:
        dcol = sol.Tbv * (dB - dV)
    else:
        raise ValueError("keine Farbdifferenz: dB und Tbv oder dBV_catalog angeben")
    ext = lambda ch: -k.get(ch, 0.0) * dX
    out = {"V": comp["V"] + dV + (sol.Tv_bv or 0.0) * dcol + ext("g")}
    if dB is not None and sol.Tb_bv is not None:
        out["B"] = comp["B"] + dB + sol.Tb_bv * dcol + ext("b")
    if dR is not None and sol.Tr_bv is not None and comp.get("R") is not None and np.isfinite(comp["R"]):
        out["R"] = comp["R"] + dR + sol.Tr_bv * dcol + ext("r")
    if comp.get("B") is not None and "B" in out:
        out["BV"] = (comp["B"] - comp["V"]) + dcol
    return out


def loo_validation(cat: pd.DataFrame, instr: pd.DataFrame, sol: TransformSolution, channels: dict | None = None) -> dict:
    """Leave-one-out-Pruefung: jeder Standardstern wird als „Veraenderlicher“ gegen alle anderen als Comps transformiert und mit seinem Katalogwert verglichen.

    Warum: Zeigt, wie gut die Koeffizienten sind und ob sich die Transformation gegenueber den *nicht transformierten* Werten (``TG``: ``Δv + V_comp``) lohnt — das Handbuch erwartet
    transformiertes V innerhalb ~0,02 mag (Tab. 6.1, E1-Standardsterne). Rueckgabe: je Groesse ``rms_transformed``, ``rms_standardized`` (ohne Transformation), ``n``, ``mean``
    (Abweichung transformiert − Katalog) und die Rohabweichungen unter ``resid_*``. Grenze: Die Koeffizienten wurden an denselben Sternen bestimmt (leicht optimistisch).
    """
    channels = channels or {"b": "b", "v": "g", "r": "r"}
    c = cat.set_index("id")
    idx = [i for i in c.index if i in instr.index]
    C, I = c.loc[idx], instr.loc[idx]
    out = {}
    for band, ch, cmag, tname in (("B", "b", "B", "Tb_bv"), ("V", "v", "V", "Tv_bv"), ("R", "r", "R", "Tr_bv")):
        col = channels[ch]
        if getattr(sol, tname) is None or col not in I or cmag not in C:
            continue
        T = getattr(sol, tname)
        tr, st = [], []
        for i in range(len(idx)):
            if not np.isfinite(I[col].iloc[i]) or not np.isfinite(C[cmag].iloc[i]):
                continue
            vals_tr, vals_st = [], []
            for j in range(len(idx)):
                if j == i or not np.isfinite(I[col].iloc[j]) or not np.isfinite(C[cmag].iloc[j]):
                    continue
                d = I[col].iloc[i] - I[col].iloc[j]
                dbv = sol.Tbv * ((I[channels["b"]].iloc[i] - I[channels["v"]].iloc[i]) - (I[channels["b"]].iloc[j] - I[channels["v"]].iloc[j]))
                vals_tr.append(C[cmag].iloc[j] + d + T * dbv)
                vals_st.append(C[cmag].iloc[j] + d)
            if vals_tr:
                tr.append(np.median(vals_tr) - C[cmag].iloc[i]); st.append(np.median(vals_st) - C[cmag].iloc[i])
        if tr:
            tr, st = np.array(tr), np.array(st)
            out[band] = dict(rms_transformed=float(np.sqrt(np.mean(tr ** 2))), rms_standardized=float(np.sqrt(np.mean(st ** 2))), n=len(tr),
                             mean=float(tr.mean()), resid_transformed=tr.tolist(), resid_standardized=st.tolist())
    return out


def transformed_light_curve(meas: dict[str, pd.DataFrame], stars: pd.DataFrame, target_id, sol: TransformSolution, channels: dict | None = None,
                            min_comps: int = 4, clip: float = 3.0) -> pd.DataFrame:
    """Transformierte Lichtkurve (B, V, R, B−V) des Ziels aus den Messtabellen der Farbkanaele — Anwendung der Koeffizienten (Handbuch Gl. 6.11–6.14).

    Warum: Erst damit darf man ``V``/``B``/``R`` mit ``TRANS=YES`` melden. Wie: Je Bild und Comp ``j`` (mit Katalog-B und -V): instrumentelle Differenzen ``Δb, Δg, Δr`` Ziel − Comp aus
    ``m = −2,5·log10(flux)``; :func:`transform_target` (Farbe aus den instrumentellen Kanaelen, ``Δ(B−V) = Tbv·Δ(b−g)``); Median ueber alle Comps (Ausreisser > ``clip``·MAD verworfen), Streuung/√n als Fehler.
    Nur Bilder ohne ``frame_flags`` und mit Messung des Ziels in den Kanaelen b und g (r optional). Die Luftmasse des Ziels und der Comps im selben Bild gilt als gleich (enges Feld; Handbuch §6.5.1).
    Rueckgabe: ``file, jd_mid, airmass, B, V, R, BV, V_err, n_comps``. Grenzen: Gueltig im Farbbereich der Standardsterne (``sol.bv_range``) und fuer geeignete Sterne ((V−R) < 1, keine starken Emissionslinien);
    der Katalog der Comps muss AAVSO-Werte tragen (Gaia-abgeleitete Comps werden abgelehnt, :func:`_forbid_gaia`). ``stars``: Spalten ``id, role, B, V`` (``R`` optional); Rolle ``comp``.
    Validierung: ``tests/test_transform.py``.
    """
    _forbid_gaia(stars)
    channels = channels or {"b": "b", "v": "g", "r": "r"}
    comps = stars[(stars["role"] == "comp") & stars["B"].notna() & stars["V"].notna()].set_index("id")
    wide, info = {}, None
    for ch, df in meas.items():
        d = df[(df["frame_flags"] == "") & (df["flux"] > 0)] if "frame_flags" in df else df[df["flux"] > 0]
        wide[ch] = d.pivot_table(index="file", columns="star_id", values="flux", aggfunc="first").pipe(lambda t: -2.5 * np.log10(t))
        if info is None or ch == channels["v"]:
            info = d.drop_duplicates("file").set_index("file")[[c for c in ("jd_mid", "airmass") if c in d]]
    bch, vch, rch = channels["b"], channels["v"], channels["r"]
    rows = []
    for f in wide[bch].index.intersection(wide[vch].index):
        mb, mv = wide[bch].loc[f], wide[vch].loc[f]
        mr = wide[rch].loc[f] if rch in wide and f in wide[rch].index else None
        if target_id not in mb.index or target_id not in mv.index or not (np.isfinite(mb[target_id]) and np.isfinite(mv[target_id])):
            continue
        vals = {"B": [], "V": [], "R": [], "BV": []}
        for j, cj in comps.iterrows():
            if j not in mb.index or j not in mv.index or not (np.isfinite(mb[j]) and np.isfinite(mv[j])):
                continue
            dB, dV = mb[target_id] - mb[j], mv[target_id] - mv[j]
            dR = (mr[target_id] - mr[j]) if mr is not None and target_id in mr.index and j in mr.index and np.isfinite(mr[target_id]) and np.isfinite(mr[j]) else None
            try:
                o = transform_target(dB, dV, dR, dict(B=cj["B"], V=cj["V"], R=cj.get("R")), sol)
            except ValueError:
                continue
            for k in vals:
                if k in o:
                    vals[k].append(o[k])
        if len(vals["V"]) < min_comps:
            continue
        def robust(x):
            x = np.asarray(x, float)
            med = np.median(x)
            mad = 1.4826 * np.median(np.abs(x - med)) or 1e-9
            keep = np.abs(x - med) <= clip * max(mad, 0.005)
            return float(np.median(x[keep])), float(np.std(x[keep], ddof=1) / np.sqrt(keep.sum())) if keep.sum() > 1 else float("nan"), int(keep.sum())
        V, Ve, n = robust(vals["V"])
        row = dict(file=f, V=V, V_err=Ve, n_comps=n)
        for k in ("B", "R", "BV"):
            row[k] = robust(vals[k])[0] if len(vals[k]) >= min_comps else float("nan")
        for c in ("jd_mid", "airmass"):
            row[c] = info[c].get(f, np.nan) if c in info else np.nan
        rows.append(row)
    cols = ["file", "jd_mid", "airmass", "B", "V", "R", "BV", "V_err", "n_comps"]
    return pd.DataFrame(rows, columns=cols).sort_values("jd_mid" if rows else "file").reset_index(drop=True)


def transformed_with_check(meas: dict[str, pd.DataFrame], stars: pd.DataFrame, target_id, sol: TransformSolution, check_id=None, **kw) -> pd.DataFrame:
    """Transformierte Lichtkurve des Ziels **und** des Check-Sterns (Spalten ``V_check``, ``B_check``) — dieselbe Rechnung (Handbuch §6.7: im Feld KMAG gehoert die transformierte Check-Magnitude).

    Warum: Der Check-Stern ist die einzige Gegenprobe der Transformation: weicht sein transformierter Wert im Mittel vom Katalog ab, stimmt etwas nicht (Koeffizienten, Comps, Farbbereich). Wie: ``check_id`` wird wie ein Ziel
    behandelt (Rolle ``check`` zaehlt nicht als Vergleichsstern), das Ergebnis per ``file`` angefuegt. Ohne ``check_id`` unveraendert :func:`transformed_light_curve`. Validierung: ``tests/test_transform.py``.
    """
    lc = transformed_light_curve(meas, stars, target_id, sol, **kw)
    if check_id is None:
        return lc
    ck = transformed_light_curve(meas, stars, check_id, sol, **kw)[["file", "V", "B"]].rename(columns={"V": "V_check", "B": "B_check"})
    return lc.merge(ck, on="file", how="left")
