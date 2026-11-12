"""Sofort-Hinweise unter den Formularen der Notebooks und Notebook-Header-Rendering.

render_nb_header() erzeugt den farbigen Workflow-Header am Anfang jedes Notebooks
(drei Schritt-Kacheln + „Ihr Fall"-Zeile). Aufruf z. B. in NB01:

    from IPython.display import HTML, display
    from varphot.hints import render_nb_header, CASES
    from varphot import Session
    display(HTML(render_nb_header("01", "Titel", "Ergebnis ...", SCHRITTE, Session.current().method)))


Warum: Eine Tabelle am Anfang orientiert, aber erst die **Rueckmeldung direkt nach der Auswahl** gibt dem Nutzer Sicherheit („das ist richtig so“) oder warnt („das passt nicht zusammen“). Jedes Formular
bekommt ein Hinweisfeld, das sich bei jeder Aenderung sofort aktualisiert.

Wie: Die Texte entstehen in reinen Funktionen (``nb00_hints`` usw.: Werte hinein, Liste ``(Stufe, Text)`` heraus — ohne Widgets, damit testbar). :func:`bind` haengt eine Funktion an ein HTML-Widget
und beobachtet die Felder; :func:`render` setzt die Liste in farbige Kaesten: ``ok`` gruen (passt), ``info`` blau (zur Orientierung), ``warn`` orange (pruefen), ``error`` rot (so geht es nicht).
Die Farben setzen Hintergrund und Schrift ausdruecklich, damit sie in hellen und dunklen Notebook-Designs lesbar bleiben.
"""
from __future__ import annotations

from typing import Callable, Iterable

Hint = tuple[str, str]
_STYLE = {
    "ok": ("#2e7d32", "#e8f5e9"),
    "info": ("#1565c0", "#e3f2fd"),
    "warn": ("#ef6c00", "#fff3e0"),
    "error": ("#c62828", "#ffebee"),
}


def render(items: Iterable[Hint]) -> str:
    """HTML der Hinweise (ein Kasten je Eintrag); leere Liste ergibt einen leeren Text."""
    out = []
    for level, text in items:
        bar, bg = _STYLE.get(level, _STYLE["info"])
        out.append(f'<div style="margin:4px 0;padding:6px 10px;border-left:4px solid {bar};background:{bg};color:#1b1b1b;font-size:13px">{text}</div>')
    return "".join(out)


def bind(panel, watched: Iterable, fn: Callable[[], Iterable[Hint]]) -> None:
    """Setzt ``panel.value`` (HTML-Widget) aus ``fn()`` und aktualisiert es bei jeder Aenderung der Felder in ``watched``. ``fn`` darf nie scheitern: Fehler werden als Hinweis angezeigt."""
    def _update(*_):
        try:
            panel.value = render(fn())
        except Exception as e:          # ein Hinweis darf das Formular nie blockieren
            panel.value = render([("warn", f"Hinweis nicht verfuegbar: {e}")])
    for w in watched:
        w.observe(_update, names="value")
    _update()


# ---------------------------------------------------------------- Notebook-Header

_STEP_COLORS = [
    ("#1565c0", "#e3f2fd"),   # Schritt 1 — blau
    ("#ef6c00", "#fff3e0"),   # Schritt 2 — orange
    ("#2e7d32", "#e8f5e9"),   # Schritt 3 — grün
]
_CASE_COLORS = {
    "mono":    ("#1565c0", "#e3f2fd"),
    "monorgb": ("#6a1b9a", "#f3e5f5"),
    "osc":     ("#2e7d32", "#e8f5e9"),
    "dslr":    ("#bf360c", "#fbe9e7"),
}


