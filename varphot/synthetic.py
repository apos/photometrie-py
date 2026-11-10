"""Synthetische Testdaten für die Demo und Unit-Tests.

Nur für Tests und die Demo — nicht in der echten Pipeline verwenden.
"""
import numpy as np
from astropy.wcs import WCS
from astropy.table import Table

from .config import CFG

_rng = np.random.default_rng(42)


def make_wcs(ra0=337.29, dec0=58.41, cfg=None):
    cfg = cfg or CFG
    w = WCS(naxis=2)
    w.wcs.crpix = [cfg["nx"] / 2, cfg["ny"] / 2]
    w.wcs.crval = [ra0, dec0]
    w.wcs.cdelt = [-cfg["scale_arcsec"] / 3600, cfg["scale_arcsec"] / 3600]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


def make_catalog(w, n=60, cfg=None):
    cfg = cfg or CFG
    nx, ny = cfg["nx"], cfg["ny"]
    x = _rng.uniform(60, nx - 60, n)
    y = _rng.uniform(60, ny - 60, n)
    mag = np.sort(_rng.uniform(7.0, 13.0, n))
    bv = _rng.normal(0.8, 0.35, n).clip(0.0, 1.8)
    ra, dec = w.pixel_to_world_values(x, y)
    cat = Table({"id": np.arange(n), "ra": ra, "dec": dec, "V": mag, "BV": bv, "x": x, "y": y})
    cat["var"] = False
    cat["V"][0] = 4.0
    cat["x"][0], cat["y"][0] = nx * 0.5, ny * 0.5
    cat["ra"][0], cat["dec"][0] = w.pixel_to_world_values(cat["x"][0], cat["y"][0])
    cat["var"][0] = True
    cat["var"][7] = True
    return cat


def render_frame(cat, t, w, fwhm=4.5, zp=21.0, airmass_trend=0.0, cfg=None):
    """Rendert einen synthetischen Frame mit Poisson-Rauschen."""
    cfg = cfg or CFG
    nx, ny = cfg["nx"], cfg["ny"]
    P = cfg.get("period_days", 5.366)
    yy, xx = np.mgrid[0:ny, 0:nx]
    img = 800 + 30 * np.sin(xx / 400.0)
    for r in cat:
        v = r["V"]
        if r["id"] == 0:
            v = 3.75 + 0.35 * np.sin(2 * np.pi * t / P)
        if r["id"] == 7:
            v = r["V"] + 0.4 * np.sin(2 * np.pi * t / 0.9)
        v += airmass_trend
        flux = 10 ** (-0.4 * (v - zp))
        s = (22.0 if r["id"] == 0 else fwhm) / 2.355
        x0, y0 = r["x"], r["y"]
        x1, x2 = int(x0 - 6 * fwhm), int(x0 + 6 * fwhm)
        y1, y2 = int(y0 - 6 * fwhm), int(y0 + 6 * fwhm)
        x1, y1 = max(x1, 0), max(y1, 0)
        x2, y2 = min(x2, nx), min(y2, ny)
        sub = np.exp(-((xx[y1:y2, x1:x2] - x0) ** 2 + (yy[y1:y2, x1:x2] - y0) ** 2) / (2 * s * s))
        img[y1:y2, x1:x2] += flux * sub / (2 * np.pi * s * s)
    img = _rng.poisson(img.clip(0)).astype(float) + _rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 65535)


def bayer_frame(shape=(400, 600), signal_e=10000.0, gain=2.0, read_noise_e=3.0, offset=100.0, max_adu=16383,
                pattern="RGGB", qe=None, dark_e=0.0, flat_amp=0.03, rng=None):
    """Synthetisches rohes Bayer-Flat in ADU (Test und Demo fuer NB07): Schrot- plus Ausleserauschen, Offset, ADC-Grenze.

    ``signal_e``: mittlere Elektronen je Pixel (vor ``qe``); ``qe``: Faktoren je Ebene (``R``, ``G1``, ``G2``, ``B``);
    ``flat_amp``: feste Vignettierung (±), die in Differenzen verschwindet. Ergebnis ``round(clip((e + N(0,RN))/gain + offset))``.
    """
    from .camera import BAYER_OFFSETS
    rng = rng or np.random.default_rng()
    ny, nx = shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    flat = 1.0 + flat_amp * np.cos(np.pi * (xx / nx - 0.5)) * np.cos(np.pi * (yy / ny - 0.5)) - flat_amp
    q = np.ones((ny, nx))
    for name, (r, c) in BAYER_OFFSETS[pattern].items():
        q[r::2, c::2] = (qe or {}).get(name, 1.0)
    e = rng.poisson((signal_e * flat * q + dark_e).clip(0)).astype(float) + rng.normal(0, read_noise_e, (ny, nx))
    return np.clip(np.round(e / gain + offset), 0, max_adu)


TRUTH_TRANSFORM = dict(Tb_bv=0.25, Tv_bv=-0.08, Tr_bv=0.40, k=dict(b=0.30, g=0.18, r=0.10))


