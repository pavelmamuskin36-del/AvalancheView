"""CRYOWRF display metadata and diagnostics; source NetCDF values stay unchanged."""

import logging
from dataclasses import dataclass, field

import numpy as np

SNOWPACK_VERTICAL_DIM = "snowpack_layers_stag"
SNOWPACK_LAYER_VARIABLES = frozenset(
    {
        "SNPACK_T",
        "SN_THICK",
        "SN_VOLI",
        "SN_VOLW",
        "SN_VOLV",
        "SN_RG",
        "SN_RB",
        "SN_DD",
        "SN_SP",
        "SN_CDOT",
        "SN_METAMO",
        "SN_DEPD",
        "SN_GRAINTYPE",
        "SN_MK",
    }
)
SNOWPACK_BULK_VARIABLES = frozenset(
    {
        "SNOW",
        "SNOWH",
        "SN_NLAYERS",
        "SNPACK_CON",
        "SNPACK_QSFX",
        "SNPACK_NSFX",
        "SNPACK_STAB",
        "SN_C_HEIGHT",
    }
)
SNOWPACK_DIAGNOSTICS = frozenset({"Snow Density", "Layer bulk density"})
SNOW_SUMMARY_VARIABLES = ("SNOWH", "SNOW", "TSK", "SN_NLAYERS")
logger = logging.getLogger(__name__)

# Russian title, English title, optional DISPLAY units (never a numeric conversion).
DISPLAY_METADATA = {
    "SNOWH": ("Высота снежного покрова", "Snow depth", None),
    "SNOW": ("Масса снежного покрова / water-equivalent mass", "Snow water-equivalent mass", None),
    "TSK": ("Температура поверхности", "Surface temperature", None),
    "SN_NLAYERS": ("Активных элементов SNOWPACK", "Active SNOWPACK elements", None),
    "SNPACK_T": ("Температура слоя SNOWPACK", "SNOWPACK layer temperature", None),
    "SN_THICK": ("Толщина элемента SNOWPACK", "SNOWPACK element thickness", None),
    "SN_VOLI": ("Объёмная доля льда", "Ice volume fraction", "1"),
    "SN_VOLW": ("Объёмная доля жидкой воды", "Liquid water volume fraction", "1"),
    "SN_VOLV": ("Объёмная доля воздуха", "Air volume fraction", "1"),
    "SN_RG": ("Размер зерна", "Grain size", None),
    "SN_RB": ("Размер связи между зёрнами", "Grain bond size", None),
    "SN_DD": ("Dendricity", "Dendricity", None),
    "SN_SP": ("Sphericity", "Sphericity", None),
    "SN_CDOT": (
        "SNOWPACK CDot / internal loading-rate variable",
        "SNOWPACK CDot / internal loading-rate variable",
        None,
    ),
    "SN_METAMO": ("Параметр метаморфизма SNOWPACK", "SNOWPACK metamorphism parameter", None),
    "SN_DEPD": (
        "Дата образования элемента (raw Julian date)",
        "Element creation date (raw Julian date)",
        None,
    ),
    "SN_GRAINTYPE": ("Код типа зерна SNOWPACK", "SNOWPACK grain type code", "code"),
    "SN_MK": (
        "Microstructure/history marker SNOWPACK",
        "Microstructure/history marker SNOWPACK",
        None,
    ),
    "SNPACK_STAB": (
        "Параметр атмосферной устойчивости SNOWPACK",
        "SNOWPACK atmospheric stability parameter",
        None,
    ),
    "SNPACK_CON": ("Диагностика SNPACK_CON", "SNPACK_CON diagnostic", None),
    "SNPACK_QSFX": ("Диагностика SNPACK_QSFX", "SNPACK_QSFX diagnostic", None),
    "SNPACK_NSFX": ("Диагностика SNPACK_NSFX", "SNPACK_NSFX diagnostic", None),
    "SN_C_HEIGHT": ("Диагностика SN_C_HEIGHT", "SN_C_HEIGHT diagnostic", None),
}


def is_snowpack_variable(info) -> bool:
    """Detect layer fields by dimension name, including unknown model diagnostics."""
    return SNOWPACK_VERTICAL_DIM in info.dimensions


def is_categorical_variable(name: str) -> bool:
    """Grain codes have no continuous physical metric or inferred code meanings."""
    return name == "SN_GRAINTYPE"


def snowpack_display_metadata(info, language="ru") -> tuple[str, str]:
    """Return a display title and units without changing source VariableInfo/attrs."""
    entry = DISPLAY_METADATA.get(info.name)
    if entry is None:
        return info.description or info.name, info.units
    return entry[0 if language == "ru" else 1], info.units if entry[2] is None else entry[2]


def normalize_layer_counts(values, capacity: int, warnings=None) -> np.ndarray:
    """Clamp counts to capacity; non-finite counts are inactive, never fabricated."""
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    safe = np.where(finite, values, 0)
    invalid = ~finite | (safe < 0) | (safe > capacity) | (safe != np.floor(safe))
    if np.any(invalid):
        message = f"SN_NLAYERS: invalid active count; clamped to 0..{capacity}, non-finite counts treated as inactive."
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
    return np.floor(np.clip(safe, 0, capacity)).astype(np.int64)