def render_nb_header(
    nb_num: str,
    title: str,
    ergebnis: str,
    schritte: list[tuple[str, str]],
    method: str | None = None,
) -> str:
    """Farbiger Workflow-Header für den Anfang eines Notebooks.

    ``schritte``: Liste von (Kurzname, Beschreibung) — genau 3 Einträge.
    ``method``: aktuelle Methode aus Session (``"mono"``, ``"osc"`` …) → hebt den passenden Fall hervor.
    Gibt einen HTML-String zurück, der mit ``display(HTML(...))`` angezeigt wird.
    """
    # --- Schritt-Kacheln
    tiles = ""
    for i, (name, desc) in enumerate(schritte[:3]):
        bar, bg = _STEP_COLORS[i % len(_STEP_COLORS)]
        tiles += (
            f'<div style="padding:12px 14px;background:{bg};border-radius:6px;border-top:3px solid {bar};">'
            f'<div style="font-weight:600;color:{bar};font-size:12px;margin-bottom:5px;">{name}</div>'
            f'<div style="font-size:12px;color:#1b1b1b;">{desc}</div>'
            f'</div>'
        )

    # --- „Ihr Fall"-Zeile (optional)
    fall_html = ""
    if method is not None:
        badges = ""
        for m, (letter, desc) in CASES.items():
            bar, bg = _CASE_COLORS.get(m, ("#555", "#eee"))
            if m == method:
                badges += (
                    f'<span style="display:inline-flex;align-items:center;gap:5px;'
                    f'padding:3px 10px 3px 6px;border-radius:14px;background:{bar};color:#fff;'
                    f'font-size:12px;font-weight:600;">'
                    f'<span style="display:inline-block;width:18px;height:18px;border-radius:50%;'
                    f'background:#fff;color:{bar};text-align:center;line-height:18px;font-weight:700;font-size:11px;">'
                    f'{letter}</span> {desc}</span> '
                )
            else:
                badges += (
                    f'<span style="display:inline-flex;align-items:center;gap:5px;'
                    f'padding:3px 10px 3px 6px;border-radius:14px;background:#e0e0e0;color:#757575;'
                    f'font-size:12px;opacity:0.7;">'
                    f'<span style="display:inline-block;width:18px;height:18px;border-radius:50%;'
                    f'background:#bdbdbd;color:#757575;text-align:center;line-height:18px;font-weight:700;font-size:11px;">'
                    f'{letter}</span> {desc}</span> '
                )
        fall_html = (
            f'<div style="margin-top:10px;padding:8px 12px;background:#f5f5f5;border-radius:6px;">'
            f'<span style="font-size:11px;font-weight:600;color:#757575;text-transform:uppercase;'
            f'letter-spacing:.5px;margin-right:8px;">Ihr Fall (aus NB00)</span>'
            f'<span style="display:inline-flex;flex-wrap:wrap;gap:6px;align-items:center;">{badges}</span>'
            f'</div>'
        )

    return (
        f'<div style="padding:16px 18px;border-radius:8px;background:#fafafa;'
        f'border:1px solid #e0e0e0;font-family:sans-serif;margin-bottom:4px;">'
        f'<div style="font-size:17px;font-weight:700;color:#1a1a2e;margin-bottom:5px;">'
        f'<span style="color:#9e9e9e;font-weight:400;font-size:13px;margin-right:6px;">NB{nb_num}</span>'
        f'{title}</div>'
        f'<div style="font-size:12px;color:#555;margin-bottom:12px;">'
        f'<b>Ergebnis:</b> {ergebnis}</div>'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">{tiles}</div>'
        f'{fall_html}'
        f'</div>'
    )


def render_camera_legend() -> str:
    """Erklärungs-HTML für den Unterschied zwischen Kamera-Profil und -Vorlage (NB00)."""
    return (
        '<div style="font-size:11px;color:#555;margin:2px 0 6px 0;line-height:1.6;">'
        '<b style="color:#2e7d32;">● Eigenes Profil</b> = in NB07 kalibriert (eigene Messwerte für Gain, Rauschen, Linearität) &nbsp;|&nbsp; '
        '<b style="color:#1565c0;">» Vorlage</b> = Herstellerwerte (Ausgangspunkt; NB07 noch ausstehend)'
        '</div>'
    )


# ---------------------------------------------------------------- NB00

