"""Notebook headless ausfuehren (fuer Testdurchfuehrungen): gleiche Zellen wie im Jupyter, Ergebnis als Kopie, Fortschritt live auf der Konsole.

Warum: Testfaelle brauchen **exakte, wiederholbare** Schritte. Das Quellnotebook bleibt unveraendert (nbstripout!); die ausgefuehrte Kopie mit allen Ausgaben liegt im Ausgabeordner und ist der Beleg
der Testdurchfuehrung. Jede Zelle meldet sich sofort (Nummer, Dauer, erste Ausgabezeile), damit ein Lauf live mitverfolgt werden kann (`tail -f` auf die Log-Datei oder direkt im Terminal).

Aufruf (Arbeitsordner = Repo-Wurzel)::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/run_notebook.py notebooks/00_planung.ipynb --out /tmp/lauf --env VARPHOT_NB00_MODE=demo --env VARPHOT_WORKSPACE=/tmp/lauf/ws

``--env SCHLUESSEL=WERT`` setzt Umgebungsvariablen fuer den Kernel (die Formulare der Notebooks lesen sie als Vorbelegung). Rueckgabecode 0 = alle Zellen fehlerfrei; 1 = Zellenfehler (Zellennummer und Meldung stehen im Protokoll);
2 = Aufruffehler. Grenzen: Widgets werden nur mit ihren Vorgabewerten (aus den Umgebungsvariablen) ausgefuehrt — eine manuelle Eingabe im Formular ersetzt der Lauf nicht.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError


def _first_line(cell) -> str:
    for o in cell.get("outputs", []):
        txt = o.get("text") or (o.get("data", {}).get("text/plain")) or ""
        if isinstance(txt, list):
            txt = "".join(txt)
        for ln in str(txt).splitlines():
            if ln.strip():
                return ln.strip()[:150]
        if o.get("output_type") == "error":
            return f"FEHLER {o.get('ename')}: {str(o.get('evalue'))[:120]}"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("notebook")
    ap.add_argument("--out", required=True, help="Ausgabeordner fuer die ausgefuehrte Kopie")
    ap.add_argument("--env", action="append", default=[], help="SCHLUESSEL=WERT fuer den Kernel (mehrfach)")
    ap.add_argument("--kernel", default="photometrie-py")
    ap.add_argument("--timeout", type=int, default=900, help="Sekunden je Zelle")
    a = ap.parse_args(argv)
    src = Path(a.notebook).resolve()
    if not src.is_file():
        print("Notebook nicht gefunden:", src)
        return 2
    for kv in a.env:
        if "=" not in kv:
            print("--env erwartet SCHLUESSEL=WERT:", kv)
            return 2
        k, v = kv.split("=", 1)
        os.environ[k] = v
    out = Path(a.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    nb = nbformat.read(src, as_version=4)
    t0 = time.time()
    state = {"i": 0}

    def on_done(cell, cell_index, execute_reply, **kw):
        if cell.cell_type == "code":
            state["i"] += 1
            print(f"[{time.time() - t0:6.1f}s] Zelle {cell_index:2d}: {_first_line(cell)}", flush=True)

    client = NotebookClient(nb, timeout=a.timeout, kernel_name=a.kernel, resources={"metadata": {"path": str(src.parent)}}, on_cell_executed=on_done)
    rc = 0
    try:
        client.execute()
    except CellExecutionError as e:
        print("ABBRUCH:", str(e).splitlines()[-1][:300], flush=True)
        rc = 1
    dst = out / (src.stem + ".ausgefuehrt.ipynb")
    nbformat.write(nb, dst)
    print(f"Ergebnis: {'OK' if rc == 0 else 'FEHLER'} · {state['i']} Codezellen · {time.time() - t0:.0f} s · Kopie: {dst}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
