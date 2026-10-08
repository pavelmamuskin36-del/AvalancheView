"""Metadata-only series index with bounded, on-demand file and field caches."""

import hashlib
import json
import logging
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import numpy as np

from avalanche_view.config import CACHE_LIMIT_BYTES
from avalanche_view.data.dataset import NETCDF_LOCK, DatasetError
from avalanche_view.data.derived import default_registry
from avalanche_view.data.time_axis import format_timestamp
from avalanche_view.data.variable import VariableInfo
from avalanche_view.data.wrf_dataset import WRFDataset

logger = logging.getLogger(__name__)


class Compatibility(StrEnum):
    COMPATIBLE = "Compatible"
    PARTIAL = "Partially Compatible"
    INCOMPATIBLE = "Incompatible"


@dataclass(frozen=True)
class CompatibilityResult:
    status: Compatibility
    reasons: tuple[str, ...] = ()
    unavailable: frozenset[str] = frozenset()


@dataclass
class FileEntry:
    path: Path
    times: tuple[datetime | None, ...]
    metadata: dict
    variables: dict[str, VariableInfo]
    dimensions: dict[str, int]
    time_dimension: str | None
    x_dimension: str
    y_dimension: str
    latitude_name: str | None
    longitude_name: str | None
    projection: object
    domain: str
    model_type: str
    coordinate_signature: str
    projection_signature: str = ""
    unavailable: set[str] = field(default_factory=set)

    @property
    def timestamp(self):
        return self.times[0]

    @property
    def available_variables(self):
        return self.variables.keys() - self.unavailable

    def exclude_variables(self, names):
        self.unavailable.update(names)
        for variable in default_registry().available(set(self.variables)):
            if not set(variable.dependencies) <= self.available_variables:
                self.unavailable.add(variable.name)

    @classmethod
    def inspect(cls, path):
        with WRFDataset(path, cache_limit=0) as dataset:
            metadata = dataset.metadata
            title = str(metadata.get("TITLE", "")).upper()
            model_type = (
                "met_em"
                if metadata.get("FLAG_METGRID") or "METGRID" in title
                else ("WRF" if "WRF" in title or "bottom_top" in dataset.dimensions else "NetCDF")
            )
            match = re.search(r"(?:[._])d(\d+)(?:[._])", dataset.path.name)
            domain_id = metadata.get("grid_id", metadata.get("GRID_ID"))
            domain = (
                f"d{int(domain_id):02d}"
                if domain_id is not None
                else (f"d{int(match[1]):02d}" if match else "—")
            )
            if match and domain_id is not None and int(match[1]) != int(domain_id):
                raise DatasetError("Domain в имени файла не совпадает с grid_id в метаданных")
            signatures = []
            for timestep in range(dataset.time_count):
                grid = dataset.coordinates(timestep)
                if not np.isfinite(grid.x).all() or not np.isfinite(grid.y).all():
                    raise DatasetError("Координаты содержат некорректные значения")
                digest = hashlib.sha256()
                digest.update(str((grid.geographic, grid.x.shape)).encode())
                for values in (grid.x, grid.y):
                    digest.update(
                        np.round(values, 6 if grid.geographic else 3).astype("<f8").tobytes()
                    )
                signatures.append(digest.hexdigest())
            if len(set(signatures)) != 1:
                raise DatasetError("Файл содержит движущуюся сетку; откройте его отдельно")
            return cls(
                dataset.path,
                tuple(dataset.times),
                metadata,
                dataset.variables,
                dataset.dimensions,
                dataset.time_dimension,
                dataset.x_dimension,
                dataset.y_dimension,
                dataset.latitude_name,
                dataset.longitude_name,
                dataset.projection,
                domain,
                model_type,
                signatures[0],
                json.dumps(
                    {
                        name: dict(array.attrs)
                        for name, array in dataset.raw.variables.items()
                        if "grid_mapping_name" in array.attrs
                    },
                    sort_keys=True,
                    default=lambda value: np.asarray(value).tolist(),
                ),
            )


