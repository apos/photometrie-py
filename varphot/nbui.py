"""Bausteine für die Darstellung der Notebooks: Schrittleiste, Schrittkarte, abhakbare Aufgaben, Kacheln, Aufbau-Karten, Hinweise.

Autor: Axel Pospischil. Stand 2026-11-12.

Warum: Die Anleitungen standen als lange Markdown-Texte und breite Tabellen in den Notebooks (unruhig, kaum lesbar). Dieses Modul erzeugt aus knappen Angaben einheitliche HTML-Karten,
die in Jupyter und Datalore gleich aussehen. Alles ist reines HTML mit festen Farben und etwas CSS, ohne Skript: Das Abhaken (Klick färbt die Aufgabe grün) läuft über Checkboxen.

Benutzung in einer Notebook-Zelle::

    from varphot.nbui import step, tasks, tiles, cases, note, show
    show(step("00", 4, "Probebilder aufnehmen", meta=[("Wo", "Am Teleskop")], blocks=[tasks(["3 Messbilder aufnehmen"])]))

Texte dürfen ``**fett**`` und ```code``` enthalten. Der Haken liegt nur in der Anzeige und geht beim erneuten Ausführen der Zelle verloren.
"""
from __future__ import annotations

import re
from html import escape

STEPS = {
    "00": ["Einrichtung", "Fall, Ziel", "Sichtbarkeit", "Probebilder", "Auswertung", "Empfehlung", "Plan"],
    "07": ["Kamera", "Bilder", "Offset", "Gain", "Linearität", "Dunkelstrom", "Ergebnis"],
    "08": ["Eingaben", "Katalog", "Koeffizienten", "Gütetest", "Speichern"],
}
CARD_PREFIX = "from varphot import nbui as ui\n\nui.show("
"""Jede reine Karten-Zelle beginnt so; Tests und Vorschau erkennen daran, welche Zellen allein lauffähig sind."""
SHORT_CASES = {"mono": ("A", "Mono + Filter"), "monorgb": ("B", "Filterrad"), "osc": ("C", "Farbkamera"), "dslr": ("D", "DSLR")}

TEXT, MUTED, FAINT, LINE, SURF = "#1b1b1b", "#5f6368", "#666666", "#d9d9d9", "#f5f5f4"
ACC, ACC_BG, OK, OK_BG, OK_LINE, OK_TX = "#1565c0", "#e3f2fd", "#2e7d32", "#e8f5e9", "#a5d6a7", "#1b5e20"
NOTE = {"info": (ACC_BG, "#0d47a1", "#90caf9", "info"), "warn": ("#fff3e0", "#7a3d00", "#ffcc80", "alert"),
        "ok": (OK_BG, OK_TX, OK_LINE, "check"), "error": ("#ffebee", "#8e1b1b", "#ef9a9a", "alert")}

CONTRAST_PAIRS = [("Text auf Weiß", TEXT, "#ffffff"), ("Zusatztext auf Weiß", MUTED, "#ffffff"), ("Zusatztext auf Fläche", MUTED, SURF), ("Blasser Text auf Weiß", FAINT, "#ffffff"),
                  ("Blasser Text auf Fläche", FAINT, SURF), ("Erledigt-Text", OK_TX, OK_BG), ("Haken-Kreis", OK, OK_BG), ("Aktiver Schritt", "#ffffff", ACC), ("Hinweis Info", NOTE["info"][1], NOTE["info"][0]),
                  ("Hinweis Warnung", NOTE["warn"][1], NOTE["warn"][0]), ("Hinweis Ok", NOTE["ok"][1], NOTE["ok"][0]), ("Hinweis Fehler", NOTE["error"][1], NOTE["error"][0]),
                  ("Kachel hervorgehoben", "#0d47a1", ACC_BG), ("Kennzahl Zusatz ok", OK_TX, "#ffffff"), ("Kennzahl Zusatz Warnung", "#7a3d00", "#ffffff"),
                  ("Kennzahl Zusatz Fehler", "#8e1b1b", "#ffffff"), ("Tabellenkopf", MUTED, SURF), ("Meldung ohne Rahmen", TEXT, "#ffffff"), ("Platzhalter in der Vorschau", "#0d47a1", ACC_BG)]
