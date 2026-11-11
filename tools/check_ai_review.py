"""Zeigt den gewaehlten KI-Weg und laesst die Zweitlesung einen Bericht mit offensichtlichen Fehlern pruefen (Testfall KI-Zweitlesung).

Aufruf::

    cd ~/Nextcloud/WORKSPACE/ASTRO/PHOTOMETRIE_PY && .venv/bin/python tools/check_ai_review.py

Ausgabe: alle Wege mit Zustand, den gewaehlten Weg und die Antwort (Zeilen ``N. OK`` / ``N. AUFFAELLIG``, ``Fazit``). Rueckgabecode 0 = Antwort mit ``Fazit`` erhalten; 3 = **kein Weg verfuegbar** (Ausfallfall:
das Skript meldet das sauber, wirft keine Ausnahme); 1 = Weg gewaehlt, aber Aufruf gescheitert. Der Bericht ist erfunden (TG mit TRANS=YES, OBSTYPE=CCD, Zeitraum verkehrt, Fehler 0,0004 mag); erwartet wird, dass
mindestens zwei dieser Fehler als AUFFAELLIG erscheinen (Kleine Modelle irren — die Ausgabe ist ein Hinweis, kein Beweis).
"""
import sys

from varphot import ai_review, choose_backend, detect_backends, load_ai_config

TEXT = ("# Export\n- Filter: TG (Bayer)\n- TRANS: YES\n- OBSTYPE: CCD\n- Zeitraum: JD 2461000.3 - 2461000.1\n- Mittlerer Fehler: 0.0004 mag\nWarnungen: keine\n")


def main() -> int:
    bs = detect_backends(load_ai_config())
    for b in bs:
        print("  ", "✓" if b.usable else "·", b.label(), "—", b.detail)
    ch = choose_backend(bs)
    print("gewaehlt:", ch.label() if ch else None)
    r = ai_review(TEXT, ch, timeout=300)
    if ch is None:
        print("kein KI-Weg verfuegbar:", r.error)
        return 3
    print(r.error or r.text)
    return 0 if (r.text and "Fazit" in r.text) else 1


if __name__ == "__main__":
    sys.exit(main())
