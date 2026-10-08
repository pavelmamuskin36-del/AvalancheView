"""Small real NetCDF fixtures exercise Snowpack access through the existing readers."""

from dataclasses import replace
from urllib.request import urlopen

import numpy as np
import pytest
import xarray as xr
from matplotlib.figure import Figure
from PyQt6.QtCore import QSettings, Qt

from avalanche_view.data.dataset import Dataset
from avalanche_view.data.dataset_series import DatasetSeries
from avalanche_view.data.snowpack import (
    SNOWPACK_LAYER_VARIABLES,
    SNOWPACK_VERTICAL_DIM,
    snowpack_depth,
    snowpack_display_metadata,
    snowpack_point_summary,
    snowpack_profile,
)
from avalanche_view.data.wrf_dataset import WRFDataset
from avalanche_view.gis.capabilities import VariableCapabilities
from avalanche_view.gis.geometry import grid_geometry
from avalanche_view.gis.scientific import PreparedScene, colorize, scalar_descriptor
from avalanche_view.gis.terrain import TerrainService
from avalanche_view.gis.transport import LocalDataService
from avalanche_view.ui.dataset_browser import DatasetBrowser
from avalanche_view.ui.localization import translate_window
from avalanche_view.ui.main_window import MainWindow
from avalanche_view.ui.snowpack_profile_dialog import SnowpackProfileDialog
from avalanche_view.visualization.layers import Layer, RenderMode
from avalanche_view.visualization.renderer import RendererRegistry


def snowpack_fixture():
    """Surface-first 3 × 8 × 2 × 3 data with reordered layer and bulk dimensions."""
    t, z, y, x = "Time", SNOWPACK_VERTICAL_DIM, "south_north", "west_east"
    counts = np.array(
        [
            [[0, 0, 0], [0, 0, 0]],
            [[4, 2, 0], [1, 3, 8]],
            [[5, 2, 1], [0, 4, 8]],
        ],
        dtype=float,
    )
    lat, lon = np.meshgrid([42.0, 42.01], [43.0, 43.01, 43.02], indexing="ij")
    times = np.array([list(f"2025-02-18_{hour}:00:00") for hour in ("12", "13", "14")], dtype="S1")
    dims = (t, z, y, x)
    layer_index = np.broadcast_to(np.arange(8)[None, :, None, None], (3, 8, 2, 3))

    def layer(value, units=""):
        values = np.broadcast_to(value, (3, 8, 2, 3)).astype(float).copy()
        values[0] = 0
        return dims, values, {"units": units}

    data = xr.Dataset(
        {
            "XLAT": ((y, x), lat),
            "XLONG": ((y, x), lon),
            "Times": ((t, "DateStrLen"), times),
            "SN_NLAYERS": ((t, y, x), counts),
            "SNOW": ((t, y, x), np.ones((3, 2, 3)) * 80, {"units": "kg m-2"}),
            "SNOWH": ((t, y, x), np.ones((3, 2, 3)) * 0.4, {"units": "m"}),
            "TSK": ((t, y, x), np.ones((3, 2, 3)) * 267, {"units": "K"}),
            "SNPACK_T": layer(270.0 - layer_index, "K"),
            "SN_THICK": layer(0.01 * (layer_index + 1), "m"),
            "SN_VOLI": layer(0.218, "%"),
            "SN_VOLW": layer(0.02, "%"),
            "SN_VOLV": layer(0.762, "%"),
            "SN_RG": layer(0.8, "mm"),
            "SN_RB": layer(0.2, "mm"),
            "SN_DD": layer(0.3),
            "SN_SP": layer(0.4),
            "SN_CDOT": layer(0.001),
            "SN_METAMO": layer(0.5),
            "SN_GRAINTYPE": layer(np.where(layer_index % 2, 990, 12)),
            "SN_DEPD": layer(2460725.5),
            "SN_MK": layer(1),
            "SNPACK_STAB": ((t, y, x), np.ones((3, 2, 3))),
            "GHT": (
                (t, "bottom_top", y, x),
                np.broadcast_to(np.arange(3)[None, :, None, None] * 100.0, (3, 3, 2, 3)),
                {"units": "m"},
            ),
            "SN_QI_SUBLIM3D": ((t, "bottom_top", y, x), np.ones((3, 3, 2, 3))),
        }
    )
    data["SNPACK_T"] = data["SNPACK_T"].transpose(x, t, y, z)
    data["SN_NLAYERS"] = data["SN_NLAYERS"].transpose(x, y, t)
    return data


@pytest.fixture
def snow_path(tmp_path):
    path = tmp_path / "wrfout_d01_2025-02-18_12%3A00%3A00"
    snowpack_fixture().to_netcdf(path, engine="h5netcdf")
    return path


