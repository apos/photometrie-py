"""Visualisierungen: Sternkarte und Lichtkurve."""
import numpy as np
import matplotlib.pyplot as plt
from astropy.visualization import ImageNormalize, ZScaleInterval, AsinhStretch


def chart_map(img, w, src, tgt, comps, check, var_rows, outfile="chart.png"):
    """Sternkarte: alle detektierten Quellen, Ziel, Comps, Check, Veränderliche."""
    fig = plt.figure(figsize=(11, 7.8))
    ax = fig.add_subplot(111, projection=w)
    norm = ImageNormalize(img, interval=ZScaleInterval(), stretch=AsinhStretch(a=0.1))
    ax.imshow(img, origin="lower", cmap="gray_r", norm=norm)

    for r in src:
        ax.plot(r["x_centroid"], r["y_centroid"], "o",
                mfc="none", mec="tab:blue", ms=9, mew=0.7, alpha=0.6)

    ax.plot(tgt["x_centroid"], tgt["y_centroid"], "s",
            mfc="none", mec="red", ms=30, mew=2)
    ax.annotate("Ziel", (tgt["x_centroid"], tgt["y_centroid"]),
                xytext=(14, 14), textcoords="offset points", color="red", weight="bold")

    for k, r in enumerate(comps, 1):
        ax.plot(r["x_centroid"], r["y_centroid"], "o",
                mfc="none", mec="green", ms=18, mew=2)
        ax.annotate(f"C{k}  V={r['V']:.2f}", (r["x_centroid"], r["y_centroid"]),
                    xytext=(12, 10), textcoords="offset points", color="green", fontsize=8)

    if check is not None:
        ax.plot(check["x_centroid"], check["y_centroid"], "D",
                mfc="none", mec="darkorange", ms=18, mew=2)
        ax.annotate(f"Check V={check['V']:.2f}", (check["x_centroid"], check["y_centroid"]),
                    xytext=(12, 10), textcoords="offset points", color="darkorange", fontsize=8)

    for r in var_rows:
        ax.plot(r["x_centroid"], r["y_centroid"], "x", c="magenta", ms=14, mew=2)
        ax.annotate("Veränderlicher (VSX)", (r["x_centroid"], r["y_centroid"]),
                    xytext=(10, -14), textcoords="offset points", color="magenta", fontsize=8)

    ax.coords.grid(color="k", alpha=0.2)
    ax.set_xlabel("RA"); ax.set_ylabel("Dec")
    ax.set_title("Karte: erkannte Sterne (blau), Ziel (rot), Comps (grün), Check (orange)")
    fig.savefig(outfile, dpi=110, bbox_inches="tight")
    plt.close(fig)


