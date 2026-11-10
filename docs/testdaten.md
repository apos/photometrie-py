# Testdaten — Herkunft, Auswahl, Ergebnisse

Die Bilder liegen **nicht** im Repo (zu groß, eigene Nutzungsbedingungen). Laden mit
`python tools/download_testdata.py lco-dcep hatp32` (Standardziel `~/astro_testdata`, `VARPHOT_TESTDATA` überschreibt;
vorhandene Dateien werden per MD5 bzw. Größe geprüft und nicht erneut geladen).

## 1. `lco-dcep` — δ Cep, Filter V (Hauptdatensatz, Cepheide)

| | |
|---|---|
| Quelle | Las Cumbres Observatory, öffentliches Archiv <https://archive.lco.global>, API `archive-api.lco.global/frames/` |
| Abfrage | `OBJECT=delta Cep`, `public=true`, `reduction_level=91` (BANZAI-reduziert), `primary_optical_element=V`, Dateiname beginnt mit `elp0m411-` |
| Programme | FTPEPO2014A-004 (Faulkes Telescope Project), LCOEPO2018B-001 |
| Instrument | Teleskop 0m4-11 (0,4 m, McDonald Observatory, Texas), Kamera kb88 (2019/20) bzw. kb92 (2018) |
| Umfang | 156 Bilder, 1,1 GB, 3054×2042 px, 0,58″/px (Feld 29′×20′), Belichtung ~1,29 s |
| Bedingungen | Öffentliche LCO-Daten; Namensnennung (Las Cumbres Observatory / Faulkes Telescope Project) und die Hinweise des Archivs beachten |

**Warum nur `elp0m411`:** Das Archiv liefert für „delta Cep, V" insgesamt 259 Bilder von sechs Teleskopen mit
unterschiedlicher Pixelskala und Feldgröße (u. a. zwei Bilder 4096×4096 px vom 1-m-Teleskop). Das 0m4-11 hat die einzige
zusammenhängende Zeitreihe; die übrigen 103 Bilder (769 MB) wurden aus dem Testsatz entfernt. Hinweis: Der `count` der
Archiv-API ist unzuverlässig (meldete 24 statt 259) — das Skript blättert bis zur ersten kurzen Seite.

### Ergebnis der Pipeline-Läufe (NB01–NB05, Stand 2026-11-10)

**Bildqualität** (`qc_frames`, Schwellen: Comp-S/N ≥ 10, Transparenz ≥ 0,6, FWHM ≤ 4″):

| Ergebnis | Bilder |
|---|---|
| **brauchbar** | **98** von 156 (34 Nächte, 2019-11-15 bis 2020-01-10) |
| zu wenig Signal (`NO_SIGNAL`) | 44 — davon 9 Bilder von 2018 (kb92) ohne erkennbare Vergleichssterne |
| zu wenig Signal und schlechtes Seeing | 10 |
| dünne Wolken (`LOW_TRANSPARENCY`) | 3 |
| schlechtes Seeing (`BAD_SEEING`) | 1 |

**Lichtkurve** (5 Comps aus Gaia DR3/AAVSO-VSP, Check-Stern g1, Apertur 10 px, Himmelsring 16–24 px):

| | ohne Kernmaske | mit Kernmaske 1,5 px |
|---|---|---|
| Lomb-Scargle-Periode | 5,30 d | **5,363 d** (Literatur 5,366 d) |
| Fourier-Residuum (3 Harmonische) | 0,129 mag | **0,068 mag** |
| Modellamplitude | 0,70 mag | 0,81 mag (Literatur ~0,88) |

Befunde: Das Rauschen innerhalb einer Nacht (0,039 mag) entspricht dem Fehlerbudget; die Reststreuung kam **zwischen den
Nächten** und korrelierte mit dem Seeing (r = −0,73): δ Cep ist in 86 der 98 Bilder gesättigt (Kern ~103 000 ADU),
und der Sättigungsverlust hängt vom Seeing ab. Aperturgröße und Himmelsring (6–36 px) ändern die Streuung nicht. Siehe
`varphot.batch.light_curve(core_correct=True)` und NB04 Schritt 4b. Der Kernradius wurde an diesen Daten gewählt.
Der Check-Stern weicht um +0,15 mag vom Katalog ab (Gaia-abgeleitetes V roter Sterne ist unsicher).

## 2. `hatp32` — HAT-P-32 b Transit (Test ohne WCS, Clear-Filter)

| | |
|---|---|
| Quelle | <https://github.com/rzellem/EXOTIC_sampledata> (Beispielsatz des Programms EXOTIC, Verzeichnis `HatP32Dec202017`) |
| Instrument | MicroObservatory (Harvard-Smithsonian CfA), Whipple Observatory, Arizona; 6″-Teleskop |
| Umfang | 142 FITS, 89 MB, 650×500 px, 5,2″/px, Belichtung 60 s, Filter Clear, Nacht 2017-12-19/20 |
| Besonderheiten | Header **ohne WCS**; Längenangabe `LONGITUD = 110.88` ohne Vorzeichen (West) — Standort darf nicht automatisch aus dem Header gelesen werden |

Ergebnis: ASTAP löst Bild 1 in 0,2 s (`radius_deg=5`, `fov_deg=0.72`). Die Pipeline (NB04/05) lief mit diesem Satz noch
nicht; er soll Transit, Clear-Filter und grobe Pixelskala abdecken.

## 3. Noch fehlend: Farbkamera (One-Shot-Color)

Für das Konzept TG/TB/TR (KONZEPT.md §11) fehlt ein Satz mit Roh-Bayer-Bildern eines Veränderlichen. Kandidaten:
siehe KONZEPT.md §11.6.
