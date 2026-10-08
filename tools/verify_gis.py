"""Real QWebEngine + met_em verification. Run: py tools/verify_gis.py."""

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

from PyQt6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from avalanche_view.data.dataset_series import DatasetSeries  # noqa: E402
from avalanche_view.logging_config import configure_logging  # noqa: E402
from avalanche_view.services.file_service import model_files  # noqa: E402
from avalanche_view.ui.main_window import MainWindow  # noqa: E402
from avalanche_view.visualization.layers import RenderMode  # noqa: E402


def main():
    configure_logging()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["AvalancheView GIS verification"])
    out = ROOT / "verification" / "gis"
    out.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(out / "settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    settings.setValue("maps/basemap", "relief")
    settings.setValue("maps/terrainSource", "model")
    window = MainWindow(settings)
    window.resize(1600, 1000)
    errors = []
    events = []
    window._show_error = lambda *args: errors.append(args)
    window.map.bridge.received.connect(
        lambda e: (
            events.append({k: v for k, v in e.items() if k != "png"})
            if e["type"] not in {"cursor"}
            else None
        )
    )
    window.show()

    def wait(predicate, label, seconds=60):
        until = time.monotonic() + seconds
        while not predicate():
            app.processEvents()
            QTest.qWait(25)
            if errors:
                raise AssertionError(errors)
            if time.monotonic() > until:
                raise TimeoutError(f"{label}: {events[-8:]}")

    def settled():
        wait(
            lambda: (
                window.map.last_frame is not None
                and window.map.last_frame.get("revision") == window._render_revision
                and not window._jobs
            ),
            "GPU frame",
        )

    def diagnostics():
        window.map.last_diagnostics = None
        window.map.send("diagnostics")
        wait(lambda: window.map.last_diagnostics is not None, "diagnostics")
        return window.map.last_diagnostics

    report = {}
    try:
        wait(lambda: window.map._ready, "WebGL startup")
        window.map.send("interactive", enabled=False)
        QTest.qWait(500)
        window.grab().save(str(out / "startup.png"))
        paths = model_files(ROOT / "demo_data")
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        series = DatasetSeries(paths)
        window._loaded(series)
        settled()
        window.add_layer("SNOWH")
        wait(lambda: len(window.layers.layers) == 1, "snow layer")
        settled()
        snow = window.layers.layers[0]
        window.update_layer(replace(snow, opacity=0.72, mode=RenderMode.NATIVE_GRID))
        settled()
        window.grab().save(str(out / "met_em_2d.png"))
        window.map.send(
            "camera", camera={"center": [43.4, 42.65], "zoom": 8.2, "pitch": 0, "bearing": 15}
        )
        QTest.qWait(500)
        before = diagnostics()
        window.timeline.slider.setValue(1)
        settled()
        after = diagnostics()
        assert before["camera"] == after["camera"], (before, after)
        window.timeline.speed.setCurrentText("4x")
        window.timeline.play.setChecked(True)
        wait(lambda: (window.map.last_frame or {}).get("timestep", 0) >= 3, "Timeline playback")
        window.timeline.pause()
        settled()
        assert diagnostics()["camera"] == before["camera"]
        report["playback_preserves_camera"] = True
        window.add_layer("Wind Speed (UU/VV)")
        wait(lambda: len(window.layers.layers) == 2, "wind layer")
        wind = window.layers.layers[0]
        window.update_layer(replace(wind, mode=RenderMode.WIND_BARBS, level=1))
        window.select_layer(wind.id)
        settled()
        window.map.set_mode(True)
        QTest.qWait(800)

        def terrain_loaded():
            state = diagnostics()
            return (state.get("height") or 0) > 0

        wait(terrain_loaded, "DEM tiles", seconds=90)
        QTest.qWait(300)
        report["three_dimensional"] = diagnostics()
        assert report["three_dimensional"]["terrain"] is not None
        assert "wind-glyphs" in report["three_dimensional"]["deckLayers"]
        assert report["three_dimensional"]["height"] > 0
        window.grab().save(str(out / "met_em_3d.png"))
        window.map.export_png(str(out / "map_export.png"), scale=2)
        wait(lambda: any(e["type"] == "export" for e in events), "PNG export")
        QTest.qWait(800)
        window.grab().save(str(out / "after_export.png"))
        window.map.set_mode(False)
        QTest.qWait(800)
        checked_modes = []
        for mode in (
            RenderMode.FILL_CONTOURS,
            RenderMode.CONTOUR_LINES,
            RenderMode.FILLED_CONTOURS,
        ):
            window.update_layer(replace(window.layers.get(snow.id), mode=mode, levels=8))
            settled()
            assert not window._frame.scene["warnings"]
            checked_modes.append(mode.value)
        for mode in (
            RenderMode.WIND_VECTORS,
            RenderMode.STREAMLINES,
            RenderMode.WIND_SPEED_ARROWS,
            RenderMode.WIND_SPEED_BARBS,
        ):
            window.update_layer(replace(window.layers.get(wind.id), mode=mode, opacity=0.7))
            settled()
            assert not window._frame.scene["warnings"]
            if mode == RenderMode.STREAMLINES:
                assert "wind-streamlines" in diagnostics()["deckLayers"]
                window.grab().save(str(out / "streamlines.png"))
            checked_modes.append(mode.value)
        for index in range(2, series.time_count):
            window.timeline.slider.setValue(index)
            settled()
        window.set_visibility(wind.id, False)
        window.update_layer(
            replace(window.layers.get(snow.id), mode=RenderMode.FILL_CONTOURS, opacity=0.3)
        )
        settled()
        window.map.send("fit")
        QTest.qWait(1200)
        window.map.basemap.setCurrentIndex(window.map.basemap.findData("satellite"))
        QTest.qWait(12000)
        report["satellite_tile_errors"] = [e["message"] for e in events if e["type"] == "tileError"]
        window.grab().save(str(out / "satellite_terrain.png"))
        window.inspect_point(43.4, 42.65)
        settled()
        window.terrain_controls.analysis.setCurrentIndex(2)
        window.terrain_controls.derive()
        wait(lambda: not window._jobs, "aspect analysis")
        QTest.qWait(1500)
        window.grab().save(str(out / "terrain_aspect.png"))
        assert hashes == {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        }
        report.update(
            {
                "status": "passed",
                "files": len(paths),
                "shape": list(series.coordinates().x.shape),
                "camera_preserved": True,
                "raw_files_unchanged": True,
                "modes": checked_modes,
                "startup": before,
                "events": events,
            }
        )
        print(
            json.dumps({k: v for k, v in report.items() if k != "events"}, ensure_ascii=False),
            flush=True,
        )
    except Exception as exc:
        window.grab().save(str(out / "failure.png"))
        report.update({"status": "failed", "error": str(exc), "events": events})
        raise
    finally:
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
