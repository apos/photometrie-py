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
