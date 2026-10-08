from dataclasses import replace

import numpy as np
import pytest
import xarray as xr
from matplotlib.backend_bases import MouseEvent
from PIL import Image
from PyQt6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from avalanche_view.services.export_service import ExportService
from avalanche_view.ui.main_window import MainWindow
from avalanche_view.visualization.layers import RenderMode


@pytest.fixture
def window(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = MainWindow(settings, renderer="legacy")
    qtbot.addWidget(widget)
    widget.show()
    yield widget
    widget.timeline.pause()
    qtbot.waitUntil(lambda: not widget._jobs, timeout=10000)
    widget.close()


def load(window, qtbot, path):
    with qtbot.waitSignal(window.dataset_loaded, timeout=15000):
        window.open_path(path)
    qtbot.waitUntil(lambda: not window._jobs, timeout=10000)
    window._redraw_timer.stop()
    window._render()
    window.map.canvas.draw()


def test_file_menu_and_drag_drop(window, qtbot, demo_path, monkeypatch):
    from avalanche_view.ui import main_window

    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", lambda *args: (str(demo_path), "")
    )
    with qtbot.waitSignal(window.dataset_loaded, timeout=15000):
        window.open_action.trigger()
    qtbot.waitUntil(lambda: not window._jobs, timeout=10000)
    assert window.browser.tree.topLevelItemCount() == 6
    window.browser.search.setText("Snow")
    group = window.browser.tree.topLevelItem(4)
    names = [
        group.child(i).text(0) for i in range(group.childCount()) if not group.child(i).isHidden()
    ]
    assert names == ["SNOWH"]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(demo_path))])
    drag = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(drag)
    assert drag.isAccepted()
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with qtbot.waitSignal(window.dataset_loaded, timeout=15000):
        window.dropEvent(drop)
    assert drop.isAccepted()


def test_layers_properties_time_point_series_and_export(window, qtbot, demo_path, tmp_path):
    load(window, qtbot, demo_path)
    window.add_layer("T2")
    window.add_layer("SNOWH")
    assert len(window.layers.layers) == 2
    snow, temperature = window.layers.layers
    window.properties.opacity.setValue(45)
    window.properties.colormap.setCurrentText("plasma")
    window.properties.automatic.setChecked(False)
    window.properties.minimum.setValue(0)
    window.properties.maximum.setValue(2.5)
    qtbot.waitUntil(lambda: window.layers.get(snow.id).colormap == "plasma", timeout=3000)
    snow = window.layers.get(snow.id)
    assert snow.opacity == 0.45 and snow.maximum == 2.5
    item = window.layer_manager.tree.topLevelItem(0)
    item.setCheckState(0, Qt.CheckState.Unchecked)
    assert not snow.visible
    item.setCheckState(0, Qt.CheckState.Checked)
    assert snow.visible
    window.move_layer(snow.id, 1)
    assert window.layers.layers == [temperature, snow]
    window.timeline.slider.setValue(2)
    assert window.timestep == 2
    window.timeline.speed.setCurrentText("4x")
    assert window.timeline.timer.interval() == 250
    with qtbot.waitSignal(window.timeline.timestep_changed, timeout=3000):
        window.timeline.play.setChecked(True)
    window.timeline.pause()
    assert not window.timeline.timer.isActive()
    window._redraw_timer.stop()
    window._render()
    window.map.canvas.draw()
    grid = window.dataset.coordinates(window.timestep)
    row, column = 4, 7
    lon, lat = grid.x[row, column], grid.y[row, column]
    axes = window.map.axes
    if hasattr(axes, "projection"):
        from avalanche_view.visualization.geography import ccrs

        x, y = axes.projection.transform_point(lon, lat, ccrs.PlateCarree())
    else:
        x, y = lon, lat
    px, py = axes.transData.transform((x, y))
    event = MouseEvent("button_press_event", window.map.canvas, px, py, button=1)
    window.map.canvas.callbacks.process("button_press_event", event)
    assert window.selected_point == (row, column)
    assert window.inspector.table.rowCount() == 2
    window.show_time_series("SNOWH")
    qtbot.waitUntil(lambda: len(window._dialogs) == 1, timeout=10000)
    dialog = window._dialogs[0]
    plotted = dialog.canvas.figure.axes[0].lines[0].get_ydata()
    np.testing.assert_array_equal(plotted, window.dataset.time_series("SNOWH", row, column))
    window._redraw_timer.stop()
    window._render()
    window.map.canvas.draw()
    path = ExportService.export_png(window.map.figure, tmp_path / "map.png", dpi=150)
    with Image.open(path) as image:
        assert image.width > 600 and image.height > 300
    window.remove_layer(snow.id)
    assert len(window.layers.layers) == 1


