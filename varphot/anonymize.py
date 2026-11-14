"""Datenanonymisierung: persönliche und ortsbezogene Angaben aus einem Text entfernen, bevor er an eine Cloud-KI geht.

Autor: Axel Pospischil. Stand 2026-11-14 (KONZEPT §11.15.3).

Warum: Die KI-Zweitlesung (:mod:`varphot.aireview`) liest den Berichtstext. Läuft sie lokal, bleibt er im Heimnetz. Bei einer Cloud-KI verlässt er den Rechner; dann dürfen weder der AAVSO-Beobachtercode noch
Standort, Koordinaten, Pfade oder Rechnernamen mitgehen. Dieses Modul ersetzt sie durch Platzhalter, prüft unabhängig davon, dass nichts übrig blieb, und kann die Antwort lokal zurückübersetzen.

Wie: :func:`collect_secrets` liest die **bekannten** Werte aus der Konfiguration (Beobachtercode, Standorte mit Koordinaten, Rechner aus der ``ai``-Konfiguration, Heimverzeichnis und Benutzername). Dazu kommen
allgemeine Muster (Pfade unter ``/Users`` und ``/home``, IPv4-Adressen, E-Mail-Adressen). :func:`anonymize` ersetzt alles in **einem** Durchlauf (so wird nie in einem Platzhalter ersetzt); jeder verschiedene
Wert bekommt einen eigenen Platzhalter (``[BEOBACHTERCODE]``, ``[STANDORT]``, ``[BREITE]``, ``[HOST_2]`` …). :func:`find_leaks` prüft das Ergebnis mit einem **anderen** Verfahren (reiner Teilstring-Vergleich
ohne Wortgrenzen) und :func:`prepare_for_cloud` bricht ab, wenn dabei etwas gefunden wird. :func:`restore` setzt die Platzhalter in der Antwort lokal wieder ein. :func:`save_sent_text` legt den gesendeten
(anonymisierten) Text zur Nachvollziehbarkeit ab, **nie** die Zuordnung Platzhalter → Original.

Grenzen: Anonymisieren ist Mustererkennung. Es bleiben im Text: Zielstern, Beobachtungszeiten, Gerätetypen und Messwerte; ihre Kombination kann indirekt auf den Beobachter schließen (akzeptiertes Restrisiko, KONZEPT §11.15.3).
Die Standorthöhe wird **nicht** ersetzt (eine Zahl wie „120“ ist ohne Zusammenhang nicht eindeutig; ohne Koordinaten verrät sie wenig). Koordinaten werden nur in Dezimalschreibweise erkannt (``49.3212``, ``49,32``), nicht in
Grad-Minuten-Sekunden. Ein sehr kurzer Beobachtercode (unter vier Zeichen) wird nur als eigenständiges Wort erkannt und geprüft.

Validierung: ``tests/test_anonymize.py`` (Beispielwerte, Wortgrenzen, Mehrfachwerte, Rückübersetzung, Rückstandsprüfung, Ablage ohne Zuordnung).
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

LABELS = {"code": "BEOBACHTERCODE", "site": "STANDORT", "lat": "BREITE", "lon": "LAENGE", "host": "HOST", "path": "PFAD", "email": "EMAIL", "user": "BENUTZER"}
"""Art des Werts → Name des Platzhalters (``[BEOBACHTERCODE]``; weitere verschiedene Werte der Art bekommen ``_2``, ``_3`` …)."""
KIND_TEXT = {"code": "Beobachtercode", "site": "Standort", "lat": "Breite", "lon": "Länge", "host": "Rechner/Adresse", "path": "Pfad", "email": "E-Mail", "user": "Benutzername"}

_EMAIL = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
_PATH = r"(?:/Users|/home)/[^\s/\]\)\"'<>,;]+(?:/[^\s\]\)\"'<>,;]*)?"
_IPV4 = r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"


class AnonymizationError(Exception):
    """Der Text darf nicht gesendet werden (Rückstand gefunden oder zu lang). Die Meldung nennt nur Arten, nie die Werte."""


@dataclass(frozen=True)
class Secret:
    """Ein bekannter Wert, der nicht hinausgehen darf. ``ci``: Groß/Klein egal; ``pattern``: fertiger regulärer Ausdruck statt eines Literals (Koordinaten)."""
    kind: str
    value: str
    ci: bool = False
    pattern: str = ""


@dataclass
class Anonymized:
    """Ergebnis: ``text`` (anonymisiert), ``mapping`` (Platzhalter → Original, **nur im Speicher**) und ``counts`` (Art → Zahl der ersetzten Stellen)."""
    text: str
    mapping: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


def _literal(value: str, ci: bool = False) -> str:
    """Regulärer Ausdruck für den Wortlaut ``value`` mit Wortgrenzen dort, wo der Wert mit Buchstabe oder Ziffer beginnt oder endet."""
    rx = re.escape(value)
    if value[:1].isalnum():
        rx = r"(?<![A-Za-z0-9])" + rx
    if value[-1:].isalnum():
        rx += r"(?![A-Za-z0-9])"
    return f"(?i:{rx})" if ci else rx


def coordinate_pattern(value: float) -> str:
    """Regulärer Ausdruck für eine Koordinate in Dezimalschreibweise mit 2 bis 6 Nachkommastellen, Punkt oder Komma, beliebigem Vorzeichen (``-`` oder ``−``), ohne anhängende Ziffern."""
    variants = {f"{abs(value):.{n}f}" for n in range(2, 7)}
    alts = []
    for s in sorted(variants, key=len, reverse=True):
        whole, frac = s.split(".")
        alts.append(re.escape(whole) + r"[.,]" + re.escape(frac))
    return r"(?<![\d.,])[-−+]?(?:" + "|".join(alts) + r")(?!\d)"


def collect_secrets(obs=None, sites=(), ai_cfg: dict | None = None, extra=(), home: str | Path | None = None) -> list[Secret]:
    """Bekannte geheime Werte aus der Konfiguration: Beobachtercode, Standortnamen und Koordinaten, Rechner und Adressen der ``ai``-Konfiguration, Heimverzeichnis und Benutzername.

    ``obs``: :class:`varphot.observer.Observer`; ``sites``: Liste :class:`varphot.observer.Site`; ``ai_cfg``: Ergebnis von ``load_ai_config``; ``extra``: weitere ``(Art, Wert)``; ``home``: Heimverzeichnis
    (Standard: das des Benutzers). Leere Werte werden übergangen.
    """
    out: list[Secret] = []
    if obs is not None and getattr(obs, "aavso_code", ""):
        out.append(Secret("code", obs.aavso_code))
    names = {getattr(obs, "site_name", "")} if obs is not None else set()
    names |= {getattr(s, "name", "") for s in sites}
    out += [Secret("site", n, ci=True) for n in sorted(names) if n]
    for s in sites:
        for kind, v in (("lat", getattr(s, "lat_deg", 0.0)), ("lon", getattr(s, "lon_deg", 0.0))):
            if v:
                out.append(Secret(kind, f"{v}", pattern=coordinate_pattern(v)))
    for h in (ai_cfg or {}).get("hosts", []) or []:
        for v in [h.get("name", ""), h.get("ssh", ""), *h.get("addresses", [])]:
            if v:
                out.append(Secret("host", str(v), ci=True))
    h_url = ((ai_cfg or {}).get("local") or {}).get("ollama_url", "")
    host_in_url = re.sub(r"^[a-z]+://", "", h_url).split("/")[0].split(":")[0]
    if host_in_url and host_in_url not in ("127.0.0.1", "localhost", "::1"):
        out.append(Secret("host", host_in_url, ci=True))
    home_p = str(home or Path.home())
    out.append(Secret("path", home_p))
    user = Path(home_p).name
    if len(user) >= 3:
        out.append(Secret("user", user, ci=True))
    out += [Secret(k, v) for k, v in extra if v]
    seen, uniq = set(), []
    for s in out:
        key = (s.kind, s.value)
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return uniq


def _rules(secrets) -> list[tuple[str, str]]:
    """Reihenfolge der Ersetzung: bekannte Werte (längste zuerst), danach die allgemeinen Muster."""
    rules = []
    for s in sorted(secrets, key=lambda x: len(x.value), reverse=True):
        rules.append((s.kind, s.pattern or _literal(s.value, s.ci)))
    rules += [("path", _PATH), ("email", _EMAIL), ("host", _IPV4)]
    return rules


def anonymize(text: str, secrets: list[Secret]) -> Anonymized:
    """Ersetzt alle bekannten Werte und allgemeinen Muster durch Platzhalter (ein Durchlauf, jeder verschiedene Wert ein eigener Platzhalter)."""
    rules = _rules(secrets)
    combined = re.compile("|".join(f"(?P<g{i}>{rx})" for i, (_, rx) in enumerate(rules)))
    mapping: dict[str, str] = {}
    by_value: dict[tuple[str, str], str] = {}
    counts: dict[str, int] = {}
    per_kind: dict[str, int] = {}

    def repl(m: re.Match) -> str:
        kind = rules[int(m.lastgroup[1:])][0]
        raw = m.group(0)
        if kind == "host":
            try:
                ipaddress.ip_address(raw)
            except ValueError:
                if re.fullmatch(_IPV4, raw):                         # z. B. 999.1.1.1: keine Adresse, stehen lassen
                    return raw
        key = (kind, raw.lower())
        if key not in by_value:
            per_kind[kind] = per_kind.get(kind, 0) + 1
            n = per_kind[kind]
            by_value[key] = f"[{LABELS[kind]}]" if n == 1 else f"[{LABELS[kind]}_{n}]"
            mapping[by_value[key]] = raw
        counts[kind] = counts.get(kind, 0) + 1
        return by_value[key]

    return Anonymized(combined.sub(repl, text), mapping, counts)


def find_leaks(text: str, secrets: list[Secret]) -> list[str]:
    """Arten bekannter Werte, die in ``text`` noch vorkommen. Prüft **anders** als :func:`anonymize` (Teilstring ohne Wortgrenzen), damit ein Fehler der Ersetzung auffällt; Werte unter vier Zeichen nur als eigenes Wort."""
    low, found = text.lower(), []
    for s in secrets:
        if s.pattern:
            base = s.value.lstrip("-+")
            hit = len(base) >= 5 and base.lower() in low
        elif len(s.value) < 4:
            hit = re.search(_literal(s.value, True), text) is not None
        else:
            hit = s.value.lower() in low
        if hit and s.kind not in found:
            found.append(s.kind)
    for kind, rx in (("path", _PATH), ("email", _EMAIL)):
        if re.search(rx, text) and kind not in found:
            found.append(kind)
    return found


def prepare_for_cloud(text: str, secrets: list[Secret], max_chars: int | None = None) -> Anonymized:
    """Anonymisiert ``text`` und bricht mit :class:`AnonymizationError` ab, wenn danach noch ein bekannter Wert drin steht oder der Text länger als ``max_chars`` ist (nie stillschweigend kürzen)."""
    res = anonymize(text, secrets)
    leaks = find_leaks(res.text, secrets)
    if leaks:
        raise AnonymizationError("Nach der Anonymisierung steht noch etwas drin: " + ", ".join(KIND_TEXT[k] for k in leaks) + ". Es wird nichts gesendet.")
    if max_chars is not None and len(res.text) > max_chars:
        raise AnonymizationError(f"Der Text ist mit {len(res.text)} Zeichen länger als erlaubt ({max_chars}). Es wird nichts gesendet.")
    return res


def restore(text: str, mapping: dict[str, str]) -> str:
    """Setzt in ``text`` (z. B. der Antwort der KI) die Platzhalter wieder durch die Originale ein; längere Platzhalter zuerst (``[HOST_10]`` vor ``[HOST_1]``)."""
    for ph in sorted(mapping, key=len, reverse=True):
        text = text.replace(ph, mapping[ph])
    return text


def summary(anon: Anonymized) -> list[tuple[str, int]]:
    """Für die Vorschau: ``(Art als Text, Zahl der ersetzten Stellen)``, nach Zahl absteigend; ohne die Werte selbst."""
    return sorted(((KIND_TEXT[k], n) for k, n in anon.counts.items()), key=lambda x: -x[1])


def save_sent_text(directory: str | Path, base: str, anon: Anonymized, provider: str, model: str = "") -> Path:
    """Legt den **gesendeten, anonymisierten** Text neben dem Bericht ab (``<base>_ki_gesendet.md``); die Zuordnung Platzhalter → Original wird nie geschrieben."""
    p = Path(directory) / f"{base}_ki_gesendet.md"
    head = (f"# An die KI gesendet ({provider}{', ' + model if model else ''})\n\nZeit (UTC): {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M:%S}. "
            f"Anonymisierte Stellen: {', '.join(f'{n}× {k}' for k, n in summary(anon)) or 'keine'}.\n\n---\n\n")
    p.write_text(head + anon.text + "\n", encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p
