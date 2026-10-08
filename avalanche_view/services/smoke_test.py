"""Opt-in verification of a bundled application's data, WebGL frame and PNG export."""

import json
import logging
import sys
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QTimer

from avalanche_view.config import PROJECT_ROOT, RUNTIME_ROOT
from avalanche_view.data.snowpack import SNOWPACK_VERTICAL_DIM

logger = logging.getLogger(__name__)


def install_smoke_test(window, application, report_path=None):
    """Exit nonzero on startup/render/export failure instead of treating a timeout as success."""
    report = {"frozen": bool(getattr(sys, "frozen", False)), "status": "running"}
    finished, started = False, False
    if report_path is not None:
        report_path = Path(report_path).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)

    def finish(success, error=""):
        nonlocal finished
        if finished:
            return
        finished = True
        report.update(status="passed" if success else "failed", error=error)
        logger.info("Smoke test: %s", json.dumps(report, ensure_ascii=False))
        if report_path is not None:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        application.exit(0 if success else 1)

    def failed(title, message, *details):
        finish(False, f"{title}: {message}")

    def ready(*args):
        nonlocal started
        if started or finished:
            return
        started = True
        try:
            data = window.dataset
            if data is None:
                raise ValueError("No dataset was loaded")
            if window.gis_enabled:
                warnings = window._frame.scene["warnings"]
                if warnings:
                    raise ValueError("; ".join(warnings))
            report.update(
                renderer="gis" if window.gis_enabled else "legacy",
                file=str(data.path), time_count=data.time_count,
                dimensions=data.dimensions, runtime_root=str(RUNTIME_ROOT),
                bundled_web_resources=(PROJECT_ROOT / "avalanche_view/resources/web/index.html").is_file(),
            )
            if SNOWPACK_VERTICAL_DIM in data.dimensions and "SNPACK_T" in data.variables:
                point = (0, 0)
                for timestep in range(min(data.time_count, 3)):
                    indices = np.argwhere(data.read("SN_NLAYERS", timestep) > 0)
                    if indices.size:
                        point = tuple(int(index) for index in indices[0])
                        break
                report["snowpack_active_counts"] = [
                    len(data.vertical_profile("SNPACK_T", timestep, *point))
                    for timestep in range(min(data.time_count, 3))
                ]
            if report_path is not None:
                window.grab().save(str(report_path.with_suffix(".window.png")))
                if window.gis_enabled:
                    window.map.export_finished.connect(lambda _: finish(True))
                    window._export_png(report_path.with_suffix(".map.png"))
                    return
            finish(True)
        except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
            finish(False, str(exc))

    window._show_error = failed
    if window.gis_enabled:
        window.map.frame_rendered.connect(lambda _: QTimer.singleShot(500, ready))
    else:
        window.dataset_loaded.connect(lambda _: QTimer.singleShot(1800, ready))
    QTimer.singleShot(60000, lambda: finish(False, "Startup/render/export timeout"))
