"""Gegenpruefung einer WCS gegen Gaia DR3: Erkannte Sterne mit Gaia-Positionen (auf die Aufnahmeepoche
verschoben) vergleichen und Versatz, Streuung und Trend ueber das Bild ausweisen."""
from __future__ import annotations

from dataclasses import dataclass, field

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.table import Table

from .vsp import _cached_json, _tap_json

GAIA_EPOCH = 2016.0


def gaia_field(ra: float, dec: float, radius_deg: float, gmax: float = 14.0, gmin: float = 8.0,
               cache_dir=None, force=False) -> Table:
    """Gaia-DR3-Sterne (G zwischen ``gmin`` und ``gmax``, RUWE < 1,4) im Kegel, mit Eigenbewegung."""
    q = ("SELECT source_id, ra, dec, pmra, pmdec, phot_g_mean_mag AS G, ruwe FROM gaiadr3.gaia_source WHERE "
         f"1=CONTAINS(POINT('ICRS',ra,dec),CIRCLE('ICRS',{ra:.5f},{dec:.5f},{radius_deg:.4f})) "
         f"AND phot_g_mean_mag BETWEEN {gmin:g} AND {gmax:g} AND ruwe<1.4")
    rows = _cached_json(cache_dir, f"gaiawcs_{ra:.4f}_{dec:.4f}_{radius_deg:g}_{gmin:g}_{gmax:g}",
                        lambda: _tap_json(q, 120), force)
    t = Table(rows=[{k: (np.nan if v is None else v) for k, v in r.items()} for r in rows])
    for c in ("pmra", "pmdec"):                       # fehlende Eigenbewegung -> 0 (Fehler klein gegen Pixel)
        t[c] = np.nan_to_num(np.asarray(t[c], float), nan=0.0)
    return t


def epoch_positions(gaia: Table, epoch: float) -> SkyCoord:
    """Gaia-Positionen (Epoche 2016,0) mit Eigenbewegung auf ``epoch`` (Jahr, z. B. 2024.31) verschieben."""
    dt = epoch - GAIA_EPOCH
    dec = np.asarray(gaia["dec"], float)
    ra = np.asarray(gaia["ra"], float) + (np.asarray(gaia["pmra"], float) * dt / 3.6e6) / np.cos(np.radians(dec))
    dec = dec + np.asarray(gaia["pmdec"], float) * dt / 3.6e6
    return SkyCoord(ra * u.deg, dec * u.deg)


@dataclass
class WCSCheck:
    n_detected: int
    n_gaia_in_image: int
    n_match: int
    median_dra_arcsec: float          # erkannt - Gaia, E-W (RA*cos(dec))
    median_ddec_arcsec: float
    rms_arcsec: float                 # robust (1,4826*MAD) je Achse, gemittelt
    pixel_scale_arcsec: float
    trend_arcsec: float               # groesste lineare Verschiebung ueber das Bild (Skalen-/Rotationsfehler)
    worst_cell_arcsec: float          # groesster Betrag des Median-Residuums einer Bildzelle (8x6, >= 5 Sterne)
    verdict: str
    x: np.ndarray = field(repr=False, default=None)
    y: np.ndarray = field(repr=False, default=None)
    dra: np.ndarray = field(repr=False, default=None)
    ddec: np.ndarray = field(repr=False, default=None)
    G: np.ndarray = field(repr=False, default=None)

    @property
    def offset_arcsec(self) -> float:
        return float(np.hypot(self.median_dra_arcsec, self.median_ddec_arcsec))

    @property
    def recovery(self) -> float:
        return self.n_match / self.n_gaia_in_image if self.n_gaia_in_image else float("nan")


