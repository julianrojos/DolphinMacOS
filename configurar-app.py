#!/usr/bin/env python3
"""Configura o restaura los metadatos de una instalación local registrada."""
import argparse
import sys

if __name__ == "__main__":
    try:
        from dolphin_install import main
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--restaurar", action="store_true")
        args = parser.parse_args()
        main(["--restaurar-metadatos" if args.restaurar else "--metadatos"])
    except Exception as error:
        import traceback
        from pathlib import Path
        log = Path(__file__).resolve().parent / "run/error-metadatos.log"
        log.parent.mkdir(exist_ok=True)
        with log.open("a") as output:
            traceback.print_exc(file=output)
        print(f"No se pudieron configurar los metadatos: {error}", file=sys.stderr)
        print(f"Detalle técnico: {log}", file=sys.stderr)
        sys.exit(1)
