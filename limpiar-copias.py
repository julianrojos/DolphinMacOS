#!/usr/bin/env python3
"""Planifica la limpieza; --aplicar ejecuta exactamente el plan mostrado."""
import argparse
import fcntl
from pathlib import Path
import shutil
import sys
import traceback

from dolphin_config import load, read_json
from dolphin_store import Store, write_json


def plan(settings):
    from dolphin_install import load_state
    if (settings.backups / "pendiente.json").exists():
        raise RuntimeError("Resuelve la operación pendiente antes de limpiar copias.")
    current = load_state(settings)
    if current is None:
        raise RuntimeError("No hay una instalación registrada que permita proteger sus copias.")
    store = Store(settings.backups)
    artifacts = sorted(p for p in store.root.iterdir() if p.is_dir() and not p.is_symlink()
                       and len(p.name) == 64 and all(c in "0123456789abcdef" for c in p.name))
    history = sorted((settings.backups / "historial").glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    # Validar todo el historial antes de proponer un solo borrado.
    states = []
    for path in history:
        state = read_json(path)
        if not {"baseline", "installed"} <= state.keys():
            raise RuntimeError(f"Historial incompleto: {path}")
        states.append(state)
    pin_file = settings.backups / "protegidas.json"
    if pin_file.exists():
        pins = read_json(pin_file)
        if set(pins) != {"artifacts", "history"} or not all(isinstance(pins[k], list) and all(isinstance(x, str) for x in pins[k]) for k in pins):
            raise RuntimeError("El registro de copias protegidas no es válido.")
    else:
        # No sabemos cuál es el primer estado de Craft: preservar todos los
        # artefactos previos, sin deducir su procedencia a partir de fechas.
        pins = {"artifacts": [p.name for p in artifacts], "history": [p.name for p in history]}
    if not set(pins["history"]) <= {path.name for path in history}:
        raise RuntimeError("El registro protege archivos de historial que no existen.")
    protected = set(pins["artifacts"])
    for key in protected:
        store.load(key)
    retained_states = [state for index, state in enumerate(states) if index < 3 or history[index].name in pins["history"]]
    for state in [current] + retained_states:
        for key in ("baseline", "installed"):
            store.load(state[key])
            protected.add(state[key])
    protected.update(p.name for p in sorted(artifacts, key=lambda p: p.stat().st_mtime_ns, reverse=True)[:3])
    delete_artifacts = [p for p in artifacts if p.name not in protected]
    delete_history = [p for p in history[3:] if p.name not in pins["history"]]
    return delete_artifacts, delete_history, pins


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--aplicar", action="store_true")
    mode.add_argument("--listar-protecciones", action="store_true", help="Mostrar identificadores completos y referencias activas")
    mode.add_argument("--quitar-proteccion", metavar="TIPO:ID", help="Retirar una protección manual, sin borrar la copia")
    args = parser.parse_args(argv)
    settings = load()
    if not settings.backups.is_dir():
        raise RuntimeError("No hay copias de una instalación registrada.")
    with (settings.backups / "instalacion.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Hay otra instalación o limpieza en curso.") from error
        artifacts, history, pins = plan(settings)
        from dolphin_install import load_state
        current = load_state(settings)
        active = {current["baseline"], current["installed"]}
        if args.listar_protecciones:
            for key in sorted(set(pins["artifacts"]) | active):
                roles = []
                if key in active:
                    roles.append("instalación activa; no retirable")
                if key in pins["artifacts"]:
                    roles.append("protección manual")
                print(f"copia:{key} — {'; '.join(roles)}")
            for key in sorted(pins["history"]):
                state = read_json(settings.backups / "historial" / key)
                print(f"historial:{key} — protección manual; referencias: copia:{state['baseline']}, copia:{state['installed']}")
            if not (settings.backups / "protegidas.json").exists():
                print("Las protecciones manuales se inicializarán al aplicar una operación; esta consulta no modifica archivos.")
            return
        if args.quitar_proteccion:
            kind, separator, key = args.quitar_proteccion.partition(":")
            field = {"copia": "artifacts", "historial": "history"}.get(kind)
            if not separator or field is None or not key:
                raise RuntimeError("Usa copia:ID o historial:ID; consulta --listar-protecciones.")
            if field == "artifacts" and key in active:
                raise RuntimeError("No se puede retirar la protección de una copia necesaria para la instalación activa y su restauración.")
            if key not in pins[field]:
                raise RuntimeError("Esa referencia no tiene una protección manual; consulta --listar-protecciones.")
            updated = {name: [value for value in values if name != field or value != key] for name, values in pins.items()}
            write_json(settings.backups / "protegidas.json", updated)
            print(f"Protección retirada: {args.quitar_proteccion}. No se ha borrado ningún archivo de copia o historial.")
            print("Puede seguir retenida por el historial conservado o por la política de copias recientes. Consulta el plan de limpieza.")
            return
        for path in artifacts + history:
            print("Eliminar:" if args.aplicar else "Se podría eliminar:", path)
        print(f"Plan: {len(artifacts)} copias y {len(history)} archivos de historial.")
        if not (settings.backups / "protegidas.json").exists():
            print("Se protegerán todas las copias e historiales previos, de procedencia aún no clasificada.")
        if args.aplicar:
            write_json(settings.backups / "protegidas.json", pins)
            # Eliminar primero referencias obsoletas: una interrupción solo deja
            # copias adicionales, nunca un historial apuntando a una copia borrada.
            for path in history:
                path.unlink()
            for path in artifacts:
                shutil.rmtree(path)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        log = Path(__file__).resolve().parent / "run/error-limpieza.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a") as output:
            traceback.print_exc(file=output)
        print(f"No se pudo limpiar las copias: {error}\nDetalle técnico: {log}", file=sys.stderr)
        sys.exit(1)
