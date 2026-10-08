import logging
from pathlib import Path

from avalanche_view.config import RUNTIME_ROOT

logger = logging.getLogger(__name__)
try:
    import cartopy
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    cartopy.config["data_dir"] = RUNTIME_ROOT / "cartopy"
    CARTOPY_AVAILABLE = True
except (ImportError, OSError):
    ccrs = cfeature = None
    CARTOPY_AVAILABLE = False


def map_projection(dataset):
    if not CARTOPY_AVAILABLE:
        return None
    attributes = dataset.metadata
    try:
        projection = int(attributes.get("MAP_PROJ", 6))
        globe = ccrs.Globe(ellipse=None, semimajor_axis=6370000, semiminor_axis=6370000)
        longitude = float(attributes.get("STAND_LON", attributes.get("CEN_LON", 0)))
        latitude = float(attributes.get("MOAD_CEN_LAT", attributes.get("CEN_LAT", 0)))
        lat1 = float(attributes.get("TRUELAT1", latitude))
        lat2 = float(attributes.get("TRUELAT2", lat1))
        if projection == 1:
            return ccrs.LambertConformal(
                longitude, latitude, standard_parallels=(lat1, lat2), globe=globe
            )
        if projection == 2:
            return ccrs.Stereographic(
                central_longitude=longitude,
                central_latitude=90 if lat1 >= 0 else -90,
                true_scale_latitude=lat1,
                globe=globe,
            )
        if projection == 3:
            return ccrs.Mercator(longitude, latitude_true_scale=lat1, globe=globe)
    except (ValueError, TypeError, RuntimeError):
        logger.warning("Invalid WRF map projection; using PlateCarree", exc_info=True)
    return ccrs.PlateCarree()


def add_cached_boundaries(axes, color: str) -> None:
    if not CARTOPY_AVAILABLE:
        return
    data_dir = Path(cartopy.config["data_dir"]) / "shapefiles" / "natural_earth"
    for category, name, coastline in (
        ("physical", "coastline", True),
        ("cultural", "admin_0_boundary_lines_land", False),
    ):
        path = data_dir / category / f"ne_110m_{name}.shp"
        if path.exists():
            if coastline:
                axes.coastlines(resolution="110m", color=color, linewidth=0.6, zorder=100)
            else:
                axes.add_feature(
                    cfeature.BORDERS.with_scale("110m"), edgecolor=color, linewidth=0.6, zorder=100
                )


def download_boundaries() -> str:
    if not CARTOPY_AVAILABLE:
        raise RuntimeError("Install cartopy to use geographic boundaries")
    from cartopy.io import shapereader

    for category, name in (("physical", "coastline"), ("cultural", "admin_0_boundary_lines_land")):
        shapereader.natural_earth("110m", category, name)
    return "Map boundaries downloaded"
