# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/),
Versionierung nach [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unveröffentlicht]

## [0.6.0] — 2026-11-11

**Notebook-Umbau und fachliche Prüfung** (Konzept §12.2–§12.4, §13): vier Phasen-Notebooks (00 Planung, 01 Vorbereitung, 02 Messung, 03 Bericht) mit einer gemeinsamen Sitzung; Eigendatenweg lauffähig.

### Neu
- **Sitzung** (`varphot/session.py`): `session.json` im Siril-Arbeitsordner trägt Ziel, Methode, Ordner, Plan, Referenzbild/WCS, Feldkonfiguration von Notebook zu Notebook; `Session.open()` erhält Ergebnisse bei erneutem NB00 und leert sie bei Wechsel von Ziel/Methode.
- **Notebooks neu strukturiert:** `01_vorbereitung` (Kalibrierung, Plate-Solve, Comps; ersetzt 01–03), `02_messung` (Photometrie, Lichtkurve, Periode; ersetzt 04–05), `03_bericht` (ersetzt 06); je ein Formular am Anfang, danach „Ab hier automatisch“; Logik in getesteten Funktionen (`varphot/workflow.py`). NB00 legt die Sitzung an, erfasst Beobachter/Standort (aus der alten NB01), nimmt Probebilder aus `probe/` (RAW per Siril nach FITS) und ein scharfes Referenzbild aus `probe/scharf/`; Modus „LCO-Testdaten“ zum Ausprobieren mit echten Bildern.
- **Siril-Skripte aus der Sitzung** (`varphot/siril.py`): Kalibrierung (Bias/Dark/Flat → Master → `calibrate`, Farbkameras im CFA-Bereich) und RAW→FITS; Ausführung mit `siril-cli`, sonst liegt das Skript in `scripts/`. **Nicht gegen Siril getestet.**
- **WCS je Bild per Registrierung** (`varphot/registration.py`, `run_batch(reference=, wcs_mode=)`): ein scharfes Referenzbild wird gelöst, jedes Bild der Reihe per `astroalign` darauf registriert (LCO δ Cep: 104 von 104, Median 0,5″ gegen den Kopf). Ohne das war der Eigendatenweg nicht lauffähig.
- **Aperturradius aus den Daten** (`varphot/aperture.py`, Wachstumskurve nach Stetson 1990 und S/N-Optimum nach Howell 1989): NB00 Schritt 4; am LCO-Satz 9 px (Amplitude 0,79 mag, Periode 5,366 d) statt 5 px (0,64 mag) bzw. der 1,5-×-FWHM-Regel (3 px).
- **`defocus_solve_ladder`**, `solve_array`, Defokus-Rechnungen, `readiness` (aus 0.5.0) sind in NB00 eingebunden.

### Behoben (fachliche Prüfung, KONZEPT §13)
- **`qc_frames`:** ein einziger verrauschter Comp verwarf das ganze Bild (34 statt 93 von 105 brauchbar); jetzt zählt die Zahl brauchbarer Comps (`min_comps`), `light_curve` übergeht zu schwache Comps im Bild. Regressionstest.
- **ASTAP löscht komprimierte Eingaben** (`.fits.fz`): `solve_image` löst sie über eine Kopie. Regressionstest mit Attrappe.
- **Registrierung auf feste Muster:** Hotpixel zogen die Zuordnung auf „keine Verschiebung“; 3×3-Medianfilter, Sternfinder ohne Formfilter (Donuts), Gegenprobe an den hellsten Referenzsternen. Regressionstest.
- **Comp-Regeln für kleine Felder:** Nachbarradius aus Apertur × Pixelskala (die 36″ galten nur für 1,44″/px), Farb-/Randregeln stufenweise gelockert (jede Stufe gemeldet), Check-Stern notfalls ein mittelheller Comp, Sequenznamen mit ausgeschriebenen griechischen Buchstaben.
- **Fremde Archivdaten unter eigenem Code:** NB03 erkennt LCO-Köpfe (`ORIGIN`, `PROPID`) und erzwingt `TST01` und die Kennzeichnung (zuvor entstand beim Test eine Datei mit echtem Code und ohne Warnung; gelöscht).
- Aperturplanung: Median über die Probebilder (nicht das unschärfste: 15 px ergaben Residuum 0,107 mag und 56 Bilder ohne Signal), bei gesättigtem Ziel 98 % Fluss.

