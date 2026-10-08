from collections.abc import Callable

import numpy as np
from matplotlib import colormaps
from matplotlib.colors import BoundaryNorm, LightSource, ListedColormap, Normalize

from avalanche_view.data.snowpack import is_categorical_variable
from avalanche_view.visualization.layers import Layer, RenderMode


def smooth_field(values: np.ndarray) -> np.ndarray:
    """NaN-aware 3×3 display filter; the scientific source stays unchanged."""
    padded = np.pad(values, 1, mode="edge")
    total = np.zeros_like(values)
    weight = np.zeros_like(values)
    for row in range(3):
        for column in range(3):
            cell = padded[row : row + values.shape[0], column : column + values.shape[1]]
            finite = np.isfinite(cell)
            total += np.where(finite, cell, 0)
            weight += finite
    return np.divide(total, weight, out=np.full_like(total, np.nan), where=weight > 0)


def field_range(values: np.ndarray, layer: Layer) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        raise ValueError(f"{layer.name}: the selected slice contains no finite data")
    low, high = (
        (float(finite.min()), float(finite.max()))
        if layer.automatic_range
        else (layer.minimum, layer.maximum)
    )
    if low == high:
        width = max(abs(low) * 0.01, 0.01)
        low, high = low - width, high + width
    return low, high


class RendererRegistry:
    """New point, polygon and raster renderers can be registered by plugins."""

    def __init__(self) -> None:
        self._renderers: dict[str, Callable] = {}

    def register(self, mode: str, renderer: Callable) -> None:
        self._renderers[mode] = renderer

    def render(
        self, axes, grid, values: np.ndarray, layer: Layer, zorder: int, transform=None, wind=None
    ):
        if layer.mode in self._renderers:
            return self._renderers[layer.mode](axes, grid, values, layer, zorder, transform)
        layer.validate()
        if values.shape != grid.x.shape or values.shape != grid.y.shape:
            raise ValueError(f"{layer.name}: data and coordinates have different shapes")
        if not np.isfinite(grid.x).all() or not np.isfinite(grid.y).all():
            raise ValueError("Map coordinates contain invalid values")
        if layer.smooth:
            values = smooth_field(values)
        low, high = field_range(values, layer)
        values = np.ma.masked_invalid(values)
        kwargs = dict(
            cmap=layer.colormap, norm=Normalize(low, high), alpha=layer.opacity, zorder=zorder
        )
        if transform is not None:
            kwargs["transform"] = transform
        if layer.mode == RenderMode.HEATMAP:
            return axes.pcolormesh(grid.x, grid.y, values, shading="auto", **kwargs)
        if layer.mode in (RenderMode.FILLED_CONTOURS, RenderMode.CONTOUR_LINES):
            method = axes.contourf if layer.mode == RenderMode.FILLED_CONTOURS else axes.contour
            return method(
                grid.x, grid.y, values, levels=np.linspace(low, high, layer.levels), **kwargs
            )
        if layer.mode == RenderMode.CATEGORIES:
            if is_categorical_variable(layer.variable):
                codes = np.unique(values.compressed())
                boundaries = np.concatenate(([codes[0] - .5], (codes[:-1] + codes[1:]) / 2, [codes[-1] + .5]))
                colors = colormaps["tab20"](np.remainder(codes, 20).astype(int))
                kwargs["cmap"] = ListedColormap(colors)
                kwargs["norm"] = BoundaryNorm(boundaries, len(codes))
                artist = axes.pcolormesh(grid.x, grid.y, values, shading="auto", **kwargs)
                artist.category_codes = codes
                return artist
            boundaries = np.arange(np.floor(low) - 0.5, np.ceil(high) + 1.5)
            if len(boundaries) > 257:
                raise ValueError("Categorical mode supports at most 256 classes")
            kwargs["norm"] = BoundaryNorm(boundaries, 256)
            return axes.pcolormesh(grid.x, grid.y, values, shading="auto", **kwargs)
        if layer.mode == RenderMode.HILLSHADE:
            if grid.geographic:
                dx, dy = grid.spacing_m()
            else:
                raise ValueError(
                    "Hillshade requires latitude/longitude coordinates with known distances"
                )
            shade = LightSource(azdeg=315, altdeg=45).hillshade(values.filled(np.nan), dx=dx, dy=dy)
            kwargs.update(cmap="Greys", norm=Normalize(0, 1))
            return axes.pcolormesh(grid.x, grid.y, shade, shading="auto", **kwargs)
        if layer.mode in (RenderMode.WIND_VECTORS, RenderMode.WIND_BARBS):
            if wind is None:
                raise ValueError("Wind vectors require U10 and V10")
            step = layer.vector_stride
            section = (slice(None, None, step), slice(None, None, step))
            u, v = wind
            kwargs.pop("norm")
            kwargs.pop("cmap")
            method = axes.quiver if layer.mode == RenderMode.WIND_VECTORS else axes.barbs
            artist = method(
                grid.x[section],
                grid.y[section],
                u[section],
                v[section],
                values[section],
                cmap=layer.colormap,
                norm=Normalize(low, high),
                **kwargs,
            )
            if layer.mode == RenderMode.WIND_VECTORS:
                axes.quiverkey(artist, 0.88, 1.01, 10, "10 m/s", coordinates="axes")
            return artist
        raise ValueError(f"Unsupported renderer: {layer.mode}")
