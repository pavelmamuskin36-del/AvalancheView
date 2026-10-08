from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import Polygon

from avalanche_view.data.dataset import NETCDF_LOCK


def vertices_from_centers(values):
    if min(values.shape) < 2:
        raise ValueError("Для геометрии ячеек нужна сетка не меньше 2×2")
    padded = np.pad(values, 1, mode="edge")
    padded[0, 1:-1] = 2 * values[0] - values[1]
    padded[-1, 1:-1] = 2 * values[-1] - values[-2]
    padded[:, 0] = 2 * padded[:, 1] - padded[:, 2]
    padded[:, -1] = 2 * padded[:, -2] - padded[:, -3]
    return (padded[:-1, :-1] + padded[1:, :-1] + padded[:-1, 1:] + padded[1:, 1:]) / 4


@dataclass(frozen=True)
class GridGeometry:
    longitude: np.ndarray
    latitude: np.ndarray
    corner_source: str

    @property
    def ring(self):
        x, y = self.longitude, self.latitude
        return np.concatenate(
            [
                np.column_stack((x[0], y[0])),
                np.column_stack((x[1:, -1], y[1:, -1])),
                np.column_stack((x[-1, -2::-1], y[-1, -2::-1])),
                np.column_stack((x[-2::-1, 0], y[-2::-1, 0])),
            ]
        )

    @property
    def bounds(self):
        return [
            float(self.longitude.min()),
            float(self.latitude.min()),
            float(self.longitude.max()),
            float(self.latitude.max()),
        ]

    def domain_geojson(self):
        return {
            "type": "Feature",
            "properties": {"name": "Граница расчётной области"},
            "geometry": {"type": "Polygon", "coordinates": [self.ring.tolist()]},
        }

    def polygon(self):
        return Polygon(self.ring)


def grid_geometry(dataset, timestep=0):
    grid = dataset.coordinates(timestep)
    if not grid.geographic:
        raise ValueError("GIS-карта требует широты и долготы. Геопривязка не определена.")
    if not np.isfinite(grid.x).all() or not np.isfinite(grid.y).all():
        raise ValueError("В координатах есть NaN; исправьте геопривязку набора данных.")
    if np.ptp(grid.x) > 180 or np.max(np.abs(grid.y)) > 85.05:
        raise ValueError("Домен пересекает антимеридиан или выходит за границы Web Mercator.")
    with NETCDF_LOCK:
        source = dataset
        local_time = timestep
        if hasattr(dataset, "get_dataset_for_time"):
            source = dataset.get_dataset_for_time(timestep)
            local_time = source.timestamps.index(dataset.timestamps[timestep])
        if hasattr(source, "raw") and {"XLAT_C", "XLONG_C"} <= source.raw.variables.keys():
            arrays = []
            for name in ("XLONG_C", "XLAT_C"):
                array = source.raw[name]
                if source.time_dimension in array.dims:
                    array = array.isel({source.time_dimension: local_time})
                arrays.append(np.asarray(array.to_numpy(), dtype=float).squeeze())
            expected = (grid.x.shape[0] + 1, grid.x.shape[1] + 1)
            if all(array.shape == expected for array in arrays):
                return GridGeometry(*arrays, "XLONG_C / XLAT_C")
    crs = dataset.projection
    if crs is None or crs.is_geographic:
        crs = CRS.from_proj4(
            f"+proj=aeqd +lat_0={np.median(grid.y)} +lon_0={np.median(grid.x)} +datum=WGS84"
        )
    forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inverse = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    x, y = forward.transform(grid.x, grid.y)
    lon, lat = inverse.transform(vertices_from_centers(x), vertices_from_centers(y))
    return GridGeometry(np.asarray(lon), np.asarray(lat), "projected center midpoints")
