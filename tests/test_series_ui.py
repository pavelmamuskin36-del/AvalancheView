import numpy as np
import pytest
from PyQt6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PyQt6.QtGui import QDropEvent
from PyQt6.QtWidgets import QDialog, QMessageBox

from avalanche_view.ui.main_window import MainWindow
from avalanche_view.visualization.layers import RenderMode
from tests.test_dataset_series import write_file


@pytest.fixture
def series_window(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat), renderer="legacy")
    qtbot.addWidget(window)
    window.show()
    yield window
    window.timeline.pause()
    qtbot.waitUntil(lambda: not window._jobs, timeout=20000)
    window.close()


def wait_render(window, qtbot, timestep):
    qtbot.waitUntil(
        lambda: (
            window._frame_timestep == timestep
            and window._render_job is None
            and not window._redraw_timer.isActive()
        ),
        timeout=20000,
    )
    window.map.canvas.draw()


def test_closed_panels_toolbar_and_default_layout(series_window, qtbot):
    window = series_window
    for dock in (window.layers_dock, window.plots_dock):
        dock.show()
        qtbot.waitUntil(dock.isVisible)
        action = dock.toggleViewAction()
        assert action.isChecked() and action in window.toolbar.actions()
        dock.close()
        assert not dock.isVisible() and not action.isChecked()
        action.trigger()
        assert dock.isVisible() and action.isChecked()
    window.toolbar.hide()
    assert not window.toolbar.toggleViewAction().isChecked()
    window.toolbar.toggleViewAction().trigger()
    assert window.toolbar.isVisible()
    for dock in window.docks:
        dock.close()
    window.restore_layout_action.trigger()
    assert all(dock.isVisible() and dock.toggleViewAction().isChecked() for dock in window.docks)


def test_series_dialog_animation_map_extent_point_graph(
    series_window, qtbot, tmp_path, monkeypatch
):
    paths = [write_file(tmp_path / f"{hour}.nc", [hour]) for hour in (12, 13, 14)]
    monkeypatch.setattr(
        "avalanche_view.ui.main_window.QFileDialog.getOpenFileNames",
        lambda *args: ([str(path) for path in reversed(paths)], ""),
    )
    window = series_window
    with qtbot.waitSignal(window.dataset_loaded, timeout=20000):
        window.open_series_action.trigger()
    wait_render(window, qtbot, 0)
    assert window.dataset.time_count == 3
    assert window.timeline.timestamps == window.dataset.timestamps
    window.add_layer("SNOWH")
    qtbot.waitUntil(lambda: len(window.layers.layers) == 1, timeout=20000)
    wait_render(window, qtbot, 0)
    layer = window.layers.layers[0]
    window.map.axes.set_xlim(10.2, 10.8)
    limits = window.map.axes.get_xlim()
    window.timeline.slider.setValue(1)
    wait_render(window, qtbot, 1)
    assert window.layers.layers[0].id == layer.id
    np.testing.assert_allclose(window.map.axes.get_xlim(), limits)
    np.testing.assert_array_equal(window._frame.read("SNOWH"), 13)
    window.inspect_point(10.5, 40.5)
    wait_render(window, qtbot, 1)
    window.show_time_series("SNOWH")
    qtbot.waitUntil(lambda: window.plots.tabs.count() == 1, timeout=20000)
    plotted = window.plots.tabs.widget(0).canvas.figure.axes[0].lines[0]
    np.testing.assert_array_equal(plotted.get_ydata(), [12, 13, 14])
    window.plots_dock.close()
    window.plots_dock.toggleViewAction().trigger()
    assert window.plots_dock.isVisible() and window.plots.tabs.count() == 1
    window.add_layer("Wind Speed 10m")
    qtbot.waitUntil(lambda: len(window.layers.layers) == 2, timeout=20000)
    wind = window.layers.layers[0]
    wind.mode = RenderMode.WIND_VECTORS
    window.schedule_render()
    wait_render(window, qtbot, 1)
    assert window._frame.earth_relative_wind(1)[0].shape == (4, 5)
    window.timeline.speed.setCurrentText("4x")
    with qtbot.waitSignal(window.timeline.timestep_changed, timeout=3000):
        window.play_action.trigger()
    window.timeline.pause()
    assert not window.play_action.isChecked()


