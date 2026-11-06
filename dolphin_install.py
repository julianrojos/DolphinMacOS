"""Compilación completa, metadatos y recuperación de Dolphin para uso local."""
import argparse
import fcntl
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from dolphin_config import load, read_json, check_version
from dolphin_store import Store, collect, deploy, recover, verify_live

APP_PATH = Path("Applications/KDE/dolphin.app")
INFO_PATH = APP_PATH / "Contents/Info.plist"


def ensure_closed(settings):
    processes = subprocess.run(["ps", "-ax", "-o", "pid=,comm="], check=True, capture_output=True, text=True)
    executable = str(settings.app / "Contents/MacOS/dolphin")
    commands = [line.strip().split(maxsplit=1)[-1] for line in processes.stdout.splitlines() if line.strip()]
    # comm puede conservar una ruta relativa; bloquear también ese ejecutable
    # por nombre y sufijo del paquete, sin resolverlo contra nuestro cwd.
    if any(command == executable or command.endswith("/dolphin.app/Contents/MacOS/dolphin") or command == "dolphin" for command in commands):
        raise RuntimeError("Dolphin está abierto. Ciérralo antes de instalar o restaurar para poder comprobar la nueva versión.")


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def load_state(settings):
    path = settings.backups / "instalacion.json"
    if not path.exists():
        # No reutilizar ni reinterpretar como originales las copias del prototipo.
        legacy = settings.backups / "parche.json"
        if legacy.exists():
            data = read_json(legacy)
            required = {"backup", "original", "patched", "executable", "version"}
            if not required <= data.keys() or data["version"] != settings.version:
                raise RuntimeError("El manifiesto antiguo está incompleto o pertenece a otra versión.")
            for field in ("original", "patched", "executable"):
                value = data[field]
                if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                    raise RuntimeError(f"Huella no válida en el manifiesto antiguo: {field}")
        return None
    data = read_json(path)
    required = {"schema", "version", "baseline", "installed", "managed"}
    if set(data) != required or data.get("schema") != 2 or data.get("version") != settings.version:
        raise RuntimeError("El manifiesto de instalación está incompleto o tiene un formato o versión no compatible.")
    if not isinstance(data["managed"], list) or not all(isinstance(x, str) for x in data["managed"]) or len(set(data["managed"])) != len(data["managed"]):
        raise RuntimeError("La lista de archivos del manifiesto no es válida.")
    return data


def set_metadata(tree, version):
    info = tree / INFO_PATH
    with info.open("rb") as stream:
        data = plistlib.load(stream)
    data.update(CFBundleIdentifier="org.kde.dolphin", CFBundleName="Dolphin",
                CFBundleDisplayName="Dolphin", CFBundleShortVersionString=version,
                CFBundleVersion=version)
    with info.open("wb") as stream:
        plistlib.dump(data, stream)


def sign_tree(tree):
    for path in sorted(tree.rglob("*")):
        if not path.is_symlink() and path.is_file() and path.suffix in (".dylib", ".so"):
            run("codesign", "--force", "--sign", "-", path)
            run("codesign", "--verify", path)
    for app in sorted(tree.rglob("*.app"), reverse=True):
        run("codesign", "--force", "--sign", "-", app)
        run("codesign", "--verify", app)