CASES = {
    "mono": ("A", "Monochrom-Kamera + Standardfilter (V, B, R)"),
    "monorgb": ("B", "Monochrom-Kamera + RGB-Filterrad"),
    "osc": ("C", "Farbkamera (OSC, Bayer)"),
    "dslr": ("D", "DSLR / spiegellos (RAW, Bayer)"),
}
_MONO_METHODS = ("mono", "monorgb")


def nb00_hints(mode: str, method: str, filt: str, cam_kind: str, workspace: str = "") -> list[Hint]:
    """Hinweise zu Schritt 1 von NB00 (Modus, Methode, Meldefilter, Kamera)."""
    h: list[Hint] = []
    if mode == "lco":
        h.append(("ok", "<b>LCO-Testdaten:</b> Ziel δ Cep, Methode Monochrom + Standardfilter, Meldefilter V sind <b>vorgegeben</b> (grau) — nichts zu ändern. Sitzungsordner so lassen. Weiter mit der nächsten Zelle."))
        return h
    if mode == "demo":
        h.append(("info", "<b>Demo:</b> synthetische Probebilder — zeigt die Auswertung und die Warnungen. <b>Es wird nichts gespeichert.</b>"))
    elif mode == "real":
        ws = workspace or "&lt;Sitzungsordner&gt;"
        h.append(("info", f"<b>Eigene Probebilder:</b> legen Sie <b>vor der nächsten Zelle</b> 3 Messbilder nach <code>{ws}/probe/</code> und 1 scharfes Bild nach <code>{ws}/probe/scharf/</code> (Schritt 2c)."))
    if method in CASES:
        letter, name = CASES[method]
        h.append(("ok", f"<b>Fall {letter}:</b> {name}."))
    bayer_method = method in ("osc", "dslr")
    if filt in ("TG", "TB", "TR"):
        h.append(("info", f"<b>Meldefilter {filt}:</b> {'Grün' if filt == 'TG' else 'Blau' if filt == 'TB' else 'Rot'}kanal einer Farbkamera/eines RGB-Filters — "
                          "die Transformation auf V/B/R kommt später mit NB08."))
    elif filt in ("V", "B", "R"):
        h.append(("info", f"<b>Meldefilter {filt}:</b> Messung im Standardband {filt}."))
    if method == "mono" and filt in ("TG", "TB", "TR"):
        h.append(("warn", "Fall A (Standardfilter) meldet normalerweise <b>V, B oder R</b> — TG/TB/TR gehört zu Farbkamera/RGB-Filter."))
    if method in ("monorgb", "osc", "dslr") and filt in ("V", "B", "R"):
        h.append(("warn", "RGB-Filter/Farbkamera melden untransformiert <b>TG/TB/TR</b>; V/B/R nur mit Transformation (NB08)."))
    if cam_kind:
        if method in _MONO_METHODS and cam_kind != "Mono":
            h.append(("error", f"Die Kamera ist <b>{cam_kind}</b>, die Methode verlangt eine <b>Monochrom</b>-Kamera. Andere Kamera oder andere Methode wählen."))
        elif bayer_method and cam_kind == "Mono":
            h.append(("error", "Die Kamera ist <b>Mono</b>, die Methode verlangt eine <b>Farbkamera (Bayer)</b>. Andere Kamera oder andere Methode wählen."))
        else:
            h.append(("ok", f"Kamera: <b>{cam_kind}</b> — passt zur Methode."))
    return h


