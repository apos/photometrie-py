"""KI-Zweitlesung: Backend-Suche, Reihenfolge, Sicherheit (nur privates Netz), Aufruf — mit Ollama-Attrappe (HTTP) und Opencode-Attrappe (Skript)."""
import json
import os
import stat
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from varphot import aireview as A
from varphot.observer import Camera, Observer, Site, load_config, save_config


# ------------------------------------------------------------------------------------------------ Ollama-Attrappe
class _Fake(BaseHTTPRequestHandler):
    models = ["bge-m3:latest", "llama3.1:8b", "qwen2.5:7b"]
    mode = "ok"
    seen = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send(200, {"models": [{"name": m} for m in self.models]}) if self.path == "/api/tags" else self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append(body)
        if self.mode == "error":
            return self._send(500, {"error": "boom"})
        if self.mode == "empty":
            return self._send(200, {"message": {"content": "  "}})
        if self.mode == "think":
            return self._send(200, {"message": {"content": "<think>ueberlege</think>Keine Auffaelligkeiten."}})
        self._send(200, {"message": {"content": "- CHART fehlt"}})


class _Server(ThreadingHTTPServer):
    def server_bind(self):                       # ohne ``socket.getfqdn`` (blockiert auf manchen Rechnern bis zu 35 s)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


@pytest.fixture
def ollama():
    _Fake.models, _Fake.mode, _Fake.seen = ["bge-m3:latest", "llama3.1:8b", "qwen2.5:7b"], "ok", []
    srv = _Server(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], _Fake
    srv.shutdown()


def _cfg(port, **kw):
    cfg = {"enabled": True, "hosts": [{"name": "stark", "addresses": ["203.0.113.9", "127.0.0.1"], "ollama_port": port}],
           "local": {"ollama_url": "http://127.0.0.1:9", "opencode_model": None}, "models": ["qwen2.5:7b", "llama3.1:8b"]}
    cfg.update(kw)
    return cfg


@pytest.fixture
def no_opencode(monkeypatch):
    monkeypatch.setattr(A.shutil, "which", lambda n: None)