"""Alle verwendeten Text/Hintergrund-Paare; ``tests/test_nbui.py`` verlangt für jedes mindestens WCAG AA (Kontrast 4,5)."""

_PATHS = {
    "photo": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M21 16l-5-5-8 8"/>',
    "focus": '<circle cx="12" cy="12" r="3"/><path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/>',
    "chart": '<path d="M4 19V5M4 19h16M8 15l4-5 3 3 4-6"/>',
    "check": '<path d="M5 12l5 5L20 7"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M11 12h1v5h1"/>',
    "star": '<path d="M12 4l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z"/>',
}

CSS = f"""<style>
.vp-t{{position:relative;display:flex;gap:10px;align-items:flex-start;padding:9px 12px;border:1px solid {LINE};border-radius:8px;cursor:pointer;margin:0 0 6px;background:#fff;color:{TEXT};font:14px/1.5 sans-serif}}
.vp-t input{{position:absolute;opacity:0;pointer-events:none}}
.vp-t .b{{width:20px;height:20px;border-radius:50%;border:2px solid #8a8a8a;flex:none;margin-top:1px;box-sizing:border-box;color:#fff;display:flex;align-items:center;justify-content:center}}
.vp-t .b svg{{opacity:0}}
.vp-t input:checked+.b{{background:{OK};border-color:{OK}}}
.vp-t input:checked+.b svg{{opacity:1}}
.vp-t input:checked~.x{{color:{OK_TX}}}
.vp-t:has(input:checked){{background:{OK_BG};border-color:{OK_LINE}}}
.vp-t:hover{{border-color:#666666}}
.vp-t .s{{display:block;font-size:12px;color:{MUTED};margin-top:2px}}
.vp-d summary{{cursor:pointer;font-weight:500}}
</style>"""


