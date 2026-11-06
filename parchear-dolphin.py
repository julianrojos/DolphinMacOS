#!/usr/bin/env python3
"""Instala o restaura Dolphin completo desde una misma compilación local."""
import sys

if __name__ == "__main__":
    try:
        from dolphin_install import main
        main()
    except Exception as error:
        import traceback
        from pathlib import Path
        log = Path(__file__).resolve().parent / "run/error-instalacion.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a") as output:
            traceback.print_exc(file=output)
        print(f"No se pudo completar la instalación: {error}", file=sys.stderr)
        print(f"Detalle técnico: {log}", file=sys.stderr)
        sys.exit(1)
