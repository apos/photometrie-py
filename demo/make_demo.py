"""demo/make_demo.py — Synthetische FITS-Testdaten für Notebook 01-04.

Erzeugt eine vollständige Siril-Workspace-Struktur mit:
  demo/siril_workspace/
    lights/     20 Rohbilder (variable + Vergleichssterne, Rauschen, Bias, Dark)
    darks/       5 Master-Dark-Kandidaten
    flats/       5 Flat-Frames
    biases/      5 Bias-Frames
    process/    20 kalibrierte Frames (bereit für Notebook 02)

Zielstern:   Delta Cep (Cepheid, V ≈ 3.5–4.4 mag, P ≈ 5.366 d) — simuliert
Bildgröße:  1600 × 1100 px  (QHY268M-Ausschnitt, 1.44 arcsec/px)
WCS:         RA 22h 29m 10s, Dec +58° 24' 55" (Delta Cep Umgebung)
"""

from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.time import Time
import astropy.units as u

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------
DEMO_DIR = Path(__file__).parent / "siril_workspace"
LIGHTS_DIR  = DEMO_DIR / "lights"
DARKS_DIR   = DEMO_DIR / "darks"
FLATS_DIR   = DEMO_DIR / "flats"
BIASES_DIR  = DEMO_DIR / "biases"
PROCESS_DIR = DEMO_DIR / "process"

for d in [LIGHTS_DIR, DARKS_DIR, FLATS_DIR, BIASES_DIR, PROCESS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# Kamera- und Optik-Parameter (QHY268M / Apo 80/540)
# ---------------------------------------------------------------------------
NX, NY         = 1600, 1100
SCALE          = 1.44           # arcsec/px
GAIN_E_ADU     = 1.0            # e-/ADU
READ_NOISE_E   = 3.5            # e-
DARK_CURRENT   = 0.02           # e-/px/s
BIAS_LEVEL     = 1000           # ADU
EXPTIME        = 120.0          # s
SAT_ADU        = 65535

# ---------------------------------------------------------------------------
# WCS (Delta Cep Feld)
# ---------------------------------------------------------------------------
RA_CENTER  = 337.2917   # 22h 29m 10s
DEC_CENTER =  58.4153   # +58° 24' 55"

def make_wcs():
    w = WCS(naxis=2)
    w.wcs.crpix = [NX / 2, NY / 2]
    w.wcs.cdelt = [-SCALE / 3600, SCALE / 3600]
    w.wcs.crval = [RA_CENTER, DEC_CENTER]
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w


# ---------------------------------------------------------------------------
# Sternkatalog (Zielstern + 12 Vergleichssterne)
# ---------------------------------------------------------------------------
def make_catalog(wcs):
    """Gibt dict mit Sternen: ra, dec, V, B-V, is_target."""
    stars = [
        # Zielstern Delta Cep (wird Lichtkurve bekommen)
        dict(ra=337.2917, dec=58.4153, V=3.75, bv=0.58, is_target=True,  label="DeltaCep"),
        # Vergleichssterne (AAVSO-ähnlich, V 3–8 mag)
        dict(ra=337.1800, dec=58.4500, V=5.10, bv=0.72, is_target=False, label="C01"),
        dict(ra=337.4200, dec=58.3800, V=5.65, bv=0.65, is_target=False, label="C02"),
        dict(ra=337.0500, dec=58.5000, V=6.20, bv=0.80, is_target=False, label="C03"),
        dict(ra=337.5500, dec=58.3200, V=6.80, bv=0.55, is_target=False, label="C04"),
        dict(ra=337.1200, dec=58.2800, V=7.10, bv=0.90, is_target=False, label="C05"),
        dict(ra=337.3600, dec=58.5600, V=7.40, bv=0.68, is_target=False, label="C06"),
        dict(ra=337.6000, dec=58.4800, V=7.80, bv=0.75, is_target=False, label="C07"),
        dict(ra=337.2000, dec=58.1500, V=8.10, bv=0.60, is_target=False, label="C08"),
        # Hintergrundsterne (schwächer, keine Comps)
        dict(ra=337.4800, dec=58.5200, V=9.50, bv=0.40, is_target=False, label="S01"),
        dict(ra=337.1500, dec=58.3300, V=9.80, bv=0.95, is_target=False, label="S02"),
        dict(ra=337.3000, dec=58.2000, V=10.2, bv=0.50, is_target=False, label="S03"),
        dict(ra=337.5000, dec=58.6000, V=10.8, bv=1.10, is_target=False, label="S04"),
    ]
    # Pixel-Koordinaten berechnen
    for s in stars:
        xy = wcs.all_world2pix([[s["ra"], s["dec"]]], 0)[0]
        s["x"], s["y"] = float(xy[0]), float(xy[1])
    return stars


# ---------------------------------------------------------------------------
# Hilfsfunktionen: Gauß-PSF, Fluss aus Magnitude
# ---------------------------------------------------------------------------
FWHM_PX = 4.0
SIGMA_PX = FWHM_PX / (2 * np.sqrt(2 * np.log(2)))
ZP_INST  = 20.0  # Instrumenteller Nullpunkt (mag)


def v_to_flux(V):
    return 10 ** ((ZP_INST - V) / 2.5) * EXPTIME


def add_star(img, x, y, flux):
    """Addiert eine Gauß-PSF auf img (in-place)."""
    xi = int(round(x))
    yi = int(round(y))
    r  = int(4 * SIGMA_PX) + 2
    xs = np.arange(max(0, xi - r), min(NX, xi + r + 1))
    ys = np.arange(max(0, yi - r), min(NY, yi + r + 1))
    if xs.size == 0 or ys.size == 0:
        return
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    gauss  = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * SIGMA_PX ** 2))
    gauss *= flux / (2 * np.pi * SIGMA_PX ** 2)
    img[ys[:, None], xs[None, :]] += gauss