### Geändert
- Notebooks 01–06 entfallen (siehe Zuordnung in KONZEPT §12.4); entfallen sind die Sternbild-Kontextkarte und der Kernradius-Vergleich (jetzt Feld „Kernmaske“). Docstrings verweisen auf die neuen Nummern. Tests: Notebooks gültig/ohne Ausgaben/übersetzbar, NB00-Demo läuft durch (`tests/test_notebooks.py`).

## [0.5.0] — 2026-11-10

NB00 umgebaut (Vorbedingungen, Bereitschaft NB07/NB08, Defokus-Vergleich, Plate-Solve-Test), Defokus-Simulation, gemeinsame Vorbedingungsprüfung in NB01/NB00.

### Neu
- **NB00 umgebaut:** Schritt 0 **Vorbedingungen** (gemeinsame Prüfung mit NB01, `varphot.readiness`: Python, Pakete, ASTAP, Siril, Datenordner, `observer.json`, KI-Wege); Schritt 2b **Bereitschaft** (Kameraprofil NB07, Transformation NB08, am Standort sichtbare Standardfelder); Schritt 3c **scharf gegen defokussiert** (FWHM, Spitzenwert, S/N-Folgen, Wunschbelichtung → nötiger Defokus, `defocus_tradeoff`/`defocus_needed`) und **Plate-Solve-Test** mit ASTAP am geplanten Fokus und an künstlich verunschärften Bildern (`defocus_solve_ladder`); der Plan speichert FWHM scharf, Defokusfaktor, Plate-Solve-Ergebnis und Bereitschaft.
  `fwhm_summary` weist FWHM heller und schwacher Sterne getrennt aus (helle Sterne sind auf echten Bildern breiter). NB01 nutzt dieselbe Prüfung (Siril optional statt ✗). `solve_array` löst Arrays ohne WCS (RA/Dec in Grad → `OBJCTRA`/`OBJCTDEC`).
- **Defokus-Simulation** `varphot.synthetic.defocus_image` (Gauß-Faltung oder Kreisring mit Obstruktion) und `tools/defocus_solve_test.py`: prüft an einem echten scharfen Bild, bis zu welcher Unschärfe ASTAP noch löst (LCO δ Cep: Gauß bis FWHM ~20 px, Donut bis ~12 px; KONZEPT §12.1). Befund: bei echten Bildern ist die FWHM heller Sterne größer als die schwacher (7 px gegen 4,5 px).

## [0.4.0] — 2026-11-10

Schwerpunkte: Transformation und AAVSO-Export, Planung (NB00), Inhaltsprüfung, lokale KI-Zweitlesung, Kamera-Charakterisierung (NB07), Transformationskoeffizienten (NB08), breitere Tests (79 → 91 % Abdeckung, 196 → 210+ Tests).

### Neu
- **Lokale KI als zweite Leserin des Berichts** (`varphot/aireview.py`, NB01 Vorbedingungen, NB06 Schritt 6): Weg zur KI in fester Reihenfolge — (1) stärkerer Rechner im Heimnetz (Adressen der Reihe nach, z. B. LAN dann WireGuard): Opencode-Prüfung per `ssh` (Aufruf **noch nicht eingebaut**), sonst Ollama dort;
  (2) lokal: Opencode (nur mit **lokalem** Modell — die `opencode/*`-Modelle sind Cloud und werden nicht benutzt), dann Ollama. Nur Ziele im privaten Netz (`is_private_host`); Konfiguration im Schlüssel `ai` der privaten `observer.json` (`save_config` erhält ihn); `VARPHOT_AI=off`, `VARPHOT_AI_REVIEW=0`.
  Ohne Weiterleitungen, ohne Proxy (Tests). Ausweichen auf `curl`/`nc`, wenn macOS dem Python das lokale Netz sperrt („No route to host“). Prompt mit fester Prüfliste (ohne Liste meldeten alle getesteten Modelle „Keine Auffälligkeiten“); Probelauf und Grenzen (Fehlalarme, Übersehenes): KONZEPT §11.14. Nur Anmerkungen, nie Zahlen.
