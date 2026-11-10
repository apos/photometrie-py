"""varphot — differentielle Photometrie für Veränderliche."""
from .config import CFG
from .detect import detect
from .catalog import crossmatch, select_comps
from .photometry import aperture_flux, diff_mag
from .plot import chart_map, plot_lightcurve

__all__ = ["CFG", "detect", "crossmatch", "select_comps", "aperture_flux", "diff_mag",
           "chart_map", "plot_lightcurve"]
