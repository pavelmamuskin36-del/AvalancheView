import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PyQt6.QtWidgets import QDialog, QVBoxLayout


class VerticalProfileDialog(QDialog):
    def __init__(
        self,
        variable,
        values,
        units,
        point,
        vertical_values=None,
        vertical_name="Уровень модели",
        vertical_units="",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"AvalancheView • {variable} • Вертикальный разрез")
        self.resize(720, 620)
        figure = Figure(figsize=(6, 5), layout="constrained", facecolor="#f8fafc")
        self.canvas = FigureCanvasQTAgg(figure)
        layout = QVBoxLayout(self)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        axes = figure.add_subplot(111)
        levels = (
            np.asarray(vertical_values, dtype=float)
            if vertical_values is not None
            else np.arange(len(values), dtype=float)
        )
        axes.plot(values, levels, color="#087f8c", linewidth=2.2, marker="o", markersize=4)
        axes.set_title(f"{variable} · Grid X {point[1]} / Y {point[0]}")
        axes.set_xlabel(f"{variable}, {units}" if units else variable)
        axes.set_ylabel(
            f"{vertical_name}, {vertical_units}" if vertical_units else vertical_name
        )
        if vertical_values is None:
            axes.yaxis.set_major_locator(MaxNLocator(integer=True))
        if vertical_units.lower() in {"pa", "hpa", "mbar"}:
            axes.invert_yaxis()
        axes.grid(alpha=0.25)
        self.canvas.draw_idle()
