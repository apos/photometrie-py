# Demo-Daten — synthetischer Siril-Workspace

Erzeugt mit `make_demo.py` (`.venv/bin/python demo/make_demo.py`).

## Zielstern
**Delta Cephei** (simuliert) — Cepheid, V ≈ 3.5–4.4 mag, Periode 5.366 d  
Koordinaten: RA 22h 29m 10s, Dec +58° 24′ 55″

## Workspace-Struktur

```
demo/siril_workspace/
  lights/        20 Roh-Light-Frames  (120s, V-Filter, QHY268M sim.)
  darks/          5 Roh-Dark-Frames   (120s)
  flats/          5 Roh-Flat-Frames   (5s, V-Filter, Vignettierung)
  biases/         5 Roh-Bias-Frames
  process/       20 kalibrierte Frames (pp_light_*.fits, bereit für NB 02)
```

## Notebooks verwenden

**Notebook 01** — Workspace wählen:
```
/…/PHOTOMETRIE_PY/demo/siril_workspace
```
Erkennt `lights/`, `darks/`, `flats/`, `biases/`, `process/` automatisch.

**Notebook 02** — liest `session_config.json` automatisch;  
DIR_CAL zeigt auf `process/` mit 20 vorkalibrierten Frames.

## Technische Details
- Bildgröße: 1600 × 1100 px
- Skala: 1.44 arcsec/px (Apo 80/540 + QHY268M, kein Binning)
- Gain: 0 dB, Read Noise: 3.5 e⁻, Dark: 0.02 e⁻/px/s, T = −15 °C
- 8 Vergleichssterne (C01–C08, V 5.1–8.1 mag), 4 schwache Hintergrundsterne
- Lichtkurve Delta Cep: asymmetrisch, schneller Anstieg (Phase 0–0.3)
- Airmass: zufällig 1.1–1.8 je Frame, einfache Extinktionskorrektur
- WCS im FITS-Header (TAN-Projektion)
