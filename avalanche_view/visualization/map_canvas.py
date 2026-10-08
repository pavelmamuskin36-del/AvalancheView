import logging

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from avalanche_view.visualization.geography import (
    add_cached_boundaries,
    ccrs,
    map_projection,
)
from avalanche_view.visualization.layers import RenderMode
from avalanche_view.visualization.renderer import RendererRegistry

logger = logging.getLogger(__name__)


class MapCanvas(QWidget):
    point_selected = pyqtSignal(float, float)
    cursor_moved = pyqtSignal(str)
    render_warning = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.figure = Figure(figsize=(10, 7), dpi=100)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)
        self.axes = self.figure.add_subplot(111)
        self.colorbars = []
        self.renderer = RendererRegistry()
        self._projection_key = None
        self._geographic = False
        self._has_data = False
        self._point = None
        self._dark = False
        self.canvas.mpl_connect("motion_notify_event", self._motion)
        self.canvas.mpl_connect("button_press_event", self._click)
        self.empty()

    def set_theme(self, dark: bool) -> None:
        self._dark = dark

    def _colors(self) -> tuple[str, str]:
        return ("#141e2c", "#dbe5ef") if self._dark else ("#f8fafc", "#23364d")

    def empty(self) -> None:
        for bar in self.colorbars:
            bar.remove()
        self.colorbars.clear()
        self.axes.clear()
        background, foreground = self._colors()
        self.figure.set_facecolor(background)
        self.axes.set_facecolor(background)
        self.axes.set_axis_off()
        self.axes.text(
            0.5,
            0.56,
            "AvalancheView",
            ha="center",
            va="center",
            fontsize=28,
            color=foreground,
            transform=self.axes.transAxes,
        )
        self.axes.text(
            0.5,
            0.44,
            "Open a WRF / NetCDF file or load the demo dataset\n"
            "Add variables as layers to explore mountain weather",
            ha="center",
            va="center",
            fontsize=12,
            linespacing=1.8,
            color=foreground,
            transform=self.axes.transAxes,
        )
        self._has_data = False
        self.canvas.draw_idle()

    def render(self, dataset, layers, timestep: int, reset_extent: bool = False) -> None:
        grid = dataset.coordinates(timestep)
        self._geographic = grid.geographic
        projection = map_projection(dataset) if grid.geographic else None
        key = str(projection)
        old_limits = (self.axes.get_xlim(), self.axes.get_ylim()) if self._has_data else None
        for bar in self.colorbars:
            bar.remove()
        self.colorbars.clear()
        if key != self._projection_key:
            self.figure.delaxes(self.axes)
            self.axes = self.figure.add_subplot(111, projection=projection)
            self._projection_key = key
            old_limits = None
        self.axes.clear()
        self.axes.set_axis_on()
        self.toolbar.update()
        background, foreground = self._colors()
        self.figure.set_facecolor(background)
        self.axes.set_facecolor(background)
        self.axes.tick_params(colors=foreground, labelsize=9)
        for spine in self.axes.spines.values():
            spine.set_color(foreground)
        transform = ccrs.PlateCarree() if projection is not None else None
        active = [layer for layer in layers if layer.visible]
        artists = []
        warnings = []
        for zorder, layer in enumerate(reversed(active), start=2):
            try:
                values = dataset.read(layer.variable, timestep, layer.level)
                wind = None
                if layer.mode in (RenderMode.WIND_VECTORS, RenderMode.WIND_BARBS):
                    wind = dataset.earth_relative_wind(timestep, layer.level, layer.variable)
                artist = self.renderer.render(
                    self.axes, grid, values, layer, zorder, transform, wind
                )
                if layer.show_colorbar and layer.mode != RenderMode.HILLSHADE:
                    artists.append((artist, layer))
            except (ValueError, KeyError, IndexError, RuntimeError) as exc:
                logger.warning("Layer %s could not be drawn", layer.name, exc_info=True)
                warnings.append(str(exc))
        bars = len(artists)
        bar_spacing = max(0.075, 90 / self.figure.bbox.width)
        width = max(0.30, 0.85 - bar_spacing * bars)
        self.axes.set_position([0.08, 0.12, width, 0.70])
        for index, (artist, layer) in enumerate(artists):
            cax = self.figure.add_axes(
                [0.08 + width + 0.025 + index * bar_spacing, 0.20, 0.018, 0.61]
            )
            colorbar = self.figure.colorbar(artist, cax=cax)
            if hasattr(artist, "category_codes"):
                colorbar.set_ticks(artist.category_codes, labels=[str(int(code)) for code in artist.category_codes])
            colorbar.set_label(
                f"{layer.name} [{layer.units}]" if layer.units else layer.name,
                color=foreground,
                fontsize=9,
            )
            colorbar.ax.tick_params(colors=foreground, labelsize=8)
            self.colorbars.append(colorbar)
        if projection is not None:
            add_cached_boundaries(self.axes, foreground)
            gridlines = self.axes.gridlines(
                draw_labels=True, linewidth=0.5, color=foreground, alpha=0.25, linestyle="--"
            )
            gridlines.top_labels = gridlines.right_labels = False
            gridlines.xlabel_style = gridlines.ylabel_style = {"color": foreground, "size": 9}
            if not old_limits or reset_extent:
                xmin, xmax = float(np.nanmin(grid.x)), float(np.nanmax(grid.x))
                ymin, ymax = float(np.nanmin(grid.y)), float(np.nanmax(grid.y))
                if xmax - xmin > 180:
                    self.axes.set_global()
                else:
                    dx, dy = max((xmax - xmin) * 0.02, 0.01), max((ymax - ymin) * 0.02, 0.01)
                    self.axes.set_extent(
                        [xmin - dx, xmax + dx, max(-89.9, ymin - dy), min(89.9, ymax + dy)],
                        crs=transform,
                    )
        else:
            self.axes.set_xlabel(
                "Longitude (°)" if grid.geographic else grid.x_dimension, color=foreground
            )
            self.axes.set_ylabel(
                "Latitude (°)" if grid.geographic else grid.y_dimension, color=foreground
            )
            self.axes.grid(alpha=0.2, color=foreground)
            if not active:
                self.axes.set_xlim(float(np.nanmin(grid.x)), float(np.nanmax(grid.x)))
                self.axes.set_ylim(float(np.nanmin(grid.y)), float(np.nanmax(grid.y)))
        if old_limits and not reset_extent:
            self.axes.set_xlim(old_limits[0])
            self.axes.set_ylim(old_limits[1])
        names = ", ".join(layer.name for layer in active)
        if len(names) > 90:
            names = names[:87] + "…"
        self.axes.set_title(
            f"{names or dataset.path.name}\n{dataset.timestamps[timestep]}",
            fontsize=11,
            color=foreground,
            pad=18,
        )
        if dataset.metadata.get("SYNTHETIC_DATA"):
            self.axes.text(
                0.01,
                0.01,
                "SYNTHETIC DEMO",
                color=foreground,
                fontsize=8,
                transform=self.axes.transAxes,
                zorder=200,
                bbox={"facecolor": background, "edgecolor": "none", "alpha": 0.85},
            )
        if self._point:
            self._draw_point(transform)
        self._has_data = True
        self.canvas.draw_idle()
        if warnings:
            self.render_warning.emit("; ".join(warnings))

    def mark_point(self, x: float, y: float) -> None:
        self._point = (x, y)

    def clear_point(self) -> None:
        self._point = None

    def _draw_point(self, transform) -> None:
        kwargs = {"transform": transform} if transform else {}
        self.axes.plot(
            *self._point,
            marker="+",
            markersize=14,
            markeredgewidth=2,
            color="#f97316",
            zorder=201,
            **kwargs,
        )

    def _coordinates(self, event):
        if event.inaxes != self.axes or event.xdata is None or event.ydata is None:
            return None
        if self._geographic and hasattr(self.axes, "projection"):
            return ccrs.PlateCarree().transform_point(
                event.xdata, event.ydata, self.axes.projection
            )
        return event.xdata, event.ydata

    def _motion(self, event) -> None:
        coordinates = self._coordinates(event)
        if coordinates:
            x, y = coordinates
            if self._geographic:
                self.cursor_moved.emit(f"Lon {x:.4f}°    Lat {y:.4f}°")
            else:
                self.cursor_moved.emit(f"X {x:.3f}    Y {y:.3f}")

    def _click(self, event) -> None:
        if event.button != 1 or self.toolbar.mode:
            return
        coordinates = self._coordinates(event)
        if coordinates and self._has_data:
            self.point_selected.emit(*coordinates)