class DatasetCompatibilityChecker:
    @staticmethod
    def variable_schema(entry: FileEntry, name: str):
        info = entry.variables[name]
        return (
            tuple(
                (dimension, entry.dimensions[dimension])
                for dimension in info.dimensions
                if dimension != entry.time_dimension
            ),
            info.units,
            info.plottable,
        )

    def check(self, first: FileEntry, other: FileEntry) -> CompatibilityResult:
        reasons = []
        if first.model_type != other.model_type:
            reasons.append("Разные типы модели")
        if first.domain != other.domain:
            reasons.append(f"Разные domains: {first.domain} / {other.domain}")
        if (first.x_dimension, first.y_dimension) != (other.x_dimension, other.y_dimension) or any(
            first.dimensions.get(dim) != other.dimensions.get(dim)
            for dim in (
                first.x_dimension,
                first.y_dimension,
                first.x_dimension + "_stag",
                first.y_dimension + "_stag",
            )
        ):
            reasons.append("Разные размеры горизонтальной сетки")
        if (
            first.projection != other.projection
            or first.projection_signature != other.projection_signature
        ):
            reasons.append("Разные проекции")
        for key in (
            "DX",
            "DY",
            "MAP_PROJ",
            "TRUELAT1",
            "TRUELAT2",
            "STAND_LON",
            "POLE_LAT",
            "POLE_LON",
        ):
            left, right = first.metadata.get(key), other.metadata.get(key)
            if left is None and right is None:
                continue
            try:
                equal = np.allclose(float(left), float(right), rtol=1e-7, atol=1e-7)
            except (TypeError, ValueError):
                equal = str(left) == str(right)
            if not equal:
                reasons.append(f"Различаются метаданные проекции: {key}")
        if first.coordinate_signature != other.coordinate_signature:
            reasons.append("Различаются координаты сетки (XLAT/XLONG или CF coordinates)")
        # met_em SIMULATION_START_DATE is the valid date, as observed in demo_data.
        if first.model_type == "WRF" and first.metadata.get(
            "SIMULATION_START_DATE"
        ) != other.metadata.get("SIMULATION_START_DATE"):
            reasons.append("Разные запуски WRF (SIMULATION_START_DATE)")
        if reasons:
            return CompatibilityResult(Compatibility.INCOMPATIBLE, tuple(reasons))
        common = first.variables.keys() & other.variables.keys()
        mismatches = frozenset(
            name
            for name in common
            if self.variable_schema(first, name) != self.variable_schema(other, name)
        )
        if mismatches or first.variables.keys() != other.variables.keys():
            return CompatibilityResult(
                Compatibility.PARTIAL,
                ("Различается состав, размерность или единицы переменных",),
                mismatches,
            )
        return CompatibilityResult(Compatibility.COMPATIBLE)


@dataclass
class SeriesGroup:
    entries: list[FileEntry]
    warnings: list[str] = field(default_factory=list)

    @property
    def label(self):
        first = self.entries[0]
        times = sorted(time for entry in self.entries for time in entry.times if time is not None)
        span = (
            f"{format_timestamp(times[0])} → {format_timestamp(times[-1])}"
            if times
            else "Время не определено"
        )
        return f"{first.model_type} / {first.domain} · {len(self.entries)} файлов\n{span}"


@dataclass
class ScanResult:
    groups: list[SeriesGroup]
    errors: list[str]


def analyse_files(paths, progress=None) -> ScanResult:
    checker = DatasetCompatibilityChecker()
    groups, errors = [], []
    unique = sorted({Path(path).resolve() for path in paths}, key=lambda path: str(path).lower())
    for index, path in enumerate(unique):
        if progress:
            progress(index, len(unique), path.name)
        try:
            entry = FileEntry.inspect(path)
            if not all(time is not None for time in entry.times):
                raise DatasetError(
                    "Не удалось определить даты из данных или имени файла; откройте файл отдельно"
                )
            for group in groups:
                result = checker.check(group.entries[0], entry)
                if result.status != Compatibility.INCOMPATIBLE:
                    entry.exclude_variables(result.unavailable)
                    # Compare shared variables introduced after the first file, too.
                    for previous in group.entries:
                        for name in previous.available_variables & entry.available_variables:
                            if checker.variable_schema(previous, name) != checker.variable_schema(
                                entry, name
                            ):
                                entry.unavailable.add(name)
                    entry.exclude_variables(())
                    group.entries.append(entry)
                    if result.status == Compatibility.PARTIAL or entry.unavailable:
                        group.warnings.append(
                            f"{path.name}: частичная совместимость; недоступные переменные: {', '.join(sorted(entry.unavailable)) or 'разный состав'}"
                        )
                    break
            else:
                groups.append(SeriesGroup([entry]))
        except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
            message = f"{path.name}: {exc}"
            errors.append(message)
            logger.warning("Пропущен файл %s", message, exc_info=True)
    if progress:
        progress(len(unique), len(unique), "Анализ завершён")
    return ScanResult(groups, errors)