def _md(t: str) -> str:
    """Kleinstes Markdown: **fett**, *kursiv*, `code`; sonst wird der Text als HTML übernommen."""
    t = re.sub(r"`([^`]+)`", r'<code style="background:#eceff1;padding:1px 5px;border-radius:4px;font-size:12px">\1</code>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return re.sub(r"(?<![\w*])\*(?=\S)([^*\n]*\S)\*(?![\w*])", r"<i>\1</i>", t)


def icon(name: str, size: int = 22, color: str = "currentColor") -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true">{_PATHS[name]}</svg>')


def _wrap(inner: str) -> str:
    return f'<div style="font:14px/1.5 sans-serif;color:{TEXT};margin:4px 0">{CSS}{inner}</div>'


def show(*html: str) -> None:
    """Zeigt die Bausteine in der Notebook-Zelle an."""
    from IPython.display import HTML, display
    display(HTML(_wrap("".join(html))))


def stepper(nb: str, current: int | None = None) -> str:
    """Schrittleiste: Schritte vor ``current`` grün mit Haken, ``current`` blau, spätere grau; ohne ``current`` alle grau."""
    names = STEPS.get(nb)
    if not names:
        return ""
    cells = []
    for i, name in enumerate(names, 1):
        if current is not None and i < current:
            dot = f'<div style="width:26px;height:26px;border-radius:50%;margin:0 auto 4px;background:{OK_BG};color:{OK};border:1px solid {OK_LINE};display:flex;align-items:center;justify-content:center;box-sizing:border-box">{icon("check", 14)}</div>'
            lab = f'<div style="font-size:12px;color:{MUTED}">{escape(name)}</div>'
        elif i == current:
            dot = f'<div style="width:26px;height:26px;border-radius:50%;margin:0 auto 4px;background:{ACC};color:#fff;font-size:13px;font-weight:600;line-height:26px">{i}</div>'
            lab = f'<div style="font-size:12px;font-weight:600">{escape(name)}</div>'
        else:
            dot = f'<div style="width:26px;height:26px;border-radius:50%;margin:0 auto 4px;background:{SURF};border:1px solid #bdbdbd;color:{FAINT};font-size:13px;line-height:24px;box-sizing:border-box">{i}</div>'
            lab = f'<div style="font-size:12px;color:{FAINT}">{escape(name)}</div>'
        cells.append(f'<div style="flex:1;text-align:center;min-width:0">{dot}{lab}</div>')
    return f'<div style="display:flex;align-items:flex-start;padding:12px 8px 4px">{"".join(cells)}</div>'


def para(text: str) -> str:
    return f'<p style="margin:0 0 10px;color:{MUTED};font-size:14px;line-height:1.55">{_md(text)}</p>'


def body(*blocks: str) -> str:
    """Innenabstand für Bausteine, die direkt in einer Ergebniskarte (:func:`result`, :func:`panel`) stehen und nicht in einer Schrittkarte."""
    return f'<div style="padding:10px 16px 8px">{"".join(blocks)}</div>'


def note(kind: str, text: str) -> str:
    bg, fg, line, ic = NOTE[kind]
    return (f'<div style="display:flex;gap:10px;align-items:flex-start;margin:8px 0;padding:10px 12px;border-radius:8px;background:{bg};color:{fg};border:1px solid {line};font-size:13px;line-height:1.5">'
            f'<span style="flex:none;margin-top:1px">{icon(ic, 18)}</span><span>{_md(text)}</span></div>')


def tasks(items: list, group: str = "") -> str:
    """Abhakbare Aufgaben. Eintrag: ``"Text"``, ``("Text", "Zusatz")`` oder ``("Text", "Zusatz", True)`` (vorab abgehakt)."""
    out = []
    for it in items:
        text, sub, checked = (it, "", False) if isinstance(it, str) else (tuple(it) + ("", False))[:3]
        s = f'<span class="s">{_md(sub)}</span>' if sub else ""
        out.append(f'<label class="vp-t"><input type="checkbox"{" checked" if checked else ""}><span class="b">{icon("check", 13)}</span><span class="x">{_md(text)}{s}</span></label>')
    return f'<div style="margin:6px 0 10px">{"".join(out)}</div>'


def tiles(items: list, cols: int | None = None) -> str:
    """Kacheln. Eintrag: ``(Symbol, Titel, Zusatz[, hervorgehoben])``; Symbol aus :func:`icon` oder leer."""
    cols = cols or min(len(items), 4)
    out = []
    for it in items:
        sym, title, sub = it[:3]
        hot = len(it) > 3 and it[3]
        bg, line, fg, fg2 = (ACC_BG, "#90caf9", "#0d47a1", "#0d47a1") if hot else ("#fff", LINE, TEXT, MUTED)
        ic = f'<div style="color:{fg2};margin-bottom:2px">{icon(sym, 22)}</div>' if sym else ""
        out.append(f'<div style="border:1px solid {line};border-radius:8px;padding:10px 8px;text-align:center;background:{bg}">{ic}'
                   f'<div style="font-size:13px;font-weight:600;color:{fg}">{_md(title)}</div><div style="font-size:12px;color:{fg2}">{_md(sub)}</div></div>')
    return f'<div style="display:grid;grid-template-columns:repeat({cols},minmax(0,1fr));gap:8px;margin:6px 0 12px">{"".join(out)}</div>'


def cases(active: str | None, texts: dict[str, str], title: str = "Ihr Aufbau") -> str:
    """Vier Karten A bis D mit je einem Satz; ``active`` (``mono``/``monorgb``/``osc``/``dslr``) wird grün hervorgehoben."""
    out = []
    for key, (letter, name) in SHORT_CASES.items():
        on = key == active
        bg, fg, line = (OK_BG, OK_TX, OK_LINE) if on else (SURF, FAINT, "#e0e0e0")
        mark = ' <span style="font-weight:400">· Ihr Fall</span>' if on else ""
        out.append(f'<div style="border-radius:8px;padding:8px 10px;background:{bg};color:{fg};border:1px solid {line};font-size:12px;line-height:1.45">'
                   f'<b style="font-weight:600">{letter} {name}</b>{mark}<br>{_md(texts.get(key, ""))}</div>')
    head = f'<div style="font-size:13px;font-weight:600;margin:6px 0">{escape(title)}</div>' if title else ""
    return f'{head}<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-bottom:12px">{"".join(out)}</div>'


def fields(rows: list[tuple[str, str, str]], heads: tuple[str, str] = ("Testlauf", "Eigene Aufnahmen")) -> str:
    """Formularfelder: je Feld eine Zeile mit Name und zwei kurzen Zeilen (Testlauf, eigene Aufnahmen), statt einer breiten Tabelle."""
    out = []
    for name, test, own in rows:
        out.append(f'<div style="padding:9px 0;border-top:1px solid {LINE}"><div style="font-size:14px;font-weight:600;margin-bottom:3px">{_md(name)}</div>'
                   f'<div style="display:grid;grid-template-columns:110px 1fr;gap:2px 10px;font-size:13px"><span style="color:{FAINT}">{escape(heads[0])}</span><span>{_md(test)}</span>'
                   f'<span style="color:{FAINT}">{escape(heads[1])}</span><span>{_md(own)}</span></div></div>')
    return f'<div style="margin:4px 0 8px">{"".join(out)}</div>'


def kv(rows: list[tuple[str, str]], key_width: int = 130) -> str:
    """Zwei Spalten ohne Tabelle: links Name, rechts Text, getrennt durch dünne Linien."""
    out = "".join(f'<div style="display:grid;grid-template-columns:{key_width}px 1fr;gap:10px;padding:7px 0;border-top:1px solid {LINE};font-size:13px"><b style="font-weight:600">{_md(k)}</b><span>{_md(v)}</span></div>'
                  for k, v in rows)
    return f'<div style="margin:4px 0 8px">{out}</div>'


def numbered(items: list[str]) -> str:
    """Nummerierte Zeilen (Reihenfolge wichtig, kein Abhaken)."""
    out = "".join(f'<div style="display:flex;gap:10px;padding:6px 0;border-top:1px solid {LINE};font-size:14px"><span style="width:20px;height:20px;border-radius:50%;background:{SURF};'
                  f'font-size:12px;line-height:20px;text-align:center;flex:none">{i}</span><span>{_md(t)}</span></div>' for i, t in enumerate(items, 1))
    return f'<div style="margin:4px 0 8px">{out}</div>'


def code(text: str) -> str:
    return f'<pre style="font:12px/1.6 monospace;background:{SURF};border-radius:8px;padding:8px 12px;margin:6px 0 10px;white-space:pre-wrap;color:{TEXT}">{escape(text)}</pre>'


def chips(items: list[str]) -> str:
    out = "".join(f'<span style="padding:3px 10px;border-radius:999px;border:1px solid #bdbdbd;color:{MUTED};font-size:12px;margin-right:6px">{_md(t)}</span>' for t in items)
    return f'<div style="margin:6px 0 10px">{out}</div>'


def details(summary: str, inner: str, open_: bool = False) -> str:
    return (f'<details class="vp-d"{" open" if open_ else ""} style="border-top:1px solid {LINE};padding-top:8px;margin-top:8px"><summary>{_md(summary)}</summary>'
            f'<div style="margin-top:8px">{inner}</div></details>')


def step(nb: str, num: int | str | None, title: str, *, tag: str = "", meta: list[tuple[str, str]] = (), intro: str = "", blocks: list[str] = (), bar: bool = True) -> str:
    """Schrittkarte: optional Schrittleiste, Kopf mit Nummer und Titel, Kennzahlen (``meta``), Einleitung und beliebige Bausteine.

    ``num`` ist ``4`` oder ``"1.2"`` (Unterschritt) oder ``None`` (Karte ohne Nummer); die Leiste hebt den Hauptschritt hervor. ``tag`` steht rechts im Kopf, z. B. ``"einmalig"``.
    """
    main = int(str(num).split(".")[0]) if num is not None and str(num).split(".")[0].isdigit() else None
    top = stepper(nb, main) if bar and main else ""
    chip = (f'<span style="font-size:12px;padding:2px 8px;border-radius:8px;background:#fff;border:1px solid {LINE};color:{MUTED}">{escape(tag)}</span>' if tag else "")
    m = ""
    if meta:
        cells = "".join(f'<div style="padding:9px 14px;{"border-left:1px solid " + LINE + ";" if i else ""}"><div style="font-size:12px;color:{MUTED}">{escape(k)}</div>'
                        f'<div style="font-size:14px;font-weight:600">{_md(v)}</div></div>' for i, (k, v) in enumerate(meta))
        m = f'<div style="display:grid;grid-template-columns:repeat({len(meta)},minmax(0,1fr));border-bottom:1px solid {LINE}">{cells}</div>'
    body = (para(intro) if intro else "") + "".join(blocks)
    badge = (f'<span style="min-width:28px;height:28px;padding:0 6px;box-sizing:border-box;border-radius:14px;background:{ACC};color:#fff;font-weight:600;font-size:14px;line-height:28px;text-align:center">{escape(str(num))}</span>'
             if num is not None else "")
    return (f'{top}<div style="border:1px solid {LINE};border-radius:12px;background:#fff;overflow:hidden;margin:6px 0">'
            f'<div style="display:flex;align-items:center;gap:10px;padding:11px 16px;background:{SURF};border-bottom:1px solid {LINE}">'
            f'{badge}'
            f'<span style="font-size:16px;font-weight:600;flex:1">{_md(title)}</span>{chip}</div>{m}<div style="padding:12px 16px 8px">{body}</div></div>')


def header(nb: str, title: str, ergebnis: str, *, wann: str = "", flow: list[tuple[str, str]] = (), blocks: list[str] = (), method: str | None = None, texts: dict[str, str] | None = None, fall_title: str = "Ihr Fall (aus NB00)") -> str:
    """Kopf eines Notebooks: Titel, Wann/Ergebnis, entweder ``flow`` (drei Kacheln Formular/Prüfen/Automatisch) oder die Schrittleiste, weitere Bausteine, Zeile „Ihr Fall“."""
    sub = (f'<div style="font-size:13px;color:{MUTED};margin-bottom:3px"><b>Wann:</b> {_md(wann)}</div>' if wann else "")
    res = f'<div style="font-size:13px;color:{MUTED};margin-bottom:10px"><b>Ergebnis:</b> {_md(ergebnis)}</div>'
    colors = [(ACC, ACC_BG), ("#ef6c00", "#fff3e0"), (OK, OK_BG)]
    fl = ""
    if flow:
        t = "".join(f'<div style="padding:11px 13px;background:{bg};border-radius:8px;border-top:3px solid {bar}"><div style="font-weight:600;color:{bar};font-size:12px;margin-bottom:4px">{escape(n)}</div>'
                    f'<div style="font-size:12px">{_md(d)}</div></div>' for (n, d), (bar, bg) in zip(flow, colors))
        fl = f'<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:8px">{t}</div>'
    elif STEPS.get(nb):
        fl = stepper(nb)
    fall = cases(method, texts, fall_title) if (method is not None and texts) else ""
    return (f'<div style="padding:14px 16px;border:1px solid {LINE};border-radius:12px;background:#fff;margin-bottom:6px">'
            f'<div style="font-size:18px;font-weight:700;margin-bottom:4px"><span style="color:{FAINT};font-weight:400;font-size:13px;margin-right:6px">NB{nb}</span>{_md(title)}</div>'
            f'{sub}{res}{fl}{"".join(blocks)}{fall}</div>')


TONES = {"ok": OK, "warn": "#ef6c00", "error": "#c62828", "info": ACC, "none": "#9e9e9e"}


def _num(v) -> str:
    """Zahl für Tabellen: ganze Zahlen ohne Nachkommastellen, sonst bis zu drei Stellen mit Komma, leer als Strich."""
    try:
        import math
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "–"
    except Exception:
        pass
    if isinstance(v, (int,)) or (hasattr(v, "is_integer") and not isinstance(v, bool) and float(v).is_integer() and abs(float(v)) < 1e15):
        return str(int(v))
    if isinstance(v, float) or hasattr(v, "__float__") and not isinstance(v, (str, bool)):
        return f"{float(v):.3f}".rstrip("0").rstrip(".").replace(".", ",")
    return escape(str(v))


def result(kind: str, title: str, right: str = "", blocks: list[str] = ()) -> str:
    """Ergebniskarte mit farbigem Statuskopf (``ok``, ``warn``, ``error``, ``info``), Titel links, Zusatz rechts und beliebigen Bausteinen darunter."""
    bg, fg, line, ic = NOTE[kind]
    head = (f'<div style="display:flex;align-items:center;gap:10px;padding:11px 16px;background:{bg};color:{fg};border-bottom:1px solid {line}">'
            f'<span style="flex:none">{icon(ic, 20)}</span><span style="flex:1;font-size:15px;font-weight:600">{_md(title)}</span>'
            f'<span style="font-size:13px">{_md(right)}</span></div>')
    return f'<div style="border:1px solid {LINE};border-radius:12px;background:#fff;overflow:hidden;margin:6px 0 12px">{head}{"".join(blocks)}</div>'


def panel(title: str, blocks: list[str] = (), right: str = "") -> str:
    """Neutrale Karte mit grauem Kopfband für zusammengehörige Ergebnisse."""
    head = (f'<div style="display:flex;gap:10px;padding:11px 16px;background:{SURF};border-bottom:1px solid {LINE}"><span style="flex:1;font-size:15px;font-weight:600">{_md(title)}</span>'
            f'<span style="font-size:13px;color:{MUTED}">{_md(right)}</span></div>')
    return f'<div style="border:1px solid {LINE};border-radius:12px;background:#fff;overflow:hidden;margin:6px 0 12px">{head}{"".join(blocks)}</div>'


def stats(items: list, cols: int | None = None) -> str:
    """Kennzahl-Kacheln in einer Reihe. Eintrag: ``(Bezeichnung, Wert, Zusatz[, Ton])``; Ton ``ok``/``warn``/``error`` färbt den Zusatz."""
    cols = cols or min(len(items), 4)
    cells = []
    for i, it in enumerate(items):
        label, value, sub = it[:3]
        tone = it[3] if len(it) > 3 else None
        col = {"ok": OK_TX, "warn": "#7a3d00", "error": "#8e1b1b"}.get(tone, MUTED)
        cells.append(f'<div style="padding:12px 14px;{"border-left:1px solid " + LINE + ";" if i % cols else ""}{"border-top:1px solid " + LINE + ";" if i >= cols else ""}">'
                     f'<div style="font-size:12px;color:{MUTED}">{_md(label)}</div><div style="font-size:18px;font-weight:600">{_md(value)}</div>'
                     f'<div style="font-size:12px;color:{col}">{_md(sub)}</div></div>')
    return f'<div style="display:grid;grid-template-columns:repeat({cols},minmax(0,1fr))">{"".join(cells)}</div>'


def status_rows(rows: list) -> str:
    """Statuszeilen mit Punkt. Eintrag: ``(Ton, Titel, Etikett, Text)``; Ton ``ok``/``warn``/``error``/``none`` (grau = optional/nicht vorhanden)."""
    out = []
    for i, (tone, title, tag, text) in enumerate(rows):
        t = f'<span style="font-weight:400;color:{MUTED}"> · {_md(tag)}</span>' if tag else ""
        d = f'<div style="font-size:13px;color:{MUTED};margin-top:1px">{_md(text)}</div>' if text else ""
        out.append(f'<div style="display:flex;gap:10px;align-items:flex-start;padding:9px 16px;{"border-top:1px solid " + LINE if i else ""}">'
                   f'<span style="width:10px;height:10px;border-radius:50%;background:{TONES[tone]};margin-top:6px;flex:none"></span>'
                   f'<div style="flex:1"><div style="font-size:14px;font-weight:600">{_md(title)}{t}</div>{d}</div></div>')
    return f'<div>{"".join(out)}</div>'


def bars(rows: list, head: str = "") -> str:
    """Rangliste mit Balken. Eintrag: ``(Name, Wert, Maximum, Wert-Text, Zusatz, Ton)``; Ton ``ok``/``warn``/``none``; ``none`` zeigt statt des Balkens den Zusatz in Grau."""
    out = []
    for name, value, vmax, vtext, side, tone in rows:
        if tone == "none":
            mid = f'<span style="color:{FAINT}">{_md(side)}</span>'
            out.append(f'<span style="color:{FAINT}">{_md(name)}</span>{mid}<span style="color:{FAINT}">{_md(vtext)}</span><span></span>')
            continue
        w = 0 if not vmax else max(2, min(100, round(100 * value / vmax)))
        colr = {"ok": OK, "warn": "#ef6c00"}[tone]
        out.append(f'<span style="font-weight:600">{_md(name)}</span><div style="height:10px;border-radius:5px;background:{SURF}"><div style="width:{w}%;height:10px;border-radius:5px;background:{colr}"></div></div>'
                   f'<span>{_md(vtext)}</span><span style="color:{MUTED}">{_md(side)}</span>')
    h = f'<div style="font-size:13px;font-weight:600;margin-bottom:8px">{_md(head)}</div>' if head else ""
    return (f'<div style="padding:10px 16px 6px;border-top:1px solid {LINE}">{h}<div style="display:grid;grid-template-columns:130px 1fr 60px 80px;gap:6px 10px;align-items:center;font-size:13px;margin-bottom:6px">'
            f'{"".join(out)}</div></div>')


def table(df, *, max_rows: int | None = 30, index: bool | None = None, row_tone=None) -> str:
    """Gestaltete Tabelle aus einem pandas-DataFrame (oder einer Series): Kopfband, Linien, rechtsbündige Zahlen, ✓/✗ für Wahrheitswerte.

    ``index``: Zeilenindex als erste Spalte zeigen (Standard: nur wenn er benannt oder kein einfacher Zähler ist). ``row_tone``: Funktion Zeile → ``ok``/``warn``/``error``/``None`` für farbige Zeilen.
    """
    import pandas as pd
    if isinstance(df, pd.Series):
        df = df.to_frame("Wert")
        index = True if index is None else index
    default_index = isinstance(df.index, pd.RangeIndex) and df.index.name is None
    if index or (index is None and not default_index):
        df = df.reset_index()
    total = len(df)
    shown = df if max_rows is None else df.head(max_rows)
    numeric = [pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c]) for c in df.columns]
    head = "".join(f'<th style="padding:7px 12px;font-weight:600;font-size:12px;color:{MUTED};text-align:{"right" if n else "left"};white-space:nowrap">{escape(str(c))}</th>' for c, n in zip(df.columns, numeric))
    rows = []
    for _, r in shown.iterrows():
        tone = row_tone(r) if row_tone else None
        bg = {"ok": OK_BG, "warn": NOTE["warn"][0], "error": NOTE["error"][0]}.get(tone, "#fff")
        cells = []
        for v, n in zip(r.tolist(), numeric):
            if isinstance(v, bool) or type(v).__name__ == "bool_":
                cells.append(f'<td style="padding:7px 12px;color:{OK if v else FAINT};font-weight:600">{"✓" if v else "✗"}</td>')
            else:
                cells.append(f'<td style="padding:7px 12px;text-align:{"right" if n else "left"};{"font-variant-numeric:tabular-nums;" if n else ""}white-space:nowrap">{_num(v)}</td>')
        rows.append(f'<tr style="border-top:1px solid {LINE};background:{bg}">{"".join(cells)}</tr>')
    more = f'<div style="padding:7px 12px;font-size:12px;color:{MUTED};border-top:1px solid {LINE}">… {total - len(shown)} weitere Zeilen</div>' if total > len(shown) else ""
    return (f'<div style="border:1px solid {LINE};border-radius:8px;overflow-x:auto;margin:6px 0 12px;background:#fff"><table style="width:100%;border-collapse:collapse;font-size:13px;color:{TEXT}">'
            f'<thead><tr style="background:{SURF}">{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>{more}</div>')


