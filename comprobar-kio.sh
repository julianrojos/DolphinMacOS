#!/bin/zsh
# Solo crea, elimina y restaura sus propios archivos temporales.
set -euo pipefail
ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
CMAKE="$CRAFT_ROOT/dev-utils/bin/cmake"
BUILD="$ROOT/run/kio-check-build"
if [[ ! -x "$CMAKE" || ! -x "$CRAFT_ROOT/bin/dbus-run-session" ]]; then
    echo "Faltan herramientas de Craft. Ejecuta ./setup.sh primero." >&2
    exit 1
fi
"$CMAKE" -S "$ROOT/tests" -B "$BUILD" -DCMAKE_PREFIX_PATH="$CRAFT_ROOT"
"$CMAKE" --build "$BUILD"
exec "$CRAFT_ROOT/bin/dbus-run-session" --dbus-daemon="$ROOT/dbus-dolphin.sh" \
    --config-file="$CRAFT_ROOT/share/dbus-1/session.conf" -- "$BUILD/kio-check"
