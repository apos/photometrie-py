"""VSX-Abfrage (AAVSO Variable Star Index): erwarteter Helligkeitsbereich eines Sterns fuer die Inhaltspruefung.

Autor: Axel Pospischil. Verfahren: Stand 2026-11 (KONZEPT.md §11.16).

Warum: Eine Datei mit dem falschen Stern, Filter oder Katalog ist formal fehlerfrei. Der Bereich aus VSX faengt grobe Verwechslungen (>= 1 mag). Wie: JSON-Abfrage ``view=api.object`` (Name oder AUID),
ersatzweise ``view=api.list`` (Kegel um die Koordinaten des Ziels); Antwort im Zwischenspeicher (30 Tage). Quelle: nicht offiziell dokumentierte Schnittstelle (Forenbeitraege), Aufbau am 2026-11-14 geprueft;
``www.aavso.org`` liegt hinter einer Cloudflare-Abfrage, ``vsx.aavso.org`` antwortet ohne Anmeldung.

Bereichsformate in ``MaxMag``/``MinMag`` (Stichprobe 2077 Eintraege): ``3.49 V`` (brauchbar), ``4.0: p`` (unsicher), ``<17.5 V`` (nur Grenze), ``(0.013) V`` (**Amplitude**, keine Helligkeit), ``?``/leer, dazu andere
Baender (G, g, r, Rc, TESS, ...). Brauchbar ist nur ein Wert ohne Klammer und ohne ``<`` im gesuchten Band.

Datenschutz: gesendet werden nur Sternname/AUID bzw. die Koordinaten des Sterns, ein allgemeiner Programmname als User-Agent — nie Standort, Beobachtercode oder Pfade. Fehler/Offline fuehren nie zum Abbruch:
es gibt dann keinen Bereich und eine Meldung. ``VARPHOT_VSX=off`` schaltet die Abfrage ab, ``VARPHOT_VSX_CACHE`` setzt den Ort des Zwischenspeichers.
Grenzen: Der Bereich ist keine harte Grenze (Ausbrueche, Mittelwert+Amplitude-Eintraege); Aufrufer duerfen ihn nur als Warnung verwenden. Validierung: ``tests/test_vsx.py`` (mit Attrappe, ohne Netz).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

BASE = "https://vsx.aavso.org/index.php"
USER_AGENT = "varphot"
CACHE_DAYS = 30
NOT_FOUND_DAYS = 1
CONE_RADIUS_DEG = 0.003                                   # ca. 11 Bogensekunden
_MAG_RE = re.compile(r"(<|>)?\s*(\()?\s*(\d+(?:\.\d+)?)\s*\)?\s*(:)?\s*(\S*)")


@dataclass
class CatalogRange:
    """Bereich aus VSX im Band ``band`` (``lo`` = hellster, ``hi`` = schwaechster Wert), ``source`` fuer die Meldung."""
    lo: float
    hi: float
    band: str = "V"
    uncertain: bool = False
    source: str = "VSX"
    name: str = ""


def parse_mag(text: str | None, band: str = "V") -> tuple[float | None, str]:
    """Zahl und Status aus einem VSX-Helligkeitsfeld.

    Status: ``ok``, ``unsicher`` (Doppelpunkt), ``grenze`` (``<``/``>``), ``amplitude`` (Klammer), ``leer``, ``band`` (anderes Band), ``unlesbar``. Nur ``ok``/``unsicher`` liefern eine Zahl.
    """
    t = (text or "").strip()
    if not t or t == "?":
        return None, "leer"
    m = _MAG_RE.fullmatch(t)
    if not m:
        return None, "unlesbar"
    lt, par, val, unc, b = m.groups()
    if par:
        return None, "amplitude"
    if lt:
        return None, "grenze"
    if b.upper() != band.upper():
        return None, "band"
    return float(val), ("unsicher" if unc else "ok")


def catalog_range(obj: dict | None, band: str = "V") -> tuple[CatalogRange | None, str]:
    """Bereich eines VSX-Objekts im Band; ohne brauchbare Angabe ``(None, Grund)``."""
    if not obj:
        return None, "kein Eintrag"
    mx, s1 = parse_mag(obj.get("MaxMag"), band)
    mn, s2 = parse_mag(obj.get("MinMag"), band)
    if mx is None or mn is None:
        why = {"leer": "fehlt", "grenze": "nur eine Grenze", "amplitude": "nur Amplitude", "band": f"nicht im Band {band}", "unlesbar": "unlesbar"}
        bad = s1 if mx is None else s2
        return None, f"Bereich {why.get(bad, bad)} (Max '{obj.get('MaxMag', '')}', Min '{obj.get('MinMag', '')}')"
    return CatalogRange(min(mx, mn), max(mx, mn), band, "unsicher" in (s1, s2), "VSX", str(obj.get("Name", ""))), ""


def _default_fetch(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:                       # nur der VSX-Host; kein Proxy-/Weiterleitungs-Eingriff noetig, der Host ist fest
        return r.read().decode("utf-8", "replace")


def cache_path() -> Path:
    return Path(os.environ.get("VARPHOT_VSX_CACHE") or "~/.cache/varphot/vsx.json").expanduser()


def _load_cache(p: Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(p: Path, d: dict) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass                                                                       # Zwischenspeicher ist nur eine Beschleunigung


def _object_from(text: str) -> dict | None:
    d = json.loads(text)
    o = d.get("VSXObject")
    return o if isinstance(o, dict) and o else None


def _nearest(objs: list[dict], ra: float, dec: float, band: str) -> dict | None:
    best, bd = None, 1e9
    for o in objs:
        if catalog_range(o, band)[0] is None:
            continue
        try:
            dra = (float(o["RA2000"]) - ra) * math.cos(math.radians(dec))
            d = math.hypot(dra, float(o["Declination2000"]) - dec)
        except (KeyError, ValueError):
            continue
        if d < bd:
            best, bd = o, d
    return best


def fetch_object(name: str | None = None, auid: str | None = None, ra: float | None = None, dec: float | None = None, band: str = "V", *,
                 fetch: Callable[[str], str] | None = None, cache: Path | None = None, now: float | None = None) -> tuple[dict | None, str]:
    """Holt das VSX-Objekt: erst AUID, dann Name, dann Kegel um (ra, dec); Rueckgabe ``(objekt|None, Status)`` mit Status ``ok``, ``nicht gefunden``, ``aus``, ``nicht erreichbar``."""
    if os.environ.get("VARPHOT_VSX", "").lower() in ("off", "0", "no"):
        return None, "aus"
    fetch = fetch or _default_fetch
    now = time.time() if now is None else now
    p = cache or cache_path()
    store = _load_cache(p)
    queries: list[tuple[str, str]] = []
    if auid:
        queries.append(("obj", auid.strip()))
    if name and name.strip():
        queries.append(("obj", re.sub(r"^\*+\s*", "", name.strip())))
    if ra is not None and dec is not None:
        queries.append(("cone", f"{ra:.5f},{dec:.5f}"))
    unreachable = False
    for kind, q in queries:
        key = f"{kind}:{q.lower()}"
        hit = store.get(key)
        if hit and now - hit.get("ts", 0) < (CACHE_DAYS if hit.get("obj") else NOT_FOUND_DAYS) * 86400:
            if hit.get("obj"):
                return hit["obj"], "ok"
            continue
        try:
            if kind == "obj":
                obj = _object_from(fetch(f"{BASE}?" + urllib.parse.urlencode({"view": "api.object", "format": "json", "ident": q})))
            else:
                r, d = (float(x) for x in q.split(","))
                text = fetch(f"{BASE}?" + urllib.parse.urlencode({"view": "api.list", "format": "json", "ra": f"{r:.5f}", "dec": f"{d:.5f}", "radius": CONE_RADIUS_DEG}))
                lst = (json.loads(text).get("VSXObjects") or {}).get("VSXObject") or []
                obj = _nearest(lst if isinstance(lst, list) else [lst], r, d, band)
        except (OSError, ValueError, KeyError, AttributeError, TypeError):
            unreachable = True
            continue
        store[key] = {"ts": now, "obj": obj}
        _save_cache(p, store)
        if obj:
            return obj, "ok"
    return None, ("nicht erreichbar" if unreachable else "nicht gefunden")


def lookup_range(name: str | None = None, auid: str | None = None, ra: float | None = None, dec: float | None = None, band: str = "V", **kw) -> tuple[CatalogRange | None, str]:
    """Bereich fuer die Inhaltspruefung; zweiter Wert = Meldung, wenn keiner vorliegt (leer bei Erfolg)."""
    obj, status = fetch_object(name, auid, ra, dec, band, **kw)
    if status == "aus":
        return None, "VSX-Abfrage ausgeschaltet (VARPHOT_VSX=off)"
    if obj is None:
        return None, f"VSX: {status} — Katalogbereich nicht geprueft"
    rng, why = catalog_range(obj, band)
    return (rng, "") if rng else (None, f"VSX '{obj.get('Name', '')}': {why} — Katalogbereich nicht geprueft")
