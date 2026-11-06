#!/bin/zsh
# Abre Dolphin con una sesión D-Bus propia, cerrada al terminar la aplicación.
set -euo pipefail

ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
RUN_DIR="$ROOT/run"
APP="$CRAFT_ROOT/Applications/KDE/dolphin.app/Contents/MacOS/dolphin"
SESSION="$CRAFT_ROOT/bin/dbus-run-session"
DAEMON="$ROOT/dbus-dolphin.sh"
CONFIG="$CRAFT_ROOT/share/dbus-1/session.conf"

for required in "$APP" "$SESSION" "$DAEMON" "$CONFIG"; do
    if [[ ! -e "$required" ]]; then
        echo "Falta $required. Ejecuta ./setup.sh primero." >&2
        exit 1
    fi
done
for executable in "$APP" "$SESSION" "$DAEMON"; do
    if [[ ! -x "$executable" ]]; then
        echo "No se puede ejecutar $executable. Comprueba sus permisos." >&2
        exit 1
    fi
done
if (( $# > 1 )) || { (( $# == 1 )) && [[ ! -d "$1" ]]; }; then
    echo "Uso: $0 [carpeta existente]" >&2
    exit 1
fi

mkdir -p "$RUN_DIR"
# Craft's Qt reads extra data dirs (MIME database, application definitions)
# from QT_DATA_DIRS on macOS; XDG_DATA_DIRS is ignored there.
export QT_DATA_DIRS="$CRAFT_ROOT/share${QT_DATA_DIRS:+:$QT_DATA_DIRS}"
log_file="$(mktemp "$RUN_DIR/dolphin.log.XXXXXXXX")"
nohup "$SESSION" --dbus-daemon="$DAEMON" --config-file="$CONFIG" -- \
    "$APP" "${1:-$HOME}" > "$log_file" 2>&1 &
session_pid=$!
sleep 2
if ! kill -0 "$session_pid" 2>/dev/null; then
    if wait "$session_pid"; then
        echo "Dolphin terminó durante el arranque. Registro: $log_file" >&2
    else
        echo "Dolphin no pudo arrancar o terminó inesperadamente. Registro: $log_file" >&2
    fi
    exit 1
fi
echo "Proceso iniciado (PID $session_pid); comprueba que aparezca la ventana. Registro: $log_file"
disown
