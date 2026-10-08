from dataclasses import dataclass, field
from enum import StrEnum
from uuid import uuid4


class RenderMode(StrEnum):
    HEATMAP = "Heatmap"
    FILLED_CONTOURS = "Filled contours"
    CONTOUR_LINES = "Contour lines"
    WIND_VECTORS = "Wind vectors"
    WIND_BARBS = "Wind barbs"
    HILLSHADE = "Hillshade"
    CATEGORIES = "Categorical classes"
    NATIVE_GRID = "Native grid"
    FILL_CONTOURS = "Fill and contours"
    STREAMLINES = "Streamlines"
    WIND_SPEED_ARROWS = "Wind speed and arrows"
    WIND_SPEED_BARBS = "Wind speed and barbs"


@dataclass
class Layer:
    variable: str
    name: str = ""
    units: str = ""
    visible: bool = True
    opacity: float = 1.0
    mode: RenderMode | str = RenderMode.HEATMAP
    colormap: str = "viridis"
    minimum: float = 0.0
    maximum: float = 1.0
    automatic_range: bool = True
    levels: int = 20
    smooth: bool = False
    show_colorbar: bool = True
    level: int = 0
    vector_stride: int = 5
    auto_density: bool = True
    cell_edges: bool = False
    contour_interval: float = 0.0
    contour_color: str = "#263449"
    contour_by_value: bool = False
    contour_width: float = 1.4
    contour_labels: bool = True
    label_format: str = ".1f"
    group: str = "MODEL"
    id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.variable
        self.validate()

    def validate(self) -> None:
        import math

        from matplotlib import colormaps
        from matplotlib.colors import is_color_like

        from avalanche_view.data.snowpack import is_categorical_variable

        if is_categorical_variable(self.variable):
            self.mode = RenderMode.CATEGORIES
            self.smooth = False
            self.colormap = "tab20"

        if not self.variable:
            raise ValueError("Choose a variable")
        if not math.isfinite(self.opacity) or not 0 <= self.opacity <= 1:
            raise ValueError("Opacity must be between 0 and 1")
        if not all(math.isfinite(v) for v in (self.minimum, self.maximum)):
            raise ValueError("Range must contain finite numbers")
        if not self.automatic_range and self.minimum >= self.maximum:
            raise ValueError("Minimum must be less than maximum")
        if self.levels < 2 or self.level < 0 or self.vector_stride < 1:
            raise ValueError("Invalid contour count, level or vector spacing")
        if self.colormap not in colormaps:
            raise ValueError(f"Unknown colormap: {self.colormap}")
        if self.contour_interval < 0 or not 0.1 <= self.contour_width <= 20:
            raise ValueError("Некорректный интервал или толщина изолиний")
        if not is_color_like(self.contour_color):
            raise ValueError("Укажите цвет изолиний, например #263449")
        try:
            format(1.25, self.label_format)
        except (ValueError, TypeError) as exc:
            raise ValueError("Неверный формат подписи, например .1f") from exc
        if not isinstance(self.mode, str) or not self.mode.strip():
            raise ValueError("Render mode must have a name")
        # External renderers may introduce modes beyond the built-in enum.
        if self.mode in {mode.value for mode in RenderMode}:
            self.mode = RenderMode(self.mode)


class LayerCollection:
    """Order is top-to-bottom, like the visible layer manager."""

    def __init__(self) -> None:
        self.layers: list[Layer] = []

    def add(self, layer: Layer) -> None:
        self.layers.insert(0, layer)

    def get(self, layer_id: str) -> Layer:
        return next(layer for layer in self.layers if layer.id == layer_id)

    def remove(self, layer_id: str) -> None:
        self.layers = [layer for layer in self.layers if layer.id != layer_id]

    def move(self, layer_id: str, delta: int) -> None:
        current = next(i for i, layer in enumerate(self.layers) if layer.id == layer_id)
        target = max(0, min(len(self.layers) - 1, current + delta))
        self.layers.insert(target, self.layers.pop(current))
