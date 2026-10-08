"""Create a real Qt screenshot and exported demo map for review."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
INTERPRETER = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if INTERPRETER.exists() and Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
    raise SystemExit(
        subprocess.call([str(INTERPRETER), str(Path(__file__).resolve()), *sys.argv[1:]])
    )
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from avalanche_view.logging_config import configure_logging  # noqa: E402
from avalanche_view.services.export_service import ExportService  # noqa: E402
from avalanche_view.ui.main_window import MainWindow  # noqa: E402
from avalanche_view.visualization.layers import RenderMode  # noqa: E402


def main() -> int:
    configure_logging()
    application = QApplication([])
    output = ROOT / "docs"
    output.mkdir(exist_ok=True)
    settings = QSettings(str(ROOT / ".runtime" / "preview.ini"), QSettings.Format.IniFormat)
    settings.clear()
    window = MainWindow(settings, renderer="legacy")
    window.resize(1640, 1080)
    window.show()
    errors = []

    def prepare(dataset):
        window.add_layer("SNOWH")
        snow = window.layers.layers[0]
        window.update_layer(
            replace(snow, opacity=0.48, automatic_range=False, minimum=0, maximum=2)
        )
        window.add_layer("Wind Speed 10m")
        wind = window.layers.layers[0]
        window.update_layer(
            replace(
                wind,
                mode=RenderMode.WIND_VECTORS,
                show_colorbar=False,
                vector_stride=6,
                opacity=0.9,
            )
        )
        window.timeline.slider.setValue(4)
        grid = dataset.coordinates(4)
        window.inspect_point(grid.x[34, 35], grid.y[34, 35])
        window.select_layer(snow.id)
        window.layer_manager.refresh(window.layers.layers, snow.id)
        window.inspector.variable.setCurrentText("SNOWH")
        QTimer.singleShot(800, capture)

    def capture():
        try:
            window._redraw_timer.stop()
            window._render()
            window.map.canvas.draw()
            application.processEvents()
            if not window.grab().save(str(output / "screenshot.png")):
                raise RuntimeError("Could not save screenshot")
            ExportService.export_png(window.map.figure, output / "demo_map.png")
            print(f"Screenshot: {output / 'screenshot.png'}")
            print(f"PNG map: {output / 'demo_map.png'}")
        except Exception as exc:
            errors.append(str(exc))
            raise
        finally:
            window.close()

    window.dataset_loaded.connect(prepare)
    QTimer.singleShot(0, window.load_demo)
    QTimer.singleShot(20000, window.close)
    result = application.exec()
    return 1 if errors else result


if __name__ == "__main__":
    raise SystemExit(main())
