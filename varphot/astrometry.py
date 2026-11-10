"""Plate Solving mit ASTAP — liefert eine WCS, ohne die FITS-Datei zu veraendern.

ASTAP schreibt mit ``-wcs`` NICHT in den FITS-Header, sondern legt neben das Bild eine
Textdatei ``<bild>.wcs`` (FITS-Header als 80-Zeichen-Karten). Diese wird hier gelesen.
Das Originalbild bleibt unveraendert (kein ``-update``).
"""
from __future__ import annotations

import subprocess
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.wcs import WCS

ASTAP_DEFAULT = "/Applications/ASTAP.app/Contents/MacOS/astap"


@dataclass
class SolveResult:
    """Ergebnis von :func:`solve_image`."""
    wcs: WCS | None
    source: str                 # "ASTAP", "header" oder "keine"
    log: str = ""               # ASTAP-Ausgabe (gekuerzt)
    header: fits.Header | None = None
    notes: list[str] = field(default_factory=list)


def _wcs_from_header(hdr: fits.Header) -> WCS | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        w = WCS(hdr)
    return w if w.has_celestial else None


def read_wcs_sidecar(path: Path) -> fits.Header:
    """Liest eine ASTAP-``.wcs``-Datei (Karten ohne Zeilenumbruch) als Header."""
    return fits.Header.fromstring(path.read_bytes().decode("ascii", "replace"))


