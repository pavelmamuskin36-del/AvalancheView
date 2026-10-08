"""Native cell fields and contours. Only descriptors cross QWebChannel."""

from dataclasses import asdict, replace

import contourpy
import numpy as np
from matplotlib import colormaps
from matplotlib.colors import to_hex
from scipy.ndimage import uniform_filter
from scipy.spatial import cKDTree

from avalanche_view.data.snowpack import is_categorical_variable
from avalanche_view.gis.capabilities import WIND_MODES, VariableCapabilities
from avalanche_view.gis.geometry import grid_geometry
from avalanche_view.gis.terrain import hillshade
from avalanche_view.services.file_service import PreparedFrame
from avalanche_view.visualization.layers import RenderMode


def binary(service, array, dtype):
    return service.asset_url(service.store.put(np.asarray(array, dtype=dtype).tobytes()))


def json_asset(service, value):
    return service.asset_url(service.store.json(value))


def colorize(values, layer):
    finite = values[np.isfinite(values)]
    if is_categorical_variable(layer.variable):
        codes = np.unique(finite)
        # Stable per-code qualitative colors, independent of range/time/selected layer.
        cmap = colormaps["tab20"]
        safe = np.where(np.isfinite(values), values, 0)
        rgba = cmap(np.remainder(safe, cmap.N).astype(int), bytes=True)
        rgba[..., 3] = np.where(np.isfinite(values), 255, 0)
        palette = cmap(np.remainder(codes, cmap.N).astype(int), bytes=True).tolist()
        return rgba, float(codes.min()) if codes.size else 0, float(codes.max()) if codes.size else 1, palette
    low, high = layer.minimum, layer.maximum
    if layer.automatic_range and finite.size:
        low, high = float(finite.min()), float(finite.max())
    if low == high:
        high = low + 1
    normalized = np.clip((values - low) / (high - low), 0, 1)
    if layer.mode in (RenderMode.FILLED_CONTOURS, RenderMode.CATEGORIES):
        normalized = np.floor(normalized * (layer.levels - 1)) / (layer.levels - 1)
    cmap = colormaps[layer.colormap]
    rgba = cmap(np.nan_to_num(normalized), bytes=True)
    rgba[..., 3] = np.where(np.isfinite(values), 255, 0)
    palette = cmap(np.linspace(0, 1, 32), bytes=True).tolist()
    return rgba, low, high, palette


def scalar_descriptor(service, grid, geometry, values, layer):
    if values.size > 250_000:
        raise ValueError(
            "Больше 250 000 исходных ячеек: выберите меньшую расчётную область. Значения не прорежены автоматически."
        )
    categorical = is_categorical_variable(layer.variable)
    if categorical:
        layer = replace(layer, mode=RenderMode.CATEGORIES, smooth=False, colormap="tab20")
    display = np.array(values, dtype=float, copy=True)
    if layer.smooth:
        mask = np.isfinite(display)
        weight = uniform_filter(mask.astype(float), size=3)
        display = uniform_filter(np.where(mask, display, 0), size=3) / np.maximum(weight, 1e-12)
        display[~mask] = np.nan
    if layer.mode == RenderMode.HILLSHADE:
        display = hillshade(grid, display)
    rgba, low, high, palette = colorize(display, layer)
    result = {
        **asdict(layer),
        "minimum": low,
        "maximum": high,
        "palette": palette,
        "shape": list(values.shape),
        "colors": binary(service, rgba, "u1"),
        "values": binary(service, values, "<f8"),
        "corners": binary(service, np.stack((geometry.longitude, geometry.latitude), -1), "<f8"),
        "cornerSource": geometry.corner_source,
    }
    if categorical:
        codes = np.unique(values[np.isfinite(values)])
        result["categories"] = [
            {"code": int(code), "label": f"Grain type code {int(code)}", "color": color}
            for code, color in zip(codes, palette, strict=True)
        ]
    if layer.mode in (RenderMode.CONTOUR_LINES, RenderMode.FILL_CONTOURS):
        levels = (
            np.arange(low, high + layer.contour_interval / 2, layer.contour_interval)
            if layer.contour_interval
            else np.linspace(low, high, layer.levels)
        )
        if len(levels) > 500:
            raise ValueError("Слишком много изолиний: увеличьте интервал (максимум 500).")
        generator = contourpy.contour_generator(
            x=grid.x, y=grid.y, z=np.ma.masked_invalid(display), corner_mask=False
        )
        features = []
        for value in levels:
            rgb = colormaps[layer.colormap]((value - low) / (high - low), bytes=True)
            color = (
                f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"
                if layer.contour_by_value
                else to_hex(layer.contour_color)
            )
            for line in generator.lines(value):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "value": float(value),
                            "label": format(value, layer.label_format),
                            "color": color,
                        },
                        "geometry": {"type": "LineString", "coordinates": line.tolist()},
                    }
                )
        result["contours"] = json_asset(
            service, {"type": "FeatureCollection", "features": features}
        )
    return result