@pytest.fixture
def snow_service():
    service = LocalDataService(TerrainService())
    yield service
    service.close()


@pytest.mark.parametrize("reader", [Dataset, WRFDataset])
def test_open_dimensions_and_bulk_maps(snow_path, reader):
    with reader(snow_path) as data:
        assert data.time_count == 3
        assert data.vertical_dimensions("SNPACK_T") == {SNOWPACK_VERTICAL_DIM: 8}
        assert data.read("SNOWH", 1).shape == (2, 3)
        for name in ("SNOWH", "SNOW", "TSK", "SN_NLAYERS"):
            assert len(data.time_series(name, 0, 0)) == 3
        assert SNOWPACK_LAYER_VARIABLES <= data.variables.keys()
        assert data.vertical_dimensions("SN_QI_SUBLIM3D") == {"bottom_top": 3}
        np.testing.assert_allclose(data.read("SN_QI_SUBLIM3D", 0), 1)


def test_active_profiles_empty_record_and_lazy_slice(snow_path, monkeypatch):
    with WRFDataset(snow_path) as data:
        assert len(data.vertical_profile("SNPACK_T", 0, 0, 0)) == 0
        assert len(data.vertical_profile("SNPACK_T", 1, 0, 0)) == 4
        assert len(data.vertical_profile("SNPACK_T", 2, 0, 0)) == 5
        # No per-level point_value calls or full domain arrays during profile reading.
        original = data.point_value
        calls = []

        def point_value(name, *args, **kwargs):
            calls.append(name)
            return original(name, *args, **kwargs)

        monkeypatch.setattr(data, "point_value", point_value)
        np.testing.assert_allclose(data.vertical_profile("SNPACK_T", 1, 0, 0), [270, 269, 268, 267])
        assert calls == ["SN_NLAYERS"]
        assert not data.raw["SNPACK_T"].variable._in_memory


def test_map_point_time_masks_and_raw_preservation(snow_path):
    with WRFDataset(snow_path) as data:
        values = data.read("SNPACK_T", 1, 2)
        assert values[0, 0] == 268
        assert np.isnan(values[0, 1]) and np.isnan(values[0, 2])
        assert np.isnan(data.point_value("SNPACK_T", 1, 0, 1, 2))
        assert (
            data.raw["SNPACK_T"]
            .isel(Time=1, south_north=0, west_east=1, snowpack_layers_stag=2)
            .item()
            == 268
        )
        np.testing.assert_allclose(
            data.time_series("SNPACK_T", 0, 0, 4), [np.nan, np.nan, 266], equal_nan=True
        )
        assert np.isnan(data.read("SNPACK_T", 0)).all()
        assert not values.flags.writeable
        np.testing.assert_allclose(data.vertical_profile("GHT", 0, 0, 0), [0, 100, 200])


@pytest.mark.parametrize("count, expected", [(-5, 0), (99, 8), (np.nan, 0), (np.inf, 0), (3.7, 3)])
def test_invalid_counts_clamped_with_warning(tmp_path, count, expected, caplog):
    raw = snowpack_fixture()
    raw["SN_NLAYERS"].loc[dict(Time=1, south_north=0, west_east=0)] = count
    path = tmp_path / "invalid.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        assert len(data.vertical_profile("SNPACK_T", 1, 0, 0)) == expected
        assert "SN_NLAYERS" in caplog.text and "clamped" in caplog.text
        profile = snowpack_profile(data, 1, 0, 0)
        assert profile.warnings


def test_depth_fractions_density_mass_and_mean_density(snow_path):
    with WRFDataset(snow_path) as data:
        profile = snowpack_profile(data, 1, 0, 0)
        np.testing.assert_allclose(profile.center_depth, [0.005, 0.02, 0.045, 0.08])
        np.testing.assert_allclose(profile.bottom_depth, [0.01, 0.03, 0.06, 0.1])
        assert not profile.warnings
        assert data.variables["SN_VOLI"].units == "%"
        assert data.raw["SN_VOLI"].attrs["units"] == "%"
        assert snowpack_display_metadata(data.variables["SN_VOLI"])[1] == "1"
        np.testing.assert_allclose(profile.properties["SN_VOLI"], 0.218)
        np.testing.assert_allclose(profile.properties["Snow Density"], 917 * 0.218)
        np.testing.assert_allclose(
            profile.properties["Layer bulk density"], 917 * 0.218 + 1000 * 0.02
        )
        np.testing.assert_allclose(
            profile.properties["Layer mass per unit area"],
            np.arange(1, 5) * 0.01 * (917 * 0.218 + 1000 * 0.02),
        )
        assert snowpack_point_summary(data, 1, 0, 0)["Mean apparent snow density"] == pytest.approx(
            200
        )
        assert "917 * SN_VOLI + 1000 * SN_VOLW" in data.variables["Layer bulk density"].description
        np.testing.assert_allclose(profile.properties["SN_DEPD"], 2460725.5)
        assert "атмосферной" in snowpack_display_metadata(data.variables["SNPACK_STAB"])[0]
        assert "strain" not in snowpack_display_metadata(data.variables["SN_CDOT"])[0].lower()


