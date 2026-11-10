"""Oeffentliche Testdatensaetze: Quellen, Auswahl und Download (mit Pruefsummen).

Warum: Die Pipeline wird an echten Bildern geprueft, die nicht im (oeffentlichen) Repo liegen duerfen — zu gross und
mit eigenen Nutzungsbedingungen. Dieses Modul beschreibt die Quellen und holt die Dateien reproduzierbar.

Wie: ``download_dataset("lco-dcep")`` fragt die Archiv-/Repo-API ab, filtert wie unten dokumentiert und laedt in
``testdata_dir()`` (Standard ``PHOTOMETRIE_PY_DATA/testdata`` neben dem Repo — liegt im Nextcloud-Ordner und ist damit gesichert, vom Nutzer
ausdruecklich gewuenscht; ohne Datenordner ``~/astro_testdata``; ueberschreibbar mit ``VARPHOT_TESTDATA``). Vorhandene Dateien werden nicht erneut geladen, wenn die Pruefsumme (LCO: MD5) bzw. die Groesse
(GitHub) stimmt. TLS-Zertifikate werden immer geprueft.

Quellen und Bedingungen siehe ``README.md`` (Abschnitt Beispieldaten) und ``docs/testdaten.md``.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

LCO_API = "https://archive-api.lco.global/frames/"
EXOTIC_API = "https://api.github.com/repos/rzellem/EXOTIC_sampledata/contents/HatP32Dec202017"

DATASETS = {
    "lco-dcep": dict(
        title="delta Cep, Filter V, LCO 0,4-m-Teleskop elp0m411 (McDonald), 2018-2020",
        source="Las Cumbres Observatory, oeffentliches Archiv (https://archive.lco.global), BANZAI-reduziert",
        n_frames=156, size_mb=1100,
    ),
    "hatp32": dict(
        title="HAT-P-32 b Transit, MicroObservatory (CfA), 2017-12-20, 142 Bilder",
        source="https://github.com/rzellem/EXOTIC_sampledata (Beispielsatz des Programms EXOTIC)",
        n_frames=142, size_mb=89,
    ),
}


def testdata_dir() -> Path:
    """Ordner der Testdaten: ``VARPHOT_TESTDATA``, sonst ``PHOTOMETRIE_PY_DATA/testdata`` (wenn der Datenordner existiert), sonst ``~/astro_testdata``."""
    if os.environ.get("VARPHOT_TESTDATA"):
        return Path(os.environ["VARPHOT_TESTDATA"]).expanduser()
    from .observer import data_dir
    return data_dir() / "testdata" if data_dir().is_dir() else Path("~/astro_testdata").expanduser()


def md5sum(path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _get_json(url: str, params=None, tries: int = 3):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def lco_frames(object_name: str = "delta Cep", filt: str = "V", basename_prefix: str = "elp0m411-",
               reduction_level: int = 91) -> list[dict]:
    """Rahmenliste aus dem oeffentlichen LCO-Archiv.

    Der anonyme Zugang erlaubt hoechstens 100 Eintraege je Abfrage (``limit``); es wird mit ``offset`` geblaettert.
    Der Archiv-``count`` ist unzuverlaessig (meldete 24 statt 259) — es wird bis zur ersten kurzen Seite gelesen.
    ``basename_prefix`` waehlt ein Teleskop (``elp0m411`` = Standort elp, Teleskop 0m4-11); ``reduction_level=91`` sind
    die BANZAI-reduzierten Bilder. Jeder Eintrag enthaelt ``filename``, ``url`` (signiert, ca. 2 Tage gueltig) und
    ``version_set[0]['md5']``.
    """
    out, offset = [], 0
    while True:
        page = _get_json(LCO_API, dict(OBJECT=object_name, public="true", reduction_level=reduction_level,
                                       primary_optical_element=filt, limit=100, offset=offset))["results"]
        out += [f for f in page if f["basename"].startswith(basename_prefix)]
        if len(page) < 100:
            return out
        offset += 100


def download_file(url: str, dest: Path, md5: str | None = None, size: int | None = None) -> str:
    """Laedt eine Datei atomar (``.part`` -> Zielname); Rueckgabe ``'vorhanden'`` oder ``'geladen'``.

    Eine vorhandene Datei bleibt, wenn MD5 bzw. Groesse stimmen. Stimmt die Pruefsumme nach dem Laden nicht,
    wird die Datei verworfen und ein ``IOError`` ausgeloest.
    """
    dest = Path(dest)
    if dest.exists() and ((md5 and md5sum(dest) == md5) or (not md5 and size and dest.stat().st_size == size)):
        return "vorhanden"
    part = dest.with_name(dest.name + ".part")
    for i in range(3):
        try:
            with requests.get(url, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(part, "wb") as f:
                    for block in r.iter_content(1 << 20):
                        f.write(block)
            break
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(2 * (i + 1))
    if (md5 and md5sum(part) != md5) or (size and part.stat().st_size != size):
        part.unlink(missing_ok=True)
        raise IOError(f"{dest.name}: Pruefsumme/Groesse stimmt nicht")
    part.replace(dest)
    return "geladen"


def hatp32_files() -> list[dict]:
    """Dateiliste des EXOTIC-Beispielsatzes (GitHub-API: ``name``, ``size``, ``download_url``)."""
    return [f for f in _get_json(EXOTIC_API) if f["type"] == "file"]


def download_dataset(name: str, dest: Path | None = None, dry_run: bool = False, progress=print) -> Path:
    """Laedt einen Datensatz aus :data:`DATASETS` nach ``dest`` (Standard ``testdata_dir()/<name>``)."""
    if name not in DATASETS:
        raise KeyError(f"unbekannter Datensatz '{name}' (gueltig: {', '.join(DATASETS)})")
    dest = Path(dest or testdata_dir() / name)
    if name == "lco-dcep":
        jobs = [(f["filename"], f["url"], f["version_set"][0]["md5"], None) for f in lco_frames()]
    else:
        jobs = [(f["name"], f["download_url"], None, f["size"]) for f in hatp32_files()]
    progress(f"{name}: {len(jobs)} Dateien -> {dest}")
    if dry_run:
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for i, (fn, url, md5, size) in enumerate(jobs, 1):
        state = download_file(url, dest / fn, md5, size)
        if state == "geladen" or i % 25 == 0 or i == len(jobs):
            progress(f"  [{i}/{len(jobs)}] {fn}: {state}")
    return dest