def streamlines(grid, u, v, stride):
    """Integrate geographic paths using nearest original earth-relative vectors.

    Integration creates geometry, not extra measured wind values.
    """
    x, y = grid.metric_xy()
    tree = cKDTree(
        np.column_stack((grid.x.ravel() * np.cos(np.deg2rad(np.median(grid.y))), grid.y.ravel()))
    )
    step = min(grid.spacing_m()) * 0.3
    scale = np.cos(np.deg2rad(np.median(grid.y)))
    ny, nx = u.shape
    stride = max(stride, int(np.sqrt(u.size / 350)))
    paths = []
    for i in range(0, ny, stride):
        for j in range(0, nx, stride):
            p = np.array([grid.x[i, j], grid.y[i, j]])
            line = [p.tolist()]
            for _ in range(80):
                distance, index = tree.query([p[0] * scale, p[1]])
                if distance * 111_320 > step * 3:
                    break
                a, b = float(u.ravel()[index]), float(v.ravel()[index])
                speed = np.hypot(a, b)
                if not np.isfinite(speed) or speed < 0.05:
                    break
                p = p + np.array([a / np.cos(np.deg2rad(p[1])), b]) * step / speed / 111_320
                line.append(p.tolist())
            if len(line) > 2:
                paths.append(
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "LineString", "coordinates": line},
                    }
                )
    return {"type": "FeatureCollection", "features": paths}


class PreparedScene(PreparedFrame):
    def __init__(self, dataset, layers, timestep, service):
        # Capture original values for the existing point inspector.
        super().__init__(dataset, [], timestep)
        geometry = grid_geometry(dataset, timestep)
        service.terrain.set_model(dataset, timestep, self._grid, geometry)
        self.scene = {
            "timestamp": dataset.timestamps[timestep],
            "timestep": timestep,
            "bounds": geometry.bounds,
            "domain": json_asset(service, geometry.domain_geojson()),
            "terrain": service.terrain.descriptor(service.base_url),
            "layers": [],
            "warnings": [],
        }
        for layer in reversed(layers):
            if not layer.visible:
                continue
            try:
                capabilities = VariableCapabilities.detect(dataset, layer.variable)
                if reason := capabilities.reason(layer.mode):
                    raise ValueError(reason)
                values = dataset.read(layer.variable, timestep, layer.level)
                self._fields[(layer.variable, layer.level)] = values
                descriptor = scalar_descriptor(service, self._grid, geometry, values, layer)
                descriptor["capabilities"] = asdict(capabilities)
                if layer.mode in WIND_MODES:
                    u, v = dataset.earth_relative_wind(
                        timestep, layer.level, capabilities.vector_variable
                    )
                    wind = np.stack((self._grid.x, self._grid.y, u, v), -1)
                    descriptor["wind"] = binary(service, wind, "<f8")
                    speed = np.hypot(u, v)
                    _, low, high, palette = colorize(speed, layer)
                    descriptor.update(minimum=low, maximum=high, palette=palette, units="m/s")
                    if layer.mode == RenderMode.STREAMLINES:
                        descriptor["show_colorbar"] = False  # Uniform path color encodes direction only.
                        descriptor["streamlines"] = json_asset(
                            service, streamlines(self._grid, u, v, layer.vector_stride)
                        )
                    if layer.mode in (RenderMode.WIND_SPEED_ARROWS, RenderMode.WIND_SPEED_BARBS):
                        descriptor.update(
                            scalar_descriptor(service, self._grid, geometry, speed, layer)
                        )
                        descriptor["wind"] = binary(service, wind, "<f8")
                        descriptor["units"] = "m/s"
                self.scene["layers"].append(descriptor)
            except (ValueError, KeyError, IndexError, RuntimeError, OSError) as exc:
                self._fields[(layer.variable, layer.level)] = exc
                self.scene["warnings"].append(f"{layer.name}: {exc}")
