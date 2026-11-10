# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] — 2026-11-10

### Neu
- **`varphot/` Paket** mit 6 Modulen:
  - `config.py` — zentrales `CFG`-Dict (Ausgangspunkt für YAML-Config je Ziel)
  - `detect.py` — Quellendetektion via `DAOStarFinder`
  - `catalog.py` — Katalog-Crossmatch und Comp/Check-Auswahl mit QC-Flags
  - `photometry.py` — Aperturphotometrie und Ensemble-Differenzmagnitude
  - `plot.py` — Sternkarte und 4-Panel-Lichtkurve
  - `synthetic.py` — synthetische Testdaten (nur Demo/Tests)
- **`varphot_demo.py`** — End-to-End-Test mit synthetischen Daten; nutzt das Paket,
  endet mit `assert`-Checks (≥ 5 Comps, Check-Streuung < 0,05 mag, Periode ± 0,5 d)
- **`KONZEPT.md`** — arc42-Konzeptdokumentation mit Mermaid-Diagrammen, ADRs,
  API-Tabelle und priorisierter Roadmap (P0–P2)
- **`notebooks/01–06`** — Jupyter-Notebook-Gerüst für die vollständige Pipeline:
  Kalibrierung → Plate Solve → Feld & Comps → Photometrie-Stapel → Lichtkurve → Bericht
- **`requirements.txt`** — Python 3.13, astropy 8.0.2, photutils 3.1.1, astroalign,
  astroquery, scipy, matplotlib, jupyter, ipykernel

### Getestet
- Synthetische Pipeline (macOS M4, Python 3.13.18): 46 Quellen, 8 Comps,
  Check-Streuung 0,0101 mag, Lomb-Scargle-Periode 5,384 d (Soll 5,366 d)

### Noch nicht getestet
- ASTAP-CLI, Katalogabfragen (Gaia/VSP), Registrierung mit echten Bildern,
  AAVSO-Export-Format (siehe KONZEPT.md §8 Test-Strategie)

[0.1.0]: https://github.com/apos/photometrie-py/releases/tag/v0.1.0
