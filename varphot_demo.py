"""varphot_demo.py - Testkette fuer differentielle Photometrie (synthetische Daten).
Getestet mit: Python 3.13, astropy 8.0.2, photutils 3.1.1, numpy 2.5, matplotlib 3.11.
Stufen: 1 Testdaten -> 2 Detektion -> 3 Katalog-Crossmatch -> 4 Comp/Check-Auswahl
        -> 5 Aperturphotometrie -> 6 differentielle Helligkeit -> 7 Karte + Lichtkurve."""
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy.io import fits
from astropy.wcs import WCS
from astropy.table import Table
from astropy.coordinates import SkyCoord
import astropy.units as u
from astropy.visualization import ImageNormalize, ZScaleInterval, AsinhStretch
from astropy.stats import sigma_clipped_stats
from astropy.timeseries import LombScargle
from photutils.detection import DAOStarFinder
from photutils.aperture import CircularAperture, CircularAnnulus, ApertureStats

rng = np.random.default_rng(42)
SAT_ADU = 50000                             # Peak-Grenze (Linearitaet der Kamera pruefen)
NX, NY, SCALE = 1600, 1100, 1.44          # Pixel, Bogensekunden/Pixel (Apo 80/540 + QHY268M)
P, T0 = 5.366, 0.0                         # Periode Delta Cep in Tagen

# ---------- 1 Testdaten ----------
def make_wcs(ra0=337.29, dec0=58.41):
    w = WCS(naxis=2)
    w.wcs.crpix = [NX/2, NY/2]; w.wcs.crval = [ra0, dec0]
    w.wcs.cdelt = [-SCALE/3600, SCALE/3600]; w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return w

def make_catalog(w, n=60):
    x = rng.uniform(60, NX-60, n); y = rng.uniform(60, NY-60, n)
    mag = np.sort(rng.uniform(7.0, 13.0, n))           # V-Magnituden
    bv = rng.normal(0.8, 0.35, n).clip(0.0, 1.8)       # B-V
    ra, dec = w.pixel_to_world_values(x, y)
    cat = Table({"id": np.arange(n), "ra": ra, "dec": dec, "V": mag, "BV": bv, "x": x, "y": y})
    cat["var"] = False
    cat["V"][0] = 4.0; cat["x"][0], cat["y"][0] = NX*0.5, NY*0.5   # Ziel: hell (Cepheide)
    cat["ra"][0], cat["dec"][0] = w.pixel_to_world_values(cat["x"][0], cat["y"][0])
    cat["var"][0] = True
    cat["var"][7] = True                                # ein weiterer Veraenderlicher (VSX) im Feld
    return cat

def render_frame(cat, t, w, fwhm=4.5, zp=21.0, airmass_trend=0.0):
    yy, xx = np.mgrid[0:NY, 0:NX]
    img = 800 + 30*np.sin(xx/400.0)                     # Himmelshintergrund mit Gradient
    for r in cat:
        v = r["V"]
        if r["id"] == 0: v = 3.75 + 0.35*np.sin(2*np.pi*(t-T0)/P)   # Lichtwechsel
        if r["id"] == 7: v = r["V"] + 0.4*np.sin(2*np.pi*t/0.9)
        v += airmass_trend
        flux = 10**(-0.4*(v - zp))
        s = (22.0 if r["id"] == 0 else fwhm)/2.355     # Ziel defokussiert (FWHM ca. 22 px)
        x0, y0 = r["x"], r["y"]
        x1, x2 = int(x0-6*fwhm), int(x0+6*fwhm); y1, y2 = int(y0-6*fwhm), int(y0+6*fwhm)
        x1, y1 = max(x1,0), max(y1,0); x2, y2 = min(x2,NX), min(y2,NY)
        sub = np.exp(-((xx[y1:y2,x1:x2]-x0)**2+(yy[y1:y2,x1:x2]-y0)**2)/(2*s*s))
        img[y1:y2, x1:x2] += flux*sub/(2*np.pi*s*s)
    img = rng.poisson(img.clip(0)).astype(float) + rng.normal(0, 4, img.shape)
    return np.clip(img, 0, 65535)

# ---------- 2 Detektion ----------
def detect(img, fwhm=4.5, nsigma=8.0):
    mean, med, std = sigma_clipped_stats(img, sigma=3.0)
    finder = DAOStarFinder(fwhm=fwhm, threshold=nsigma*std)
    src = finder(img - med)
    return src, med, std

