"""WCS fuer jedes Bild einer Reihe aus einem einmal geloesten Referenzbild (Registrierung statt Plate-Solve je Bild).

Autor: Axel Pospischil. Stand 2026-11-10 (KONZEPT §12.3).

Warum: Eigene Reihen (Siril-kalibrierte Bilder) tragen keine WCS, und ein bewusst defokussiertes Bild loest ASTAP oft nicht (KONZEPT §12.1). Geloest wird deshalb **einmal** ein scharfes Referenzbild;
fuer jedes Bild der Reihe wird die Verschiebung/Drehung gegen die Referenz bestimmt und die WCS daraus abgeleitet. Das setzt gleiche Optik und Pixelskala voraus (Nachfuehrfehler und Drehung sind erlaubt).
Wie: die hellsten Sterne beider Bilder (``DAOStarFinder``) werden mit ``astroalign.find_transform`` (Dreiecks-Invarianten + RANSAC, unabhaengig von WCS und kaum empfindlich gegen Seeing-Unterschiede)
zugeordnet; die Aehnlichkeitstransformation ``q = A·p + t`` (Bildpixel ``p`` -> Referenzpixel ``q``) ergibt die WCS: ``CD' = CD·A``, ``CRPIX' = 1 − A⁻¹·(t + 1 − CRPIX)`` (FITS-Pixel 1-basiert).
Die Schaetzung wird verworfen bei < ``min_match`` Treffern, Restfehler > ``max_rms_px`` oder Massstab ausserhalb ±``max_scale_dev``.
Quelle: Beroiz, M., Cabral, J. B. & Sanchez, B. 2020, Astronomy and Computing 32, 100384, doi:10.1016/j.ascom.2020.100384, arXiv:1909.02946 (Titel/Autoren per Suche geprueft, Volltext nicht gelesen).
Grenzen: keine Verzeichnung (SIP) und nur Aehnlichkeit (Verschiebung, Drehung, gleicher Massstab); stark defokussierte Bilder zeigen nur die hellsten Sterne — es genuegen 4; Felder mit sehr wenigen hellen Sternen
(δ Cep: ein gesaettigter Stern und wenige Nachbarn) koennen scheitern, dann bleibt das Bild ohne WCS (Flag ``NO_WCS``). Validierung: ``tests/test_registration.py`` (bekannte Verschiebung/Drehung, defokussiert) und
LCO δ Cep (registrierte WCS gegen die WCS im Kopf, siehe KONZEPT §12.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from astropy.wcs import WCS


@dataclass
class Registration:
    """Ergebnis einer Registrierung; ``ok`` False -> ``wcs`` None und ``note`` nennt den Grund."""
    ok: bool
    wcs: WCS | None = None
    n_match: int = 0
    rms_px: float = float("nan")
    shift_px: float = float("nan")
    rotation_deg: float = float("nan")
    scale: float = float("nan")
    note: str = ""
    matrix: np.ndarray | None = field(default=None, repr=False)


def bright_sources(img, fwhm: float, nsigma: float = 6.0, n_max: int = 60, edge: int = 10) -> np.ndarray:
    """Positionen ``(x, y)`` der hellsten Sterne (nach Helligkeit absteigend, hoechstens ``n_max``); leeres ``(0, 2)``-Array ohne Sterne.

    Warum: Zum Zuordnen genuegen die hellsten Sterne; sie sind auch im defokussierten Bild noch da. ``DAOStarFinder`` (Formfilter Schaerfe/Rundheit) verwirft Donuts (Ringe) und findet dort Rauschspitzen
    (im Test: 0 von 25 Treffern echt) — deshalb hier ohne Formfilter: Glaetten mit einem Gauss (``sigma = FWHM/2,355``), lokale Maxima ueber ``nsigma`` mal dem robusten Rauschen (1,4826·MAD des geglaetteten Bildes),
    Schwerpunkt in einem Fenster der Breite ``FWHM`` (Mitte eines Rings = Sternort). Sterne am Rand (``edge`` px) werden ausgelassen. Grenzen: Doppelsterne/Nachbarn innerhalb einer FWHM verschmelzen; Feste Muster (heisse Spalten, Streifen) koennen Spitzen vortaeuschen; einzelne Hotpixel entfernt ein 3×3-Medianfilter. Validierung: ``tests/test_registration.py`` (Gauss, Donut).
    """
    from photutils.detection import find_peaks
    from scipy import ndimage
    a = ndimage.median_filter(np.asarray(img, float), size=3)                       # Hotpixel/Kosmische: einzelne Pixel fallen heraus (Sterne bleiben)
    ny, nx = a.shape
    fwhm = max(float(fwhm), 1.5)
    sm = ndimage.gaussian_filter(a, fwhm / 2.3548)
    med = float(np.median(sm))
    sig = 1.4826 * float(np.median(np.abs(sm - med)))
    if sig <= 0:
        return np.empty((0, 2))
    box = int(max(3, round(1.5 * fwhm))) | 1
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pk = find_peaks(sm - med, threshold=nsigma * sig, box_size=box, npeaks=n_max * 2, border_width=edge)
    if pk is None or len(pk) == 0:
        return np.empty((0, 2))
    half = int(max(2, round(fwhm / 2)))
    out = []
    for x0, y0, _v in sorted(zip(pk["x_peak"], pk["y_peak"], pk["peak_value"]), key=lambda t: -t[2]):
        sub = (sm - med)[max(y0 - half, 0):y0 + half + 1, max(x0 - half, 0):x0 + half + 1].clip(0)
        if sub.sum() <= 0:
            continue
        yy, xx = np.mgrid[max(y0 - half, 0):max(y0 - half, 0) + sub.shape[0], max(x0 - half, 0):max(x0 - half, 0) + sub.shape[1]]
        out.append(((sub * xx).sum() / sub.sum(), (sub * yy).sum() / sub.sum()))
        if len(out) >= n_max:
            break
    return np.asarray(out, float).reshape(-1, 2)


def wcs_from_transform(ref_wcs: WCS, matrix: np.ndarray) -> WCS:
    """WCS eines Bildes, dessen Pixel ``p`` ueber ``q = A·p + t`` (``matrix`` = 3x3, 0-basiert) auf Referenzpixel ``q`` abgebildet werden.

    ``CD' = CD·A`` und ``CRPIX' = 1 − A⁻¹·(t + 1 − CRPIX)`` (FITS-Pixel 1-basiert); Projektion, ``CRVAL`` und Koordinatensystem bleiben. Validierung: ``tests/test_registration.py`` (Rundreise Pixel -> Himmel).
    """
    A, t = np.asarray(matrix, float)[:2, :2], np.asarray(matrix, float)[:2, 2]
    cd = np.asarray(ref_wcs.pixel_scale_matrix, float)
    w = WCS(naxis=2)
    w.wcs.ctype = list(ref_wcs.wcs.ctype)
    w.wcs.crval = list(ref_wcs.wcs.crval)
    w.wcs.radesys = ref_wcs.wcs.radesys or "ICRS"
    w.wcs.cd = cd @ A
    w.wcs.crpix = 1.0 - np.linalg.solve(A, t + 1.0 - np.asarray(ref_wcs.wcs.crpix, float))
    return w


def register_frame(ref_xy: np.ndarray, img, ref_wcs: WCS, fwhm: float, nsigma: float = 6.0, min_match: int = 4, max_rms_px: float = 1.5, max_scale_dev: float = 0.05) -> Registration:
    """WCS fuer ``img`` aus der Referenz (Sternpositionen ``ref_xy`` und WCS der Referenz); siehe Modulkopf.

    ``fwhm``: erwartete Sternbreite in ``img`` (defokussiert: groesser als in der Referenz). Rueckgabe :class:`Registration` mit Treffern, Restfehler [px], Verschiebung [px], Drehung [Grad] und Massstab.
    """
    last = Registration(False, note="keine Zuordnung versucht")
    if len(ref_xy) < min_match:
        return Registration(False, note=f"Referenz hat nur {len(ref_xy)} Sterne (mindestens {min_match})")
    for ns, n_max in ((nsigma, 25), (1.6 * nsigma, 40), (0.7 * nsigma, 60)):       # defokussierte Bilder liefern bei niedriger Schwelle viele Rauschspitzen: erst streng, dann lockerer
        xy = bright_sources(img, fwhm, ns, n_max=n_max)
        if len(xy) < min_match:
            last = Registration(False, note=f"nur {len(xy)} Sterne im Bild (mindestens {min_match}) — zu schwach oder zu stark defokussiert")
            continue
        last = _align(ref_xy[:max(n_max, 25)], xy, np.asarray(img).shape, ref_wcs, min_match, max_rms_px, max_scale_dev)
        if last.ok:
            return last
    return last


def _similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Kleinste-Quadrate-Aehnlichkeitstransformation ``dst ≈ s·R·src + t`` (Umeyama 1991), als 3x3-Matrix."""
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    a, b = src - mu_s, dst - mu_d
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.diag([1.0, np.sign(np.linalg.det(U) * np.linalg.det(Vt))])
    R = U @ D @ Vt
    sc = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(axis=1).mean())
    M = np.eye(3)
    M[:2, :2] = sc * R
    M[:2, 2] = mu_d - sc * R @ mu_s
    return M


