#!/bin/zsh
# Installs or removes the application-menu fragment and .desktop bridge links,
# then rebuilds KService's cache for both "Open With" and "Other Application".
# On macOS KService scans ~/Applications and /Applications for .desktop files.
# A real folder holds one symlink per bridge because directory symlinks are not followed.
# Usage: ./install-open-with.sh [--remove|--help]
set -euo pipefail

ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
TARGET="$HOME/Applications/Dolphin Open With"
PILOT_TARGET="$HOME/Applications/Dolphin Open With Pilot"

# Help works without Craft and does not modify files or rebuild the cache.
if (( $# == 1 )) && [[ "$1" == "--help" ]]; then
    print -r -- "Uso: $0 [--remove|--help]"
    print -r -- "Instala el fragmento de menú y los puentes a aplicaciones de macOS para \"Abrir con\"."
    print -r -- "  --remove  Retira el fragmento de menú y los enlaces a los puentes."
    print -r -- "  --help    Muestra esta ayuda sin cambiar la configuración."
    print -r -- "Los errores de la caché se guardan en $ROOT/run/open-with-cache.log."
    exit 0
fi

# Validate arguments before changing anything.
if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != "--remove" ]]; }; then
    echo "Uso: $0 [--remove|--help]" >&2
    exit 1
fi

operation="comprobar los requisitos"
trap 'print -u2 -- "Falló la configuración de \"Abrir con\" al $operation. Corrige el error y repite la orden con los mismos argumentos."' ZERR
command -v python3 > /dev/null
for tool in qtpaths6 kbuildsycoca6; do
    if [[ ! -x "$CRAFT_ROOT/bin/$tool" ]]; then
        print -u2 -- "Falta el ejecutable: $CRAFT_ROOT/bin/$tool"
        exit 1
    fi
done

# Shared with tools/install-macos-pilot.py: both change the same links and the
# cache. The lock is released when the shell exits.
zmodload zsh/system
mkdir -p "$ROOT/run"
: >> "$ROOT/run/open-with.lock"  # zsystem flock needs an existing file
if ! zsystem flock -t 0 "$ROOT/run/open-with.lock" 2> /dev/null; then
    print -u2 -- "Ya se está ejecutando otra instalación de \"Abrir con\" o del piloto. Espera a que termine."
    exit 1
fi

# Check all affected names before changing the menu or any links.
for bridge in "$ROOT"/share/applications/*.desktop(N); do
    link="$TARGET/${bridge:t}"
    merged="$PILOT_TARGET/${bridge:t:r}.bridge"
    if [[ -e "$link" || -L "$link" ]]; then
        if [[ ! -L "$link" ]]; then
            print -u2 -- "No se modifica un archivo ajeno: $link"
            exit 1
        fi
        current="$(readlink "$link")"
        if [[ "$current" != "$bridge" && "$current" != "$merged" ]]; then
            print -u2 -- "No se modifica un enlace ajeno: $link"
            exit 1
        fi
    fi
done

# Validate ownership and update the menu before modifying any bridge links.
operation="configurar el menú de aplicaciones"
python3 "$ROOT/install-menu.py" "$@"

operation="actualizar los enlaces a las aplicaciones"
if [[ "${1:-}" == "--remove" ]]; then
    for bridge in "$ROOT"/share/applications/*.desktop(N); do
        link="$TARGET/${bridge:t}"
        [[ ! -L "$link" ]] || rm "$link"
    done
    rmdir "$TARGET" 2> /dev/null || true
else
    mkdir -p "$TARGET"
    for bridge in "$ROOT"/share/applications/*.desktop(N); do
        merged="$PILOT_TARGET/${bridge:t:r}.bridge"
        if [[ -f "$merged" ]]; then
            ln -sfn "$merged" "$TARGET/${bridge:t}"
        else
            ln -sfn "$bridge" "$TARGET/${bridge:t}"
        fi
    done
fi

# Rebuild the service cache with the environment Dolphin gets from Info.plist.
operation="regenerar la caché de aplicaciones"
mkdir -p "$ROOT/run"
cache_log="$ROOT/run/open-with-cache.log"
if ! QT_DATA_DIRS="$CRAFT_ROOT/share" "$CRAFT_ROOT/bin/kbuildsycoca6" --noincremental > "$cache_log" 2>&1; then
    print -u2 -- "Falló la regeneración de la caché de \"Abrir con\". Consulta $cache_log. Corrige el error y repite la orden con los mismos argumentos."
    exit 1
fi
echo "Aplicaciones de \"Abrir con\" actualizadas en $TARGET"
