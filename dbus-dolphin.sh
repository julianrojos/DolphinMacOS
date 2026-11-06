#!/bin/zsh
# Evita el socket de launchd incluido en la configuración precompilada.
ROOT="${0:A:h}"
exec "$ROOT/CraftRoot/bin/dbus-daemon" --address=unix:tmpdir=/tmp "$@"
