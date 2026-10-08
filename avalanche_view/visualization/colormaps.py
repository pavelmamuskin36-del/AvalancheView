COLORMAPS = [
    "viridis",
    "plasma",
    "inferno",
    "magma",
    "cividis",
    "turbo",
    "coolwarm",
    "RdBu_r",
    "Blues",
    "YlGnBu",
    "terrain",
    "Greys",
    "Spectral_r",
    "tab20",
]


def default_colormap(variable: str) -> str:
    from avalanche_view.data.snowpack import is_categorical_variable

    if is_categorical_variable(variable):
        return "tab20"
    name = variable.lower()
    if "snow" in name:
        return "YlGnBu"
    if name == "t2" or "temperature" in name:
        return "coolwarm"
    if name == "hgt" or "elevation" in name:
        return "terrain"
    if "rain" in name or "precip" in name:
        return "Blues"
    return "viridis"
