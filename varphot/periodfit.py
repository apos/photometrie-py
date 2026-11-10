"""Harmonische Anpassung periodischer Lichtkurven (Fourier-Reihe, Periode per Gittersuche).

Ergaenzt Lomb-Scargle: liefert neben der Periode das Residuum um das Modell und die Modellamplitude — brauchbar als
Guetemass, um Messvarianten (Apertur, Kernmaske, Comp-Auswahl) zu vergleichen.
"""
from __future__ import annotations

import numpy as np


def _design(t, period, nharm, t0):
    ph = 2 * np.pi * (np.asarray(t, float) - t0) / period
    return np.column_stack([np.ones_like(ph)] + [f(k * ph) for k in range(1, nharm + 1) for f in (np.sin, np.cos)])


def harmonic_fit(t, y, p_lo: float, p_hi: float, nharm: int = 3, n_period: int = 400) -> dict:
    """Fourier-Reihe mit ``nharm`` Harmonischen; Periode im Bereich [p_lo, p_hi] mit kleinstem Residuum-RMS.

    Rueckgabe: ``period``, ``rms`` (Residuum), ``amplitude`` (Spitze-Spitze des Modells), ``model`` (Werte bei ``t``),
    ``residual``. Mit zu wenigen Punkten (< 2*nharm + 3) wird ein ``ValueError`` ausgeloest.
    """
    t, y = np.asarray(t, float), np.asarray(y, float)
    if len(t) < 2 * nharm + 3:
        raise ValueError(f"zu wenige Punkte ({len(t)}) fuer {nharm} Harmonische")
    t0 = t.min()
    best = None
    for P in np.linspace(p_lo, p_hi, n_period):
        A = _design(t, P, nharm, t0)
        c, *_ = np.linalg.lstsq(A, y, rcond=None)
        rms = float(np.std(y - A @ c))
        if best is None or rms < best["rms"]:
            tt = np.linspace(0, P, 400) + t0
            best = dict(period=float(P), rms=rms, model=A @ c, residual=y - A @ c,
                        amplitude=float(np.ptp(_design(tt, P, nharm, t0) @ c)))
    return best