def plot_detections(img, w, src, fwhm=5.0, zoom_center=None, zoom_size=(700, 525),
                    target=None, max_px=2500, max_overview=1500, outfile=None):
    """Sternkarte für ein echtes Bild: Übersicht (verkleinert) + Ausschnitt in voller Auflösung.

    Links das ganze Bild mit den ``max_overview`` hellsten erkannten Quellen (kleine Kreise), rechts ein Ausschnitt
    1:1 mit Kreisen im Radius 1,5·FWHM; beide mit RA/Dec-Gitter der WCS ``w``.
    ``src``: Ergebnistabelle von :func:`varphot.detect` (Spalten ``x_centroid``, ``y_centroid``,
    ``flux``). ``zoom_center=(x, y)`` in Pixeln; ``None`` = Fensterlage mit den meisten Quellen.
    ``target=(ra, dec)`` in Grad markiert die Zielposition (gelber Kreis) im Übersichtsbild.
    Gibt die Figure zurück (bei ``outfile`` zusätzlich gespeichert und geschlossen).
    """
    ny, nx = img.shape[-2:]
    f = max(1, int(np.ceil(max(nx, ny) / max_px)))
    small = np.asarray(img[::f, ::f], dtype=float)
    xs = np.asarray(src["x_centroid"], float); ys = np.asarray(src["y_centroid"], float)
    flux = np.asarray(src["flux"], float)

    zw, zh = zoom_size
    if zoom_center is None:
        hist, xe, ye = np.histogram2d(xs, ys, bins=[max(1, nx // zw), max(1, ny // zh)],
                                      range=[[0, nx], [0, ny]])
        i, j = np.unravel_index(np.argmax(hist), hist.shape)
        zoom_center = (0.5 * (xe[i] + xe[i + 1]), 0.5 * (ye[j] + ye[j + 1]))
    x0 = int(np.clip(zoom_center[0] - zw / 2, 0, nx - zw)); x1 = x0 + zw
    y0 = int(np.clip(zoom_center[1] - zh / 2, 0, ny - zh)); y1 = y0 + zh
    crop = np.asarray(img[y0:y1, x0:x1], dtype=float)
    # Ausschnitt flachziehen (großräumigen Nebel abziehen), sonst verschwinden schwache Sterne im Stretch
    from scipy.ndimage import gaussian_filter, median_filter
    crop = crop - gaussian_filter(median_filter(crop, size=25), 20)

    fig = plt.figure(figsize=(16, 7.2))
    ax1 = fig.add_subplot(1, 2, 1, projection=w)
    ax2 = fig.add_subplot(1, 2, 2, projection=w)

    norm1 = ImageNormalize(small, interval=ZScaleInterval(), stretch=AsinhStretch(a=0.1))
    ax1.imshow(small, origin="lower", cmap="gray_r", norm=norm1,
               extent=(-0.5, nx - 0.5, -0.5, ny - 0.5))
    top = np.argsort(flux)[::-1][:max_overview]
    ax1.scatter(xs[top], ys[top], s=22, facecolors="none", edgecolors="tab:blue", linewidths=0.5, alpha=0.8)
    ax1.add_patch(plt.Rectangle((x0, y0), zw, zh, fill=False, ec="red", lw=1.5))
    if target is not None:
        tx, ty = w.all_world2pix([[target[0], target[1]]], 0)[0]
        ax1.plot(tx, ty, "o", ms=26, mfc="none", mec="gold", mew=2)
    ax1.set_xlim(-0.5, nx - 0.5); ax1.set_ylim(-0.5, ny - 0.5)
    ax1.set_title(f"Übersicht: {len(xs)} Quellen erkannt, {min(len(xs), max_overview)} hellste markiert "
                  f"(Anzeige 1:{f}; roter Rahmen = Ausschnitt)", fontsize=10)

    norm2 = ImageNormalize(crop, interval=ZScaleInterval(), stretch=AsinhStretch(a=0.1))
    ax2.imshow(crop, origin="lower", cmap="gray_r", norm=norm2,
               extent=(x0 - 0.5, x1 - 0.5, y0 - 0.5, y1 - 0.5))
    inside = (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
    ax2.scatter(xs[inside], ys[inside], s=(3 * fwhm * 1.5) ** 2 / 4, facecolors="none",
                edgecolors="tab:blue", linewidths=0.8)
    order = np.argsort(flux[inside])[::-1][:10]
    for k, idx in enumerate(np.flatnonzero(inside)[order], 1):
        ax2.annotate(str(k), (xs[idx], ys[idx]), xytext=(7, 7), textcoords="offset points",
                     color="crimson", fontsize=8, weight="bold")
    ax2.set_xlim(x0 - 0.5, x1 - 0.5); ax2.set_ylim(y0 - 0.5, y1 - 0.5)
    ax2.set_title(f"Ausschnitt 1:1 ({zw}×{zh} px ab x={x0}, y={y0}): {inside.sum()} Quellen; "
                  f"Nummern = 10 hellste", fontsize=10)

    for ax in (ax1, ax2):
        ax.coords.grid(color="cyan", alpha=0.35, linestyle="--", linewidth=0.5)
        for c in ax.coords:
            c.set_axislabel("RA (J2000)" if c.coord_type == "longitude" else "Dec (J2000)", fontsize=9)
    fig.tight_layout()
    if outfile:
        fig.savefig(outfile, dpi=110, bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_comp_field(res, target, field_deg=(2.49, 1.67), pa_deg=None, margin_deg=0.05, outfile=None):
    """Himmelskarte um das Ziel: VSP-Sterne nach Rolle (Comp/Check/Reserve/verworfen) und Sensorfeld.

    ``res``: Ergebnis von :func:`varphot.vsp.select_comps_catalog`; ``pa_deg=None`` zeichnet zusätzlich
    den rotationssicheren Kreis, sonst das gedrehte Rechteck. Osten links (wie am Himmel).
    """
    from .astrometry import gnomonic
    x, y = gnomonic(np.asarray(res["ra"]), np.asarray(res["dec"]), target["ra"], target["dec"])
    L, S = max(field_deg), min(field_deg)
    fig, ax = plt.subplots(figsize=(10, 7.4))
    ax.set_aspect("equal")
    if pa_deg is None:
        ax.add_patch(plt.Circle((0, 0), 0.5 * S - margin_deg, fill=False, ec="red", lw=1.6,
                                label="rotationssicherer Kreis"))
        ax.add_patch(plt.Rectangle((-L / 2, -S / 2), L, S, fill=False, ec="red", lw=0.8, ls=":",
                                   label=f"Sensor {L:.2f}°×{S:.2f}° (PA 0°)"))
    else:
        a = np.radians(pa_deg)
        cx = np.array([-1, 1, 1, -1, -1]) * (L / 2 - margin_deg)
        cy = np.array([-1, -1, 1, 1, -1]) * (S / 2 - margin_deg)
        xi = cx * np.cos(a) - cy * np.sin(a); eta = cx * np.sin(a) + cy * np.cos(a)
        ax.plot(-xi, eta, "r-", lw=1.6, label=f"Sensorfeld (PA {pa_deg:g}°, Rand {margin_deg}°)")
    style = {"comp": ("o", "green", "Comp"), "check": ("D", "darkorange", "Check"),
             "reserve": ("o", "tab:blue", "Reserve"), "verworfen": ("x", "0.55", "verworfen")}
    src_all = np.asarray(res["source"]).astype(str) if "source" in res.colnames else np.array(["VSP"] * len(res))
    for role, (mk0, col, lab) in style.items():
        for src, mk in (("VSP", mk0), ("Gaia", "s" if mk0 != "x" else "+")):
            m = (np.asarray(res["role"]).astype(str) == role) & (src_all == src)
            if not m.any():
                continue
            kw = dict(c=col) if mk in ("x", "+") else dict(facecolors="none", edgecolors=col)
            ax.scatter(x[m], y[m], marker=mk, s=70 if role != "verworfen" else 36, linewidths=1.6,
                       label=f"{lab} {'(Gaia-V)' if src == 'Gaia' else ''} ({m.sum()})".replace("  ", " "), zorder=3, **kw)
            for xx, yy, r in zip(x[m], y[m], res[m]):
                if np.isfinite(xx) and abs(xx) < 1.9 and abs(yy) < 1.9:
                    ax.annotate(f"{r['label']}" + (f"  V={r['V']:.1f}" if role != "verworfen" else ""), (xx, yy),
                                xytext=(6, 5), textcoords="offset points",
                                fontsize=7.5 if role != "verworfen" else 6.5, color=col)
    ax.plot(0, 0, "*", ms=16, c="gold", mec="k", zorder=4, label=target.get("name", "Ziel"))
    ax.set_xlim(1.9, -1.9); ax.set_ylim(-1.9, 1.9)
    ax.set_xlabel("RA-Offset vom Ziel [°] (Osten links)"); ax.set_ylabel("Dec-Offset vom Ziel [°]")
    ax.set_title(f"Comp-Auswahl um {target.get('name', 'Ziel')}: AAVSO-VSP + Gaia-Prüfung")
    ax.grid(alpha=0.25); ax.legend(loc="lower left", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    if outfile:
        fig.savefig(outfile, dpi=110, bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_wcs_check(chk, shape, bins=(8, 6), outfile=None):
    """Drei Felder zur Gaia-Gegenprüfung der WCS: Residuen-Vektorkarte (je Zelle Median), Streudiagramm
    der Residuen (Kreis = 1 Pixel) und Betrag über G. ``chk`` ist ein :class:`varphot.WCSCheck`."""
    ny, nx = shape[-2:]
    bx, by = bins
    scale = chk.pixel_scale_arcsec
    fig, axs = plt.subplots(1, 3, figsize=(17, 5.4), gridspec_kw=dict(width_ratios=[1.35, 1, 1]))
    ax = axs[0]
    X, Y, U, W = [], [], [], []
    for i in range(bx):
        for j in range(by):
            m = (chk.x >= i * nx / bx) & (chk.x < (i + 1) * nx / bx) & (chk.y >= j * ny / by) & (chk.y < (j + 1) * ny / by)
            if m.sum() >= 5:
                X.append((i + .5) * nx / bx); Y.append((j + .5) * ny / by)
                U.append(np.median(chk.dra[m])); W.append(np.median(chk.ddec[m]))
    q = ax.quiver(X, Y, U, W, angles="xy", scale_units="xy", scale=1 / (0.35 * nx / bx), width=0.004, color="k")
    ax.quiverkey(q, 0.9, 0.05, 1.0, "1″", labelpos="E", coordinates="axes")
    ax.set_xlim(0, nx); ax.set_ylim(0, ny); ax.set_aspect("equal")
    ax.set_title("mediane Residuen je Zelle (erkannt − Gaia): E → rechts, N → oben", fontsize=10)
    ax.set_xlabel("x [px]"); ax.set_ylabel("y [px]")

    ax = axs[1]
    ax.scatter(chk.dra, chk.ddec, s=3, alpha=0.4, c="tab:blue")
    ax.add_patch(plt.Circle((0, 0), scale, fill=False, ec="red", lw=1.2, label=f"1 px = {scale:.2f}″"))
    ax.plot(chk.median_dra_arcsec, chk.median_ddec_arcsec, "r+", ms=14, mew=2, label="Median")
    lim = 3 * max(chk.rms_arcsec, 0.2) + abs(chk.median_dra_arcsec) + abs(chk.median_ddec_arcsec)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    ax.set_xlabel("ΔRA·cosδ [″]"); ax.set_ylabel("ΔDec [″]")
    ax.set_title(f"{chk.n_match} Treffer: Versatz {chk.offset_arcsec:.2f}″, Streuung {chk.rms_arcsec:.2f}″, "
                 f"schlechteste Zelle {chk.worst_cell_arcsec:.2f}″", fontsize=10)

    ax = axs[2]
    ax.scatter(chk.G, np.hypot(chk.dra, chk.ddec), s=3, alpha=0.4, c="tab:blue")
    ax.axhline(scale, c="red", lw=1, ls="--", label="1 px")
    ax.set_xlabel("Gaia G [mag]"); ax.set_ylabel("|Residuum| [″]"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
    ax.set_title("Residuum über Helligkeit (helle Sterne: Sättigung/Zentroid)", fontsize=10)
    fig.suptitle(chk.verdict, fontsize=11, color="darkgreen" if chk.verdict == "OK" else "darkred")
    fig.tight_layout()
    if outfile:
        fig.savefig(outfile, dpi=110, bbox_inches="tight")
        plt.close(fig)
    return fig


def plot_lightcurve(lc, period, outfile="lightcurve.png"):
    """Vier-Panel-Lichtkurve: Rohkurve, Check, Phase, Periodogramm."""
    from astropy.timeseries import LombScargle
    freq, power = LombScargle(lc[:, 0], lc[:, 1]).autopower(
        minimum_frequency=1 / 20, maximum_frequency=2, samples_per_peak=50)
    pbest = 1 / freq[np.argmax(power)]

    fig, axs = plt.subplots(2, 2, figsize=(12, 7.5))
    ax = axs[0, 0]
    ax.plot(lc[:, 0], lc[:, 1], "ko", ms=3)
    ax.invert_yaxis(); ax.set_xlabel("t [d]"); ax.set_ylabel("V (diff.) [mag]")
    ax.set_title("Lichtkurve Ziel")

    ax = axs[0, 1]
    ax.plot(lc[:, 0], lc[:, 2] - lc[:, 2].mean(), "o", c="darkorange", ms=3)
    ax.axhline(0, c="k", lw=0.5); ax.set_ylim(0.1, -0.1)
    ax.set_xlabel("t [d]"); ax.set_ylabel("Check − Mittel [mag]")
    ax.set_title(f"Check-Stern (Streuung {lc[:, 2].std():.4f} mag)")

    ax = axs[1, 0]
    ph = (lc[:, 0] / pbest) % 1
    ax.plot(np.r_[ph, ph + 1], np.r_[lc[:, 1], lc[:, 1]], "ko", ms=3)
    ax.invert_yaxis(); ax.set_xlabel(f"Phase (P = {pbest:.3f} d)"); ax.set_ylabel("V [mag]")
    ax.set_title("Phasenkurve")

    ax = axs[1, 1]
    ax.plot(1 / freq, power, "k-"); ax.axvline(pbest, c="r", ls=":")
    ax.set_xlabel("Periode [d]"); ax.set_ylabel("Lomb-Scargle-Leistung")
    ax.set_title("Periodogramm")

    fig.tight_layout()
    fig.savefig(outfile, dpi=110)
    plt.close(fig)
    return pbest
