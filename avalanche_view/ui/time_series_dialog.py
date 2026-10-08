import numpy as np
from matplotlib import dates as mdates
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from PyQt6.QtWidgets import QDialog, QVBoxLayout

from avalanche_view.data.snowpack import is_categorical_variable
from avalanche_view.data.time_axis import parse_datetime


class TimeSeriesDialog(QDialog):
    def __init__(self, variable, timestamps, values, units, point, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"AvalancheView • {variable} • Графики")
        self.resize(880, 520)
        figure = Figure(figsize=(8, 4), layout="constrained", facecolor="#f8fafc")
        self.canvas = FigureCanvasQTAgg(figure)
        layout = QVBoxLayout(self)
        layout.addWidget(NavigationToolbar2QT(self.canvas, self))
        layout.addWidget(self.canvas)
        axes = figure.add_subplot(111)
        dates = [parse_datetime(timestamp) for timestamp in timestamps]
        dated = all(date is not None for date in dates)
        categorical = is_categorical_variable(variable)
        axes.plot(
            dates if dated else range(len(values)),
            values,
            color="#087f8c",
            linewidth=2,
            marker="o",
            markersize=4,
            linestyle="none" if categorical else "-",
        )
        if categorical:
            codes = np.unique(np.asarray(values)[np.isfinite(values)])
            axes.set_yticks(codes, [str(int(code)) for code in codes])
        axes.set_title(f"{variable} · Grid X {point[1]} / Y {point[0]}")
        axes.set_ylabel(units or "Value")
        axes.set_xlabel("Время (UTC)")
        if dated:
            locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
            axes.xaxis.set_major_locator(locator)
            axes.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
        else:
            axes.xaxis.set_major_locator(MaxNLocator(nbins=6, integer=True))
        indices = sorted(
            {
                round(i * (len(timestamps) - 1) / min(5, max(1, len(timestamps) - 1)))
                for i in range(min(6, len(timestamps)))
            }
        )
        if not dated:
            axes.set_xticks(
                indices, [timestamps[i] for i in indices], rotation=18, ha="right", fontsize=8
            )
        axes.grid(alpha=0.2)
        self.canvas.draw_idle()
