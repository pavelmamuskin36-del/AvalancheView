import numpy as np
import pytest

from avalanche_view.data.derived import DerivedVariable, DerivedVariableRegistry
from avalanche_view.data.wrf_dataset import WRFDataset


def test_wind_speed(dataset):
    for index in (0, 3):
        expected = np.hypot(dataset.read("U10", index), dataset.read("V10", index))
        np.testing.assert_allclose(dataset.read("Wind Speed 10m", index), expected, rtol=1e-6)
    u, v = dataset.earth_relative_wind(2)
    np.testing.assert_allclose(np.hypot(u, v), dataset.read("Wind Speed 10m", 2), rtol=1e-6)


def test_precipitation_and_temperature(dataset):
    np.testing.assert_allclose(
        dataset.read("Total Precipitation", 4),
        dataset.read("RAINC", 4) + dataset.read("RAINNC", 4),
        rtol=1e-6,
    )
    np.testing.assert_allclose(
        dataset.read("Temperature 2m (°C)", 1), dataset.read("T2", 1) - 273.15, atol=3e-5
    )
    expected = dataset.time_series("RAINC", 2, 3) + dataset.time_series("RAINNC", 2, 3)
    np.testing.assert_allclose(
        dataset.time_series("Total Precipitation", 2, 3), expected, rtol=1e-6
    )


def test_registry_extension(demo_path):
    registry = DerivedVariableRegistry()
    entry = DerivedVariable(
        "Snow cm", ("SNOWH",), "cm", "Snow depth in cm", lambda snow: snow * 100
    )
    registry.register(entry)
    assert not registry.available({"T2"})
    with pytest.raises(ValueError, match="already registered"):
        registry.register(entry)
    with WRFDataset(demo_path, registry=registry) as data:
        np.testing.assert_allclose(data.read("Snow cm"), data.read("SNOWH") * 100, rtol=1e-6)