def solve_image(image: str | Path, astap: str = ASTAP_DEFAULT, radius_deg: float = 10.0,
                fov_deg: float | None = None, timeout: int = 300, max_stars: int = 5000) -> SolveResult:
    """Loest ``image`` mit ASTAP; faellt bei Misserfolg auf eine WCS im FITS-Header zurueck.

    ``radius_deg``: Suchradius um die Naeherungsposition aus dem Header (RA/DEC bzw. OBJCTRA).
    ``fov_deg``: Feldhoehe in Grad; ``None`` = ASTAP bestimmt sie aus dem Header.
    ``max_stars``: Zahl der Sterne, die ASTAP fuer die Loesung nutzt (``-s``; ASTAP-Standard 500). Am M16-Bild
    (2,1 Grad) blieb mit 500 Sternen ein Rotationsfehler von ~1,2" am Bildrand, mit 5000 ~0,8" (Gaia-Pruefung).
    Bei gescheiterter Loesung wird NIE eine WCS erfunden: entweder Header-WCS (mit Hinweis) oder
    ``wcs=None``.
    """
    image = Path(image)
    if image.suffix.lower() in (".fz", ".gz"):
        return _solve_compressed(image, astap, radius_deg, fov_deg, timeout, max_stars)
    notes: list[str] = []
    with fits.open(image) as hdul:
        img_hdr = hdul[0].header.copy()

    if not Path(astap).exists():
        notes.append(f"ASTAP nicht gefunden: {astap}")
        w = _wcs_from_header(img_hdr)
        return SolveResult(w, "header" if w else "keine", "", img_hdr, notes)

    sidecar = image.with_suffix(".wcs")
    sidecar.unlink(missing_ok=True)          # keine alte Loesung mit neuer verwechseln
    cmd = [astap, "-f", str(image), "-r", str(radius_deg), "-s", str(int(max_stars)), "-wcs"]
    if fov_deg:
        cmd += ["-fov", str(fov_deg)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        log = (run.stdout + run.stderr).strip()
    except subprocess.TimeoutExpired:                  # haengt ASTAP (z. B. leeres Feld), bleibt der Fallback auf die Header-WCS
        log = ""
        notes.append(f"ASTAP: Zeitlimit {timeout} s")
    except OSError as e:
        log = ""
        notes.append(f"ASTAP nicht startbar: {e}")

    if sidecar.exists() and "Solution found" in log:
        hdr = read_wcs_sidecar(sidecar)
        w = _wcs_from_header(hdr)
        if w is not None:
            return SolveResult(w, "ASTAP", log[-800:], hdr, notes)
        notes.append("ASTAP-.wcs ohne gueltige Himmelskoordinaten")

    notes.append("ASTAP: keine Loesung")
    w = _wcs_from_header(img_hdr)
    if w is not None:
        notes.append("Fallback: WCS aus dem FITS-Header")
        return SolveResult(w, "header", log[-800:], img_hdr, notes)
    return SolveResult(None, "keine", log[-800:], img_hdr, notes)


def _solve_compressed(image: Path, astap: str, radius_deg: float, fov_deg: float | None, timeout: int, max_stars: int) -> SolveResult:
    """Loest ein komprimiertes Bild (``.fits.fz``/``.gz``) ueber eine **Kopie** in einem Wegwerf-Ordner.

    Warum: ASTAP entpackt ``.fz``-Dateien neben dem Original und **loescht dabei das Original** (beobachtet 2026-11-11: eine Verknuepfung auf ein LCO-``.fits.fz`` war danach weg; die entpackte ``.fits``,
    ``.ini`` und ``.wcs`` lagen im Ordner). Das verletzte die Zusage „Originalbild bleibt unveraendert“. Jetzt: Daten und Kopf per astropy lesen, als normales FITS in einen Wegwerf-Ordner schreiben, dort loesen;
    die ``.wcs`` wird neben das Original kopiert (``<bild>.wcs``). Validierung: ``tests/test_core.py`` (Attrappe, die die Eingabedatei loescht).
    """
    import shutil
    import tempfile

    from .batch import read_frame
    img, hdr, _ = read_frame(image)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / (image.name.split(".")[0] + ".fits")
        keep = fits.Header()
        for k, v in hdr.items():
            if k not in ("COMMENT", "HISTORY", "") and not k.startswith(("CTYPE", "CRVAL", "CRPIX", "CD", "PC", "CDELT", "A_", "B_", "AP_", "BP_")):
                try:
                    keep[k] = v
                except (ValueError, TypeError):
                    pass
        fits.PrimaryHDU(np.asarray(img, np.float32), keep).writeto(tmp)
        res = solve_image(tmp, astap=astap, radius_deg=radius_deg, fov_deg=fov_deg, timeout=timeout, max_stars=max_stars)
        side = tmp.with_suffix(".wcs")
        if side.exists():
            shutil.copy2(side, image.with_suffix(".wcs"))
    res.notes.append("komprimiertes Bild ueber eine Kopie geloest (ASTAP wuerde das Original loeschen)")
    return res


def gnomonic(ra, dec, ra0, dec0, min_cos: float = 0.1):
    """Gnomonische Projektion (Grad) um (ra0, dec0); x waechst nach Osten links (x = -xi).

    Punkte auf der abgewandten Himmelshalbkugel (Abstand > ~84 Grad, ``cos c <= min_cos``)
    haben keine gueltige Abbildung und liefern ``(nan, nan)`` — sonst wuerden sie gespiegelt
    ins Bild fallen (Fehler in v0.2.0: Orion erschien im Feld von M16).
    """
    r0, d0 = np.radians(ra0), np.radians(dec0)
    r, d = np.radians(np.asarray(ra, float)), np.radians(np.asarray(dec, float))
    dr = (r - r0 + np.pi) % (2 * np.pi) - np.pi
    cos_c = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(dr)
    ok = cos_c > min_cos
    with np.errstate(divide="ignore", invalid="ignore"):
        x = -np.degrees(np.cos(d) * np.sin(dr) / cos_c)
        y = np.degrees((np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(dr)) / cos_c)
    x, y = np.where(ok, x, np.nan), np.where(ok, y, np.nan)
    return (float(x), float(y)) if x.ndim == 0 else (x, y)


def great_circle_xy(ra1, dec1, ra2, dec2, ra0, dec0, n: int = 64, min_cos: float = 0.1):
    """Grosskreis-Bogen zwischen zwei Himmelspunkten, gnomonisch um (ra0, dec0) projiziert (Grad).

    Gibt ``n`` Stuetzpunkte (x, y) zurueck; Punkte auf der abgewandten Halbkugel (``cos c <= min_cos``)
    sind NaN. Bei Projektion von Grosskreisen entstehen Geraden — liegen beide Endpunkte vorn, ist der Bogen
    daher exakt die Strecke dazwischen; bei einem Endpunkt hinten bleibt der vordere Teil erhalten (statt
    die ganze Linie zu verwerfen).
    """
    def vec(ra, dec):
        r, d = np.radians(ra), np.radians(dec)
        return np.array([np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)])

    a, b = vec(ra1, dec1), vec(ra2, dec2)
    omega = np.arccos(np.clip(a @ b, -1, 1))
    t = np.linspace(0, 1, n)
    if omega < 1e-9:
        pts = np.tile(a, (n, 1))
    else:                                           # Slerp; bei exakt gegenueberliegenden Punkten mehrdeutig
        pts = (np.sin((1 - t) * omega)[:, None] * a + np.sin(t * omega)[:, None] * b) / np.sin(omega)
    ra = np.degrees(np.arctan2(pts[:, 1], pts[:, 0])) % 360
    dec = np.degrees(np.arcsin(np.clip(pts[:, 2], -1, 1)))
    return gnomonic(ra, dec, ra0, dec0, min_cos)


