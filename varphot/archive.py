"""Archivierung und Projektdokumentation nach einer Messreihe.

Autor: Axel Pospischil. Stand 2026-11-12. (KONZEPT §73)

Typischer Ablauf::

    from varphot.archive import archive_session, archive_dir_default
    dest = archive_session(sess, images="best")
    print(f"Archiv: {dest}")

Ordnerstruktur im Archiv::

    <archiv_root>/<target_aavso>/<JJJJ-MM-TT>_<filter>/
        zeitreihe.csv
        messtabelle.csv          # optional
        aavso_*.txt              # AAVSO-Exportdatei (falls vorhanden)
        lichtkurve.png
        chart.png
        bericht.md               # Nacht-Bericht mit eingebetteten Plots
    <archiv_root>/<target_aavso>/
        index.md                 # Ziel-Index, wird bei jedem Archivaufruf aktualisiert

Bildauswahl (``images``):
    ``"none"``  — keine Einzelbilder
    ``"first"`` — erstes Bild der Reihe (lights/)
    ``"best"``  — schärfstes Bild (kleinstes fwhm_arcsec in zeitreihe.csv)
    ``"all"``   — alle Einzelbilder (kann sehr groß sein)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from varphot import __version__
from varphot.session import Session

# Defaults-Datei neben observer.json
_ARCHIVE_DEFAULTS_FILE = "archive_defaults.json"


# ---------------------------------------------------------------------------
# Öffentliche Hilfsfunktionen
# ---------------------------------------------------------------------------

def archive_dir_default(data_dir: Path | None = None) -> Path:
    """Standard-Archivordner: `<data_dir>/archiv/` oder `~/VARPHOT_ARCHIV/`."""
    if data_dir is None:
        from varphot.observer import data_dir as _dd
        data_dir = _dd()
    if data_dir.is_dir():
        return data_dir / "archiv"
    return Path("~/VARPHOT_ARCHIV").expanduser()


def load_archive_defaults(data_dir: Path | None = None) -> dict:
    """Lädt gespeicherte Archiv-Einstellungen oder gibt leeres Dict zurück."""
    if data_dir is None:
        from varphot.observer import data_dir as _dd
        data_dir = _dd()
    p = data_dir / _ARCHIVE_DEFAULTS_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_archive_defaults(defaults: dict, data_dir: Path | None = None) -> Path:
    """Speichert Archiv-Einstellungen (Bildauswahl, Archivordner …)."""
    if data_dir is None:
        from varphot.observer import data_dir as _dd
        data_dir = _dd()
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / _ARCHIVE_DEFAULTS_FILE
    p.write_text(json.dumps(defaults, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Kern: eine Sitzung archivieren
# ---------------------------------------------------------------------------

def archive_session(
    sess: Session,
    archive_root: Path | str | None = None,
    images: str = "best",
    copy_messtabelle: bool = False,
    copy_masters: bool = False,
    excel: bool = True,
) -> Path:
    """Archiviert eine abgeschlossene Sitzung.

    ``images``: ``"none"``, ``"first"``, ``"best"`` (Standard), ``"all"``.
    ``copy_messtabelle``: messtabelle.csv ebenfalls kopieren (groß, Standard: nein).
    ``copy_masters``: Pfade der Kalibrationsmaster in projekt.json eintragen (Standard: nein, nie kopieren).
    ``excel``: Excel-Export der Zeitreihe (Standard: ja).

    Nach jedem Archivlauf wird automatisch ein kumulatives PDF aller Nächte dieses Ziels erstellt.
    Pandoc + XeLaTeX müssen installiert sein (macOS: brew install pandoc && brew install --cask mactex).

    Rückgabe: Pfad des erstellten Archivordners.
    """
    if archive_root is None:
        archive_root = archive_dir_default()
    archive_root = Path(archive_root).expanduser()

    results = sess.results_dir()
    lc_path = results / "zeitreihe.csv"
    if not lc_path.exists():
        raise FileNotFoundError(f"zeitreihe.csv nicht gefunden in {results} — NB02 ausführen")

    lc = pd.read_csv(lc_path)

    # Ziel-Name: AAVSO-Konvention (Leerzeichen → Unterstrich, keine Sonderzeichen)
    target_safe = _safe_name(sess.target or "unbekannt")
    # Datum aus erstem BJD (UTC)
    if "bjd_tdb" in lc.columns and lc["bjd_tdb"].notna().any():
        jd_first = float(lc["bjd_tdb"].dropna().iloc[0])
        date_str = _jd_to_date(jd_first)
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filt = (sess.aavso_filter or "").upper() or "V"
    dest = archive_root / target_safe / f"{date_str}_{filt}"
    dest.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    # --- Messdaten
    shutil.copy2(lc_path, dest / "zeitreihe.csv")
    copied.append("zeitreihe.csv")

    tr_path = results / "zeitreihe_transformiert.csv"
    if tr_path.exists():
        shutil.copy2(tr_path, dest / "zeitreihe_transformiert.csv")
        copied.append("zeitreihe_transformiert.csv")

    if copy_messtabelle:
        for p in sorted(results.glob("messtabelle*.csv")):
            shutil.copy2(p, dest / p.name)
            copied.append(p.name)

    # --- AAVSO-Exportdatei
    from varphot.observer import data_dir as _dd
    exports_dir = (_dd() if _dd().is_dir() else sess.path()) / "exports"
    aavso_files = sorted(exports_dir.glob(f"aavso_{target_safe}*_{filt}_*.txt"))
    if not aavso_files:
        aavso_files = sorted(exports_dir.glob("aavso_*.txt"))
    for af in aavso_files[-1:]:             # nur die neueste
        shutil.copy2(af, dest / af.name)
        copied.append(af.name)

    # --- Plots aus results/
    for plot_name in ("chart.png", "lightcurve.png", "lichtkurve.png", "langzeitkurve.png"):
        p = results / plot_name
        if p.exists():
            shutil.copy2(p, dest / plot_name)
            copied.append(plot_name)

    # --- Einzelbilder
    if images != "none":
        _copy_frames(sess, lc, dest, images, copied)

    # --- projekt.json (Metadaten)
    _write_projekt_json(sess, lc, dest, copied, copy_masters)

    # --- Bericht Markdown
    bericht_path = dest / "bericht.md"
    bericht_path.write_text(
        _render_bericht(sess, lc, date_str, filt, aavso_files, copied),
        encoding="utf-8",
    )
    copied.append("bericht.md")

    # --- Excel
    if excel:
        try:
            xlsx_path = dest / "zeitreihe.xlsx"
            lc.to_excel(xlsx_path, index=False)
            copied.append("zeitreihe.xlsx")
        except Exception as exc:
            print(f"⚠ Excel-Export fehlgeschlagen: {exc}")

    # --- Ziel-Index aktualisieren
    _update_index(archive_root / target_safe, target_safe, date_str, filt, lc)

    # --- Kumulatives PDF aller Nächte dieses Ziels
    write_object_summary_pdf(archive_root / target_safe, target_safe)

    print(f"✓ Archiviert in: {dest}")
    print(f"  {len(copied)} Dateien: {', '.join(copied[:6])}" + (" …" if len(copied) > 6 else ""))
    return dest


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _safe_name(name: str) -> str:
    """Datei-sicherer Name: Leerzeichen → _, Sonderzeichen entfernt."""
    import re
    return re.sub(r"[^\w.\-]", "_", name).strip("_")


def _jd_to_date(jd: float) -> str:
    """JD → JJJJ-MM-TT (UTC, grob)."""
    try:
        from astropy.time import Time
        return Time(jd, format="jd", scale="tdb").to_datetime().strftime("%Y-%m-%d")
    except Exception:
        # Näherung: JD 2451545.0 = 2000-01-01.5
        days = jd - 2451545.0
        from datetime import timedelta
        dt = datetime(2000, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=days)
        return dt.strftime("%Y-%m-%d")


def _copy_frames(sess: Session, lc: pd.DataFrame, dest: Path, mode: str, copied: list[str]) -> None:
    """Kopiert Einzelbilder gemäß ``mode`` in dest/einzelbilder/."""
    lights = Path(sess.frames_dir) if sess.frames_dir else sess.path("process")
    if not lights.is_dir():
        lights = sess.path("lights")
    if not lights.is_dir():
        return
    fits_files = sorted(lights.glob("*.fits")) + sorted(lights.glob("*.fit")) + sorted(lights.glob("*.fts"))
    if not fits_files:
        return
    eb = dest / "einzelbilder"
    eb.mkdir(exist_ok=True)
    if mode == "first":
        to_copy = fits_files[:1]
    elif mode == "best" and "fwhm_arcsec" in lc.columns and "file" in lc.columns:
        best_file = lc.loc[lc["fwhm_arcsec"].idxmin(), "file"]
        matches = [f for f in fits_files if f.name == Path(best_file).name]
        to_copy = matches[:1] or fits_files[:1]
    else:
        to_copy = fits_files
    for f in to_copy:
        shutil.copy2(f, eb / f.name)
        copied.append(f"einzelbilder/{f.name}")


def _write_projekt_json(sess: Session, lc: pd.DataFrame, dest: Path, copied: list[str], copy_masters: bool) -> None:
    meta = {
        "varphot_version": __version__,
        "archiviert": datetime.now(timezone.utc).isoformat(),
        "target": sess.target,
        "method": sess.method,
        "aavso_filter": sess.aavso_filter,
        "camera_model": sess.camera_model,
        "camera_setting": sess.camera_setting,
        "obstype": sess.obstype,
        "tag": sess.tag,
        "n_punkte": int(lc["mag"].notna().sum()),
        "mag_min": float(lc["mag"].min()) if lc["mag"].notna().any() else None,
        "mag_max": float(lc["mag"].max()) if lc["mag"].notna().any() else None,
        "mag_err_median": float(lc["mag_err"].median()) if "mag_err" in lc.columns else None,
        "zeitraum_jd": [float(lc["bjd_tdb"].min()), float(lc["bjd_tdb"].max())] if "bjd_tdb" in lc.columns else None,
        "quellordner": str(sess.results_dir()),
        "dateien": copied,
    }
    if copy_masters:
        for sub in ("masters",):
            p = sess.path(sub)
            if p.is_dir():
                meta[f"pfad_{sub}"] = str(p)
    (dest / "projekt.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _render_bericht(
    sess: Session, lc: pd.DataFrame, date_str: str, filt: str,
    aavso_files: list[Path], copied: list[str],
) -> str:
    n = int(lc["mag"].notna().sum())
    mag_min = f"{lc['mag'].min():.3f}" if lc["mag"].notna().any() else "—"
    mag_max = f"{lc['mag'].max():.3f}" if lc["mag"].notna().any() else "—"
    err_med = f"{lc['mag_err'].median():.4f}" if "mag_err" in lc.columns and lc["mag_err"].notna().any() else "—"
    aavso_line = f"`{aavso_files[-1].name}`" if aavso_files else "*(nicht erstellt)*"

    has_lc_png = any("lichtkurve" in c or "lightcurve" in c for c in copied)
    has_chart = "chart.png" in copied
    plot_section = ""
    if has_chart:
        plot_section += "\n![Sternkarte](chart.png)\n"
    if has_lc_png:
        lc_fname = "lichtkurve.png" if "lichtkurve.png" in copied else "lightcurve.png"
        plot_section += f"\n![Lichtkurve]({lc_fname})\n"

    return f"""# Nacht-Bericht: {sess.target or '—'} — {date_str}

