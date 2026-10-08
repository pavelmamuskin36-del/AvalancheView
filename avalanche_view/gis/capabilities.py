from dataclasses import dataclass

from avalanche_view.data.snowpack import is_categorical_variable, is_snowpack_variable
from avalanche_view.visualization.layers import RenderMode

WIND_PAIRS = {
    "Wind Speed 10m": ("U10", "V10"),
    "Wind Speed (UU/VV)": ("UU", "VV"),
    "Wind Speed (U/V)": ("U", "V"),
}
ELEVATIONS = {"HGT", "HGT_M", "DEM"}


def wind_variable(dataset, name):
    for diagnostic, pair in WIND_PAIRS.items():
        if (name == diagnostic or name in pair) and set(pair) <= dataset.variables.keys():
            return diagnostic
    return None


@dataclass(frozen=True)
class VariableCapabilities:
    canRender2D: bool = False
    canRender3D: bool = False
    canContour: bool = False
    canFill: bool = False
    canNativeGrid: bool = False
    canVector: bool = False
    canBarb: bool = False
    canStreamline: bool = False
    canVerticalProfile: bool = False
    canTimeSeries: bool = False
    canCrossSection: bool = False
    canDrapeOnTerrain: bool = False
    requiresVerticalLevel: bool = False
    requiresVectorPair: bool = False
    geometry_kind: str = "unsupported"
    vector_variable: str | None = None
    vector_reason: str = ""

    @classmethod
    def detect(cls, dataset, name):
        info = dataset.variables[name]
        spatial = info.plottable and bool(dataset.latitude_name and dataset.longitude_name)
        vertical = any(size > 1 for size in dataset.vertical_dimensions(name).values())
        wind = wind_variable(dataset, name)
        rotation_missing = (
            dataset.projection is not None
            and dataset.metadata.get("MAP_PROJ") != 6
            and not {"COSALPHA", "SINALPHA"} <= dataset.variables.keys()
        )
        vector = bool(wind) and spatial and not rotation_missing
        # Data dimensions alone do not imply that a volume renderer exists.
        return cls(
            canRender2D=spatial,
            canRender3D=spatial and name in ELEVATIONS,
            canContour=spatial and not is_categorical_variable(name),
            canFill=spatial,
            canNativeGrid=spatial,
            canVector=vector,
            canBarb=vector,
            canStreamline=vector,
            canVerticalProfile=spatial and vertical,
            canTimeSeries=info.plottable and dataset.time_count > 1,
            canCrossSection=spatial and vertical,
            canDrapeOnTerrain=spatial,
            requiresVerticalLevel=vertical,
            requiresVectorPair=bool(wind),
            geometry_kind="elevation"
            if name in ELEVATIONS
            else ("categorical" if is_categorical_variable(name)
                  else "snowpack_slice" if is_snowpack_variable(info)
                  else "atmospheric_slice" if vertical else "draped_field"),
            vector_variable=wind,
            vector_reason="Для поворота ветра нужны COSALPHA/SINALPHA." if wind and rotation_missing else "Режим ветра требует совместимой пары U/V.",
        )

    def reason(self, mode):
        if not self.canRender2D:
            return "Нет горизонтальной сетки с географическими координатами."
        if self.geometry_kind == "categorical" and mode != RenderMode.CATEGORIES:
            return "Grain type codes require discrete categories; interpolation is not supported."
        if mode in WIND_MODES and not self.canVector:
            return self.vector_reason or "Режим ветра требует совместимой пары U/V."
        if mode == RenderMode.HILLSHADE and self.geometry_kind != "elevation":
            return "Отмывка применима к высоте рельефа, а не к метеорологическому полю."
        return ""


WIND_MODES = {
    RenderMode.WIND_VECTORS,
    RenderMode.WIND_BARBS,
    RenderMode.STREAMLINES,
    RenderMode.WIND_SPEED_ARROWS,
    RenderMode.WIND_SPEED_BARBS,
}
