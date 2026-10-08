"""Qt host and the single, typed-message boundary to the GIS scene."""

import base64
import json
import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QImage
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QToolBar, QVBoxLayout, QWidget

from avalanche_view import __version__
from avalanche_view.gis.basemaps import DETAILED_TERRAIN_ID, BasemapRegistry
from avalanche_view.gis.terrain import TerrainService
from avalanche_view.gis.transport import LocalDataService

logger = logging.getLogger(__name__)


class MapBridge(QObject):
    command = pyqtSignal(str)
    received = pyqtSignal(object)

    def send(self, kind, **payload):
        self.command.emit(
            json.dumps({"type": kind, **payload}, ensure_ascii=False, allow_nan=False)
        )

    @pyqtSlot(str)
    def event(self, message):
        try:
            value = json.loads(message)
            if isinstance(value, dict) and isinstance(value.get("type"), str):
                self.received.emit(value)
        except (ValueError, TypeError):
            logger.warning("Invalid GIS event")


class GISPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        # URLs may contain provider keys: log the message, not the source URL.
        logger.info("GIS JavaScript line %s: %s", line, message[:1000])


class GISMapWidget(QWidget):
    point_selected = pyqtSignal(float, float)
    cursor_moved = pyqtSignal(str)
    render_warning = pyqtSignal(str)
    frame_rendered = pyqtSignal(object)
    export_finished = pyqtSignal(str)
    ready = pyqtSignal()
    terrain_source_changed = pyqtSignal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        # A parent Electron/Chromium crash pipe belongs to that process, not Qt's child.
        os.environ.pop("CHROME_CRASHPAD_PIPE_NAME", None)
        self.settings = settings
        self.registry = BasemapRegistry(settings)
        self.terrain = TerrainService()
        self.service = LocalDataService(self.terrain)
        self.bridge = MapBridge(self)
        self.bridge.received.connect(self._event)
        self._ready = False
        self._queue = {}
        self._has_data = False
        self._closed = False
        self._export_path = None
        self.last_frame = None
        self.last_diagnostics = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.toolbar = QToolBar("Карта", self)
        self.toolbar.setObjectName("gisToolbar")
        self.toolbar._actions = {}
        for key, text, callback in (
            ("home", "⌂", lambda: self.send("home")),
            ("pan", "Перемещение", lambda: self.send("interactive", enabled=True)),
            ("zoom", "+", lambda: self.send("zoomIn")),
        ):
            action = QAction(text, self)
            action.triggered.connect(callback)
            self.toolbar._actions[key] = action
        self.toolbar.addAction("2D", lambda: self.set_mode(False))
        self.toolbar.addAction("3D", lambda: self.set_mode(True))
        self.mountains_action = self.toolbar.addAction("К горам", self.focus_mountains)
        self.mountains_action.setToolTip("3D-вид на горный массив с реальными высотами; приблизить камеру")
        self.toolbar.addSeparator()
        self.basemap = QComboBox()
        for provider in self.registry.providers.values():
            if provider.type != "raster-dem":
                self.basemap.addItem(provider.name, provider.id)
        self.basemap.setCurrentIndex(
            max(0, self.basemap.findData(settings.value("maps/basemap", "light")))
        )
        self.basemap.currentIndexChanged.connect(self._basemap_changed)
        self.toolbar.addWidget(self.basemap)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(QLabel(" Высота × "))
        self.exaggeration = QComboBox()
        self.exaggeration.addItems(["0.5", "1", "1.5", "2", "3"])
        self.exaggeration.setCurrentText("1")
        self.exaggeration.currentTextChanged.connect(
            lambda value: self.send("terrain", exaggeration=float(value))
        )
        self.toolbar.addWidget(self.exaggeration)
        layout.addWidget(self.toolbar)
        self.diagnostic = QLabel("Инициализация WebGL…")
        self.diagnostic.setWordWrap(True)
        layout.addWidget(self.diagnostic)
        self.view = QWebEngineView(self)
        page = GISPage(self.view)
        profile = page.profile()
        profile.setHttpUserAgent(f"AvalancheView/{__version__} " + profile.httpUserAgent())
        profile.setHttpCacheMaximumSize(192 * 1024 * 1024)
        self.view.setPage(page)
        page.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.channel = QWebChannel(page)
        self.channel.registerObject("bridge", self.bridge)
        page.setWebChannel(self.channel)
        page.loadingChanged.connect(
            lambda info: logger.info("GIS load: %s %s", info.status().name, info.errorString())
        )
        page.renderProcessTerminated.connect(
            lambda *_: self._fatal(
                "Процесс Qt WebEngine завершился. Проверьте журнал приложения и драйвер GPU."
            )
        )
        self.view.loadFinished.connect(
            lambda ok: None if ok else self._fatal("Не удалось загрузить локальную GIS-сцену")
        )
        layout.addWidget(self.view, 1)
        self.view.load(QUrl(self.service.base_url + "index.html"))
        QTimer.singleShot(60000, self._startup_check)
        self._basemap_changed()
        self.select_terrain(settings.value("maps/terrainSource", DETAILED_TERRAIN_ID))

    def send(self, kind, **payload):
        if self._ready:
            self.bridge.send(kind, **payload)
        else:
            self._queue[kind] = payload

    def _startup_check(self):
        if not self._ready and not self._closed:
            self._fatal(
                "Карта не ответила за 60 секунд. Проверьте Qt WebEngine / WebGL. Диагностика: py main.py --legacy-map"
            )

    def _fatal(self, message):
        self.diagnostic.setText(message)
        self.diagnostic.show()
        self.render_warning.emit(message)

    def _event(self, event):
        kind = event["type"]
        if kind == "ready":
            self._ready = True
            self.diagnostic.hide()
            for command, payload in self._queue.items():
                self.bridge.send(command, **payload)
            self._queue.clear()
            self.ready.emit()
        elif kind == "error":
            self._fatal(event["message"])
        elif kind == "point":
            self.point_selected.emit(event["lon"], event["lat"])
        elif kind == "cursor":
            heights = self.terrain.heights(event["lon"], event["lat"])
            text = f"Широта: {event['lat']:.5f}°  Долгота: {event['lon']:.5f}°"
            for name, value in (
                ("Модель", heights["model"]),
                ("DEM", heights["dem"]),
                ("Рельеф карты", event.get("elevation")),
            ):
                if value is not None:
                    text += f"  {name}: {value:.1f} м"
            self.cursor_moved.emit(text)
        elif kind == "rendered":
            self.last_frame = event
            self.frame_rendered.emit(event)
        elif kind == "diagnostics":
            self.last_diagnostics = event
        elif kind == "terrainUnavailable":
            if self.terrain.selected == "provider" and self.terrain.model is not None:
                self.terrain.selected = "model"
                self.send("terrain", source=self.terrain.descriptor(self.service.base_url))
                self.terrain_source_changed.emit("model")
                message = "Детальный DEM недоступен. Временно показан грубый модельный рельеф; выберите реальный DEM для повторной загрузки."
                self.send("terrainNotice", message=message)
                self.render_warning.emit(message)
        elif kind == "export":
            try:
                data = base64.b64decode(event["png"], validate=True)
                if self._export_path:
                    path, self._export_path = self._export_path, None
                    Path(path).write_bytes(data)
                    self.export_finished.emit(str(path))
                else:
                    QApplication.clipboard().setImage(QImage.fromData(data, "PNG"))
                    self.export_finished.emit("Буфер обмена")
            except (ValueError, OSError) as exc:
                self._fatal(str(exc))

    def _basemap_changed(self):
        key = self.basemap.currentData()
        try:
            self.send("basemap", provider=self.registry.get(key))
            self.settings.setValue("maps/basemap", key)
        except ValueError as exc:
            self.render_warning.emit(str(exc))

    def render(self, frame, layers, timestep, reset=False):
        self._has_data = True
        self.send("scene", scene={**frame.scene, "reset": reset})

    def set_mode(self, enabled):
        self.send("mode", enabled=enabled)

    def select_terrain(self, key, persist=False):
        if key in {"model", "local", "none"}:
            self.terrain.selected = key
        else:
            provider = self.registry.providers.get(key)
            if provider is None or provider.type != "raster-dem":
                key = DETAILED_TERRAIN_ID
            self.terrain.provider = self.registry.get(key)
            self.terrain.selected = "provider"
        if persist:
            self.settings.setValue("maps/terrainSource", key)
        self.send("terrain", source=self.terrain.descriptor(self.service.base_url))
        self.terrain_source_changed.emit(key)

    def focus_mountains(self):
        # This explicit action may move/zoom the camera; plain 2D/3D never does.
        self.send("mountains", center=self.terrain.mountain_focus())

    def set_theme(self, dark):
        self.send("theme", dark=dark)

    def empty(self):
        pass

    def clear_point(self):
        self.send("point", point=None)

    def mark_point(self, lon, lat):
        self.send("point", point=[float(lon), float(lat)])

    def export_png(self, path=None, scale=2):
        self._export_path = path
        self.send("export", scale=scale)

    def shutdown(self):
        if not self._closed:
            self._closed = True
            self.view.stop()
            self.view.setUrl(QUrl("about:blank"))
            self.service.close()
