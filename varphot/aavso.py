"""AAVSO Extended File Format: Datei erzeugen und gegen die Regeln des Formats pruefen.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (Notebook 06, KONZEPT.md §11.2).

Warum: Beobachtungen werden ueber WebObs als Textdatei im „Extended Format“ eingereicht. Fehler im Format (falsche Filtercodes, zu lange Felder, Leerzeilen) fuehren zur Ablehnung der Datei oder — schlimmer —
zu falsch eingeordneten Daten. Dieses Modul schreibt die Datei und prueft sie **vor** dem Hochladen. Ein automatischer Upload findet nicht statt; die Datei wird von Hand ueber WebObs eingereicht.

Quelle: AAVSO Extended File Format, Version 1.2 (Stand 2021-12-02), <https://archive.aavso.org/aavso-extended-file-format> — im Wortlaut gelesen (2026-11-10). Alle Regeln unten stammen von dieser Seite:
sechs Pflichtparameter (``#TYPE``, ``#OBSCODE``, ``#SOFTWARE``, ``#DELIM``, ``#DATE``, ``#OBSTYPE``); Datum nur ``JD``, ``HJD`` oder ``EXCEL`` (Mittenzeit, UT); je Beobachtung 15 Felder (``STARID, DATE, MAGNITUDE,
MAGERR, FILTER, TRANS, MTYPE, CNAME, CMAG, KNAME, KMAG, AIRMASS, GROUP, CHART, NOTES``), „na“ fuer fehlende Werte, keine Leerzeichen am Feldrand, Trennzeichen nicht ``|``, ``#`` oder Leerzeichen, keine
nicht auskommentierten Leerzeilen; Laengen: STARID 30, DATE 16, MAGNITUDE 8 (mit Punkt), MAGERR 6, CNAME 20, CMAG 8, KNAME 20, KMAG 8, AIRMASS 7, GROUP 5, CHART 20; ``ENSEMBLE`` als CNAME mit CMAG ``na``;
``TRANS`` ``YES``/``NO``; ``MTYPE`` ``STD`` oder ``DIF`` (``DIF`` braucht CNAME); NOTES-Unterfelder ``|SCHLUESSEL=WERT``. Ergaenzend: AAVSO DSLR Observing Manual v1.4 §6.7 (gelesen): fuer Ensemble „ensemble“ im Comp-Label,
„na“ als Comp-Mag, im Check-Mag-Feld die **transformierte** Magnitude; mehrere Farben desselben Bildes mit gleicher GROUP-Nummer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

FILTERS = {"U", "B", "V", "R", "I", "J", "H", "K", "TG", "TB", "TR", "CV", "CR", "SZ", "SU", "SG", "SR", "SI", "STU", "STV", "STB", "STY",
           "STHBW", "STHBN", "MA", "MB", "MI", "ZS", "Y", "HA", "HAC", "O"}
FIELDS = ["NAME", "DATE", "MAG", "MERR", "FILT", "TRANS", "MTYPE", "CNAME", "CMAG", "KNAME", "KMAG", "AMASS", "GROUP", "CHART", "NOTES"]
MAXLEN = {"NAME": 30, "DATE": 16, "MAG": 8, "MERR": 6, "CNAME": 20, "CMAG": 8, "KNAME": 20, "KMAG": 8, "AMASS": 7, "GROUP": 5, "CHART": 20}
REQUIRED_PARAMS = ("TYPE", "OBSCODE", "SOFTWARE", "DELIM", "DATE", "OBSTYPE")
FORBIDDEN_DELIMS = {"|", "#", " "}


@dataclass
class Observation:
    """Eine Zeile der Datei (Zahlen als Zahlen; ``None`` wird zu ``na``)."""
    star: str
    jd: float
    mag: float
    err: float | None = None
    filt: str = "V"
    trans: bool = False
    mtype: str = "STD"
    cname: str = "ENSEMBLE"
    cmag: float | None = None
    kname: str | None = None
    kmag: float | None = None
    airmass: float | None = None
    group: int | None = None
    chart: str | None = None
    notes: str | None = None


def _num(x, digits: int) -> str:
    """Zahl als Text mit Punkt; ``na`` fuer fehlende/ungueltige Werte."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "na"
    s = f"{float(x):.{digits}f}"
    return s if "." in s else s + ".0"


def _text(x) -> str:
    s = "na" if x is None or str(x).strip() == "" else str(x).strip()
    return s


