from datetime import UTC, datetime

import numpy as np
import pytest
import xarray as xr

from avalanche_view.data.dataset import DatasetError
from avalanche_view.data.dataset_series import (
    Compatibility,
    DatasetCompatibilityChecker,
    DatasetSeries,
    FileEntry,
    VariableUnavailableError,
    analyse_files,
)
from avalanche_view.data.wrf_dataset import WRFDataset


def write_file(path, hours, *, domain=1, missing=(), nx=5, shift=0, projection=6):
    shape = (len(hours), 4, nx)
    lat, lon = np.meshgrid(np.linspace(40, 41, 4), np.linspace(10, 11, nx), indexing="ij")
    fields = {
        "Times": (
            ("Time",),
            np.array([f"2025-02-18_{hour:02d}:00:00" for hour in hours], dtype="S19"),
        ),
        "XLAT": (("south_north", "west_east"), lat),
        "XLONG": (("south_north", "west_east"), lon + shift),
    }
    for name, units, offset in (
        ("T2", "K", 270),
        ("SNOWH", "m", 0),
        ("U10", "m s-1", 1),
        ("V10", "m s-1", 2),
    ):
        if name not in missing:
            fields[name] = (
                ("Time", "south_north", "west_east"),
                np.broadcast_to(np.array(hours)[:, None, None] + offset, shape).copy(),
                {"units": units},
            )
    xr.Dataset(
        fields,
        attrs={
            "TITLE": "OUTPUT FROM WRF",
            "grid_id": domain,
            "MAP_PROJ": projection,
            "SIMULATION_START_DATE": "2025-02-18_00:00:00",
        },
    ).to_netcdf(path, engine="h5netcdf")
    return path


@pytest.fixture
def series_files(tmp_path):
    return [write_file(tmp_path / f"file_{hour}.nc", [hour]) for hour in (12, 13, 14)]


def test_series_sorting_times_switching_and_get_data(series_files):
    with DatasetSeries(list(reversed(series_files))) as series:
        assert [date.hour for date in series.times] == [12, 13, 14]
        assert series.time_count == 3
        assert series.get_dataset_for_time(1).path == series_files[1].resolve()
        np.testing.assert_array_equal(series.get_data("SNOWH", 2), 14)
        np.testing.assert_array_equal(series.get_data("SNOWH", series.times[0]), 12)
        assert series.coordinates(2).nearest(10, 40) == (0, 0)
        assert series.availability("SNOWH") == 3


def test_internal_multitime_and_filename_is_only_fallback(tmp_path):
    first = write_file(tmp_path / "met_em.d01.2025-02-18_23%3A00%3A00.nc", [14, 12])
    second = write_file(tmp_path / "other.nc", [13, 15])
    with DatasetSeries([first, second]) as series:
        assert [date.hour for date in series.times] == [12, 13, 14, 15]
        np.testing.assert_array_equal(series.time_series("SNOWH", 2, 3), [12, 13, 14, 15])


@pytest.mark.parametrize(
    "difference", [{"nx": 6}, {"shift": 0.01}, {"projection": 2}, {"domain": 2}]
)
def test_grid_domain_projection_compatibility(tmp_path, difference):
    first = FileEntry.inspect(write_file(tmp_path / "a.nc", [12]))
    other = FileEntry.inspect(write_file(tmp_path / "b.nc", [13], **difference))
    checker = DatasetCompatibilityChecker()
    assert checker.check(first, other).status == Compatibility.INCOMPATIBLE
    with pytest.raises(DatasetError):
        DatasetSeries(entries=[first, other])
    assert len(analyse_files([first.path, other.path]).groups) == 2


def test_missing_variable_and_derived_availability(tmp_path):
    paths = [
        write_file(tmp_path / "a.nc", [12]),
        write_file(tmp_path / "b.nc", [13], missing=("SNOWH", "V10")),
    ]
    with DatasetSeries(paths) as series:
        assert series.availability("SNOWH") == 1
        assert series.availability("Wind Speed 10m") == 1
        with pytest.raises(VariableUnavailableError, match="недоступна"):
            series.read("SNOWH", 1)
        values = series.time_series("SNOWH", 0, 0)
        assert values[0] == 12 and np.isnan(values[1])
        assert series.warnings


def test_variable_units_mismatch_is_reported(tmp_path):
    first = write_file(tmp_path / "a.nc", [12])
    other = tmp_path / "b.nc"
    with xr.open_dataset(first, engine="h5netcdf") as raw:
        raw = raw.load()
    raw["Times"] = xr.DataArray(np.array(["2025-02-18_13:00:00"], dtype="S19"), dims=("Time",))
    raw["SNOWH"].attrs["units"] = "cm"
    raw.to_netcdf(other, engine="h5netcdf")
    with DatasetSeries([first, other]) as series:
        assert series.availability("SNOWH") == 1
        with pytest.raises(VariableUnavailableError):
            series.read("SNOWH", 1)


def test_incompatible_dependency_disables_derived_field(tmp_path):
    first = write_file(tmp_path / "a.nc", [12])
    other = tmp_path / "b.nc"
    with xr.open_dataset(first, engine="h5netcdf") as source:
        raw = source.load()
    raw["Times"] = xr.DataArray(np.array(["2025-02-18_13:00:00"], dtype="S19"), dims=("Time",))
    raw["U10"].attrs["units"] = "cm s-1"
    raw.to_netcdf(other, engine="h5netcdf")
    with DatasetSeries([first, other]) as series:
        assert series.availability("Wind Speed 10m") == 1
        with pytest.raises(VariableUnavailableError):
            series.read("Wind Speed 10m", 1)