def active_layer_count(dataset, timestep, row, column, capacity=None, warnings=None) -> int:
    """Read the count for one history record and cell, under Dataset's NetCDF lock."""
    if capacity is None:
        capacity = dataset.dimensions[SNOWPACK_VERTICAL_DIM]
    if "SN_NLAYERS" not in dataset.variables:
        message = (
            "SN_NLAYERS is missing: active elements cannot be verified; showing stored levels."
        )
        logger.warning(message)
        if warnings is not None:
            warnings.append(message)
        return capacity
    value = dataset.point_value("SN_NLAYERS", timestep, row, column)
    return int(normalize_layer_counts(value, capacity, warnings))


def mask_inactive_layers(values, counts, selected_layer, capacity):
    """Return a masked copy for visualization; retain valid cells independently."""
    return np.where(normalize_layer_counts(counts, capacity) > selected_layer, values, np.nan)


def snowpack_depth(thickness):
    """Surface-first depths in metres, or None if thickness is unavailable/invalid."""
    if thickness is None:
        return None
    thickness = np.asarray(thickness, dtype=float)
    if thickness.ndim != 1 or not np.all(np.isfinite(thickness) & (thickness > 0)):
        return None
    with np.errstate(over="ignore", invalid="ignore"):
        bottom = np.cumsum(thickness)
    if not np.all(np.isfinite(bottom)):
        return None
    return bottom - thickness / 2, bottom


def snowpack_point_summary(dataset, timestep, row, column):
    """Read bulk properties for one cell, even when absent from visible map layers."""
    values = {}
    for name in SNOW_SUMMARY_VARIABLES:
        if name in dataset.variables:
            try:
                values[name] = dataset.point_value(name, timestep, row, column)
            except (ValueError, KeyError, IndexError, OSError) as exc:
                logger.warning("Snow summary %s unavailable: %s", name, exc)
    height = values.get("SNOWH", np.nan)
    if np.isfinite(height) and height > 0 and np.isfinite(values.get("SNOW", np.nan)):
        values["Mean apparent snow density"] = values["SNOW"] / values["SNOWH"]
    return values


@dataclass
class SnowpackProfile:
    """Detached, cell-sized snapshot safe to plot after a series source is evicted."""

    point: tuple[int, int]
    timestep: int
    timestamp: str
    count: int
    properties: dict
    metadata: dict
    summary: dict
    xy: tuple[float, float]
    geographic: bool
    center_depth: np.ndarray | None = None
    bottom_depth: np.ndarray | None = None
    warnings: list[str] = field(default_factory=list)


def snowpack_profile(dataset, timestep, row, column, language="ru") -> SnowpackProfile:
    """Load only vectors from one cell/time; each vector is already trimmed by Dataset."""
    from avalanche_view.data.dataset import NETCDF_LOCK

    with NETCDF_LOCK:
        warnings = []
        count = active_layer_count(dataset, timestep, row, column, warnings=warnings)
        properties, metadata = {}, {}
        for name, info in dataset.variables.items():
            if not info.plottable or not is_snowpack_variable(info):
                continue
            try:
                properties[name] = dataset.vertical_profile(name, timestep, row, column)
                metadata[name] = snowpack_display_metadata(info, language)
            except (ValueError, KeyError, IndexError, OSError) as exc:
                warnings.append(f"{name}: {exc}")
        for name in SNOW_SUMMARY_VARIABLES:
            if name in dataset.variables:
                metadata[name] = snowpack_display_metadata(dataset.variables[name], language)
        depth = snowpack_depth(properties.get("SN_THICK"))
        if depth is None and count:
            warnings.append(
                "SN_THICK missing or invalid: using element indices instead of physical depth."
            )
        if {"SN_VOLI", "SN_VOLW", "SN_VOLV"} <= properties.keys():
            total = properties["SN_VOLI"] + properties["SN_VOLW"] + properties["SN_VOLV"]
            bad = np.flatnonzero(~np.isfinite(total) | (np.abs(total - 1) > 0.02))
            if bad.size:
                warnings.append(
                    "SN_VOLI + SN_VOLW + SN_VOLV differs from 1 by > 0.02 or is missing: layers "
                    + ", ".join(map(str, bad))
                )
        if {"SN_THICK", "Layer bulk density"} <= properties.keys():
            thickness = properties["SN_THICK"]
            properties["Layer mass per unit area"] = np.where(
                np.isfinite(thickness) & (thickness > 0),
                thickness * properties["Layer bulk density"],
                np.nan,
            )
            metadata["Layer mass per unit area"] = ("Layer mass per unit area", "kg m-2")
        # coordinates() reads only coordinate planes, never a Time × layers × Y × X field.
        grid = dataset.coordinates(timestep)
        return SnowpackProfile(
            (row, column),
            timestep,
            dataset.timestamps[timestep],
            count,
            properties,
            metadata,
            snowpack_point_summary(dataset, timestep, row, column),
            (float(grid.x[row, column]), float(grid.y[row, column])),
            grid.geographic,
            *(depth if depth is not None else (None, None)),
            warnings,
        )