**Ziel:** {sess.target}
**Filter:** {filt}
**Methode:** {sess.method or '—'}
**Kamera:** {sess.camera_model or '—'} ({sess.camera_setting or '—'})
**Sitzungs-Tag:** {sess.tag or '—'}

## Ergebnisse

| Kenngröße | Wert |
|:---|:---|
| Messpunkte | {n} |
| Helligkeitsbereich | {mag_max} … {mag_min} mag |
| Mittlerer Fehler | {err_med} mag |
| AAVSO-Datei | {aavso_line} |

{plot_section}
## Dateien

{chr(10).join(f'- `{c}`' for c in copied)}

---

*Erstellt mit varphot {__version__} am {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC*
"""


def _update_index(target_dir: Path, target_safe: str, date_str: str, filt: str, lc: pd.DataFrame) -> None:
    """Erstellt/aktualisiert index.md im Zielordner."""
    index_path = target_dir / "index.md"
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
    else:
        existing = f"# {target_safe.replace('_', ' ')} — Beobachtungsarchiv\n\n| Datum | Filter | Punkte | Bereich | Bericht |\n|:---|:---|---:|:---|:---|\n"

    # Zeile für diese Nacht
    n = int(lc["mag"].notna().sum())
    mag_min = f"{lc['mag'].min():.3f}" if lc["mag"].notna().any() else "—"
    mag_max = f"{lc['mag'].max():.3f}" if lc["mag"].notna().any() else "—"
    new_row = f"| {date_str} | {filt} | {n} | {mag_max}–{mag_min} | [{date_str}_{filt}/bericht.md]({date_str}_{filt}/bericht.md) |"

    # Wenn Datum schon vorhanden: ersetzen
    lines = existing.splitlines()
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"| {date_str} | {filt} "):
            lines[i] = new_row
            updated = True
            break
    if not updated:
        lines.append(new_row)

    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _pandoc_or_hint() -> str | None:
    """Gibt Pandoc-Pfad zurück oder druckt Installationshinweis und gibt None zurück."""
    p = shutil.which("pandoc")
    if p is None:
        print(
            "⚠ PDF-Zusammenfassung übersprungen: Pandoc nicht gefunden.\n"
            "  Installation:\n"
            "    macOS : brew install pandoc && brew install --cask mactex\n"
            "    Linux : apt install pandoc texlive-xetex\n"
            "  Danach NB05 erneut ausführen."
        )
    return p


def write_object_summary_pdf(target_dir: Path, target_safe: str) -> Path | None:
    """Erstellt/aktualisiert die kumulative PDF-Zusammenfassung aller Nächte eines Ziels.

    Liest ``index.md`` und alle ``*/bericht.md`` aus ``target_dir``, fügt sie zu einem
    einzigen Markdown-Dokument zusammen und erzeugt daraus
    ``<target_dir>/<target_safe>_beobachtungen.pdf``.

    Gibt den PDF-Pfad zurück oder ``None`` wenn Pandoc fehlt.
    """
    if _pandoc_or_hint() is None:
        return None

    index_path = target_dir / "index.md"
    if not target_dir.is_dir():
        return None

    # Alle Nacht-Berichte chronologisch sortiert
    nacht_berichte = sorted(target_dir.glob("*/bericht.md"))

    if not nacht_berichte and not index_path.exists():
        return None

    parts: list[str] = []
    if index_path.exists():
        parts.append(index_path.read_text(encoding="utf-8"))

    for bp in nacht_berichte:
        parts.append("\n\n---\n\n")
        parts.append(bp.read_text(encoding="utf-8"))

    combined_md = "\n".join(parts)

    # Pandoc braucht relative Pfade für Bilder → temporäres MD-File im target_dir
    tmp_md = target_dir / "_zusammenfassung_tmp.md"
    tmp_md.write_text(combined_md, encoding="utf-8")

    pdf_path = target_dir / f"{target_safe}_beobachtungen.pdf"
    try:
        r = subprocess.run(
            ["pandoc", str(tmp_md), "-o", str(pdf_path),
             "--pdf-engine=xelatex",
             f"--resource-path={target_dir}",
             "-V", "geometry:margin=2cm",
             "-V", "fontsize=11pt"],
            capture_output=True, text=True, cwd=str(target_dir), check=False,
        )
        if r.returncode == 0:
            print(f"✓ PDF-Zusammenfassung: {pdf_path}")
        else:
            print(f"⚠ Pandoc-PDF fehlgeschlagen: {r.stderr[:300]}")
            pdf_path = None
    finally:
        tmp_md.unlink(missing_ok=True)

    return pdf_path
