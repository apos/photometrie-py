"""Harmonische Anpassung periodischer Lichtkurven (Fourier-Reihe, Periode per Gittersuche).

Autor: Axel Pospischil. Ergaenzt Lomb-Scargle: liefert neben der Periode das Residuum um das Modell und die
Modellamplitude — brauchbar als Guetemass, um Messvarianten (Apertur, Kernmaske, Comp-Auswahl) zu vergleichen.
"""
from __future__ import annotations

import numpy as np


def _design(t, period, nharm, t0):
    ph = 2 * np.pi * (np.asarray(t, float) - t0) / period
    return np.column_stack([np.ones_like(ph)] + [f(k * ph) for k in range(1, nharm + 1) for f in (np.sin, np.cos)])


def harmonic_fit(t, y, p_lo: float, p_hi: float, nharm: int = 3, n_period: int = 400) -> dict:
    """Fourier-Reihe mit ``nharm`` Harmonischen; Periode im Bereich [p_lo, p_hi] mit kleinstem Residuum-RMS.

    Warum: Lomb-Scargle nennt die Periode, aber kein Guetemass fuer die *Form* der Kurve. Das Residuum um eine glatte Kurve
    vergleicht Messvarianten direkt (am LCO-Satz: 0,129 -> 0,068 mag durch die Kernkorrektur), die Modellamplitude ist
    unabhaengig von einzelnen Ausreissern.

    Wie: Fuer jede Testperiode ``P`` wird ``y = c0 + sum_k [a_k sin(2 pi k t/P) + b_k cos(2 pi k t/P)]`` linear (kleinste
    Quadrate) angepasst; gewaehlt wird die Periode mit kleinstem Residuum-RMS. Amplitude = Spitze-Spitze des Modells.

    Rueckgabe: ``period``, ``rms`` (Residuum), ``amplitude``, ``model`` (Werte bei ``t``), ``residual``. Zu wenige Punkte
    (< 2*nharm + 3) -> ``ValueError``.

    Grenzen: Zeitbasis ``T`` begrenzt die Periodenaufloesung auf etwa ``P^2/T`` (56 d, 5,4 d -> ~0,5 d). Das Residuum
    enthaelt Rauschen *und* echte Zyklus-zu-Zyklus-Aenderungen; die Gittersuche findet bei grosser Luecke Nebenmaxima.
    Wenige Harmonische glaetten die Amplitude (LCO delta Cep: 3 Harmonische 0,81 mag, Spannweite der Punkte 0,93 mag).

    Validierung: ``tests/test_periodfit.py`` (Periode 5,366 d +- 0,02 aus 90 verrauschten Punkten).

    Quellen (Zitate per Suche geprueft, Volltexte nicht gelesen): Standardverfahren (Fourier-Zerlegung von Lichtkurven);
    Zusammenhang mit Lomb-Scargle: Lomb, N. R. 1976, Ap&SS 39, 447, doi:10.1007/bf00648343; Scargle, J. D. 1982, ApJ 263, 835
    (zeigt die Aequivalenz von Periodogramm und Kleinste-Quadrate-Sinusanpassung); VanderPlas, J. T. 2018, ApJS 236, 16,
    doi:10.3847/1538-4365/aab766.
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
