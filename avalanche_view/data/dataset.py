"""Lazy, serialized NetCDF access with a bounded cache of selected 2D fields."""

import logging
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np
import xarray as xr

from avalanche_view.config import CACHE_LIMIT_BYTES
from avalanche_view.data.coordinates import GridCoordinates, wrf_crs
from avalanche_view.data.derived import DerivedVariableRegistry, default_registry
from avalanche_view.data.paths import native_netcdf_path
from avalanche_view.data.snowpack import (
    SNOWPACK_DIAGNOSTICS,
    SNOWPACK_VERTICAL_DIM,
    active_layer_count,
    is_snowpack_variable,
    normalize_layer_counts,
)
from avalanche_view.data.time_axis import format_timestamp, read_time_axis
from avalanche_view.data.variable import VariableInfo

logger = logging.getLogger(__name__)
# netCDF/HDF libraries can be unsafe when multiple Qt jobs access different files.
NETCDF_LOCK = threading.RLock()


class DatasetError(ValueError):
    """A file or variable cannot be represented as a horizontal field."""


class Dataset:
    def __init__(
        self,
        path: str | Path,
        registry: DerivedVariableRegistry | None = None,
        cache_limit: int = CACHE_LIMIT_BYTES,
    ) -> None:
        self.path = Path(path)
        self.registry = registry or default_registry()
        self.cache_limit = cache_limit
        self._cache: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._cache_bytes = 0
        self._closed = False
        with NETCDF_LOCK:
            self.raw = self._open()
            try:
                self.dimensions = dict(self.raw.sizes)
                self.metadata = dict(self.raw.attrs)
                self.time_dimension = self._detect_time_dimension()
                self.time_count = self.dimensions.get(self.time_dimension, 1)
                self.times = read_time_axis(
                    self.raw, self.time_dimension, self.time_count, self.path
                )
                self.timestamps = self._timestamps()
                self.latitude_name = self._coordinate_name(True)
                self.longitude_name = self._coordinate_name(False)
                self.y_dimension, self.x_dimension = self._horizontal_dimensions()
                self.projection = wrf_crs(self.metadata)
                self.variables = self._variable_info()
            except Exception:
                self.raw.close()
                raise

    def _open(self) -> xr.Dataset:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        errors = []
        for engine in ("h5netcdf", "netcdf4"):
            path = native_netcdf_path(self.path) if engine == "netcdf4" else self.path
            for decode in (True, False):
                try:
                    data = xr.open_dataset(
                        path,
                        engine=engine,
                        decode_times=decode,
                        cache=False,
                    )
                    if not decode:
                        logger.warning("CF time decoding unavailable for %s", self.path)
                    return data
                except (OSError, ValueError, TypeError, ImportError) as exc:
                    errors.append(f"{engine}: {exc}")
        raise DatasetError("Unable to open NetCDF file. " + " | ".join(errors))

    def _detect_time_dimension(self) -> str | None:
        for name in self.dimensions:
            if name.lower() in {"time", "times", "xtime"}:
                return name
        for coordinate in self.raw.coords.values():
            if (
                coordinate.attrs.get("axis") == "T"
                or coordinate.attrs.get("standard_name") == "time"
            ):
                if coordinate.ndim == 1:
                    return coordinate.dims[0]
        return None

    def _timestamps(self) -> list[str]:
        if all(date is not None for date in self.times):
            return [format_timestamp(date) for date in self.times]
        if "Times" in self.raw:
            array = self.raw["Times"].to_numpy()
            result = []
            for row in np.atleast_1d(array):
                if np.ndim(row):
                    row = b"".join(row) if row.dtype.kind == "S" else "".join(row)
                value = row.decode("utf-8") if isinstance(row, bytes) else str(row)
                result.append(value.strip("\x00").replace("_", " ") + " UTC")
            if len(result) == self.time_count:
                return result
        if self.time_dimension in self.raw:
            coordinate = self.raw[self.time_dimension]
            if coordinate.ndim == 1:
                array = coordinate.to_numpy()
                if np.issubdtype(array.dtype, np.datetime64):
                    return [
                        np.datetime_as_string(t, unit="m").replace("T", " ") + " UTC" for t in array
                    ]
                units = coordinate.attrs.get("units", "")
                return [f"{self.time_dimension}: {t} {units}".strip() for t in array]
        if "XTIME" in self.raw and self.raw["XTIME"].ndim == 1:
            coordinate = self.raw["XTIME"]
            return [f"{t:g} {coordinate.attrs.get('units', 'min')}" for t in coordinate.to_numpy()]
        return [f"Step {i + 1} / {self.time_count}" for i in range(self.time_count)]

    def _coordinate_name(self, latitude: bool) -> str | None:
        candidates = (
            ("XLAT", "XLAT_M", "lat", "latitude", "LAT")
            if latitude
            else ("XLONG", "XLONG_M", "lon", "longitude", "LON")
        )
        for name in candidates:
            if name in self.raw:
                return name
        standard = "latitude" if latitude else "longitude"
        for name, array in self.raw.variables.items():
            if array.attrs.get("standard_name") == standard:
                return name
        return None

    def _horizontal_dimensions(self) -> tuple[str, str]:
        for y, x in (
            ("south_north", "west_east"),
            ("lat", "lon"),
            ("latitude", "longitude"),
            ("y", "x"),
        ):
            if y in self.dimensions and x in self.dimensions:
                return y, x
        if self.latitude_name and self.longitude_name:
            latitude, longitude = self.raw[self.latitude_name], self.raw[self.longitude_name]
            dims = [d for d in latitude.dims if d != self.time_dimension]
            if len(dims) == 2:
                return dims[0], dims[1]
            if len(dims) == 1 and longitude.ndim == 1:
                return dims[0], longitude.dims[0]
        excluded = {self.time_dimension, "bottom_top", "bottom_top_stag", "level", "lev", "z"}
        for array in self.raw.data_vars.values():
            dims = [d for d in array.dims if d not in excluded and not d.endswith("_stag")]
            if len(dims) >= 2 and np.issubdtype(array.dtype, np.number):
                return dims[-2], dims[-1]
        # A metadata-only/point dataset can still be inspected in the browser.
        return "", ""

    def _variable_info(self) -> dict[str, VariableInfo]:
        result = {}
        coordinate_names = set(self.raw.coords) | {
            self.latitude_name,
            self.longitude_name,
            "Times",
            "XTIME",
        }
        for name, array in self.raw.variables.items():
            dims = {d.removesuffix("_stag") for d in array.dims}
            plottable = (
                np.issubdtype(array.dtype, np.number)
                and {self.y_dimension, self.x_dimension} <= dims
                and bool(self.x_dimension and self.y_dimension)
            )
            result[name] = VariableInfo(
                name,
                tuple(array.dims),
                tuple(array.shape),
                str(array.attrs.get("units", "")),
                str(array.attrs.get("description", array.attrs.get("long_name", ""))),
                coordinate=name in coordinate_names,
                plottable=plottable,
            )
        for entry in self.registry.available(set(result)):
            if entry.name in result:
                continue  # A diagnostic must never replace a field supplied by the file.
            reference = result[entry.dependencies[0]]
            if entry.name in SNOWPACK_DIAGNOSTICS and any(
                not is_snowpack_variable(result[name])
                or dict(zip(result[name].dimensions, result[name].shape, strict=True))
                != dict(zip(reference.dimensions, reference.shape, strict=True))
                for name in entry.dependencies
            ):
                continue
            result[entry.name] = VariableInfo(
                entry.name,
                reference.dimensions,
                reference.shape,
                entry.units,
                entry.description,
                derived=True,
                plottable=all(result[n].plottable for n in entry.dependencies),
            )
        return result

    def _check(self, name: str, timestep: int) -> None:
        if self._closed:
            raise DatasetError("Dataset is closed.")
        if name not in self.variables:
            raise KeyError(f"Variable not found: {name}")
        if not 0 <= timestep < self.time_count:
            raise IndexError(f"Timestep {timestep} outside 0..{self.time_count - 1}")

    def vertical_dimensions(self, name: str) -> dict[str, int]:
        dimensions = self.variables[name].dimensions
        excluded = {
            self.time_dimension,
            self.x_dimension,
            self.y_dimension,
            self.x_dimension + "_stag",
            self.y_dimension + "_stag",
        }
        return {d: self.dimensions[d] for d in dimensions if d not in excluded}

    def _raw_field(
        self,
        name: str,
        timestep: int | None,
        level: int,
        point: tuple[int, int] | None = None,
        vertical_slice: tuple[str, slice] | None = None,
    ) -> xr.DataArray:
        array = self.raw[name]
        selections: dict[str, int | slice] = {}
        if timestep is not None and self.time_dimension in array.dims:
            selections[self.time_dimension] = timestep
        for dim, size in self.vertical_dimensions(name).items():
            if vertical_slice is not None and dim == vertical_slice[0]:
                selections[dim] = vertical_slice[1]
                continue
            if size == 1:
                selections[dim] = 0
                continue
            if not 0 <= level < size:
                raise IndexError(f"Level {level} outside dimension {dim} (size {size})")
            selections[dim] = level
        if point:
            row, column = point
            for dim, index in ((self.y_dimension, row), (self.x_dimension, column)):
                if dim in array.dims:
                    selections[dim] = slice(index, index + 1)
                if dim + "_stag" in array.dims:
                    selections[dim + "_stag"] = slice(index, index + 2)
        array = array.isel(selections)
        for dim in tuple(array.dims):
            if dim.endswith("_stag") and dim.removesuffix("_stag") in {
                self.x_dimension,
                self.y_dimension,
            }:
                axis = array.get_axis_num(dim)
                values = array.to_numpy()
                left = [slice(None)] * values.ndim
                right = left.copy()
                left[axis], right[axis] = slice(None, -1), slice(1, None)
                values = (values[tuple(left)] + values[tuple(right)]) * 0.5
                dims = tuple(d.removesuffix("_stag") if d == dim else d for d in array.dims)
                array = xr.DataArray(values, dims=dims, attrs=array.attrs)
        return array

    def _field(
        self,
        name: str,
        timestep: int | None,
        level: int,
        point: tuple[int, int] | None = None,
        vertical_slice: tuple[str, slice] | None = None,
    ) -> xr.DataArray:
        if self.variables[name].derived:
            entry = self.registry.get(name)
            fields = [self._raw_field(n, timestep, level, point, vertical_slice) for n in entry.dependencies]
            array = entry.compute(*fields)
            array.attrs = {"units": entry.units, "description": entry.description}
        else:
            array = self._raw_field(name, timestep, level, point, vertical_slice)
        if (
            vertical_slice is None
            and is_snowpack_variable(self.variables[name])
            and "SN_NLAYERS" in self.variables
        ):
            counts = self._raw_field("SN_NLAYERS", timestep, 0, point)
            capacity = self.vertical_dimensions(name)[SNOWPACK_VERTICAL_DIM]
            valid = xr.DataArray(
                normalize_layer_counts(counts.to_numpy(), capacity) > level,
                dims=counts.dims, coords=counts.coords,
            )
            array = array.where(valid)
        return array

    def read(self, name: str, timestep: int = 0, level: int = 0) -> np.ndarray:
        with NETCDF_LOCK:
            self._check(name, timestep)
            if not self.variables[name].plottable:
                raise DatasetError(f"{name} does not contain a numeric horizontal grid.")
            key = (
                name,
                timestep if self.time_dimension in self.variables[name].dimensions
                or is_snowpack_variable(self.variables[name]) else 0,
                level,
            )
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            field = self._field(name, timestep, level)
            if set(field.dims) != {self.y_dimension, self.x_dimension}:
                raise DatasetError(f"Unsupported field dimensions for {name}: {field.dims}")
            values = np.asarray(
                field.transpose(self.y_dimension, self.x_dimension).to_numpy(), dtype=float
            )
            values.setflags(write=False)
            if values.nbytes <= self.cache_limit:
                while self._cache and self._cache_bytes + values.nbytes > self.cache_limit:
                    _, removed = self._cache.popitem(last=False)
                    self._cache_bytes -= removed.nbytes
                self._cache[key] = values
                self._cache_bytes += values.nbytes
            return values

    def coordinates(self, timestep: int = 0) -> GridCoordinates:
        with NETCDF_LOCK:
            if not self.x_dimension or not self.y_dimension:
                raise DatasetError("This dataset has no horizontal grid.")
            if not 0 <= timestep < self.time_count:
                raise IndexError(timestep)
            geographic = bool(self.latitude_name and self.longitude_name)
            if geographic:
                x, y = self.raw[self.longitude_name], self.raw[self.latitude_name]
                if self.time_dimension in x.dims:
                    x = x.isel({self.time_dimension: timestep})
                if self.time_dimension in y.dims:
                    y = y.isel({self.time_dimension: timestep})
                y, x = xr.broadcast(y, x)
                x = x.transpose(self.y_dimension, self.x_dimension).to_numpy()
                y = y.transpose(self.y_dimension, self.x_dimension).to_numpy()
            else:
                x = self.raw.coords.get(self.x_dimension)
                y = self.raw.coords.get(self.y_dimension)
                x = (
                    x.to_numpy()
                    if x is not None and x.ndim == 1
                    else np.arange(self.dimensions[self.x_dimension])
                )
                y = (
                    y.to_numpy()
                    if y is not None and y.ndim == 1
                    else np.arange(self.dimensions[self.y_dimension])
                )
                x, y = np.meshgrid(x, y)
            return GridCoordinates(
                np.asarray(x, dtype=float),
                np.asarray(y, dtype=float),
                geographic,
                self.x_dimension,
                self.y_dimension,
            )

    def point_value(self, name: str, timestep: int, row: int, column: int, level: int = 0) -> float:
        with NETCDF_LOCK:
            self._check(name, timestep)
            self._validate_point(row, column)
            return float(
                self._field(name, timestep, level, (row, column)).to_numpy().reshape(-1)[0]
            )

    def vertical_profile(
        self, name: str, timestep: int, row: int, column: int
    ) -> np.ndarray:
        """Read one vertical vector; Snowpack vectors contain only active elements."""
        with NETCDF_LOCK:
            self._check(name, timestep)
            self._validate_point(row, column)
            dimensions = self.vertical_dimensions(name)
            varying = [(dim, size) for dim, size in dimensions.items() if size > 1
                       or dim == SNOWPACK_VERTICAL_DIM]
            if len(varying) != 1:
                raise DatasetError(f"{name} does not have one supported vertical dimension.")
            dimension, size = varying[0]
            if dimension == SNOWPACK_VERTICAL_DIM:
                size = active_layer_count(self, timestep, row, column, size)
                if size == 0:
                    return np.empty(0, dtype=float)
            field = self._field(name, timestep, 0, (row, column), (dimension, slice(0, size)))
            return np.asarray(field.transpose(dimension, ...).to_numpy(), dtype=float).reshape(-1)

    def _validate_point(self, row: int, column: int) -> None:
        if not (
            0 <= row < self.dimensions[self.y_dimension]
            and 0 <= column < self.dimensions[self.x_dimension]
        ):
            raise IndexError("Grid point outside dataset")

    def time_series(self, name: str, row: int, column: int, level: int = 0) -> np.ndarray:
        with NETCDF_LOCK:
            self._check(name, 0)
            self._validate_point(row, column)
            field = self._field(name, None, level, (row, column))
            values = np.asarray(field.to_numpy(), dtype=float).reshape(-1)
            if self.time_dimension not in field.dims:
                values = np.repeat(values[0], self.time_count)
            return values

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    def get_data(self, variable: str, time: int = 0, level: int = 0) -> np.ndarray:
        return self.read(variable, time, level)

    def get_dataset_for_time(self, time: int):
        if not 0 <= time < self.time_count:
            raise IndexError(time)
        return self

    def availability(self, variable: str) -> int:
        return self.time_count if variable in self.variables else 0

    def close(self) -> None:
        with NETCDF_LOCK:
            if not self._closed:
                self.raw.close()
                self._cache.clear()
                self._cache_bytes = 0
                self._closed = True

    def __enter__(self) -> "Dataset":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