- **Inhaltsprüfung des AAVSO-Exports** (`check_plausibility`, NB06 Schritt 4b): `ERROR` blockiert die Datei, `WARN` steht als „Offene Punkte“ im Bericht; **Reifegrad-Tabelle** (`varphot/maturity.py`) nennt nicht an echten Daten geprüfte Funktionen; `OBSTYPE` bei Farbkamera/RGB-Filter wird abgefragt (`VARPHOT_OBSTYPE`, `VARPHOT_OBSTYPE_CONFIRMED`).
- **Automatisiert:** Sequenz-ID (`CHART`) aus der VSP-Antwort (NB03 → NB06, vorher von Hand); Feldgröße aus Sensor und Brennweite (`field_of_view_deg`, NB00 → Plan → NB03); transformierter Check-Stern (`transformed_with_check`, KMAG in NB06, Warnung bei Abweichung > 0,05 mag).
- **AAVSO-Export (NB06, `varphot/aavso.py`):** Extended Format v1.2 schreiben und gegen dessen Regeln prüfen (Pflichtparameter, 15 Felder, Feldlängen, Filtercodes, Ensemble-Regel, JD, Leerzeilen; Beispiele der Format-Seite als Tests). Datei nur bei fehlerfreier Prüfung; kein Upload.
  Testdaten (LCO) mit Code `TST01` und markiertem Dateinamen; Gaia-Comps werden gekennzeichnet; transformierter Export nur nach bestandenem NB08-Gütetest.
- **Transformation in der Lichtkurve:** `transformed_light_curve()` (je Bild und Comp nach Handbuch Gl. 6.11–6.14, Median über die Comps) und NB05 Schritt 6 (optional, `VARPHOT_TRANSFORM_FILE`, Messtabellen der drei Kanäle).
- **Gaia-Sperre für die Transformation:** `fit_transform`/`transformed_light_curve` lehnen Kataloge mit Gaia-abgeleiteten Werten ab (Spalte `source` oder Gaia-Kennung `g1` …); NB03 schaltet für TB/TR/B/R die Gaia-Ergänzung ab.
- **AAVSO-Standardfelder per Programm:** `fetch_std_field()` (VSP-Schnittstelle mit `special=std_field`): M 67 (190 Sterne), NGC 7790 (178), M 11 (415), NGC 3532 (226), NGC 1252 (22), Melotte 111 (85) mit U/B/V/Rc/Ic — kein Herunterladen von Hand nötig. NB08 nutzt sie (`VARPHOT_NB08_STDFIELD`).
- **NB00:** jeden Katalogstern (Ziel, Comps, Check) einzeln gegen Obergrenze und S/N ≥ 100 prüfen (`check_field_stars`), `V_comp_min` im Plan; **Mond** in der Sichtbarkeit; Methode `monorgb` (Mono + RGB-Filter). **NB03 liest den Plan** (`comp_v_range`, neue Regel `comp_bv_abs`).
- **Kanaltrennung:** `varphot/cfa.py` und `tools/split_cfa.py` (R, G = Mittel beider Grün, B; WCS und Pixelskala angepasst; getestet), `tools/siril_calibrate_cfa.ssf` (ungetestet). Preset `qhy268m` (Mono). KONZEPT §11.12 (RGB-Filterrad), §11.13.

