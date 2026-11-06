#!/bin/zsh
# Registers the .desktop bridges in share/applications so Dolphin's "Open With"
# lists macOS apps. On macOS KService only scans ~/Applications and
# /Applications for .desktop files, and it does not follow a symlinked
# directory, so a real folder holds one symlink per bridge.
# Usage: ./install-open-with.sh [--remove]
set -euo pipefail

ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
TARGET="$HOME/Applications/Dolphin Open With"

if [[ "${1:-}" == "--remove" ]]; then
    for link in "$TARGET"/*.desktop(N@); do
        rm "$link"
    done
    rmdir "$TARGET" 2> /dev/null || true
else
    mkdir -p "$TARGET"
    # Drop links to bridges that no longer exist in the project.
    for link in "$TARGET"/*.desktop(N@); do
        [[ -e "$link" ]] || rm "$link"
    done
    for bridge in "$ROOT"/share/applications/*.desktop(N); do
        ln -sfn "$bridge" "$TARGET/${bridge:t}"
    done
fi

# Rebuild the service cache with the environment Dolphin gets from Info.plist.
QT_DATA_DIRS="$CRAFT_ROOT/share" "$CRAFT_ROOT/bin/kbuildsycoca6" --noincremental > /dev/null 2>&1
echo "Asociaciones de \"Abrir con\" actualizadas en $TARGET"
