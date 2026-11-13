#!/usr/bin/env python3
"""Build and exercise the Quick Look bridge with a native Qt window."""
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


def main():
    settings = load()
    source = settings.source / "src"
    cmake = settings.craft / "dev-utils/bin/cmake"
    with tempfile.TemporaryDirectory(prefix="dolphin-quicklook-native-") as directory:
        work = Path(directory)
        (work / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.16)
project(quicklook_native_check LANGUAGES CXX OBJCXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_OBJCXX_STANDARD 17)
set(CMAKE_MACOSX_BUNDLE_GUI_IDENTIFIER "local.dolphin.quicklook.native-test")
find_package(Qt6 REQUIRED COMPONENTS Widgets)
add_executable(check MACOSX_BUNDLE {cmake_literal(ROOT / "tests/quicklook-native-check.mm")} {cmake_literal(source / "quicklook_macos.mm")})
target_compile_options(check PRIVATE -fobjc-arc)
target_include_directories(check PRIVATE {cmake_literal(source)})
target_link_libraries(check PRIVATE Qt6::Widgets "-framework AppKit" "-framework QuickLookUI")
''')
        build = work / "build"
        subprocess.run([str(cmake), "-S", str(work), "-B", str(build), f"-DCMAKE_PREFIX_PATH={settings.craft}"],
                       check=True, stdout=subprocess.DEVNULL)
        subprocess.run([str(cmake), "--build", str(build)], check=True, stdout=subprocess.DEVNULL)
        result = subprocess.run([str(build / "check.app/Contents/MacOS/check")], timeout=30)
        if result.returncode == 77:
            raise RuntimeError("The native test could not activate its window; no controller result is available")
        result.check_returncode()


if __name__ == "__main__":
    main()