### Neu
- **NB08 Transformationskoeffizienten** (`notebooks/08_transformation.ipynb`, `varphot/transform.py`): `Tbv`, `Tb_bv`, `Tv_bv`, `Tr_bv` nach AAVSO DSLR Observing Manual v1.4 Gl. 6.15–6.18 (gelesen) aus Standardsternen mit Geraden und Sigma-Clipping (`linfit`);
  mittlere instrumentelle Magnituden je Kanal aus den NB04-Messtabellen mit Abzug der Bildnullpunkte (`instrumental_table`); Extinktion k aus dem Nullpunktgang (`fit_extinction`); Anwendung `transform_target` (Gl. 6.11–6.14, Extinktion 6.19–6.21);
  **Leave-one-out-Gütetest** (`loo_validation`: transformiert gegen nicht transformiert) mit Entscheidung `TG`/`V` je Band; Katalog aus CSV oder AAVSO-VSP (`catalog_from_vsp_table`); Ergebnis `transform_<Kamera>_<Einstellung>.json`.
  Demo-Modus mit synthetischem Standardfeld: Koeffizienten auf ±0,003 wiedergefunden (Tbv 1,489 statt 1,493). 9 neue Tests. Nicht mit echten Standardfeld-Aufnahmen geprüft (NB05 Schritt 6 und NB06 wenden sie an, s. o.).

### Behoben / Robustheit (Durchsicht des gesamten Codes, zweifach)
- `ensemble_mag` liefert ohne brauchbaren Comp (Fluss ≤ 0, V unbekannt) oder bei Ziel ohne Fluss `(nan, nan, 0, nan)` statt Warnungen und Unsinn; `light_curve` schließt Comps ohne endliches V aus.
- `solve_image`: Zeitüberschreitung oder nicht startbares ASTAP führt zum Fallback auf die Header-WCS (vorher Absturz des Notebooks).
- `select_comps` (Altpfad): fehlendes Ziel meldet `ValueError` statt `IndexError`; die festen Zahlen 60 px und 6 mag stehen als `comp_halo_px`/`comp_dv_max` in `CFG`.
- `aperture_flux`: Sättigungshinweis als `warnings.warn` statt `print`. `ThreadingHTTPServer`-Tests ohne `getfqdn` (blockierte bis 35 s).
- Werkzeug: `ruff` (Konfiguration in `pyproject.toml`), `pytest-cov`; Befunde (Schleifenvariable in Lambda, nicht genutzte Variable, fehlendes `check=`, `raise … from`) behoben.
- Neue Tests: `test_aireview.py`, `test_core.py` (Cache, Comp-Auswahl und ihre Verwerfungsgründe, Photometrie, PSF, Plots, ASTAP-Attrappe, Zeit, VSP/SIMBAD gemockt), `test_pipeline_extra.py` (`run_batch` mit echten FITS, Download-Ablauf).

### Behoben
- **NB04-Cache-Pfad:** Eine bereits berechnete `messtabelle_roh_*.csv` wurde mit `keep_default_na=False` gelesen; leere Felder (NaN) blieben leere Zeichenketten und machten Zahlenspalten zu Text
  (`TypeError: '>' not supported between 'str' and 'float'` in `qc_frames`). Neu `read_measurements()` (Regressionstest). Der Fehler trat nur beim zweiten Lauf auf.
- **NB04-Cache-Schlüssel** enthält jetzt Kernmaske **und Aperturen**; mit einem Plan (andere Aperturen) wurde sonst eine veraltete Tabelle wiederverwendet.

### Neu
- **NB00 Planung und Probebilder** (`notebooks/00_planung.ipynb`, `varphot/plan.py`): Ziel (SIMBAD), Methode (Monochrom + Filter / Farbkamera / DSLR) und Kamera-Profil wählen, Sichtbarkeit am Standort, **Probebilder** auswerten (hellster Stern, Sättigung, FWHM per Gauß-Anpassung; bei Bayer auf der Grünebene),
  daraus längste/empfohlene Belichtung, Aperturen (1,5 × FWHM, Ring nach Handbuch §6.1) und Warnungen (Bayer-Rohbild-FWHM < 8 px, alles gesättigt). Der Plan wird als JSON in `PHOTOMETRIE_PY_DATA/plans/` gespeichert; **NB04** übernimmt die Aperturen über `VARPHOT_PLAN`. Demo-Modus mit synthetischen Probebildern
  (FWHM 2,98 statt 3,0 px und 4,45 statt 4,5 px wiedergefunden). Mit echten Probebildern nicht getestet. `Camera` hat jetzt `linear_min_adu`/`linear_max_adu` (NB07 schreibt sie; NB00 nutzt die gemessene Obergrenze statt der 75-%-Regel). KONZEPT §12.

