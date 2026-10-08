from dataclasses import replace

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from avalanche_view.data.snowpack import SNOWPACK_VERTICAL_DIM, is_categorical_variable
from avalanche_view.visualization.colormaps import COLORMAPS
from avalanche_view.visualization.layers import RenderMode


class LayerProperties(QWidget):
    layer_changed = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layer = None
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(140)
        self._timer.timeout.connect(self._apply)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        self.variable = QLabel("Select a layer to edit its appearance")
        self.variable.setWordWrap(True)
        self.variable.setObjectName("datasetName")
        layout.addWidget(self.variable)
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setContentsMargins(0, 10, 0, 0)
        form.setVerticalSpacing(10)
        self.name = QLineEdit()
        self.units = QLabel()
        self.mode = QComboBox()
        self.mode.addItems([mode.value for mode in RenderMode])
        self.colormap = QComboBox()
        self.colormap.addItems(COLORMAPS)
        self.automatic = QCheckBox("Automatic range per frame")
        self.minimum = QDoubleSpinBox()
        self.maximum = QDoubleSpinBox()
        for control in (self.minimum, self.maximum):
            control.setRange(-1e15, 1e15)
            control.setDecimals(4)
            control.setKeyboardTracking(False)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.levels = QSpinBox()
        self.levels.setRange(2, 100)
        self.levels.setKeyboardTracking(False)
        self.vertical_level = QSpinBox()
        self.vertical_level.setKeyboardTracking(False)
        self.stride = QSpinBox()
        self.stride.setRange(1, 100)
        self.stride.setKeyboardTracking(False)
        self.smooth = QCheckBox("Smooth display (3×3 filter)")
        self.smooth.setToolTip("Only the rendered field is smoothed; point values remain original")
        self.colorbar = QCheckBox("Show colorbar")
        self.auto_density = QCheckBox("Автоматическая плотность ветра")
        self.cell_edges = QCheckBox("Границы исходных ячеек")
        self.contour_interval = QDoubleSpinBox()
        self.contour_interval.setRange(0, 1e9)
        self.contour_interval.setDecimals(4)
        self.contour_interval.setSpecialValueText("По числу уровней")
        self.contour_color = QLineEdit()
        self.contour_by_value = QCheckBox("Цвет изолиний по значению")
        self.contour_width = QDoubleSpinBox()
        self.contour_width.setRange(.1, 20)
        self.contour_labels = QCheckBox("Подписи изолиний")
        self.label_format = QLineEdit()
        self.capability_hint = QLabel()
        self.capability_hint.setWordWrap(True)
        for title, control in (
            ("Layer name", self.name),
            ("Variable units", self.units),
            ("Render mode", self.mode),
            ("Colormap", self.colormap),
            ("", self.automatic),
            ("Minimum", self.minimum),
            ("Maximum", self.maximum),
            ("Opacity", self.opacity),
            ("Contour levels", self.levels),
            ("Vertical index", self.vertical_level),
            ("Vector spacing", self.stride),
            ("", self.smooth),
            ("", self.colorbar),
            ("", self.auto_density), ("", self.cell_edges),
            ("Интервал изолиний", self.contour_interval),
            ("Цвет линии", self.contour_color), ("", self.contour_by_value),
            ("Толщина линии", self.contour_width), ("", self.contour_labels),
            ("Формат подписи", self.label_format), ("", self.capability_hint),
        ):
            form.addRow(title, control)
        layout.addWidget(self.form_widget)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setObjectName("error")
        layout.addWidget(self.error)
        hint = QLabel("Changes apply automatically.\nUse a fixed range to compare timesteps.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.form_widget.setEnabled(False)
        self.name.editingFinished.connect(self._schedule)
        for control in (self.mode, self.colormap):
            control.currentTextChanged.connect(self._schedule)
        for control in (
            self.minimum,
            self.maximum,
            self.opacity,
            self.levels,
            self.vertical_level,
            self.stride,
            self.contour_interval, self.contour_width,
        ):
            control.valueChanged.connect(self._schedule)
        for control in (self.automatic, self.smooth, self.colorbar, self.auto_density,
                        self.cell_edges, self.contour_by_value, self.contour_labels):
            control.toggled.connect(self._schedule)
        self.contour_color.editingFinished.connect(self._schedule)
        self.label_format.editingFinished.connect(self._schedule)

    def set_layer(self, layer, vertical_dimensions=None) -> None:
        self._timer.stop()
        self._loading = True
        self._layer = layer
        self.error.clear()
        self.form_widget.setEnabled(layer is not None)
        if layer is None:
            self.variable.setText("Select a layer to edit its appearance")
            self._loading = False
            return
        self.variable.setText(layer.variable)
        self.name.setText(layer.name)
        self.units.setText(layer.units or "Unspecified")
        index = self.mode.findData(str(layer.mode))
        if index < 0:
            index = self.mode.findText(str(layer.mode))
        if index < 0:
            self.mode.addItem(str(layer.mode))
            index = self.mode.count() - 1
        self.mode.setCurrentIndex(index)
        if self.colormap.findText(layer.colormap) < 0:
            self.colormap.addItem(layer.colormap)
        self.colormap.setCurrentText(layer.colormap)
        self.automatic.setChecked(layer.automatic_range)
        self.minimum.setValue(layer.minimum)
        self.maximum.setValue(layer.maximum)
        self.minimum.setEnabled(not layer.automatic_range)
        self.maximum.setEnabled(not layer.automatic_range)
        self.opacity.setValue(round(layer.opacity * 100))
        self.levels.setValue(layer.levels)
        dimensions = vertical_dimensions or {}
        sizes = [size for size in dimensions.values() if size > 1]
        self.vertical_level.setRange(0, min(sizes) - 1 if sizes else 0)
        self.vertical_level.setValue(layer.level)
        self.vertical_level.setEnabled(bool(sizes))
        self.vertical_level.setToolTip(
            ", ".join(f"{name}: {size} indices" for name, size in dimensions.items())
            or "Surface variable"
        )
        snowpack = SNOWPACK_VERTICAL_DIM in dimensions
        self.vertical_level.setPrefix("Snowpack layer " if snowpack else "")
        if snowpack:
            self.vertical_level.setEnabled(True)
            self.vertical_level.setToolTip(
                "Snowpack layer (zero-based). Cells with SN_NLAYERS <= this index are inactive/NaN; active counts vary across the domain."
            )
        self.stride.setValue(layer.vector_stride)
        self.smooth.setChecked(layer.smooth)
        categorical = is_categorical_variable(layer.variable)
        self.smooth.setEnabled(not categorical)
        self.mode.setEnabled(not categorical)
        self.colormap.setEnabled(not categorical)
        self.colorbar.setChecked(layer.show_colorbar)
        for key in ("auto_density", "cell_edges", "contour_by_value", "contour_labels"):
            getattr(self, key).setChecked(getattr(layer, key))
        for key in ("contour_interval", "contour_width"):
            getattr(self, key).setValue(getattr(layer, key))
        for key in ("contour_color", "label_format"):
            getattr(self, key).setText(getattr(layer, key))
        self._loading = False

    def set_capabilities(self, capabilities):
        for index in range(self.mode.count()):
            reason = capabilities.reason(self.mode.itemData(index) or self.mode.itemText(index))
            item = self.mode.model().item(index)
            item.setEnabled(not reason)
            item.setToolTip(reason)
        text = "2D · наложение на рельеф"
        if capabilities.geometry_kind == "elevation":
            text = "2D · источник 3D-рельефа"
        elif capabilities.requiresVerticalLevel:
            text += " · горизонтальный срез выбранного уровня (не объёмное 3D)"
        if capabilities.geometry_kind == "snowpack_slice":
            text += " · неактивные элементы по SN_NLAYERS скрыты в каждой ячейке"
        self.capability_hint.setText(text)

    def _schedule(self, *args) -> None:
        if not self._loading and self._layer:
            self.minimum.setEnabled(not self.automatic.isChecked())
            self.maximum.setEnabled(not self.automatic.isChecked())
            self.opacity.setToolTip(f"{self.opacity.value()}%")
            self._timer.start()

    def _apply(self) -> None:
        if not self._layer:
            return
        try:
            candidate = replace(
                self._layer,
                name=self.name.text().strip() or self._layer.variable,
                mode=self.mode.currentData() or self.mode.currentText(),
                colormap=self.colormap.currentText(),
                minimum=self.minimum.value(),
                maximum=self.maximum.value(),
                opacity=self.opacity.value() / 100,
                levels=self.levels.value(),
                automatic_range=self.automatic.isChecked(),
                level=self.vertical_level.value(),
                vector_stride=self.stride.value(),
                smooth=self.smooth.isChecked(),
                show_colorbar=self.colorbar.isChecked(),
                auto_density=self.auto_density.isChecked(), cell_edges=self.cell_edges.isChecked(),
                contour_interval=self.contour_interval.value(), contour_width=self.contour_width.value(),
                contour_color=self.contour_color.text(), contour_by_value=self.contour_by_value.isChecked(),
                contour_labels=self.contour_labels.isChecked(), label_format=self.label_format.text(),
            )
            candidate.validate()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        self._layer = candidate
        self.layer_changed.emit(candidate)