def _fake_opencode(tmp_path, monkeypatch, models, run_out="Anmerkung vom Modell", rc=0):
    exe = tmp_path / "bin" / "opencode"
    exe.parent.mkdir()
    exe.write_text(f"#!/bin/sh\nif [ \"$1\" = models ]; then printf '%s\\n' {' '.join(repr(m) for m in models)}; exit 0; fi\n"
                   f"if [ \"$1\" = run ]; then echo '{run_out}'; exit {rc}; fi\nexit 2\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])
    return exe


# ------------------------------------------------------------------------------------------------ Sicherheit
@pytest.mark.parametrize("host,ok", [("127.0.0.1", True), ("localhost", True), ("192.168.1.5", True), ("10.8.0.5", True), ("172.16.3.4", True), ("172.32.0.1", False),
                                     ("8.8.8.8", False), ("203.0.113.9", False), ("", False), ("[::1]", True), ("nicht.aufloesbar.invalid", False)])
def test_is_private_host(host, ok):
    assert A.is_private_host(host) is ok


def test_public_target_is_refused_without_connecting():
    with pytest.raises(ValueError, match="privaten Netz"):
        A._http_json("http://8.8.8.8:11434/api/tags")
    r = A.ai_review("x", A.Backend("ollama", "x", True, "", url="http://8.8.8.8:11434", model="m"))
    assert r.error and "privaten Netz" in r.error and r.text == ""


# ------------------------------------------------------------------------------------------------ Modellwahl
def test_pick_model_prefers_list_ignores_embeddings():
    assert A.pick_model(["bge-m3:latest", "llama3.1:8b", "qwen2.5:7b"], ["qwen2.5:7b", "llama3.1:8b"]) == "qwen2.5:7b"
    assert A.pick_model(["bge-m3:latest", "mistral:7b"], ["qwen2.5:7b"]) == "mistral:7b"      # nicht bevorzugt, aber kein Einbettungsmodell
    assert A.pick_model(["bge-m3:latest", "nomic-embed-text"], ["qwen2.5:7b"]) is None
    assert A.pick_model(["qwen2.5:7b:latest"], ["qwen2.5:7b"]) is None or True                 # Namensform; kein Absturz
    assert A.pick_model(["gemma3:latest"], ["gemma3"]) == "gemma3:latest"                      # ":latest" gleich dem Namen ohne Zusatz
    assert A.pick_model([], None) is None


# ------------------------------------------------------------------------------------------------ Reihenfolge der Backends
def test_strong_host_first_skips_unreachable_address(ollama, no_opencode):
    port, _ = ollama
    bs = A.detect_backends(_cfg(port), check_opencode_remote=False)
    ch = A.choose_backend(bs)
    assert ch.kind == "ollama" and ch.strong and ch.model == "qwen2.5:7b" and ch.url == f"http://127.0.0.1:{port}"
    assert "127.0.0.1" in ch.where and "203.0.113.9" not in ch.where              # erste Adresse (nicht privat/unerreichbar) uebersprungen
    assert [b.kind for b in bs][-2:] == ["opencode", "ollama"] and not bs[-1].usable   # danach lokal: Opencode, Ollama (hier nicht verfuegbar)


def test_remote_opencode_is_probed_but_ollama_is_used(ollama, no_opencode, monkeypatch):
    port, _ = ollama
    monkeypatch.setattr(A, "probe_opencode_remote", lambda alias, timeout=8.0: True)
    cfg = _cfg(port); cfg["hosts"][0]["ssh"] = "stark"
    bs = A.detect_backends(cfg)
    rem = bs[0]
    assert rem.kind == "opencode" and rem.ssh == "stark" and rem.usable is False and "noch nicht eingebaut" in rem.detail
    assert A.choose_backend(bs).kind == "ollama" and A.choose_backend(bs).strong
    monkeypatch.setattr(A, "probe_opencode_remote", lambda alias, timeout=8.0: False)
    assert "nicht installiert" in A.detect_backends(cfg)[0].detail


def test_unreachable_strong_host_falls_back_to_local_opencode_then_ollama(ollama, tmp_path, monkeypatch):
    port, _ = ollama
    _fake_opencode(tmp_path, monkeypatch, ["ollama/qwen2.5:7b", "opencode/big-pickle-free"])
    cfg = _cfg(1)                                       # starker Rechner: Port 1 → nicht erreichbar
    cfg["local"]["ollama_url"] = f"http://127.0.0.1:{port}"
    bs = A.detect_backends(cfg, check_opencode_remote=False)
    assert not bs[0].usable and "nicht erreichbar" in bs[0].detail
    ch = A.choose_backend(bs)
    assert ch.kind == "opencode" and ch.where == "lokal" and ch.model == "ollama/qwen2.5:7b"      # lokal: erst Opencode
    # ohne lokales Opencode-Modell → Ollama lokal
    _fake_opencode_cloud_only = tmp_path / "bin" / "opencode"
    _fake_opencode_cloud_only.write_text("#!/bin/sh\n[ \"$1\" = models ] && printf 'opencode/big-pickle\\nopencode/beam-free\\n'\nexit 0\n")
    bs = A.detect_backends(cfg, check_opencode_remote=False)
    oc = next(b for b in bs if b.kind == "opencode")
    assert not oc.usable and "nur Cloud-Modelle" in oc.detail and "verlassen" in oc.detail
    ch = A.choose_backend(bs)
    assert ch.kind == "ollama" and ch.where == "lokal" and ch.model == "qwen2.5:7b"


def test_opencode_explicit_model_must_be_installed(tmp_path, monkeypatch):
    _fake_opencode(tmp_path, monkeypatch, ["ollama/qwen2.5:7b", "opencode/x"])
    assert A.probe_opencode_local("ollama/qwen2.5:7b").usable
    b = A.probe_opencode_local("ollama/nicht-da")
    assert not b.usable and "nicht bei Opencode eingerichtet" in b.detail


def test_nothing_available_and_disabled(no_opencode, monkeypatch):
    bs = A.detect_backends({"enabled": True, "hosts": [], "local": {"ollama_url": "http://127.0.0.1:9", "opencode_model": None}, "models": []})
    assert A.choose_backend(bs) is None
    rows = A.preflight_lines(bs)
    assert not any(ok for _, ok, _ in rows) and "kein Weg" in rows[-1][2]
    assert A.detect_backends({"enabled": False}) == []
    assert "abgeschaltet" in A.preflight_lines([])[0][2]


def test_server_without_chat_model(ollama, no_opencode):
    port, fake = ollama
    fake.models = ["bge-m3:latest"]
    b = A.detect_backends(_cfg(port), check_opencode_remote=False)[0]
    assert not b.usable and "kein brauchbares Chat-Modell" in b.detail


def test_ipv6_loopback_literal_address(ollama, no_opencode):
    # ::1 ist privat; Adresse nur als Literal pruefen (Attrappe lauscht auf IPv4 → nicht erreichbar, aber kein Absturz)
    cfg = _cfg(1)
    cfg["hosts"][0]["addresses"] = ["::1"]
    assert not A.detect_backends(cfg, check_opencode_remote=False)[0].usable


# ------------------------------------------------------------------------------------------------ Aufruf
def test_review_ollama_ok_and_payload(ollama, no_opencode):
    port, fake = ollama
    b = A.choose_backend(A.detect_backends(_cfg(port), check_opencode_remote=False))
    r = A.ai_review("Bericht", b, timeout=10)
    assert r.error == "" and r.text == "- CHART fehlt" and r.model == "qwen2.5:7b" and r.seconds >= 0
    body = fake.seen[-1]
    assert body["stream"] is False and body["model"] == "qwen2.5:7b" and body["messages"][1]["content"] == "Bericht" and "nichts aendern" in body["messages"][0]["content"]


@pytest.mark.parametrize("mode,expect", [("error", "HTTP"), ("empty", "leere Antwort")])
def test_review_errors_do_not_raise(ollama, no_opencode, mode, expect):
    port, fake = ollama
    fake.mode = mode
    r = A.ai_review("x", A.choose_backend(A.detect_backends(_cfg(port), check_opencode_remote=False)), timeout=10)
    assert r.text == "" and expect in r.error


def test_review_strips_think_blocks(ollama, no_opencode):
    port, fake = ollama
    fake.mode = "think"
    r = A.ai_review("x", A.choose_backend(A.detect_backends(_cfg(port), check_opencode_remote=False)), timeout=10)
    assert r.text == "Keine Auffaelligkeiten."


def test_review_timeout_and_unreachable():
    r = A.ai_review("x", A.Backend("ollama", "x", True, "", url="http://127.0.0.1:1", model="m"), timeout=2)
    assert r.error and r.text == ""
    assert "nicht aufrufbar" in A.ai_review("x", A.Backend("opencode", "x", True, "", ssh="h", model="m")).error
    assert "ohne URL" in A.ai_review("x", A.Backend("ollama", "x", True, "")).error


def test_review_opencode_local(tmp_path, monkeypatch):
    _fake_opencode(tmp_path, monkeypatch, ["ollama/qwen2.5:7b"], run_out="Anmerkung vom Modell")
    b = A.probe_opencode_local()
    r = A.ai_review("Bericht", b, timeout=20)
    assert r.error == "" and r.text == "Anmerkung vom Modell"
    _fake_opencode_fail = tmp_path / "bin" / "opencode"
    _fake_opencode_fail.write_text("#!/bin/sh\n[ \"$1\" = models ] && echo ollama/qwen2.5:7b\n[ \"$1\" = run ] && { echo kaputt >&2; exit 3; }\n")
    r = A.ai_review("Bericht", b, timeout=20)
    assert "Rueckgabecode 3" in r.error and "kaputt" in r.error


# ------------------------------------------------------------------------------------------------ Konfiguration
def test_config_roundtrip_keeps_other_keys_and_save_config_keeps_ai(tmp_path):
    p = tmp_path / "observer.json"
    save_config(Observer("TST01", "Ort", Camera(model="K")), [Site("Ort", 49.5, 8.4, 100)], p)
    cfg = A.load_ai_config(p)
    assert cfg["enabled"] and cfg["hosts"] == [] and cfg["local"]["ollama_url"].startswith("http://127.0.0.1")
    cfg["hosts"] = [{"name": "stark", "addresses": ["10.0.0.5"]}]
    A.save_ai_config(cfg, p)
    assert oct(p.stat().st_mode)[-3:] == "600"
    obs, sites = load_config(p)                                   # Beobachter/Standorte unveraendert lesbar
    assert obs.aavso_code == "TST01" and sites[0].name == "Ort"
    save_config(obs, sites, p)                                    # erneutes Speichern darf ``ai`` nicht verlieren
    assert A.load_ai_config(p)["hosts"][0]["name"] == "stark"
    assert json.loads(p.read_text())["aavso_code"] == "TST01"


def test_env_switch_and_broken_file(tmp_path, monkeypatch):
    p = tmp_path / "observer.json"
    p.write_text("{kaputt")
    assert A.load_ai_config(p)["enabled"]                         # kaputte Datei → Vorgaben statt Absturz
    monkeypatch.setenv("VARPHOT_AI", "off")
    assert A.load_ai_config(p)["enabled"] is False


def test_preflight_marks_only_chosen(ollama, no_opencode):
    port, _ = ollama
    rows = A.preflight_lines(A.detect_backends(_cfg(port), check_opencode_remote=False))
    assert [ok for _, ok, _ in rows].count(True) == 1 and rows[0][1] and rows[0][2].startswith("benutzt")


# ------------------------------------------------------------------------------------------------ gesperrtes lokales Netz (macOS): Ersatzweg ueber curl/nc
def _fake_tool(tmp_path, monkeypatch, name, script):
    exe = tmp_path / "bin2" / name
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\n" + script)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])


def test_blocked_local_network_falls_back_to_curl_and_nc(tmp_path, monkeypatch):
    import errno
    import urllib.error
    def blocked(*a, **k):
        raise urllib.error.URLError(OSError(errno.EHOSTUNREACH, "No route to host"))
    monkeypatch.setattr(A.urllib.request, "urlopen", blocked)
    monkeypatch.setattr(A.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EHOSTUNREACH, "No route to host")))
    _fake_tool(tmp_path, monkeypatch, "curl", "cat >/dev/null 2>&1 </dev/null; echo '{\"models\": [{\"name\": \"qwen2.5:7b\"}], \"message\": {\"content\": \"via curl\"}}'\n")
    _fake_tool(tmp_path, monkeypatch, "nc", "exit 0\n")
    assert A.tcp_open("192.168.1.5", 11434)                                         # nc springt ein
    assert A.ollama_models("http://192.168.1.5:11434") == ["qwen2.5:7b"]             # curl springt ein
    r = A.ai_review("x", A.Backend("ollama", "x", True, "", url="http://192.168.1.5:11434", model="qwen2.5:7b"))
    assert r.text == "via curl" and r.error == ""