def say(*parts, kind: str | None = None) -> None:
    """Eine Meldungszeile mit farbigem Streifen, Text umbricht. Ton aus ``kind`` (``ok``/``warn``/``error``/``info``) oder aus dem ersten Zeichen: ``⚠`` Warnung, ``✗`` Fehler, ``✓`` ok."""
    text = " ".join(str(p) for p in parts)
    kind = kind or {"⚠": "warn", "✗": "error", "✓": "ok"}.get(text.lstrip()[:1], "info")
    bg, fg, line, _ = NOTE[kind]
    plain = kind == "info"
    show(f'<div style="border-left:4px solid {TONES[kind]};padding:5px 12px;margin:1px 0;font-size:13px;line-height:1.5;{"" if plain else f"background:{bg};color:{fg};"}'
         f'overflow-wrap:anywhere;white-space:pre-wrap">{escape(text)}</div>')


_PLACEHOLDER = re.compile(r"\[[A-ZÄÖÜ]+(?:_\d+)?\]")


def cloud_preview(provider: str, summary: list[tuple[str, int]], text: str) -> str:
    """Vorschau vor dem Senden an eine Cloud-KI: Warnhinweis, Zusammenfassung der anonymisierten Stellen, Länge und der **genaue** Text mit hervorgehobenen Platzhaltern (aufgeklappt).

    ``summary`` aus :func:`varphot.anonymize.summary`; ``text`` ist der bereits anonymisierte Text.
    """
    chips_html = "".join(f'<span style="font-size:12px;padding:3px 10px;border-radius:999px;background:{ACC_BG};color:#0d47a1;margin:0 6px 6px 0;display:inline-block">{n}× {escape(k)}</span>' for k, n in summary)
    chips_html += f'<span style="font-size:12px;padding:3px 10px;border-radius:999px;background:{SURF};color:{MUTED};margin:0 6px 6px 0;display:inline-block">{len(text):,} Zeichen'.replace(",", " ") + "</span>"
    shown = _PLACEHOLDER.sub(lambda m: f'<span style="background:{ACC_BG};color:#0d47a1;padding:0 4px;border-radius:4px">{m.group(0)}</span>', escape(text))
    body = (f'<div style="font:12px/1.7 monospace;background:{SURF};border-radius:8px;padding:10px 12px;white-space:pre-wrap;overflow-wrap:anywhere;color:{TEXT}">{shown}</div>')
    return (note("warn", f"Der **anonymisierte** Text verlässt das Heimnetz (Anbieter: {provider}). Persönliche Angaben sind durch Platzhalter ersetzt.")
            + f'<div style="margin:10px 0 2px">{chips_html}</div>' + details("Vorschau: genau dieser Text wird gesendet", body, open_=True))