def polyline_in_window(x, y, half: float, samples: int = 400) -> bool:
    """True, wenn der Linienzug (x, y; NaN trennt Teile) das Fenster [-half, half]^2 beruehrt —
    auch wenn kein Stuetzpunkt darin liegt (lange Strecke quer durchs Fenster)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    for i in range(len(x) - 1):
        if not np.all(np.isfinite([x[i], y[i], x[i + 1], y[i + 1]])):
            continue
        s = np.linspace(0, 1, samples)
        px, py = x[i] + s * (x[i + 1] - x[i]), y[i] + s * (y[i + 1] - y[i])
        if np.any((np.abs(px) <= half) & (np.abs(py) <= half)):
            return True
    return False


def field_from_wcs(wcs: WCS, shape) -> dict:
    """Sensorfeld aus WCS und Bildform ``(ny, nx)``: Mitte, Kantenlaengen und Winkel der langen Seite.

    Warum: Die Comp-Auswahl braucht das echte Bildfeld (Groesse und Drehung), damit nur Sterne gewaehlt werden, die im Bild
    liegen; ohne Winkel gilt der rotationssichere Kreis (halbe kurze Seite), der bei kleinen Feldern fast alle Sterne verwirft. Wie: Mitten der Bildkanten (Pixelraender) gnomonisch
    um die Bildmitte projiziert; Laenge der Verbindungen = Kantenlaengen. Rueckgabe ``ra0, dec0`` (Grad), ``field_deg`` =
    (lange, kurze Seite) in Grad, ``pa_deg`` = Richtung der langen Seite von Osten nach Norden (wie ``vsp.in_field``: 0 =
    West-Ost, 90 = Nord-Sued). Grenze: Verzerrung (SIP) wird ignoriert. Validierung: ``tests/test_batch.py``.
    Quelle: TAN-Projektion nach Calabretta, M. R. & Greisen, E. W. 2002, A&A 395, 1077, doi:10.1051/0004-6361:20021327 (Zitat per Suche geprueft).
    """
    ny, nx = shape
    cx, cy = (nx - 1) / 2, (ny - 1) / 2
    ra0, dec0 = (float(v) for v in wcs.pixel_to_world_values(cx, cy))

    def tangent(px, py):
        x, y = gnomonic(*wcs.pixel_to_world_values(px, py), ra0, dec0)
        return -x, y                                  # (xi nach Osten, eta nach Norden)

    xe, ye = tangent(nx - 0.5, cy), tangent(-0.5, cy)  # Mitte der rechten / linken Bildkante (Pixelrand)
    xn, yn = tangent(cx, ny - 0.5), tangent(cx, -0.5)  # Mitte der oberen / unteren Bildkante
    len_x = float(np.hypot(xe[0] - ye[0], xe[1] - ye[1]))
    len_y = float(np.hypot(xn[0] - yn[0], xn[1] - yn[1]))
    (a, b, la, sh) = (xe, ye, len_x, len_y) if len_x >= len_y else (xn, yn, len_y, len_x)
    pa = float(np.degrees(np.arctan2(a[1] - b[1], a[0] - b[0])) % 180)
    return dict(ra0=ra0, dec0=dec0, field_deg=(la, sh), pa_deg=pa)


def solve_array(img, hint: dict | None = None, astap: str = ASTAP_DEFAULT, radius_deg: float = 10.0, fov_deg: float | None = None, timeout: int = 180) -> SolveResult:
    """Loest ein Bild, das nur als Array vorliegt (z. B. kuenstlich verunschaerft): schreibt es **ohne WCS** in eine Wegwerf-Datei und ruft :func:`solve_image` auf.

    ``hint``: Kopfzeilen, die ASTAP als Naeherungsposition braucht (``RA``/``DEC`` als Zahlen in Grad — werden zu ``OBJCTRA``/``OBJCTDEC`` umgeschrieben, oder diese direkt; ``EXPTIME``, ``DATE-OBS``). Es wird nie eine WCS aus dem Hinweis gebaut:
    liefert ASTAP nichts, ist ``wcs`` leer (kein Fallback auf eine Header-WCS, denn die gibt es hier nicht). Validierung: ``tests/test_core.py`` (ASTAP-Attrappe).
    """
    import tempfile
    hint = dict(hint or {})
    if isinstance(hint.get("RA"), (int, float)) and isinstance(hint.get("DEC"), (int, float)):      # Grad -> OBJCTRA/OBJCTDEC (Stunden-/Gradschreibweise, die ASTAP sicher liest)
        from astropy import units as u
        from astropy.coordinates import Angle
        hint["OBJCTRA"] = Angle(hint.pop("RA"), u.deg).to_string(unit=u.hour, sep=" ", precision=1, pad=True)
        hint["OBJCTDEC"] = Angle(hint.pop("DEC"), u.deg).to_string(unit=u.deg, sep=" ", precision=0, alwayssign=True, pad=True)
    with tempfile.TemporaryDirectory() as d:
        h = fits.Header()
        for k, v in hint.items():
            if k.upper() not in ("CTYPE1", "CTYPE2", "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "CD1_1", "CD1_2", "CD2_1", "CD2_2", "CDELT1", "CDELT2"):
                h[k] = v
        p = Path(d) / "probe.fits"
        fits.PrimaryHDU(np.asarray(img, np.float32), h).writeto(p)
        return solve_image(p, astap=astap, radius_deg=radius_deg, fov_deg=fov_deg, timeout=timeout)


def plate_solve_summary(res: SolveResult, shape, truth_wcs: WCS | None = None) -> dict:
    """Kurzbefund einer Loesung: geloest?, Pixelskala ["/px], Bildmitte und — mit ``truth_wcs`` — Versatz der Bildmitte zur Wahrheit ["]."""
    ny, nx = shape
    if res.wcs is None or res.source != "ASTAP":
        return dict(solved=False, source=res.source, notes=list(res.notes))
    ra, dec = (float(v) for v in res.wcs.pixel_to_world_values(nx / 2, ny / 2))
    scale = float(np.sqrt(abs(np.linalg.det(res.wcs.pixel_scale_matrix)))) * 3600.0
    out = dict(solved=True, source=res.source, scale_arcsec=round(scale, 3), center_ra=ra, center_dec=dec)
    if truth_wcs is not None:
        r0, d0 = (float(v) for v in truth_wcs.pixel_to_world_values(nx / 2, ny / 2))
        out["offset_arcsec"] = round(float(np.hypot((ra - r0) * np.cos(np.radians(d0)), dec - d0)) * 3600.0, 2)
    return out


def defocus_solve_ladder(img, truth_wcs: WCS, hint: dict | None = None, blurs=(0, 4, 8, 12, 20, 30), kinds=("gauss", "donut"), astap: str = ASTAP_DEFAULT, radius_deg: float = 5.0,
                         timeout: int = 180, progress=None):
    """Loest ein scharfes Bild in wachsender kuenstlicher Unschaerfe und zeigt, wo ASTAP aufgibt (Tabelle ``kind, blur_px, solved, offset_arcsec, seconds``).

    Warum: Bevor man in der Nacht defokussiert, soll bekannt sein, ob ASTAP solche Bilder noch loest (KONZEPT §12.1). Wie: :func:`varphot.synthetic.defocus_image` (Gauss oder Kreisring) ->
    :func:`solve_array` -> :func:`plate_solve_summary` gegen ``truth_wcs`` (die WCS des scharfen Bildes). Feldhoehe aus ``truth_wcs`` fuer ``-fov``.
    Grenzen: eine Faltung ist kein echtes Defokussieren; gilt fuer das Sternfeld des Bildes. Validierung: ``tests/test_core.py`` (Attrappe), LCO δ Cep (KONZEPT §12.1).
    """
    import time

    import pandas as pd

    from .synthetic import defocus_image
    ny, nx = np.asarray(img).shape
    scale = float(np.sqrt(abs(np.linalg.det(truth_wcs.pixel_scale_matrix)))) * 3600.0
    fov = ny * scale / 3600.0
    rows = []
    for kind in kinds:
        for b in blurs:
            arr = defocus_image(img, b, kind) if b else np.asarray(img, float)
            t0 = time.time()
            res = solve_array(arr, hint, astap=astap, radius_deg=radius_deg, fov_deg=fov, timeout=timeout)
            s = plate_solve_summary(res, (ny, nx), truth_wcs)
            rows.append(dict(kind=kind, blur_px=b, solved=s["solved"], offset_arcsec=s.get("offset_arcsec"), seconds=round(time.time() - t0, 1)))
            if progress:
                progress(rows[-1])
    return pd.DataFrame(rows)