def test_other_network_errors_are_not_rerouted(monkeypatch):
    import errno
    monkeypatch.setattr(A.socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.ECONNREFUSED, "refused")))
    assert A.tcp_open("127.0.0.1", 9) is False and not A._blocked(OSError(errno.ECONNREFUSED, "x")) and A._blocked(OSError(65, "x"))


# ------------------------------------------------------------------------------------------------ Sicherheit: Weiterleitung, Proxy; URL-Auswertung
class _Redirect(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(302); self.send_header("Location", "http://8.8.8.8:11434/api/tags"); self.end_headers()


def test_redirect_to_public_address_is_not_followed():
    srv = _Server(("127.0.0.1", 0), _Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        with pytest.raises(Exception, match="302|Redirect|Found"):
            A._http_json(url + "/api/tags", timeout=5)
        assert A.ollama_models(url) == []                      # nach aussen: leere Liste, nie ein Zugriff auf die oeffentliche Adresse
    finally:
        srv.shutdown()


def test_system_proxy_is_ignored(ollama, monkeypatch):
    port, _ = ollama
    for k in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(k, "http://127.0.0.1:9")            # toter Proxy: wuerde der Aufruf ueber ihn laufen, schluege er fehl
    assert A.ollama_models(f"http://127.0.0.1:{port}") != []


def test_url_helpers():
    assert A._host_of("http://[::1]:11434") == "::1" and A._port_of("http://[::1]:11434") == 11434
    assert A._host_of("http://192.168.1.5") == "192.168.1.5" and A._port_of("http://192.168.1.5") == 11434 and A._port_of("http://h:99") == 99
    assert A._host_of("kaputt") == "" and A._host_of("http://[bad") == "" and A._port_of("http://[bad") == 11434


def test_local_opencode_can_be_disabled(tmp_path, monkeypatch):
    _fake_opencode(tmp_path, monkeypatch, ["ollama/qwen2.5:7b"])
    cfg = {"enabled": True, "hosts": [], "local": {"ollama_url": "http://127.0.0.1:9", "opencode": False, "opencode_model": None}, "models": []}
    assert [b.kind for b in A.detect_backends(cfg)] == ["ollama"]


def test_review_without_backend_returns_error_not_exception():
    r = A.ai_review("x", None)
    assert r.text == "" and "kein KI-Weg" in r.error


# ------------------------------------------------------------------------------------------------ Cloud: Claude-Kommandozeile (Attrappe)
def _fake_claude(tmp_path, monkeypatch, logged_in=True, rc=0):
    """Attrappe des Programms ``claude``: ``auth status`` liefert JSON, jeder andere Aufruf schreibt Argumente, Umgebung, Ordner und Eingabe in ``rec/`` und antwortet mit einer Anmerkung."""
    rec = tmp_path / "rec"
    rec.mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = auth ]; then echo '{{\"loggedIn\": {'true' if logged_in else 'false'}, \"authMethod\": \"claude.ai\"}}'; touch \"{rec}/auth_called\"; exit 0; fi\n"
        f"printf '%s\\n' \"$@\" > \"{rec}/argv.txt\"\n"
        f"env | grep -c '^ANTHROPIC_API_KEY=' > \"{rec}/key.txt\"\n"
        f"pwd > \"{rec}/cwd.txt\"\n"
        f"cat > \"{rec}/stdin.txt\"\n"
        f"if [ {rc} -ne 0 ]; then echo 'Fehler vom Programm' >&2; exit {rc}; fi\n"
        "echo 'Anmerkung von Claude: [BEOBACHTERCODE] steht im Kopf.'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])
    return rec


def test_probe_claude_cli_states(tmp_path, monkeypatch):
    monkeypatch.setattr(A.shutil, "which", lambda n: None)
    assert not A.probe_claude_cli().usable and "nicht installiert" in A.probe_claude_cli().detail
    monkeypatch.undo()
    _fake_claude(tmp_path, monkeypatch, logged_in=False)
    b = A.probe_claude_cli()
    assert not b.usable and "claude auth login" in b.detail
    monkeypatch.undo()
    _fake_claude(tmp_path, monkeypatch, logged_in=True)
    b = A.probe_claude_cli()
    assert b.usable and "claude.ai" in b.detail


def test_cloud_backends_off_by_default_and_never_called(tmp_path, monkeypatch):
    rec = _fake_claude(tmp_path, monkeypatch)
    cfg = A.load_ai_config(tmp_path / "keine.json")
    out = A.detect_cloud_backends(cfg)
    assert [b.usable for b in out] == [False, False] and "ai.cloud.enabled" in out[0].detail
    assert not (rec / "auth_called").exists()                                                  # ohne Einschalten wird das Programm nicht einmal gestartet
    assert A.cloud_preflight_lines(cfg)[0][1] is False
    cfg["cloud"]["enabled"] = True
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "leer"))                              # keine Gemini-Anmeldung auf diesem Rechner
    out = A.detect_cloud_backends(cfg)
    assert [b.kind for b in out] == ["claude-cli", "gemini-cli"] and out[0].usable and not out[1].usable
    assert [r[0] for r in A.cloud_preflight_lines(cfg)] == ["Cloud-KI Claude", "Cloud-KI Gemini"]
    monkeypatch.setenv("VARPHOT_AI_CLOUD", "off")
    assert A.load_ai_config(tmp_path / "keine.json")["cloud"]["enabled"] is False