def nb00_observer_hints(site_name: str, is_test_site: bool, is_new: bool, aavso_code: str, cam_label: str, cam_kind: str) -> list[Hint]:
    """Hinweise zum Formular „Beobachter, Standort, Kamera“ (Schritt 0b)."""
    h: list[Hint] = []
    if is_test_site:
        h.append(("ok", "<b>Testdaten-Standort:</b> fest vorgegeben — <b>nichts ändern, nicht speichern</b>, wenn Sie nur die Testdaten ausprobieren."))
    elif is_new:
        h.append(("info", "<b>Neuer Standort:</b> Name, Breite (° N), Länge (° O; West = −) und Höhe eintragen, dann unten <b>Speichern</b>."))
    else:
        h.append(("ok", f"Standort <b>{site_name}</b> ist gespeichert."))
    code = (aavso_code or "").strip()
    if code:
        h.append(("ok", f"Beobachtercode <b>{code}</b> geht in Dateien mit <i>eigenen</i> Beobachtungen; Testdaten gehen immer als <code>TST01</code> hinaus."))
    else:
        h.append(("warn", "Kein Beobachtercode: echte Exportdateien bekommen erst mit Code den richtigen <code>OBSCODE</code> (Testdaten gehen als <code>TST01</code>)."))
    if cam_kind:
        fall = {"Mono": "Fall A oder B (Mono)", "Farbe (DSLR)": "Fall D (DSLR)"}.get(cam_kind, "Fall C (Farbkamera)")
        h.append(("info", f"Kamera <b>{cam_label}</b>: {cam_kind} — passt zu {fall}."))
    return h


# ---------------------------------------------------------------- NB01

def nb01_hints(cal: str, siril_found: bool, method: str, ref: str, ref_exists: bool, radius: float, gaia_fill: bool, gaia_check: bool, lco: bool = False) -> list[Hint]:
    """Hinweise zum Formular von NB01 (Kalibrierung, Referenzbild, ASTAP, Gaia)."""
    h: list[Hint] = []
    if cal == "run":
        if siril_found:
            extra = " Farbkamera/DSLR: im CFA-Bereich, ohne Debayern." if method in ("osc", "dslr") else ""
            h.append(("ok", f"<b>Siril läuft automatisch</b> (Bias, Dunkel, Flat, Lights → <code>process/</code>); je nach Bildzahl Minuten.{extra}"))
        else:
            h.append(("error", "<b>Siril wurde nicht gefunden.</b> „Skript nur erzeugen“ wählen (und in Siril selbst ausführen) oder Siril installieren."))
        if lco:
            h.append(("warn", "Testdaten sind schon kalibriert — hier besser <b>„Bilder sind schon kalibriert“</b> wählen."))
    elif cal == "script":
        h.append(("info", "Es wird nur <code>scripts/calibrate.ssf</code> erzeugt. In Siril ausführen (Arbeitsordner = Sitzungsordner), danach hier <b>erneut ab „Ab hier automatisch“</b>."))
    elif cal == "done":
        h.append(("ok", "<b>Es wird nichts kalibriert:</b> die Bilder müssen schon kalibriert im Bilderordner liegen." + (" (Testdaten: passt.)" if lco else "")))
    if (ref or "").strip():
        h.append(("ok", "Eigenes Referenzbild gefunden.") if ref_exists else ("error", "Das angegebene <b>Referenzbild existiert nicht</b> — Pfad prüfen oder Feld leeren."))
    else:
        h.append(("info", "Referenzbild: automatisch (scharfes Bild aus NB00, sonst das beste der Reihe)."))
    if radius > 10.0:
        h.append(("info", f"ASTAP-Suchradius {radius:g}°: sinnvoll bei Weitfeld; kostet Zeit."))
    if not gaia_fill:
        h.append(("warn", "Ohne Gaia-Auffüllung bleibt es bei der AAVSO-Sequenz — bei kleinem Feld können zu wenige Comps übrig sein."))
    if not gaia_check:
        h.append(("warn", "Ohne Gaia-Gegenprüfung bleiben WCS-Fehler und falsche Sequenzsterne unbemerkt."))
    return h


# ---------------------------------------------------------------- NB02