### Neu
- **NB07 Schritt 3b: RAW-Kompression prüfen** (`histogram_gaps`, `compression_verdict`): zählt je Flat-Aufnahme und Farbebene fehlende ganzzahlige ADU-Werte im Kern der Verteilung (Median ± 2σ, nur wo sie bei dem Rauschen vorkommen
  müssten) und den gemeinsamen Teiler der besetzten Werte; Verdacht bei mindestens zwei Pegeln mit > 5 % Lücken oder Teiler > 1 (Startwert). Erkennt verlustbehaftete („companded“) und skalierte (14 → 16 Bit) RAW-Daten, vor der Gain-Messung.
  Demo mit `VARPHOT_NB07_DEMO_COMPRESS=1`. Test mit sauberen, komprimierten und skalierten synthetischen Daten. Nicht gegen echte Kameradaten geprüft.

### Neu
- **Kamera-Auswahl** (`varphot/camera_presets.py`): Vorlagen für **Player One Ares-C Pro** (Herstellerdaten aus dem Handbuch gelesen) und **Panasonic Lumix S9** (Vollformat; Panasonic-Spezifikation gelesen: nur elektronischer Verschluss,
  6000×4000, RAW-Bittiefe nicht angegeben) sowie „Eigene Kamera“, jeweils mit Prüfstatus je Angabe. **NB07** wählt Kamera und Einstellung (Dropdown oder `VARPHOT_CAMERA`/`VARPHOT_CAMERA_SETTING`); die Bittiefe wird bei Unbekannten aus dem Maximalwert abgeleitet
  (`detect_saturation`: mehrere Bilder am Anschlag = gesättigt, sonst Abbruch statt falscher Wert); RAW-Ordner werden erkannt und auf die Siril-Wandlung (`tools/siril_convert_raw.ssf`, ungetestet) verwiesen.
- **Mehrere Kameraprofile** in `observer.json` (Liste `cameras`, je Modell + Einstellung; `camera` = aktive). **NB01** wählt die Kamera (Profil, Vorlage oder neu) und bewahrt dabei die NB07-Felder; ältere Dateien bleiben lesbar.
- KONZEPT §11.11: Lumix S9 (Spezifikation, Folgen, offene Punkte, Kamera im Originalzustand, nicht astro-modifiziert (vom Nutzer bestätigt)).

### Neu
- **NB07 Kamera-Charakterisierung** (`notebooks/07_kamera_charakterisierung.ipynb`, `varphot/camera.py`): Bayer-Ebenen trennen, Offset und Maximalwert, **Gain per Photon-Transfer-Kurve**
  je Farbebene (Gegenprobe Einzelpaar-Formel), Ausleserauschen aus Bias-Paar, Full Well, Linearitätsbereich aus Belichtungsreihe (robuste Referenzgerade), Dunkelstrom aus Darks;
  Vergleich mit Herstellerwerten (Ares-C Pro, Gain 0 LRN), Speichern als Kameraprofil in `PHOTOMETRIE_PY_DATA/` und `observer.json` (nur im Modus `real`).
  Verfahren nach AAVSO DSLR Observing Manual v1.4 (Anhang A, E, gelesen) und Janesick 2001. **Demo-Modus** mit synthetischen Bildern bekannter Wahrheit (Gain 4,4 → gefunden 4,41).
  Befund beim Bau: Das Ausleserauschen ist aus dem Achsenabschnitt der Photon-Transfer-Kurve nicht bestimmbar (lieferte 0 statt 3 e⁻) und wird nur aus dem Bias-Paar berechnet.