@pytest.mark.parametrize("thickness", [None, [-0.1, 0.2], [0.1, np.nan], [0, 0.2], [1e308, 1e308]])
def test_invalid_depth_fallback(thickness):
    assert snowpack_depth(thickness) is None


def test_missing_count_thickness_and_fraction_warnings(tmp_path):
    raw = snowpack_fixture().drop_vars(["SN_NLAYERS", "SN_THICK"])
    raw["SN_VOLV"][:] = 0.6
    path = tmp_path / "missing.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        profile = snowpack_profile(data, 1, 0, 0)
        assert profile.count == 8 and profile.center_depth is None
        assert any("SN_NLAYERS is missing" in warning for warning in profile.warnings)
        assert any("SN_THICK" in warning for warning in profile.warnings)
        assert any("0.02" in warning for warning in profile.warnings)


def test_static_layer_time_dependent_mask_and_cache(tmp_path):
    raw = snowpack_fixture()
    raw["static_snow"] = raw["SN_RG"].isel(Time=1, drop=True)
    path = tmp_path / "static.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        assert np.isnan(data.read("static_snow", 0)).all()
        assert data.read("static_snow", 1)[0, 0] == pytest.approx(0.8)
        np.testing.assert_allclose(
            data.time_series("static_snow", 0, 0), [np.nan, 0.8, 0.8], equal_nan=True
        )


def test_singleton_snowpack_dimension_and_source_density_preserved(tmp_path):
    raw = snowpack_fixture().isel(snowpack_layers_stag=slice(0, 1))
    raw["SN_NLAYERS"] = raw["SN_NLAYERS"].clip(max=1)
    raw["Snow Density"] = xr.full_like(raw["SN_VOLI"], 333)
    path = tmp_path / "one-layer.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        assert data.vertical_dimensions("SNPACK_T") == {SNOWPACK_VERTICAL_DIM: 1}
        assert len(data.vertical_profile("SNPACK_T", 1, 0, 0)) == 1
        assert not data.variables["Snow Density"].derived
        assert data.point_value("Snow Density", 1, 0, 0) == 333


def test_zero_snow_height_has_no_apparent_density(tmp_path):
    raw = snowpack_fixture()
    raw["SNOWH"][:] = 0
    path = tmp_path / "no-snow.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        assert "Mean apparent snow density" not in snowpack_point_summary(data, 1, 0, 0)


def test_browser_language_preserves_coordinate_dimension_sizes(qtbot, tmp_path):
    raw = snowpack_fixture().assign_coords(west_east=np.arange(3), south_north=np.arange(2))
    path = tmp_path / "coordinates.nc"
    raw.to_netcdf(path, engine="h5netcdf")
    with Dataset(path) as data:
        browser = DatasetBrowser()
        qtbot.addWidget(browser)
        browser.set_dataset(data)
        browser.set_language("en")
        dimensions = browser.tree.topLevelItem(0)
        assert {
            dimensions.child(index).text(0): int(dimensions.child(index).text(1))
            for index in range(dimensions.childCount())
        } == data.dimensions


def test_series_profiles_use_local_time_and_masks(snow_path, tmp_path):
    raw = snowpack_fixture()
    paths = []
    for index in range(3):
        path = tmp_path / f"record{index}.nc"
        raw.isel(Time=slice(index, index + 1)).to_netcdf(path, engine="h5netcdf")
        paths.append(path)
    with DatasetSeries(list(reversed(paths)), max_open_files=1) as data:
        assert len(data.vertical_profile("SNPACK_T", 1, 0, 0)) == 4
        assert data.snowpack_profile(2, 0, 0).count == 5
        np.testing.assert_allclose(
            data.time_series("SNPACK_T", 0, 0, 4), [np.nan, np.nan, 266], equal_nan=True
        )
        assert data.snowpack_profile(0, 0, 0).count == 0


