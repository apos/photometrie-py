# Oberfläche der Notebooks: Regeln, Bausteine, Prüfung

Gilt für alle Notebooks (`notebooks/*.ipynb`) und jede neue Oberfläche in diesem Projekt. Die allgemeinen Grundsätze (nicht nur für Notebooks) stehen im zentralen Wissensspeicher des Autors; hier steht, was im Repo gilt und geprüft wird.

## 1. Ablauf: Mockup zuerst

1. **Mockup vor Code.** Jede neue oder geänderte Oberfläche wird zuerst als sichtbares Mockup abgestimmt, bei offener Gestaltung als **drei Varianten** zum Vergleich. Ein Textentwurf oder eine Tabelle in Markdown ist kein Mockup.
2. **Das verabschiedete Mockup ist das Abnahmekriterium.** Die Umsetzung sieht so aus und kann, was das Mockup zeigt (Abhaken, Hervorhebung, Zuklappen). Weicht sie ab, wird das gesagt und begründet.
3. **Echte Ausgabe ansehen.** Vor „fertig“ die gerenderte Seite im Browser prüfen (`python tools/gui_preview.py`, Datei `build/gui-vorschau.html`) und, wenn das Notebook in Datalore läuft, auch dort.
4. **Jeder Baustein hat eine Vorschau.** Neue Funktionen in `varphot/nbui.py` brauchen einen Eintrag in `tools/gui_preview.py` (`SAMPLES`); der Test `test_every_public_building_block_has_a_preview` schlägt sonst fehl.

## 2. Gestaltungsregeln

| Regel | Umsetzung |
|---|---|
| Keine Textwüsten | Markdown-Zellen höchstens 600 Zeichen; Anleitungen als Karte (`ui.step`) mit Aufgaben, Kacheln und Hinweisen |
| Keine breiten Tabellen | Markdown-Tabellen sind verboten; stattdessen `ui.fields` (Feld mit zwei kurzen Zeilen), `ui.kv` (Name links, Text rechts) oder `ui.tiles` |
| Orientierung | Schrittleiste (`ui.stepper`) zeigt, wo man ist; Schritte laufen **fortlaufend ab 1**, Unterschritte `1.1`, `1.2` (kein `b` ohne `a`) |
| Handlung | Aufgaben sind **ausformulierte Sätze**, abhakbar (`ui.tasks`); keine Kürzel, keine Stichworte ohne Verb |
| Kontext | Der eigene Aufbau (Fall A bis D) ist hervorgehoben (`ui.cases`), die anderen grau |
| Details | Seltenes steht zugeklappt (`ui.details`) |
| Bedeutung durch Farbe | grün = erledigt/passt, blau = aktuell/Info, orange = prüfen, rot = Fehler; Farbe nie als einziger Hinweis |
| Lesbarkeit | Text/Hintergrund mindestens Kontrast 4,5 (WCAG AA), feste Farben und ausdrückliche Hintergründe, damit helle und dunkle Notebook-Designs lesbar bleiben |

## 3. Technische Eigenheiten von Jupyter und Datalore

- **Markdown rendert ohne Ausführen, HTML-Karten erst nach dem Ausführen.** Die Karten sind Code-Zellen; im Repo stehen keine Ausgaben (`nbstripout`). Beim Durchlaufen von oben nach unten sind sie sichtbar.
- **Interaktion ohne Skript.** Das Abhaken sind Checkboxen mit CSS (`:checked`, `:has`). Der Haken lebt nur in der Anzeige und geht beim erneuten Ausführen verloren; Zustand, der bleiben soll, gehört in die Sitzung (`Session`) oder in `ipywidgets`.
- **Symbole als Inline-SVG** (`ui.icon`), nicht als Icon-Schrift: Web-Icon-Fonts stehen im Notebook nicht zur Verfügung.
- **Zelltyp-Wechsel in Datalore.** `cell edit` ändert den Typ nicht; `tools/sync_datalore.py` legt die Zelle dann neu an und schreibt die neue ID in `*_dl_ids.json`.
- **Veralteter Kernel.** Nach einem `git pull` auf panama den Agent neu starten, sonst bleibt das alte `varphot.nbui` im Speicher.

## 4. Prüfung (automatisch)

| Prüfung | Datei |
|---|---|
| Keine Markdown-Tabellen, keine Textwände | `tests/test_gui_rules.py` |
| Schrittnummern ab 1 lückenlos, passend zur Schrittleiste | `tests/test_gui_rules.py` |
| Kontrast aller Farbpaare (`nbui.CONTRAST_PAIRS`) | `tests/test_gui_rules.py` |
| Jeder Baustein hat eine Vorschau | `tests/test_gui_rules.py` |
| Jede umgebaute Zelle rendert, Abhaken und Hervorhebung stimmen | `tests/test_nbui.py` |
| Notebook gültig, ohne Ausgaben, Kopfzelle mit `ui.header(` | `tests/test_notebooks.py` |

## 5. Checkliste bei neuer oder geänderter Oberfläche

- [ ] Mockup (bei offener Gestaltung drei Varianten) gezeigt und freigegeben
- [ ] Umsetzung entspricht dem Mockup, Abweichungen benannt
- [ ] Keine Markdown-Tabelle, kein Absatz über 600 Zeichen
- [ ] Schritte fortlaufend ab 1, Aufgaben als ganze Sätze, eigener Fall hervorgehoben
- [ ] Neuer Baustein: Eintrag in `tools/gui_preview.py`, Test grün
- [ ] Vorschau im Browser angesehen, in Datalore geprüft (falls dort genutzt)
- [ ] `CHANGELOG.md` ergänzt

## 6. Neuen Baustein anlegen

1. Funktion in `varphot/nbui.py` (liefert einen HTML-String, nimmt Texte mit `**fett**`, `*kursiv*`, `` `code` `` an, nutzt nur die Farben aus dem Kopf des Moduls).
2. Neue Text/Hintergrund-Paare in `CONTRAST_PAIRS` eintragen.
3. Beispiel in `tools/gui_preview.py` (`SAMPLES`), Vorschau ansehen.
4. Test in `tests/test_nbui.py`.
