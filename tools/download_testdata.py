#!/usr/bin/env python
"""Testdaten laden: ``python tools/download_testdata.py lco-dcep hatp32 [--dest ORDNER] [--dry-run] [--list]``.

Quellen, Umfang und Nutzungsbedingungen: README.md (Beispieldaten) und docs/testdaten.md.
Standardziel: PHOTOMETRIE_PY_DATA/testdata neben dem Repo (Nextcloud; sonst ~/astro_testdata; VARPHOT_TESTDATA ueberschreibt); Zertifikate werden immer geprueft.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from varphot.testdata import DATASETS, download_dataset, testdata_dir  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("datasets", nargs="*", help=f"Datensaetze: {', '.join(DATASETS)}")
    ap.add_argument("--dest", type=Path, help="Zielordner (je Datensatz ein Unterordner); Standard: %s" % testdata_dir())
    ap.add_argument("--dry-run", action="store_true", help="nur anzeigen, was geladen wuerde")
    ap.add_argument("--list", action="store_true", help="Datensaetze anzeigen")
    a = ap.parse_args(argv)
    if a.list or not a.datasets:
        for k, v in DATASETS.items():
            print(f"{k:9s} {v['n_frames']:4d} Dateien, ~{v['size_mb']} MB  {v['title']}\n{'':9s} Quelle: {v['source']}")
        return 0
    for name in a.datasets:
        download_dataset(name, (a.dest / name) if a.dest else None, a.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