- `Camera` um Bayer-Muster, Bittiefe, Maximalwert, Offset, Full Well, Einstellung und Quelle erweitert (alte `observer.json` bleiben lesbar). 11 neue Tests.

### Geändert
- **KONZEPT §11 gegen das AAVSO-DSLR-Handbuch v1.4 abgeglichen** (vom Nutzer lokal abgelegt, Kap. 4–6, Anhang A und E im Wortlaut gelesen): maßgebliche
  Transformationsgleichungen 6.11–6.14 und Koeffizientenbestimmung 6.15–6.18, Extinktionserweiterung 6.19–6.22, Einreichungsregeln (Ensemble-Eintrag, `GROUP`,
  `OBSTYPE=DSLR`), Comp-Regeln (B−V 0,3–1,0, S/N ≥ 100), Sättigungsgrenze 75 % des Maximalwerts, FWHM ≥ 8–10 px im Rohbild, beide Grünkanäle mitteln,
  keine Transformation bei Sternen mit starken Emissionslinien, Kameratests für NB07 (Anhang A/E). Kamenec 2023 bleibt als Variante.

### Geändert / korrigiert
- **`v_from_gaia`:** Koeffizienten gegen die Gaia-EDR3-Dokumentation (Tab. 5.7) geprüft — stimmen; der Gültigkeitsbereich war falsch angegeben
  (2,75 statt **5,0** für BP−RP) und σ = 0,03017 statt 0,04. Gegenprobe gegen die AAVSO-Sequenz: 31 Sterne, Streuung 0,029 mag
  (`tools/compare_gaia_vsp.py`).
