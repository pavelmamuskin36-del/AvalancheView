from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class PointInspector(QWidget):
    series_requested = pyqtSignal(str)
    profile_requested = pyqtSignal(str)
    snowpack_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.point = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.coordinates = QLabel("Click on the map to inspect a grid cell")
        self.coordinates.setWordWrap(True)
        self.coordinates.setObjectName("datasetName")
        layout.addWidget(self.coordinates)
        tabs = QTabWidget()
        values_tab = QWidget()
        values_layout = QVBoxLayout(values_tab)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Variable", "Value", "Units"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 135)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 55)
        self.table.horizontalHeader().setMinimumSectionSize(35)
        values_layout.addWidget(self.table)
        tabs.addTab(values_tab, "Point values")
        series_tab = QWidget()
        series_layout = QVBoxLayout(series_tab)
        hint = QLabel("Plot the full time series at the selected grid cell.")
        hint.setWordWrap(True)
        series_layout.addWidget(hint)
        self.variable = QComboBox()
        series_layout.addWidget(self.variable)
        self.series_button = QPushButton("Временной ряд")
        self.series_button.setEnabled(False)
        self.series_button.clicked.connect(
            lambda: self.series_requested.emit(self.variable.currentText())
        )
        series_layout.addWidget(self.series_button)
        series_layout.addStretch()
        tabs.addTab(series_tab, "Временной ряд")
        profile_tab = QWidget()
        profile_layout = QVBoxLayout(profile_tab)
        profile_hint = QLabel(
            "Показывает все вертикальные уровни выбранной переменной в отмеченной ячейке."
        )
        profile_hint.setWordWrap(True)
        profile_layout.addWidget(profile_hint)
        self.profile_variable = QComboBox()
        profile_layout.addWidget(self.profile_variable)
        self.profile_button = QPushButton("Построить вертикальный разрез")
        self.profile_button.setEnabled(False)
        self.profile_button.clicked.connect(
            lambda: self.profile_requested.emit(self.profile_variable.currentText())
        )
        profile_layout.addWidget(self.profile_button)
        profile_layout.addStretch()
        self.profile_tab_index = tabs.addTab(profile_tab, "Вертикальный разрез")
        tabs.setTabEnabled(self.profile_tab_index, False)
        self.tabs = tabs
        layout.addWidget(tabs, 1)
        self.snow_label = QLabel("Снежный покров")
        layout.addWidget(self.snow_label)
        self.snow_table = QTableWidget(0, 3)
        self.snow_table.setHorizontalHeaderLabels(["Variable", "Value", "Units"])
        self.snow_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.snow_table.verticalHeader().hide()
        self.snow_table.horizontalHeader().setStretchLastSection(True)
        self.snow_table.setMaximumHeight(185)
        layout.addWidget(self.snow_table)
        self.snow_status = QLabel()
        self.snow_status.setWordWrap(True)
        layout.addWidget(self.snow_status)
        self.snow_button = QPushButton("Профиль SNOWPACK")
        self.snow_button.setEnabled(False)
        self.snow_button.clicked.connect(self.snowpack_requested.emit)
        layout.addWidget(self.snow_button)
        self.set_snow_values([], False, available=False)

    def set_snow_values(self, values, active, message="", available=True):
        """Keep Snowpack bulk properties separate from the existing visible-layer values."""
        for widget in (self.snow_label, self.snow_table, self.snow_button, self.snow_status):
            widget.setVisible(available)
        self.snow_table.setRowCount(len(values))
        for row, entries in enumerate(values):
            for column, entry in enumerate(entries):
                self.snow_table.setItem(row, column, QTableWidgetItem(str(entry)))
        self.snow_status.setText(message)
        self.snow_button.setEnabled(active and self.point is not None)

    def set_variables(self, names: list[str], vertical_names: list[str] | None = None) -> None:
        selected = self.variable.currentText()
        self.variable.clear()
        self.variable.addItems(names)
        self.variable.setCurrentText(selected)
        self.series_button.setEnabled(self.point is not None and bool(names))
        selected_profile = self.profile_variable.currentText()
        self.profile_variable.clear()
        self.profile_variable.addItems(vertical_names or [])
        self.profile_variable.setCurrentText(selected_profile)
        available = self.profile_variable.count() > 0
        self.tabs.setTabEnabled(self.profile_tab_index, available)
        self.profile_button.setEnabled(self.point is not None and available)

    def update_values(self, point, grid, values) -> None:
        self.point = point
        row, column = point
        x, y = grid.x[row, column], grid.y[row, column]
        label = (
            f"Latitude {y:.5f}°\nLongitude {x:.5f}°" if grid.geographic else f"Y {y:.5f}\nX {x:.5f}"
        )
        self.coordinates.setText(f"{label}\nGrid X {column} · Y {row} (zero-based)")
        self.table.setRowCount(len(values))
        for index, (name, value, units) in enumerate(values):
            for column_index, text in enumerate((name, value, units)):
                self.table.setItem(index, column_index, QTableWidgetItem(text))
        self.series_button.setEnabled(self.variable.count() > 0)
        self.profile_button.setEnabled(self.profile_variable.count() > 0)

    def clear(self) -> None:
        self.point = None
        self.coordinates.setText("Click on the map to inspect a grid cell")
        self.table.setRowCount(0)
        self.series_button.setEnabled(False)
        self.profile_button.setEnabled(False)
        self.set_snow_values([], False, available=False)
