"""Zentrale Konfiguration; als Ausgangspunkt fuer projektspezifisches YAML gedacht."""

CFG = {
    # Kamera / Aufbau
    "sat_adu": 50000,          # Sättigungsgrenze (ADU); Linearität vorab prüfen
    "nx": 1600,
    "ny": 1100,
    "scale_arcsec": 1.44,      # Bogensekunden/Pixel (Apo 80/540 + QHY268M)
    # Bildqualitaet (qc_frames; Startwerte)
    "snr_min": 10.0,           # jeder Comp mindestens S/N 10, sonst NO_SIGNAL
    "transp_min": 0.6,         # Comp-Fluss relativ zum Laufmedian, sonst LOW_TRANSPARENCY (Wolken)
    "fwhm_max_arcsec": 4.0,    # schlechteres Seeing -> BAD_SEEING
    # Detektion
    "detect_fwhm": 4.5,
    "detect_nsigma": 8.0,
    # Crossmatch
    "xmatch_tol_arcsec": 3.0,
    # Comp-Auswahl
    "comp_dmag": 2.0,
    "comp_bv_tol": 0.35,
    "comp_edge_px": 80,
    "comp_r_iso_px": 25,
    "comp_n": 8,
    "comp_peak_max": 40000,
    "comp_halo_px": 60,        # Abstand zum Ziel, innerhalb dessen ein Stern im Halo des defokussierten Ziels liegt
    "comp_dv_max": 6.0,        # groesste erlaubte Helligkeitsdifferenz Comp - Ziel [mag] (Bildumfang/Linearitaet)
    # Apertur Comps/Check
    "ap_r": 10,
    "ap_r_in": 18,
    "ap_r_out": 26,
    # Apertur Ziel (defokussiert)
    "target_ap_r": 45,
    "target_ap_r_in": 55,
    "target_ap_r_out": 70,
    # Hintergrundring Ziel: mindestens target_ap_r + 5 px Abstand
    # PSF-Photometrie (fokussierte Felder; nicht für defokussiertes Ziel)
    "psf_stamp_size":    25,     # Briefmarkengröße in Pixeln (ungerade bevorzugt)
    "psf_oversampling":   2,     # EPSF-Überabtastung
    "psf_maxiters":       5,     # EPSFBuilder-Iterationen
    "psf_peak_lo":      500,     # untere Flussgrenze für PSF-Referenzsterne (ADU)
}