- **`scintillation_mag`:** Formel auf Osborn et al. (2015), Gl. 2 umgestellt (gelesen) und mit deren Korrekturfaktor `c_y = 1,5` (Young unterschätzt
  die mediane Szintillation „typically by a factor of 1.5") versehen. Wert am LCO-Satz ~0,008 statt ~0,006 mag.
- **Zitate geprüft:** Calabretta & Greisen 2002, Stetson 1987, Lomb 1976, Scargle 1982, Vallenari 2023, Montegriffo 2023, Riello 2021, Osborn 2015.
  Merline & Howell 1995 war nicht auffindbar und wurde entfernt; Howell 2006 bleibt ohne Kapitelangabe.
- **Lizenzen:** Nutzungsbedingungen der Testdaten im Wortlaut nachgetragen (`docs/testdaten.md` §3): LCO = CC BY-NC 4.0 mit Namensnennung;
  EXOTIC-Beispielsatz ohne Lizenz (alle Rechte vorbehalten, keine Weitergabe); MicroObservatory-Bedingungen nicht prüfbar (TLS-Fehler der Seite).
  Die Daten waren vor dieser Prüfung geladen worden — jetzt als Regel in `docs/entwicklung.md` §2a.

### Neu
- **KONZEPT §11 neu gefasst:** AAVSO-Regeln aus dem Wortlaut (Extended Format, Forum-Zusammenfassung zu OSC: `OBSTYPE=DSLR`, `FILTER` = Band des Ergebnisses),
  Transformationsgleichungen nach Kamenec 2023 (gelesen), Herstellerdaten der Ares-C Pro (Handbuch gelesen: IMX533, 14 bit, Gain-Tabelle, kein IR-Sperrfilter im Fenster),
  Gaia gegen AAVSO quantitativ, Erklärung zu Sirils Lichtkurve, Entwurf NB07 (Kamera-Charakterisierung) und NB08 (Transformationskoeffizienten), Beispieldaten, Prüfstatus.
- **`tools/compare_gaia_vsp.py`:** misst Gaia-V/B/R gegen die AAVSO-Sequenz im Feld eines Ziels.

### Neu
- **Testdaten-Download** (`varphot/testdata.py`, `tools/download_testdata.py`): `lco-dcep` (LCO-Archiv, MD5-geprüft) und `hatp32`
  (EXOTIC-Beispielsatz), Standardziel `PHOTOMETRIE_PY_DATA/testdata/` (Nextcloud). Quellen, Auswahl und Ergebnisse: `docs/testdaten.md`, README.
  Aus dem Testsatz entfernt: 103 Bilder anderer Teleskope (769 MB; nicht re-downloadbar nötig, Skript lädt nur `elp0m411`).
- **Entwicklungsrichtlinien** (`docs/entwicklung.md`): Git, Datenschutz, Tests und Docstring-Standard (Warum, Wie, Grenzen,
  Validierung, Quellen mit Prüfstatus). Kernfunktionen entsprechend dokumentiert (`light_curve`/Kernkorrektur, `harmonic_fit`,
  `measure_frame`, `qc_frames`, `ensemble_mag`, `scintillation_mag`, BJD/Zeit, `aperture_flux`, `detect`, `check_wcs`, `field_from_wcs`).
- **KONZEPT §11 Farbkamera** (One-Shot-Color, Player One Ares-C): AAVSO-Extended-Format (`TG`/`TB`/`TR`, `TRANS`, CMOS → `CCD`),
  Rolle von Siril (CFA-Kalibrierung, Kanaltrennung), Transformationsverfahren, Beispieldaten und Prüfstatus der Quellen.
  Nur Konzept, nichts implementiert.

### Neu (P0-3: erster echter Datensatz, LCO δ Cep, Filter V)
- **Stapelphotometrie** (`varphot/batch.py`): `read_frame` (auch `.fits.fz`), `measure_frame`, `run_batch` (parallel),
  `qc_frames` (Bildflags `NO_WCS`, `NO_SIGNAL`, `LOW_TRANSPARENCY`, `BAD_SEEING`), `ensemble_mag` (robust, gewichtet),
  `light_curve` (BJD_TDB, Fehler, Check-Stern, Sättigungsmarkierung). Ersetzt die Platzhalter in NB04/NB05.
- **Zeit** (`varphot/timeutil.py`): Belichtungsmitte, `bjd_tdb()` mit Standort, Luftmasse, Standort aus LCO-Header.
- **Fehlerbudget** (P1): CCD-Gleichung (Photonen, Himmel, Ausleserauschen; Gain/RON aus dem Header) plus
  Szintillation nach Young (`scintillation_mag`).
- **`field_from_wcs()`**: Sensorfeld und Winkel direkt aus dem WCS eines Bildes; NB03 nimmt über `VARPHOT_FRAME` ein
  Referenzbild, `VARPHOT_RULES` überschreibt Auswahlregeln (Kleinfeld-Optik).
- **Gesättigtes Ziel: Kernmaske** (`core_r`, `light_curve(core_correct=True)`): Der Sättigungsverlust hängt vom Seeing
  ab (Korrelation Nachtresiduum–FWHM −0,73) und verfälschte die Lichtkurve von Nacht zu Nacht. Jetzt wird nur der Ring
  außerhalb des Kerns gemessen und mit dem Ringanteil heller, ungesättigter Comps desselben Bildes hochgerechnet.
  NB04 Schritt 4b vergleicht mehrere Kernradien (Residuum um eine Fourier-Reihe, Korrelation mit dem Seeing).
- **`harmonic_fit()`** (`varphot/periodfit.py`): Fourier-Reihe mit Periodensuche, liefert Periode, Residuum, Amplitude.
- **Ergebnis am LCO-Satz** (156 Bilder des Teleskops `0m4-11`, 98 brauchbar, 86 mit gesättigtem Ziel):
  Cepheiden-Lichtkurve mit Lomb-Scargle **5,363 d** (Literatur 5,366 d), Spannweite 0,93 mag, Fourier-Residuum **0,068 mag**
  (vorher 0,129 mag, Periode 5,30 d). Die Modellamplitude (3 Harmonische) ist mit 0,81 mag etwas kleiner als in der
  Literatur (~0,88); sie wächst mit dem Kernradius (0,70 → 0,99 mag), der Radius 1,5 px ist auf kleinstes Residuum
  gewählt, nicht auf die Amplitude. Aperturgröße und Himmelsring ändern die Streuung nicht (0,125–0,138 mag).

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
