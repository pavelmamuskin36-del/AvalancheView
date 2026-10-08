import json
from dataclasses import asdict, dataclass
from urllib.parse import quote, urlsplit

DETAILED_TERRAIN_ID = "terrain-global"


@dataclass(frozen=True)
class BasemapProvider:
    id: str
    name: str
    type: str = "raster"
    url: str = ""
    attribution: str = ""
    minZoom: int = 0
    maxZoom: int = 18
    requiresInternet: bool = True
    requiresApiKey: bool = False
    license: str = ""
    labels_url: str = ""
    encoding: str = "mapbox"
    cache_policy: str = "HTTP response headers; no bulk/offline download"

    def validate(self):
        if (
            not self.id
            or not self.name
            or self.type not in {"raster", "style", "raster-dem", "none"}
        ):
            raise ValueError("Укажите идентификатор, имя и допустимый тип провайдера")
        if self.type != "none" and urlsplit(self.url).scheme not in {"https", "http"}:
            raise ValueError("Укажите HTTP(S) URL тайлов или стиля")
        if self.type != "none" and not self.attribution:
            raise ValueError("Укажите attribution источника")
        if not 0 <= self.minZoom <= self.maxZoom <= 24:
            raise ValueError("Некорректные уровни масштаба")
        if self.requiresApiKey and "{key}" not in self.url:
            raise ValueError("Добавьте {key} в URL провайдера")

    def resolved(self, key=""):
        if self.requiresApiKey and not key:
            raise ValueError(f"Для «{self.name}» нужен API key: Настройки → Карты → Провайдеры")
        result = asdict(self)
        result["url"] = self.url.replace("{key}", quote(key, safe=""))
        return result


class BasemapRegistry:
    def __init__(self, settings=None):
        self.settings = settings
        self.providers = {p.id: p for p in defaults()}
        if settings:
            for record in json.loads(settings.value("maps/providers", "[]")):
                try:
                    self.register(BasemapProvider(**record))
                except (TypeError, ValueError):
                    continue

    def register(self, provider):
        provider.validate()
        self.providers[provider.id] = provider

    def save(self, provider, key=""):
        self.register(provider)
        if self.settings:
            self.settings.setValue(
                "maps/providers", json.dumps([asdict(p) for p in self.providers.values()])
            )
            # The key is user configuration, never part of source code or exported metadata.
            self.settings.setValue(f"maps/keys/{provider.id}", key)

    def get(self, provider_id):
        provider = self.providers[provider_id]
        key = self.settings.value(f"maps/keys/{provider_id}", "") if self.settings else ""
        return provider.resolved(key)


def defaults():
    nasa = (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
        "BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg"
    )
    osm = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    carto = osm + ' · © <a href="https://carto.com/attributions">CARTO</a>'
    return [
        BasemapProvider(
            DETAILED_TERRAIN_ID,
            "Реальный рельеф · Terrain Tiles",
            type="raster-dem",
            url="https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",
            encoding="terrarium",
            maxZoom=15,
            attribution='Terrain Tiles · USGS/SRTM · <a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">DEM sources & attribution</a>',
            license="https://github.com/tilezen/joerd/blob/master/docs/attribution.md",
        ),
        BasemapProvider(
            "satellite",
            "Спутник · NASA Blue Marble",
            url=nasa,
            maxZoom=8,
            attribution="NASA GIBS · Blue Marble",
            license="NASA Earthdata open imagery",
        ),
        BasemapProvider(
            "satellite-labels",
            "Спутник + подписи",
            url=nasa,
            maxZoom=8,
            labels_url="https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
            attribution="NASA GIBS · Blue Marble · " + carto,
            license="NASA Earthdata; CARTO basemap terms",
        ),
        BasemapProvider(
            "topographic",
            "Топографическая",
            url="https://tile.opentopomap.org/{z}/{x}/{y}.png",
            maxZoom=17,
            attribution=osm + " · SRTM · OpenTopoMap (CC-BY-SA)",
            license="https://opentopomap.org/about",
        ),
        BasemapProvider(
            "streets",
            "Улицы",
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            maxZoom=19,
            attribution=osm,
            license="https://operations.osmfoundation.org/policies/tiles/",
        ),
        BasemapProvider(
            "light",
            "Светлая",
            url="https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
            attribution=carto,
            license="https://carto.com/legal/",
        ),
        BasemapProvider(
            "dark",
            "Тёмная",
            url="https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            attribution=carto,
            license="https://carto.com/legal/",
        ),
        BasemapProvider("relief", "Рельеф", type="none", requiresInternet=False),
        BasemapProvider("none", "Без подложки / офлайн", type="none", requiresInternet=False),
    ]
