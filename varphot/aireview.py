"""Lokale KI als zweite Leserin des Berichts — Backends suchen, auswaehlen und aufrufen (Opencode, Ollama).

Autor: Axel Pospischil. Stand 2026-11-10 (Notebook 01 Vorbedingungen, Notebook 06 Schritt 4c).

Warum: Die festen Regeln (:func:`varphot.aavso.check_plausibility`) pruefen Zahlen und Format. Ein Sprachmodell kann den **Berichtstext** zusaetzlich auf Widersprueche, unklare Formulierungen und
fehlende Angaben lesen. Es ist dafuer nur zweite Leserin: es darf nichts aendern und wird nicht fuer Zahlen benutzt (kleine lokale Modelle rechnen unzuverlaessig und erfinden Belege).
Die Daten sollen den eigenen Rechner/das Heimnetz **nicht verlassen**; deshalb werden nur Rechner im privaten Netz angesprochen (:func:`is_private_host`), und Opencode wird nur benutzt, wenn
es ein **lokales** Modell hat (die vorgegebenen ``opencode/*``-Modelle laufen in der Cloud).

Reihenfolge (festgelegt vom Anwender): 1. der staerkere Rechner im Heimnetz (Adressen der Reihe nach, z. B. LAN, dann WireGuard): erst Opencode pruefen (der Aufruf ueber ``ssh`` ist **noch nicht eingebaut**,
es wird nur festgestellt, ob es vorhanden ist), sonst Ollama dort; 2. der lokale Rechner: erst Opencode (mit lokalem Modell), dann Ollama.

Konfiguration: Schluessel ``ai`` in ``observer.json`` (privater Datenordner, nicht im oeffentlichen Repo; Adressen gehoeren nicht ins Repo)::

    "ai": {"enabled": true,
           "hosts": [{"name": "rechner", "addresses": ["192.168.x.y", "10.x.y.z"], "ollama_port": 11434, "ssh": "alias"}],
           "local": {"ollama_url": "http://127.0.0.1:11434", "opencode": true, "opencode_model": "ollama/qwen2.5:7b"},
           "models": ["qwen2.5:7b", "llama3.1:8b"]}

Ohne Konfiguration wird nur der lokale Rechner geprueft. ``VARPHOT_AI=off`` schaltet alles ab.
Validierung: ``tests/test_aireview.py`` (Ollama-Attrappe als HTTP-Server, Opencode-Attrappe als Skript) und ein Lauf gegen den echten Ollama im Heimnetz (KONZEPT §11.14).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PREFERRED_MODELS = ["gemma2:9b", "llama3.1:8b", "qwen2.5:7b", "aya-expanse:8b", "gemma3:4b"]      # Reihenfolge nach Probelauf (KONZEPT §11.14): gemma2 fand die meisten echten Fehler, qwen die wenigsten
NOT_FOR_CHAT = ("embed", "bge", "nomic", "minilm", "rerank")           # Einbettungsmodelle taugen nicht zum Lesen
LOCAL_OPENCODE_PROVIDERS = ("ollama", "lmstudio", "llama", "local")     # Anbieter-Praefixe, die lokale Modelle bedeuten; ``opencode/*`` ist Cloud

PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")]   # bewusst explizit:
# ``ipaddress.is_private`` zaehlt auch Dokumentations-/Testnetze (z. B. 203.0.113.0/24) und reservierte Bereiche dazu

SYSTEM_PROMPT = (
    "Du pruefst den Bericht zu einer Veraenderlichen-Photometrie, der an die AAVSO gemeldet werden soll. Antworte auf Deutsch. Gehe die folgende Liste Punkt fuer Punkt durch und schreibe zu JEDEM Punkt "
    "genau eine Zeile, die mit der Nummer des Punkts beginnt, also zum Beispiel '3. OK' oder '3. AUFFAELLIG: <kurze Begruendung mit Zitat aus dem Bericht>'. Trifft ein Punkt auf den Bericht nicht zu (z. B. keine Farbkamera), schreibe 'OK'. Nur Aussagen, die im Text belegt sind; nichts erfinden, keine Zahlen nachrechnen, nichts aendern.\n"
    "1. Filter TG, TB oder TR bedeutet untransformiert: dann muss TRANS NO sein. Filter V, B oder R mit TRANS YES verlangt Koeffizienten (Tbv, Tv_bv ...).\n"
    "2. Farbkamera, Bayer-Kamera oder RGB-Filter (Filter TG/TB/TR): OBSTYPE soll DSLR sein, nicht CCD.\n"
    "3. Der Zeitraum muss vom frueheren zum spaeteren Datum laufen (erster JD kleiner als zweiter JD).\n"
    "4. Der mittlere Fehler muss zwischen 0.001 und 0.08 mag liegen; kleiner oder groesser ist unplausibel.\n"
    "5. CHART soll eine AAVSO-Sequenz-ID wie X43370IPN sein; 'Gaia' oder 'na' als CHART bedeutet Comps nicht aus der AAVSO-Sequenz. Gaia-abgeleitete Comps muessen genannt sein.\n"
    "6. Es darf keine Warnung im Text stehen, die dem Rest widerspricht (z. B. 'keine Warnungen', obwohl oben Probleme genannt sind).\n"
    "7. Fehlt etwas, das ein Pruefer erwartet (Beobachtercode, Check-Stern, Zahl der Comps)?\n"
    "Danach eine Zeile 'Fazit:' mit hoechstens einem Satz."
)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Eingegrenzter Pruefauftrag mit Kontext (Stand 2026-11-17)
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Warum: Der allgemeine :data:`SYSTEM_PROMPT` liess die KI selbst entscheiden, was gilt. Ergebnis im Probelauf (2026-11-16, Claude): "OK: Es gibt keine Hinweise auf Farb-, Bayer- oder RGB-Kamera" — ein
# Urteil ohne Beleg und ohne zu wissen, welche Kamera es war; zugleich meldete sie mit Recht Widersprueche im Bericht, die die Software selbst haette vermeiden muessen. Hier gilt die Methode der
# Regel "praezise, konkrete, belegte Aussagen" (BM 00012): (1) der **Kontext** (was ist das, was wurde erwartet, was ist Absicht) kommt aus den Daten der Software, nicht aus der Annahme der KI;
# (2) die **Pruefpunkte** werden von der Software je Fall zusammengestellt (die KI entscheidet nie, ob ein Punkt gilt); (3) jedes Urteil muss ein **woertliches Zitat** enthalten, kein nacktes "OK";
# (4) was feste Regeln schon sicher pruefen (Zahlenbereiche, Format, Filter/TRANS/OBSTYPE-Regeln), wird **nicht** wiederholt.
METHOD_TEXT = {"mono": "Mono-Kamera mit Messfilter (Johnson V)", "monorgb": "Mono-Kamera mit RGB-Filterrad (Kanaele TB/TG/TR)",
               "osc": "Farbkamera mit Bayer-Matrix (Gruenkanal TG)", "dslr": "DSLR/spiegellose Kamera, RAW, Gruenkanal TG"}
VERDICTS = "OK, AUFFAELLIG oder NICHT_PRUEFBAR"


def build_context(f: dict) -> str:
    """Abschnitt ``## Kontext`` fuer die KI: was der Text ist, was erwartet wurde, was Absicht ist, was die Software schon geprueft hat.

    ``f`` (alle Schluessel optional): ``method``, ``camera``, ``mode`` (``untransformiert``/``transformiert``), ``exp_filter``, ``exp_trans`` (bool), ``exp_obstype``, ``is_test``, ``n_points``,
    ``n_comps_sel`` (ausgewaehlt), ``n_comps_ens`` (Median der je Bild im Ensemble benutzten), ``n_gaia``, ``chart``, ``obstype_open`` (bei Farbkamera bei der AAVSO noch nicht geklaert).
    Enthaelt keine persoenlichen Angaben (Beobachtercode/Standort stehen nur im Bericht und werden vor dem Senden ersetzt).
    """
    L = ["## Kontext (verbindlich; gilt als wahr, nicht anzweifeln)",
         "- Der folgende Text ist ein **automatisch erzeugter** Bericht der Auswertesoftware varphot zu einer Datei im AAVSO Extended Format (Veraenderlichen-Photometrie). Kein Mensch hat ihn geschrieben.",
         "- Du bist die **zweite Leserin**: Du pruefst nur Text, Widersprueche und Verstaendlichkeit. Zahlenbereiche, Format und Regeln hat die Software schon geprueft (Abschnitt 'Ergebnis der festen Pruefungen')."]
    m = f.get("method")
    if m:
        L.append(f"- Aufnahme: {METHOD_TEXT.get(m, m)}" + (f", Kamera {f['camera']}" if f.get("camera") else "") + f"; Betriebsart: {f.get('mode') or 'untransformiert'}.")
    if f.get("exp_filter") is not None:
        L.append(f"- Erwartet fuer diese Datei (aus Plan und Regel): Filter {f['exp_filter']}, TRANS {'YES' if f.get('exp_trans') else 'NO'}, OBSTYPE {f.get('exp_obstype') or 'CCD'}"
                 + (" (OBSTYPE bei Farbkamera/RGB-Filter ist bei der AAVSO noch **nicht geklaert**: ein Abweichen von DSLR/CCD melden, aber nicht als Programmfehler bewerten)." if f.get("obstype_open") else "."))
    L.append("- Testdaten: " + ("**ja** — Kennzeichnung 'TESTDATEN' und der Beobachtercode TST01 sind Absicht; die Datei ist nicht zum Einreichen." if f.get("is_test") else "nein — Echtdaten."))
    L.append("- Bewusst so, **kein Fehler**:")
    if f.get("n_comps_sel") is not None:
        L.append(f"  * 'Comps' ({f['n_comps_sel']}, ausgewaehlte Vergleichssterne) und 'Ensemble' ({f.get('n_comps_ens', '?')}, Median der je Bild tatsaechlich benutzten Comps) sind **zwei verschiedene Groessen**; Ensemble <= Comps ist normal (Ausreisser-Verwurf je Bild).")
    if f.get("chart") and str(f["chart"]).startswith("Gaia"):
        L.append("  * CHART 'Gaia DR3 V-deriv' ist der vorgesehene Notbehelf, wenn keine AAVSO-Sequenz-ID vorliegt; er steht schon als Warnung im Bericht (nicht erneut melden, nur auf Widersprueche achten).")
    L.append("  * Platzhalter in eckigen Klammern (z. B. [BEOBACHTERCODE]) sind ausgeblendete Angaben, ausgefuellt und kein Fehler.")
    L.append("- Von der Software schon sicher geprueft (nicht wiederholen): Pflichtfelder und Format, Zeit (Zukunft, doppelte Zeilen), Helligkeitsbereich, Fehler > 0, Luftmasse, Check-Stern-Streuung, Filter/TRANS/OBSTYPE-Regeln.")
    return "\n".join(L)


def build_system_prompt(f: dict) -> str:
    """Systemanweisung mit den **fuer diesen Fall zusammengestellten** Pruefpunkten (die KI entscheidet nie selbst, ob ein Punkt gilt)."""
    pts = []
    if f.get("exp_filter") is not None:
        pts.append(f"Abgleich mit der Erwartung aus dem Kontext (Filter {f['exp_filter']}, TRANS {'YES' if f.get('exp_trans') else 'NO'}, OBSTYPE {f.get('exp_obstype') or 'CCD'}): zitiere aus 'Kopf der Datei' die Zeile #OBSTYPE und aus der ersten Datenzeile die Felder FILT und TRANS. Gleich = OK, abweichend = AUFFAELLIG.")
    pts.append("Zahlen, die im Bericht mehr als einmal vorkommen (Punkte, Zeitraum, Zahl der Comps, Check-Stern): zitiere jeweils beide Fundstellen. Gleiche Groesse mit verschiedenem Wert = AUFFAELLIG; Groessen, die der Kontext als verschieden erklaert, sind kein Widerspruch.")
    pts.append("Mengenwoerter ('teils', 'alle', 'keine', 'einige', 'ein Teil') gegen die Zahl in derselben Datei: zitiere Wort und Zahl; passen sie nicht zusammen = AUFFAELLIG.")
    pts.append("Ueberschriften gegen ihren Inhalt (zum Beispiel 'nicht an echten Daten geprueft' ueber einer Liste, die sagt, alles sei geprueft): zitiere Ueberschrift und erste Zeile darunter.")
    pts.append("Warnungen: steht jede Zeile aus 'Ergebnis der festen Pruefungen' auch unter 'Offene Punkte'? Und sagt 'Warnungen:' oben nicht 'keine', obwohl Punkte aufgelistet sind? Zitiere die Gegenstellen.")
    pts.append("Verstaendlichkeit: Nennt jede Zeile unter 'Offene Punkte' den gemessenen Wert **und** die Schwelle, sodass ein Beobachter ohne Programmkenntnis sie versteht? Zitiere jede Zeile, der das fehlt (sonst: 'alle Zeilen nennen Wert und Schwelle' mit Zitat einer Zeile).")
    if f.get("is_test"):
        pts.append("Testkennzeichnung: zitiere aus 'Kopf der Datei' die Zeile mit 'TESTDATEN'. Fehlt sie = AUFFAELLIG.")
    if f.get("mode") == "transformiert":
        pts.append("Transformiert: zitiere aus der NOTES-Spalte der ersten Datenzeile die Koeffizienten (Tbv, Tv_bv ...). Fehlen sie = AUFFAELLIG.")
    num = "\n".join(f"{i}. {t}" for i, t in enumerate(pts, 1))
    return ("Du bist die zweite Leserin eines automatisch erzeugten Photometrie-Berichts (AAVSO). Antworte auf Deutsch. Der Abschnitt '## Kontext' ist verbindlich und wahr; er sagt, was erwartet und was Absicht ist.\n"
            "Pruefe NUR die folgenden Punkte, keine weiteren. Fuege keine eigenen Punkte, keine Empfehlungen zur Messmethode und keine Aussagen ueber Daten hinzu, die nicht im Text stehen. Rechne keine Zahlen nach, aendere nichts.\n"
            f"Antwortformat, genau eine Zeile je Punkt, mit der Nummer des Punkts: '<Nr>. <Urteil> | Gefunden: \"<woertliches Zitat oder Zahl mit Fundstelle>\" | Grund: <ein Satz>'. Urteil ist {VERDICTS}. "
            "**Kein Urteil ohne woertliches Zitat**: auch bei OK muss das Zitat zeigen, was geprueft wurde. NICHT_PRUEFBAR nur, wenn die benoetigte Stelle im Text fehlt (nenne, was fehlt); raten ist verboten.\n"
            f"Pruefpunkte:\n{num}\n"
            "Danach eine Zeile 'Fazit:' mit der Zahl der AUFFAELLIG-Punkte und deren Nummern, hoechstens ein Satz.")


ANON_NOTE = ("\n\nHINWEIS: Der Text ist anonymisiert. Angaben in eckigen Klammern in Grossbuchstaben, zum Beispiel [BEOBACHTERCODE], [STANDORT], [BREITE], [LAENGE], [PFAD] oder [HOST], "
             "stehen fuer ausgeblendete persoenliche Angaben. Sie sind ausgefuellt und kein Fehler; melde sie nicht als fehlend oder unausgefuellt (bei Punkt 7 gilt zum Beispiel [BEOBACHTERCODE] als vorhanden).")
"""Anhang an den Systemprompt bei anonymisiertem Text. Ohne ihn hielt Claude im Probelauf (2026-11-14) den Platzhalter ``[BEOBACHTERCODE]`` für einen unausgefüllten Code (Fehlalarm bei Punkt 7)."""

@dataclass
class Backend:
    """Ein moeglicher Weg zur KI: ``kind`` ``ollama`` oder ``opencode``; ``usable`` = kann jetzt benutzt werden; ``detail`` erklaert den Zustand."""
    kind: str
    where: str
    usable: bool
    detail: str
    url: str | None = None
    model: str | None = None
    ssh: str | None = None
    strong: bool = False

    def label(self) -> str:
        return f"{self.kind} @ {self.where}" + (f" ({self.model})" if self.model else "")


@dataclass
class ReviewResult:
    """Ergebnis einer Zweitlesung; ``error`` gesetzt = kein Text."""
    text: str = ""
    backend: str = ""
    model: str = ""
    seconds: float = 0.0
    error: str = ""


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Netz und Sicherheit
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def is_private_host(host: str) -> bool:
    """``True`` fuer Loopback, private Adressbereiche (:data:`PRIVATE_NETS`: 10/8, 172.16/12, 192.168/16, Link-Local, fc00::/7) und Namen, die nur darauf aufloesen — **nie** fuer oeffentliche Adressen.

    Warum: Berichtstexte duerfen das eigene Netz nicht verlassen. Grenzen: Ein Name im privaten Netz, der auf einen oeffentlichen Rechner zeigt, wird erkannt (Aufloesung); ein bewusst falsch konfigurierter
    privater Rechner kann den Text trotzdem weitergeben — das liegt ausserhalb dieser Pruefung.
    """
    host = (host or "").strip().strip("[]")
    if not host:
        return False
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        if host.lower() == "localhost":
            return True
        try:
            addrs = [ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, None)]
        except (socket.gaierror, ValueError):
            return False
    return bool(addrs) and all(any(a in n for n in PRIVATE_NETS) for a in addrs)


def _host_of(url: str) -> str:
    """Rechnername/-adresse einer URL (ohne Klammern bei IPv6); leer bei ungueltiger URL."""
    try:
        return urllib.parse.urlsplit(url.strip()).hostname or ""
    except ValueError:
        return ""


def _port_of(url: str, default: int = 11434) -> int:
    """Port einer URL oder ``default``."""
    try:
        return urllib.parse.urlsplit(url.strip()).port or default
    except ValueError:
        return default


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Folgt keinen Weiterleitungen: ein privater Server koennte sonst auf eine oeffentliche Adresse umleiten und die Pruefung :func:`is_private_host` umgehen."""

    def redirect_request(self, *a, **k):
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())     # ohne System-/Umgebungs-Proxy: der Text soll direkt zum Zielrechner, nicht ueber einen Proxy


