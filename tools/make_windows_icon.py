"""Render the existing SVG logo into the multi-size ICO used by the Windows bundle."""

import sys
from pathlib import Path

from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parents[1]
application = QGuiApplication(sys.argv[:1])
renderer = QSvgRenderer(str(root / "avalanche_view/resources/mountain.svg"))
if not renderer.isValid():
    raise ValueError("The application SVG icon could not be read")
canvas = QImage(256, 256, QImage.Format.Format_RGBA8888)
canvas.fill(Qt.GlobalColor.transparent)
painter = QPainter(canvas)
renderer.render(painter)
painter.end()
output = root / "build" / "AvalancheView.ico"
output.parent.mkdir(parents=True, exist_ok=True)
image = Image.frombytes("RGBA", (256, 256), canvas.constBits().asstring(canvas.sizeInBytes()))
image.save(output, sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