def _refine(M: np.ndarray, xy: np.ndarray, ref_xy: np.ndarray, tol: float = 2.5, iters: int = 3) -> np.ndarray:
    """Verfeinert die Transformation ueber **alle** Sterne, die nach ihr auf einem Referenzstern liegen (Aehnlichkeit nach kleinsten Quadraten; astroalign nutzt nur wenige Kontrollpunkte).

    Warum: Die erste Schaetzung stuetzt sich auf wenige Dreiecke; mit allen zugeordneten Sternen mittelt sich das Zentroidrauschen heraus (LCO δ Cep: Fehler gegen den WCS-Kopf sank so). Mindestens 6 Paare, sonst unveraendert.
    """
    for _ in range(iters):
        xy_t = (np.c_[xy, np.ones(len(xy))] @ M.T)[:, :2]
        d = np.hypot(*(xy_t[:, None, :] - ref_xy[None, :, :]).transpose(2, 0, 1))
        j, nn = d.argmin(axis=1), d.min(axis=1)
        ok = nn < tol
        if ok.sum() < 6:
            break
        M = _similarity(xy[ok], ref_xy[j[ok]])
    return M


def _align(ref_xy: np.ndarray, xy: np.ndarray, shape, ref_wcs: WCS, min_match: int, max_rms_px: float, max_scale_dev: float) -> Registration:
    """Ein Zuordnungsversuch (``astroalign.find_transform``) mit den Pruefungen aus :func:`register_frame`."""
    import astroalign as aa
    try:
        tf, _ = aa.find_transform(xy, ref_xy, max_control_points=min(50, len(xy), len(ref_xy)))
    except Exception as e:                                          # astroalign: MaxIterError/ValueError bei keiner Loesung
        return Registration(False, note=f"keine Zuordnung zur Referenz ({type(e).__name__})")
    M = _refine(np.asarray(tf.params, float), xy, ref_xy)
    xy_t = (np.c_[xy, np.ones(len(xy))] @ M.T)[:, :2]
    d = np.hypot(*(xy_t[:, None, :] - ref_xy[None, :, :]).transpose(2, 0, 1))
    nn = d.min(axis=1)
    pair = nn < 2.0                                                    # Sterne, die nach der Transformation auf einem Referenzstern liegen
    src_m = xy[pair]
    res = nn[pair]
    rms = float(np.sqrt(np.mean(res ** 2))) if len(res) else float("nan")
    scale = float(np.sqrt(abs(np.linalg.det(M[:2, :2]))))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    c = np.array([shape[1] / 2, shape[0] / 2])
    shift = float(np.hypot(*(M[:2, :2] @ c + M[:2, 2] - c)))
    n_top = min(10, len(ref_xy))
    top_ok = int((d[:, :n_top].min(axis=0) < 2.0).sum())                 # wie viele der hellsten Referenzsterne liegen nach der Transformation auf einem erkannten Stern?
    base = dict(n_match=int(len(src_m)), rms_px=rms, shift_px=shift, rotation_deg=rot, scale=scale, matrix=M)
    if top_ok < max(4, n_top // 2):
        return Registration(False, note=f"nur {top_ok} der {n_top} hellsten Referenzsterne wiedergefunden — Zuordnung auf feste Muster (Hotpixel/Spalten) oder zu wenige Sterne?", **base)
    if len(src_m) < min_match or len(src_m) < 0.3 * min(len(xy), len(ref_xy)):
        return Registration(False, note=f"nur {len(src_m)} von {min(len(xy), len(ref_xy))} Sternen nach der Transformation auf Referenzsternen (mindestens {min_match} und 30 %)", **base)
    if rms > max_rms_px:
        return Registration(False, note=f"Restfehler {rms:.2f} px > {max_rms_px:g} px", **base)
    if abs(scale - 1) > max_scale_dev:
        return Registration(False, note=f"Massstab {scale:.3f} weicht um mehr als {100 * max_scale_dev:.0f} % von 1 ab (andere Optik/Pixelskala?)", **base)
    return Registration(True, wcs=wcs_from_transform(ref_wcs, M), **base)
