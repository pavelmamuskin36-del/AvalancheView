import hashlib
import io
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import contains_xy

from avalanche_view.data.coordinates import GridCoordinates
from avalanche_view.gis.geometry import GridGeometry

TO_MERCATOR = Transformer.from_crs(4326, 3857, always_xy=True)
FROM_MERCATOR = Transformer.from_crs(3857, 4326, always_xy=True)
EARTH_HALF = 20037508.342789244


def terrain_derivatives(grid, elevation):
    """Metric derivatives on a curvilinear grid, including row orientation."""
    x, y = grid.metric_xy()
    zi, zj = np.gradient(elevation)
    xi, xj = np.gradient(x)
    yi, yj = np.gradient(y)
    determinant = xi * yj - xj * yi
    valid = np.abs(determinant) > 1e-10
    gx = np.divide(zi * yj - zj * yi, determinant, out=np.full_like(x, np.nan), where=valid)
    gy = np.divide(xi * zj - xj * zi, determinant, out=np.full_like(y, np.nan), where=valid)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.mod(np.degrees(np.arctan2(-gx, -gy)), 360)
    aspect = np.where(slope > 1e-8, aspect, np.nan)
    return slope, aspect, gx, gy


def hillshade(grid, elevation, azimuth=315, altitude=45):
    _, _, gx, gy = terrain_derivatives(grid, elevation)
    az, alt = np.deg2rad([azimuth, altitude])
    illumination = -gx * np.sin(az) * np.cos(alt) - gy * np.cos(az) * np.cos(alt) + np.sin(alt)
    return np.clip(illumination / np.sqrt(gx * gx + gy * gy + 1), 0, 1)


def encode_dem(height):
    encoded = (
        np.rint((np.nan_to_num(height, nan=0) + 10000) * 10).clip(0, 16777215).astype(np.uint32)
    )
    rgb = np.stack(((encoded >> 16) & 255, (encoded >> 8) & 255, encoded & 255), axis=-1).astype(
        np.uint8
    )
    output = io.BytesIO()
    Image.fromarray(rgb).save(output, format="PNG")
    return output.getvalue()


def tile_coordinates(z, x, y, size=256):
    if not 0 <= z <= 22 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise ValueError("Tile outside XYZ grid")
    span = 2 * EARTH_HALF / 2**z
    east = -EARTH_HALF + (x + (np.arange(size) + 0.5) / size) * span
    north = EARTH_HALF - (y + (np.arange(size) + 0.5) / size) * span
    return np.meshgrid(east, north)


@dataclass
class TerrainSource:
    name: str
    kind: str
    grid: GridCoordinates
    values: np.ndarray
    geometry: GridGeometry
    path: Path | None = None

    def __post_init__(self):
        valid = np.isfinite(self.values) & np.isfinite(self.grid.x) & np.isfinite(self.grid.y)
        if not valid.any():
            raise ValueError("DEM не содержит доступных высот")
        x, y = TO_MERCATOR.transform(self.grid.x, self.grid.y)
        positions = np.isfinite(x) & np.isfinite(y)
        self.tree = cKDTree(np.column_stack((np.asarray(x)[positions], np.asarray(y)[positions])))
        self.heights = self.values[positions]
        self.valid_mask = valid
        self.version = hashlib.sha256(self.values.tobytes() + self.grid.x.tobytes()).hexdigest()[
            :16
        ]

    def height(self, lon, lat):
        if not contains_xy(self.geometry.polygon(), lon, lat):
            return None
        if self.path:
            import rasterio

            with rasterio.open(self.path) as raster:
                x, y = Transformer.from_crs(4326, raster.crs, always_xy=True).transform(lon, lat)
                value = next(raster.sample([(x, y)], masked=True))[0]
                return None if np.ma.is_masked(value) or not np.isfinite(value) else float(value)
        row, column = self.grid.nearest(lon, lat)
        value = self.values[row, column]
        return float(value) if np.isfinite(value) else None

    def tile(self, z, x, y):
        east, north = tile_coordinates(z, x, y)
        if self.path:
            import rasterio
            from rasterio.enums import Resampling
            from rasterio.transform import from_bounds
            from rasterio.warp import reproject

            span = 2 * EARTH_HALF / 2**z
            left = -EARTH_HALF + x * span
            top = EARTH_HALF - y * span
            result = np.zeros((256, 256), dtype=np.float32)
            with rasterio.open(self.path) as raster:
                reproject(
                    rasterio.band(raster, 1),
                    result,
                    src_transform=raster.transform,
                    src_crs=raster.crs,
                    src_nodata=raster.nodata,
                    dst_crs="EPSG:3857",
                    dst_transform=from_bounds(left, top - span, left + span, top, 256, 256),
                    dst_nodata=0,
                    resampling=Resampling.bilinear,
                )
        else:
            lon, lat = FROM_MERCATOR.transform(east, north)
            indices = self.tree.query(np.column_stack((east.ravel(), north.ravel())))[1]
            result = self.heights[indices].reshape(east.shape)
            mask = contains_xy(self.geometry.polygon(), lon, lat)
            # Outside model coverage the native terrain is at zero, never fabricated mountains.
            result = np.where(mask, result, 0)
        return encode_dem(result)


