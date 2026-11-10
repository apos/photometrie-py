# Testdaten — Herkunft, Auswahl, Ergebnisse

Die Bilder liegen **nicht** im Repo (zu groß, eigene Nutzungsbedingungen). Laden mit
`python tools/download_testdata.py lco-dcep hatp32` (Standardziel `PHOTOMETRIE_PY_DATA/testdata/` neben dem Repo (Nextcloud), `VARPHOT_TESTDATA` überschreibt;
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

### Ergebnis der Pipeline-Läufe (alte Notebooks NB01–NB05, Stand 2026-11-10; seit 0.6.0: 01_vorbereitung, 02_messung)

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
`varphot.batch.light_curve(core_correct=True)` und frühere NB04 Schritt 4b (jetzt Feld „Kernmaske“ in 02_messung). Der Kernradius wurde an diesen Daten gewählt.
Der Check-Stern weicht um +0,15 mag vom Katalog ab (Gaia-abgeleitetes V roter Sterne ist unsicher).

## 2. `hatp32` — HAT-P-32 b Transit (Test ohne WCS, Clear-Filter)

| | |
|---|---|
| Quelle | <https://github.com/rzellem/EXOTIC_sampledata> (Beispielsatz des Programms EXOTIC, Verzeichnis `HatP32Dec202017`) |
| Instrument | MicroObservatory (Harvard-Smithsonian CfA), Whipple Observatory, Arizona; 6″-Teleskop |
| Umfang | 142 FITS, 89 MB, 650×500 px, 5,2″/px, Belichtung 60 s, Filter Clear, Nacht 2017-12-19/20 |
| Besonderheiten | Header **ohne WCS**; Längenangabe `LONGITUD = 110.88` ohne Vorzeichen (West) — Standort darf nicht automatisch aus dem Header gelesen werden |

Ergebnis: ASTAP löst Bild 1 in 0,2 s (`radius_deg=5`, `fov_deg=0.72`). Die Pipeline (frühere NB04/05) lief mit diesem Satz noch
nicht; er soll Transit, Clear-Filter und grobe Pixelskala abdecken.

## 3. Lizenzen und Nutzungsbedingungen (Stand 2026-11-10, im Wortlaut geprüft soweit zugänglich)

**Versäumnis:** Beide Datensätze wurden geladen, *bevor* die Bedingungen gelesen waren. Das ist nachgeholt; die Regel steht jetzt in
`docs/entwicklung.md` §2a. Die Daten liegen im privaten Nextcloud-Ordner `PHOTOMETRIE_PY_DATA/testdata/` (auf Wunsch des Nutzers, damit sie nicht verloren gehen), **nicht im Repo**. Das ist keine Veröffentlichung; der Ordner darf nicht öffentlich geteilt werden (EXOTIC-Daten ohne Lizenz, LCO nur mit Namensnennung und nicht-kommerziell).

| Datensatz | Quelle der Bedingungen | Wortlaut (Auszug) | Folgen |
|---|---|---|---|
| `lco-dcep` | <https://lco.global/observatory/acknowledgments/> (gelesen 2026-11-10) | „All images and data derived from observations made at LCO facilities are made available for scientific or educational use, subject to the Creative Commons license BY-NC 4.0 and in the case of science data, subject to an additional proprietary period.“ — „… to be freely shared and redistributed on the condition that an appropriate attribution is made.“ — „Any use of LCO images and data not for scientific or educational purposes, e.g. for commercial purposes, is not permitted unless through an explicit arrangement.“ Kontakt `image_use@lco.global`. | CC BY-NC 4.0: nur nicht-kommerziell, Namensnennung. Namensnennung für Bilder: „Image taken with [Teleskop] operated by Las Cumbres Observatory“; in Veröffentlichungen: „This work makes use of observations from the Las Cumbres Observatory global telescope network.“ und Zitat Brown, T. M. et al. 2013, PASP 125, 1031 (Kürzel „LCOGT“). Weitergabe wäre mit Namensnennung erlaubt; wir geben die Bilder nicht weiter (das Download-Skript holt sie aus dem Archiv). |
| `hatp32` | GitHub `rzellem/EXOTIC_sampledata` (API-Abfrage 2026-11-10): `license: null`, keine Lizenzdatei; README: „Sample transit observations for testing EXOTIC“. Der Code-Repo `rzellem/exotic` steht unter einer BSD-ähnlichen Lizenz (Caltech/JPL), die **nicht** für den Datensatz gilt. | — | **Keine Lizenz für die Daten = alle Rechte vorbehalten.** Nur lokale Tests; nicht weitergeben, nicht ins Repo. Ursprung (MicroObservatory, CfA, Harvard-Smithsonian) in Veröffentlichungen nennen. |
| MicroObservatory (Ursprung von `hatp32`) | <https://microobservatory.org> | **Nicht prüfbar:** TLS-Zertifikatsfehler der Seite („unable to verify the first certificate“); die Prüfung wurde nicht abgeschaltet. Die Websuche fand keine Nutzungsbedingungen für das Archiv. | Bedingungen unbekannt → keine Weitergabe. Offen: Rückfrage beim CfA oder Bedingungen später lesen. |

Software, die wir nur lesen und zitieren: `astronomyk/seestar_photometry` ist laut GitHub GPL-3.0 — Code wird nicht übernommen.

## 4. Noch fehlend: Farbkamera (One-Shot-Color)

Für das Konzept TG/TB/TR (KONZEPT.md §11) fehlt ein Satz mit Roh-Bayer-Bildern eines Veränderlichen. Kandidaten:
siehe KONZEPT.md §11.6.
