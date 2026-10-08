import numpy as np
import pytest

from avalanche_view.visualization.layers import Layer, LayerCollection
from avalanche_view.visualization.renderer import RendererRegistry, field_range, smooth_field


@pytest.mark.parametrize(
    "options",
    [
        {"opacity": -0.1},
        {"opacity": 1.1},
        {"opacity": float("nan")},
        {"minimum": 5, "maximum": 2, "automatic_range": False},
        {"minimum": float("inf")},
        {"colormap": "unknown"},
        {"levels": 1},
        {"level": -1},
    ],
)
def test_invalid_configuration(options):
    with pytest.raises(ValueError):
        Layer("T2", **options)


def test_layer_order_and_visibility():
    collection = LayerCollection()
    temperature, snow = Layer("T2"), Layer("SNOWH", opacity=0.5)
    collection.add(temperature)
    collection.add(snow)
    assert collection.layers == [snow, temperature]
    collection.move(snow.id, 1)
    assert collection.layers == [temperature, snow]
    collection.get(snow.id).visible = False
    assert not snow.visible
    collection.remove(temperature.id)
    assert collection.layers == [snow]


def test_normalization_handles_constant_and_nan():
    low, high = field_range(np.array([[np.nan, 7, 7]]), Layer("test"))
    assert low < 7 < high
    with pytest.raises(ValueError, match="no finite"):
        field_range(np.full((3, 3), np.nan), Layer("test"))
    assert field_range(
        np.array([[1, 2]]), Layer("test", automatic_range=False, minimum=0, maximum=10)
    ) == (0, 10)
    values = np.ones((5, 5))
    values[2, 2] = np.nan
    np.testing.assert_array_equal(smooth_field(values), np.ones((5, 5)))


def test_custom_renderer_registration():
    renderer = RendererRegistry()
    seen = []

    def points(axes, grid, values, layer, zorder, transform):
        seen.append((layer.mode, zorder))
        return "point artist"

    renderer.register("Points", points)
    layer = Layer("test", mode="Points")
    assert renderer.render(None, None, np.zeros((2, 2)), layer, 5) == "point artist"
    assert seen == [("Points", 5)]
