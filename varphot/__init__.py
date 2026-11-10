"""varphot — differentielle Photometrie für Veränderliche."""
__version__ = "0.2.0"
from .config import CFG
from .detect import detect
from .catalog import crossmatch, select_comps
from .photometry import aperture_flux, build_psf, psf_flux, diff_mag
from .plot import chart_map, plot_comp_field, plot_detections, plot_lightcurve
from .cache import skip_if_fresh
from .astrometry import solve_image, SolveResult, gnomonic

__all__ = [
    "CFG",
    "detect", "crossmatch", "select_comps",
    "aperture_flux", "build_psf", "psf_flux", "diff_mag",
    "chart_map", "plot_comp_field", "plot_detections", "plot_lightcurve",
    "skip_if_fresh",
    "solve_image", "SolveResult", "gnomonic",
]
