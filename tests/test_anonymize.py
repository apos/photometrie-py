"""Datenanonymisierung vor dem Senden an eine Cloud-KI (varphot.anonymize): Beobachtercode, Standort, Koordinaten, Pfade, Rechner, E-Mail."""
from types import SimpleNamespace

import pytest

from varphot import anonymize as A

OBS = SimpleNamespace(aavso_code="ABCD", site_name="Balkon Musterstadt")
SITES = [SimpleNamespace(name="Balkon Musterstadt", lat_deg=49.3212, lon_deg=-7.5481, height_m=120.0)]
AI = {"hosts": [{"name": "rechner", "addresses": ["192.168.7.20", "10.8.0.5"], "ssh": "meinalias"}], "local": {"ollama_url": "http://127.0.0.1:11434"}}
HOME = "/Users/maxmuster"
BERICHT = """#OBSCODE=ABCD
#NOTES Standort Balkon Musterstadt, Breite 49.3212, Länge -7.5481 (49,32 N), Daten in /Users/maxmuster/Nextcloud/DATA/exports/x.txt
Kontakt max@example.org, Rechner rechner (192.168.7.20) und 10.8.0.5, Alias meinalias. Beobachter ABCD meldet delta Cep, V = 3.8, 12 Punkte.
"""


@pytest.fixture
def secrets():
    return A.collect_secrets(OBS, SITES, AI, home=HOME)


def test_collects_known_values_from_config(secrets):
    kinds = {(s.kind, s.value) for s in secrets}
    assert ("code", "ABCD") in kinds and ("site", "Balkon Musterstadt") in kinds and ("host", "192.168.7.20") in kinds and ("host", "meinalias") in kinds
    assert ("path", HOME) in kinds and ("user", "maxmuster") in kinds
    assert not any(s.value in ("127.0.0.1",) for s in secrets)                       # lokaler Ollama zählt nicht als geheim


def test_anonymize_replaces_everything_and_keeps_the_science(secrets):
    r = A.anonymize(BERICHT, secrets)
    for geheim in ("ABCD", "Balkon", "49.3212", "-7.5481", "49,32", "maxmuster", "max@example.org", "192.168.7.20", "10.8.0.5", "meinalias", "rechner"):
        assert geheim not in r.text, geheim
    for bleibt in ("delta Cep", "V = 3.8", "12 Punkte"):
        assert bleibt in r.text
    assert "[BEOBACHTERCODE]" in r.text and "[STANDORT]" in r.text and "[BREITE]" in r.text and "[LAENGE]" in r.text and "[PFAD]" in r.text
    assert r.counts["code"] == 2 and r.counts["email"] == 1


def test_distinct_values_get_numbered_placeholders_and_restore_round_trips(secrets):
    r = A.anonymize("a 192.168.7.20 b 10.8.0.5 c 192.168.7.20", secrets)
    assert r.text == "a [HOST] b [HOST_2] c [HOST]"
    assert A.restore(r.text, r.mapping) == "a 192.168.7.20 b 10.8.0.5 c 192.168.7.20"
    assert A.restore("[HOST_10] und [HOST_1]", {"[HOST_1]": "x", "[HOST_10]": "y"}) == "y und x"          # längere Platzhalter zuerst


def test_ai_answer_is_restored_locally(secrets):
    r = A.anonymize(BERICHT, secrets)
    antwort = "7. [BEOBACHTERCODE] steht im Kopf, OK."
    assert A.restore(antwort, r.mapping) == "7. ABCD steht im Kopf, OK."


def test_anonymize_is_idempotent_and_never_rewrites_inside_placeholders(secrets):
    r = A.anonymize(BERICHT, secrets)
    assert A.anonymize(r.text, secrets).text == r.text


def test_site_name_is_case_insensitive_and_invalid_ip_is_left_alone(secrets):
    r = A.anonymize("BALKON MUSTERSTADT, Version 999.1.1.1", secrets)
    assert "[STANDORT]" in r.text and "999.1.1.1" in r.text


def test_short_code_only_as_whole_word():
    s = A.collect_secrets(SimpleNamespace(aavso_code="AB", site_name=""), [], None, home=HOME)
    r = A.anonymize("AB meldet; TABELLE bleibt", s)
    assert r.text.startswith("[BEOBACHTERCODE] meldet") and "TABELLE" in r.text


def test_prepare_for_cloud_refuses_when_something_is_left(secrets):
    with pytest.raises(A.AnonymizationError, match="Beobachtercode"):
        A.prepare_for_cloud("Der Wert XYZABCDXYZ steckt im Wort", secrets)                  # Wortgrenze: nicht ersetzt, aber die unabhängige Prüfung findet ihn
    with pytest.raises(A.AnonymizationError, match="länger als erlaubt"):
        A.prepare_for_cloud("kurz " * 100, secrets, max_chars=50)
    ok = A.prepare_for_cloud(BERICHT, secrets, max_chars=5000)
    assert A.find_leaks(ok.text, secrets) == []


def test_error_message_never_contains_the_secret_value(secrets):
    with pytest.raises(A.AnonymizationError) as e:
        A.prepare_for_cloud("XYZABCDXYZ", secrets)
    assert "ABCD" not in str(e.value) and "maxmuster" not in str(e.value)


def test_summary_counts_without_values(secrets):
    r = A.anonymize(BERICHT, secrets)
    s = dict(A.summary(r))
    assert s["Beobachtercode"] == 2 and "ABCD" not in str(s)


def test_save_sent_text_writes_only_the_anonymized_text(tmp_path, secrets):
    r = A.anonymize(BERICHT, secrets)
    p = A.save_sent_text(tmp_path, "bericht", r, "Claude", "modell-x")
    t = p.read_text(encoding="utf-8")
    assert p.name == "bericht_ki_gesendet.md" and "Claude, modell-x" in t and "[BEOBACHTERCODE]" in t
    assert "ABCD" not in t and "maxmuster" not in t and "49.3212" not in t
    assert oct(p.stat().st_mode & 0o777) == "0o600"


def test_coordinate_variants_do_not_hit_longer_numbers(secrets):
    r = A.anonymize("Messwert 149.3212 und 49.32129", secrets)
    assert "149.3212" in r.text and "49.32129" in r.text                                       # andere Zahlen bleiben


def test_no_secrets_still_catches_generic_patterns():
    r = A.anonymize("Pfad /home/sternfreund/x.csv, Mail a@b.de, Adresse 10.0.0.1", [])
    assert r.text == "Pfad [PFAD], Mail [EMAIL], Adresse [HOST]"
