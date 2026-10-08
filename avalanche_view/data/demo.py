from pathlib import Path

import numpy as np
import xarray as xr


def create_demo_dataset(path: str | Path, timesteps: int = 12, ny: int = 64, nx: int = 80) -> Path:
    """Deterministic, WRF-shaped synthetic mountain weather; not a forecast."""
    if timesteps < 1 or ny < 2 or nx < 2:
        raise ValueError("Use at least 1 timestep and a 2×2 grid")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    longitude, latitude = np.meshgrid(np.linspace(41.8, 43.1, nx), np.linspace(42.8, 43.7, ny))
    xx, yy = np.meshgrid(np.linspace(-2, 2, nx), np.linspace(-2, 2, ny))
    terrain = (
        650
        + 3000 * np.exp(-((xx + 0.4) ** 2 / 0.35 + (yy - 0.2) ** 2 / 1.6))
        + 2100 * np.exp(-((xx - 0.7) ** 2 / 0.65 + (yy + 0.5) ** 2 / 0.8))
        + 200 * np.sin(xx * 5 + yy * 3) ** 2
    )
    t = np.arange(timesteps)[:, None, None]
    temperature = 280.5 - 0.0065 * terrain + 2.8 * np.sin(t * np.pi / 6) + 0.5 * np.cos(xx * 2)
    snowfall = np.maximum(0, (terrain - 1000) / 1800) + 0.025 * t + 0.08 * np.sin(xx * 3 + t / 3)
    u = 7 + 4 * np.cos(yy * 1.5 + t / 4) + 0.001 * terrain
    v = 3 + 4 * np.sin(xx * 1.4 - t / 5) + np.zeros_like(terrain)
    precipitation = 0.8 + 2.2 * np.exp(-((xx - 0.3) ** 2 + yy**2))
    times = np.datetime64("2026-02-01T00:00") + np.arange(timesteps) * np.timedelta64(3, "h")
    dimensions = ("Time", "south_north", "west_east")
    fields = {
        "T2": (temperature, "K", "2 m air temperature"),
        "SNOWH": (np.maximum(snowfall, 0), "m", "Snow depth"),
        "U10": (u, "m s-1", "10 m eastward wind"),
        "V10": (v, "m s-1", "10 m northward wind"),
        "RAINC": (t * precipitation * 0.25, "mm", "Accumulated convective precipitation"),
        "RAINNC": (t * precipitation * 0.75, "mm", "Accumulated non-convective precipitation"),
        "PSFC": (101325 * np.exp(-terrain / 8500) + t * 4, "Pa", "Surface pressure"),
        "Q2": (
            0.002 * np.exp(-terrain / 5000) + t * 0.00001,
            "kg kg-1",
            "2 m water vapour mixing ratio",
        ),
    }
    data_vars = {
        name: (
            dimensions,
            np.broadcast_to(values, (timesteps, ny, nx)).astype("float32"),
            {"units": units, "description": description},
        )
        for name, (values, units, description) in fields.items()
    }
    for name, values, units, description in (
        ("XLAT", latitude, "degrees_north", "Latitude"),
        ("XLONG", longitude, "degrees_east", "Longitude"),
        ("HGT", terrain, "m", "Terrain elevation"),
        ("COSALPHA", np.ones_like(terrain), "1", "Wind rotation cosine"),
        ("SINALPHA", np.zeros_like(terrain), "1", "Wind rotation sine"),
    ):
        data_vars[name] = (
            ("south_north", "west_east"),
            values.astype("float32"),
            {"units": units, "description": description},
        )
    strings = [np.datetime_as_string(value, unit="s").replace("T", "_") for value in times]
    data_vars["Times"] = (("Time",), np.asarray(strings, dtype="S19"))
    dataset = xr.Dataset(
        data_vars=data_vars,
        coords={"Time": times, "south_north": np.arange(ny), "west_east": np.arange(nx)},
        attrs={
            "TITLE": "AvalancheView • synthetic Caucasus mountain weather",
            "SIMULATION_START_DATE": strings[0],
            "MAP_PROJ": 6,
            "CEN_LAT": 43.25,
            "CEN_LON": 42.45,
            "STAND_LON": 42.45,
            "TRUELAT1": 43.25,
            "TRUELAT2": 43.25,
            "SYNTHETIC_DATA": "true",
        },
    )
    encoding = {name: {"zlib": True, "complevel": 3} for name in fields}
    try:
        dataset.to_netcdf(path, engine="h5netcdf", encoding=encoding)
    finally:
        dataset.close()
    return path
