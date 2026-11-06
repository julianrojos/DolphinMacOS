"""Configuración validada, sin modificar la instalación al importar el módulo."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys


def read_json(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"No se puede leer el archivo JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"El archivo {path} debe contener un objeto JSON.")
    return value


@dataclass(frozen=True)
class Settings:
    root: Path
    version: str

    @property
    def craft(self): return self.root / "CraftRoot"
    @property
    def work(self): return self.craft / "build/kde/applications/dolphin/work"
    @property
    def source(self): return self.work / f"dolphin-{self.version}"
    @property
    def build(self): return self.work / "build"
    @property
    def patch(self): return self.root / f"patches/dolphin-{self.version}-accesibilidad.patch"
    @property
    def backups(self): return self.root / "backups" / self.version
    @property
    def app(self): return self.craft / "Applications/KDE/dolphin.app"


def load(root=None):
    root = Path(root) if root else Path(__file__).resolve().parent
    version = read_json(root / "dolphin-version.json").get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise RuntimeError("La versión debe tener el formato mayor.menor.parche.")
    settings = Settings(root, version)
    if not settings.patch.is_file():
        raise RuntimeError(f"La versión {version} no tiene un parche validado.")
    return settings


def check_version(executable, version):
    result = subprocess.run([str(executable), "--version"], check=True,
                            capture_output=True, text=True, timeout=15)
    if result.stdout.strip() != f"dolphin {version}":
        raise RuntimeError(f"Versión instalada inesperada: {result.stdout.strip()!r}; esperada {version}")


if __name__ == "__main__":
    try:
        print(load().version)
    except (RuntimeError, OSError) as error:
        print(f"Configuración no válida: {error}", file=sys.stderr)
        sys.exit(1)
