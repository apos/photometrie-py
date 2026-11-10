# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unveröffentlicht]

### Neu (P0-3: erster echter Datensatz, LCO δ Cep, Filter V)
- **Stapelphotometrie** (`varphot/batch.py`): `read_frame` (auch `.fits.fz`), `measure_frame`, `run_batch` (parallel),
  `qc_frames` (Bildflags `NO_WCS`, `NO_SIGNAL`, `LOW_TRANSPARENCY`, `BAD_SEEING`), `ensemble_mag` (robust, gewichtet),
  `light_curve` (BJD_TDB, Fehler, Check-Stern, Sättigungsmarkierung). Ersetzt die Platzhalter in NB04/NB05.
- **Zeit** (`varphot/timeutil.py`): Belichtungsmitte, `bjd_tdb()` mit Standort, Luftmasse, Standort aus LCO-Header.
- **Fehlerbudget** (P1): CCD-Gleichung (Photonen, Himmel, Ausleserauschen; Gain/RON aus dem Header) plus
  Szintillation nach Young (`scintillation_mag`).
- **`field_from_wcs()`**: Sensorfeld und Winkel direkt aus dem WCS eines Bildes; NB03 nimmt über `VARPHOT_FRAME` ein
  Referenzbild, `VARPHOT_RULES` überschreibt Auswahlregeln (Kleinfeld-Optik).
- **Ergebnis am LCO-Satz** (156 Bilder des Teleskops `0m4-11`, 98 brauchbar): erkennbare Cepheiden-Lichtkurve
  (schneller Anstieg, langsamer Abfall), Lomb-Scargle 5,30 d (Literatur 5,366 d; Zeitbasis 56 d), Amplitude ~1,1 mag
  (Literatur ~0,9). Streuung um die Kurve ~0,1 mag: das Ziel ist in 1,3 s fast gesättigt (V≈4 an einer 0,4-m-Optik).

### Behoben
- **Aperturphotometrie schnitt helle Sternkerne ab**: `photutils.ApertureStats` wendet standardmäßig Sigma-Clipping auch
  auf die Aperturensumme an. Der Fluss heller Sterne war dadurch zu klein (Test: 205 statt 251). `aperture_flux()` und
  die neue Stapelphotometrie rechnen jetzt ohne Clipping; Regressionstest `tests/test_photometry.py`.

### Neu
- **Beobachter, Standort, Kamera** (`varphot/observer.py`, NB01 Abschnitt 0): Standort-Picker (Breite, Länge Ost +, Höhe;
  Testdaten-Standorte LCO McDonald und Whipple eingebaut), AAVSO-Beobachtercode und Kameradaten (Gain, Ausleserauschen,
  Dunkelstrom, Linearität = AAVSO „Detector Details"). Gespeichert in `PHOTOMETRIE_PY_DATA/observer.json` neben dem Repo (Nextcloud;
  Fallback `~/.config/varphot/`, Überschreiben mit `VARPHOT_CONFIG`; Rechte 0600, **nicht** im öffentlichen Repo), in jedem Notebook vorbelegt; `session_config.json` enthält sie für NB02+.
  Voraussetzung für BJD_TDB und Luftmasse (P1). 9 Tests.

---

## [0.3.0] — 2026-11-10

