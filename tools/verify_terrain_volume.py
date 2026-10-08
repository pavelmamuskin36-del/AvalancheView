"""Compare coarse model terrain with real DEM in the same mountain camera."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv"
INTERPRETER = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if INTERPRETER.exists() and Path(sys.prefix).resolve() != ENVIRONMENT.resolve():
    raise SystemExit(subprocess.call([str(INTERPRETER), str(Path(__file__).resolve())]))
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from avalanche_view.data.wrf_dataset import WRFDataset  # noqa: E402
from avalanche_view.gis.basemaps import DETAILED_TERRAIN_ID  # noqa: E402
from avalanche_view.logging_config import configure_logging  # noqa: E402
from avalanche_view.ui.main_window import MainWindow  # noqa: E402


def main():
    configure_logging()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["Terrain volume verification"])
    output = ROOT / "verification" / "terrain-volume"
    output.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(output / "settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    settings.setValue("maps/basemap", "relief")
    settings.setValue("maps/terrainSource", "model")
    window = MainWindow(settings)
    window.resize(1500, 950)
    events, errors = [], []
    window.map.bridge.received.connect(lambda event: events.append({k: v for k, v in event.items() if k != "png"}))
    window._show_error = lambda *args: errors.append(args)
    window.show()

    def wait(predicate, label, timeout=90):
        end = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            QTest.qWait(40)
            if errors or time.monotonic() > end:
                raise AssertionError(f"{label}: {errors or events[-6:]}")

    def diagnostics():
        window.map.last_diagnostics = None
        window.map.send("diagnostics")
        wait(lambda: window.map.last_diagnostics is not None, "diagnostics", 15)
        return window.map.last_diagnostics

    def terrain_ready(expected=None):
        value = diagnostics()
        source = value.get("terrainSource") or {}
        return (expected is None or source.get("id") == expected) and (value["height"] or 0) > 1000

    report = {}
    try:
        wait(lambda: window.map._ready, "WebGL ready")
        window.map.send("interactive", enabled=False)
        dataset = WRFDataset(next((ROOT / "demo_data").glob("met_em*")))
        window._loaded(dataset)
        wait(lambda: window.map.last_frame is not None and not window._jobs, "model ready")
        window.map.focus_mountains()
        QTest.qWait(1800)
        wait(lambda: terrain_ready(), "model terrain tiles")
        report["model"] = diagnostics()
        window.grab().save(str(output / "model_9km.png"))
        window.map.select_terrain(DETAILED_TERRAIN_ID)
        QTest.qWait(500)
        wait(lambda: terrain_ready(DETAILED_TERRAIN_ID), "detailed terrain tiles")
        report["real_dem"] = diagnostics()
        assert report["real_dem"]["terrainSource"]["id"] == DETAILED_TERRAIN_ID
        assert report["real_dem"]["terrainSource"]["encoding"] == "terrarium"
        QTest.qWait(600)
        window.map.send("elevationProbe", points=[[42.4453, 43.355], [42.516, 43.252]])
        wait(lambda: any(e["type"] == "elevationProbe" for e in events), "peak/valley probe")
        probe = next(e for e in reversed(events) if e["type"] == "elevationProbe")
        report["peak_valley"] = probe["points"]
        assert probe["points"][0]["height"] > 5000
        assert probe["points"][1]["height"] < 3500
        window.grab().save(str(output / "real_mountains.png"))
        print("Real DEM relief verified", report["peak_valley"], flush=True)
        window.map.export_png(str(output / "real_mountains_export.png"), scale=2)
        wait(lambda: any(e["type"] == "export" for e in events), "terrain export")
        # Ordinary 2D/3D toggles must preserve position and zoom.
        before = diagnostics()["camera"]
        window.map.set_mode(False)
        QTest.qWait(800)
        flat = diagnostics()["camera"]
        assert abs(flat["zoom"] - before["zoom"]) < 1e-6
        assert max(abs(a-b) for a, b in zip(flat["center"], before["center"], strict=True)) < 1e-6
        window.map.set_mode(True)
        QTest.qWait(800)
        window.add_layer("SNOWH")
        wait(lambda: window.map.last_frame.get("revision") == window._render_revision and len(window.layers.layers) == 1, "draped snow")
        window.grab().save(str(output / "snow_on_real_terrain.png"))
        report.update(status="passed", events=[e for e in events if e["type"] in {"error", "tileError", "terrainUnavailable"}])
    except Exception as exc:
        report.update(status="failed", error=str(exc), events=events[-15:])
        window.grab().save(str(output / "failure.png"))
        raise
    finally:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