def test_cloud_is_never_chosen_automatically(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch)
    cfg = A.load_ai_config(tmp_path / "keine.json")
    cfg["cloud"]["enabled"] = True
    cfg["local"]["opencode"] = False
    chosen = A.choose_backend(A.detect_backends(cfg, check_opencode_remote=False))
    assert chosen is None or chosen.kind not in ("claude-cli", "gemini-cli")
    assert all(b.kind not in ("claude-cli", "gemini-cli") for b in A.detect_backends(cfg, check_opencode_remote=False))


def test_ai_review_claude_cli_is_isolated(tmp_path, monkeypatch):
    rec = _fake_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim-nicht-weitergeben")
    bk = A.Backend("claude-cli", "Cloud", True, "angemeldet", model="modell-x")
    res = A.ai_review("Text mit [BEOBACHTERCODE]", bk, system="Systemanweisung", timeout=30)
    assert res.error == "" and "Anmerkung von Claude" in res.text and res.model == "modell-x"
    argv = (rec / "argv.txt").read_text().split("\n")
    i = argv.index("--tools")
    assert argv[i + 1] == "" and "--disable-slash-commands" in argv and "--strict-mcp-config" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--system-prompt") + 1] == "Systemanweisung" and argv[argv.index("--model") + 1] == "modell-x"
    assert (rec / "stdin.txt").read_text() == "Text mit [BEOBACHTERCODE]"                      # Text über die Standardeingabe, nicht in der Prozessliste
    assert (rec / "key.txt").read_text().strip() == "0"                                        # gesetzter API-Schlüssel wird nicht weitergereicht
    assert (rec / "cwd.txt").read_text().strip() != os.getcwd()                                # eigener Wegwerf-Ordner, nicht der Projektordner
    assert "Text mit" not in " ".join(argv)