# ---------- 3 Crossmatch mit Katalog (hier: synthetischer Katalog) ----------
def crossmatch(src, cat, w, tol_arcsec=3.0):
    sc = SkyCoord(*w.pixel_to_world_values(src["x_centroid"], src["y_centroid"]), unit="deg")
    cc = SkyCoord(cat["ra"], cat["dec"], unit="deg")
    idx, sep, _ = sc.match_to_catalog_sky(cc)
    ok = sep < tol_arcsec*u.arcsec
    out = src[ok].copy(); out["cat_id"] = cat["id"][idx[ok]]
    out["V"] = cat["V"][idx[ok]]; out["BV"] = cat["BV"][idx[ok]]; out["var"] = cat["var"][idx[ok]]
    return out

# ---------- 4 Comp/Check-Auswahl nach Regeln ----------
def select_comps(m, cat, w, target_id=0, dmag=2.0, bv_tol=0.35, edge=80, r_iso_px=25, n_comp=8):
    c0 = cat[cat["id"] == target_id][0]                  # Ziel aus Katalog, nicht aus der Detektion
    tx, ty = w.world_to_pixel_values(c0["ra"], c0["dec"])
    t = {"V": c0["V"], "BV": c0["BV"], "x_centroid": float(tx), "y_centroid": float(ty), "cat_id": target_id}
    cand = []
    for r in m:
        if r["cat_id"] == target_id or r["var"]: continue                    # keine Veraenderlichen
        if np.hypot(r["x_centroid"]-t["x_centroid"], r["y_centroid"]-t["y_centroid"]) < 60: continue  # nicht im Halo des defokussierten Ziels
        if abs(r["V"] - t["V"]) > 6: continue                                # Helligkeitsspanne
        if abs(r["BV"] - t["BV"]) > bv_tol: continue                         # aehnliche Farbe
        if not (edge < r["x_centroid"] < NX-edge and edge < r["y_centroid"] < NY-edge): continue
        d = np.hypot(m["x_centroid"]-r["x_centroid"], m["y_centroid"]-r["y_centroid"])
        if np.sum(d < r_iso_px) > 1: continue                                # Nachbar im Aperturbereich
        if r["peak"] > 40000: continue                                       # keine Saettigung
        cand.append(r)
    cand.sort(key=lambda r: abs(r["V"]-(t["V"]+dmag)))
    comps = cand[:n_comp]
    check = cand[n_comp] if len(cand) > n_comp else None
    return t, comps, check

# ---------- 5 Aperturphotometrie ----------
def aperture_flux(img, xy, r_ap=10, r_in=18, r_out=26):
    ap = CircularAperture(xy, r=r_ap); an = CircularAnnulus(xy, r_in=r_in, r_out=r_out)
    sky = ApertureStats(img, an, sigma_clip=None)
    bkg = sky.median
    st = ApertureStats(img - 0, ap)
    flux = st.sum - bkg*ap.area
    peak = st.max - bkg
    if np.any(peak > SAT_ADU): print("WARNUNG: Saettigung/Nichtlinearitaet, Peak", float(np.max(peak)))
    return flux, np.sqrt(np.abs(st.sum)), bkg

# ---------- 6 differentielle Helligkeit (Ensemble) ----------
def diff_mag(f_t, f_c, V_c, f_k=None, V_k=None):
    zp = V_c + 2.5*np.log10(f_c)                    # Nullpunkt je Comp
    zp_med = np.median(zp); zp_sd = np.std(zp, ddof=1)
    m_t = -2.5*np.log10(f_t) + zp_med
    m_k = -2.5*np.log10(f_k) + zp_med if f_k is not None else np.nan
    return m_t, m_k, zp_sd