def delta_cep_mag(t_days):
    """Lichtkurven-Modell für Delta Cep: V zwischen 3.5 und 4.4 mag."""
    P = 5.366
    phase = (t_days % P) / P
    # Asymmetrische Lichtkurve (schneller Anstieg, langsamer Abfall)
    if phase < 0.3:
        m = 3.5 + (4.4 - 3.5) * (phase / 0.3)
    else:
        m = 4.4 - (4.4 - 3.5) * ((phase - 0.3) / 0.7)
    return m


# ---------------------------------------------------------------------------
# Rohbild-Generator
# ---------------------------------------------------------------------------
def make_raw_frame(catalog, wcs, t_days, airmass=1.2):
    img = np.zeros((NY, NX), dtype=np.float64)

    # Bias-Level
    img += BIAS_LEVEL

    # Dark current
    dark = RNG.poisson(DARK_CURRENT * EXPTIME, size=(NY, NX)).astype(float)
    img += dark

    # Himmels-Hintergrund (100 e-/px)
    sky = RNG.poisson(100, size=(NY, NX)).astype(float)
    img += sky

    # Sterne
    for s in catalog:
        V = delta_cep_mag(t_days) if s["is_target"] else s["V"]
        # Airmass-Extinktion (simple)
        V_eff = V + 0.1 * (airmass - 1.0)
        flux  = v_to_flux(V_eff)
        add_star(img, s["x"], s["y"], flux)

    # Schuss-Rauschen + Ausleserauschen
    img = np.clip(img, 0, None)
    shot = RNG.poisson(img).astype(float)
    read = RNG.normal(0, READ_NOISE_E, size=(NY, NX))
    img  = shot + read + BIAS_LEVEL * 0.0  # Bias schon drin

    return np.clip(img, 0, SAT_ADU).astype(np.uint16)


def make_calibrated_frame(catalog, wcs, t_days, airmass=1.2):
    """Simuliert ein kalibriertes Frame (Bias/Dark/Flat bereits abgezogen)."""
    img = np.zeros((NY, NX), dtype=np.float64)

    # Himmels-Hintergrund (kalibriert: niedriger Rest)
    sky = RNG.poisson(50, size=(NY, NX)).astype(float)
    img += sky

    for s in catalog:
        V = delta_cep_mag(t_days) if s["is_target"] else s["V"]
        V_eff = V + 0.1 * (airmass - 1.0)
        flux  = v_to_flux(V_eff)
        add_star(img, s["x"], s["y"], flux)

    img = np.clip(img, 0, None)
    shot = RNG.poisson(img).astype(float)
    read = RNG.normal(0, READ_NOISE_E, size=(NY, NX))
    img  = shot + read

    return np.clip(img, 0, SAT_ADU).astype(np.uint16)


# ---------------------------------------------------------------------------
# FITS-Header
# ---------------------------------------------------------------------------
def base_header(wcs, date_obs, exptime=EXPTIME, frame_type="LIGHT", airmass=1.2):
    h = fits.Header()
    h["SIMPLE"]   = True
    h["BITPIX"]   = 16
    h["NAXIS"]    = 2
    h["NAXIS1"]   = NX
    h["NAXIS2"]   = NY
    h["OBJECT"]   = "Delta Cep"
    h["TELESCOP"] = "Apo 80/540"
    h["INSTRUME"] = "QHY268M"
    h["DATE-OBS"] = date_obs
    h["EXPTIME"]  = exptime
    h["GAIN"]     = 0
    h["CCD-TEMP"] = -15.0
    h["XBINNING"] = 1
    h["YBINNING"] = 1
    h["FILTER"]   = "V"
    h["SITELAT"]  = 48.3
    h["SITELONG"] = 14.3
    h["AIRMASS"]  = round(airmass, 3)
    h["IMAGETYP"] = frame_type
    # WCS
    wcs_hdr = wcs.to_header()
    for k, v in wcs_hdr.items():
        h[k] = v
    return h