def standard_field(n_stars=24, truth=None, n_frames=8, noise_mag=0.01, rng=None, bv_range=(0.3, 1.4)):
    """Synthetisches Standardfeld (Test und Demo fuer NB08): Katalog ``id, B, V, R`` und Messtabellen je Kanal (``b``, ``g``, ``r``) mit bekannten Koeffizienten.

    Instrumentell gilt ``b = B − Tb·(B−V) + ZP_b`` usw. (Gl. 6.16–6.18 des AAVSO-Handbuchs), je Bild kommen Extinktion ``k·X`` (Luftmasse 1,1–1,9), ein zufaelliger Transparenzsprung und
    Messrauschen dazu. Ergebnis ``(cat, meas, truth)``; die erwartete Farbtransformation folgt aus ``1/Tbv = 1 − Tb + Tv``.
    """
    import pandas as pd
    rng = rng or np.random.default_rng()
    t = {**TRUTH_TRANSFORM, **(truth or {})}
    bv = rng.uniform(*bv_range, n_stars)
    V = rng.uniform(9.0, 12.5, n_stars)
    cat = pd.DataFrame(dict(id=[f"S{i:02d}" for i in range(n_stars)], B=V + bv, V=V, R=V - (0.45 * bv + 0.02)))
    inst = {"b": cat["B"] - t["Tb_bv"] * bv - 20.1, "g": cat["V"] - t["Tv_bv"] * bv - 20.4, "r": cat["R"] - t["Tr_bv"] * bv - 20.0}
    X = np.linspace(1.1, 1.9, n_frames)
    meas = {}
    for ch, kk in (("b", "b"), ("g", "g"), ("r", "r")):
        rows = []
        for j, x in enumerate(X):
            off = t["k"][kk] * x + rng.normal(0, 0.03)                         # Extinktion + Transparenz
            m = inst[ch].to_numpy() + off + rng.normal(0, noise_mag, n_stars)
            flux = 10 ** (-0.4 * m)
            rows += [dict(file=f"f{j:02d}", jd_mid=j, airmass=x, star_id=cat["id"][i], flux=flux[i], flux_err=flux[i] * noise_mag / 1.0857,
                          frame_flags="", star_flag="") for i in range(n_stars)]
        meas[ch] = pd.DataFrame(rows)
    truth_out = dict(t, Tbv=1.0 / (1 - t["Tb_bv"] + t["Tv_bv"]))
    return cat, meas, truth_out


def defocus_image(img, blur_fwhm_px: float, kind: str = "gauss", obstruction: float = 0.37):
    """Simuliert Defokussieren eines Bildes durch Faltung (Test und Demo fuer NB00 und das Plate-Solving).

    Warum: Fuer die Photometrie heller Sterne wird bewusst unscharf gestellt (sonst Saettigung, Bayer-Muster, Szintillation); das Plate-Solving und die Sterndetektion muessen mit solchen Bildern noch
    zurechtkommen. Mit echten Aufnahmen laesst sich das erst am Teleskop pruefen — vorher kann man ein scharfes Bild kuenstlich verunschaerfen.
    Wie: ``kind="gauss"``: Gauss-Filter mit der zusaetzlichen Breite ``blur_fwhm_px`` (FWHM, ``sigma = FWHM/2,3548``); die Gesamtbreite waechst quadratisch: ``sqrt(FWHM0² + blur²)``.
    ``kind="donut"``: Faltung mit einem Kreisring (Aussendurchmesser ``blur_fwhm_px``, Innendurchmesser ``obstruction`` mal Aussendurchmesser) — so sieht ein defokussierter Stern an einem Teleskop mit
    Fangspiegel aus (Schmidt-Cassegrain: etwa 0,35–0,4 Obstruktion, hier 0,37 als Startwert, nicht fuer ein bestimmtes Geraet gemessen). Der Fluss bleibt erhalten (Kern summiert zu 1).
    Grenzen: Eine Faltung des *scharfen* Bildes ersetzt kein echtes Defokussieren (Rauschen und Sternmuster werden mitgefaltet, Gradienten des Rands, Koma/Feldkruemmung fehlen); der Himmelshintergrund
    wird mitgefaltet (bleibt im Mittel gleich). Validierung: ``tests/test_synthetic.py`` (Fluss, Breitenzuwachs, Loch im Ring).
    """
    from scipy import ndimage, signal
    img = np.asarray(img, float)
    if blur_fwhm_px <= 0:
        return img.copy()
    if kind == "gauss":
        return ndimage.gaussian_filter(img, blur_fwhm_px / 2.3548, mode="nearest")
    if kind == "donut":
        R = blur_fwhm_px / 2.0
        n = int(np.ceil(R)) * 2 + 1
        yy, xx = np.mgrid[:n, :n] - n // 2
        r = np.hypot(xx, yy)
        k = ((r <= R) & (r >= obstruction * R)).astype(float)
        if k.sum() == 0:
            k[n // 2, n // 2] = 1.0
        return signal.fftconvolve(np.pad(img, n // 2, mode="edge"), k / k.sum(), mode="valid")
    raise ValueError(f"kind muss 'gauss' oder 'donut' sein, nicht {kind!r}")
