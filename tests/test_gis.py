import io
from urllib.error import HTTPError
from urllib.request import urlopen

import numpy as np
import pytest
from PIL import Image

from avalanche_view.data.coordinates import GridCoordinates
from avalanche_view.gis.basemaps import (
    DETAILED_TERRAIN_ID,
    BasemapProvider,
    BasemapRegistry,
)
from avalanche_view.gis.capabilities import WIND_MODES, VariableCapabilities
from avalanche_view.gis.geometry import grid_geometry
from avalanche_view.gis.scientific import PreparedScene, colorize
from avalanche_view.gis.terrain import TerrainService, encode_dem, terrain_derivatives
from avalanche_view.gis.transport import AssetStore, LocalDataService
from avalanche_view.visualization.layers import Layer, RenderMode


@pytest.fixture
def service():
    result = LocalDataService(TerrainService())
    yield result
    result.close()


@pytest.mark.parametrize("mode", list(RenderMode))
def test_native_scene_modes(dataset, service, mode):
    name = (
        "Wind Speed 10m"
        if mode in WIND_MODES
        else "HGT"
        if mode == RenderMode.HILLSHADE
        else "SNOWH"
    )
    original = dataset.read(name).copy()
    layer = Layer(name, mode=mode)
    result = PreparedScene(dataset, [layer], 0, service)
    assert not result.scene["warnings"]
    descriptor = result.scene["layers"][0]
    with urlopen(descriptor["values"]) as response:
        values = np.frombuffer(response.read(), "<f8").reshape(original.shape)
    np.testing.assert_allclose(values, original, equal_nan=True)
    np.testing.assert_array_equal(dataset.read(name), original)
    with urlopen(descriptor["corners"]) as response:
        corners = np.frombuffer(response.read(), "<f8").reshape(
            original.shape[0] + 1, original.shape[1] + 1, 2
        )
    assert np.isfinite(corners).all()
    if mode in WIND_MODES:
        assert "wind" in descriptor
    if mode == RenderMode.STREAMLINES:
        with urlopen(descriptor["streamlines"]) as response:
            assert b"LineString" in response.read()


def test_capability_gating(dataset):
    snow = VariableCapabilities.detect(dataset, "SNOWH")
    assert snow.canDrapeOnTerrain and not snow.canRender3D
    assert snow.reason(RenderMode.WIND_BARBS)
    assert snow.reason(RenderMode.HILLSHADE)
    wind = VariableCapabilities.detect(dataset, "U10")
    assert wind.canVector and wind.vector_variable == "Wind Speed 10m"
    assert VariableCapabilities.detect(dataset, "HGT").canRender3D
    from types import SimpleNamespace

    without_rotation = SimpleNamespace(
        variables={k: v for k, v in dataset.variables.items() if k not in {"COSALPHA", "SINALPHA"}},
        latitude_name=dataset.latitude_name, longitude_name=dataset.longitude_name,
        vertical_dimensions=dataset.vertical_dimensions, time_count=dataset.time_count,
        metadata={**dataset.metadata, "MAP_PROJ": 1}, projection=dataset.projection,
    )
    unavailable = VariableCapabilities.detect(without_rotation, "U10")
    assert not unavailable.canVector
    assert "COSALPHA" in unavailable.reason(RenderMode.WIND_VECTORS)


def test_no_data_not_colored_or_mutated():
    values = np.array([[1.0, np.nan], [2.0, 3.0]])
    rgba, *_ = colorize(values, Layer("test"))
    assert rgba[0, 1, 3] == 0
    assert np.isnan(values[0, 1])


def test_terrain_metric_derivatives_and_encoding():
    y, x = np.mgrid[:5, :6] * 100.0
    grid = GridCoordinates(x, y, False, "x", "y")
    slope, aspect, *_ = terrain_derivatives(grid, x)
    np.testing.assert_allclose(slope, 45)
    np.testing.assert_allclose(aspect, 270)
    heights = np.array([[-250.0, 0.0, 1234.5, 5000.0]])
    rgb = np.asarray(Image.open(io.BytesIO(encode_dem(heights)))).astype(np.int64)
    decoded = -10000 + (rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]) * 0.1
    np.testing.assert_allclose(decoded, heights)


