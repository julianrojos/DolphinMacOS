#!/bin/zsh
# Craft registers a launchd agent for the D-Bus session bus, but its prebuilt
# dbus-daemon looks for session.conf under the KDE CI path and exits, so apps
# launched from the Dock/Finder hang waiting for the bus. Point the agent at
# Craft's config, reload it and check the bus answers.
# Usage: ./fix-dbus-service.sh
set -euo pipefail

ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
LABEL="org.freedesktop.dbus-session"
PLIST="$CRAFT_ROOT/Library/LaunchAgents/$LABEL.plist"
CONFIG_ARG="--config-file=$CRAFT_ROOT/share/dbus-1/session.conf"
DOMAIN="gui/$(id -u)"
BUDDY=/usr/libexec/PlistBuddy

if [[ ! -f "$PLIST" ]]; then
    echo "No existe $PLIST. Ejecuta ./setup.sh primero." >&2
    exit 1
fi

bus_responds() {
    local socket
    socket="$(launchctl getenv DBUS_LAUNCHD_SESSION_BUS_SOCKET)"
    [[ -n "$socket" ]] && "$CRAFT_ROOT/bin/dbus-send" --bus="unix:path=$socket" \
        --dest=org.freedesktop.DBus --reply-timeout=3000 --print-reply \
        /org/freedesktop/DBus org.freedesktop.DBus.GetId > /dev/null 2>&1
}

# Expected arguments: dbus-daemon --nofork <config>. Craft installs "--session".
changed=0
current="$($BUDDY -c "Print :ProgramArguments:2" "$PLIST")"
if [[ "$current" != "$CONFIG_ARG" ]]; then
    if [[ "$current" != "--session" ]]; then
        echo "Argumento inesperado en $PLIST: $current" >&2
        exit 1
    fi
    $BUDDY -c "Set :ProgramArguments:2 $CONFIG_ARG" "$PLIST"
    echo "Servicio D-Bus apuntado a la configuración de Craft."
    changed=1
fi

# Reloading restarts the bus and disconnects running KDE apps: only do it when
# the plist changed or the bus does not answer.
if (( changed )) || ! bus_responds; then
    launchctl bootout "$DOMAIN/$LABEL" 2> /dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
fi

if ! bus_responds; then
    echo "El bus D-Bus de launchd no responde." >&2
    exit 1
fi
echo "Bus D-Bus de launchd operativo."