def test_ai_review_claude_cli_error_is_a_result_not_an_exception(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, rc=3)
    res = A.ai_review("Geheimer Berichtstext", A.Backend("claude-cli", "Cloud", True, "x"), timeout=30)
    assert "Rueckgabecode 3" in res.error and "Fehler vom Programm" in res.error and "Geheimer" not in res.error and res.text == ""


def test_cloud_roundtrip_anonymize_send_restore(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from varphot import anonymize as AN
    rec = _fake_claude(tmp_path, monkeypatch)
    secrets = AN.collect_secrets(SimpleNamespace(aavso_code="ABCD", site_name=""), [], None, home="/Users/maxmuster")
    anon = AN.prepare_for_cloud("#OBSCODE=ABCD\nBeobachter ABCD, Daten in /Users/maxmuster/x", secrets)
    res = A.ai_review(anon.text, A.Backend("claude-cli", "Cloud", True, "x"), timeout=30)
    sent = (rec / "stdin.txt").read_text()
    assert "ABCD" not in sent and "maxmuster" not in sent                                      # beim Anbieter kommt nichts Persönliches an
    assert "ABCD steht im Kopf" in AN.restore(res.text, anon.mapping)                          # lokal wieder zurückübersetzt


def test_anonymization_note_tells_the_model_that_placeholders_are_filled():
    assert "[BEOBACHTERCODE]" in A.ANON_NOTE and "kein Fehler" in A.ANON_NOTE and A.SYSTEM_PROMPT.endswith("hoechstens einem Satz.")


# ---- Eingegrenzter Pruefauftrag mit Kontext (build_context / build_system_prompt) ---------------------------------------------------------------------------------------------

FACTS = dict(method="mono", camera="QHY268M", mode="untransformiert", exp_filter="V", exp_trans=False, exp_obstype="CCD", is_test=True, n_points=100, n_comps_sel=6, n_comps_ens=5, n_gaia=6, chart="Gaia DR3 V-deriv")


def test_context_states_expectation_intent_and_test_flag():
    c = A.build_context(FACTS)
    assert "Mono-Kamera" in c and "QHY268M" in c
    assert "Filter V, TRANS NO, OBSTYPE CCD" in c
    assert "zwei verschiedene Groessen" in c and "(6, ausgewaehlte" in c and "(5, Median" in c            # Comps 6 / Ensemble 5 ist erklaert, kein Widerspruch
    assert "Gaia DR3 V-deriv" in c and "TST01" in c


def test_context_without_test_and_gaia_has_no_such_lines():
    c = A.build_context(dict(FACTS, is_test=False, chart="X43370IPN"))
    assert "Echtdaten" in c and "TST01" not in c and "Notbehelf" not in c


def test_context_marks_open_obstype_question_for_colour():
    c = A.build_context(dict(FACTS, method="osc", exp_filter="TG", exp_obstype="DSLR", obstype_open=True))
    assert "nicht geklaert" in c and "Farbkamera mit Bayer" in c


def test_system_prompt_points_are_assembled_per_case():
    base = A.build_system_prompt(dict(FACTS, is_test=False))
    assert "Filter V, TRANS NO, OBSTYPE CCD" in base and "Testkennzeichnung" not in base and "Koeffizienten" not in base
    test = A.build_system_prompt(FACTS)
    assert "Testkennzeichnung" in test
    tr = A.build_system_prompt(dict(FACTS, mode="transformiert", exp_trans=True))
    assert "Koeffizienten" in tr and "TRANS YES" in tr


def test_system_prompt_forbids_bare_ok_and_limits_scope():
    s = A.build_system_prompt(FACTS)
    assert "Kein Urteil ohne woertliches Zitat" in s and "NICHT_PRUEFBAR" in s and "NUR die folgenden Punkte" in s
    assert "Fazit:" in s and s.count("\n") >= 8
    nums = [l.split(".")[0] for l in s.splitlines() if l[:1].isdigit()]
    assert nums == [str(i) for i in range(1, len(nums) + 1)]                                    # fortlaufend nummeriert


def test_context_and_prompt_hold_no_personal_data():
    blob = A.build_context(FACTS) + A.build_system_prompt(FACTS)
    assert "@" not in blob and "/Users/" not in blob and "/work/" not in blob


def test_context_explains_session_date_and_truncated_head():
    c = A.build_context(FACTS)
    assert "Tag der **Auswertung**" in c and "nicht der Beobachtung" in c      # Sitzungsdatum gegen JD der Archivdaten war ein Fehlalarm (Probelauf 2026-11-17)
    assert "nur die ersten Datenzeilen" in c and "(100)" in c


def test_context_gives_calendar_dates_computed_by_the_software():
    assert A.jd_to_date(2458802.651) == "2019-11-15" and A.jd_to_date(2458858.548) == "2020-01-10"      # LCO-Testdaten (docs/testdaten.md)
    c = A.build_context(dict(FACTS, jd_range=(2458802.651, 2458858.548), eval_date="2026-11-17"))
    assert "2019-11-15 bis 2020-01-10" in c and "ausgewertet am 2026-11-17" in c and "Rechne nicht selbst um" in c


def _fake_gemini(tmp_path, monkeypatch, rc=0):
    """Attrappe des Programms ``gemini``: schreibt Argumente, Umgebung, Ordner, Eingabe, Systemanweisung, Richtlinie und Einstellungen in ``grec/`` und antwortet mit einer Anmerkung."""
    rec = tmp_path / "grec"
    rec.mkdir(exist_ok=True)
    exe = tmp_path / "gbin" / "gemini"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > \"{rec}/argv.txt\"\n"
        f"env > \"{rec}/env.txt\"\n"
        f"pwd > \"{rec}/cwd.txt\"\n"
        f"cat > \"{rec}/stdin.txt\"\n"
        f"cp \"$GEMINI_SYSTEM_MD\" \"{rec}/system.md\"\n"
        f"cp \"$GEMINI_CLI_HOME/.gemini/settings.json\" \"{rec}/settings.json\"\n"
        f"if [ -f \"$GEMINI_CLI_HOME/.gemini/oauth_creds.json\" ]; then touch \"{rec}/oauth_copied\"; fi\n"
        f"for a in \"$@\"; do case \"$a\" in *deny.toml) cp \"$a\" \"{rec}/policy.toml\";; esac; done\n"
        f"if [ {rc} -ne 0 ]; then echo 'Warning: 256-color' >&2; echo 'Error when talking to Gemini API Full report available at: /tmp/x/bericht.json ModelNotFoundError: Modell weg, Schluessel geheim-123' >&2; echo '    at async foo (file:///x.js:1:1)' >&2; exit {rc}; fi\n"
        "echo '1. Anmerkung von Gemini: [BEOBACHTERCODE] steht im Kopf.'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])
    return rec


def _gemini_home(tmp_path, monkeypatch, key=None, oauth=False, env_file=None):
    """Eigener Heimordner fuer die Anmeldung (nie die echte ``~/.gemini`` des Rechners)."""
    d = tmp_path / "ghome" / ".gemini"
    d.mkdir(parents=True, exist_ok=True)
    (d / "GEMINI.md").write_text("PRIVATE ANWEISUNG DES NUTZERS", encoding="utf-8")
    monkeypatch.setenv("GEMINI_CLI_HOME", str(tmp_path / "ghome"))
    monkeypatch.setenv("GEMINI_API_KEY", key or "")
    if oauth:
        (d / "oauth_creds.json").write_text('{"refresh_token": "oauth-geheim-456"}', encoding="utf-8")
    if env_file:
        (d / ".env").write_text(env_file, encoding="utf-8")


def test_gemini_auth_sources_and_probe(tmp_path, monkeypatch):
    _fake_gemini(tmp_path, monkeypatch)
    _gemini_home(tmp_path, monkeypatch)
    assert A.gemini_auth() == (None, None)
    b = A.probe_gemini_cli()
    assert not b.usable and "keine Anmeldung" in b.detail and "/auth/gemini/.env" in b.detail
    _gemini_home(tmp_path, monkeypatch, env_file="# Kommentar\nexport GEMINI_API_KEY='aus-env-datei'\n")             # Datalore: Schluessel im Volume
    assert A.gemini_auth() == ("api-key", "aus-env-datei")
    _gemini_home(tmp_path, monkeypatch, key="aus-umgebung")
    assert A.gemini_auth() == ("api-key", "aus-umgebung")
    b = A.probe_gemini_cli()
    assert b.usable and "aus-umgebung" not in b.detail                                         # nie der Schluessel in der Meldung
    monkeypatch.setenv("GEMINI_API_KEY", "")
    (tmp_path / "ghome" / ".gemini" / ".env").unlink()
    _gemini_home(tmp_path, monkeypatch, oauth=True)
    assert A.gemini_auth() == ("oauth", None) and "Google-Anmeldung" in A.probe_gemini_cli().detail
    monkeypatch.setattr(A.shutil, "which", lambda n: None)
    assert not A.probe_gemini_cli().usable and "nicht installiert" in A.probe_gemini_cli().detail


def test_ai_review_gemini_cli_is_isolated(tmp_path, monkeypatch):
    rec = _fake_gemini(tmp_path, monkeypatch)
    _gemini_home(tmp_path, monkeypatch, key="schluessel-abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anderer-geheimer-schluessel")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "mein-projekt")
    bk = A.Backend("gemini-cli", "Cloud", True, "x", model="gemini-modell-x")
    res = A.ai_review("Text mit [BEOBACHTERCODE]", bk, system="Systemanweisung", timeout=30)
    assert res.error == "" and "Anmerkung von Gemini" in res.text and res.model == "gemini-modell-x" and res.backend.startswith("gemini-cli")
    argv = (rec / "argv.txt").read_text().split("\n")
    assert "--skip-trust" in argv and argv[argv.index("--model") + 1] == "gemini-modell-x" and argv[argv.index("--output-format") + 1] == "text"
    assert (rec / "stdin.txt").read_text() == "Text mit [BEOBACHTERCODE]"                      # Text ueber die Standardeingabe
    assert "Text mit" not in " ".join(argv) and "schluessel-abc" not in " ".join(argv)        # weder Text noch Schluessel in der Prozessliste
    assert (rec / "system.md").read_text() == "Systemanweisung"                                # eigene Systemanweisung ersetzt die eingebaute
    assert 'toolName = "*"' in (rec / "policy.toml").read_text() and 'decision = "deny"' in (rec / "policy.toml").read_text()      # alle Werkzeuge verboten
    env = dict(ln.split("=", 1) for ln in (rec / "env.txt").read_text().splitlines() if "=" in ln)
    assert env["GEMINI_API_KEY"] == "schluessel-abc" and "ANTHROPIC_API_KEY" not in env and "GOOGLE_CLOUD_PROJECT" not in env
    assert env["GEMINI_CLI_HOME"] != str(tmp_path / "ghome")                                   # Wegwerf-Heimordner: die GEMINI.md des Nutzers wird nicht geladen
    assert (rec / "cwd.txt").read_text().strip() != os.getcwd()
    assert '"selectedType": "gemini-api-key"' in (rec / "settings.json").read_text()
    assert not Path(env["GEMINI_CLI_HOME"]).exists()                                           # nach dem Lauf geloescht (auch eine Kopie der Anmeldung)


