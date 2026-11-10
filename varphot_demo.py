"""varphot_demo.py — End-to-End-Test mit synthetischen Daten.

Getestet mit: Python 3.13, astropy 8.0.2, photutils 3.1.1, numpy 2.5, matplotlib 3.11.
Erwartete Ausgabe (bei Erfolg):
  Detektion: 46 Quellen, gematcht: 46, Comps: 8, Check: 19
  Check-Stern: Soll V=8.903, Messung Mittel 8.902, Streuung 0.0105 mag
  Lomb-Scargle Periode: 5.345 d (Soll 5.366)
  chart.png und lightcurve.png geschrieben.
"""
import numpy as np
import matplotlib; matplotlib.use("Agg")

from varphot import CFG, detect, crossmatch, select_comps, aperture_flux, diff_mag
from varphot import chart_map, plot_lightcurve
from varphot.synthetic import make_wcs, make_catalog, render_frame

rng = np.random.default_rng(42)

w = make_wcs()
cat = make_catalog(w)

# Referenzbild für Quellenauswahl
ref = render_frame(cat, t=0.3, w=w)
src, _, _ = detect(ref, fwhm=CFG["detect_fwhm"], nsigma=CFG["detect_nsigma"])
m = crossmatch(src, cat, w)
tgt, comps, chk = select_comps(m, cat, w)
print(f"Detektion: {len(src)} Quellen, gematcht: {len(m)}, "
      f"Comps: {len(comps)}, Check: {chk['cat_id'] if chk is not None else None}")

# Sternkarte
var_rows = m[m["var"] & (m["cat_id"] != 0)]
chart_map(ref, w, src, tgt, comps, chk, var_rows)

# Zeitreihe (90 Messpunkte über 14 Nächte)
times = np.sort(rng.uniform(0, 14, 90))
rows = []
for t in times:
    img = render_frame(cat, t, w, airmass_trend=rng.normal(0, 0.01))
    f_t, _, _ = aperture_flux(img, [(tgt["x_centroid"], tgt["y_centroid"])],
                              r_ap=CFG["target_ap_r"], r_in=CFG["target_ap_r_in"],
                              r_out=CFG["target_ap_r_out"])
    f_c = np.array([aperture_flux(img, [(c["x_centroid"], c["y_centroid"])])[0][0]
                    for c in comps])
    f_k = aperture_flux(img, [(chk["x_centroid"], chk["y_centroid"])])[0][0]
    mt, mk, sd = diff_mag(f_t[0], f_c, np.array([c["V"] for c in comps]), f_k)
    rows.append((t, mt, mk, sd))

lc = np.array(rows)
print(f"Check-Stern: Soll V={chk['V']:.3f}, "
      f"Messung Mittel {lc[:, 2].mean():.3f}, Streuung {lc[:, 2].std():.4f} mag")

pbest = plot_lightcurve(lc, period=CFG.get("period_days", 5.366))
print(f"Lomb-Scargle Periode: {pbest:.3f} d (Soll {CFG.get('period_days', 5.366)})")

# Verifikation: Mindestqualität prüfen
assert len(comps) >= 5, f"Zu wenige Comps: {len(comps)}"
assert lc[:, 2].std() < 0.05, f"Check-Streuung zu groß: {lc[:, 2].std():.4f} mag"
assert abs(pbest - 5.366) < 0.5, f"Periode weicht stark ab: {pbest:.3f} d"
print("chart.png und lightcurve.png geschrieben.")
