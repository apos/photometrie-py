"""Quellendetektion auf einem einzelnen Frame."""
from astropy.stats import sigma_clipped_stats
from photutils.detection import DAOStarFinder


def detect(img, fwhm=4.5, nsigma=8.0):
    """Gibt (sources, median, std) zurück; sources ist None wenn nichts gefunden."""
    _, med, std = sigma_clipped_stats(img, sigma=3.0)
    finder = DAOStarFinder(fwhm=fwhm, threshold=nsigma * std)
    src = finder(img - med)
    return src, med, std
