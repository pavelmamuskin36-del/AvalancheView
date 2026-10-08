from dataclasses import dataclass
from typing import Any

import numpy as np
from pyproj import CRS, Geod, Transformer


@dataclass(frozen=True)
class GridCoordinates:
    x: np.ndarray
    y: np.ndarray
    geographic: bool
    x_dimension: str
    y_dimension: str

    def nearest(self, x: float, y: float) -> tuple[int, int]:
        if self.geographic:
            # Great-circle angular distance, including the dateline and poles.
            latitude = np.deg2rad(self.y)
            target_latitude = np.deg2rad(y)
            delta_lon = np.deg2rad((self.x - x + 180) % 360 - 180)
            distance = (
                np.sin((latitude - target_latitude) / 2) ** 2
                + np.cos(latitude) * np.cos(target_latitude) * np.sin(delta_lon / 2) ** 2
            )
        else:
            distance = (self.x - x) ** 2 + (self.y - y) ** 2
        valid = np.isfinite(self.x) & np.isfinite(self.y)
        if not valid.any():
            raise ValueError("The coordinate grid contains no finite cells.")
        flat = int(np.argmin(np.where(valid, distance, np.inf)))
        row, column = np.unravel_index(flat, distance.shape)
        return int(row), int(column)

    def metric_xy(self) -> tuple[np.ndarray, np.ndarray]:
        if not self.geographic:
            return self.x, self.y
        lon = float(np.nanmedian(self.x))
        lat = float(np.nanmedian(self.y))
        crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84")
        transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x, y = transformer.transform(self.x, self.y)
        return np.asarray(x), np.asarray(y)

    def spacing_m(self) -> tuple[float, float]:
        if not self.geographic:
            dx = np.nanmedian(np.abs(np.diff(self.x, axis=1))) if self.x.shape[1] > 1 else 1
            dy = np.nanmedian(np.abs(np.diff(self.y, axis=0))) if self.y.shape[0] > 1 else 1
        else:
            geod = Geod(ellps="WGS84")
            dx = geod.inv(self.x[:, :-1], self.y[:, :-1], self.x[:, 1:], self.y[:, 1:])[2]
            dy = geod.inv(self.x[:-1], self.y[:-1], self.x[1:], self.y[1:])[2]
            dx, dy = np.nanmedian(dx), np.nanmedian(dy)
        return max(float(dx), 1e-6), max(float(dy), 1e-6)


def wrf_crs(attributes: dict[str, Any]) -> CRS | None:
    """WRF uses a spherical Earth; unknown projections fall back to lon/lat."""
    try:
        projection = int(attributes.get("MAP_PROJ", 0))
        lon = float(attributes.get("STAND_LON", attributes.get("CEN_LON", 0)))
        lat = float(attributes.get("MOAD_CEN_LAT", attributes.get("CEN_LAT", 0)))
        lat1 = float(attributes.get("TRUELAT1", lat))
        lat2 = float(attributes.get("TRUELAT2", lat1))
        sphere = "+a=6370000 +b=6370000"
        if projection == 1:
            return CRS.from_proj4(
                f"+proj=lcc +lat_1={lat1} +lat_2={lat2} +lat_0={lat} +lon_0={lon} {sphere}"
            )
        if projection == 2:
            pole = 90 if lat1 >= 0 else -90
            return CRS.from_proj4(f"+proj=stere +lat_0={pole} +lat_ts={lat1} +lon_0={lon} {sphere}")
        if projection == 3:
            return CRS.from_proj4(f"+proj=merc +lat_ts={lat1} +lon_0={lon} {sphere}")
        if projection == 6:
            return CRS.from_epsg(4326)
    except (ValueError, TypeError, RuntimeError):
        return None
    return None