NO_ROUTE = (65, 113)       # EHOSTUNREACH (macOS, Linux)


def _blocked(e: BaseException) -> bool:
    """``True`` bei „No route to host“ auf einem Rechner, der im Heimnetz sehr wohl erreichbar ist: macOS sperrt dann Programme ohne Freigabe „Lokales Netzwerk“ (Homebrew-Python), waehrend die Systemprogramme
    ``curl``/``nc``/``ssh`` durchkommen. Dann wird auf diese ausgewichen."""
    r = getattr(e, "reason", e)
    return isinstance(r, OSError) and r.errno in NO_ROUTE


def tcp_open(host: str, port: int, timeout: float = 1.5) -> bool:
    """``True``, wenn eine TCP-Verbindung zustande kommt (Rechner erreichbar, Dienst lauscht); bei gesperrtem lokalen Netz (:func:`_blocked`) ersatzweise ``nc -z``."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError as e:
        nc = shutil.which("nc") if _blocked(e) else None
        if nc:
            try:
                return _run([nc, "-z", "-w", str(max(1, int(timeout))), host, str(int(port))], timeout + 3).returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                return False
        return False


def _curl_json(url: str, payload: dict | None, timeout: float) -> dict:
    """Ersatzweg ueber ``curl`` (siehe :func:`_blocked`); gleiche Rueckgabe wie :func:`_http_json`."""
    curl = shutil.which("curl")
    if not curl:
        raise OSError("curl nicht gefunden")
    cmd = [curl, "-sS", "-f", "--noproxy", "*", "-m", str(max(1, int(timeout))), "-H", "Content-Type: application/json"]      # ohne -L: keine Weiterleitungen
    if payload is not None:
        cmd += ["--data-binary", "@-"]
    r = subprocess.run(cmd + [url], input=None if payload is None else json.dumps(payload), capture_output=True, text=True, timeout=timeout + 5, check=False)
    if r.returncode != 0:
        raise OSError(f"curl Rueckgabecode {r.returncode}: {r.stderr.strip()[:160]}")
    return json.loads(r.stdout)


def _http_json(url: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    """GET (ohne ``payload``) oder POST (JSON) und Antwort als Objekt; weigert sich bei nicht privaten Zielen. Bei gesperrtem lokalen Netz Ersatzweg ueber ``curl``."""
    if not is_private_host(_host_of(url)):
        raise ValueError(f"{url}: kein Rechner im privaten Netz — KI-Aufruf abgelehnt")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with _OPENER.open(req, timeout=timeout) as r:                            # Ziel oben auf private Adressen beschraenkt, keine Weiterleitung, kein Proxy
            return json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as e:
        if _blocked(e):
            return _curl_json(url, payload, timeout)
        raise


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
DEFAULT_AI = {"enabled": True, "hosts": [], "local": {"ollama_url": "http://127.0.0.1:11434", "opencode": True, "opencode_model": None}, "models": list(PREFERRED_MODELS),
              "cloud": {"enabled": False, "model": None, "max_chars": 20000}}


def load_ai_config(path=None) -> dict:
    """Schluessel ``ai`` aus ``observer.json`` (fehlende Teile aus :data:`DEFAULT_AI`); ``VARPHOT_AI=off`` setzt ``enabled`` auf ``False``."""
    from .observer import config_path
    p = config_path(path)
    raw = {}
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8")).get("ai", {}) or {}
        except (OSError, ValueError):
            raw = {}
    cfg = {**DEFAULT_AI, **raw}
    cfg["local"] = {**DEFAULT_AI["local"], **(raw.get("local") or {})}
    cfg["cloud"] = {**DEFAULT_AI["cloud"], **(raw.get("cloud") or {})}
    if os.environ.get("VARPHOT_AI", "").lower() in ("off", "0", "no", "nein"):
        cfg["enabled"] = False
    if os.environ.get("VARPHOT_AI_CLOUD", "").lower() in ("off", "0", "no", "nein"):
        cfg["cloud"]["enabled"] = False
    return cfg


def save_ai_config(cfg: dict, path=None) -> Path:
    """Schreibt ``ai`` in ``observer.json`` und laesst alle anderen Schluessel unveraendert (Rechte nur fuer den Benutzer)."""
    from .observer import config_path
    p = config_path(path)
    raw = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    raw["ai"] = cfg
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    p.chmod(0o600)
    return p


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Modelle und Backends finden
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def ollama_models(url: str, timeout: float = 5.0) -> list[str]:
    """Namen der Modelle eines Ollama-Servers (``/api/tags``); leere Liste bei Fehler."""
    try:
        return [m["name"] for m in _http_json(url.rstrip("/") + "/api/tags", timeout=timeout).get("models", [])]
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        return []


def pick_model(available: list[str], preferred: list[str] | None = None) -> str | None:
    """Erstes bevorzugtes Modell, das vorhanden ist (Namen ohne ``:latest`` gelten gleich); sonst das erste nicht-Einbettungsmodell; sonst ``None``."""
    norm = lambda n: n[:-7] if n.endswith(":latest") else n
    have = {norm(m): m for m in available}
    for p in preferred or PREFERRED_MODELS:
        if norm(p) in have:
            return have[norm(p)]
    for m in available:
        if not any(x in m.lower() for x in NOT_FOR_CHAT):
            return m
    return None


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, check=False)


def probe_opencode_local(model: str | None = None, timeout: float = 40.0) -> Backend:
    """Prueft Opencode auf diesem Rechner: vorhanden **und** ein lokales Modell (nicht ``opencode/*``, das ist Cloud).

    Wie: ``opencode models`` auflisten; ``model`` (Konfiguration) muss darin stehen, sonst gilt das erste Modell mit lokalem Anbieter-Praefix (:data:`LOCAL_OPENCODE_PROVIDERS`). Ohne lokales Modell ist das Backend
    **nicht benutzbar** und ``detail`` sagt warum — der Berichtstext wuerde sonst das Heimnetz verlassen.
    """
    exe = shutil.which("opencode")
    if not exe:
        return Backend("opencode", "lokal", False, "nicht installiert")
    try:
        r = _run([exe, "models"], timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return Backend("opencode", "lokal", False, f"'opencode models' fehlgeschlagen: {type(e).__name__}")
    models = [ln.strip() for ln in r.stdout.splitlines() if "/" in ln.strip() and " " not in ln.strip()]
    if model:
        chosen = model if model in models else None
    else:
        chosen = next((m for m in models if m.split("/", 1)[0].lower().startswith(LOCAL_OPENCODE_PROVIDERS)), None)
    if chosen is None:
        n_cloud = sum(m.startswith("opencode/") for m in models)
        why = f"Modell '{model}' nicht bei Opencode eingerichtet" if model else f"nur Cloud-Modelle ({n_cloud} 'opencode/*') — kein lokaler Anbieter"
        return Backend("opencode", "lokal", False, why + "; Berichtstext wuerde das Heimnetz verlassen")
    return Backend("opencode", "lokal", True, "lokales Modell eingerichtet", model=chosen)


def probe_opencode_remote(ssh_alias: str, timeout: float = 8.0) -> bool:
    """``True``, wenn Opencode auf dem Rechner ``ssh_alias`` vorhanden ist (``ssh -o BatchMode=yes … command -v opencode``); jeder Fehler (kein Schluessel, nicht erreichbar) ergibt ``False``."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", ssh_alias or ""):
        return False
    try:
        r = _run(["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(timeout)}", ssh_alias, "command -v opencode"], timeout + 4)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def detect_backends(cfg: dict | None = None, check_opencode_remote: bool = True) -> list[Backend]:
    """Alle Wege zur KI in der Reihenfolge ihres Vorrangs (benutzbare haben ``usable=True``); :func:`choose_backend` nimmt den ersten benutzbaren.

    Reihenfolge: je staerkerem Rechner (Adressen der Reihe nach, erste erreichbare): Opencode-Pruefung per ``ssh`` (Aufruf noch nicht eingebaut → nie benutzbar), dann Ollama; danach lokal Opencode, dann Ollama.
    ``enabled=False`` → leere Liste. Prueft nur die Erreichbarkeit/Modelle, ruft kein Modell auf (schnell: wenige Sekunden, bei nicht erreichbarem Rechner je Adresse 1,5 s).
    """
    cfg = cfg or load_ai_config()
    if not cfg.get("enabled", True):
        return []
    out: list[Backend] = []
    for h in cfg.get("hosts", []):
        name, port = h.get("name", "?"), int(h.get("ollama_port", 11434))
        addr = next((a for a in h.get("addresses", []) if is_private_host(a) and tcp_open(a, port)), None)
        if addr is None:
            out.append(Backend("ollama", name, False, "nicht erreichbar (keine Adresse antwortet)", strong=True))
            continue
        via = f"{name} ({addr})"
        if check_opencode_remote and h.get("ssh"):
            has = probe_opencode_remote(h["ssh"])
            out.append(Backend("opencode", via, False, "vorhanden, Aufruf per ssh noch nicht eingebaut — Ollama wird benutzt" if has else "dort nicht installiert", ssh=h["ssh"], strong=True))
        url = f"http://{addr}:{port}" if ":" not in addr else f"http://[{addr}]:{port}"
        models = ollama_models(url)
        model = pick_model(models, cfg.get("models"))
        out.append(Backend("ollama", via, model is not None, f"{len(models)} Modelle" if model else "Server antwortet, aber kein brauchbares Chat-Modell", url=url, model=model, strong=True))
    if cfg["local"].get("opencode", True):                    # "opencode": false schaltet die Pruefung ab (``opencode models`` startet dessen Hintergrunddienst)
        out.append(probe_opencode_local(cfg["local"].get("opencode_model")))
    url = cfg["local"].get("ollama_url") or DEFAULT_AI["local"]["ollama_url"]
    if is_private_host(_host_of(url)) and tcp_open(_host_of(url), _port_of(url)):
        models = ollama_models(url)
        model = pick_model(models, cfg.get("models"))
        out.append(Backend("ollama", "lokal", model is not None, f"{len(models)} Modelle" if model else "Server antwortet, aber kein brauchbares Chat-Modell", url=url, model=model))
    else:
        out.append(Backend("ollama", "lokal", False, "nicht installiert oder nicht gestartet"))
    return out


CLAUDE_ISOLATION = ["--tools", "", "--disable-slash-commands", "--strict-mcp-config", "--setting-sources", ""]
"""Optionen für den Claude-Aufruf: keine Werkzeuge, keine Skills, keine MCP-Server, keine Einstellungsquellen. Gemessen am 2026-11-14: **ohne** diese Optionen geht der gesamte Arbeitskontext mit
(rund 37 000 Eingabe-Tokens, die Anweisungen der eigenen ``CLAUDE.md`` waren dem Modell bekannt), **mit** ihnen nur Systemanweisung und Text (rund 860 Tokens, die ``CLAUDE.md`` war unbekannt)."""
CLOUD_KEYS_REMOVED = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def probe_claude_cli(timeout: float = 20.0) -> Backend:
    """Prueft die Claude-Kommandozeile: vorhanden **und** angemeldet (``claude auth status``, lokale Abfrage ohne Modellaufruf).

    Die Anmeldung der Kommandozeile ist **getrennt** von der der Desktop-App; fehlt sie, sagt ``detail`` den Befehl (``claude auth login``). Die Anmeldeart (Abo oder API-Schluessel) steht im Detail,
    Kontodaten nicht.
    """
    exe = shutil.which("claude")
    if not exe:
        return Backend("claude-cli", "Cloud", False, "nicht installiert (Programm 'claude' nicht gefunden)")
    try:
        r = _run([exe, "auth", "status"], timeout)
        info = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return Backend("claude-cli", "Cloud", False, f"'claude auth status' fehlgeschlagen: {type(e).__name__}")
    if not info.get("loggedIn"):
        return Backend("claude-cli", "Cloud", False, "nicht angemeldet: im Terminal 'claude auth login' ausfuehren")
    return Backend("claude-cli", "Cloud", True, f"angemeldet ({info.get('authMethod', '?')})")


def detect_cloud_backends(cfg: dict | None = None) -> list[Backend]:
    """Cloud-Wege (nie automatisch gewaehlt: :func:`choose_backend` und :func:`detect_backends` kennen sie nicht).

    Ohne ``ai.cloud.enabled`` (oder mit ``VARPHOT_AI=off``/``VARPHOT_AI_CLOUD=off``) ist jeder Weg **nicht benutzbar** und ``detail`` nennt den Schalter; die Kommandozeile wird dann gar nicht aufgerufen.
    Gemini ist noch nicht eingerichtet (KONZEPT §11.15).
    """
    cfg = cfg or load_ai_config()
    cloud = cfg.get("cloud", {})
    if not cfg.get("enabled", True) or not cloud.get("enabled", False):
        why = "nicht eingeschaltet (observer.json: ai.cloud.enabled = true)"
        return [Backend("claude-cli", "Cloud", False, why), Backend("gemini-api", "Cloud", False, why)]
    claude = probe_claude_cli()
    claude.model = cloud.get("model") or None
    return [claude, Backend("gemini-api", "Cloud", False, "noch nicht eingerichtet (KONZEPT §11.15)")]


def cloud_preflight_lines(cfg: dict | None = None) -> list[tuple[str, bool, str]]:
    """Zeile fuer die Vorbedingungen: ``Cloud-KI`` aus oder bereit; ohne Einschalten kein Programmaufruf."""
    bk = detect_cloud_backends(cfg)[0]
    return [("Cloud-KI Claude", bk.usable, ("bereit (nur mit Einwilligung je Lauf, Text wird anonymisiert) — " if bk.usable else "") + bk.detail)]


def choose_backend(backends: list[Backend]) -> Backend | None:
    """Erster benutzbarer Weg (Vorrang = Reihenfolge der Liste); ``None``, wenn keiner geht."""
    return next((b for b in backends if b.usable), None)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Aufruf
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
_THINK = re.compile(r"<think>.*?</think>", re.S)


def _clean(text: str) -> str:
    return _THINK.sub("", text).strip()


def ai_review(text: str, backend: Backend, system: str = SYSTEM_PROMPT, timeout: float = 300.0) -> ReviewResult:
    """Laesst das Modell ``text`` lesen und liefert dessen Anmerkungen (**unverbindlich**, nie in Daten uebernehmen).

    Claude-Kommandozeile (Cloud, nur mit anonymisiertem Text, siehe :mod:`varphot.anonymize`): ``claude -p`` mit :data:`CLAUDE_ISOLATION` im leeren Wegwerf-Ordner. Ollama: ``POST /api/chat`` (ohne Streaming, Temperatur 0,2). Opencode (lokal): ``opencode run --model … <Nachricht>`` in einem leeren Wegwerf-Ordner (kein Zugriff auf Projektdateien), mit Zeitlimit.
    Jeder Fehler (Zeitlimit, Verbindung, leere Antwort) kommt als ``ReviewResult.error`` zurueck, nie als Ausnahme — die Zweitlesung darf den Export nicht blockieren.
    """
    if backend is None:                                              # kein Weg gefunden: als Ergebnis melden, nicht als Ausnahme (die Zweitlesung darf den Export nie blockieren)
        return ReviewResult(error="kein KI-Weg verfuegbar (detect_backends/choose_backend lieferten keinen)")
    t0 = time.time()
    res = ReviewResult(backend=backend.label(), model=backend.model or "")
    try:
        if backend.kind == "ollama":
            if not backend.url or not backend.model:
                raise ValueError("Ollama-Backend ohne URL oder Modell")
            d = _http_json(backend.url.rstrip("/") + "/api/chat", {"model": backend.model, "stream": False, "options": {"temperature": 0.2, "num_ctx": 8192},
                                                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}, timeout=timeout)
            res.text = _clean(d.get("message", {}).get("content", ""))
        elif backend.kind == "opencode" and backend.model and not backend.ssh:
            exe = shutil.which("opencode")
            if not exe:
                raise FileNotFoundError("opencode nicht gefunden")
            with tempfile.TemporaryDirectory() as tmp:
                r = subprocess.run([exe, "run", "--model", backend.model, system + "\n\n--- BERICHT ---\n" + text], capture_output=True, text=True, timeout=timeout, cwd=tmp, stdin=subprocess.DEVNULL, check=False)
            if r.returncode != 0:
                raise RuntimeError(f"opencode Rueckgabecode {r.returncode}: {r.stderr.strip()[:200]}")
            res.text = _clean(r.stdout)
        elif backend.kind == "claude-cli":
            exe = shutil.which("claude")
            if not exe:
                raise FileNotFoundError("claude nicht gefunden")
            env = {k: v for k, v in os.environ.items() if k not in CLOUD_KEYS_REMOVED}               # Abo-Anmeldung, nie ein zufaellig gesetzter Schluessel
            cmd = [exe, "-p", "--no-session-persistence", "--output-format", "text", "--system-prompt", system, *CLAUDE_ISOLATION] + (["--model", backend.model] if backend.model else [])
            with tempfile.TemporaryDirectory() as tmp:                                              # leerer Wegwerf-Ordner, Text ueber die Standardeingabe (nicht in der Prozessliste)
                r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=timeout, cwd=tmp, env=env, check=False)
            if r.returncode != 0:
                raise RuntimeError(f"claude Rueckgabecode {r.returncode}: {r.stderr.strip()[:200]}")
            res.text = _clean(r.stdout)
        else:
            raise ValueError(f"Backend {backend.label()} ist nicht aufrufbar")
        if not res.text:
            res.error = "leere Antwort"
    except subprocess.TimeoutExpired:
        res.error = f"Zeitlimit ({timeout:g} s)"
    except (OSError, ValueError, RuntimeError, urllib.error.URLError) as e:
        res.error = f"{type(e).__name__}: {e}"
    res.seconds = round(time.time() - t0, 1)
    return res


def preflight_lines(backends: list[Backend]) -> list[tuple[str, bool, str]]:
    """Zeilen (Name, ok, Text) fuer die Vorbedingungs-Tabelle in NB00 (Schritt 1.1); ``ok`` ist nur beim gewaehlten Weg wahr."""
    chosen = choose_backend(backends)
    rows = [(f"KI: {b.label()}", b is chosen, ("benutzt — " if b is chosen else "") + b.detail) for b in backends]
    if not backends:
        rows.append(("KI-Zweitlesung", False, "abgeschaltet (VARPHOT_AI=off oder enabled=false)"))
    elif chosen is None:
        rows.append(("KI-Zweitlesung", False, "kein Weg verfuegbar (optional — der Bericht wird dann ohne KI-Lesung erzeugt)"))
    return rows