def format_row(o: Observation, delim: str = ",") -> str:
    """Eine Beobachtung als Zeile; Trennzeichen im Text werden ersetzt (Format erlaubt sie in Feldern nicht)."""
    fields = [o.star.strip().upper(), f"{o.jd:.5f}", _num(o.mag, 3), _num(o.err, 3), o.filt.upper(), "YES" if o.trans else "NO", o.mtype.upper(),
              _text(o.cname), _num(o.cmag, 3), _text(o.kname), _num(o.kmag, 3), _num(o.airmass, 3), "na" if o.group is None else str(int(o.group)),
              _text(o.chart), _text(o.notes)]
    return delim.join(f.replace(delim, ";" if delim != ";" else ",") for f in fields)


def build_extended(observations: list[Observation], obscode: str, software: str, obstype: str = "CCD", delim: str = ",", date: str = "JD",
                   comments: list[str] | None = None) -> str:
    """Komplette Extended-Format-Datei als Text (Kopfparameter, Spaltenzeile als Kommentar, Beobachtungen).

    Warum/Wie: Kopf wie in den Beispielen der AAVSO; die Spaltenzeile beginnt mit ``#`` (wird ignoriert). ``date='JD'``: Julianisches Datum der **Mitte** der Belichtung in UT (``jd_mid`` der Pipeline;
    BJD_TDB ist im Format nicht vorgesehen). Grenzen: schreibt nur, prueft nicht — danach :func:`validate_extended` aufrufen.
    """
    head = ["#TYPE=Extended", f"#OBSCODE={obscode}", f"#SOFTWARE={software}", f"#DELIM={'comma' if delim == ',' else delim}", f"#DATE={date}", f"#OBSTYPE={obstype}"]
    head += [f"# {c}" for c in (comments or [])]
    head.append("#" + delim.join(FIELDS))
    return "\n".join(head + [format_row(o, delim) for o in observations]) + "\n"


def validate_extended(text: str) -> list[str]:
    """Prueft eine Datei gegen die Regeln des Extended Formats v1.2; Rueckgabe: Liste von Problemen (leer = formal in Ordnung).

    Geprueft werden Pflichtparameter, Trennzeichen, Datumsformat, Feldzahl (15), Feldlaengen, Filtercodes, ``TRANS``, ``MTYPE`` (``DIF`` braucht CNAME), Ensemble-Regel (CMAG ``na``), Punkt in der Magnitude,
    Leerzeichen am Feldrand und Leerzeilen. **Nicht** geprueft werden Inhalte (existiert der Stern? stimmt die Sequenz-ID?) — das macht WebObs. Validierung: ``tests/test_aavso.py`` (Beispiele der AAVSO-Seite).
    """
    issues: list[str] = []
    params: dict[str, str] = {}
    delim = None
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip() == "":
            issues.append(f"Zeile {n}: Leerzeile ohne '#' (WebObs lehnt die Datei ab)")
            continue
        if line.startswith("#"):
            m = re.match(r"#\s*([A-Za-z]+)\s*=\s*(.*)$", line)
            if m and m.group(1).upper() in REQUIRED_PARAMS + ("NAME",):
                params[m.group(1).upper()] = m.group(2).strip()
                if m.group(1).upper() == "DELIM":
                    v = m.group(2).strip()
                    delim = {"comma": ",", "tab": "\t"}.get(v.lower(), v)
                    if delim in FORBIDDEN_DELIMS:
                        issues.append(f"#DELIM '{delim}' ist nicht erlaubt (nicht |, # oder Leerzeichen)")
            continue
        if delim is None:
            issues.append(f"Zeile {n}: Beobachtung vor dem Parameter #DELIM")
            delim = ","
        f = line.split(delim)
        if len(f) != len(FIELDS):
            issues.append(f"Zeile {n}: {len(f)} statt {len(FIELDS)} Felder")
            continue
        r = dict(zip(FIELDS, f))
        for k, v in r.items():
            if v != v.strip():
                issues.append(f"Zeile {n} {k}: Leerzeichen am Feldrand")
            if k in MAXLEN and len(v) > MAXLEN[k]:
                issues.append(f"Zeile {n} {k}: {len(v)} > {MAXLEN[k]} Zeichen")
            if v == "":
                issues.append(f"Zeile {n} {k}: leer (statt 'na')")
        mag = r["MAG"].lstrip("<")
        if r["MAG"] == "na" or "." not in mag:
            issues.append(f"Zeile {n} MAG: '{r['MAG']}' braucht einen Punkt und darf nicht 'na' sein")
        else:
            try:
                float(mag)
            except ValueError:
                issues.append(f"Zeile {n} MAG: '{r['MAG']}' keine Zahl")
        for k in ("MERR", "CMAG", "KMAG", "AMASS"):
            if r[k] != "na":
                try:
                    float(r[k])
                except ValueError:
                    issues.append(f"Zeile {n} {k}: '{r[k]}' keine Zahl")
        if r["FILT"].upper() not in FILTERS:
            issues.append(f"Zeile {n} FILT: '{r['FILT']}' kein gueltiger Filtercode")
        if r["TRANS"].upper() not in ("YES", "NO"):
            issues.append(f"Zeile {n} TRANS: '{r['TRANS']}' (erlaubt YES/NO)")
        if r["MTYPE"].upper() not in ("STD", "DIF", "ABS"):
            issues.append(f"Zeile {n} MTYPE: '{r['MTYPE']}' (erlaubt STD/DIF)")
        if r["MTYPE"].upper() == "DIF" and r["CNAME"] == "na":
            issues.append(f"Zeile {n}: MTYPE=DIF braucht CNAME")
        if r["CNAME"].upper() == "ENSEMBLE" and r["CMAG"] != "na":
            issues.append(f"Zeile {n}: bei ENSEMBLE muss CMAG 'na' sein")
        if r["GROUP"] != "na" and not r["GROUP"].isdigit():
            issues.append(f"Zeile {n} GROUP: '{r['GROUP']}' keine ganze Zahl")
        if params.get("DATE", "JD").upper() in ("JD", "HJD") and not re.fullmatch(r"\d{7}(\.\d+)?", r["DATE"]):
            issues.append(f"Zeile {n} DATE: '{r['DATE']}' kein Julianisches Datum")
    for p in REQUIRED_PARAMS:
        if p not in params:
            issues.append(f"Pflichtparameter #{p} fehlt")
    if params.get("TYPE", "").upper() not in ("", "EXTENDED"):
        issues.append(f"#TYPE muss Extended sein (ist '{params['TYPE']}')")
    if params.get("DATE", "JD").upper() not in ("JD", "HJD", "EXCEL"):
        issues.append(f"#DATE '{params['DATE']}' (erlaubt JD, HJD, EXCEL)")
    if params.get("OBSTYPE", "CCD").upper() not in ("CCD", "DSLR", "PEP"):
        issues.append(f"#OBSTYPE '{params['OBSTYPE']}' (erlaubt CCD, DSLR, PEP)")
    return issues