def test_model_terrain_height_and_domain(dataset, service):
    grid = dataset.coordinates()
    geometry = grid_geometry(dataset)
    service.terrain.set_model(dataset, 0, grid, geometry)
    source = service.terrain.model
    assert source.height(float(grid.x[3, 4]), float(grid.y[3, 4])) == float(
        dataset.read("HGT")[3, 4]
    )
    assert source.height(0, 0) is None
    assert np.allclose(geometry.ring[0], geometry.ring[-1])
    assert geometry.polygon().is_valid
    heights = dataset.read("HGT")
    row, column = np.unravel_index(np.nanargmax(heights), heights.shape)
    assert service.terrain.mountain_focus() == [
        float(grid.x[row, column]),
        float(grid.y[row, column]),
    ]


def test_transport_cache_and_access(service):
    key = service.store.put(b"native")
    with urlopen(service.asset_url(key)) as response:
        assert response.read() == b"native"
    with pytest.raises(HTTPError) as exc:
        urlopen(service.base_url.replace(service.token, "wrong") + "index.html")
    assert exc.value.code == 403
    with pytest.raises(HTTPError):
        urlopen(service.base_url + "../terrain.py")
    cache = AssetStore(limit=8)
    old = cache.put(b"12345")
    cache.put(b"67890")
    assert cache.size == 5
    with pytest.raises(KeyError):
        cache.get(old)


def test_provider_key_and_legal_configuration():
    registry = BasemapRegistry()
    assert "google.com" not in registry.get("satellite")["url"]
    terrain = registry.get(DETAILED_TERRAIN_ID)
    assert terrain["type"] == "raster-dem"
    assert terrain["encoding"] == "terrarium"
    assert terrain["maxZoom"] == 15
    assert "SRTM" in terrain["attribution"]
    provider = BasemapProvider(
        "custom",
        "Custom",
        url="https://example.test/{z}/{x}/{y}?key={key}",
        attribution="Example",
        requiresApiKey=True,
    )
    with pytest.raises(ValueError):
        provider.resolved()
    assert provider.resolved("a b")["url"].endswith("key=a%20b")


def test_local_dem_crs_nodata_and_height(tmp_path):
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "terrain.tif"
    values = np.arange(12, dtype="float32").reshape(3, 4)
    values[0, 0] = -9999
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=3,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(43, 43, 0.1, 0.1),
        nodata=-9999,
    ) as dst:
        dst.write(values, 1)
    source = TerrainService().load_geotiff(path)
    assert source.height(43.15, 42.85) == 5
    assert source.height(43.05, 42.95) is None
    assert np.isnan(source.values[0, 0])


def test_localized_modes_keep_identifiers(qtbot, tmp_path, dataset):
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QWidget

    from avalanche_view.ui.layer_properties import LayerProperties
    from avalanche_view.ui.localization import translate_window

    host = QWidget()
    qtbot.addWidget(host)
    host.settings = QSettings(str(tmp_path / "language.ini"), QSettings.Format.IniFormat)
    host.properties = LayerProperties(host)
    layer = Layer("SNOWH", mode=RenderMode.FILL_CONTOURS)
    host.properties.set_layer(layer)
    translate_window(host, "ru")
    assert host.properties.mode.currentText() == "Заливка + изолинии"
    with qtbot.waitSignal(host.properties.layer_changed) as result:
        host.properties._apply()
    assert result.args[0].mode == RenderMode.FILL_CONTOURS
    host.properties.set_capabilities(VariableCapabilities.detect(dataset, "SNOWH"))
    index = host.properties.mode.findData(RenderMode.WIND_BARBS.value)
    assert not host.properties.mode.model().item(index).isEnabled()
    assert host.properties.mode.model().item(index).toolTip()
    translate_window(host, "en")
    assert host.properties.mode.currentText() == RenderMode.FILL_CONTOURS.value


def test_grouped_external_layer_removal(qtbot):
    from PyQt6.QtCore import Qt

    from avalanche_view.ui.layer_manager import LayerManager

    manager = LayerManager()
    qtbot.addWidget(manager)
    manager.grouped = True
    manager.external["gis-example"] = {"group": "GIS", "name": "Zones", "visible": True}
    manager.refresh([Layer("SNOWH")])
    assert manager.tree.topLevelItemCount() == 4
    item = manager.tree.topLevelItem(1).child(0)
    with qtbot.waitSignal(manager.external_visibility) as result:
        item.setCheckState(0, Qt.CheckState.Unchecked)
    assert result.args == ["gis-example", False]
    manager.tree.setCurrentItem(item)
    with qtbot.waitSignal(manager.external_removed) as result:
        manager._remove()
    assert result.args == ["gis-example"]
    assert not manager.external
