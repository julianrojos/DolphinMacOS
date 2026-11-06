#!/bin/zsh
# Instala Craft y compila Dolphin para macOS (uso personal).
# Uso: ./setup.sh
set -euo pipefail

ROOT="${0:A:h}"
CRAFT_ROOT="$ROOT/CraftRoot"
LOGS="$ROOT/bootstrap"

for command in curl python3 git patch c++ codesign xcrun rg; do
    if ! command -v "$command" > /dev/null; then
        echo "Falta $command. Instala las herramientas de desarrollo necesarias." >&2
        exit 1
    fi
done
VERSION="$(python3 "$ROOT/dolphin_config.py")"
xcrun --find clang > /dev/null
echo "Preparando dependencias de Dolphin $VERSION; Dolphin se instalará completo desde fuentes."

# El Python de python.org no trae certificados: usamos los del sistema.
export SSL_CERT_FILE=/etc/ssl/cert.pem

mkdir -p "$LOGS"

if [[ ! -d "$CRAFT_ROOT/craft" ]]; then
    curl -sSfL https://invent.kde.org/packaging/craft/-/raw/master/setup/CraftBootstrap.py \
        -o "$LOGS/CraftBootstrap.py"
    python3 -I "$LOGS/CraftBootstrap.py" --prefix "$CRAFT_ROOT" --use-defaults \
        > "$LOGS/craft-setup.log" 2>&1
fi

source "$CRAFT_ROOT/craft/craftenv.sh" > /dev/null 2>&1

craft --set "version=$VERSION" dolphin > /dev/null

# Accesos directos rotos en include/ (QtCore, QtGui, QtWidgets) bloquean la
# instalación de qtbase. Si aparecen, se borran y se reintenta una vez.
remove_dangling_qt_links() {
    local removed=1
    for link in "$CRAFT_ROOT"/include/Qt*(N@); do
        if [[ ! -e "$link" ]]; then
            echo "Borrando acceso roto: $link"
            rm "$link"
            removed=0
        fi
    done
    return $removed
}

if ! craft --install-deps dolphin > "$LOGS/craft-dolphin.log" 2>&1; then
    if ! remove_dangling_qt_links; then
        echo "La compilación falló. Registro: $LOGS/craft-dolphin.log" >&2
        exit 1
    fi
    echo "Reintentando tras limpiar accesos rotos..."
    if ! craft --install-deps dolphin > "$LOGS/craft-dolphin-2.log" 2>&1; then
        echo "La compilación falló. Registro: $LOGS/craft-dolphin-2.log" >&2
        exit 1
    fi
fi

"$ROOT/fix-dbus-service.sh"

# Solo las dependencias usan la caché. El instalador compila y despliega todo
# Dolphin; no mezcla una biblioteca local con ejecutables de la caché.
SOURCE="$CRAFT_ROOT/build/kde/applications/dolphin/work/dolphin-$VERSION"
BUILD="$CRAFT_ROOT/build/kde/applications/dolphin/work/build"
if [[ -f "$BUILD/CMakeCache.txt" ]] && ! rg -Fqx "CMAKE_HOME_DIRECTORY:INTERNAL=$SOURCE" "$BUILD/CMakeCache.txt"; then
    archived_build="$(mktemp -d "$LOGS/build-anterior.XXXXXXXX")"
    mv "$BUILD" "$archived_build/build"
    echo "Configuración de otra fuente archivada en $archived_build"
fi
if [[ ! -f "$SOURCE/src/kitemviews/accessibility/kitemlistviewaccessible.cpp" || ! -f "$BUILD/CMakeCache.txt" ]]; then
    echo "Preparando Dolphin desde fuentes para aplicar el parche local..."
    for action in fetch unpack configure; do
        if ! craft --no-cache "--$action" dolphin > "$LOGS/dolphin-$action.log" 2>&1; then
            echo "Falló la preparación de fuentes ($action). Registro: $LOGS/dolphin-$action.log" >&2
            exit 1
        fi
    done
fi
echo "Compilando e instalando Dolphin completo con la corrección local..."
python3 "$ROOT/parchear-dolphin.py"
"$ROOT/install-open-with.sh"

echo "Listo: $CRAFT_ROOT/Applications/KDE/dolphin.app"
echo "Para abrirlo: ./abrir-dolphin.sh"