class VariableUnavailableError(DatasetError):
    pass


class DatasetSeries:
    def __init__(
        self,
        paths=None,
        *,
        entries=None,
        cache_limit=CACHE_LIMIT_BYTES,
        max_open_files=3,
        progress=None,
    ):
        if entries is None:
            result = analyse_files(paths or [], progress)
            if len(result.groups) != 1:
                raise DatasetError("Выберите одну совместимую серию. " + " | ".join(result.errors))
            entries = result.groups[0].entries
            self.warnings = result.errors + result.groups[0].warnings
        else:
            self.warnings = []
        if not entries:
            raise DatasetError("Нет подходящих файлов")
        checker = DatasetCompatibilityChecker()
        schemas = {}
        for entry in entries:
            mismatches = set()
            for name in entry.available_variables:
                schema = checker.variable_schema(entry, name)
                if name in schemas and schemas[name] != schema:
                    mismatches.add(name)
                else:
                    schemas[name] = schema
            entry.exclude_variables(mismatches)
        for entry in entries[1:]:
            compatibility = checker.check(entries[0], entry)
            if compatibility.status == Compatibility.INCOMPATIBLE:
                raise DatasetError("; ".join(compatibility.reasons))
            entry.exclude_variables(compatibility.unavailable)
        self.entries = list(entries)
        self.path = self.entries[0].path
        self.domain = self.entries[0].domain
        self.model_type = self.entries[0].model_type
        self.name = f"{self.model_type} {self.domain} · {len(self.entries)} файлов"
        self.metadata = dict(self.entries[0].metadata)
        self.projection = self.entries[0].projection
        self.latitude_name = self.entries[0].latitude_name
        self.longitude_name = self.entries[0].longitude_name
        self.x_dimension, self.y_dimension = (
            self.entries[0].x_dimension,
            self.entries[0].y_dimension,
        )
        self.time_dimension = self.entries[0].time_dimension or "time"
        candidates = sorted(
            [
                (time, str(entry.path).lower(), local, entry)
                for entry in self.entries
                for local, time in enumerate(entry.times)
                if time is not None
            ],
            key=lambda item: item[:3],
        )
        self._steps = []
        self.times = []
        seen = set()
        for date, _, local, entry in candidates:
            if date in seen:
                self.warnings.append(
                    f"Повтор времени {format_timestamp(date)}: пропущен {entry.path.name}, оставлен первый файл"
                )
                continue
            seen.add(date)
            self.times.append(date)
            self._steps.append((entry, local))
        if not self.times:
            raise DatasetError("В серии нет распознаваемых дат")
        self.time_count = len(self.times)
        self.timestamps = [format_timestamp(time) for time in self.times]
        self.dimensions = dict(self.entries[0].dimensions)
        self.dimensions[self.time_dimension] = self.time_count
        self.variables = {}
        for entry in self.entries:
            for dim, size in entry.dimensions.items():
                if dim != entry.time_dimension:
                    self.dimensions.setdefault(dim, size)
            for name in sorted(entry.available_variables):
                if name not in self.variables:
                    info = entry.variables[name]
                    dimensions = tuple(
                        self.time_dimension if dim == entry.time_dimension else dim
                        for dim in info.dimensions
                    )
                    shape = tuple(
                        self.time_count if dim == entry.time_dimension else size
                        for dim, size in zip(info.dimensions, info.shape, strict=True)
                    )
                    self.variables[name] = replace(info, dimensions=dimensions, shape=shape)
        differences = [
            (right - left).total_seconds()
            for left, right in zip(self.times, self.times[1:], strict=False)
        ]
        self.gaps = []
        if differences:
            intervals = Counter(differences)
            self.expected_interval = min(intervals, key=lambda value: (-intervals[value], value))
            self.gaps = [
                index + 1
                for index, seconds in enumerate(differences)
                if seconds > self.expected_interval * 1.5
            ]
        else:
            self.expected_interval = None
        self.cache_limit = max(0, cache_limit)
        self.max_open_files = max(1, max_open_files)
        self._datasets = OrderedDict()
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self.max_cached_timesteps = 3
        self._closed = False

    def _step(self, time):
        if self._closed:
            raise DatasetError("Dataset is closed.")
        if isinstance(time, datetime):
            time = self.times.index(time)
        if not 0 <= time < self.time_count:
            raise IndexError(time)
        return self._steps[time]

    def _dataset(self, entry):
        if entry.path in self._datasets:
            self._datasets.move_to_end(entry.path)
        else:
            while len(self._datasets) >= self.max_open_files:
                _, old = self._datasets.popitem(last=False)
                old.close()
            self._datasets[entry.path] = WRFDataset(entry.path, cache_limit=0)
        return self._datasets[entry.path]

    def get_dataset_for_time(self, time):
        """Borrow a source dataset; it remains owned by the series LRU."""
        with NETCDF_LOCK:
            entry, _ = self._step(time)
            return self._dataset(entry)

    def _source(self, name, time):
        entry, local = self._step(time)
        if name not in self.variables:
            raise KeyError(f"Variable not found: {name}")
        if name not in entry.available_variables:
            raise VariableUnavailableError(
                f"{name}: переменная недоступна для данного временного шага ({self.timestamps[time]})"
            )
        return self._dataset(entry), local

    def read(self, name, timestep=0, level=0):
        with NETCDF_LOCK:
            self._step(timestep)
            key = (name, timestep, level)
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            dataset, local = self._source(name, timestep)
            values = dataset.read(name, local, level)
            if values.nbytes <= self.cache_limit:
                while self._cache and self._cache_bytes + values.nbytes > self.cache_limit:
                    _, removed = self._cache.popitem(last=False)
                    self._cache_bytes -= removed.nbytes
                self._cache[key] = values
                self._cache_bytes += values.nbytes
                # Last field access for a date determines its recency.
                timesteps = list(reversed(dict.fromkeys(item[1] for item in reversed(self._cache))))
                for old_time in timesteps[: -self.max_cached_timesteps]:
                    for old_key in list(self._cache):
                        if old_key[1] == old_time:
                            self._cache_bytes -= self._cache.pop(old_key).nbytes
            return values

    def get_data(self, variable, time=0, level=0):
        if isinstance(time, datetime):
            time = self.times.index(time)
        return self.read(variable, time, level)

    def coordinates(self, timestep=0):
        with NETCDF_LOCK:
            entry, local = self._step(timestep)
            return self._dataset(entry).coordinates(local)

    def vertical_dimensions(self, name):
        excluded = {
            self.time_dimension,
            self.x_dimension,
            self.y_dimension,
            self.x_dimension + "_stag",
            self.y_dimension + "_stag",
        }
        info = self.variables[name]
        return {
            dim: size
            for dim, size in zip(info.dimensions, info.shape, strict=True)
            if dim not in excluded
        }

    def availability(self, variable):
        return sum(variable in entry.available_variables for entry, _ in self._steps)

    def point_value(self, name, timestep, row, column, level=0):
        with NETCDF_LOCK:
            dataset, local = self._source(name, timestep)
            return dataset.point_value(name, local, row, column, level)

    def vertical_profile(self, name, timestep, row, column):
        with NETCDF_LOCK:
            dataset, local = self._source(name, timestep)
            return dataset.vertical_profile(name, local, row, column)

    def snowpack_profile(self, timestep, row, column, language="ru"):
        """Build a detached profile using the source record's local time and schema."""
        from avalanche_view.data.snowpack import snowpack_profile

        with NETCDF_LOCK:
            entry, local = self._step(timestep)
            profile = snowpack_profile(self._dataset(entry), local, row, column, language)
            profile.timestep = timestep
            profile.timestamp = self.timestamps[timestep]
            return profile

    def time_series(self, name, row, column, level=0, progress=None):
        # Read one cell per source date; never materialize whole fields here.
        values = np.full(self.time_count, np.nan)
        if name not in self.variables:
            raise KeyError(name)
        for index in range(self.time_count):
            try:
                values[index] = self.point_value(name, index, row, column, level)
            except VariableUnavailableError:
                pass
            if progress:
                progress(index + 1, self.time_count, "Чтение временного ряда")
        return values

    def earth_relative_wind(self, timestep=0, level=0, variable="Wind Speed 10m"):
        with NETCDF_LOCK:
            dataset, local = self._source(variable, timestep)
            return dataset.earth_relative_wind(local, level, variable)

    def prefetch(self, timestep, fields):
        for name, level in fields:
            try:
                self.read(name, timestep, level)
            except (ValueError, KeyError, IndexError, OSError):
                logger.debug("Prefetch unavailable: %s", name, exc_info=True)

    @property
    def cache_bytes(self):
        return self._cache_bytes

    def close(self):
        with NETCDF_LOCK:
            for dataset in self._datasets.values():
                dataset.close()
            self._datasets.clear()
            self._cache.clear()
            self._cache_bytes = 0
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
