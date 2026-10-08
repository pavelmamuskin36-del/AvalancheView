import logging
import traceback
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot

from avalanche_view.data.wrf_dataset import WRFDataset
from avalanche_view.visualization.layers import RenderMode

logger = logging.getLogger(__name__)


def supported_path(path: str | Path) -> bool:
    path = Path(path)
    return path.suffix.lower() in {".nc", ".nc4", ".cdf"} or path.name.lower().startswith(
        ("wrfout", "met_em")
    )


def model_files(directory):
    return sorted(
        path for path in Path(directory).iterdir() if path.is_file() and supported_path(path)
    )


def sibling_candidates(path):
    """Only discover paths here; analyse actual compatibility in the worker."""
    import re

    path = Path(path)
    match = re.match(r"(met_em[._]d\d+|wrfout[._]d\d+)[._]", path.name, re.IGNORECASE)
    if not match:
        return [path]
    prefix = match[1].lower()
    return [
        item
        for item in model_files(path.parent)
        if item.name.lower().startswith(prefix + ".") or item.name.lower().startswith(prefix + "_")
    ]


def open_dataset(path: str | Path) -> WRFDataset:
    return WRFDataset(path)


class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str, str)
    finished = pyqtSignal()
    progress = pyqtSignal(int, int, str)


class Worker(QRunnable):
    def __init__(self, function: Callable, *args, report_progress=False, **kwargs) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        if report_progress:
            self.kwargs["progress"] = self.signals.progress.emit

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as exc:
            details = traceback.format_exc()
            logger.error("Background task failed\n%s", details)
            self.signals.error.emit(str(exc), details)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class PreparedFrame:
    """A render snapshot, read in a worker; the Qt renderer never opens a file."""

    def __init__(self, dataset, layers, timestep):
        self.path = dataset.path
        self.metadata = dataset.metadata
        self.projection = dataset.projection
        self.timestamps = dataset.timestamps
        self.latitude_name = dataset.latitude_name
        self.longitude_name = dataset.longitude_name
        self._grid = dataset.coordinates(timestep)
        self._fields = {}
        self._winds = {}
        for layer in layers:
            key = (layer.variable, layer.level)
            try:
                self._fields[key] = dataset.read(layer.variable, timestep, layer.level)
                if layer.mode in (RenderMode.WIND_VECTORS, RenderMode.WIND_BARBS):
                    self._winds[key] = dataset.earth_relative_wind(
                        timestep, layer.level, layer.variable
                    )
            except (ValueError, KeyError, IndexError, OSError, RuntimeError) as exc:
                self._fields[key] = exc

    def coordinates(self, timestep=0):
        return self._grid

    def read(self, name, timestep=0, level=0):
        value = self._fields[(name, level)]
        if isinstance(value, Exception):
            raise value
        return value

    def earth_relative_wind(self, timestep=0, level=0, variable="Wind Speed 10m"):
        self.read(variable, timestep, level)
        return self._winds[(variable, level)]

    def point_value(self, name, timestep, row, column, level=0):
        return float(self.read(name, timestep, level)[row, column])
