import logging
from dataclasses import replace
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from avalanche_view import __version__
from avalanche_view.config import (
    APPLICATION,
    DEFAULT_DATA_DIRECTORY,
    DEMO_PATH,
    ORGANIZATION,
    PROJECT_ROOT,
    RUNTIME_ROOT,
)
from avalanche_view.data.dataset_series import DatasetSeries, analyse_files
from avalanche_view.data.demo import create_demo_dataset
from avalanche_view.data.snowpack import (
    SNOWPACK_VERTICAL_DIM,
    is_categorical_variable,
    is_snowpack_variable,
    snowpack_display_metadata,
    snowpack_point_summary,
    snowpack_profile,
)
from avalanche_view.services.export_service import ExportService
from avalanche_view.services.file_service import (
    PreparedFrame,
    Worker,
    model_files,
    open_dataset,
    sibling_candidates,
    supported_path,
)
from avalanche_view.ui.dataset_browser import DatasetBrowser
from avalanche_view.ui.layer_manager import LayerManager
from avalanche_view.ui.layer_properties import LayerProperties
from avalanche_view.ui.plots_panel import PlotsPanel
from avalanche_view.ui.point_inspector import PointInspector
from avalanche_view.ui.series_selection import SeriesSelectionDialog
from avalanche_view.ui.snowpack_profile_dialog import SnowpackProfileDialog
from avalanche_view.ui.theme import apply_theme
from avalanche_view.ui.time_series_dialog import TimeSeriesDialog
from avalanche_view.ui.timeline import TimelineWidget
from avalanche_view.ui.vertical_profile_dialog import VerticalProfileDialog
from avalanche_view.visualization.colormaps import default_colormap
from avalanche_view.visualization.geography import CARTOPY_AVAILABLE, download_boundaries
from avalanche_view.visualization.layers import Layer, LayerCollection, RenderMode
from avalanche_view.visualization.legacy_map_renderer import LegacyMapRenderer
from avalanche_view.visualization.terrain3d import TERRAIN3D_AVAILABLE, Terrain3DDialog

logger = logging.getLogger(__name__)
LAYOUT_VERSION = 2


def _open_demo():
    path = DEMO_PATH if DEMO_PATH.exists() else RUNTIME_ROOT / "demo" / "demo_wrf.nc"
    if not path.exists():
        create_demo_dataset(path)
    return open_dataset(path)