def nb02_hints(wcs: str, ap: str, ap_r: int, core_r: float, pmin: str, pmax: str, aperture_m: str, plan_ap: bool) -> list[Hint]:
    """Hinweise zum Formular von NB02 (WCS, Apertur, Kernmaske, Periode, Öffnung)."""
    h: list[Hint] = []
    h.append(("ok" if wcs == "auto" else "info", {
        "auto": "<b>WCS automatisch:</b> aus dem Bildkopf, sonst per Registrierung auf das Referenzbild (richtig für fast alle Fälle).",
        "header": "<b>Nur Bildkopf:</b> Bilder ohne gültige WCS fallen aus. Eigene Bilder nach Siril haben meist keine — dann <i>automatisch</i> wählen.",
        "register": "<b>Immer Registrierung:</b> jedes Bild wird auf das Referenzbild ausgerichtet (langsamer, unabhängig vom Kopf).",
    }.get(wcs, "")))
    if ap == "manual":
        h.append(("warn", f"<b>Manuelle Apertur {ap_r} px</b> gilt für alle Bilder — nur zum Vergleich; die Wahl aus dem Plan folgt dem Seeing."))
    else:
        h.append(("ok", "<b>Apertur:</b> " + ("aus dem Plan (NB00)." if plan_ap else "aus dem Referenzbild (Wachstumskurve, S/N).")))
    if core_r and core_r > 0:
        h.append(("ok", f"<b>Kernmaske {core_r:g} px:</b> gleicht Sättigungsverlust im Kern aus (nur sinnvoll bei gesättigtem Ziel)."))
    else:
        h.append(("info", "<b>Kernmaske aus:</b> in Ordnung, wenn das Ziel <b>nicht</b> gesättigt ist."))
    try:
        if pmin.strip() and pmax.strip() and float(pmin.replace(",", ".")) >= float(pmax.replace(",", ".")):
            h.append(("error", "<b>Periode von</b> muss kleiner sein als <b>Periode bis</b>."))
    except ValueError:
        h.append(("error", "Periodenangaben müssen Zahlen sein (Tage, z. B. 5,3)."))
    if not aperture_m.strip():
        h.append(("info", "Ohne Teleskopöffnung fehlt der Szintillationsterm im Fehlerbudget (Fehler etwas zu klein bei hellen Sternen)."))
    return h


# ---------------------------------------------------------------- NB03

def nb03_hints(real: bool, aavso_code: str, mode: str, band: str, tf_file: str, ai: bool, lco: bool = False) -> list[Hint]:
    """Hinweise zum Formular von NB03 (eigene Daten, Betriebsart, Transformation, KI)."""
    h: list[Hint] = []
    code = (aavso_code or "").strip()
    if real:
        if code:
            h.append(("ok", f"<b>Eigene Beobachtungen:</b> Beobachtercode <b>{code}</b> geht in die Datei."))
        else:
            h.append(("error", "<b>Eigene Beobachtungen, aber kein Beobachtercode.</b> Zuerst in NB00 (Schritt 0b) den AAVSO-Code eintragen und speichern."))
        if lco:
            h.append(("warn", "Das sind <b>LCO-Testdaten</b> — Häkchen entfernen, sonst wird die Datei mit Ihrem Code gekennzeichnet."))
    else:
        h.append(("ok", "<b>Testdaten:</b> Die Datei bekommt den Code <code>TST01</code> und den Namenszusatz <code>…_TESTDATEN_NICHT_EINREICHEN</code>."))
    if mode == "transformiert":
        if not (tf_file or "").strip():
            h.append(("error", "<b>Transformiert</b> braucht die Transformationsdatei aus NB08 (Feld „Transformationsdatei“)."))
        else:
            h.append(("ok", f"<b>Transformiert:</b> Band {band}, Werte mit <code>TRANS=YES</code>."))
    else:
        h.append(("info", "<b>Untransformiert:</b> Mono meldet V/B/R, Farbkameras <code>TG</code>/<code>TB</code>/<code>TR</code> mit <code>TRANS=NO</code>."))
    if ai:
        h.append(("info", "<b>KI-Zweitlesung:</b> lokale KI liest gegen (bis ca. 2 Minuten). Ohne erreichbaren KI-Weg läuft der Bericht trotzdem."))
    else:
        h.append(("info", "Ohne KI-Zweitlesung: der Bericht wird nur regelbasiert geprüft."))
    return h