def test_cf_projection_mapping_must_match(tmp_path):
    paths = []
    for index, central_lon in enumerate((10, 20)):
        path = tmp_path / f"cf{index}.nc"
        xr.Dataset(
            {
                "field": (("time", "y", "x"), np.ones((1, 3, 4)), {"grid_mapping": "crs"}),
                "crs": (
                    (),
                    0,
                    {
                        "grid_mapping_name": "transverse_mercator",
                        "longitude_of_central_meridian": central_lon,
                    },
                ),
            },
            coords={"time": np.array([f"2025-02-18T{12 + index}:00"], dtype="datetime64[ns]")},
        ).to_netcdf(path, engine="h5netcdf")
        paths.append(path)
    assert len(analyse_files(paths).groups) == 2


def test_duplicate_timestamp_is_deterministic_and_reported(tmp_path):
    paths = [write_file(tmp_path / "b.nc", [12]), write_file(tmp_path / "a.nc", [12])]
    with DatasetSeries(paths) as series:
        assert series.time_count == 1
        assert series.get_dataset_for_time(0).path.name == "a.nc"
        assert any("Повтор времени" in warning for warning in series.warnings)


def test_temporal_gap_and_point_series_progress(tmp_path):
    paths = [write_file(tmp_path / f"{hour}.nc", [hour]) for hour in (12, 13, 14, 17, 18)]
    events = []
    with DatasetSeries(paths) as series:
        assert series.gaps == [3]
        assert series.expected_interval == 3600
        np.testing.assert_array_equal(
            series.time_series("SNOWH", 1, 2, progress=lambda *event: events.append(event)),
            [12, 13, 14, 17, 18],
        )
        assert events[-1][:2] == (5, 5)
        assert not series._cache


def test_lazy_loading_bounded_files_fields_and_close(series_files, monkeypatch):
    original = WRFDataset.read

    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata analysis must not read weather fields")

    monkeypatch.setattr(WRFDataset, "read", forbidden)
    series = DatasetSeries(series_files, max_open_files=2, cache_limit=4 * 5 * 8 * 2)
    assert not series._datasets and series.cache_bytes == 0
    monkeypatch.setattr(WRFDataset, "read", original)
    first = series.get_dataset_for_time(0)
    assert not first.raw["T2"].variable._in_memory
    for timestep in range(3):
        series.read("T2", timestep)
        assert len(series._datasets) <= 2
        assert series.cache_bytes <= series.cache_limit
    assert first._closed
    series.close()
    assert not series._datasets and series.cache_bytes == 0
    with pytest.raises(DatasetError, match="closed"):
        series.read("T2")


def test_corrupt_file_is_skipped_with_progress(series_files, tmp_path):
    broken = tmp_path / "bad.nc"
    broken.write_text("broken")
    events = []
    result = analyse_files([*series_files, broken], lambda *event: events.append(event))
    assert len(result.groups) == 1 and len(result.groups[0].entries) == 3
    assert len(result.errors) == 1 and "bad.nc" in result.errors[0]
    assert events[-1][:2] == (4, 4)
    with DatasetSeries([*series_files, broken]) as series:
        assert series.time_count == 3 and series.warnings


def test_cf_and_xtime_and_encoded_filename_dates(tmp_path):
    cf = tmp_path / "cf.nc"
    xr.Dataset(
        {"field": (("time", "y", "x"), np.ones((2, 3, 4)))},
        coords={"time": np.array(["2025-02-18T13:00", "2025-02-18T12:00"], dtype="datetime64[ns]")},
    ).to_netcdf(cf, engine="h5netcdf")
    with DatasetSeries([cf]) as series:
        assert [date.hour for date in series.times] == [12, 13]
    xtime = tmp_path / "xtime.nc"
    xr.Dataset(
        {
            "field": (("Time", "y", "x"), np.ones((2, 3, 4))),
            "XTIME": (("Time",), [0, 60], {"units": "minutes since 2025-02-18 12:00:00"}),
        }
    ).to_netcdf(xtime, engine="h5netcdf")
    with DatasetSeries([xtime]) as series:
        assert [date.hour for date in series.times] == [12, 13]
    fallback = tmp_path / "met_em.d01.2025-02-18_12%3A00%3A00.nc"
    xr.Dataset({"field": (("y", "x"), np.ones((3, 4)))}).to_netcdf(fallback, engine="h5netcdf")
    with DatasetSeries([fallback]) as series:
        assert series.times == [datetime(2025, 2, 18, 12, tzinfo=UTC)]


def test_metgrid_staggered_wind_levels(tmp_path):
    path = tmp_path / "met_em.nc"
    xr.Dataset(
        {
            "Times": (("Time",), np.array(["2025-02-18_12:00:00"], dtype="S19")),
            "UU": (
                ("Time", "num_metgrid_levels", "south_north", "west_east_stag"),
                np.full((1, 2, 3, 5), 3.0),
            ),
            "VV": (
                ("Time", "num_metgrid_levels", "south_north_stag", "west_east"),
                np.full((1, 2, 4, 4), 4.0),
            ),
            "COSALPHA": (("south_north", "west_east"), np.ones((3, 4))),
            "SINALPHA": (("south_north", "west_east"), np.zeros((3, 4))),
        },
        attrs={"FLAG_METGRID": 1},
    ).to_netcdf(path, engine="h5netcdf")
    with DatasetSeries([path]) as series:
        name = "Wind Speed (UU/VV)"
        assert series.vertical_dimensions(name) == {"num_metgrid_levels": 2}
        np.testing.assert_array_equal(series.read(name, level=1), 5)
        u, v = series.earth_relative_wind(0, 1, name)
        np.testing.assert_array_equal(u, 3)
        np.testing.assert_array_equal(v, 4)
