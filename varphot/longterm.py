"""Langzeit-Analyse: Lichtkurven aus mehreren Sitzungen zusammenführen.

Autor: Axel Pospischil. Stand 2026-11-12.

Typischer Ablauf::

    sessions = find_sessions("del Cep", data_dir="/mnt/daten/VARPHOT")
    lc = load_lightcurves(sessions)
    folded = phase_fold(lc, period=5.366249, t0=2460000.0)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# Pflicht-Spalten für eine gültige Langzeitkurve
_REQUIRED = {"bjd_tdb", "mag", "mag_err"}
# Optionale Spalten, die übernommen werden, wenn vorhanden
_OPTIONAL = ["jd_mid", "airmass", "fwhm_arcsec", "transparency", "zp_scatter",
             "n_comps", "check_minus_cat", "scint_mag"]


def find_sessions(target: str, data_dir: str | Path) -> list[Path]:
    """Alle Ergebnisordner unter *data_dir*, die zu *target* gehören.

    Sucht rekursiv nach ``session.json``-Dateien.  Ein Ordner gilt als
    passend, wenn ``session.target`` mit *target* übereinstimmt (Groß-/
    Kleinschreibung ignoriert) und ein ``zeitreihe.csv`` im zugehörigen
    ``results``-Verzeichnis existiert.

    Rückgabe: sortierte Liste von Pfaden zu den Ergebnisordnern (den
    Verzeichnissen mit ``zeitreihe.csv``).
    """
    data_dir = Path(data_dir).expanduser()
    target_lc = target.lower().strip()
    found: list[Path] = []

    for sj in sorted(data_dir.rglob("session.json")):
        try:
            info = json.loads(sj.read_text(encoding="utf-8"))
        except Exception:
            continue
        if info.get("target", "").lower().strip() != target_lc:
            continue
        # Ergebnisordner ermitteln: aus 'results' oder results/<tag>
        res = info.get("results") or ""
        if res:
            res_path = Path(res)
        else:
            tag = info.get("tag") or "lauf"
            res_path = sj.parent / "results" / tag
        if (res_path / "zeitreihe.csv").exists():
            found.append(res_path)

    return found


def load_lightcurves(sessions: list[Path]) -> pd.DataFrame:
    """Lädt ``zeitreihe.csv`` aus jedem Ergebnisordner und fügt sie zusammen.

    Jede Zeile erhält eine Spalte ``session`` (Name des Ergebnisordners)
    für spätere Farbkodierung.  Nur Nächte mit allen Pflicht-Spalten
    (``bjd_tdb``, ``mag``, ``mag_err``) werden übernommen.

    Rückgabe: DataFrame, sortiert nach BJD_TDB.  Leere Liste → leerer
    DataFrame mit den erwarteten Spalten.
    """
    frames: list[pd.DataFrame] = []
    for res_path in sessions:
        csv = res_path / "zeitreihe.csv"
        try:
            df = pd.read_csv(csv)
        except Exception:
            continue
        missing = _REQUIRED - set(df.columns)
        if missing:
            continue
        df = df[df["mag"].notna() & df["mag_err"].notna() & df["bjd_tdb"].notna()].copy()
        df["session"] = res_path.name
        # optionale Spalten auffüllen, damit concat keine NaN-Spalten erzeugt
        for col in _OPTIONAL:
            if col not in df.columns:
                df[col] = np.nan
        frames.append(df)

    if not frames:
        cols = ["bjd_tdb", "mag", "mag_err", "session"] + _OPTIONAL
        return pd.DataFrame(columns=cols)

    combined = pd.concat(frames, ignore_index=True)
    combined.sort_values("bjd_tdb", inplace=True, ignore_index=True)
    return combined


def phase_fold(
    data: pd.DataFrame,
    period: float,
    t0: float,
    time_col: str = "bjd_tdb",
) -> pd.DataFrame:
    """Phasen-Faltung der Lichtkurve.

    Berechnet ``phase`` ∈ [0, 1) als ``((t - t0) / period) % 1``.
    Rückgabe: Kopie von *data* mit zusätzlicher Spalte ``phase``.
    """
    if period <= 0:
        raise ValueError(f"Periode muss > 0 sein, bekommen: {period}")
    df = data.copy()
    df["phase"] = ((df[time_col] - t0) / period) % 1.0
    return df.sort_values("phase", ignore_index=True)


def nightly_stats(data: pd.DataFrame, time_col: str = "bjd_tdb") -> pd.DataFrame:
    """Tagesmittelwerte der Lichtkurve (eine Zeile pro Nacht).

    Eine Nacht wird durch den ganzzahligen Teil von BJD (JD beginnt um Mittag,
    also ist jede ganze Zahl Mitternacht ±12 h) definiert.  Rückgabe:
    DataFrame mit ``night_jd`` (Mitte der Nacht), ``mag_mean``, ``mag_err_mean``,
    ``n_points``, ``session``.
    """
    df = data.copy()
    df["night"] = np.floor(df[time_col] - 0.5).astype(int)
    rows = []
    for (night, session), grp in df.groupby(["night", "session"], sort=False):
        rows.append({
            "night_jd": float(grp[time_col].mean()),
            "mag_mean": float(grp["mag"].mean()),
            "mag_err_mean": float(grp["mag_err"].mean()),
            "mag_std": float(grp["mag"].std()) if len(grp) > 1 else np.nan,
            "n_points": len(grp),
            "session": session,
        })
    return pd.DataFrame(rows).sort_values("night_jd", ignore_index=True)
