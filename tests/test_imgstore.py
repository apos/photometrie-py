"""imgstore (deploy/imgstore/imgstore): Image-Ablage als Ordner. Getestet mit einer Attrappe fuer ``docker`` (kein Daemon noetig); braucht ``zstd`` und ``bash``."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "deploy" / "imgstore" / "imgstore"
pytestmark = pytest.mark.skipif(shutil.which("zstd") is None or shutil.which("bash") is None, reason="zstd/bash fehlt")

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Attrappe: image inspect <ref> [--format F] | save <ref> | load
case "$1" in
  image)
    [ "$3" = "ghost:1" ] && exit 1
    [ -n "$FAKE_MISSING" ] && [ "$3" = "$FAKE_MISSING" ] && exit 1
    case "$5" in
      *Architecture*) echo "${FAKE_ARCH:-amd64}" ;;
      *Created*) echo "2026-11-15T10:00:00Z" ;;
      *Id*) echo "sha256:abc123" ;;
      *Size*) echo 123456789 ;;
    esac ;;
  save) head -c 300000 /dev/urandom | od -An -tx1 | head -c 200000 ;;
  load) cat > "$FAKE_LOADED" ;;
  tag) echo "$2 $3" >> "$FAKE_TAGS" ;;
esac
"""


@pytest.fixture
def env(tmp_path):
    bindir = tmp_path / "bin"; bindir.mkdir()
    d = bindir / "docker"; d.write_text(FAKE_DOCKER); d.chmod(0o755)
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", IMGSTORE_DIR=str(tmp_path / "store"), FAKE_LOADED=str(tmp_path / "loaded.bin"), FAKE_TAGS=str(tmp_path / "tags.txt"), FAKE_MISSING="", HOME=str(tmp_path / "home"))
    e.pop("IMGSTORE_PROJECT", None)
    return e


def run(env, *args, check=True):
    r = subprocess.run(["bash", str(TOOL), *args], env=env, capture_output=True, text=True)
    if check:
        assert r.returncode == 0, r.stderr
    return r


def test_push_list_verify_pull_roundtrip(env, tmp_path):
    run(env, "push", "varphot-agent:2026.4.1", "-p", "varphot")
    d = tmp_path / "store" / "varphot" / "varphot-agent" / "2026.4.1"
    assert (d / "amd64.tar.zst").is_file() and (d / "amd64.sha256").is_file() and "arch=amd64" in (d / "amd64.meta").read_text()
    assert not list(d.glob("*.part"))                                      # Nextcloud darf nie eine halbe Datei sehen
    out = run(env, "list").stdout
    assert "varphot" in out and "varphot-agent" in out and "amd64" in out
    assert "OK" in run(env, "verify", "varphot-agent:2026.4.1", "-p", "varphot", "-a", "amd64").stdout
    run(env, "pull", "varphot-agent:2026.4.1", "-p", "varphot", "-a", "amd64")
    assert Path(env["FAKE_LOADED"]).stat().st_size == 200000               # Inhalt kommt unveraendert (dekomprimiert) beim Docker an


def test_two_architectures_side_by_side_and_wrong_arch_message(env, tmp_path):
    run(env, "push", "app:1", "-p", "p")
    run(dict(env, FAKE_ARCH="arm64"), "push", "app:1", "-p", "p")
    d = tmp_path / "store" / "p" / "app" / "1"
    assert (d / "amd64.tar.zst").is_file() and (d / "arm64.tar.zst").is_file()
    r = run(env, "pull", "app:1", "-p", "p", "-a", "s390x", check=False)
    assert r.returncode != 0 and "keine Datei fuer Architektur s390x" in r.stderr and "amd64" in r.stderr and "arm64" in r.stderr


def test_corrupt_archive_is_rejected(env, tmp_path):
    run(env, "push", "app:2", "-p", "p")
    f = tmp_path / "store" / "p" / "app" / "2" / "amd64.tar.zst"
    f.write_bytes(f.read_bytes()[:-5] + b"XXXXX")
    r = run(env, "pull", "app:2", "-p", "p", "-a", "amd64", check=False)
    assert r.returncode != 0 and "Pruefsumme stimmt nicht" in r.stderr
    assert not Path(env["FAKE_LOADED"]).exists()                           # nichts geladen


def test_missing_image_and_unset_store(env):
    r = run(env, "push", "ghost:1", check=False)
    assert r.returncode != 0 and "nicht vorhanden" in r.stderr
    e = {k: v for k, v in env.items() if k != "IMGSTORE_DIR"}
    r = run(e, "list", check=False)
    assert r.returncode != 0 and "IMGSTORE_DIR" in r.stderr


def test_store_dir_from_config_file(env, tmp_path):
    cfg = tmp_path / "home" / ".config" / "imgstore"; cfg.mkdir(parents=True)
    (cfg / "dir").write_text(str(tmp_path / "from_cfg") + "\n")
    e = {k: v for k, v in env.items() if k != "IMGSTORE_DIR"}
    assert run(e, "where").stdout.strip() == str(tmp_path / "from_cfg")


def test_registry_style_names_become_valid_paths(env, tmp_path):
    run(env, "push", "jetbrains/datalore-agent:2026.4.1", "-p", "base")
    assert (tmp_path / "store" / "base" / "jetbrains_datalore-agent" / "2026.4.1" / "amd64.tar.zst").is_file()


def test_pull_retags_podman_localhost_names(env, tmp_path):
    """Archiv aus Podman traegt "localhost/<name>"; nach dem Laden in Docker wird der urspruengliche Name gesetzt."""
    run(env, "push", "app:3", "-p", "p")
    run(dict(env, FAKE_MISSING="app:3"), "pull", "app:3", "-p", "p", "-a", "amd64")
    assert (tmp_path / "tags.txt").read_text().strip() == "localhost/app:3 app:3"
    (tmp_path / "tags.txt").unlink()
    run(env, "pull", "app:3", "-p", "p", "-a", "amd64")                    # Name vorhanden: nichts umetikettieren
    assert not (tmp_path / "tags.txt").exists()
