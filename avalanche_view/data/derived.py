from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import xarray as xr


@dataclass(frozen=True)
class DerivedVariable:
    name: str
    dependencies: tuple[str, ...]
    units: str
    description: str
    compute: Callable[..., xr.DataArray]


class DerivedVariableRegistry:
    """Register diagnostic expressions without depending on the UI."""

    def __init__(self) -> None:
        self._entries: dict[str, DerivedVariable] = {}

    def register(self, variable: DerivedVariable) -> None:
        if variable.name in self._entries:
            raise ValueError(f"Derived variable already registered: {variable.name}")
        self._entries[variable.name] = variable

    def available(self, raw_names: set[str]) -> list[DerivedVariable]:
        return [v for v in self._entries.values() if set(v.dependencies) <= raw_names]

    def get(self, name: str) -> DerivedVariable:
        return self._entries[name]

    def __contains__(self, name: str) -> bool:
        return name in self._entries


def default_registry() -> DerivedVariableRegistry:
    registry = DerivedVariableRegistry()
    registry.register(
        DerivedVariable(
            "Wind Speed 10m",
            ("U10", "V10"),
            "m s-1",
            "10 m wind speed",
            lambda u, v: np.hypot(u, v),
        )
    )
    for name, u, v in (("Wind Speed (UU/VV)", "UU", "VV"), ("Wind Speed (U/V)", "U", "V")):
        registry.register(
            DerivedVariable(
                name,
                (u, v),
                "m s-1",
                "Wind speed at selected vertical level",
                lambda a, b: np.hypot(a, b),
            )
        )
    registry.register(
        DerivedVariable(
            "Total Precipitation",
            ("RAINC", "RAINNC"),
            "mm",
            "Accumulated convective + non-convective precipitation",
            lambda a, b: a + b,
        )
    )
    registry.register(
        DerivedVariable(
            "Temperature 2m (°C)",
            ("T2",),
            "°C",
            "2 m air temperature in Celsius",
            lambda temperature: temperature - 273.15,
        )
    )
    registry.register(DerivedVariable(
        "Snow Density", ("SN_VOLI",), "kg m-3",
        "Ice contribution to layer density: 917 * SN_VOLI; excludes liquid water.",
        lambda ice: 917.0 * ice,
    ))
    registry.register(DerivedVariable(
        "Layer bulk density", ("SN_VOLI", "SN_VOLW"), "kg m-3",
        "Layer bulk density diagnostic: 917 * SN_VOLI + 1000 * SN_VOLW.",
        lambda ice, water: 917.0 * ice + 1000.0 * water,
    ))
    return registry
