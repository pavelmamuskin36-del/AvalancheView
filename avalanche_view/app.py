import argparse
import logging
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSettings, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from avalanche_view.config import APPLICATION, ORGANIZATION
from avalanche_view.logging_config import configure_logging
from avalanche_view.ui.main_window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="AvalancheView • WRF / NetCDF desktop viewer")
    parser.add_argument(
        "file", nargs="*", type=Path, help="NetCDF / WRF file(s) or model folder to open"
    )
    parser.add_argument("--demo", action="store_true", help="Open synthetic demo data")
    parser.add_argument("--legacy-map", action="store_true", help="Explicit Matplotlib map for debugging")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Open demo and close after initial rendering"
    )
    parser.add_argument("--smoke-report", type=Path, help="Write smoke-test results and map PNG")
    args = parser.parse_args()
    configure_logging()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application = QApplication(sys.argv[:1])
    application.setOrganizationName(ORGANIZATION)
    application.setApplicationName(APPLICATION)

    def exception_hook(kind, value, tb):
        details = "".join(traceback.format_exception(kind, value, tb))
        logging.getLogger(__name__).error("Unhandled application error\n%s", details)
        box = QMessageBox(
            QMessageBox.Icon.Critical,
            "AvalancheView error",
            str(value),
            QMessageBox.StandardButton.Ok,
        )
        box.setDetailedText(details)
        box.exec()

    sys.excepthook = exception_hook
    smoke_settings = None
    if args.smoke_test and args.smoke_report:
        args.smoke_report = args.smoke_report.resolve()
        args.smoke_report.parent.mkdir(parents=True, exist_ok=True)
        smoke_settings = QSettings(str(args.smoke_report.with_suffix(".ini")), QSettings.Format.IniFormat)
        smoke_settings.setValue("maps/basemap", "none")
        smoke_settings.setValue("maps/terrainSource", "model")
    window = MainWindow(smoke_settings, renderer="legacy" if args.legacy_map else "gis")
    window.show()
    if args.smoke_test:
        from avalanche_view.services.smoke_test import install_smoke_test

        install_smoke_test(window, application, args.smoke_report)
    if args.file:
        if len(args.file) > 1:
            QTimer.singleShot(0, lambda: window.open_paths(args.file))
        else:
            QTimer.singleShot(0, lambda: window.open_path(args.file[0]))
    elif args.demo or args.smoke_test:
        QTimer.singleShot(0, window.load_demo)
    return application.exec()