def test_multiple_drop_and_folder_group_selection(series_window, qtbot, tmp_path, monkeypatch):
    paths = [write_file(tmp_path / f"{hour}.nc", [hour]) for hour in (12, 13)]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in reversed(paths)])
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    with qtbot.waitSignal(series_window.dataset_loaded, timeout=20000):
        series_window.dropEvent(drop)
    assert drop.isAccepted() and series_window.dataset.time_count == 2
    wait_render(series_window, qtbot, 0)
    qtbot.waitUntil(lambda: not series_window._jobs, timeout=20000)
    write_file(tmp_path / "domain2.nc", [12], domain=2)
    monkeypatch.setattr(
        "avalanche_view.ui.main_window.SeriesSelectionDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    with qtbot.waitSignal(series_window.dataset_loaded, timeout=20000):
        series_window.open_folder(tmp_path)
    assert series_window.dataset.domain == "d01"


def test_layout_saved_restored_and_corrupt_fallback(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "saved.ini"), QSettings.Format.IniFormat)
    first = MainWindow(settings, renderer="legacy")
    qtbot.addWidget(first)
    first.show()
    first.layers_dock.close()
    first.toolbar.hide()
    first.close()
    second = MainWindow(settings, renderer="legacy")
    qtbot.addWidget(second)
    second.show()
    assert not second.layers_dock.isVisible() and not second.toolbar.isVisible()
    second.restore_default_layout()
    assert second.layers_dock.isVisible() and second.toolbar.isVisible()
    second.close()
    settings.setValue("dockState", "invalid-layout")
    third = MainWindow(settings, renderer="legacy")
    qtbot.addWidget(third)
    third.show()
    assert all(dock.isVisible() for dock in third.docks)
    third.close()


@pytest.mark.parametrize("choice", ["Открыть серию", "Только этот файл", "Отмена"])
def test_single_file_series_discovery_requires_choice(
    series_window, qtbot, tmp_path, monkeypatch, choice
):
    paths = [
        write_file(tmp_path / f"met_em.d01.2025-02-18_{hour}%3A00%3A00.nc", [hour])
        for hour in (12, 13)
    ]
    prompts = []

    def choose(box):
        prompts.append(box.text())
        next(button for button in box.buttons() if button.text() == choice).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", choose)
    series_window.open_path(paths[0], discover=True)
    qtbot.waitUntil(lambda: bool(prompts) and not series_window._jobs, timeout=20000)
    assert "ещё 1" in prompts[0]
    if choice == "Отмена":
        assert series_window.dataset is None
    else:
        assert series_window.dataset.time_count == (2 if choice == "Открыть серию" else 1)
    assert series_window.open_action.isEnabled()


def test_partial_series_reports_missing_data_without_crash(
    series_window, qtbot, tmp_path, monkeypatch
):
    paths = [
        write_file(tmp_path / "a.nc", [12]),
        write_file(tmp_path / "b.nc", [13], missing=("SNOWH",)),
    ]
    messages = []
    monkeypatch.setattr(series_window, "_show_message", lambda *args: messages.append(args))
    with qtbot.waitSignal(series_window.dataset_loaded, timeout=20000):
        series_window.open_paths(paths)
    wait_render(series_window, qtbot, 0)
    series_window.add_layer("SNOWH")
    qtbot.waitUntil(lambda: len(series_window.layers.layers) == 1, timeout=20000)
    wait_render(series_window, qtbot, 0)
    warnings = []
    series_window.map.render_warning.connect(warnings.append)
    series_window.timeline.slider.setValue(1)
    wait_render(series_window, qtbot, 1)
    assert messages and warnings and "недоступна" in warnings[-1]
    assert len(series_window.layers.layers) == 1


def test_series_export_waits_for_requested_frame(series_window, qtbot, tmp_path, monkeypatch):
    paths = [write_file(tmp_path / "a.nc", [12]), write_file(tmp_path / "b.nc", [13])]
    with qtbot.waitSignal(series_window.dataset_loaded, timeout=20000):
        series_window.open_paths(paths)
    wait_render(series_window, qtbot, 0)
    series_window.add_layer("SNOWH")
    qtbot.waitUntil(lambda: len(series_window.layers.layers) == 1, timeout=20000)
    wait_render(series_window, qtbot, 0)
    output = tmp_path / "export.png"
    monkeypatch.setattr(
        "avalanche_view.ui.main_window.QFileDialog.getSaveFileName", lambda *args: (str(output), "")
    )
    observed = []

    def export(figure, path):
        observed.append((series_window._frame_timestep, figure.axes[0].get_title()))
        return path

    monkeypatch.setattr("avalanche_view.ui.main_window.ExportService.export_png", export)
    series_window.timeline.slider.setValue(1)
    series_window.export_action.trigger()
    qtbot.waitUntil(lambda: bool(observed), timeout=20000)
    assert observed[0][0] == 1 and "13:00" in observed[0][1]
