"""Instantáneas verificadas y sustitución recuperable de archivos de Dolphin."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from dolphin_config import read_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_path(root, relative):
    if not isinstance(relative, str) or not relative:
        raise RuntimeError(f"Ruta no válida en el manifiesto: {relative!r}")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or str(path) != relative:
        raise RuntimeError(f"Ruta no válida en el manifiesto: {relative!r}")
    target = root / path
    if not target.parent.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(f"La ruta sale de la instalación: {relative}")
    return target


def describe(path):
    if path.is_symlink():
        return {"type": "link", "target": os.readlink(path)}
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError(f"Se esperaba un archivo: {path}")
    return {"type": "file", "sha256": digest(path), "mode": stat.S_IMODE(path.stat().st_mode)}


def collect(root):
    return {str(path.relative_to(root)): describe(path) for path in sorted(root.rglob("*"))
            if path.is_symlink() or path.is_file()}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        json.dump(data, output, indent=2, sort_keys=True)
        output.write("\n")
    os.replace(output.name, path)


def copy_entry(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".dolphin-copy-", dir=destination.parent) as directory:
        temporary = Path(directory) / "entry"
        if source.is_symlink():
            temporary.symlink_to(os.readlink(source))
        else:
            shutil.copy2(source, temporary)
        os.replace(temporary, destination)


class Store:
    def __init__(self, backups):
        self.root = backups / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, tree, manifest=None):
        manifest = collect(tree) if manifest is None else manifest
        key = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        target = self.root / key
        if not target.exists():
            with tempfile.TemporaryDirectory(prefix=".snapshot-", dir=self.root) as directory:
                temporary = Path(directory) / "snapshot"
                (temporary / "tree").mkdir(parents=True)
                for relative, entry in manifest.items():
                    if entry is not None:
                        copy_entry(safe_path(tree, relative), safe_path(temporary / "tree", relative))
                write_json(temporary / "manifest.json", manifest)
                os.replace(temporary, target)
        self.load(key)
        return key

    def load(self, key):
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise RuntimeError("Identificador de copia no válido.")
        folder = self.root / key
        manifest = read_json(folder / "manifest.json")
        calculated = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        if calculated != key:
            raise RuntimeError("El manifiesto de la copia de seguridad fue modificado.")
        if collect(folder / "tree") != {name: entry for name, entry in manifest.items() if entry is not None}:
            raise RuntimeError("Copia de seguridad dañada: su contenido no coincide con el manifiesto.")
        for relative, entry in manifest.items():
            path = safe_path(folder / "tree", relative)
            if entry is None and describe(path) is not None:
                raise RuntimeError(f"Copia de seguridad dañada: {relative}")
        return folder / "tree", manifest


def verify_live(craft, manifest, managed):
    for relative in managed:
        if describe(safe_path(craft, relative)) != manifest.get(relative):
            raise RuntimeError(f"La instalación ha cambiado: {relative}. No se adoptará como original; revisa o restaura esa modificación.")


def put_tree(craft, tree, manifest, managed):
    for relative in managed:
        target = safe_path(craft, relative)
        if manifest.get(relative) is None:
            if target.is_file() or target.is_symlink():
                target.unlink()
            elif target.exists():
                raise RuntimeError(f"No se puede retirar un directorio ajeno: {relative}")
        else:
            copy_entry(safe_path(tree, relative), target)


def deploy(craft, store, artifact, managed, state_path, state, validate=lambda: None):
    tree, manifest = store.load(artifact)
    before = {relative: describe(safe_path(craft, relative)) for relative in managed}
    before_key = store.save(craft, before)
    pending = state_path.parent / "pendiente.json"
    prior_state = read_json(state_path) if state_path.exists() else None
    write_json(pending, {"before": before_key, "target": artifact, "managed": managed, "prior_state": prior_state})
    try:
        put_tree(craft, tree, manifest, managed)
        verify_live(craft, manifest, managed)
        validate()
        history_id = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        write_json(state_path.parent / "historial" / f"{history_id}.json", state)
        write_json(state_path, state)
        pending.unlink()
    except Exception:
        old_tree, old_manifest = store.load(before_key)
        put_tree(craft, old_tree, old_manifest, managed)
        if prior_state is not None:
            write_json(state_path, prior_state)
        elif state_path.exists():
            state_path.unlink()
        pending.unlink()
        raise


def recover(craft, store, state_path):
    pending = state_path.parent / "pendiente.json"
    data = read_json(pending)
    if set(data) not in ({"before", "managed", "prior_state"}, {"before", "target", "managed", "prior_state"}) or not isinstance(data["managed"], list):
        raise RuntimeError("Registro de recuperación incompleto.")
    tree, manifest = store.load(data["before"])
    if set(data["managed"]) != set(manifest):
        raise RuntimeError("La lista de archivos de recuperación no coincide con la copia.")
    target_manifest = store.load(data["target"])[1] if "target" in data else None
    for relative in data["managed"]:
        current = describe(safe_path(craft, relative))
        allowed = [manifest.get(relative)]
        if target_manifest is not None:
            allowed.append(target_manifest.get(relative))
        if current not in allowed:
            if target_manifest is None:
                raise RuntimeError(f"El registro de recuperación es antiguo y no identifica el destino; {relative} difiere de la copia anterior. Conserva el registro pendiente y revisa el archivo antes de continuar.")
            raise RuntimeError(f"La recuperación detectó un cambio externo en {relative}; conserva el registro pendiente y revisa el archivo antes de continuar.")
    put_tree(craft, tree, manifest, data["managed"])
    if data["prior_state"] is not None:
        write_json(state_path, data["prior_state"])
    elif state_path.exists():
        state_path.unlink()
    pending.unlink()