if __name__ == "__main__":
    w = make_wcs(); cat = make_catalog(w)
    # Referenzbild fuer Auswahl
    ref = render_frame(cat, t=0.3, w=w)
    src, med, std = detect(ref)
    m = crossmatch(src, cat, w)
    tgt, comps, chk = select_comps(m, cat, w)
    print(f"Detektion: {len(src)} Quellen, gematcht: {len(m)}, Comps: {len(comps)}, Check: {chk['cat_id'] if chk is not None else None}")
    # ----- Karte -----
    fig = plt.figure(figsize=(11, 7.8)); ax = fig.add_subplot(111, projection=w)
    norm = ImageNormalize(ref, interval=ZScaleInterval(), stretch=AsinhStretch(a=0.1))
    ax.imshow(ref, origin="lower", cmap="gray_r", norm=norm)
    for r in src:
        ax.plot(r["x_centroid"], r["y_centroid"], "o", mfc="none", mec="tab:blue", ms=9, mew=0.7, alpha=.6)
    ax.plot(tgt["x_centroid"], tgt["y_centroid"], "s", mfc="none", mec="red", ms=30, mew=2); ax.annotate("Ziel", (tgt["x_centroid"], tgt["y_centroid"]), xytext=(14, 14), textcoords="offset points", color="red", weight="bold")
    for k, r in enumerate(comps, 1):
        ax.plot(r["x_centroid"], r["y_centroid"], "o", mfc="none", mec="green", ms=18, mew=2)
        ax.annotate(f"C{k}  V={r['V']:.2f}", (r["x_centroid"], r["y_centroid"]), xytext=(12, 10), textcoords="offset points", color="green", fontsize=8)
    if chk is not None:
        ax.plot(chk["x_centroid"], chk["y_centroid"], "D", mfc="none", mec="darkorange", ms=18, mew=2)
        ax.annotate(f"Check V={chk['V']:.2f}", (chk["x_centroid"], chk["y_centroid"]), xytext=(12, 10), textcoords="offset points", color="darkorange", fontsize=8)
    for r in m[m["var"] & (m["cat_id"] != 0)]:
        ax.plot(r["x_centroid"], r["y_centroid"], "x", c="magenta", ms=14, mew=2); ax.annotate("Veraenderlicher (VSX)", (r["x_centroid"], r["y_centroid"]), xytext=(10,-14), textcoords="offset points", color="magenta", fontsize=8)
    ax.coords.grid(color="k", alpha=.2); ax.set_xlabel("RA"); ax.set_ylabel("Dec")
    ax.set_title("Karte: erkannte Sterne (blau), Ziel (rot), Comps (gruen), Check (orange)")
    fig.savefig("chart.png", dpi=110, bbox_inches="tight"); plt.close(fig)
    # ----- Zeitreihe -----
    times = np.sort(rng.uniform(0, 14, 90)); rows = []
    for t in times:
        img = render_frame(cat, t, w, airmass_trend=rng.normal(0, 0.01))
        # Positionen aus Referenz (Plate-Solve-WCS gilt fuer alle Frames; sonst je Frame nachfuehren)
        f_t, e_t, _ = aperture_flux(img, [(tgt["x_centroid"], tgt["y_centroid"])], r_ap=45, r_in=55, r_out=70)   # defokussiertes Ziel: grosse Apertur
        f_c = np.array([aperture_flux(img, [(c["x_centroid"], c["y_centroid"])])[0][0] for c in comps])
        f_k = aperture_flux(img, [(chk["x_centroid"], chk["y_centroid"])])[0][0]
        mt, mk, sd = diff_mag(f_t[0], f_c, np.array([c["V"] for c in comps]), f_k, chk["V"])
        rows.append((t, mt, mk, sd))
    lc = np.array(rows)
    print("Check-Stern: Soll V=%.3f, Messung Mittel %.3f, Streuung %.4f mag" % (chk["V"], lc[:,2].mean(), lc[:,2].std()))
    # Lomb-Scargle
    freq, power = LombScargle(lc[:,0], lc[:,1]).autopower(minimum_frequency=1/20, maximum_frequency=2, samples_per_peak=50)
    pbest = 1/freq[np.argmax(power)]; print(f"Lomb-Scargle Periode: {pbest:.3f} d (Soll {P})")
    fig, axs = plt.subplots(2, 2, figsize=(12, 7.5))
    ax = axs[0,0]; ax.plot(lc[:,0], lc[:,1], "ko", ms=3); ax.invert_yaxis(); ax.set_xlabel("t [d]"); ax.set_ylabel("V (diff.) [mag]"); ax.set_title("Lichtkurve Ziel")
    ax = axs[0,1]; ax.plot(lc[:,0], lc[:,2]-lc[:,2].mean(), "o", c="darkorange", ms=3); ax.axhline(0, c="k", lw=.5); ax.set_ylim(0.1, -0.1); ax.set_xlabel("t [d]"); ax.set_ylabel("Check - Mittel [mag]"); ax.set_title(f"Check-Stern (Streuung {lc[:,2].std():.4f} mag)")
    ax = axs[1,0]; ph = (lc[:,0]/pbest) % 1; ax.plot(np.r_[ph, ph+1], np.r_[lc[:,1], lc[:,1]], "ko", ms=3); ax.invert_yaxis(); ax.set_xlabel(f"Phase (P = {pbest:.3f} d)"); ax.set_ylabel("V [mag]"); ax.set_title("Phasenkurve")
    ax = axs[1,1]; ax.plot(1/freq, power, "k-"); ax.axvline(pbest, c="r", ls=":"); ax.set_xlabel("Periode [d]"); ax.set_ylabel("Lomb-Scargle-Leistung"); ax.set_title("Periodogramm")
    fig.tight_layout(); fig.savefig("lightcurve.png", dpi=110); plt.close(fig)