### Neu
- **Echte Testdaten gefunden**: EXOTIC-Beispielsatz HAT-P-32 b (142 FITS, MicroObservatory/Whipple, 2017-12-20,
  Clear, 60 s, 5,2″/px, ca. 89 MB; <https://github.com/rzellem/EXOTIC_sampledata>). ASTAP löst Bild 1 in 0,2 s
  (Header ohne WCS, aber mit Standort LATITUDE/LONGITUD). Liegt ausserhalb des Repos; Pipeline-Lauf folgt (P0-3).
- **Plate Solving mit echten Bildern** (`varphot/astrometry.py`): `solve_image()` ruft ASTAP auf und liest die
  `<bild>.wcs`-Datei (ASTAP schreibt mit `-wcs` NICHT in den FITS-Header); Original bleibt unverändert, Fallback auf
  Header-WCS, sonst `wcs=None`. NB02 mit echtem Bild über `VARPHOT_REF=/pfad/bild.fit`.
- **Sternerkennung für Nebelfelder**: `detect(..., background="2d")` (Background2D + Filter gegen lokales Rauschen).
- **Sternkarte für echte Bilder**: `plot_detections()` (Übersicht + 1:1-Ausschnitt, RA/Dec-Gitter); NB02 Schritt 6 mit
  Quellenliste `<bild>.sources.ecsv` und `skip_if_fresh`-Cache (`varphot/cache.py`).
- **Comp-Auswahl aus AAVSO-VSP + Gaia DR3** (`varphot/vsp.py`, Roadmap P0-2): SIMBAD-Auflösung, VSP-Abruf mit Cache,
  Regeln (Feld, Helligkeit, Fehler, Farbe, NSV/„nur visuell"), Gaia-Prüfung (Nachbarn, Variabilität, RUWE, V-Konsistenz),
  Begründung für jeden verworfenen Stern; `plot_comp_field()`; NB03 komplett neu.
- **Gaia-Feldsterne als Ensemble-Ergänzung** (`fill_with_gaia()`, NB03 Schritt 3b): Delta Cep 4 → 8 Comps + 1 Check bei
  rotationssicherem Feld; V aus G und BP−RP (abgeleitet, Fehler 0,05 mag), Nachbarprüfung per ESA-TAP.
- **WCS-Gegenprüfung gegen Gaia DR3** (`varphot/wcscheck.py`, NB02 Schritt 7): `check_wcs()` kreuzt erkannte Sterne mit
  Gaia (Eigenbewegung auf die Aufnahmeepoche), weist Versatz, Streuung, Wiederfindung und schlechteste Bildzelle aus;
  `plot_wcs_check()`. M16-Testbild: 2636 Treffer, Versatz 0,08″, Streuung 0,27″ (0,32 px), schlechteste Zelle 0,60″ → OK.
- **Gaia-TAP mit Ausfall-Umschaltung**: ESA-TAP, bei Timeout/503 der ARI-Spiegel (identische Daten, geprüft).
- `pyproject.toml` (`pip install -e .`), Tests (`tests/`, pytest).
- **nbstripout** als Git-Filter (`.gitattributes`): Zell-Outputs und Ausführungszähler landen nie im Repo; je Klon einmalig
  `nbstripout --install --attributes .gitattributes`. Notebooks 01/03/04 einmalig normalisiert.
- **PSF-Photometrie (in Arbeit)**: `build_psf()`, `psf_flux()` — bekannter Fehler, siehe unten.

### Behoben
- Sternbildkarte (NB02 Schritt 5): Linien werden als Großkreisbögen projiziert und am Kartenrand abgeschnitten statt
  verworfen, sobald ein Endstern weit außerhalb liegt; ein Sternbild zählt, sobald eine Linie das Fenster berührt
  (`great_circle_xy()`, `polyline_in_window()`). Gemessen: +1 bis +3 Linien je Zielfeld (M16, δ Cep, Polarnähe, Orion).
- `solve_image()` nutzte ASTAPs Standard von 500 Sternen: am 2,1°-Feld blieb ein Rotationsfehler von ~1,2″ am Rand
  (Gaia-Prüfung). Jetzt `max_stars=5000` (→ 0,85″ Trend, schlechteste Zelle 0,60″).
- Sternbildkarte (NB02 Schritt 5) zeigte bei Zielen auf der Gegenseite des Himmels gespiegelte Sternbilder
  (Orion im Feld von M16): `gnomonic()` liefert für die abgewandte Halbkugel NaN.
- NB02 behauptete, ASTAP schreibe die WCS in den FITS-Header (stimmt nicht, s. o.).
- Zielposition in NB02 kam aus `CRVAL` (WCS-Referenzpunkt), jetzt aus RA/DEC der Montierung im Header.

### Dokumentation
- README: Kamera QHY268M ist APS-C (6252×4176 px), nicht Vollformat.

### Bekannte Fehler
- `psf_flux()`: PSF-Differenzhelligkeit im synthetischen Demo um ~1,1 mag zu schwach, weil das Ziel defokussiert
  (FWHM 22 px) und die Comps fokussiert (4,5 px) sind; PSF-Pfad daher nur für fokussierte Felder gedacht.
- NB03 kennt noch keine Bild-Zuordnung (Crossmatch im Bild folgt mit P0-3).

---

## [0.2.0] — 2026-11-10

### Neu
- **Generische Sternkarte** (NB02 Schritt 5): alle 88 IAU-Sternbilder unterstützt
  statt hardcodierter Cepheus/Cygnus/Lacerta-Visualisierung
- **`data/const_topology.json`**: gebündelte Sternbild-Topologie (88 Konstellationen,
  601 Sternbezeichnungen nach Bayer/Flamsteed), kein Netz nötig
- **`data/constellation_lines.json`**: generierter Positionscache aus SIMBAD
  (600/601 Sterne aufgelöst, 88/88 Sternbilder mit mind. 1 Linie)
- **`tools/make_const_data.py`**: einmaliger SIMBAD-Datenaufbau via Harvard-Mirror
  (direkter HTTP/ADQL-POST, kein astroquery TAP); vollständiges Greek-Letter-Mapping
  (`xi`→`ksi`, `the`→`tet`, `mu`→`mu.`, `nu`→`nu.`, `pi`→`pi.`) + Special-Cases
  für Flamsteed-Nummern, Doppelsterne (Albireo-Muster), Variablenstern-Prefix (`V*`)
- **NB02 Schritt 4**: HTML-Tabelle mit Sensorzentrum/Zielstern, WCSAxes-Gitternetz
- **Markdown-Beschreibungen** vor jeder Code-Zelle in allen 6 Notebooks
- **NB01 Preflight-Check**: prüft alle benötigten Pakete und Binaries (ASTAP, astroalign)
- **Code-Zellen zugeklappt** (`source_hidden: true`) in allen Notebooks für bessere Übersicht
- **`docs/images/`**: Demo-Bilder (Sternkarte, Lichtkurve) für README
- **README.md**: vollständig neu — Pipeline-Übersicht, Zielsterne-Tabelle, Paketstruktur,
  PSF-Erklärung, `varphot_demo.py`-Doku, Hardware-Referenz

### Geändert
- ASTAP-Pfad korrigiert: `/Applications/astap` → `/Applications/ASTAP.app/Contents/MacOS/astap`
- ipykernel: `.venv` als Jupyter-Kernel registriert
- NB02 Sternbild-Zelle: gnomische Projektion, automatischer SIMBAD-Setup beim ersten Start

### Getestet
- Synthetische Pipeline (macOS M4, Python 3.13.18): 46 Quellen, 8 Comps,
  Check-Streuung 0,0101 mag, Lomb-Scargle-Periode 5,384 d (Soll 5,366 d)
- `make_const_data.py`: Harvard-Mirror SIMBAD, 600/601 Sterne, 88/88 Sternbilder

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

[Unveröffentlicht]: https://github.com/apos/photometrie-py/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/apos/photometrie-py/releases/tag/v0.3.0
[0.2.0]: https://github.com/apos/photometrie-py/releases/tag/v0.2.0
[0.1.0]: https://github.com/apos/photometrie-py/releases/tag/v0.1.0
