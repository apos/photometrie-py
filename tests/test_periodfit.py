import numpy as np
import pytest

from varphot.periodfit import harmonic_fit


def test_recovers_period_and_amplitude():
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 56, 90))
    P = 5.366
    y = 3.9 + 0.4 * np.sin(2 * np.pi * t / P) + 0.1 * np.sin(4 * np.pi * t / P + 1) + rng.normal(0, 0.02, len(t))
    f = harmonic_fit(t, y, 5.0, 5.8)
    assert f["period"] == pytest.approx(P, abs=0.02)
    assert f["rms"] < 0.04
    assert f["amplitude"] == pytest.approx(0.85, abs=0.12)


def test_too_few_points():
    with pytest.raises(ValueError):
        harmonic_fit([0, 1, 2], [1, 2, 3], 1, 2)