# ---------------------------------------------------------------------------
# Hauptprogramm
# ---------------------------------------------------------------------------
def main():
    wcs     = make_wcs()
    catalog = make_catalog(wcs)

    t0 = Time("2024-09-01T22:00:00", format="isot", scale="utc")

    # 20 Light-Frames über 14 Nächte
    n_lights = 20
    times_days = np.sort(RNG.uniform(0, 14, n_lights))
    airmasses  = RNG.uniform(1.1, 1.8, n_lights)

    print("Erzeuge Light-Frames …")
    for i, (td, am) in enumerate(zip(times_days, airmasses), 1):
        t_obs  = t0 + td * u.day
        date_s = t_obs.isot
        raw    = make_raw_frame(catalog, wcs, td, am)
        h      = base_header(wcs, date_s, frame_type="LIGHT", airmass=am)
        fname  = LIGHTS_DIR / f"light_{i:03d}.fits"
        fits.PrimaryHDU(raw, header=h).writeto(fname, overwrite=True)

        cal    = make_calibrated_frame(catalog, wcs, td, am)
        h_cal  = base_header(wcs, date_s, frame_type="LIGHT", airmass=am)
        h_cal["HISTORY"] = "Siril: bias/dark/flat calibrated (simulated)"
        cfname = PROCESS_DIR / f"pp_light_{i:03d}.fits"
        fits.PrimaryHDU(cal, header=h_cal).writeto(cfname, overwrite=True)
        print(f"  {i:2d}/20  t={td:.2f}d  AM={am:.2f}  V_tgt={delta_cep_mag(td):.3f}")

    # 5 Bias-Frames
    print("Erzeuge Bias-Frames …")
    for i in range(1, 6):
        bias = (BIAS_LEVEL + RNG.normal(0, READ_NOISE_E, (NY, NX))).astype(np.uint16)
        h    = fits.Header()
        h["IMAGETYP"] = "BIAS"
        h["EXPTIME"]  = 0.0
        h["INSTRUME"] = "QHY268M"
        h["DATE-OBS"] = t0.isot
        fits.PrimaryHDU(bias, header=h).writeto(BIASES_DIR / f"bias_{i:03d}.fits", overwrite=True)

    # 5 Dark-Frames (120s)
    print("Erzeuge Dark-Frames …")
    for i in range(1, 6):
        dark = (BIAS_LEVEL
                + RNG.poisson(DARK_CURRENT * EXPTIME, (NY, NX))
                + RNG.normal(0, READ_NOISE_E, (NY, NX))).astype(np.uint16)
        h    = fits.Header()
        h["IMAGETYP"] = "DARK"
        h["EXPTIME"]  = EXPTIME
        h["INSTRUME"] = "QHY268M"
        h["DATE-OBS"] = t0.isot
        fits.PrimaryHDU(dark, header=h).writeto(DARKS_DIR / f"dark_{i:03d}.fits", overwrite=True)

    # 5 Flat-Frames
    print("Erzeuge Flat-Frames …")
    # Flache Vignettierung: Gaussian-Profil, Rand 85% der Mitte
    yy, xx = np.mgrid[0:NY, 0:NX]
    vign   = np.exp(-((xx - NX/2)**2 / (2*(NX*0.6)**2) +
                      (yy - NY/2)**2 / (2*(NY*0.6)**2)))
    vign   = 0.85 + 0.15 * vign / vign.max()
    flat_level = 30000
    for i in range(1, 6):
        flat = (flat_level * vign + RNG.normal(0, 50, (NY, NX))).astype(np.uint16)
        h    = fits.Header()
        h["IMAGETYP"] = "FLAT"
        h["EXPTIME"]  = 5.0
        h["INSTRUME"] = "QHY268M"
        h["FILTER"]   = "V"
        h["DATE-OBS"] = t0.isot
        fits.PrimaryHDU(flat, header=h).writeto(FLATS_DIR / f"flat_{i:03d}.fits", overwrite=True)

    print(f"\nFertig. Workspace: {DEMO_DIR}")
    print(f"  lights/:  {n_lights} Frames")
    print(f"  darks/:    5 Frames (120s)")
    print(f"  flats/:    5 Frames (V-Filter)")
    print(f"  biases/:   5 Frames")
    print(f"  process/: {n_lights} kalibrierte Frames (pp_light_*.fits)")
    print(f"\nNotizbuch 01: Workspace = {DEMO_DIR}")
    print(f"Notizbuch 02: DIR_CAL   = {PROCESS_DIR}")


if __name__ == "__main__":
    main()
