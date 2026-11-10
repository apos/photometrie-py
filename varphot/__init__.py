"""varphot — differentielle Photometrie für Veränderliche."""
__version__ = "0.3.0"
from .config import CFG
from .detect import detect
from .catalog import crossmatch, select_comps
from .photometry import aperture_flux, build_psf, psf_flux, diff_mag
from .plot import chart_map, plot_comp_field, plot_detections, plot_wcs_check, plot_lightcurve
from .cache import skip_if_fresh
from .astrometry import solve_image, SolveResult, gnomonic, great_circle_xy, polyline_in_window, field_from_wcs
from .wcscheck import check_wcs, gaia_field, WCSCheck
from .observer import Observer, Site, Camera
from .timeutil import mid_exposure, bjd_tdb, airmass, site_from_header
from .batch import (read_frame, measure_frame, run_batch, qc_frames, ensemble_mag, light_curve,
                    stars_from_field_config, scintillation_mag)
from .periodfit import harmonic_fit
from .camera import (bayer_planes, center_roi, pair_stats, gain_from_pair, ptc_fit, read_noise_e, full_well_e,
                     linearity_curve, dark_current_e_per_s)

__all__ = [
    "CFG",
    "detect", "crossmatch", "select_comps",
    "aperture_flux", "build_psf", "psf_flux", "diff_mag",
    "chart_map", "plot_comp_field", "plot_detections", "plot_wcs_check", "plot_lightcurve",
    "skip_if_fresh",
    "solve_image", "SolveResult", "gnomonic", "great_circle_xy", "polyline_in_window", "check_wcs", "gaia_field", "WCSCheck",
    "Observer", "Site", "Camera",
    "mid_exposure", "bjd_tdb", "airmass", "site_from_header", "field_from_wcs",
    "read_frame", "measure_frame", "run_batch", "qc_frames", "ensemble_mag", "light_curve",
    "stars_from_field_config", "scintillation_mag", "harmonic_fit",
    "bayer_planes", "center_roi", "pair_stats", "gain_from_pair", "ptc_fit", "read_noise_e", "full_well_e",
    "linearity_curve", "dark_current_e_per_s",
]
