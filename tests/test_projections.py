from types import SimpleNamespace

import pytest

from avalanche_view.data.coordinates import wrf_crs
from avalanche_view.visualization.geography import CARTOPY_AVAILABLE, map_projection


@pytest.mark.parametrize("projection", [1, 2, 3, 6])
def test_wrf_projection_parameters(projection):
    attributes = {
        "MAP_PROJ": projection,
        "STAND_LON": 42.5,
        "CEN_LAT": 43.3,
        "TRUELAT1": 43.0,
        "TRUELAT2": 45.0,
    }
    crs = wrf_crs(attributes)
    assert crs is not None
    if CARTOPY_AVAILABLE:
        from avalanche_view.visualization.geography import ccrs

        display = map_projection(SimpleNamespace(metadata=attributes))
        x, y = display.transform_point(42.5, 43.3, ccrs.PlateCarree())
        longitude, latitude = ccrs.PlateCarree().transform_point(x, y, display)
        assert longitude == pytest.approx(42.5)
        assert latitude == pytest.approx(43.3)
        if projection == 2:
            assert display.proj4_params["lat_0"] == 90
            assert display.proj4_params["lon_0"] == 42.5


def test_unknown_or_invalid_projection():
    assert wrf_crs({"MAP_PROJ": 999}) is None
    assert wrf_crs({"MAP_PROJ": "not a number"}) is None
