#!/usr/bin/env python3
"""Compila el método real de Dolphin y comprueba sus filas accesibles."""
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dolphin_config import load
source = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else load().source / "src/kitemviews/accessibility/kitemlistviewaccessible.cpp"
text = source.read_text()
start = text.index("int KItemListViewAccessible::rowCount() const")
end = text.index("\nint KItemListViewAccessible::selectedCellCount()", start)
method = text[start:end]
harness = r'''
#include <iostream>
struct Model { int items; int count() const { return items; } };
struct View { Model data; const Model *model() const { return &data; } };
struct KItemListViewAccessible {
    View data; int columns;
    const View *view() const { return &data; }
    int columnCount() const { return columns; }
    int rowCount() const;
};
METHOD
int main() {
    struct Case { int items, columns, expected; };
    const Case cases[] = {{0,0,0},{0,3,0},{1,3,1},{2,3,1},{3,3,1},
                          {4,3,2},{7,3,3},{1,1,1},{7,1,7},{7,20,1}};
    for (auto c : cases) {
        KItemListViewAccessible a{{{c.items}},c.columns};
        if (a.rowCount() != c.expected) {
            std::cerr << "Fallo: " << c.items << " elementos, " << c.columns
                      << " columnas: " << a.rowCount() << " filas; esperado " << c.expected << '\n';
            return 1;
        }
    }
    std::cout << "10 casos de filas accesibles: OK\n";
}
'''.replace("METHOD", method)
with tempfile.TemporaryDirectory(prefix="dolphin-accessibility-") as directory:
    cpp = pathlib.Path(directory) / "check.cpp"
    binary = pathlib.Path(directory) / "check"
    cpp.write_text(harness)
    subprocess.run(["c++", "-std=c++17", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