def ai_answer(provider: str, seconds: float, text: str, footnote: str = "") -> str:
    """Antwort der KI-Zweitlesung als Karte: eine Zeile je Anmerkung (führende Nummer fett), Kopf mit Anbieter und Dauer, optionaler Fußhinweis."""
    rows = []
    for ln in (x.strip() for x in text.splitlines()):
        if not ln:
            continue
        m = re.match(r"^(\d+\.)\s*(.*)$", ln)
        rows.append(f'<div style="padding:7px 0;border-top:1px solid {LINE};font-size:14px"><b>{m.group(1)}</b> {_md(escape(m.group(2)))}</div>' if m
                    else f'<div style="padding:7px 0;border-top:1px solid {LINE};font-size:14px">{_md(escape(ln))}</div>')
    foot = f'<div style="margin-top:8px;padding:9px 12px;border-radius:8px;background:{SURF};font-size:13px">{_md(footnote)}</div>' if footnote else ""
    return panel("KI-Zweitlesung", [f'<div style="padding:2px 16px 10px">{"".join(rows)}{foot}</div>'], right=f"unverbindlich · {provider} · {seconds:g} s")


def current_method(default: str | None = None) -> str | None:
    """Methode der aktuellen Sitzung (``mono``, ``osc`` …), ohne Sitzung ``default``."""
    try:
        from .session import Session
        return Session.current().method
    except Exception:
        return default
