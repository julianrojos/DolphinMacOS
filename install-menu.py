#!/usr/bin/env python3
"""Install an additive application-menu fragment for KDE's Open With dialog."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

MARKER = "Managed by Dolphin install-menu.py"
CONTENT = f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- {MARKER} -->
<Menu>
  <Name>Applications</Name>
  <Include><All/></Include>
</Menu>
'''


def write_menu(target):
    content = CONTENT.encode("utf-8")
    if target.exists() and target.read_bytes() == content:
        return
    # Preserve an existing managed symlink and replace its destination atomically.
    destination = target.resolve(strict=True) if target.is_symlink() else target
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".dolphin-menu-", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            # NamedTemporaryFile creates 0600: keep an existing file's mode, or
            # use the mode a normally created file would get (0666 minus umask).
            if destination.exists():
                mode = stat.S_IMODE(destination.stat().st_mode)
            else:
                umask = os.umask(0)
                os.umask(umask)
                mode = 0o666 & ~umask
            os.fchmod(output.fileno(), mode)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    result = subprocess.run([str(root / "CraftRoot/bin/qtpaths6"), "--writable-path", "GenericConfigLocation"],
                            check=True, capture_output=True, text=True)
    config = Path(result.stdout.strip())
    if not config.is_absolute():
        raise RuntimeError("Qt devolvió una carpeta de configuración no válida")
    target = config / "menus/applications-merged/dolphin-open-with.menu"
    if (target.exists() or target.is_symlink()) and not target.is_file():
        raise RuntimeError(f"Se esperaba un archivo de menú normal, pero la ruta es de otro tipo: {target}")
    if target.exists() and MARKER not in target.read_text():
        raise RuntimeError(f"No se sustituye un archivo que no gestiona este proyecto: {target}")
    if args.remove:
        target.unlink(missing_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_menu(target)
    print(target)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Falló la configuración del menú: {error}", file=sys.stderr)
        sys.exit(1)