def test_vertical_profile_uses_physical_height(window, qtbot, tmp_path):
    path = tmp_path / "vertical-profile.nc"
    levels, ny, nx = 4, 3, 5
    longitude, latitude = np.meshgrid(np.linspace(42, 43, nx), np.linspace(43, 44, ny))
    temperature = np.arange(levels * ny * nx, dtype=float).reshape(1, levels, ny, nx)
    heights = np.broadcast_to(
        np.array([1000, 2200, 4100, 7000], dtype=float)[None, :, None, None],
        temperature.shape,
    )
    xr.Dataset(
        {
            "TT": (
                ("Time", "num_metgrid_levels", "south_north", "west_east"),
                temperature,
                {"units": "K"},
            ),
            "GHT": (
                ("Time", "num_metgrid_levels", "south_north", "west_east"),
                heights,
                {"units": "m"},
            ),
            "XLONG": (("south_north", "west_east"), longitude),
            "XLAT": (("south_north", "west_east"), latitude),
        },
        attrs={"MAP_PROJ": 6},
    ).to_netcdf(path, engine="h5netcdf")
    load(window, qtbot, path)
    window.inspect_point(float(longitude[1, 2]), float(latitude[1, 2]))
    assert window.inspector.profile_variable.findText("TT") >= 0
    window.show_vertical_profile("TT")
    qtbot.waitUntil(lambda: len(window._dialogs) == 1, timeout=10000)
    axes = window._dialogs[0].canvas.figure.axes[0]
    np.testing.assert_array_equal(axes.lines[0].get_xdata(), temperature[0, :, 1, 2])
    np.testing.assert_array_equal(axes.lines[0].get_ydata(), [1000, 2200, 4100, 7000])
    assert axes.get_ylabel() == "Высота, m"


@pytest.mark.parametrize("mode", [RenderMode.HEATMAP, RenderMode.FILLED_CONTOURS,
                                RenderMode.CONTOUR_LINES, RenderMode.WIND_VECTORS,
                                RenderMode.WIND_BARBS, RenderMode.HILLSHADE, RenderMode.CATEGORIES])
def test_render_modes_and_no_colorbar_leaks(window, qtbot, demo_path, mode):
    load(window, qtbot, demo_path)
    variable = (
        "Wind Speed 10m"
        if mode in (RenderMode.WIND_VECTORS, RenderMode.WIND_BARBS)
        else ("HGT" if mode == RenderMode.HILLSHADE else "SNOWH")
    )
    window.add_layer(variable)
    layer = window.layers.layers[0]
    window.update_layer(replace(layer, mode=mode))
    for timestep in range(3):
        window.timestep = timestep
        window._redraw_timer.stop()
        window._render()
        window.map.canvas.draw()
        assert len(window.map.figure.axes) == (1 if mode == RenderMode.HILLSHADE else 2)
        assert len(window.map.axes.collections) > 0


def test_without_optional_dependencies(window, qtbot, demo_path, monkeypatch):
    from avalanche_view.ui import main_window
    from avalanche_view.visualization import geography

    monkeypatch.setattr(geography, "CARTOPY_AVAILABLE", False)
    monkeypatch.setattr(main_window, "TERRAIN3D_AVAILABLE", False)
    load(window, qtbot, demo_path)
    window.add_layer("SNOWH")
    window._redraw_timer.stop()
    window._render()
    window.map.canvas.draw()
    assert not hasattr(window.map.axes, "projection")
    window.show_terrain()


def test_invalid_file_preserves_current_dataset(window, qtbot, demo_path, tmp_path, monkeypatch):
    load(window, qtbot, demo_path)
    errors = []
    monkeypatch.setattr(window, "_show_error", lambda *args: errors.append(args))
    broken = tmp_path / "bad.nc"
    broken.write_text("bad")
    old_dataset = window.dataset
    window.open_path(broken)
    qtbot.waitUntil(lambda: not window._jobs, timeout=15000)
    assert errors and window.dataset is old_dataset
    assert window.dataset.read("SNOWH").shape == (12, 16)
    assert window.open_action.isEnabled()
