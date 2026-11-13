#!/usr/bin/env python3
"""Compile and check Dolphin's actual Quick Look selection timing methods."""
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dolphin_config import load


def cmake_literal(value):
    text = str(value)
    equals = ""
    while "]" + equals + "]" in text:
        equals += "="
    return f"[{equals}[{text}]{equals}]"


def extract_method(code, name):
    # Dolphin formats method braces at the start of a line; nested braces are indented.
    pattern = rf"^void DolphinMainWindow::{re.escape(name)}\(\)\s*\n\{{\n.*?^\}}"
    match = re.search(pattern, code, re.MULTILINE | re.DOTALL)
    if not match:
        raise RuntimeError(f"Cannot find DolphinMainWindow::{name} in the expected source format")
    return match.group(0)


def main():
    settings = load()
    code = (settings.source / "src/dolphinmainwindow.cpp").read_text()
    methods = [extract_method(code, name) for name in ("updateQuickLook", "closeQuickLook")]
    cmake = settings.craft / "dev-utils/bin/cmake"
    with tempfile.TemporaryDirectory(prefix="dolphin-quicklook-selection-") as directory:
        work = Path(directory)
        (work / "quicklook-selection-methods.inc").write_text("\n".join(methods))
        (work / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.16)
project(quicklook_selection_check LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
find_package(Qt6 REQUIRED COMPONENTS Core)
add_executable(check {cmake_literal(ROOT / "tests/quicklook-selection-check.cpp")})
target_include_directories(check PRIVATE "${{CMAKE_CURRENT_SOURCE_DIR}}")
target_link_libraries(check PRIVATE Qt6::Core)
''')
        build = work / "build"
        subprocess.run([str(cmake), "-S", str(work), "-B", str(build), f"-DCMAKE_PREFIX_PATH={settings.craft}"],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(cmake), "--build", str(build)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(build / "check")], check=True, env=dict(os.environ))


if __name__ == "__main__":
    main()
