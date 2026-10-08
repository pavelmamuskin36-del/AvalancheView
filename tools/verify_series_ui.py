"""Exercise the real demo_data series through Qt actions and save evidence."""

import hashlib
import json
import os
import subprocess
import sys
import time
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

import numpy as np  # noqa: E402
from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from avalanche_view.logging_config import configure_logging  # noqa: E402
from avalanche_view.services.file_service import model_files  # noqa: E402
from avalanche_view.ui.main_window import MainWindow  # noqa: E402
from avalanche_view.visualization.layers import RenderMode  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    configure_logging()
    app = QApplication([])
    paths = model_files(ROOT / "demo_data")
    if len(paths) < 2:
        raise RuntimeError("Need at least two real model files in demo_data")
    before = {str(path): digest(path) for path in paths}
    output = ROOT / "docs"
    settings_path = ROOT / "verification" / "real-series-layout.ini"
    settings_path.parent.mkdir(exist_ok=True)
    settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    settings.clear()
    window = MainWindow(settings, renderer="legacy")
    window.show()
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window._show_message = lambda *args: print(str(args[0]), flush=True)

    def wait(predicate, label, timeout=120):
        deadline = time.monotonic() + timeout
        while not predicate():
            if errors:
                raise AssertionError(errors)
            if time.monotonic() > deadline:
                raise TimeoutError(label)
            app.processEvents()
            QTest.qWait(20)
        app.processEvents()

    def settled(index):
        wait(
            lambda: (
                window._frame_timestep == index
                and not window._jobs
                and not window._redraw_timer.isActive()
            ),
            f"Frame {index}",
        )
        window.map.canvas.draw()

    original_dialog = QFileDialog.getOpenFileNames
    QFileDialog.getOpenFileNames = lambda *args: ([str(path) for path in reversed(paths)], "")
    window.open_series_action.trigger()
    QFileDialog.getOpenFileNames = original_dialog
    wait(lambda: window.dataset is not None, "Open real series")
    settled(0)
    series = window.dataset
    print(f"Loaded {len(series.entries)} real files / {series.time_count} dates", flush=True)
    window.add_layer("SNOWH")
    wait(lambda: len(window.layers.layers) == 1, "Add snow")
    settled(0)
    snow_id = window.layers.layers[0].id
    initial = window._frame.read("SNOWH").copy()
    extent = window.map.axes.get_xlim(), window.map.axes.get_ylim()
    window.timeline.speed.setCurrentText("4x")
    window.play_action.trigger()
    wait(
        lambda: window._frame_timestep is not None and window._frame_timestep >= 2, "Animate scalar"
    )
    window.timeline.pause()
    settled(window.timestep)
    assert window.layers.layers[0].id == snow_id
    np.testing.assert_allclose(window.map.axes.get_xlim(), extent[0])
    np.testing.assert_allclose(window.map.axes.get_ylim(), extent[1])
    assert not np.array_equal(initial, window._frame.read("SNOWH"))
    print("Scalar animation and extent preserved", flush=True)
    window.add_layer("Wind Speed (UU/VV)")
    wait(lambda: len(window.layers.layers) == 2, "Add model wind")
    wind = window.layers.layers[0]
    window.update_layer(
        replace(wind, mode=RenderMode.WIND_VECTORS, vector_stride=7, opacity=0.8, level=5)
    )
    window.select_layer(wind.id)
    settled(window.timestep)
    first_wind = window._frame.earth_relative_wind(window.timestep, 5, wind.variable)[0].copy()
    start = window.timestep
    window.play_action.trigger()
    wait(lambda: window._frame_timestep != start, "Animate wind")
    window.timeline.pause()
    settled(window.timestep)
    changed_wind = not np.array_equal(
        first_wind, window._frame.earth_relative_wind(window.timestep, 5, wind.variable)[0]
    )
    assert changed_wind
    grid = window._frame.coordinates()
    point = (grid.x.shape[0] // 2, grid.x.shape[1] // 2)
    window.inspect_point(grid.x[point], grid.y[point])
    settled(window.timestep)
    window.show_time_series("SNOWH")
    wait(lambda: window.plots.tabs.count() == 1, "Cross-file point graph")
    wait(lambda: not window._jobs, "Graph jobs complete")
    plotted = window.plots.tabs.widget(0).canvas.figure.axes[0].lines[0].get_ydata()
    np.testing.assert_allclose(plotted, series.time_series("SNOWH", *point))
    window.layers_dock.close()
    assert not window.layers_dock.toggleViewAction().isChecked()
    window.layers_dock.toggleViewAction().trigger()
    assert window.layers_dock.isVisible()
    window.plots_dock.close()
    window.plots_dock.toggleViewAction().trigger()
    assert window.plots_dock.isVisible()
    QTest.qWait(300)
    assert window.grab().save(str(output / "series_screenshot.png"))
    screenshot = output / "series_screenshot.png"
    window.toolbar.hide()
    window.layers_dock.close()
    window.close()
    wait(lambda: not window.isVisible(), "Close")
    reopened = MainWindow(settings, renderer="legacy")
    reopened.show()
    app.processEvents()
    assert not reopened.layers_dock.isVisible() and not reopened.toolbar.isVisible()
    reopened.restore_default_layout()
    assert all(dock.isVisible() for dock in reopened.docks)
    reopened.close()
    assert {str(path): digest(path) for path in model_files(ROOT / "demo_data")} == before
    report = {
        "files": len(paths),
        "timesteps": len(series.times),
        "timestamps": series.timestamps,
        "domain": series.domain,
        "scalar_animation": True,
        "wind_animation": changed_wind,
        "point_time_series": np.asarray(plotted).tolist(),
        "panels_reopened": True,
        "layout_restored_after_restart": True,
        "demo_data_sha256_unchanged": True,
        "screenshot": str(screenshot),
        "method": "Automated Qt actions; file chooser selection supplied programmatically",
    }
    (output / "series_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
