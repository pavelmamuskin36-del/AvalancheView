"""Read-only Snowpack profile plot/table backed by a detached point snapshot."""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from avalanche_view.data.snowpack import is_categorical_variable


class SnowpackProfileDialog(QDialog):
    """Switch properties without selecting the cell again; plot only active levels."""

    def __init__(self, profile, variable="SNPACK_T", language="ru", parent=None):
        super().__init__(parent)
        self.profile = profile
        self.language = language
        self.setWindowTitle(self.tr_text("Профиль снега · SNOWPACK", "Snow profile · SNOWPACK"))
        self.resize(1120, 740)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        x, y = profile.xy
        location = (
            f"Longitude {x:.5f}° · Latitude {y:.5f}°"
            if profile.geographic
            else f"X {x:.5f} · Y {y:.5f}"
        )
        bulk = " · ".join(
            f"{name} = {value:.5g} {profile.metadata.get(name, ('', 'kg m-3'))[1]}"
            for name, value in profile.summary.items()
        )
        self.summary.setText(
            f"{location} · Grid X {profile.point[1]} / Y {profile.point[0]}\n"
            f"{profile.timestamp}\n{bulk}"
        )
        layout.addWidget(self.summary)
        self.variable = QComboBox()
        for name, (title, units) in profile.metadata.items():
            if name in profile.properties:
                self.variable.addItem(f"{name} — {title} [{units}]", name)
        selected = self.variable.findData(variable)
        self.variable.setCurrentIndex(max(selected, 0))
        self.variable.setEnabled(profile.count > 0)
        layout.addWidget(self.variable)
        self.status = QLabel()
        self.status.setWordWrap(True)
        if not profile.count:
            self.status.setText(
                self.tr_text(
                    "Для выбранной точки и времени активный профиль SNOWPACK отсутствует. "
                    "Layer diagnostics для этого history record не записаны/не активны.",
                    "No active SNOWPACK profile at this point/time. Layer diagnostics for this history record are not recorded/active.",
                )
                + ("\n" + "\n".join(profile.warnings) if profile.warnings else "")
            )
        else:
            self.status.setText("\n".join(profile.warnings))
        layout.addWidget(self.status)
        splitter = QSplitter()
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        self.canvas = FigureCanvasQTAgg(Figure(layout="constrained"))
        self.axes = self.canvas.figure.add_subplot(111)
        plot_layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        plot_layout.addWidget(self.canvas)
        splitter.addWidget(plot_widget)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        columns = [
            ("Index", None),
            ("Depth center [m]", "depth"),
            ("Thickness [m]", "SN_THICK"),
            ("Temperature [K]", "SNPACK_T"),
            ("Ice fraction", "SN_VOLI"),
            ("Water fraction", "SN_VOLW"),
            ("Air fraction", "SN_VOLV"),
            ("Ice density [kg/m³]", "Snow Density"),
            ("Bulk density [kg/m³]", "Layer bulk density"),
            ("Mass [kg/m²]", "Layer mass per unit area"),
            ("RG", "SN_RG"),
            ("RB", "SN_RB"),
            ("DD", "SN_DD"),
            ("SP", "SN_SP"),
            ("Grain type", "SN_GRAINTYPE"),
            ("Deposition Julian (raw)", "SN_DEPD"),
            ("MK", "SN_MK"),
        ]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels([label for label, _ in columns])
        self.table.setRowCount(profile.count)
        for row in range(profile.count):
            for column, (_, name) in enumerate(columns):
                values = profile.center_depth if name == "depth" else profile.properties.get(name)
                value = values[row] if values is not None and row < len(values) else np.nan
                text = str(row) if name is None else (f"{value:.8g}" if np.isfinite(value) else "—")
                if is_categorical_variable(name) and np.isfinite(value):
                    text = str(int(value))
                item = QTableWidgetItem(text)
                if name == "SN_GRAINTYPE" and np.isfinite(value):
                    item.setToolTip(f"Grain type code {int(value)}")
                elif name in profile.metadata:
                    item.setToolTip(" · ".join(profile.metadata[name]))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        splitter.addWidget(self.table)
        splitter.setSizes([480, 600])
        layout.addWidget(splitter, 1)
        self.layer_diagnostic = QLabel()
        self.layer_diagnostic.setWordWrap(True)
        layout.addWidget(self.layer_diagnostic)
        self.table.currentCellChanged.connect(self._inspect_layer)
        self.variable.currentIndexChanged.connect(self._plot)
        if profile.count:
            self.table.setCurrentCell(0, 0)
        self._plot()

    def tr_text(self, russian, english):
        return russian if self.language == "ru" else english

    def _plot(self, *args):
        self.axes.clear()
        profile = self.profile
        name = self.variable.currentData()
        if not profile.count or name not in profile.properties:
            self.canvas.draw_idle()
            return
        values = profile.properties[name]
        depth = profile.center_depth
        y = depth if depth is not None else np.arange(len(values))
        if is_categorical_variable(name):
            # Scatter and integer ticks express exact codes, with no connecting interpolation.
            self.axes.scatter(values, y, c="#087f8c")
            codes = np.unique(values[np.isfinite(values)])
            self.axes.set_xticks(codes, [str(int(code)) for code in codes])
        else:
            self.axes.plot(values, y, color="#087f8c", marker="o", markersize=4)
        title, units = profile.metadata[name]
        self.axes.set_xlabel(f"{title}, {units}" if units else title)
        self.axes.set_ylabel(
            self.tr_text("Глубина от поверхности, м", "Depth from surface, m")
            if depth is not None
            else self.tr_text("Индекс элемента", "Element index")
        )
        if depth is not None:
            self.axes.set_ylim(float(profile.bottom_depth[-1]), 0)
        else:
            self.axes.set_ylim(max(len(values) - 0.5, 0.5), -0.5)
            self.axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        self.axes.grid(alpha=0.25)
        self.canvas.draw_idle()

    def _inspect_layer(self, row, *args):
        if row < 0:
            return
        properties = self.profile.properties
        if {"SN_VOLI", "SN_VOLW", "SN_VOLV"} <= properties.keys():
            total = sum(properties[name][row] for name in ("SN_VOLI", "SN_VOLW", "SN_VOLV"))
            valid = np.isfinite(total) and abs(total - 1) <= 0.02
            self.layer_diagnostic.setText(
                f"Layer {row}: SN_VOLI + SN_VOLW + SN_VOLV = {total:.5g} · "
                + (
                    "OK"
                    if valid
                    else self.tr_text(
                        "Предупреждение: доли не согласованы", "Warning: inconsistent fractions"
                    )
                )
            )
