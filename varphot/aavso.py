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


# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Plausibilitaetspruefung (Inhalt statt Format)
# --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Finding:
    """Ergebnis einer Inhaltspruefung: ``level`` ``ERROR`` (nicht einreichen) oder ``WARN`` (bewusst entscheiden), ``code`` kurzer Schluessel, ``text`` Erklaerung."""
    level: str
    code: str
    text: str

    def __str__(self):
        return f"[{self.level}] {self.code}: {self.text}"


CHART_RE = re.compile(r"[A-Z]\d{5}[A-Z]{2,3}")        # Form der VSP-Sequenz-IDs, z. B. X43370RNS (beobachtet in der VSP-Antwort, nicht offiziell dokumentiert)


def check_plausibility(observations: list[Observation], obstype: str = "CCD", expected_range: tuple[float, float] | None = None, now_jd: float | None = None,
                       kmag_expected: float | None = None, kmag_scatter_max: float = 0.05, err_max: float = 0.08, jump_mag: float = 0.3, jump_minutes: float = 10.0,
                       min_points: int = 5, catalog=None, site=None, target_radec: tuple[float, float] | None = None, catalog_tol: float = 0.5,
                       airmass_tol: float = 0.05) -> list[Finding]:
    """Prueft den **Inhalt** der Beobachtungen auf Widersprueche und Unplausibles (das Format prueft :func:`validate_extended`).

    Warum: Eine formal fehlerfreie Datei kann falsche Daten tragen (falscher Filtercode zur Methode, vertauschter Stern, kaputte Zeit, Gaia-Comps unter AAVSO-Sequenz-ID). WebObs prueft nur wenig davon;
    fremde Auswerter finden Fehler erst spaeter. Wie: feste Regeln ueber alle Zeilen. ``ERROR`` = nicht einreichen. ``WARN`` = pruefen, dann bewusst weitermachen.
    Regeln: Zeit nicht in der Zukunft und nach 2000; keine doppelten (Stern, JD, Filter); Helligkeit endlich; bei ``expected_range`` (V-Bereich des Sterns, z. B. 3,3–4,5 fuer δ Cep): Werte ausserhalb ±0,5 mag
    => ``WARN``, mehr als 25 % => ``ERROR`` (falscher Stern/Filter/Katalog); Fehlerangaben fehlen/negativ => ``ERROR``, sehr gross (``err_max``) oder alle identisch => ``WARN``; Luftmasse < 1 => ``ERROR``, > 3 => ``WARN``;
    Filter/TRANS/OBSTYPE (DSLR-Handbuch §6.7: TG/TB/TR ohne Transformation, V/B/R nur mit TRANS=YES bei Farbkameras); CHART fehlt oder passt nicht zur Form einer AAVSO-Sequenz-ID (bei Gaia-Quelle ``WARN``);
    TRANS=YES ohne Koeffizienten in NOTES; Check-Stern: Streuung > ``kmag_scatter_max`` und Abweichung vom Katalogwert ``kmag_expected`` > 0,05 mag; Spruenge > ``jump_mag`` innerhalb ``jump_minutes`` (Ausreisser);
    weniger als ``min_points`` Zeilen.
    Optional (KONZEPT.md §11.16): ``catalog`` (:class:`varphot.vsx.CatalogRange`) => Werte ausserhalb Bereich ± ``catalog_tol`` mag (bei unsicherem Katalogrand 1 mag) nur ``WARN`` ``katalog_bereich`` (nie ``ERROR``,
    der Katalog kann unvollstaendig sein, Ausbrueche duerfen darueber liegen); ``site`` (Objekt mit ``lat_deg``, ``lon_deg``, ``height_m``) und ``target_radec`` (Grad) => Stern unter dem Horizont (< −1°) ``ERROR``
    ``stern_horizont``; Sonne hoeher als −12° ``WARN`` ``sonne_hoch``; Luftmasse der Datei weicht bei >= 25 % der Zeilen um mehr als ``airmass_tol`` (relativ) von der Rechnung ab ``WARN`` ``luftmasse_ort``.
    Grenzen: Schwellen sind Startwerte (nicht aus Daten kalibriert); WebObs wird nicht abgefragt. Validierung: ``tests/test_aavso.py``, ``tests/test_vsx.py``.
    """
    F: list[Finding] = []
    add = lambda lvl, code, txt: F.append(Finding(lvl, code, txt))
    n = len(observations)
    if n == 0:
        return [Finding("ERROR", "leer", "keine Beobachtungen")]
    if n < min_points:
        add("WARN", "wenige_punkte", f"nur {n} Beobachtungen (< {min_points})")
    jd = [o.jd for o in observations]
    if now_jd is None:
        import datetime as _dt
        now_jd = 2440587.5 + _dt.datetime.now(_dt.timezone.utc).timestamp() / 86400.0
    if max(jd) > now_jd + 0.05:
        add("ERROR", "zeit_zukunft", f"JD {max(jd):.4f} liegt in der Zukunft")
    if min(jd) < 2451544.5:                                    # 2000-01-01
        add("ERROR", "zeit_alt", f"JD {min(jd):.4f} vor dem Jahr 2000 (Einheit oder Zeitsystem falsch?)")
    if max(jd) - min(jd) > 400:
        add("WARN", "zeitraum", f"Zeitraum {max(jd) - min(jd):.0f} Tage in einer Datei")
    seen = {}
    for o in observations:
        key = (o.star.upper(), round(o.jd, 5), o.filt.upper())
        seen[key] = seen.get(key, 0) + 1
    dup = sum(v - 1 for v in seen.values() if v > 1)
    if dup:
        add("ERROR", "doppelt", f"{dup} doppelte Zeilen (gleicher Stern, JD und Filter)")
    mags = [o.mag for o in observations]
    if any(not math.isfinite(m) for m in mags):
        add("ERROR", "mag_nan", "Helligkeit nicht endlich")
    else:
        if expected_range:
            lo, hi = expected_range
            out = sum(1 for m in mags if m < lo - 0.5 or m > hi + 0.5)
            if out / n > 0.25:
                add("ERROR", "mag_bereich", f"{out} von {n} Werten ausserhalb {lo - 0.5:.1f}…{hi + 0.5:.1f} mag — falscher Stern, Filter oder Katalog?")
            elif out:
                add("WARN", "mag_bereich", f"{out} von {n} Werten ausserhalb {lo - 0.5:.1f}…{hi + 0.5:.1f} mag")
        elif min(mags) < -2 or max(mags) > 20:
            add("WARN", "mag_extrem", f"Helligkeiten {min(mags):.2f}…{max(mags):.2f} mag ungewoehnlich")
    errs = [o.err for o in observations]
    if any(e is None or not math.isfinite(e) for e in errs):
        add("ERROR", "fehler_fehlt", "Fehlerangabe (MERR) fehlt bei manchen Zeilen — AAVSO erwartet sie; sonst bewusst 'na' begruenden")
    else:
        if any(e <= 0 for e in errs):
            add("ERROR", "fehler_negativ", "Fehlerangabe <= 0")
        if sorted(errs)[n // 2] > err_max:
            add("WARN", "fehler_gross", f"mittlerer Fehler {sorted(errs)[n // 2]:.3f} mag > {err_max} mag")
        if n >= 10 and len(set(round(e, 4) for e in errs)) == 1:
            add("WARN", "fehler_konstant", "alle Fehlerangaben identisch (nicht je Messung berechnet?)")
        if n >= 10 and sorted(errs)[n // 2] < 0.001:
            add("WARN", "fehler_klein", "mittlerer Fehler < 0,001 mag (unrealistisch klein, Szintillation/Photonenrauschen)")
        if n >= 10 and 0.001 <= sorted(errs)[n // 2] < 0.003:
            add("INFO", "fehler_scint", f"mittlerer Fehler {sorted(errs)[n // 2]:.3f} mag — ggf. durch korrelierte Comp-Fehler unterschaetzt (vgl. Bootstrap-Option)")
    am = [o.airmass for o in observations if o.airmass is not None and math.isfinite(o.airmass)]
    if am and min(am) < 1.0:
        add("ERROR", "luftmasse", f"Luftmasse {min(am):.3f} < 1")
    if am and max(am) > 3.0:
        add("WARN", "luftmasse_hoch", f"Luftmasse bis {max(am):.2f} (> 3)")
    ob = obstype.upper()
    filts = {o.filt.upper() for o in observations}
    for o in {(o.filt.upper(), o.trans) for o in observations}:
        f, t = o
        if f in ("TG", "TB", "TR") and t:
            add("ERROR", "filter_trans", f"Filter {f} mit TRANS=YES (TG/TB/TR sind untransformiert; transformiert V/B/R melden)")
        if f in ("V", "B", "R") and not t and ob == "DSLR":
            add("ERROR", "filter_trans", f"OBSTYPE=DSLR mit Filter {f} und TRANS=NO — bei Farbkameras untransformiert als TG/TB/TR melden (DSLR-Handbuch §6.7)")
    if ob == "CCD" and filts & {"TG", "TB", "TR"}:
        add("WARN", "obstype", "TG/TB/TR mit OBSTYPE=CCD — Farbkameras/RGB-Filter laufen bei der AAVSO unter DSLR; vor dem Einreichen klaeren")
    if any(o.trans and not (o.notes and "=" in o.notes) for o in observations):
        add("WARN", "koeffizienten", "TRANS=YES ohne Koeffizienten in NOTES (Tbv, Tv_bv …)")
    charts = {o.chart or "na" for o in observations}
    for c in charts:
        if c == "na":
            add("WARN", "chart_fehlt", "CHART fehlt (Sequenz-ID der VSP eintragen)")
        elif c.lower().startswith("gaia"):
            noted = any("gaia-abgeleitet" in (o.notes or "").lower() or "(k)" in (o.notes or "").lower() for o in observations if (o.chart or "") == c)
            if not noted:
                add("WARN", "chart_gaia", f"CHART '{c}': Comps stammen nicht aus der AAVSO-Sequenz (Notbehelf, in NOTES kennzeichnen)")
        elif not CHART_RE.fullmatch(c):
            add("WARN", "chart_form", f"CHART '{c}' hat nicht die Form einer VSP-Sequenz-ID (z. B. X43370RNS)")
    km = [o.kmag for o in observations if o.kmag is not None and math.isfinite(o.kmag)]
    if any(o.kname for o in observations) and len(km) < n:
        add("WARN", "check_fehlt", "Check-Stern benannt, aber KMAG fehlt in einigen/allen Zeilen")
    if len(km) >= 5:
        mean = sum(km) / len(km)
        sd = (sum((x - mean) ** 2 for x in km) / (len(km) - 1)) ** 0.5
        if sd > kmag_scatter_max:
            add("WARN", "check_streuung", f"Check-Stern streut mit {sd:.3f} mag (> {kmag_scatter_max}) — Photometrie/Comps pruefen")
        if kmag_expected is not None and abs(mean - kmag_expected) > 0.05:
            add("WARN", "check_offset", f"Check-Stern im Mittel {mean:.3f} mag, Katalog {kmag_expected:.3f} (Differenz {mean - kmag_expected:+.3f})")
    if catalog is not None and all(math.isfinite(m) for m in mags):
        tol = max(catalog_tol, 1.0) if catalog.uncertain else catalog_tol
        out = sum(1 for m in mags if m < catalog.lo - tol or m > catalog.hi + tol)
        if out:
            add("WARN", "katalog_bereich", f"{out} von {n} Werten ausserhalb {catalog.source} {catalog.lo:g}–{catalog.hi:g} {catalog.band} ± {tol:g} mag"
                + (f" ({catalog.name})" if catalog.name else "") + (" — falscher Stern, Filter oder Katalog?" if out / n > 0.25 else ""))
    if site is not None and target_radec is not None:
        F.extend(_check_site_time(observations, site, target_radec, airmass_tol))
    srt = sorted(observations, key=lambda o: o.jd)
    jumps = sum(1 for a, b in zip(srt, srt[1:]) if (b.jd - a.jd) * 1440 <= jump_minutes and a.filt == b.filt and abs(b.mag - a.mag) > jump_mag)
    if jumps:
        add("WARN", "sprung", f"{jumps} Sprung/Spruenge > {jump_mag} mag innerhalb {jump_minutes:g} min (Ausreisser?)")
    return F


def _check_site_time(observations: list[Observation], site, target_radec: tuple[float, float], airmass_tol: float) -> list[Finding]:
    """Regel R2: Hoehe von Stern und Sonne und Luftmasse aus Ort und Zeit gegen die Datei (siehe :func:`check_plausibility`)."""
    from .visibility import airmass_kasten_young, altitudes
    n = len(observations)
    try:
        star, sun = altitudes(target_radec[0], target_radec[1], [o.jd for o in observations], site.lat_deg, site.lon_deg, getattr(site, "height_m", 0.0))
    except Exception as e:                                                               # astropy fehlt/Zeit ausserhalb der Tabellen: Pruefung entfaellt, kein Abbruch
        return [Finding("INFO", "ort_zeit_nicht_geprueft", f"Ort/Zeit nicht geprueft: {type(e).__name__}")]
    F: list[Finding] = []
    below = int((star < -1.0).sum())
    if below:
        F.append(Finding("ERROR", "stern_horizont", f"Stern liegt bei {below} von {n} Zeilen unter dem Horizont (Zeit, Zeitzone, Standort oder Stern falsch?)"))
    high = int((sun > -12.0).sum())
    if high:
        F.append(Finding("WARN", "sonne_hoch", f"Sonne bei {high} von {n} Zeilen hoeher als −12° (Daemmerung/Tag: Zeit oder Standort falsch?)"))
    pairs = [(o.airmass, airmass_kasten_young(float(a))) for o, a in zip(observations, star) if o.airmass is not None and math.isfinite(o.airmass)]
    pairs = [(f, c) for f, c in pairs if math.isfinite(c)]
    if pairs:
        dev = sorted(abs(f - c) / c for f, c in pairs)
        bad = sum(1 for d in dev if d > airmass_tol)
        if bad / len(pairs) >= 0.25:
            F.append(Finding("WARN", "luftmasse_ort", f"Luftmasse der Datei weicht bei {bad} von {len(pairs)} Zeilen um mehr als {airmass_tol:.0%} von der Rechnung aus Ort und Zeit ab "
                             f"(Median {dev[len(dev) // 2]:.0%}) — Zeitzone, JD/HJD oder Standort pruefen"))
    return F
