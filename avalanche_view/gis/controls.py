"""Desktop GIS menus, provider editor and terrain controls."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import numpy as np
from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avalanche_view.gis.basemaps import BasemapProvider
from avalanche_view.gis.scientific import json_asset, scalar_descriptor
from avalanche_view.gis.terrain import terrain_derivatives
from avalanche_view.services.file_service import Worker
from avalanche_view.visualization.layers import Layer


class ProviderDialog(QDialog):
    def __init__(self, registry, parent):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("Карты → Провайдеры")
        self.resize(680, 420)
        form = QFormLayout(self)
        self.choose = QComboBox()
        self.choose.addItem("Новый провайдер", None)
        for provider in registry.providers.values():
            self.choose.addItem(provider.name, provider.id)
        form.addRow("Провайдер", self.choose)
        self.fields = {}
        for key, label in (
            ("id", "Идентификатор"),
            ("name", "Название"),
            ("url", "XYZ URL: {z}/{x}/{y}, {key}"),
            ("attribution", "Attribution (HTML)"),
            ("license", "Лицензия / условия"),
        ):
            control = QLineEdit()
            self.fields[key] = control
            form.addRow(label, control)
        self.kind = QComboBox()
        self.kind.addItems(["raster", "style", "raster-dem"])
        form.addRow("Тип источника", self.kind)
        self.encoding = QComboBox()
        self.encoding.addItems(["mapbox", "terrarium"])
        form.addRow("DEM encoding", self.encoding)
        self.maximum = QDoubleSpinBox()
        self.maximum.setRange(0, 24)
        self.maximum.setDecimals(0)
        self.maximum.setValue(18)
        form.addRow("Max zoom", self.maximum)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API key (в настройках пользователя)", self.key)
        self.error = QLabel()
        self.error.setWordWrap(True)
        form.addRow(self.error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.choose.currentIndexChanged.connect(self.load)

    def load(self):
        key = self.choose.currentData()
        if not key:
            return
        provider = self.registry.providers[key]
        for name, control in self.fields.items():
            control.setText(getattr(provider, name))
        self.kind.setCurrentText(provider.type)
        self.encoding.setCurrentText(provider.encoding)
        self.maximum.setValue(provider.maxZoom)
        self.key.setText(self.registry.settings.value(f"maps/keys/{key}", ""))

    def save(self):
        try:
            values = {key: control.text().strip() for key, control in self.fields.items()}
            provider = BasemapProvider(
                **values,
                type=self.kind.currentText(),
                maxZoom=int(self.maximum.value()),
                encoding=self.encoding.currentText(),
                requiresApiKey="{key}" in values["url"],
            )
            self.registry.save(provider, self.key.text())
            self.accept()
        except ValueError as exc:
            self.error.setText(str(exc))


class TerrainControls(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.map = window.map
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.addItem("Модель HGT / HGT_M", "model")
        self.source.addItem("Локальный GeoTIFF DEM", "local")
        self.source.addItem("Без рельефа", "none")
        self.refresh_providers()
        selected = self.map.terrain.provider["id"] if self.map.terrain.selected == "provider" else self.map.terrain.selected
        self.source.setCurrentIndex(max(0, self.source.findData(selected)))
        self.map.terrain_source_changed.connect(self.sync_source)
        form.addRow("Источник высоты", self.source)
        load = QPushButton("Открыть GeoTIFF DEM…")
        load.clicked.connect(self.load_dem)
        form.addRow(load)
        self.shade = QCheckBox("Отмывка рельефа")
        self.shade.setChecked(True)
        form.addRow(self.shade)
        self.controls = {}
        for key, title, maximum, value in (
            ("intensity", "Интенсивность", 1, 0.35),
            ("opacity", "Непрозрачность", 1, 0.65),
            ("azimuth", "Азимут солнца", 360, 315),
            ("altitude", "Высота солнца", 90, 45),
        ):
            spin = QDoubleSpinBox()
            spin.setRange(0, maximum)
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(self.update_terrain)
            self.controls[key] = spin
            form.addRow(title, spin)
        self.analysis = QComboBox()
        for title, key in (
            ("Высота", "elevation"),
            ("Крутизна склона", "slope"),
            ("Экспозиция N/NE/E/SE/S/SW/W/NW", "aspect"),
            ("Склоны 30–45° (фильтр)", "slope-filter"),
        ):
            self.analysis.addItem(title, key)
        form.addRow("Анализ рельефа", self.analysis)
        derive = QPushButton("Добавить слой анализа")
        derive.clicked.connect(self.derive)
        form.addRow(derive)
        note = QLabel(
            "30–45° — геометрический фильтр склона, не вероятность лавины. Экспозиция отсчитывается по часовой стрелке от севера."
        )
        note.setWordWrap(True)
        form.addRow(note)
        layout.addLayout(form)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["GIS / TERRAIN", "Источник"])
        self.tree.itemChanged.connect(self.visibility)
        layout.addWidget(self.tree)
        remove = QPushButton("Удалить выбранный GIS-слой")
        remove.clicked.connect(self.remove)
        layout.addWidget(remove)
        self.source.currentIndexChanged.connect(self.select_source)
        self.shade.toggled.connect(self.update_terrain)

    def refresh_providers(self):
        for provider in self.map.registry.providers.values():
            if provider.type == "raster-dem" and self.source.findData(provider.id) < 0:
                self.source.addItem(provider.name, provider.id)

    def update_terrain(self):
        self.map.send(
            "terrain",
            source=self.map.terrain.descriptor(self.map.service.base_url),
            hill={
                "enabled": self.shade.isChecked(),
                **{k: v.value() for k, v in self.controls.items()},
            },
        )
        self.window.layer_manager.terrain_name = self.source.currentText()
        self.window.layer_manager.refresh(self.window.layers.layers)

    def select_source(self):
        try:
            self.map.select_terrain(self.source.currentData(), persist=True)
            self.update_terrain()
        except ValueError as exc:
            self.window.statusBar().showMessage(str(exc), 15000)

    def sync_source(self, key):
        with QSignalBlocker(self.source):
            self.source.setCurrentIndex(max(0, self.source.findData(key)))
        self.window.layer_manager.terrain_name = self.source.currentText()
        self.window.layer_manager.refresh(self.window.layers.layers)

    def load_dem(self):
        path, _ = QFileDialog.getOpenFileName(self, "Локальный DEM", "", "GeoTIFF (*.tif *.tiff)")
        if path:
            self.window._run_job(
                Worker(self.map.terrain.load_geotiff, path),
                lambda _: (self.source.setCurrentIndex(1), self.update_terrain()),
                "Чтение DEM…",
            )

    def add_item(self, name, key, source):
        item = QTreeWidgetItem([name, source])
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked)
        self.tree.addTopLevelItem(item)
        manager = self.window.layer_manager
        manager.external[key] = {
            "group": "GIS" if source in {"GIS", "GeoTIFF"} else "TERRAIN",
            "name": name,
            "visible": True,
        }
        manager.refresh(self.window.layers.layers)

    def visibility(self, item):
        key = item.data(0, Qt.ItemDataRole.UserRole)
        visible = item.checkState(0) == Qt.CheckState.Checked
        manager = self.window.layer_manager
        if key in manager.external:
            manager.external[key]["visible"] = visible
            manager.refresh(self.window.layers.layers)
        self.map.send(
            "visibility",
            id=key,
            visible=visible,
        )

    def sync_item(self, key, visible=None):
        with QSignalBlocker(self.tree):
            for index in range(self.tree.topLevelItemCount()):
                item = self.tree.topLevelItem(index)
                if item.data(0, Qt.ItemDataRole.UserRole) == key:
                    if visible is None:
                        self.tree.takeTopLevelItem(index)
                    else:
                        item.setCheckState(0, Qt.CheckState.Checked if visible else Qt.CheckState.Unchecked)
                    break

    def remove(self):
        if item := self.tree.currentItem():
            key = item.data(0, Qt.ItemDataRole.UserRole)
            self.map.send("removeOverlay", id=key)
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
            self.window.layer_manager.external.pop(key, None)
            self.window.layer_manager.refresh(self.window.layers.layers)

    def derive(self):
        source = self.map.terrain.active
        if source is None:
            self.window.statusBar().showMessage(
                "Для анализа нужен модельный или локальный DEM", 10000
            )
            return
        key = self.analysis.currentData()
        name = self.analysis.currentText()

        def prepare():
            slope, aspect, _, _ = terrain_derivatives(source.grid, source.values)
            values = {
                "elevation": source.values,
                "slope": slope,
                "aspect": aspect,
                "slope-filter": np.where((slope >= 30) & (slope <= 45), slope, np.nan),
            }[key]
            layer = Layer(
                name,
                units="m" if key == "elevation" else "°",
                opacity=0.75,
                colormap="twilight"
                if key == "aspect"
                else "terrain"
                if key == "elevation"
                else "magma",
                group="TERRAIN",
            )
            if key == "aspect":
                layer = replace(layer, automatic_range=False, minimum=0, maximum=360)
            return scalar_descriptor(self.map.service, source.grid, source.geometry, values, layer)

        def ready(descriptor):
            self.map.send("extraScalar", layer=descriptor)
            self.add_item(name, "extra-" + descriptor["id"], source.name)

        self.window._run_job(Worker(prepare), ready, "Вычисление производных рельефа…")


def install_gis_controls(window):
    window.layer_manager.external_removed.connect(lambda key: window.map.send("removeOverlay", id=key))
    window.layer_manager.external_visibility.connect(
        lambda key, visible: window.map.send("visibility", id=key, visible=visible)
    )

    def basemap_name():
        window.layer_manager.basemap_name = window.map.basemap.currentText()
        window.layer_manager.refresh(window.layers.layers)

    window.map.basemap.currentIndexChanged.connect(basemap_name)
    menu = window.menuBar().addMenu("Карта")
    basemap_menu = menu.addMenu("Подложка")
    for provider in window.map.registry.providers.values():
        if provider.type != "raster-dem":
            basemap_menu.addAction(
                window._action(
                    provider.name,
                    lambda checked=False, key=provider.id: window.map.basemap.setCurrentIndex(
                        window.map.basemap.findData(key)
                    ),
                )
            )
    menu.addAction(window._action("2D", lambda: window.map.set_mode(False)))
    menu.addAction(window._action("3D", lambda: window.map.set_mode(True)))
    menu.addAction(window._action("Копировать карту (PNG)", lambda: window.map.export_png()))
    controls = TerrainControls(window)
    window.layer_manager.external_visibility.connect(controls.sync_item)
    window.layer_manager.external_removed.connect(controls.sync_item)
    window.terrain_controls = controls
    dock = QDockWidget("Рельеф и GIS", window)
    dock.setObjectName("gisTerrainDock")
    dock.setWidget(controls)
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    window.tabifyDockWidget(window.properties_dock, dock)
    window.docks.append(dock)
    dock.hide()
    menu.addAction(dock.toggleViewAction())
    window.panels_menu.addAction(dock.toggleViewAction())

    def providers():
        dialog = ProviderDialog(window.map.registry, window)
        if dialog.exec():
            current = window.map.basemap.currentData()
            window.map.basemap.blockSignals(True)
            window.map.basemap.clear()
            for provider in window.map.registry.providers.values():
                if provider.type != "raster-dem":
                    window.map.basemap.addItem(provider.name, provider.id)
            window.map.basemap.setCurrentIndex(max(0, window.map.basemap.findData(current)))
            window.map.basemap.blockSignals(False)
            window.map._basemap_changed()
            controls.refresh_providers()

    settings = window.menuBar().addMenu("Настройки")
    settings.addMenu("Карты").addAction(window._action("Провайдеры…", providers))
    from avalanche_view.ui.localization import translate_window

    languages = settings.addMenu("Язык / Language")
    for label, language in (("Русский", "ru"), ("English", "en")):
        languages.addAction(
            window._action(
                label, lambda checked=False, lang=language: translate_window(window, lang)
            )
        )
    translate_window(window, window.settings.value("language", "ru"))

    def import_gis():
        path, _ = QFileDialog.getOpenFileName(
            window, "Добавить GIS-слой", "", "GIS (*.geojson *.json *.shp *.gpkg *.tif *.tiff)"
        )
        if not path:
            return
        if Path(path).suffix.lower() in {".tif", ".tiff"}:
            # Single-band scientific GeoTIFF is imported as a georeferenced raster field.
            def raster():
                from avalanche_view.gis.terrain import TerrainService

                source = TerrainService().load_geotiff(path)
                layer = Layer(Path(path).stem, opacity=0.75, group="GIS")
                return scalar_descriptor(
                    window.map.service, source.grid, source.geometry, source.values, layer
                )

            def raster_ready(data):
                window.map.send("extraScalar", layer=data)
                controls.add_item(Path(path).name, "extra-" + data["id"], "GeoTIFF")

            window._run_job(Worker(raster), raster_ready, "Чтение GeoTIFF…")
        else:

            def vector():
                import geopandas as gpd

                data = gpd.read_file(path)
                if data.crs is None:
                    raise ValueError("У GIS-слоя не указан CRS")
                data = data.to_crs(4326)
                if not data.geometry.is_valid.all():
                    raise ValueError("GIS-слой содержит некорректную геометрию")
                return json_asset(
                    window.map.service, json.loads(data.to_json(drop_id=True, na="null"))
                )

            def vector_ready(url):
                key = "gis-" + uuid4().hex
                window.map.send("overlay", id=key, url=url)
                controls.add_item(Path(path).name, key, "GIS")

            window._run_job(Worker(vector), vector_ready, "Чтение GIS-слоя…")
        dock.show()

    menu.addAction(window._action("Добавить GIS-слой…", import_gis))
