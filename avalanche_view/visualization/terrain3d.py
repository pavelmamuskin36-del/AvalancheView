from importlib.util import find_spec

import numpy as np
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

TERRAIN3D_AVAILABLE = all(find_spec(name) is not None for name in ("pyvista", "pyvistaqt", "vtk"))


class Terrain3DDialog(QDialog):
    def __init__(self, grid, elevation, values=None, layer=None, parent=None) -> None:
        super().__init__(parent)
        # No VTK imports during ordinary 2D startup.
        import pyvista as pv
        from pyvistaqt import QtInteractor

        self.setWindowTitle("AvalancheView • Experimental 3D terrain")
        self.resize(1050, 750)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Experimental terrain • distances and elevation in metres"))
        self.plotter = QtInteractor(self)
        layout.addWidget(self.plotter.interactor)
        if not grid.geographic:
            raise ValueError(
                "3D terrain requires latitude/longitude coordinates for metric conversion"
            )
        x, y = grid.metric_xy()
        finite = np.isfinite(elevation)
        if not finite.any():
            raise ValueError("Terrain contains no finite elevation")
        surface = pv.StructuredGrid(x, y, np.where(finite, elevation, np.nanmedian(elevation)))
        if values is not None:
            surface["field"] = values.ravel(order="F")
            limits = None if layer.automatic_range else (layer.minimum, layer.maximum)
            self.plotter.add_mesh(
                surface,
                scalars="field",
                cmap=layer.colormap,
                clim=limits,
                opacity=layer.opacity,
                scalar_bar_args={"title": f"{layer.name} [{layer.units}]"},
            )
        else:
            surface["Elevation (m)"] = elevation.ravel(order="F")
            self.plotter.add_mesh(surface, scalars="Elevation (m)", cmap="terrain")
        self.plotter.show_axes()
        self.plotter.view_isometric()
        self.plotter.reset_camera()

    def closeEvent(self, event) -> None:
        self.plotter.close()
        super().closeEvent(event)