def check_wcs(wcs, xy_detected, gaia: Table, epoch: float, shape, match_arcsec: float = 2.5,
              edge_px: float = 50.0, clip_sigma: float = 3.0) -> WCSCheck:
    """Vergleicht erkannte Sterne (Pixel 0-basiert, ``xy_detected`` = (x, y)-Arrays) mit Gaia DR3.

    Warum: Ein Plate Solve kann plausibel aussehen und trotzdem um Pixel danebenliegen; die Photometrie verfehlt dann die Sterne.
    Gaia ist die unabhaengige Referenz. Wie: Gaia-Positionen mit Eigenbewegung auf die Aufnahmeepoche; gegenseitig naechste
    Nachbarn innerhalb ``match_arcsec``; Ausreisser (> ``clip_sigma`` robuste Sigma, MAD) werden iterativ entfernt. Ausgewiesen
    werden Versatz, Streuung, Wiederfindungsrate, linearer Trend (Skalen-/Rotationsfehler) und die schlechteste Zelle eines
    8x6-Gitters. Urteil in Pixeln der Bildskala: Versatz <= 0,5 px, Streuung <= 0,7 px, schlechteste Zelle <= 1 px -> "OK".
    Grenzen: Die Schwellen sind Startwerte ohne Herleitung. Validierung: M16-Testbild (2636 Treffer, Versatz 0,08″, Streuung
    0,27″, schlechteste Zelle 0,60″ -> OK). Quelle: Gaia Collaboration (Vallenari et al.) 2023, A&A 674, A1 (Gaia DR3,
    aus dem Gedaechtnis, nicht geprueft).
    """
    x, y = (np.asarray(a, float) for a in xy_detected)
    ny, nx = shape[-2:]
    det = wcs.pixel_to_world(x, y)
    gc = epoch_positions(gaia, epoch)
    gx, gy = wcs.world_to_pixel(gc)
    inside = (gx > edge_px) & (gx < nx - edge_px) & (gy > edge_px) & (gy < ny - edge_px)
    idx_d, sep, _ = gc.match_to_catalog_sky(det)                   # je Gaia-Stern naechster erkannter
    idx_g, _, _ = det.match_to_catalog_sky(gc)                     # je erkanntem Stern naechster Gaia
    mutual = (idx_g[idx_d] == np.arange(len(gc))) & (sep.arcsec <= match_arcsec) & inside
    gi, di = np.flatnonzero(mutual), idx_d[mutual]
    dra = ((det[di].ra - gc[gi].ra) * np.cos(gc[gi].dec.rad)).to(u.arcsec).value
    ddec = (det[di].dec - gc[gi].dec).to(u.arcsec).value
    keep = np.ones(len(gi), bool)
    for _ in range(5):                                             # iteratives Sigma-Clipping
        if keep.sum() < 10:
            break
        med = np.array([np.median(dra[keep]), np.median(ddec[keep])])
        sig = np.array([1.4826 * np.median(np.abs(dra[keep] - med[0])), 1.4826 * np.median(np.abs(ddec[keep] - med[1]))])
        new = (np.abs(dra - med[0]) < clip_sigma * max(sig[0], 1e-3)) & (np.abs(ddec - med[1]) < clip_sigma * max(sig[1], 1e-3))
        if (new == keep).all():
            break
        keep = new
    scale = float(wcs.proj_plane_pixel_scales()[0].to(u.arcsec).value)
    if keep.sum() < 10:
        return WCSCheck(len(x), int(inside.sum()), int(keep.sum()), np.nan, np.nan, np.nan, scale, np.nan, np.nan,
                        "Zu wenige Treffer für ein Urteil (< 10)")
    mx, my = x[di][keep], y[di][keep]
    r1, r2 = dra[keep], ddec[keep]
    # lineares Modell Residuum ~ a + b*x + c*y je Achse -> Trend = Variation ueber das Bild
    A = np.c_[np.ones_like(mx), (mx - nx / 2) / nx, (my - ny / 2) / ny]
    trend = 0.0
    for r in (r1, r2):
        coef = np.linalg.lstsq(A, r, rcond=None)[0]
        trend = max(trend, float(np.hypot(coef[1], coef[2])))
    worst = 0.0                                                   # schlechteste Zelle eines 8x6-Gitters
    for i in range(8):
        for j in range(6):
            m = (mx >= i * nx / 8) & (mx < (i + 1) * nx / 8) & (my >= j * ny / 6) & (my < (j + 1) * ny / 6)
            if m.sum() >= 5:
                worst = max(worst, float(np.hypot(np.median(r1[m]), np.median(r2[m]))))
    med_ra, med_dec = float(np.median(r1)), float(np.median(r2))
    rms = float(0.5 * (1.4826 * np.median(np.abs(r1 - med_ra)) + 1.4826 * np.median(np.abs(r2 - med_dec))))
    off = float(np.hypot(med_ra, med_dec))
    problems = []
    if off > 0.5 * scale:
        problems.append(f"Versatz {off:.2f}″ > {0.5 * scale:.2f}″ (0,5 px)")
    if rms > 0.7 * scale:
        problems.append(f"Streuung {rms:.2f}″ > {0.7 * scale:.2f}″ (0,7 px)")
    if worst > 1.0 * scale:
        problems.append(f"schlechteste Bildzelle {worst:.2f}″ > {scale:.2f}″ (1 px)")
    return WCSCheck(len(x), int(inside.sum()), int(keep.sum()), med_ra, med_dec, rms, scale, trend, worst,
                    "OK" if not problems else "Warnung: " + "; ".join(problems),
                    mx, my, r1, r2, np.asarray(gaia["G"], float)[gi][keep])