def notes_string(free: str = "", **kv) -> str:
    """NOTES nach der Konvention der AAVSO: freier Text, dann Unterfelder ``|SCHLUESSEL=WERT`` (``None`` wird ausgelassen; Trennzeichen ``,`` im Text wird durch ``;`` ersetzt)."""
    parts = [free.replace(",", ";").replace("|", "/")] + [f"{k}={v}" for k, v in kv.items() if v is not None]
    return "|".join(p for p in parts if p != "") or "na"


def observations_from_lightcurve(lc, star: str, filt: str, trans: bool, mag_col: str = "mag", err_col: str = "mag_err", jd_col: str = "jd_mid",
                                 chart: str | None = None, kname: str | None = None, kmag_col: str | None = None, airmass_col: str = "airmass",
                                 group_col: str | None = None, notes: str | None = None) -> list[Observation]:
    """Zeilen aus einer Lichtkurve (DataFrame: ``jd_mid``, ``mag``, ``mag_err`` …): Ensemble, MTYPE=STD, JD in UT (Mitte der Belichtung).

    ``kmag_col``: Spalte mit der Check-Stern-Magnitude (bei transformierten Werten die **transformierte**). ``group_col``: ganzzahlige Gruppennummer (mehrere Farben desselben Bildes).
    Zeilen ohne Magnitude werden uebersprungen.
    """
    out = []
    for _, r in lc.iterrows():
        if not (r.get(mag_col) == r.get(mag_col)) or r.get(mag_col) is None:
            continue
        out.append(Observation(star=star, jd=float(r[jd_col]), mag=float(r[mag_col]), err=None if err_col not in lc else float(r[err_col]), filt=filt, trans=trans,
                               cname="ENSEMBLE", cmag=None, kname=kname, kmag=(None if kmag_col is None or kmag_col not in lc else float(r[kmag_col])),
                               airmass=None if airmass_col not in lc else float(r[airmass_col]),
                               group=None if group_col is None else int(r[group_col]), chart=chart, notes=notes))
    return out
