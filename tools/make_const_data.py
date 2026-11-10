#!/usr/bin/env python3
"""
Einmaliges Setup: data/constellation_lines.json generieren.

Liest Sternbild-Topologie aus data/const_topology.json (gebündelt, kein Netz nötig),
fragt SIMBAD (Harvard Mirror) via direkten HTTP/ADQL-POST nach RA/Dec/Magnitude
und speichert das Ergebnis in data/constellation_lines.json.

Laufzeit: ~1–3 Min (einmalige SIMBAD-Abfrage).
Ausführen aus dem Projektstamm:
    python tools/make_const_data.py
"""

import json
import time
from pathlib import Path

try:
    import requests
except ImportError as e:
    raise SystemExit("Fehlende Abhängigkeit: pip install requests") from e

ROOT   = Path(__file__).resolve().parent.parent
TOPO   = ROOT / "data" / "const_topology.json"
OUTPUT = ROOT / "data" / "constellation_lines.json"

# SIMBAD TAP-Sync via Harvard Mirror (cds.unistra.fr antwortet mit 404 auf /simbad/)
SIMBAD_TAP = "https://simbad.harvard.edu/simbad/sim-tap/sync"

# SIMBAD verwendet abweichende Abkürzungen für einige griechische Buchstaben
_TOPO_TO_SIMBAD = {"mu": "mu.", "nu": "nu.", "xi": "ksi", "pi": "pi.", "the": "tet"}
_SIMBAD_TO_TOPO = {v: k for k, v in _TOPO_TO_SIMBAD.items()}

import re as _re

def _split_bayer(name: str):
    """'xi02 CMa' → ('xi', '02', 'CMa')   'alf Vel' → ('alf', '', 'Vel')"""
    m = _re.match(r'^([a-z]+\.?)(\d+)?\s+(.+)$', name)
    if m:
        return m.group(1), m.group(2) or '', m.group(3)
    return name, '', ''

if not TOPO.exists():
    raise SystemExit(f"Topologie-Datei nicht gefunden: {TOPO}")

topology = json.loads(TOPO.read_text())

# Alle eindeutigen Sternbezeichnungen sammeln
all_names: set[str] = set()
for entry in topology.values():
    for s1, s2 in entry["lines"]:
        all_names.add(s1)
        all_names.add(s2)

star_list = sorted(all_names)
print(f"Topologie geladen: {len(topology)} Sternbilder, {len(star_list)} eindeutige Sterne")
print(f"SIMBAD-Endpunkt:   {SIMBAD_TAP}\n")
print("Frage SIMBAD …")


def _simbad_id(name: str) -> str:
    """'xi02 CMa' → '* ksi02 CMa'   'mu Cep' → '* mu. Cep'   '1 Vul' → '* 1 Vul'"""
    if not name or name[0].isdigit():
        return f"* {name}"   # Flamsteed-Nummern unverändert
    greek, num, con = _split_bayer(name)
    simbad_greek = _TOPO_TO_SIMBAD.get(greek, greek)
    return f"* {simbad_greek}{num} {con}"


def _topo_name(simbad_raw: str) -> str:
    """'ksi02 CMa' → 'xi02 CMa'   'mu. Cep' → 'mu Cep'   '  1 Vul' → '1 Vul'"""
    name = simbad_raw.strip()
    greek, num, con = _split_bayer(name)
    topo_greek = _SIMBAD_TO_TOPO.get(greek, greek)
    if num:
        result = f"{topo_greek}{num} {con}"
        # Albireo-Muster: SIMBAD kennt 'bet01 Cyg', Topologie hat 'bet Cyg'
        if result not in all_names and num == "01":
            result = f"{topo_greek} {con}"
    else:
        result = f"{topo_greek} {con}" if con else topo_greek
    return result


def query_simbad_batch(names: list[str]) -> dict[str, dict]:
    """
    Fragt RA, Dec, V-Magnitude für eine Liste von Sternnamen via ADQL.
    Gibt {originalname: {ra, dec, mag}} zurück.
    """
    sids    = [_simbad_id(n) for n in names]
    id_list = ", ".join(f"'{sid}'" for sid in sids)
    adql    = (
        "SELECT id.id AS queried_id, b.ra, b.dec, f.V "
        "FROM ident AS id "
        "JOIN basic AS b ON id.oidref = b.oid "
        "LEFT JOIN allfluxes AS f ON id.oidref = f.oidref "
        f"WHERE id.id IN ({id_list})"
    )

    try:
        resp = requests.post(
            SIMBAD_TAP,
            data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": adql},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    HTTP-Fehler: {exc}")
        return {}

    try:
        payload = resp.json()
    except ValueError:
        print("    JSON-Parse-Fehler")
        return {}

    result: dict[str, dict] = {}
    for row in payload.get("data", []):
        qid, ra_raw, dec_raw, v_raw = row[0], row[1], row[2], row[3]
        raw = str(qid).strip()
        if raw.startswith("* "):
            raw = raw[2:]
        orig = _topo_name(raw)   # SIMBAD→Topologie übersetzen + Flamsteed-Leerzeichen streifen
        if orig not in all_names:
            continue
        try:
            ra  = float(ra_raw)
            dec = float(dec_raw)
        except (TypeError, ValueError):
            continue
        try:
            mag = float(v_raw)
        except (TypeError, ValueError):
            mag = 5.0   # Standardwert bei fehlender V-Magnitude

        if orig not in result:   # erstes Vorkommen gewinnt
            result[orig] = {"ra": round(ra, 6), "dec": round(dec, 6), "mag": round(mag, 2)}

    return result


# ---------------------------------------------------------------------------
# Batch-Abfragen
# ---------------------------------------------------------------------------
BATCH_SIZE    = 80
star_data: dict[str, dict] = {}
batches_total = (len(star_list) - 1) // BATCH_SIZE + 1

for i in range(0, len(star_list), BATCH_SIZE):
    batch   = star_list[i : i + BATCH_SIZE]
    batch_n = i // BATCH_SIZE + 1

    found = query_simbad_batch(batch)
    new   = {k: v for k, v in found.items() if k not in star_data}
    star_data.update(new)
    print(f"  Batch {batch_n}/{batches_total}: "
          f"{len(new)} neu aufgelöst  (Gesamt: {len(star_data)})")
    if batch_n < batches_total:
        time.sleep(0.5)   # SIMBAD-Ratenlimit respektieren

print(f"\nSterne aufgelöst: {len(star_data)} / {len(star_list)}")
if len(star_data) < len(star_list) * 0.7:
    print("⚠  Weniger als 70 % aufgelöst — ggf. SIMBAD-Verbindungsproblem.")

# ---------------------------------------------------------------------------
# Ausgabe-JSON aufbauen
# ---------------------------------------------------------------------------
output: dict = {}
for abbrev, entry in topology.items():
    cname     = entry["name"]
    stars_in: dict[str, dict] = {}
    lines_ok: list            = []

    for s1, s2 in entry["lines"]:
        if s1 in star_data and s2 in star_data:
            lines_ok.append([s1, s2])
            stars_in[s1] = star_data[s1]
            stars_in[s2] = star_data[s2]

    output[abbrev] = {"name": cname, "stars": stars_in, "lines": lines_ok}

OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False))
print(f"\nGespeichert: {OUTPUT}")
print(f"Sternbilder mit mind. 1 Linie: "
      f"{sum(1 for v in output.values() if v['lines'])}/{len(output)}")
