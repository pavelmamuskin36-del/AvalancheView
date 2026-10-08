import numpy as np
import pytest
import xarray as xr

from avalanche_view.data.dataset import DatasetError
from avalanche_view.data.paths import native_netcdf_path
from avalanche_view.data.wrf_dataset import WRFDataset


def test_open_metadata(dataset):
    assert dataset.dimensions == {"Time": 6, "south_north": 12, "west_east": 16}
    assert dataset.time_count == 6
    assert "2026-02-01 03:00" in dataset.timestamps[1]
    assert {"T2", "SNOWH", "U10", "V10", "HGT", "Total Precipitation"} <= dataset.variables.keys()
    assert dataset.variables["T2"].units == "K"
    assert not dataset.variables["Times"].plottable
    assert not dataset.raw["T2"].variable._in_memory


def test_timestep_and_static_terrain(dataset):
    assert dataset.read("T2", 0).shape == (12, 16)
    assert not np.allclose(dataset.read("T2", 0), dataset.read("T2", 1))
    np.testing.assert_array_equal(dataset.read("HGT", 0), dataset.read("HGT", 5))
    assert not dataset.read("T2").flags.writeable


def test_coordinates_and_nearest(dataset):
    grid = dataset.coordinates()
    assert grid.geographic
    assert grid.x.shape == (12, 16)
    assert grid.nearest(grid.x[4, 7], grid.y[4, 7]) == (4, 7)
    assert grid.x.min() == pytest.approx(41.8)
    x, y = grid.metric_xy()
    assert np.isfinite(x).all() and np.isfinite(y).all()
    assert all(distance > 100 for distance in grid.spacing_m())


def test_point_and_series_are_same_as_slices(dataset):
    series = dataset.time_series("SNOWH", 3, 7)
    assert series.shape == (6,)
    for index, value in enumerate(series):
        assert value == dataset.read("SNOWH", index)[3, 7]
        assert value == dataset.point_value("SNOWH", index, 3, 7)
    assert np.unique(dataset.time_series("HGT", 3, 7)).size == 1


def test_missing_invalid_indices_and_closed(dataset):
    with pytest.raises(KeyError, match="not found"):
        dataset.read("missing")
    with pytest.raises(IndexError):
        dataset.read("T2", 6)
    with pytest.raises(IndexError):
        dataset.time_series("SNOWH", 999, 0)
    with pytest.raises(DatasetError, match="horizontal"):
        dataset.read("Times")
    dataset.close()
    with pytest.raises(DatasetError, match="closed"):
        dataset.read("T2")


def test_corrupt_file(tmp_path):
    path = tmp_path / "broken.nc"
    path.write_text("not a netCDF file")
    with pytest.raises(DatasetError, match="Unable to open"):
        WRFDataset(path)


def test_cache_is_bounded(demo_path):
    with WRFDataset(demo_path, cache_limit=12 * 16 * 8 * 2) as data:
        for i in range(6):
            data.read("T2", i)
            assert data.cache_bytes <= data.cache_limit
        assert len(data._cache) == 2
        assert data.read("T2", 5) is data.read("T2", 5)


def test_generic_cf_netcdf(tmp_path):
    path = tmp_path / "generic.nc"
    values = np.arange(24).reshape(2, 4, 3)
    xr.Dataset(
        {"temperature": (("time", "lon", "lat"), values, {"units": "K"})},
        coords={
            "time": np.array(["2024-01-01", "2024-01-02"], dtype="datetime64[ns]"),
            "lat": [40, 41, 42],
            "lon": [10, 11, 12, 13],
        },
    ).to_netcdf(path, engine="h5netcdf")
    with WRFDataset(path) as data:
        assert data.time_count == 2
        np.testing.assert_array_equal(data.read("temperature", 1), values[1].T)
        assert data.coordinates().nearest(11, 42) == (2, 1)
        np.testing.assert_array_equal(data.time_series("temperature", 2, 1), values[:, 1, 2])
        assert "Wind Speed 10m" not in data.variables


def test_no_coordinates_unknown_projection_nan(tmp_path):
    path = tmp_path / "grid.nc"
    values = np.full((3, 4), np.nan)
    values[1, 2] = 5
    xr.Dataset({"field": (("y", "x"), values)}, attrs={"MAP_PROJ": 999}).to_netcdf(
        path, engine="h5netcdf"
    )
    with WRFDataset(path) as data:
        assert not data.coordinates().geographic
        assert data.projection is None
        assert np.isnan(data.read("field")[0, 0])
        assert data.point_value("field", 0, 1, 2) == 5


def test_vertical_and_destaggered_fields(tmp_path):
    path = tmp_path / "vertical.nc"
    values = np.arange(2 * 3 * 4 * 6).reshape(2, 3, 4, 6).astype(float)
    xr.Dataset(
        {
            "U": (("Time", "bottom_top", "south_north", "west_east_stag"), values),
            "T2": (("Time", "south_north", "west_east"), np.ones((2, 4, 5))),
        },
    ).to_netcdf(path, engine="h5netcdf")
    with WRFDataset(path) as data:
        assert data.vertical_dimensions("U") == {"bottom_top": 3}
        expected = (values[1, 2, :, :-1] + values[1, 2, :, 1:]) / 2
        np.testing.assert_array_equal(data.read("U", 1, level=2), expected)
        assert data.point_value("U", 1, 2, 3, level=2) == expected[2, 3]
        np.testing.assert_array_equal(
            data.vertical_profile("U", 1, 2, 3),
            (values[1, :, 2, 3] + values[1, :, 2, 4]) / 2,
        )
        with pytest.raises(DatasetError, match="vertical dimension"):
            data.vertical_profile("T2", 1, 2, 3)
        np.testing.assert_array_equal(
            data.time_series("U", 2, 3, level=2), (values[:, 2, 2, 3] + values[:, 2, 2, 4]) / 2
        )


def test_wrf_character_timestamps(tmp_path):
    path = tmp_path / "times.nc"
    strings = ["2026-02-01_00:00:00", "2026-02-01_03:00:00"]
    characters = np.array([list(s) for s in strings], dtype="S1")
    xr.Dataset(
        {
            "Times": (("Time", "DateStrLen"), characters),
            "field": (("Time", "y", "x"), np.ones((2, 3, 4))),
        }
    ).to_netcdf(path, engine="h5netcdf")
    with WRFDataset(path) as data:
        assert data.timestamps == [s.replace("_", " ") + " UTC" for s in strings]


def test_classic_netcdf_backend_fallback(tmp_path):
    path = tmp_path / "classic.nc"
    values = np.arange(12, dtype=float).reshape(3, 4)
    xr.Dataset({"field": (("y", "x"), values)}).to_netcdf(
        native_netcdf_path(path.parent) / path.name, engine="netcdf4", format="NETCDF3_CLASSIC"
    )
    with WRFDataset(path) as data:
        np.testing.assert_array_equal(data.read("field"), values)
        assert not data.coordinates().geographic


def test_classic_unicode_filename(tmp_path):
    original = tmp_path / "original.nc"
    values = np.arange(12, dtype=float).reshape(3, 4)
    xr.Dataset({"field": (("y", "x"), values)}).to_netcdf(
        native_netcdf_path(original.parent) / original.name,
        engine="netcdf4",
        format="NETCDF3_CLASSIC",
    )
    renamed = tmp_path / "моделирование.nc"
    original.rename(renamed)
    with WRFDataset(renamed) as data:
        assert data.path == renamed
        np.testing.assert_array_equal(data.read("field"), values)