class MainWindow(QMainWindow):
    dataset_loaded = pyqtSignal(object)

    def __init__(self, settings: QSettings | None = None, renderer="gis") -> None:
        super().__init__()
        self.settings = settings or QSettings(ORGANIZATION, APPLICATION)
        self.gis_enabled = renderer != "legacy"
        self.dataset = None
        self.layers = LayerCollection()
        self.timestep = 0
        self.selected_point = None
        self._jobs: set[Worker] = set()
        self._dialogs = []
        self._loading = False
        self._pending_close = False
        self._reset_extent = False
        self._render_job = None
        self._render_pending = False
        self._render_revision = 0
        self._prefetch_job = None
        self._frame = None
        self._frame_timestep = None
        self._pending_export = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("AvalancheView")
        self.setWindowIcon(
            QIcon(str(PROJECT_ROOT / "avalanche_view" / "resources" / "mountain.svg"))
        )
        self.resize(1500, 930)
        self.setMinimumSize(1050, 680)
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_menus()
        self._connect()
        self._redraw_timer = QTimer(self)
        self._redraw_timer.setSingleShot(True)
        self._redraw_timer.setInterval(35)
        self._redraw_timer.timeout.connect(self._render)
        self._restore_settings()
        self.statusBar().showMessage("Ready · Open a NetCDF file or load demo data")

    def _dock(self, name: str, widget, area) -> QDockWidget:
        dock = QDockWidget(name, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 14, 22, 14)
        branding = QVBoxLayout()
        brand = QLabel("AvalancheView")
        brand.setObjectName("brand")
        branding.addWidget(brand)
        subtitle = QLabel("MOUNTAIN WEATHER  /  WRF & NETCDF")
        subtitle.setObjectName("eyebrow")
        branding.addWidget(subtitle)
        header_layout.addLayout(branding)
        header_layout.addStretch()
        self.mode_label = QLabel("2D GEOGRAPHIC" if CARTOPY_AVAILABLE else "2D GRID VIEW")
        self.mode_label.setObjectName("eyebrow")
        header_layout.addWidget(self.mode_label)
        self.demo_button = QPushButton("Load demo")
        self.demo_button.setToolTip("Synthetic Caucasus mountain weather • 12 timesteps")
        header_layout.addWidget(self.demo_button)
        layout.addWidget(header)
        if self.gis_enabled:
            from avalanche_view.gis.map_widget import GISMapWidget

            self.map = GISMapWidget(self.settings)
        else:
            self.map = LegacyMapRenderer()
        layout.addWidget(self.map, 1)
        self.timeline = TimelineWidget()
        self.setCentralWidget(central)

        self.browser = DatasetBrowser()
        self.layer_manager = LayerManager()
        self.layer_manager.grouped = self.gis_enabled
        self.data_dock = self._dock(
            "Данные и переменные", self.browser, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.layers_dock = self._dock(
            "Слои", self.layer_manager, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.splitDockWidget(self.data_dock, self.layers_dock, Qt.Orientation.Vertical)
        self.data_dock.setMinimumWidth(280)
        self.properties = LayerProperties()
        properties_scroll = QScrollArea()
        properties_scroll.setWidgetResizable(True)
        properties_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        properties_scroll.setWidget(self.properties)
        self.properties_dock = self._dock(
            "Свойства слоя", properties_scroll, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.properties_dock.setMinimumWidth(290)
        self.inspector = PointInspector()
        self.inspector_dock = self._dock(
            "Инспектор точки", self.inspector, Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.splitDockWidget(self.properties_dock, self.inspector_dock, Qt.Orientation.Vertical)
        self.timeline_dock = self._dock(
            "Временная шкала", self.timeline, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.plots = PlotsPanel()
        self.plots_dock = self._dock("Графики", self.plots, Qt.DockWidgetArea.BottomDockWidgetArea)
        self.splitDockWidget(self.plots_dock, self.timeline_dock, Qt.Orientation.Vertical)
        self.timeline_dock.setMaximumHeight(100)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomRightCorner, Qt.DockWidgetArea.RightDockWidgetArea)
        self.plots_dock.hide()
        self.docks = [
            self.data_dock,
            self.layers_dock,
            self.properties_dock,
            self.inspector_dock,
            self.timeline_dock,
            self.plots_dock,
        ]
        self.resizeDocks(
            [self.data_dock, self.properties_dock], [320, 320], Qt.Orientation.Horizontal
        )
        self.resizeDocks(
            [self.properties_dock, self.inspector_dock], [520, 240], Qt.Orientation.Vertical
        )
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(150)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.cursor_label = QLabel()
        self.statusBar().addPermanentWidget(self.cursor_label)

    def _action(self, text, callback, shortcut=None, icon=None, checkable=False):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(shortcut)
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&Файл")
        self.open_action = self._action(
            "Открыть файл…",
            self.open_dialog,
            QKeySequence.StandardKey.Open,
            QStyle.StandardPixmap.SP_DialogOpenButton,
        )
        self.open_series_action = self._action(
            "Открыть серию файлов…",
            self.open_series_dialog,
            "Ctrl+Shift+O",
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
        )
        self.open_folder_action = self._action(
            "Открыть папку модели…",
            self.open_folder_dialog,
            "Ctrl+Alt+O",
            QStyle.StandardPixmap.SP_DirOpenIcon,
        )
        self.demo_action = self._action("Load demo data", self.load_demo)
        self.export_action = self._action(
            "Export image (PNG)…",
            self.export_dialog,
            "Ctrl+Shift+S",
            QStyle.StandardPixmap.SP_DialogSaveButton,
        )
        self.export_action.setEnabled(False)
        file_menu.addActions(
            [
                self.open_action,
                self.open_series_action,
                self.open_folder_action,
                self.demo_action,
                self.export_action,
            ]
        )
        file_menu.addSeparator()
        file_menu.addAction(self._action("Выход", self.close, QKeySequence.StandardKey.Quit))
        view_menu = self.menuBar().addMenu("&Вид")
        self.panels_menu = view_menu.addMenu("Панели")
        panel_icons = [
            QStyle.StandardPixmap.SP_FileDialogContentsView,
            QStyle.StandardPixmap.SP_FileDialogDetailedView,
            QStyle.StandardPixmap.SP_FileDialogInfoView,
            QStyle.StandardPixmap.SP_MessageBoxInformation,
            QStyle.StandardPixmap.SP_MediaPlay,
            QStyle.StandardPixmap.SP_ComputerIcon,
        ]
        for dock, icon in zip(self.docks, panel_icons, strict=True):
            action = dock.toggleViewAction()
            action.setIcon(self.style().standardIcon(icon))
            action.setToolTip(f"Показать/скрыть панель «{dock.windowTitle()}»")
            self.panels_menu.addAction(action)
        self.restore_layout_action = self._action(
            "Восстановить расположение панелей", self.restore_default_layout
        )
        view_menu.addAction(self.restore_layout_action)
        self.toolbars_menu = view_menu.addMenu("Панели инструментов")
        view_menu.addSeparator()
        self.dark_action = self._action("Dark theme", self.set_dark, checkable=True)
        view_menu.addAction(self.dark_action)
        self.fit_action = self._action(
            "Весь домен", self.fit_extent, "Ctrl+Home", QStyle.StandardPixmap.SP_DialogResetButton
        )
        view_menu.addAction(self.fit_action)
        tools_menu = self.menuBar().addMenu("&Инструменты")
        self.terrain_action = self._action("Experimental 3D terrain", self.show_terrain)
        self.terrain_action.setEnabled(TERRAIN3D_AVAILABLE)
        self.terrain_action.setToolTip(
            "Explore terrain in 3D"
            if TERRAIN3D_AVAILABLE
            else "Install optional 3D dependencies: py -m pip install -e .[terrain]"
        )
        tools_menu.addAction(self.terrain_action)
        boundaries_action = self._action("Download map boundaries…", self.download_map_boundaries)
        boundaries_action.setEnabled(CARTOPY_AVAILABLE)
        tools_menu.addAction(boundaries_action)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("Quick start", self.quick_start))
        help_menu.addAction(self._action("About AvalancheView", self.about))
        toolbar = QToolBar("Основная панель", self)
        self.toolbar = toolbar
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.addActions([self.open_action, self.open_series_action, self.open_folder_action])
        toolbar.addSeparator()
        toolbar.addAction(self.map.toolbar._actions["home"])
        self.map.toolbar._actions["home"].setToolTip("Исходный вид карты")
        toolbar.addAction(self.fit_action)
        for key, title in (("pan", "Перемещение карты"), ("zoom", "Масштабирование карты")):
            action = self.map.toolbar._actions[key]
            action.setToolTip(title)
            toolbar.addAction(action)
        toolbar.addSeparator()
        for dock in (
            self.data_dock,
            self.layers_dock,
            self.properties_dock,
            self.plots_dock,
            self.inspector_dock,
        ):
            toolbar.addAction(dock.toggleViewAction())
        toolbar.addSeparator()
        self.previous_action = self._action(
            "Предыдущий шаг",
            self.timeline.previous.click,
            icon=QStyle.StandardPixmap.SP_MediaSeekBackward,
        )
        self.play_action = self._action(
            "Воспроизведение / пауза",
            self.timeline.play.setChecked,
            icon=QStyle.StandardPixmap.SP_MediaPlay,
            checkable=True,
        )
        self.timeline.play.toggled.connect(self.play_action.setChecked)
        self.timeline.play.toggled.connect(
            lambda playing: self.play_action.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_MediaPause
                    if playing
                    else QStyle.StandardPixmap.SP_MediaPlay
                )
            )
        )
        self.next_action = self._action(
            "Следующий шаг",
            self.timeline.next.click,
            icon=QStyle.StandardPixmap.SP_MediaSeekForward,
        )
        toolbar.addActions([self.previous_action, self.play_action, self.next_action])
        toolbar.addSeparator()
        toolbar.addAction(self.export_action)
        self.export_action.setText("Экспорт PNG…")
        self.addToolBar(toolbar)
        self.toolbars_menu.addAction(toolbar.toggleViewAction())
        self.toolbars_menu.addAction(self.map.toolbar.toggleViewAction())
        self._default_state = self.saveState(LAYOUT_VERSION)
        if self.gis_enabled:
            from avalanche_view.gis.controls import install_gis_controls

            install_gis_controls(self)
            self._default_state = self.saveState(LAYOUT_VERSION)
            self.layer_manager.refresh([])
            self.terrain_action.setText("3D-рельеф в карте")
            self.terrain_action.setEnabled(True)
            self.terrain_action.setToolTip("Переключить эту карту в 3D")
            boundaries_action.setVisible(False)
            self.map.frame_rendered.connect(self._gis_rendered)
            self.map.export_finished.connect(lambda path: self.statusBar().showMessage(f"Экспортировано: {path}", 10000))
            self.map.bridge.received.connect(lambda event: self.mode_label.setText(event["mode"] + " · GIS") if event["type"] == "mode" else None)

    def _connect(self) -> None:
        self.demo_button.clicked.connect(self.load_demo)
        self.browser.add_requested.connect(self.add_layer)
        self.browser.info_requested.connect(self.show_dataset_info)
        self.layer_manager.layer_selected.connect(self.select_layer)
        self.layer_manager.visibility_changed.connect(self.set_visibility)
        self.layer_manager.remove_requested.connect(self.remove_layer)
        self.layer_manager.move_requested.connect(self.move_layer)
        self.properties.layer_changed.connect(self.update_layer)
        self.timeline.timestep_changed.connect(self.set_timestep)
        self.map.point_selected.connect(self.inspect_point)
        self.map.cursor_moved.connect(self.cursor_label.setText)
        self.map.render_warning.connect(
            lambda message: self.statusBar().showMessage(message, 15000)
        )
        self.inspector.series_requested.connect(self.show_time_series)
        self.inspector.profile_requested.connect(self.show_vertical_profile)
        self.inspector.snowpack_requested.connect(self.show_snowpack_profile)

    def _restore_settings(self) -> None:
        if geometry := self.settings.value("geometry"):
            try:
                self.restoreGeometry(geometry)
            except (TypeError, ValueError):
                self.resize(1500, 930)
        if state := self.settings.value("dockState"):
            try:
                restored = self.settings.value(
                    "layoutVersion", 0, type=int
                ) == LAYOUT_VERSION and self.restoreState(state, LAYOUT_VERSION)
            except (TypeError, ValueError):
                restored = False
            if not restored or all(dock.isHidden() for dock in self.docks):
                self.restore_default_layout()
        dark = self.settings.value("darkTheme", False, type=bool)
        self.dark_action.setChecked(dark)
        self.set_dark(dark)

    def set_dark(self, dark: bool) -> None:
        apply_theme(QApplication.instance(), dark)
        self.map.set_theme(dark)
        self.settings.setValue("darkTheme", dark)
        if self.dataset:
            self.schedule_render()
        else:
            self.map.empty()

    def restore_default_layout(self) -> None:
        self.restoreState(self._default_state, LAYOUT_VERSION)
        for dock in self.docks:
            dock.setFloating(False)
            dock.show()
        self.toolbar.show()
        self.map.toolbar.show()
        self.resizeDocks([self.data_dock, self.layers_dock], [420, 240], Qt.Orientation.Vertical)
        self.resizeDocks([self.plots_dock, self.timeline_dock], [280, 85], Qt.Orientation.Vertical)

    def show_dataset_info(self) -> None:
        if not self.dataset:
            return
        dataset = self.dataset
        details = (
            f"Тип: {getattr(dataset, 'model_type', 'WRF / NetCDF')}\n"
            f"Domain: {getattr(dataset, 'domain', dataset.metadata.get('grid_id', '—'))}\n"
            f"Файлов: {len(dataset.entries) if isinstance(dataset, DatasetSeries) else 1}\n"
            f"Временных шагов: {dataset.time_count}\nНачало: {dataset.timestamps[0]}\nКонец: {dataset.timestamps[-1]}\n"
            f"Grid: {dataset.dimensions.get(dataset.y_dimension)} × {dataset.dimensions.get(dataset.x_dimension)}\n"
            f"Projection: {dataset.projection}\nVariables: {len(dataset.variables)}\n"
        )
        self._show_message(
            "Информация о наборе данных",
            details,
            "\n".join(
                f"{name}: {dataset.availability(name)} / {dataset.time_count}"
                for name in dataset.variables
            ),
        )

    def _show_message(self, title, message, details=""):
        box = QMessageBox(
            QMessageBox.Icon.Information, title, message, QMessageBox.StandardButton.Ok, self
        )
        if details:
            box.setDetailedText(details)
        box.exec()

    def open_dialog(self) -> None:
        directory = self.settings.value("lastDirectory", str(DEFAULT_DATA_DIRECTORY))
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть файл WRF / NetCDF",
            directory,
            "NetCDF / WRF (*.nc *.nc4 *.cdf met_em* wrfout*);;Все файлы (*)",
        )
        if path:
            self.open_path(path, discover=True)

    def open_series_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Открыть серию файлов",
            self.settings.value("lastDirectory", str(DEFAULT_DATA_DIRECTORY)),
            "NetCDF / WRF (*.nc *.nc4 *.cdf met_em* wrfout*);;Все файлы (*)",
        )
        if paths:
            self.open_paths(paths)

    def open_folder_dialog(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Открыть папку модели",
            self.settings.value("lastDirectory", str(DEFAULT_DATA_DIRECTORY)),
        )
        if directory:
            self.open_folder(directory)

    def open_folder(self, directory):
        if self._loading:
            return
        self.settings.setValue("lastDirectory", str(directory))
        self._begin_loading()
        worker = Worker(
            lambda progress: analyse_files(model_files(directory), progress), report_progress=True
        )
        self._run_job(
            worker, lambda result: self._analysed(result, choose=True), "Анализ папки модели…"
        )

    def open_paths(self, paths):
        if self._loading:
            return
        paths = list(paths)
        if not paths:
            return
        self.settings.setValue("lastDirectory", str(Path(paths[0]).parent))
        self._begin_loading()
        self._run_job(
            Worker(analyse_files, paths, report_progress=True),
            self._analysed,
            "Анализ файлов модели…",
        )

    def _analysed(self, result, choose=False, single_path=None):
        if self._pending_close:
            return
        if not result.groups:
            if single_path is not None:
                self._run_job(Worker(open_dataset, single_path), self._loaded, "Открытие файла…")
                return
            self._show_error(
                "Нет подходящей серии",
                "Не найдено совместимых файлов с определённым временем.",
                "\n".join(result.errors),
            )
            return
        groups = result.groups
        if single_path is not None:
            group = next(
                (
                    group
                    for group in groups
                    if any(entry.path.resolve() == single_path.resolve() for entry in group.entries)
                ),
                None,
            )
            if group is None:
                self._run_job(Worker(open_dataset, single_path), self._loaded, "Открытие файла…")
                return
            if len(group.entries) > 1:
                box = QMessageBox(
                    QMessageBox.Icon.Question,
                    "Найдена временная серия",
                    f"В этой папке найдено ещё {len(group.entries) - 1} совместимых файлов модели.\nОткрыть всю временную серию?",
                    parent=self,
                )
                series_button = box.addButton("Открыть серию", QMessageBox.ButtonRole.AcceptRole)
                single_button = box.addButton("Только этот файл", QMessageBox.ButtonRole.NoRole)
                box.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() == single_button:
                    self._run_job(
                        Worker(open_dataset, single_path), self._loaded, "Открытие файла…"
                    )
                    return
                if box.clickedButton() != series_button:
                    return
            else:
                self._run_job(Worker(open_dataset, single_path), self._loaded, "Открытие файла…")
                return
        elif len(groups) > 1 or choose:
            dialog = SeriesSelectionDialog(groups, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            group = groups[dialog.selected_index]
        else:
            group = groups[0]
        dataset = DatasetSeries(entries=group.entries)
        dataset.warnings.extend(result.errors + group.warnings)
        self._loaded(dataset)
        if dataset.warnings:
            for warning in dataset.warnings:
                logger.warning("Series: %s", warning)
            self._show_message(
                "Результат анализа серии",
                f"Загружено: {len(dataset.entries)} файлов\nПропущено: {len(result.errors)} файлов\nВременных шагов: {dataset.time_count}\nПредупреждений: {len(dataset.warnings)}",
                "\n".join(dataset.warnings),
            )

    def open_path(self, path: str | Path, discover=False) -> None:
        if self._loading:
            self.statusBar().showMessage("Please wait for the current file to open", 5000)
            return
        path = Path(path)
        if path.is_dir():
            self.open_folder(path)
            return
        self.settings.setValue("lastDirectory", str(path.parent))
        self._begin_loading()
        if discover:

            def scan(progress):
                candidates = sibling_candidates(path)
                return analyse_files(candidates, progress) if len(candidates) > 1 else None

            def found(result):
                if result is None:
                    self._run_job(Worker(open_dataset, path), self._loaded, "Открытие файла…")
                else:
                    self._analysed(result, single_path=path)

            self._run_job(Worker(scan, report_progress=True), found, "Поиск совместимой серии…")
            return
        self._run_job(Worker(open_dataset, path), self._loaded, "Opening and analysing NetCDF…")

    def load_demo(self) -> None:
        if self._loading:
            return
        self._begin_loading()
        self._run_job(
            Worker(_open_demo),
            lambda dataset: self._loaded(dataset, demo=True),
            "Loading demo data…",
        )

    def _begin_loading(self) -> None:
        self._loading = True
        self.timeline.pause()
        self.timeline.setEnabled(False)
        for action in (self.previous_action, self.play_action, self.next_action):
            action.setEnabled(False)
        self.open_action.setEnabled(False)
        self.open_series_action.setEnabled(False)
        self.open_folder_action.setEnabled(False)
        self.demo_action.setEnabled(False)
        self.demo_button.setEnabled(False)

    def _run_job(self, worker, callback, message) -> None:
        self._jobs.add(worker)
        self.progress.show()
        self.statusBar().showMessage(message)
        worker.signals.result.connect(callback)
        worker.signals.error.connect(self._worker_error)
        worker.signals.finished.connect(lambda: self._finish_job(worker))
        worker.signals.progress.connect(self._job_progress)
        self.pool.start(worker)

    def _job_progress(self, current, total, message):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(current)
        self.statusBar().showMessage(f"{message} · {current} / {total}")

    def _finish_job(self, worker) -> None:
        self._jobs.discard(worker)
        if not self._jobs:
            self.progress.hide()
            self.progress.setRange(0, 0)
            self._loading = False
            self.open_action.setEnabled(True)
            self.open_series_action.setEnabled(True)
            self.open_folder_action.setEnabled(True)
            self.demo_action.setEnabled(True)
            self.demo_button.setEnabled(True)
            self.timeline.setEnabled(self.dataset is not None)
            for action in (self.previous_action, self.play_action, self.next_action):
                action.setEnabled(self.dataset is not None and self.dataset.time_count > 1)
            if self._pending_close:
                QTimer.singleShot(0, self.close)

    def _worker_error(self, message, details) -> None:
        if not self._pending_close:
            self._show_error("Operation failed", message, details)

    def _loaded(self, dataset, demo=False) -> None:
        if self._pending_close:
            dataset.close()
            return
        self._redraw_timer.stop()
        if self.dataset:
            self.dataset.close()
        self.dataset = dataset
        self._frame = None
        self._frame_timestep = None
        self._pending_export = None
        logger.info(
            "Opened %s: %s, %d timesteps", dataset.path, dataset.dimensions, dataset.time_count
        )
        self.layers = LayerCollection()
        self.selected_point = None
        self.timestep = 0
        self._snow_inspection_key = None
        self.map.clear_point()
        self.map._has_data = False
        self.browser.set_dataset(dataset, self.settings.value("language", "ru"))
        self.layer_manager.refresh([])
        self.properties.set_layer(None)
        self.inspector.clear()
        plottable = [v.name for v in dataset.variables.values() if v.plottable]
        vertical = [
            name
            for name in plottable
            if sum(size > 1 for size in dataset.vertical_dimensions(name).values()) == 1
        ]
        self.inspector.set_variables(plottable, vertical)
        self.timeline.set_timestamps(dataset.timestamps, getattr(dataset, "gaps", []))
        self.export_action.setEnabled(True)
        self.setWindowTitle(f"AvalancheView — {getattr(dataset, 'name', dataset.path.name)}")
        self.mode_label.setText(
            "2D GEOGRAPHIC" if dataset.latitude_name and CARTOPY_AVAILABLE else "2D GRID VIEW"
        )
        if self.gis_enabled:
            self.mode_label.setText("GIS · WebGL")
            from avalanche_view.ui.localization import translate_window
            translate_window(self, self.settings.value("language", "ru"))
        self._reset_extent = True
        if demo:
            self.add_layer("Temperature 2m (°C)")
        else:
            self.schedule_render()
        self.statusBar().showMessage(
            f"Opened {dataset.path.name} · Double-click a variable to add a layer", 10000
        )
        self.dataset_loaded.emit(dataset)

    def add_layer(self, variable: str, values=None) -> None:
        if not self.dataset:
            return
        if isinstance(self.dataset, DatasetSeries) and values is None:
            dataset = self.dataset
            timestep = self.timestep

            def ready(values):
                if dataset is self.dataset and not self._pending_close:
                    self.add_layer(variable, values)

            self._run_job(
                Worker(dataset.read, variable, timestep), ready, f"Чтение слоя {variable}…"
            )
            return
        try:
            info = self.dataset.variables[variable]
            if not info.plottable:
                raise ValueError("Select a numeric variable on a horizontal grid")
            if values is None:
                values = self.dataset.read(variable, self.timestep)
            finite = values[np.isfinite(values)]
            layer = Layer(
                variable,
                units=snowpack_display_metadata(info, self.settings.value("language", "ru"))[1],
                colormap=self.settings.value(f"colormap/{variable}", default_colormap(variable)),
                minimum=float(finite.min()) if finite.size else 0,
                maximum=float(finite.max()) if finite.size else 1,
                opacity=0.72 if self.layers.layers else 1,
            )
            if variable == "T2" or "Temperature" in variable:
                layer.mode = RenderMode.FILLED_CONTOURS
            self.layers.add(layer)
            self.layer_manager.refresh(self.layers.layers, layer.id)
            self.select_layer(layer.id)
            self.properties_dock.show()
            self.schedule_render()
            self._refresh_inspector()
        except (KeyError, ValueError, IndexError, OSError) as exc:
            logger.exception("Unable to add layer")
            self._show_error("Cannot add layer", str(exc))

    def select_layer(self, layer_id: str) -> None:
        layer = self.layers.get(layer_id)
        self.properties.set_layer(layer, self.dataset.vertical_dimensions(layer.variable))
        if self.gis_enabled:
            from avalanche_view.gis.capabilities import VariableCapabilities

            self.properties.set_capabilities(VariableCapabilities.detect(self.dataset, layer.variable))
        self.inspector.variable.setCurrentText(layer.variable)

    def update_layer(self, candidate: Layer) -> None:
        index = next(i for i, layer in enumerate(self.layers.layers) if layer.id == candidate.id)
        self.layers.layers[index] = candidate
        self.settings.setValue("lastColormap", candidate.colormap)
        self.settings.setValue(f"colormap/{candidate.variable}", candidate.colormap)
        self.layer_manager.refresh(self.layers.layers, candidate.id)
        self.schedule_render()
        self._refresh_inspector()

    def set_visibility(self, layer_id: str, visible: bool) -> None:
        self.layers.get(layer_id).visible = visible
        self.schedule_render()
        self._refresh_inspector()

    def remove_layer(self, layer_id: str) -> None:
        self.layers.remove(layer_id)
        selection = self.layers.layers[0].id if self.layers.layers else None
        self.layer_manager.refresh(self.layers.layers, selection)
        if selection:
            self.select_layer(selection)
        else:
            self.properties.set_layer(None)
        self.schedule_render()
        self._refresh_inspector()

    def move_layer(self, layer_id: str, delta: int) -> None:
        self.layers.move(layer_id, delta)
        self.layer_manager.refresh(self.layers.layers, layer_id)
        self.schedule_render()

    def set_timestep(self, timestep: int) -> None:
        if self.dataset is None or not 0 <= timestep < self.dataset.time_count:
            return
        self.timestep = timestep
        if (self.gis_enabled or isinstance(self.dataset, DatasetSeries)) and self.timeline.play.isChecked():
            # Pace animation by completed frames, including slow disks.
            self.timeline.timer.stop()
        self.schedule_render()
        self._refresh_inspector()

    def schedule_render(self) -> None:
        if self.dataset:
            self._render_revision += 1
            self._redraw_timer.start()

    def _render(self) -> None:
        if not self.dataset:
            return
        if self.gis_enabled or isinstance(self.dataset, DatasetSeries):
            if self._render_job is not None:
                self._render_pending = True
                return
            dataset, timestep = self.dataset, self.timestep
            layers = [replace(layer) for layer in self.layers.layers]
            revision = self._render_revision
            if self.gis_enabled:
                from avalanche_view.gis.scientific import PreparedScene

                worker = Worker(PreparedScene, dataset, layers, timestep, self.map.service)
            else:
                worker = Worker(PreparedFrame, dataset, [layer for layer in layers if layer.visible], timestep)
            self._render_job = worker
            self._jobs.add(worker)

            def ready(frame):
                if self._pending_close or self.dataset is not dataset:
                    return
                if timestep != self.timestep or revision != self._render_revision:
                    self._render_pending = True
                    return
                try:
                    self._frame, self._frame_timestep = frame, timestep
                    if self.gis_enabled:
                        frame.scene["revision"] = revision
                    self.map.render(frame, layers, timestep, self._reset_extent)
                    self._reset_extent = False
                    self._refresh_inspector()
                    if isinstance(dataset, DatasetSeries):
                        self._prefetch_next(dataset, timestep, layers)
                    if not self.gis_enabled and self.timeline.play.isChecked() and not self._loading:
                        self.timeline.timer.start()
                    if self._pending_export and not self.gis_enabled:
                        path, self._pending_export = self._pending_export, None
                        self._export_png(path)
                except (ValueError, KeyError, IndexError, OSError, RuntimeError) as exc:
                    logger.exception("Series rendering failed")
                    self.timeline.pause()
                    self._pending_export = None
                    self.statusBar().showMessage(f"Не удалось отобразить карту: {exc}", 15000)

            def done():
                self._render_job = None
                self._finish_job(worker)
                if self._render_pending and not self._pending_close:
                    self._render_pending = False
                    self._redraw_timer.start()

            worker.signals.result.connect(ready)

            def failed(message, details):
                logger.error("Series frame failed: %s\n%s", message, details)
                self.timeline.pause()
                self._pending_export = None
                self.statusBar().showMessage(message, 15000)

            worker.signals.error.connect(failed)
            worker.signals.finished.connect(done)
            self.pool.start(worker)
            return
        try:
            self.map.render(self.dataset, self.layers.layers, self.timestep, self._reset_extent)
            self._reset_extent = False
        except (ValueError, IndexError, OSError, RuntimeError) as exc:
            logger.exception("Map rendering failed")
            self.timeline.pause()
            self.statusBar().showMessage(f"Cannot draw map: {exc}", 15000)

    def _prefetch_next(self, dataset, timestep, layers):
        if self._prefetch_job is not None or self._loading or dataset.time_count < 2:
            return
        worker = Worker(
            dataset.prefetch,
            (timestep + 1) % dataset.time_count,
            [(layer.variable, layer.level) for layer in layers if layer.visible],
        )
        self._prefetch_job = worker
        self._jobs.add(worker)

        def done():
            self._prefetch_job = None
            self._finish_job(worker)

        worker.signals.finished.connect(done)
        self.pool.start(worker)

    def fit_extent(self) -> None:
        if self.gis_enabled:
            self.map.send("fit")
            return
        self._reset_extent = True
        self.schedule_render()

    def inspect_point(self, x: float, y: float) -> None:
        if not self.dataset:
            return
        try:
            source = self._frame if isinstance(self.dataset, DatasetSeries) else self.dataset
            if source is None:
                return
            grid = source.coordinates(self.timestep)
            self.selected_point = grid.nearest(x, y)
            row, column = self.selected_point
            self.map.mark_point(grid.x[row, column], grid.y[row, column])
            self._refresh_inspector()
            self.inspector_dock.show()
            self.schedule_render()
        except (ValueError, IndexError, OSError) as exc:
            logger.exception("Point inspection failed")
            self._show_error("Cannot inspect point", str(exc))

    def _refresh_inspector(self) -> None:
        if not self.dataset or self.selected_point is None:
            return
        row, column = self.selected_point
        source = self.dataset
        if isinstance(source, DatasetSeries):
            if self._frame is None or self._frame_timestep != self.timestep:
                return
            source = self._frame
        grid = source.coordinates(self.timestep)
        self.map.mark_point(grid.x[row, column], grid.y[row, column])
        values = []
        for layer in self.layers.layers:
            if layer.visible:
                try:
                    value = source.point_value(
                        layer.variable, self.timestep, row, column, layer.level
                    )
                    text = (str(int(value)) if is_categorical_variable(layer.variable)
                            else f"{value:.5g}") if np.isfinite(value) else "NaN / missing"
                except (ValueError, IndexError, KeyError) as exc:
                    logger.warning("Point value unavailable: %s", exc)
                    text = "Недоступно для этого шага"
                values.append((layer.name, text, layer.units))
        self.inspector.update_values(self.selected_point, grid, values)
        if SNOWPACK_VERTICAL_DIM not in self.dataset.dimensions:
            return
        dataset, timestep, point = self.dataset, self.timestep, self.selected_point
        key = (id(dataset), timestep, point)
        if getattr(self, "_snow_inspection_key", None) == key:
            return
        self._snow_inspection_key = key
        self.inspector.set_snow_values([], False)

        def show_snow_summary(summary):
            if self._pending_close or self.dataset is not dataset or self.timestep != timestep or self.selected_point != point:
                return
            language = self.settings.value("language", "ru")
            entries = []
            for name, value in summary.items():
                if name in dataset.variables:
                    title, units = snowpack_display_metadata(dataset.variables[name], language)
                else:
                    title = "Средняя кажущаяся плотность покрова" if language == "ru" else name
                    units = "kg m-3"
                text = (str(int(value)) if name == "SN_NLAYERS" else f"{value:.5g}") if np.isfinite(value) else "NaN"
                entries.append((title, text, units))
            count = summary.get("SN_NLAYERS", np.nan)
            active = np.isfinite(count) and count > 0 and any(
                info.plottable and is_snowpack_variable(info) for info in dataset.variables.values()
            )
            message = "" if active else (
                "Layer diagnostics SNOWPACK для этого history record не записаны/не активны."
                if language == "ru" else "SNOWPACK layer diagnostics are not recorded/active for this history record."
            )
            self.inspector.set_snow_values(entries, active, message)

        self._run_job(Worker(snowpack_point_summary, dataset, timestep, *point),
                      show_snow_summary, "Чтение свойств снежного покрова…")

    def show_time_series(self, variable: str) -> None:
        if self.dataset is None or self.selected_point is None or self._loading:
            return
        self.timeline.pause()
        dataset = self.dataset
        point = self.selected_point
        layer = next((layer for layer in self.layers.layers if layer.variable == variable), None)
        level = layer.level if layer else 0
        worker = Worker(
            dataset.time_series,
            variable,
            *point,
            level,
            report_progress=isinstance(dataset, DatasetSeries),
        )

        def show(values):
            if self._pending_close or self.dataset is not dataset:
                return
            dialog = TimeSeriesDialog(
                variable, dataset.timestamps, values,
                snowpack_display_metadata(dataset.variables[variable], self.settings.value("language", "ru"))[1],
                point, self
            )
            self._keep_dialog(dialog, show=False)
            self.plots.add_plot(dialog, f"{variable} · X {point[1]} / Y {point[0]}")
            self.plots_dock.show()
            self.plots_dock.raise_()

        self._run_job(worker, show, f"Reading {variable} time series…")

    def show_vertical_profile(self, variable: str) -> None:
        if self.dataset is None or self.selected_point is None or self._loading or not variable:
            return
        if is_snowpack_variable(self.dataset.variables[variable]):
            self.show_snowpack_profile(variable)
            return
        self.timeline.pause()
        dataset = self.dataset
        point = self.selected_point
        timestep = self.timestep

        def read_profile():
            values = dataset.vertical_profile(variable, timestep, *point)
            dimensions = dataset.vertical_dimensions(variable)
            vertical_dimension = next(name for name, size in dimensions.items() if size > 1)
            coordinate = None
            coordinate_name = "Уровень модели"
            coordinate_units = ""
            for candidate in ("GHT", "PRES"):
                if candidate not in dataset.variables:
                    continue
                candidate_dimensions = dataset.vertical_dimensions(candidate)
                if candidate_dimensions.get(vertical_dimension, 0) <= 1:
                    continue
                coordinate = dataset.vertical_profile(candidate, timestep, *point)
                coordinate_name = "Высота" if candidate == "GHT" else "Давление"
                coordinate_units = dataset.variables[candidate].units or (
                    "Pa" if candidate == "PRES" else "m"
                )
                break
            return values, coordinate, coordinate_name, coordinate_units

        def show(result):
            if self._pending_close or self.dataset is not dataset:
                return
            values, coordinate, coordinate_name, coordinate_units = result
            dialog = VerticalProfileDialog(
                variable,
                values,
                dataset.variables[variable].units,
                point,
                coordinate,
                coordinate_name,
                coordinate_units,
                self,
            )
            self._keep_dialog(dialog, show=False)
            self.plots.add_plot(dialog, f"{variable} · вертикальный разрез")
            self.plots_dock.show()
            self.plots_dock.raise_()

        self._run_job(Worker(read_profile), show, f"Чтение вертикального разреза {variable}…")

    def show_snowpack_profile(self, variable="SNPACK_T") -> None:
        """Read a point snapshot in a worker and keep the atmospheric profile path intact."""
        if self.dataset is None or self.selected_point is None or self._loading:
            return
        self.timeline.pause()
        dataset, point, timestep = self.dataset, self.selected_point, self.timestep
        language = self.settings.value("language", "ru")
        if isinstance(dataset, DatasetSeries):
            worker = Worker(dataset.snowpack_profile, timestep, *point, language)
        else:
            worker = Worker(snowpack_profile, dataset, timestep, *point, language)

        def show(profile):
            if self._pending_close or self.dataset is not dataset:
                return
            dialog = SnowpackProfileDialog(profile, variable, language, self)
            self._keep_dialog(dialog, show=False)
            self.plots.add_plot(dialog, "SNOWPACK · " + profile.timestamp)
            self.plots_dock.show()
            self.plots_dock.raise_()

        self._run_job(worker, show, "Чтение профиля SNOWPACK…")

    def _keep_dialog(self, dialog, show=True) -> None:
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialogs.append(dialog)
        dialog.destroyed.connect(
            lambda: self._dialogs.remove(dialog) if dialog in self._dialogs else None
        )
        if show:
            dialog.show()

    def export_dialog(self) -> None:
        if not self.dataset:
            return
        self.timeline.pause()
        path, _ = QFileDialog.getSaveFileName(
            self, "Export map at 300 DPI", "avalanche_map.png", "PNG (*.png)"
        )
        if path:
            if self.gis_enabled or isinstance(self.dataset, DatasetSeries):
                self._pending_export = path
                self.schedule_render()
                return
            try:
                self._redraw_timer.stop()
                self._render()
                self._export_png(path)
            except (ValueError, OSError, RuntimeError) as exc:
                logger.exception("PNG export failed")
                self._show_error("Cannot export image", str(exc))

    def _export_png(self, path):
        if self.gis_enabled:
            self.map.export_png(path)
            return
        try:
            self.map.canvas.draw()
            output = ExportService.export_png(self.map.figure, path)
            self.statusBar().showMessage(f"Экспортировано: {output}", 10000)
        except (ValueError, OSError, RuntimeError) as exc:
            logger.exception("PNG export failed")
            self._show_error("Не удалось экспортировать изображение", str(exc))

    def show_terrain(self) -> None:
        if self.gis_enabled:
            self.map.set_mode(True)
            return
        if not self.dataset or not TERRAIN3D_AVAILABLE:
            return
        self.timeline.pause()
        try:
            terrain_name = next(
                (name for name in ("HGT", "HGT_M") if name in self.dataset.variables), None
            )
            if terrain_name is None:
                raise ValueError("This dataset has no HGT terrain variable")
            layer = next(
                (
                    layer
                    for layer in self.layers.layers
                    if layer.visible
                    and layer.mode
                    not in (
                        RenderMode.WIND_VECTORS,
                        RenderMode.WIND_BARBS,
                        RenderMode.HILLSHADE,
                    )
                ),
                None,
            )
            grid = self.dataset.coordinates(self.timestep)
            elevation = self.dataset.read(terrain_name, self.timestep)
            values = (
                self.dataset.read(layer.variable, self.timestep, layer.level) if layer else None
            )
            dialog = Terrain3DDialog(grid, elevation, values, layer, self)
            self._keep_dialog(dialog)
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            logger.exception("3D terrain initialization failed")
            self._show_error("3D terrain unavailable", str(exc))

    def download_map_boundaries(self) -> None:
        self._run_job(
            Worker(download_boundaries),
            lambda message: (self.statusBar().showMessage(message, 10000), self.schedule_render()),
            "Downloading Natural Earth coastlines and borders…",
        )

    def _show_error(self, title: str, message: str, details: str = "") -> None:
        box = QMessageBox(
            QMessageBox.Icon.Warning, title, message[:700], QMessageBox.StandardButton.Ok, self
        )
        box.setDetailedText(details or message)
        box.exec()

    def quick_start(self) -> None:
        QMessageBox.information(
            self,
            "Quick start",
            "1. Open a NetCDF file or click Load demo.\n"
            "2. Double-click a variable to add a layer.\n"
            "3. Select a layer to adjust its appearance.\n"
            "4. Use the timeline to explore time steps and animation.\n"
            "5. Click the map for point values and time series.\n"
            "6. Export a 300 DPI PNG from File → Export image.",
        )

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About AvalancheView",
            f"AvalancheView {__version__}\n"
            "Scientific WRF / NetCDF desktop viewer\nPython · PyQt6 · xarray · Matplotlib\n"
            "Demo data are synthetic. Avalanche risk models are a future extension.",
        )

    def dragEnterEvent(self, event) -> None:
        if any(
            url.isLocalFile()
            and (Path(url.toLocalFile()).is_dir() or supported_path(url.toLocalFile()))
            for url in event.mimeData().urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        directories = [path for path in paths if path.is_dir()]
        files = [path for path in paths if path.is_file() and supported_path(path)]
        if len(directories) == 1 and not files:
            self.open_folder(directories[0])
        elif files or directories:

            def scan(progress):
                candidates = files + [
                    path for directory in directories for path in model_files(directory)
                ]
                return analyse_files(candidates, progress)

            if len(files) == 1 and not directories:
                self.open_path(files[0], discover=True)
            elif not self._loading:
                self._begin_loading()
                self._run_job(
                    Worker(scan, report_progress=True),
                    self._analysed,
                    "Анализ перетаскиваемых файлов…",
                )
        else:
            return
        event.acceptProposedAction()

    def closeEvent(self, event) -> None:
        self.timeline.pause()
        self._redraw_timer.stop()
        if self._jobs:
            self._pending_close = True
            self.statusBar().showMessage("Finishing background operations before closing…")
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("dockState", self.saveState(LAYOUT_VERSION))
        self.settings.setValue("layoutVersion", LAYOUT_VERSION)
        self.settings.sync()
        for dialog in list(self._dialogs):
            dialog.close()
        if self.dataset:
            self.dataset.close()
        if self.gis_enabled:
            self.map.shutdown()
        event.accept()

    def _gis_rendered(self, frame):
        if frame.get("revision") != self._render_revision:
            return
        if self.timeline.play.isChecked() and not self._loading:
            self.timeline.timer.start()
        if self._pending_export:
            path, self._pending_export = self._pending_export, None
            self._export_png(path)