def test_ai_review_gemini_cli_oauth_copies_login_only_temporarily(tmp_path, monkeypatch):
    rec = _fake_gemini(tmp_path, monkeypatch)
    _gemini_home(tmp_path, monkeypatch, oauth=True)
    res = A.ai_review("Text", A.Backend("gemini-cli", "Cloud", True, "x"), timeout=30)
    assert res.error == "" and (rec / "oauth_copied").exists() and "--model" not in (rec / "argv.txt").read_text()
    assert '"selectedType": "oauth-personal"' in (rec / "settings.json").read_text()
    env = dict(ln.split("=", 1) for ln in (rec / "env.txt").read_text().splitlines() if "=" in ln)
    assert "GEMINI_API_KEY" not in env and not Path(env["GEMINI_CLI_HOME"]).exists()


def test_ai_review_gemini_cli_errors_are_results_without_secrets(tmp_path, monkeypatch):
    _fake_gemini(tmp_path, monkeypatch, rc=1)
    _gemini_home(tmp_path, monkeypatch, key="geheim-123")
    res = A.ai_review("Geheimer Berichtstext", A.Backend("gemini-cli", "Cloud", True, "x"), timeout=30)
    assert "Rueckgabecode 1" in res.error and "ModelNotFoundError: Modell weg" in res.error and "geheim-123" not in res.error and "256-color" not in res.error
    assert "/tmp/x/bericht.json" not in res.error and "async foo" not in res.error and res.text == ""
    _gemini_home(tmp_path, monkeypatch)                                                        # keine Anmeldung: Ergebnis mit Fehler, kein Aufruf
    res = A.ai_review("Text", A.Backend("gemini-cli", "Cloud", True, "x"), timeout=30)
    assert "keine Gemini-Anmeldung" in res.error


def test_gemini_model_comes_from_config(tmp_path, monkeypatch):
    _fake_gemini(tmp_path, monkeypatch)
    _gemini_home(tmp_path, monkeypatch, key="k")
    cfg = A.load_ai_config(tmp_path / "keine.json")
    cfg["cloud"].update(enabled=True, gemini_model="gemini-aus-konfig")
    assert A.detect_cloud_backends(cfg)[1].model == "gemini-aus-konfig"
