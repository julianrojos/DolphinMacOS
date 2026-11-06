#!/usr/bin/env python3
"""Build Dolphin's real accessible table methods against its real item layouter and check them."""
import argparse
import os
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dolphin_config import load

settings = load()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", nargs="?", type=pathlib.Path)
parser.add_argument("--library", type=pathlib.Path)
args = parser.parse_args()
source = pathlib.Path(os.path.abspath(args.source or settings.source / "src/kitemviews/accessibility/kitemlistviewaccessible.cpp"))
src = source.parents[2]
text = source.read_text()
# The three methods that describe the table; the check compiles them as they are.
methods = []
for signature, following in (("QAccessibleInterface *KItemListViewAccessible::cellAt(", "\nQAccessibleInterface *KItemListViewAccessible::caption()"),
                             ("int KItemListViewAccessible::columnCount() const", "\nint KItemListViewAccessible::selectedCellCount()")):
    start = text.index(signature)
    methods.append(text[start:text.index(following, start)])
library = pathlib.Path(os.path.abspath(args.library or settings.craft / "lib/libdolphinprivate.6.dylib"))
if not library.is_file():
    raise SystemExit(f"Missing Dolphin test library: {library}")
cmake = settings.craft / "dev-utils/bin/cmake"
def cmake_literal(value):
    text = str(value)
    equals = ""
    while "]" + equals + "]" in text:
        equals += "="
    return f"[{equals}[{text}]{equals}]"


cmakelists = f"""cmake_minimum_required(VERSION 3.16)
project(accessibility_layout_check LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)
find_package(Qt6 REQUIRED COMPONENTS Gui)
add_executable(check {cmake_literal(root / "tests/accessibility-layout-check.cpp")} {cmake_literal(src / "kitemviews/private/kitemlistviewlayouter.cpp")})
target_include_directories(check PRIVATE {cmake_literal(src)} {cmake_literal(settings.build / "src")} "${{CMAKE_CURRENT_SOURCE_DIR}}")
target_link_libraries(check PRIVATE Qt6::Gui {cmake_literal(library)})
"""
with tempfile.TemporaryDirectory(prefix="dolphin-accessibility-") as directory:
    work = pathlib.Path(directory)
    (work / "CMakeLists.txt").write_text(cmakelists)
    (work / "methods.inc").write_text("\n".join(methods))
    build = work / "build"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([str(cmake), "-S", str(work), "-B", str(build), f"-DCMAKE_PREFIX_PATH={settings.craft}", "-DCMAKE_BUILD_TYPE=Release"],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(cmake), "--build", str(build)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([str(build / "check")], check=True, env=env)
