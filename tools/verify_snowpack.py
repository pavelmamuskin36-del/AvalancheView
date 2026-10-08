"""Exercise Snowpack through the real GIS window. Usage: python tools/verify_snowpack.py FILE."""

import argparse
import hashlib
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
    raise SystemExit(
        subprocess.call([str(INTERPRETER), str(Path(__file__).resolve()), *sys.argv[1:]])
    )
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QSettings, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from avalanche_view.data.snowpack import SNOWPACK_VERTICAL_DIM, snowpack_profile  # noqa: E402
from avalanche_view.data.wrf_dataset import WRFDataset  # noqa: E402
from avalanche_view.ui.main_window import MainWindow  # noqa: E402
from avalanche_view.ui.snowpack_profile_dialog import SnowpackProfileDialog  # noqa: E402


def file_digest(path):
    """Hash large wrfout files without materializing their contents in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    """Verify one supplied history file, preserving its bytes and reporting actual counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--row", type=int)
    parser.add_argument("--column", type=int)
    args = parser.parse_args()
    if (args.row is None) != (args.column is None):
        parser.error("--row and --column must be specified together")
    original_hash = file_digest(args.file)
    out = ROOT / "verification" / "snowpack"
    out.mkdir(parents=True, exist_ok=True)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(["AvalancheView SNOWPACK verification"])
    settings = QSettings(str(out / "settings.ini"), QSettings.Format.IniFormat)
    settings.clear()
    settings.setValue("maps/basemap", "none")
    settings.setValue("maps/terrainSource", "model")
    window = MainWindow(settings)
    window.resize(1600, 1000)
    errors = []
    window._show_error = lambda *details: errors.append(details)
    window.show()

    def wait(predicate, label, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            app.processEvents()
            QTest.qWait(25)
            if errors:
                raise AssertionError(errors)
            if time.monotonic() > deadline:
                raise TimeoutError(label)

    def settled():
        wait(
            lambda: (
                window.map.last_frame is not None
                and window.map.last_frame.get("revision") == window._render_revision
                and not window._jobs
            ),
            "GIS frame",
        )
        assert not window._frame.scene["warnings"], window._frame.scene["warnings"]

    report = {"file": str(args.file), "status": "running"}
    try:
        wait(lambda: window.map._ready, "WebGL startup")
        window._loaded(WRFDataset(args.file))
        data = window.dataset
        assert SNOWPACK_VERTICAL_DIM in data.dimensions
        active = None
        for timestep in range(data.time_count):
            counts = data.read("SN_NLAYERS", timestep)
            if args.row is None:
                candidates = np.argwhere(np.isfinite(counts) & (counts > 0))
                if candidates.size:
                    active = timestep, tuple(int(index) for index in candidates[0])
            elif counts[args.row, args.column] > 0:
                active = timestep, (args.row, args.column)
            if active is not None:
                break
        if active is None:
            raise ValueError("No active SNOWPACK cell found in the supplied history file")
        timestep, point = active
        window.timeline.slider.setValue(timestep)
        settled()
        for name in ("SNOWH", "SNOW", "TSK", "SN_NLAYERS"):
            if name in data.variables:
                window.add_layer(name)
                settled()
        grid = data.coordinates(timestep)
        window.inspect_point(float(grid.x[point]), float(grid.y[point]))
        wait(lambda: window.inspector.snow_button.isEnabled(), "Snowpack point summary")
        window.inspector.snow_button.click()
        wait(lambda: bool(window._dialogs), "Snowpack profile")
        dialog = window._dialogs[-1]
        assert isinstance(dialog, SnowpackProfileDialog)
        profile = snowpack_profile(data, timestep, *point)
        assert dialog.table.rowCount() == profile.count
        if profile.center_depth is not None:
            assert dialog.axes.yaxis_inverted()
        for name in ("SNPACK_T", "SN_VOLI", "SN_VOLW", "SN_VOLV", "SN_RG", "SN_RB", "SN_GRAINTYPE"):
            index = dialog.variable.findData(name)
            if index >= 0:
                dialog.variable.setCurrentIndex(index)
                assert len(profile.properties[name]) == profile.count
        dialog.variable.setCurrentIndex(max(0, dialog.variable.findData("SNPACK_T")))
        dialog.canvas.draw()
        dialog.resize(1200, 750)
        dialog.grab().save(str(out / "profile.png"))
        for name in ("SNOWH", "SNOW", "TSK", "SN_NLAYERS", "SNPACK_T"):
            if name in data.variables:
                window.show_time_series(name)
                wait(lambda: not window._jobs, f"Time series {name}")
        if "SN_GRAINTYPE" in data.variables:
            window.add_layer("SN_GRAINTYPE")
            settled()
            descriptor = next(
                layer
                for layer in window._frame.scene["layers"]
                if layer["variable"] == "SN_GRAINTYPE"
            )
            assert descriptor["categories"] and not descriptor["smooth"]
            for layer in window.layers.layers:
                if layer.variable != "SN_GRAINTYPE":
                    window.set_visibility(layer.id, False)
            settled()
        window.plots_dock.hide()
        window.map.send("fit")
        QTest.qWait(700)
        window.grab().save(str(out / "map.png"))
        window._export_png(out / "map_export.png")
        wait(
            lambda: (out / "map_export.png").is_file() and window.map._export_path is None,
            "PNG export",
        )
        counts = [
            len(data.vertical_profile("SNPACK_T", time_index, *point))
            for time_index in range(data.time_count)
        ]
        assert original_hash == file_digest(args.file)
        report.update(
            status="passed",
            point=point,
            timestep=timestep,
            capacity=data.dimensions[SNOWPACK_VERTICAL_DIM],
            active_counts=counts,
            raw_file_unchanged=True,
            bulk_inspector=True,
            profile=True,
            categorical_codes="SN_GRAINTYPE" in data.variables,
            time_series=True,
            png_export=True,
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
    except (
        AssertionError,
        TimeoutError,
        ValueError,
        KeyError,
        IndexError,
        OSError,
        RuntimeError,
    ) as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        window.timeline.pause()
        wait(lambda: not window._jobs, "Worker shutdown")
        window.close()
        app.processEvents()


if __name__ == "__main__":
    main()