class TerrainService:
    def __init__(self):
        self.model = None
        self.local = None
        self.selected = "model"
        self.provider = None
        self.lock = threading.RLock()
        self._sources = {}
        self._tiles = OrderedDict()

    def set_model(self, dataset, timestep, grid, geometry):
        name = next((n for n in ("HGT", "HGT_M") if n in dataset.variables), None)
        if not name:
            self.model = None
            return
        values = dataset.read(name, timestep)
        with self.lock:
            if (
                self.model is None
                or not np.array_equal(self.model.values, values, equal_nan=True)
                or not np.array_equal(self.model.grid.x, grid.x)
                or not np.array_equal(self.model.grid.y, grid.y)
            ):
                self.model = TerrainSource(name, "model", grid, values, geometry)
                self._remember(self.model)

    def _remember(self, source):
        self._sources[source.version] = source
        while len(self._sources) > 3:
            self._sources.pop(next(iter(self._sources)))

    def load_geotiff(self, path):
        import rasterio
        from rasterio.enums import Resampling

        with rasterio.open(path) as raster:
            if raster.crs is None:
                raise ValueError("У GeoTIFF не указан CRS")
            scale = max(1, math.sqrt(raster.width * raster.height / 1_000_000))
            rows, columns = max(2, int(raster.height / scale)), max(2, int(raster.width / scale))
            values = raster.read(
                1, out_shape=(rows, columns), masked=True, resampling=Resampling.nearest
            )
            a = raster.transform
            sx, sy = raster.width / columns, raster.height / rows
            transform = type(a)(a.a * sx, a.b * sy, a.c, a.d * sx, a.e * sy, a.f)
            yy, xx = np.mgrid[:rows, :columns]
            x, y = rasterio.transform.xy(transform, yy, xx)
            lon, lat = Transformer.from_crs(raster.crs, 4326, always_xy=True).transform(x, y)
            grid = GridCoordinates(
                np.asarray(lon).reshape(rows, columns),
                np.asarray(lat).reshape(rows, columns),
                True,
                "x",
                "y",
            )
            cy, cx = np.mgrid[: rows + 1, : columns + 1]
            vx, vy = rasterio.transform.xy(transform, cy, cx, offset="ul")
            vx, vy = Transformer.from_crs(raster.crs, 4326, always_xy=True).transform(vx, vy)
            geometry = GridGeometry(
                np.asarray(vx).reshape(rows + 1, columns + 1),
                np.asarray(vy).reshape(rows + 1, columns + 1),
                "GeoTIFF affine transform",
            )
            source = TerrainSource(
                Path(path).name,
                "local",
                grid,
                values.astype(float).filled(np.nan),
                geometry,
                Path(path),
            )
        with self.lock:
            self.local = source
            self.selected = "local"
            self._remember(source)
        return source

    @property
    def active(self):
        return (
            self.local
            if self.selected == "local"
            else self.model
            if self.selected == "model"
            else None
        )

    def descriptor(self, base_url):
        source = self.active
        if self.selected == "provider":
            return self.provider
        if source is None:
            return None
        return {
            "id": source.version,
            "name": source.name,
            "kind": source.kind,
            "url": base_url + f"dem/{source.version}/{{z}}/{{x}}/{{y}}.png",
            "encoding": "mapbox",
            "maxZoom": 14,
            "bounds": source.geometry.bounds,
            "attribution": "Model terrain" if source.kind == "model" else source.name,
        }

    def tile(self, version, z, x, y):
        key = (version, z, x, y)
        with self.lock:
            if key in self._tiles:
                self._tiles.move_to_end(key)
                return self._tiles[key]
            source = self._sources.get(version)
        if source is None:
            raise KeyError("DEM version expired")
        value = source.tile(z, x, y)
        with self.lock:
            self._tiles[key] = value
            while len(self._tiles) > 128:
                self._tiles.popitem(last=False)
        return value

    def heights(self, lon, lat):
        with self.lock:
            return {
                "model": self.model.height(lon, lat) if self.model else None,
                "dem": self.local.height(lon, lat) if self.local else None,
            }

    def mountain_focus(self):
        """Aim at the highest known land cell, without changing scientific values."""
        source = self.active or self.model
        if source is None:
            return None
        row, column = np.unravel_index(np.nanargmax(source.values), source.values.shape)
        return [float(source.grid.x[row, column]), float(source.grid.y[row, column])]