def test_discrete_grain_codes_gis_and_legacy(snow_path, snow_service):
    service = snow_service
    with WRFDataset(snow_path) as data:
        layer = Layer("SN_GRAINTYPE", mode=RenderMode.CONTOUR_LINES, smooth=True, colormap="turbo")
        assert (
            layer.mode == RenderMode.CATEGORIES and not layer.smooth and layer.colormap == "tab20"
        )
        values = data.read("SN_GRAINTYPE", 1)
        grid = data.coordinates(1)
        descriptor = scalar_descriptor(service, grid, grid_geometry(data, 1), values, layer)
        assert "contours" not in descriptor and not descriptor["smooth"]
        assert descriptor["categories"] == [
            {"code": 12, "label": "Grain type code 12", "color": descriptor["palette"][0]}
        ]
        with urlopen(descriptor["values"]) as response:
            np.testing.assert_allclose(
                np.frombuffer(response.read(), "<f8").reshape(values.shape), values, equal_nan=True
            )
        colors, *_ = colorize(np.array([[12.0, 990.0, np.nan]]), layer)
        assert colors[0, 2, 3] == 0
        assert not np.array_equal(colors[0, 0], colors[0, 1])
        capabilities = VariableCapabilities.detect(data, "SN_GRAINTYPE")
        assert not capabilities.canContour and capabilities.reason(RenderMode.CONTOUR_LINES)
        artist = RendererRegistry().render(
            Figure().subplots(), grid, data.read("SN_GRAINTYPE", 1, 1), layer, 1
        )
        assert set(artist.category_codes) == {990}
        scene = PreparedScene(data, [layer], 1, service)
        assert not scene.scene["warnings"]


def test_snowpack_dialog_empty_depth_table_and_codes(qtbot, snow_path):
    with WRFDataset(snow_path) as data:
        empty = SnowpackProfileDialog(snowpack_profile(data, 0, 0, 0))
        qtbot.addWidget(empty)
        assert empty.table.rowCount() == 0 and not empty.axes.lines
        assert "отсутствует" in empty.status.text()
        profile = snowpack_profile(data, 1, 0, 0)
        dialog = SnowpackProfileDialog(profile)
        qtbot.addWidget(dialog)
        assert dialog.table.rowCount() == 4 and dialog.axes.yaxis_inverted()
        np.testing.assert_allclose(dialog.axes.lines[0].get_ydata(), profile.center_depth)
        dialog.variable.setCurrentIndex(dialog.variable.findData("SN_GRAINTYPE"))
        assert not dialog.axes.lines and len(dialog.axes.collections) == 1
        assert dialog.table.item(1, 14).text() == "990"
        assert "code 990" in dialog.table.item(1, 14).toolTip()
        fallback = SnowpackProfileDialog(
            replace(profile, center_depth=None, bottom_depth=None), language="en"
        )
        qtbot.addWidget(fallback)
        assert fallback.axes.get_ylabel() == "Element index" and fallback.axes.yaxis_inverted()


def test_main_window_snow_summary_timeline_profile_and_series(qtbot, snow_path, tmp_path):
    settings = QSettings(str(tmp_path / "snow-ui.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings, renderer="legacy")
    qtbot.addWidget(window)
    window.show()
    errors = []
    window._show_error = lambda *args: errors.append(args)
    window._loaded(WRFDataset(snow_path))
    window.add_layer("SNOWH")
    qtbot.waitUntil(lambda: not window._jobs, timeout=15000)
    grid = window.dataset.coordinates()
    window.inspect_point(float(grid.x[0, 0]), float(grid.y[0, 0]))
    qtbot.waitUntil(lambda: window.inspector.snow_table.rowCount() == 5, timeout=15000)
    assert not window.inspector.snow_button.isEnabled()
    assert window.inspector.table.rowCount() == 1  # Existing visible layer values preserved.
    window.set_timestep(1)
    qtbot.waitUntil(lambda: window.inspector.snow_button.isEnabled(), timeout=15000)
    assert window.inspector.snow_table.item(3, 1).text() == "4"
    window.inspector.snow_button.click()
    qtbot.waitUntil(lambda: len(window._dialogs) == 1, timeout=15000)
    profile = window._dialogs[0]
    assert isinstance(profile, SnowpackProfileDialog) and profile.table.rowCount() == 4
    window.show_time_series("SNOWH")
    qtbot.waitUntil(lambda: len(window._dialogs) == 2, timeout=15000)
    np.testing.assert_allclose(window._dialogs[1].canvas.figure.axes[0].lines[0].get_ydata(), 0.4)
    window.add_layer("SNPACK_T")
    assert window.properties.vertical_level.prefix() == "Snowpack layer "
    assert "SN_NLAYERS" in window.properties.vertical_level.toolTip()
    window.show_vertical_profile("SNPACK_T")
    qtbot.waitUntil(lambda: len(window._dialogs) == 3, timeout=15000)
    assert isinstance(window._dialogs[-1], SnowpackProfileDialog)
    translate_window(window, "en")
    assert window.inspector.snow_button.text() == "SNOWPACK profile"
    window.browser.search.setText("ice volume fraction")
    matches = window.browser.tree.findItems("SN_VOLI", Qt.MatchFlag.MatchRecursive)
    assert matches and not matches[0].isHidden()
    qtbot.waitUntil(lambda: not window._jobs and window._render_job is None, timeout=15000)
    assert not errors
    window.close()
