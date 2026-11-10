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
                    stars_from_field_config, scintillation_mag, read_measurements)
from .periodfit import harmonic_fit
from .camera import (bayer_planes, center_roi, pair_stats, gain_from_pair, ptc_fit, read_noise_e, full_well_e,
                     linearity_curve, dark_current_e_per_s, detect_saturation, exposure_from_header, iso_from_header, histogram_gaps, compression_verdict)
from .plan import (field_of_view_deg, ObservingPlan, METHODS, green_plane, star_metrics, fwhm_summary, recommend_exposure, aperture_from_fwhm,
                   night_altitudes, save_plan, load_plan, latest_plan)
from .transform import (TransformSolution, linfit, catalog_from_vsp_table, instrumental_table, fit_extinction, fit_transform,
                        transform_target, loo_validation, solution_path, transformed_light_curve, transformed_with_check)
from .aavso import Observation, build_extended, validate_extended, notes_string, observations_from_lightcurve, Finding, check_plausibility
from .maturity import maturity, maturity_warnings
from .aireview import (Backend, ReviewResult, detect_backends, choose_backend, ai_review, load_ai_config, save_ai_config, is_private_host)
from .camera_presets import PRESETS, CameraPreset, VendorValues, get_preset, preset_choices

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
    "stars_from_field_config", "scintillation_mag", "read_measurements", "harmonic_fit",
    "bayer_planes", "center_roi", "pair_stats", "gain_from_pair", "ptc_fit", "read_noise_e", "full_well_e",
    "linearity_curve", "dark_current_e_per_s", "detect_saturation", "exposure_from_header", "iso_from_header", "histogram_gaps", "compression_verdict",
    "ObservingPlan", "METHODS", "green_plane", "star_metrics", "fwhm_summary", "recommend_exposure", "aperture_from_fwhm",
    "night_altitudes", "save_plan", "load_plan", "latest_plan",
    "TransformSolution", "linfit", "catalog_from_vsp_table", "instrumental_table", "fit_extinction", "fit_transform",
    "transform_target", "loo_validation", "solution_path", "transformed_light_curve", "transformed_with_check",
    "Observation", "build_extended", "validate_extended", "notes_string", "observations_from_lightcurve",
    "Finding", "check_plausibility", "Backend", "ReviewResult", "detect_backends", "choose_backend", "ai_review", "load_ai_config", "save_ai_config", "is_private_host", "maturity", "maturity_warnings", "field_of_view_deg",
    "PRESETS", "CameraPreset", "VendorValues", "get_preset", "preset_choices",
]
