#!/usr/bin/env python3
"""Prueba opcional: cambia y restaura la instalación real y termina parcheada."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolphin_config import load, read_json
from dolphin_install import INFO_PATH
from dolphin_store import Store, digest, verify_live


def run(script, *args):
    subprocess.run([sys.executable, str(ROOT / script), *args], check=True, cwd=ROOT)


def main():
    settings = load()
    state_path = settings.backups / "instalacion.json"
    store = Store(settings.backups)
    initial = read_json(state_path)
    baseline, original_manifest = store.load(initial["baseline"])
    patched, _ = store.load(initial["installed"])
    lib = Path(f"lib/libdolphinprivate.{settings.version}.dylib")
    original_info = (baseline / INFO_PATH).read_bytes()
    patched_hash = digest(patched / lib)
    run("configurar-app.py", "--restaurar")
    assert (settings.craft / INFO_PATH).read_bytes() == original_info
    assert digest(settings.craft / lib) == patched_hash
    assert read_json(state_path)["baseline"] == initial["baseline"]
    print("Info.plist original restaurado byte a byte, biblioteca corregida conservada: OK", flush=True)
    run("configurar-app.py")
    assert read_json(state_path)["baseline"] == initial["baseline"]
    print("Metadatos reaplicados sin cambiar el original: OK", flush=True)
    run("parchear-dolphin.py", "--restaurar")
    state = read_json(state_path)
    verify_live(settings.craft, original_manifest, state["managed"])
    assert state["installed"] == initial["baseline"]
    print("Instalación completa sin parche restaurada y verificada archivo a archivo: OK", flush=True)
    run("parchear-dolphin.py")
    state = read_json(state_path)
    _, manifest = store.load(state["installed"])
    verify_live(settings.craft, manifest, state["managed"])
    assert (settings.craft / INFO_PATH).read_bytes() != original_info
    assert digest(settings.craft / lib) != digest(baseline / lib)
    print("Instalación completa corregida reinstalada y verificada: OK", flush=True)


if __name__ == "__main__":
    main()
