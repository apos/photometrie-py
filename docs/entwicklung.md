# Entwicklungsrichtlinien

Gelten für alle Änderungen an `varphot/`, den Notebooks und `tools/`. Die Kurzfassung der Git-Regeln steht auch im
Notizsystem (basic-memory, `chat_rules.md` §8); hier ist die maßgebliche Fassung für das Repo.

## 1. Git: sauber halten, sofort committen

- Nach **jedem** Arbeitsschritt: Tests grün → logisch getrennte, kommentierte Commits (`feat:`, `fix:`, `docs:`,
  `chore:`, `wip:`) → Push `dev` → PR auf `main` → Merge → `dev` auf `main` setzen → `git status -sb` sauber,
  `main == dev == origin/*`. Keine liegen gebliebenen Branches oder unfertigen Dateien.
- Jeder Commit muss für sich importierbar sein und die Tests bestehen (Reihenfolge der Commits beachten).
- Kein `Co-Authored-By` und keine KI-Hinweise in Commit-Nachrichten oder Quelltext (Regel des Projekteigners).
- Vor einem Branchwechsel: Arbeitsbaum sauber? Ein veröffentlichtes Tag wird nie verschoben, ein neuer Stand bekommt
  eine neue Version.

## 2. Datenschutz: das Repo ist öffentlich

Keine persönlichen Daten im Repo (Koordinaten des Beobachtungsortes, AAVSO-Code, Adressen, Pfade mit Benutzernamen in
Ausgaben). Sie liegen in `PHOTOMETRIE_PY_DATA/observer.json` neben dem Repo (`varphot/observer.py`). Notebooks werden
ohne Zell-Ausgaben committet (nbstripout). Tests verwenden Dummywerte. Rohbilder und Ergebnisse gehören nicht ins Repo.

## 3. Dokumentation von Funktionen und Modulen

Jede Funktion, die ein **Messergebnis beeinflusst** (Photometrie, Fehler, Zeit, Astrometrie, Auswahl, Periode, Export),
bekommt einen Docstring mit diesen Abschnitten — in dieser Reihenfolge, auf Deutsch, knapp:

| Abschnitt | Inhalt |
|---|---|
| Kurzzeile | Was sie tut (ein Satz). |
| **Warum** | Das Problem, das sie löst; warum nicht der einfachere Weg. Bei Korrekturen: die beobachtete Auswirkung. |
| **Wie** | Verfahren und Formeln (mit Symbolen und Einheiten), wichtige Entscheidungen und Startwerte. |
| **Parameter / Rückgabe** | Typ, Einheit, Konvention (z. B. 0-basierte Pixel, Länge Ost +). |
| **Grenzen** | Annahmen, bekannte Fehlerfälle, wann man sie nicht benutzen darf. |
| **Validierung** | Test oder Datensatz, an dem sie geprüft wurde, mit Zahlen (z. B. „LCO δ Cep: Residuum 0,13 → 0,07 mag"). |
| **Quellen** | Autor(en) Jahr, Zeitschrift Band, Seite, DOI/URL. Vermerk, ob die Quelle **geprüft** oder „aus dem Gedächtnis, nicht geprüft" ist. Eigene Methoden als *eigene Methode* kennzeichnen. |

- **Wissenschaftliche Behauptungen brauchen eine Quelle** oder den ausdrücklichen Vermerk „Startwert/willkürlich".
  Koeffizienten, die aus dem Gedächtnis stammen, werden als solche markiert, bis sie gegen die Quelle geprüft sind.
- **Modulkopf:** Zweck des Moduls in 2–4 Sätzen, `Autor:` (Projektautor; KI-Unterstützung wird nicht eingetragen), Stand
  des Verfahrens, Verweis auf Notebook/Konzept-Kapitel.
- Private Hilfsfunktionen (`_name`) brauchen nur die Kurzzeile und, wenn nicht offensichtlich, das Warum.
- **Änderung eines Verfahrens = Änderung des Docstrings im selben Commit** (und Eintrag im `CHANGELOG.md`). Eine
  Korrektur, die einen Fehler behebt, nennt im Docstring den ursprünglichen Fehler (Beispiel: Sigma-Clipping in
  `ApertureStats`).

Musterbeispiele im Code: `varphot/batch.py` (`light_curve`, `measure_frame`, `scintillation_mag`),
`varphot/periodfit.py` (`harmonic_fit`).

## 4. Tests

- Jede Funktion mit Rechenlogik bekommt einen Test mit **bekannter Wahrheit** (synthetisches Bild/Zahlenbeispiel) —
  nicht nur „läuft durch". Gefundene Fehler bekommen einen **Regressionstest** im selben Commit.
- Netzwerk-Aufrufe werden in Tests gemockt oder aus Fixtures (`tests/data/`) bedient.
- Echte Datensätze (`tools/download_testdata.py`) dienen der Validierung in den Notebooks, nicht den Unit-Tests.

## 5. Zahlen und Aussagen

- Berichte nennen, was **nicht** geprüft ist, ebenso wie das Geprüfte. Willkürliche Schwellen (z. B. QC-Grenzen) heißen
  „Startwerte" und stehen in `CFG`, nicht im Code verstreut.
- Parameter, die an einem Datensatz gewählt wurden (z. B. Kernradius), werden als solche dokumentiert und nicht
  stillschweigend als allgemeingültig übernommen.