def ensure_patch(settings, enabled):
    reverse = subprocess.run(["patch", "--batch", "--forward", "--dry-run", "-R", "-p1", "-i", str(settings.patch)],
                             cwd=settings.source, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if reverse.returncode == 0:
        if not enabled:
            run("patch", "--batch", "--forward", "-R", "-p1", "-i", settings.patch, cwd=settings.source)
    else:
        run("patch", "--batch", "--dry-run", "--forward", "-p1", "-i", settings.patch, cwd=settings.source)
        if enabled:
            run("patch", "--batch", "--forward", "-p1", "-i", settings.patch, cwd=settings.source)


def build_artifact(settings, store, patched):
    ensure_patch(settings, patched)
    if patched:
        run(sys.executable, settings.root / "tests/comprobar-accesibilidad.py")
    cmake = settings.craft / "dev-utils/bin/cmake"
    phase = "corregido" if patched else "sin-parche"
    log = settings.root / "run" / f"compilacion-{phase}.log"
    log.parent.mkdir(exist_ok=True)
    print(f"Compilando Dolphin completo ({phase}). Registro: {log}", flush=True)
    with log.open("w") as output:
        run(cmake, "--build", settings.build, "-j", "4", stdout=output, stderr=subprocess.STDOUT)
        with tempfile.TemporaryDirectory(prefix="dolphin-stage-") as directory:
            run(cmake, "--install", settings.build, "--prefix", settings.craft,
                env=dict(os.environ, DESTDIR=directory), stdout=output, stderr=subprocess.STDOUT)
            tree = Path(directory) / settings.craft.relative_to("/")
            if not (tree / INFO_PATH).is_file() or not any((tree / "plugins").rglob("*.so")):
                raise RuntimeError(f"Instalación completa no generada; consulta {log}")
            if patched:
                set_metadata(tree, settings.version)
            sign_tree(tree)
            return store.save(tree)


def validate_sources(settings):
    cache = settings.build / "CMakeCache.txt"
    if not settings.source.is_dir() or not cache.is_file():
        raise RuntimeError(f"Faltan fuentes o configuración de Dolphin {settings.version}. Ejecuta ./setup.sh.")
    values = {}
    for line in cache.read_text().splitlines():
        if "=" in line and ":" in line.split("=", 1)[0]:
            key, value = line.split("=", 1)
            values[key.split(":", 1)[0]] = value
    if values.get("CMAKE_PROJECT_VERSION") != settings.version or values.get("CMAKE_HOME_DIRECTORY") != str(settings.source):
        raise RuntimeError("La configuración CMake no corresponde a las fuentes y versión seleccionadas.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--restaurar", action="store_true", help="Restaurar la compilación completa sin parche")
    group.add_argument("--metadatos", action="store_true")
    group.add_argument("--restaurar-metadatos", action="store_true")
    group.add_argument("--recuperar", action="store_true", help="Revertir una sustitución interrumpida")
    group.add_argument("--reinstalar", action="store_true", help="Reconstruir desde fuentes aunque Craft haya cambiado la instalación; conserva una copia previa")
    args = parser.parse_args(argv)
    settings = load()
    settings.backups.mkdir(parents=True, exist_ok=True)
    with (settings.backups / "instalacion.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Ya hay otra instalación o restauración en curso.") from error
        store = Store(settings.backups)
        state_path = settings.backups / "instalacion.json"
        if args.recuperar:
            ensure_closed(settings)
            recover(settings.craft, store, state_path)
            print("Se recuperó la instalación anterior a la sustitución interrumpida.")
            return
        if (settings.backups / "pendiente.json").exists():
            raise RuntimeError("Hay una sustitución interrumpida. Ejecuta python3 parchear-dolphin.py --recuperar.")
        state = load_state(settings)
        ensure_closed(settings)
        if state:
            _, current = store.load(state["installed"])
            _, baseline_manifest = store.load(state["baseline"])
            if not (set(current) | set(baseline_manifest)) <= set(state["managed"]):
                raise RuntimeError("El manifiesto omite archivos de la instalación.")
            if not args.reinstalar:
                try:
                    verify_live(settings.craft, current, state["managed"])
                except RuntimeError as error:
                    raise RuntimeError(f"{error} Para reconstruir desde fuentes conservando una copia previa, ejecuta python3 parchear-dolphin.py --reinstalar.") from error
        if args.restaurar or args.metadatos or args.restaurar_metadatos:
            if not state:
                raise RuntimeError("No hay una instalación completa registrada. Ejecuta python3 parchear-dolphin.py primero.")
            baseline = state["baseline"]
            target = baseline
            if args.metadatos or args.restaurar_metadatos:
                base_tree, _ = store.load(baseline)
                current_tree, _ = store.load(state["installed"])
                with tempfile.TemporaryDirectory(prefix="dolphin-metadata-") as directory:
                    tree = Path(directory) / "tree"
                    shutil.copytree(current_tree, tree, symlinks=True)
                    if args.restaurar_metadatos:
                        shutil.copy2(base_tree / INFO_PATH, tree / INFO_PATH)
                    else:
                        set_metadata(tree, settings.version)
                    sign_tree(tree)
                    target = store.save(tree)
        else:
            validate_sources(settings)
            # El original se genera desde fuentes sin el parche, nunca desde lo instalado.
            baseline = build_artifact(settings, store, False)
            target = build_artifact(settings, store, True)
        _, clean = store.load(baseline)
        _, updated = store.load(target)
        managed = set(clean) | set(updated) | set(state["managed"] if state else [])
        # También conservar/retirar recursos antiguos dentro de los paquetes sustituidos.
        bundles = {Path(*Path(path).parts[:index + 1]) for path in updated
                   for index, part in enumerate(Path(path).parts) if part.endswith(".app")}
        for relative in sorted(bundles):
            app = settings.craft / relative
            managed.update(str(relative / path) for path in collect(app))
        state = dict(schema=2, version=settings.version, baseline=baseline, installed=target, managed=sorted(managed))

        def validate():
            run("codesign", "--verify", settings.app)
            check_version(settings.app / "Contents/MacOS/dolphin", settings.version)

        deploy(settings.craft, store, target, state["managed"], state_path, state, validate)
        print("Instalación completa verificada. Reinicia Dolphin para cargarla.")
